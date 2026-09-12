"""JSON transport; the shared service owns all booking decisions."""

from http import HTTPStatus
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Path, Request, Response

from app.db.connection import connect
from app.schemas import bookings as schema
from app.services import bookings_svc as svc


def errors(*statuses):
    return {
        status: {
            "description": HTTPStatus(status).phrase,
            "content": {
                "application/problem+json": {
                    "schema": schema.Problem.model_json_schema()
                }
            },
        }
        for status in {*statuses, 500, 503}
    }


def no_query(request: Request):
    if request.query_params:
        raise svc.BookingError("validation_error")


router = APIRouter(prefix="/v1", dependencies=[Depends(no_query)])
ParentId = Annotated[schema.TextId, Header(alias="X-Demo-Parent-Id")]
Key = Annotated[schema.RequestKey, Header(alias="Idempotency-Key")]
BookingId = Annotated[schema.TextId, Path(alias="bookingId")]
ClassId = Annotated[schema.TextId, Path(alias="trialClassId")]
AttemptId = Annotated[schema.TextId, Path(alias="paymentAttemptId")]


def committed(request, record, replayed, event):
    details = {"event": event, "replayed": replayed}
    if event == "booking_created":
        details.update(bookingId=record["id"], outcome=record["status"])
    else:
        details.update(
            bookingId=record["booking_id"],
            paymentAttemptId=record["id"],
            outcome=record["outcome"],
            reason=record["reason"],
        )
    request.state.committed = details


def blocked(attempt):
    if attempt["outcome"] == "blocked":
        raise svc.BookingError(
            attempt["reason"],
            booking_id=attempt["booking_id"],
            payment_attempt_id=attempt["id"],
            booking_status=attempt["booking_status"],
        )


@router.get(
    "/health",
    status_code=200,
    response_model=schema.Envelope[schema.Health],
    responses=errors(422),
)
def health(request: Request):
    with connect(request.app.state.db_path, readonly=True) as db:
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if (
            not {"parents", "students", "trial_classes", "bookings", "payment_attempts"}
            <= tables
        ):
            raise svc.BookingError("database_unavailable")
    return {"data": [{"status": "ok"}], "meta": {}}


@router.get(
    "/parents",
    status_code=200,
    response_model=schema.Envelope[schema.Parent],
    responses=errors(422),
)
def read_parents(request: Request):
    return {"data": svc.list_parents(request.app.state.db_path), "meta": {}}


@router.get(
    "/students",
    status_code=200,
    response_model=schema.Envelope[schema.Student],
    responses=errors(404, 422),
)
def read_students(request: Request, parent_id: ParentId):
    return {"data": svc.list_students(request.app.state.db_path, parent_id), "meta": {}}


@router.get(
    "/trial-classes",
    status_code=200,
    response_model=schema.Envelope[schema.TrialClass],
    responses=errors(422),
)
def read_trial_classes(request: Request):
    return {"data": svc.list_classes(request.app.state.db_path), "meta": {}}


@router.post(
    "/bookings",
    status_code=201,
    response_model=schema.Envelope[schema.Booking],
    responses={
        **errors(403, 404, 409, 415, 422),
        200: {"model": schema.Envelope[schema.Booking], "description": "Replay"},
    },
)
def create_booking(
    request: Request,
    response: Response,
    body: schema.CreateBooking,
    parent_id: ParentId,
    key: Key,
):
    record, replayed = svc.create_booking(
        request.app.state.db_path, parent_id, body.student_id, body.trial_class_id, key
    )
    committed(request, record, replayed, "booking_created")
    response.status_code = 200 if replayed else 201
    response.headers["Location"] = f"/v1/bookings/{record['id']}"
    return {"data": [record], "meta": {"replayed": replayed}}


@router.get(
    "/bookings/{bookingId}",
    status_code=200,
    response_model=schema.Envelope[schema.Booking],
    responses=errors(403, 404, 422),
)
def read_booking(request: Request, booking_id: BookingId, parent_id: ParentId):
    return {
        "data": [svc.get_booking(request.app.state.db_path, parent_id, booking_id)],
        "meta": {},
    }


@router.post(
    "/bookings/{bookingId}/payment-attempts",
    status_code=201,
    response_model=schema.Envelope[schema.PaymentAttempt],
    responses={
        **errors(403, 404, 409, 415, 422),
        200: {"model": schema.Envelope[schema.PaymentAttempt], "description": "Replay"},
    },
)
def complete_payment(
    request: Request,
    response: Response,
    body: schema.CompletePayment,
    booking_id: BookingId,
    parent_id: ParentId,
    key: Key,
):
    record, replayed = svc.complete_payment(
        request.app.state.db_path, parent_id, booking_id, body.requested_outcome, key
    )
    committed(request, record, replayed, "payment_completed")
    blocked(record)
    response.status_code = 200 if replayed else 201
    response.headers["Location"] = f"/v1/payment-attempts/{record['id']}"
    return {"data": [record], "meta": {"replayed": replayed}}


@router.get(
    "/payment-attempts/{paymentAttemptId}",
    status_code=200,
    response_model=schema.Envelope[schema.PaymentAttempt],
    responses=errors(403, 404, 422),
)
def read_payment_attempt(request: Request, attempt_id: AttemptId, parent_id: ParentId):
    return {
        "data": [
            svc.get_payment_attempt(request.app.state.db_path, parent_id, attempt_id)
        ],
        "meta": {},
    }


@router.get(
    "/trial-classes/{trialClassId}/roster",
    status_code=200,
    response_model=schema.Envelope[schema.RosterMember],
    responses=errors(404, 422),
)
def read_roster(request: Request, trial_class_id: ClassId):
    roster = svc.get_roster(request.app.state.db_path, trial_class_id)
    return {
        "data": roster,
        "meta": {
            "trialClassId": trial_class_id,
            "capacity": 4,
            "confirmedCount": len(roster),
        },
    }
