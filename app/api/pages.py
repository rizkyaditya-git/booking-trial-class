"""Three server-rendered views, using the same service as the JSON API."""

from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.api.bookings import BookingId, ClassId, blocked, committed
from app.schemas import bookings as schema
from app.services import bookings_svc as svc

templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
templates.env.filters["class_time"] = lambda value: datetime.strptime(
    value, "%Y-%m-%dT%H:%M:%S.%fZ"
).strftime("%a, %d %b %Y · %H:%M UTC")


def page_query(request: Request):
    allowed = (
        {"demoParentId"}
        if request.method == "GET" and "/bookings/" in request.url.path
        else set()
    )
    if set(request.query_params) - allowed or any(
        len(request.query_params.getlist(key)) > 1 for key in request.query_params
    ):
        raise svc.BookingError("validation_error")


router = APIRouter(prefix="/v1/ui", dependencies=[Depends(page_query)])
ParentQuery = Annotated[schema.TextId, Query(alias="demoParentId")]


def new_context(request, parent_id=None, values=None):
    path = request.app.state.db_path
    students = svc.list_students(path, parent_id) if parent_id else []
    return {
        "parents": svc.list_parents(path),
        "students": students,
        "classes": svc.list_classes(path),
        "parent_id": parent_id,
        "values": values or {},
        "key": (values or {}).get("idempotencyKey", str(uuid4())),
    }


def status_context(request, parent_id, booking_id, values=None):
    path = request.app.state.db_path
    booking = svc.get_booking(path, parent_id, booking_id)
    student = next(
        row
        for row in svc.list_students(path, parent_id)
        if row["id"] == booking["student_id"]
    )
    trial_class = svc.get_class(path, booking["trial_class_id"])
    attempt = svc.get_booking_attempt(path, parent_id, booking_id)
    existing_id = None
    if booking["status_reason"] == "duplicate_booking":
        existing_id = next(
            row["booking_id"]
            for row in svc.get_roster(path, trial_class["id"])
            if row["student_id"] == student["id"]
        )
    # Stable across a pending-page refresh; the two outcome buttons share one request.
    key = (values or {}).get(
        "idempotencyKey", f"payment-{booking_id}-{booking['created_at']}"
    )
    return {
        "booking": booking,
        "student": student,
        "trial_class": trial_class,
        "attempt": attempt,
        "parent_id": parent_id,
        "key": key,
        "existing_id": existing_id,
    }


def render_problem(request, code, status, detail, context):
    values = getattr(request.state, "form_values", {})
    error = {"code": code, "detail": detail, **context}
    template, data = "base.html", {"error": error}
    if status < 500 and code not in (
        "ownership_violation",
        "not_found",
        "method_not_allowed",
    ):
        raw_parent = values.get(
            "demoParentId", request.query_params.get("demoParentId")
        )
        try:
            parent_id = schema.decimal_id(raw_parent)
            if parent_id <= 0:
                parent_id = None
        except (ValueError, TypeError):
            parent_id = None
        try:
            if request.url.path in ("/v1/ui/bookings", "/v1/ui/bookings/new"):
                data = new_context(request, parent_id, values)
                template = "book_trial.html"
            elif parent_id and "bookingId" in request.path_params:
                data = status_context(
                    request,
                    parent_id,
                    schema.decimal_id(request.path_params["bookingId"]),
                    values,
                )
                template = "booking_status.html"
        except (svc.BookingError, ValueError, TypeError):
            template, data = "base.html", {}
    data["error"] = error
    data["fallback_retry"] = template == "base.html"
    data["retry_values"] = {
        key: value
        for key, value in values.items()
        if key
        in {
            "demoParentId",
            "studentId",
            "trialClassId",
            "idempotencyKey",
            "requestedOutcome",
        }
    }
    return templates.TemplateResponse(
        request=request, name=template, context=data, status_code=status
    )


@router.get("/bookings/new", status_code=200, response_class=HTMLResponse)
def new_booking(
    request: Request,
    parent_id: Annotated[schema.TextId | None, Query(alias="demoParentId")] = None,
):
    return templates.TemplateResponse(
        request=request, name="book_trial.html", context=new_context(request, parent_id)
    )


@router.post("/bookings", status_code=303, response_class=HTMLResponse)
def submit_booking(request: Request, form: Annotated[schema.BookingForm, Form()]):
    request.state.form_values = form.model_dump(by_alias=True)
    record, replayed = svc.create_booking(
        request.app.state.db_path,
        form.demo_parent_id,
        form.student_id,
        form.trial_class_id,
        form.idempotency_key,
    )
    committed(request, record, replayed, "booking_created")
    return RedirectResponse(
        f"/v1/ui/bookings/{record['id']}?demoParentId={form.demo_parent_id}",
        status_code=303,
    )


@router.get("/bookings/{bookingId}", status_code=200, response_class=HTMLResponse)
def booking_status(request: Request, booking_id: BookingId, parent_id: ParentQuery):
    return templates.TemplateResponse(
        request=request,
        name="booking_status.html",
        context=status_context(request, parent_id, booking_id),
    )


@router.post(
    "/bookings/{bookingId}/payment-attempts",
    status_code=303,
    response_class=HTMLResponse,
)
def submit_payment(
    request: Request, booking_id: BookingId, form: Annotated[schema.PaymentForm, Form()]
):
    request.state.form_values = form.model_dump(by_alias=True)
    record, replayed = svc.complete_payment(
        request.app.state.db_path,
        form.demo_parent_id,
        booking_id,
        form.requested_outcome,
        form.idempotency_key,
    )
    committed(request, record, replayed, "payment_completed")
    blocked(record)
    return RedirectResponse(
        f"/v1/ui/bookings/{booking_id}?demoParentId={form.demo_parent_id}",
        status_code=303,
    )


@router.get(
    "/trial-classes/{trialClassId}/roster", status_code=200, response_class=HTMLResponse
)
def class_roster(request: Request, trial_class_id: ClassId):
    path = request.app.state.db_path
    roster = svc.get_roster(path, trial_class_id)
    return templates.TemplateResponse(
        request=request,
        name="roster.html",
        context={"trial_class": svc.get_class(path, trial_class_id), "roster": roster},
    )
