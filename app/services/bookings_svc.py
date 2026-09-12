"""Booking rules and SQL shared by the JSON and HTML routes."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.db.connection import connect


class BookingError(Exception):
    def __init__(self, code: str, **context):
        super().__init__(code)
        self.code = code
        self.context = context


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _required(db, sql, params, code):
    row = db.execute(sql, params).fetchone()
    if row is None:
        raise BookingError(code)
    return dict(row)


def _parent(db, parent_id):
    return _required(
        db, "SELECT * FROM parents WHERE id=?", (parent_id,), "parent_not_found"
    )


def _student(db, parent_id, student_id):
    _parent(db, parent_id)
    row = _required(
        db, "SELECT * FROM students WHERE id=?", (student_id,), "student_not_found"
    )
    if row["parent_id"] != parent_id:
        raise BookingError("ownership_violation")
    return row


def _booking(db, parent_id, booking_id):
    _parent(db, parent_id)
    row = _required(
        db, "SELECT * FROM bookings WHERE id=?", (booking_id,), "booking_not_found"
    )
    _student(db, parent_id, row["student_id"])
    return row


def _public(row):
    return {key: value for key, value in row.items() if key != "idempotency_key"}


def _key(parent_id, client_key):
    if not isinstance(client_key, str) or not 1 <= len(client_key) <= 128:
        raise BookingError("validation_error")
    return f"{parent_id}:{client_key}"


def _block(db, student_id, trial_class_id):
    duplicate = db.execute(
        "SELECT id FROM bookings WHERE student_id=? AND trial_class_id=? AND status='confirmed'",
        (student_id, trial_class_id),
    ).fetchone()
    if duplicate:
        return "duplicate_booking", duplicate["id"]
    count = db.execute(
        "SELECT count(*) FROM bookings WHERE trial_class_id=? AND status='confirmed'",
        (trial_class_id,),
    ).fetchone()[0]
    return ("class_full", None) if count >= 4 else (None, None)


def list_parents(db_path: Path):
    with connect(db_path) as db:
        return [dict(row) for row in db.execute("SELECT * FROM parents ORDER BY id")]


def list_students(db_path: Path, parent_id: int):
    with connect(db_path) as db:
        _parent(db, parent_id)
        return [
            dict(row)
            for row in db.execute(
                "SELECT * FROM students WHERE parent_id=? ORDER BY id", (parent_id,)
            )
        ]


def list_classes(db_path: Path):
    with connect(db_path) as db:
        return [
            dict(row)
            for row in db.execute("""
            SELECT c.*, 4 AS capacity, count(b.id) AS confirmed_count,
                   4 - count(b.id) AS seats_remaining
            FROM trial_classes c LEFT JOIN bookings b
            ON b.trial_class_id=c.id AND b.status='confirmed'
            GROUP BY c.id ORDER BY c.starts_at, c.id
        """)
        ]


def get_class(db_path: Path, trial_class_id: int):
    for row in list_classes(db_path):
        if row["id"] == trial_class_id:
            return row
    raise BookingError("trial_class_not_found")


def get_booking(db_path: Path, parent_id: int, booking_id: int):
    with connect(db_path) as db:
        return _public(_booking(db, parent_id, booking_id))


def _attempt(db, attempt_id):
    return _required(
        db,
        """
        SELECT p.*, b.status AS booking_status, b.status_reason AS booking_status_reason
        FROM payment_attempts p JOIN bookings b ON b.id=p.booking_id WHERE p.id=?
    """,
        (attempt_id,),
        "payment_attempt_not_found",
    )


def get_payment_attempt(db_path: Path, parent_id: int, attempt_id: int):
    with connect(db_path) as db:
        _parent(db, parent_id)
        row = _attempt(db, attempt_id)
        _booking(db, parent_id, row["booking_id"])
        return _public(row)


def get_booking_attempt(db_path: Path, parent_id: int, booking_id: int):
    with connect(db_path) as db:
        _booking(db, parent_id, booking_id)
        row = db.execute(
            "SELECT id FROM payment_attempts WHERE booking_id=? ORDER BY id DESC LIMIT 1",
            (booking_id,),
        ).fetchone()
        return _public(_attempt(db, row["id"])) if row else None


def get_roster(db_path: Path, trial_class_id: int):
    with connect(db_path) as db:
        _required(
            db,
            "SELECT id FROM trial_classes WHERE id=?",
            (trial_class_id,),
            "trial_class_not_found",
        )
        return [
            dict(row)
            for row in db.execute(
                """
            SELECT b.id AS booking_id, s.id AS student_id, s.name AS student_name
            FROM bookings b JOIN students s ON s.id=b.student_id
            WHERE b.trial_class_id=? AND b.status='confirmed' ORDER BY b.id
        """,
                (trial_class_id,),
            )
        ]


def create_booking(
    db_path: Path, parent_id: int, student_id: int, trial_class_id: int, client_key: str
):
    key = _key(parent_id, client_key)
    with connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        _student(db, parent_id, student_id)
        _required(
            db,
            "SELECT id FROM trial_classes WHERE id=?",
            (trial_class_id,),
            "trial_class_not_found",
        )
        existing = db.execute(
            "SELECT * FROM bookings WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            if (existing["student_id"], existing["trial_class_id"]) != (
                student_id,
                trial_class_id,
            ):
                raise BookingError("idempotency_conflict")
            db.commit()
            return _public(dict(existing)), True
        reason, duplicate_id = _block(db, student_id, trial_class_id)
        if reason:
            context = {"existing_booking_id": duplicate_id} if duplicate_id else {}
            raise BookingError(reason, **context)
        timestamp = now()
        cursor = db.execute(
            """
            INSERT INTO bookings(student_id,trial_class_id,idempotency_key,created_at,updated_at)
            VALUES (?,?,?,?,?)
        """,
            (student_id, trial_class_id, key, timestamp, timestamp),
        )
        result = _public(_booking(db, parent_id, cursor.lastrowid))
        db.commit()
        return result, False


def complete_payment(
    db_path: Path,
    parent_id: int,
    booking_id: int,
    requested_outcome: str,
    client_key: str,
):
    if requested_outcome not in ("success", "failure"):
        raise BookingError("validation_error")
    key = _key(parent_id, client_key)
    with connect(db_path) as db:
        # SQLite serializes writers; use a server DB if write throughput matters.
        db.execute("BEGIN IMMEDIATE")
        booking = _booking(db, parent_id, booking_id)
        existing = db.execute(
            "SELECT * FROM payment_attempts WHERE idempotency_key=?", (key,)
        ).fetchone()
        if existing:
            if (existing["booking_id"], existing["requested_outcome"]) != (
                booking_id,
                requested_outcome,
            ):
                raise BookingError("idempotency_conflict")
            result = _public(_attempt(db, existing["id"]))
            db.commit()
            return result, True
        if booking["status"] != "pending_payment":
            raise BookingError("invalid_transition")
        cursor = db.execute(
            """
            INSERT INTO payment_attempts(booking_id,requested_outcome,idempotency_key,created_at)
            VALUES (?,?,?,?)
        """,
            (booking_id, requested_outcome, key, now()),
        )
        attempt_id = cursor.lastrowid
        if requested_outcome == "failure":
            outcome, reason, status = "failed", "mock_declined", "payment_failed"
        else:
            reason, _ = _block(db, booking["student_id"], booking["trial_class_id"])
            outcome, status = (
                ("blocked", "cancelled") if reason else ("succeeded", "confirmed")
            )
        db.execute(
            "UPDATE payment_attempts SET outcome=?,reason=? WHERE id=?",
            (outcome, reason, attempt_id),
        )
        try:
            db.execute(
                "UPDATE bookings SET status=?,status_reason=?,updated_at=? WHERE id=?",
                (status, reason if status == "cancelled" else None, now(), booking_id),
            )
        except sqlite3.IntegrityError as exc:
            if str(exc) in ("duplicate_booking", "class_full"):
                raise BookingError(str(exc)) from exc
            raise
        result = _public(_attempt(db, attempt_id))
        db.commit()
        return result, False
