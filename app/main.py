"""App wiring, sanitized errors, and local JSON diagnostics."""

import json
import logging
import sqlite3
import sys
from collections.abc import Mapping
from http import HTTPStatus
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.routing import Match

from app.api import bookings, pages
from app.db.connection import default_path
from app.schemas.bookings import Problem
from app.services import bookings_svc as svc

logger = logging.getLogger("trial_booking")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

DETAILS = {
    "validation_error": (422, "Check the submitted fields and demo parent context."),
    "ownership_violation": (403, "This record belongs to another demo parent."),
    "duplicate_booking": (
        409,
        "This child already has a confirmed booking for this class.",
    ),
    "class_full": (
        409,
        "The class is full. No seat was confirmed and no charge was made.",
    ),
    "idempotency_conflict": (
        409,
        "This request key was already used with different input.",
    ),
    "invalid_transition": (
        409,
        "This booking is already final and cannot be paid again.",
    ),
    "unsupported_media_type": (415, "Use the documented request content type."),
    "method_not_allowed": (405, "This method is not supported on this route."),
    "database_busy": (503, "The database is busy. Retry the same request key."),
    "database_unavailable": (
        503,
        "The database is unavailable. Check explicit database setup.",
    ),
    "internal_error": (500, "The request could not be completed."),
}


def problem(request, code, *, context=None, errors=None, headers=None):
    if code.endswith("not_found"):
        status, detail = 404, "The requested resource was not found."
    else:
        status, detail = DETAILS[code]
    request.state.error_code = code
    if code == "validation_error" and errors is None:
        errors = [{"field": "request", "message": detail}]
    body = Problem(
        title=HTTPStatus(status).phrase,
        status=status,
        code=code,
        detail=detail,
        instance=request.url.path,
        request_id=request.state.request_id,
        errors=errors,
        **(context or {}),
    )
    response_headers = dict(headers or {})
    if status == 503:
        response_headers["Retry-After"] = "1"
    if request.url.path.startswith("/v1/ui/"):
        response = pages.render_problem(request, code, status, detail, context or {})
        response.headers.update(response_headers)
        return response
    return JSONResponse(
        body.model_dump(by_alias=True, exclude_none=True),
        status_code=status,
        media_type="application/problem+json",
        headers=response_headers,
    )


def database_code(exc):
    code = getattr(exc, "sqlite_errorcode", 0) & 0xFF
    if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return "database_busy"
    if code in (
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_NOTADB,
        sqlite3.SQLITE_CORRUPT,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_READONLY,
    ) or "no such table" in str(exc):
        return "database_unavailable"
    return "internal_error"


def create_app(db_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Ottodot trial booking", redirect_slashes=False)
    app.state.db_path = Path(db_path) if db_path is not None else default_path()
    app.include_router(bookings.router, tags=["Backend API (/v1)"])
    app.include_router(pages.router, tags=["UI pages (/v1/ui)"])
    app.mount(
        "/v1/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )

    @app.exception_handler(svc.BookingError)
    def booking_error(request: Request, exc: svc.BookingError):
        return problem(request, exc.code, context=exc.context)

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, exc: RequestValidationError):
        if isinstance(exc.body, Mapping):
            request.state.form_values = dict(exc.body)
        errors = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return problem(request, "validation_error", errors=errors)

    @app.exception_handler(HTTPException)
    def http_error(request: Request, exc: HTTPException):
        return problem(
            request,
            {
                404: "not_found",
                405: "method_not_allowed",
                415: "unsupported_media_type",
            }.get(exc.status_code, "internal_error"),
            headers=exc.headers,
        )

    @app.exception_handler(sqlite3.Error)
    def database_error(request: Request, exc: sqlite3.Error):
        return problem(request, database_code(exc))

    @app.middleware("http")
    async def diagnostics(request: Request, call_next):
        started = perf_counter()
        request.state.request_id = str(uuid4())
        try:
            is_write = request.method == "POST" and request.url.path.startswith("/v1/")
            media_type = (
                request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            )
            matched = next(
                (
                    route
                    for route in app.routes
                    if route.matches(request.scope)[0] == Match.FULL
                ),
                None,
            )
            expected_type = (
                "application/x-www-form-urlencoded"
                if request.url.path.startswith("/v1/ui/")
                else "application/json"
            )
            if is_write and matched is not None and media_type != expected_type:
                request.scope["route"] = matched
                response = await run_in_threadpool(
                    problem, request, "unsupported_media_type"
                )
            else:
                response = await call_next(request)
        except Exception:
            response = await run_in_threadpool(problem, request, "internal_error")
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        if request.method == "HEAD":
            response = Response(
                status_code=response.status_code, headers=dict(response.headers)
            )
        error_code = getattr(request.state, "error_code", None)
        level = (
            logging.WARNING
            if error_code == "database_busy"
            else logging.ERROR
            if response.status_code >= 500
            else logging.INFO
        )
        record = {
            "timestamp": svc.now(),
            "level": logging.getLevelName(level),
            "event": "request",
            "requestId": request.state.request_id,
            "method": request.method,
            "route": getattr(request.scope.get("route"), "path", "unmatched"),
            "httpStatus": response.status_code,
            "durationMs": round((perf_counter() - started) * 1000, 2),
        }
        if error_code:
            record["code"] = error_code
        try:
            outcome = getattr(request.state, "committed", None)
            if outcome:
                logger.log(level, json.dumps({**record, **outcome}))
            logger.log(level, json.dumps(record))
        except Exception:
            # Committed database outcomes remain authoritative if a log sink fails.
            pass
        return response

    return app


app = create_app()
