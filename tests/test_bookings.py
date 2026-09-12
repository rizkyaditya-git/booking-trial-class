import sqlite3
from contextlib import closing

import pytest

from app.db.connection import connect, setup_database
from app.services import bookings_svc as svc


def test_seed_and_constraints(db_path):
    with closing(sqlite3.connect(db_path)) as db:
        db.execute("PRAGMA foreign_keys = ON")
        tables = db.execute("PRAGMA table_list").fetchall()
        assert sum(row[5] for row in tables) == 5
        assert db.execute("SELECT count(*) FROM parents").fetchone()[0] == 2
        assert (
            db.execute(
                "SELECT count(*) FROM bookings WHERE trial_class_id=2 AND status='confirmed'"
            ).fetchone()[0]
            == 3
        )
        assert (
            db.execute("SELECT status FROM bookings WHERE id=4").fetchone()[0]
            == "pending_payment"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO students VALUES (99, 999, 'Invalid parent')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE bookings SET status='cancelled',status_reason=NULL WHERE id=4"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE bookings SET status='confirmed' WHERE id=4")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE bookings SET status='pending_payment' WHERE id=1")


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO parents VALUES (99, '   ')",
        "INSERT INTO students VALUES ('text', 1, 'Test')",
        "INSERT INTO students VALUES (99, NULL, 'Test')",
        "DELETE FROM parents WHERE id=1",
        "UPDATE students SET id=99 WHERE id=1",
        "UPDATE bookings SET status='unknown' WHERE id=4",
        "UPDATE bookings SET status='payment_failed' WHERE id=4",
        "UPDATE bookings SET status='cancelled',status_reason='class_full' WHERE id=4",
        "UPDATE bookings SET student_id=3,status='payment_failed' WHERE id=4",
        "UPDATE bookings SET id=99 WHERE id=4",
        "UPDATE bookings SET trial_class_id=3 WHERE id=4",
        "UPDATE bookings SET idempotency_key='changed' WHERE id=4",
        "UPDATE bookings SET created_at='changed' WHERE id=4",
        "DELETE FROM bookings WHERE id=1",
        "UPDATE payment_attempts SET reason='class_full' WHERE id=1",
        "DELETE FROM payment_attempts WHERE id=1",
        "INSERT INTO bookings SELECT 99,student_id,trial_class_id,status,status_reason,'x',created_at,updated_at FROM bookings WHERE id=1",
        "INSERT INTO payment_attempts SELECT 99,4,'success','succeeded',NULL,'x',created_at FROM payment_attempts WHERE id=1",
        "INSERT INTO payment_attempts SELECT 99,999,'success','pending',NULL,'x',created_at FROM payment_attempts WHERE id=1",
        "INSERT INTO bookings SELECT 99,999,1,'pending_payment',NULL,'x',created_at,updated_at FROM bookings WHERE id=4",
        "INSERT INTO bookings SELECT 99,1,999,'pending_payment',NULL,'x',created_at,updated_at FROM bookings WHERE id=4",
    ],
)
def test_direct_sql_guards(db_path, sql):
    with connect(db_path) as db, pytest.raises(sqlite3.IntegrityError):
        db.execute(sql)


@pytest.mark.parametrize(
    "changes",
    [
        "outcome='failed',requested_outcome='failure',reason=NULL",
        "outcome='blocked',reason=NULL",
        "outcome='failed',reason='mock_declined'",
        "outcome='succeeded',reason='class_full'",
        "outcome='unknown'",
        "outcome='succeeded',id=99",
        "outcome='succeeded',booking_id=1",
        "outcome='succeeded',idempotency_key='changed'",
        "outcome='succeeded',created_at='changed'",
    ],
)
def test_attempt_combinations_and_identity(db_path, changes):
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO payment_attempts VALUES (9,4,'success','pending',NULL,'test','2026-09-09T01:00:00.000000Z')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(f"UPDATE payment_attempts SET {changes} WHERE id=9")


def test_failed_attempt_requires_explicit_reason(db_path):
    with connect(db_path) as db:
        db.execute(
            "INSERT INTO payment_attempts VALUES (9,4,'failure','pending',NULL,'test','t')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            db.execute("UPDATE payment_attempts SET outcome='failed' WHERE id=9")


def test_direct_duplicate_payment_and_confirmation_capacity(db_path):
    with connect(db_path) as db:

        def pending(booking_id, student_id):
            db.execute(
                "INSERT INTO bookings VALUES (?,?,2,'pending_payment',NULL,?,'t','t')",
                (booking_id, student_id, f"b{booking_id}"),
            )
            db.execute(
                "INSERT INTO payment_attempts VALUES (?,?,'success','pending',NULL,?,'t')",
                (booking_id, booking_id, f"p{booking_id}"),
            )
            db.execute(
                "UPDATE payment_attempts SET outcome='succeeded' WHERE id=?",
                (booking_id,),
            )

        pending(10, 2)
        with pytest.raises(sqlite3.IntegrityError, match="duplicate_booking"):
            db.execute("UPDATE bookings SET status='confirmed' WHERE id=10")
        db.execute(
            "INSERT INTO payment_attempts VALUES (20,10,'success','pending',NULL,'second','t')"
        )
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
            db.execute("UPDATE payment_attempts SET outcome='succeeded' WHERE id=20")
        pending(11, 1)
        db.execute("UPDATE bookings SET status='confirmed' WHERE id=11")
        pending(12, 3)
        with pytest.raises(sqlite3.IntegrityError, match="class_full"):
            db.execute("UPDATE bookings SET status='confirmed' WHERE id=12")


def test_setup_preserves_existing_data_and_reset_is_explicit(db_path):
    before = db_path.read_bytes()
    with pytest.raises(FileExistsError):
        setup_database(db_path)
    assert db_path.read_bytes() == before
    with connect(db_path) as db:
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        db.execute("INSERT INTO parents VALUES (99, 'Additional')")
    setup_database(db_path, reset=True)
    with connect(db_path) as db:
        assert db.execute("SELECT count(*) FROM parents").fetchone()[0] == 2


def test_missing_connection_does_not_create_file(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(sqlite3.OperationalError), connect(missing):
        pass
    assert not missing.exists()


def test_booking_payment_flow_and_rejection(db_path):
    booking, replayed = svc.create_booking(db_path, 1, 1, 1, "create")
    assert not replayed and booking["status"] == "pending_payment"
    assert booking["created_at"] == booking["updated_at"]
    attempt, replayed = svc.complete_payment(
        db_path, 1, booking["id"], "success", "pay"
    )
    assert not replayed and attempt["outcome"] == "succeeded"
    assert svc.get_booking(db_path, 1, booking["id"])["status"] == "confirmed"
    assert len(svc.get_roster(db_path, 1)) == 1
    with pytest.raises(svc.BookingError, match="duplicate_booking"):
        svc.create_booking(db_path, 1, 1, 1, "duplicate")
    failed, _ = svc.complete_payment(db_path, 1, 4, "failure", "failure")
    assert failed["outcome"] == "failed" and failed["reason"] == "mock_declined"
    assert svc.get_booking(db_path, 1, 4)["status"] == "payment_failed"
    assert len(svc.get_roster(db_path, 1)) == 1
    last, _ = svc.create_booking(db_path, 1, 1, 2, "last")
    svc.complete_payment(db_path, 1, last["id"], "success", "last-pay")
    with pytest.raises(svc.BookingError, match="class_full"):
        svc.create_booking(db_path, 2, 3, 2, "full")
    assert len(svc.get_roster(db_path, 2)) == 4


def test_replays_scopes_terminal_states_and_timestamps(db_path):
    booking, _ = svc.create_booking(db_path, 1, 1, 1, "same")
    assert svc.create_booking(db_path, 1, 1, 1, "same") == (booking, True)
    with pytest.raises(svc.BookingError, match="idempotency_conflict"):
        svc.create_booking(db_path, 1, 2, 1, "same")
    other, _ = svc.create_booking(db_path, 2, 3, 1, "same")
    assert other["id"] != booking["id"]
    attempt, _ = svc.complete_payment(db_path, 1, booking["id"], "success", "same")
    confirmed = svc.get_booking(db_path, 1, booking["id"])
    assert svc.create_booking(db_path, 1, 1, 1, "same") == (confirmed, True)
    assert svc.complete_payment(db_path, 1, booking["id"], "success", "same") == (
        attempt,
        True,
    )
    assert svc.get_booking(db_path, 1, booking["id"]) == confirmed
    with pytest.raises(svc.BookingError, match="idempotency_conflict"):
        svc.complete_payment(db_path, 1, booking["id"], "failure", "same")
    with pytest.raises(svc.BookingError, match="invalid_transition"):
        svc.complete_payment(db_path, 1, booking["id"], "success", "fresh")
    failed, _ = svc.complete_payment(db_path, 1, 4, "failure", "failure")
    assert svc.complete_payment(db_path, 1, 4, "failure", "failure") == (failed, True)
    with pytest.raises(svc.BookingError, match="idempotency_conflict"):
        svc.complete_payment(db_path, 1, 4, "success", "same")
    with pytest.raises(svc.BookingError, match="invalid_transition"):
        svc.complete_payment(db_path, 1, 4, "success", "fresh-failure")
    other_attempt, _ = svc.complete_payment(db_path, 2, other["id"], "failure", "same")
    assert other_attempt["id"] != attempt["id"]
    with connect(db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE idempotency_key LIKE '%:same'"
            ).fetchone()[0]
            == 2
        )
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE outcome='pending'"
            ).fetchone()[0]
            == 0
        )


def test_ownership_missing_records_and_rejected_keys_make_no_writes(db_path):
    before = db_path.read_bytes()
    calls = [
        (lambda: svc.create_booking(db_path, 1, 3, 1, "key"), "ownership_violation"),
        (lambda: svc.get_booking(db_path, 2, 4), "ownership_violation"),
        (
            lambda: svc.complete_payment(db_path, 2, 4, "success", "key"),
            "ownership_violation",
        ),
        (lambda: svc.get_payment_attempt(db_path, 2, 1), "ownership_violation"),
        (lambda: svc.list_students(db_path, 99), "parent_not_found"),
        (lambda: svc.create_booking(db_path, 1, 99, 1, "key"), "student_not_found"),
        (lambda: svc.create_booking(db_path, 1, 1, 99, "key"), "trial_class_not_found"),
        (lambda: svc.get_booking(db_path, 1, 99), "booking_not_found"),
        (lambda: svc.get_payment_attempt(db_path, 1, 99), "payment_attempt_not_found"),
        (lambda: svc.get_roster(db_path, 99), "trial_class_not_found"),
        (lambda: svc.create_booking(db_path, 1, 1, 1, ""), "validation_error"),
        (lambda: svc.create_booking(db_path, 1, 1, 1, "x" * 129), "validation_error"),
        (
            lambda: svc.complete_payment(db_path, 1, 4, "maybe", "key"),
            "validation_error",
        ),
    ]
    for call, code in calls:
        with pytest.raises(svc.BookingError, match=code):
            call()
    assert db_path.read_bytes() == before
    accepted, _ = svc.create_booking(db_path, 1, 1, 1, "key")
    assert accepted["status"] == "pending_payment"


def test_payment_rollback_then_same_key_retry(db_path):
    with connect(db_path) as db:
        db.execute("""CREATE TRIGGER injected_failure BEFORE UPDATE ON bookings
                      WHEN OLD.id=4 BEGIN SELECT RAISE(ABORT, 'test fault'); END""")
    before = svc.get_booking(db_path, 1, 4)
    with pytest.raises(sqlite3.IntegrityError, match="test fault"):
        svc.complete_payment(db_path, 1, 4, "success", "retry-after-fault")
    with connect(db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE booking_id=4"
            ).fetchone()[0]
            == 0
        )
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE idempotency_key='1:retry-after-fault'"
            ).fetchone()[0]
            == 0
        )
        db.execute("DROP TRIGGER injected_failure")
    assert svc.get_booking(db_path, 1, 4) == before
    attempt, replayed = svc.complete_payment(
        db_path, 1, 4, "success", "retry-after-fault"
    )
    assert not replayed and attempt["outcome"] == "succeeded"


def test_busy_timeout_rolls_back_then_same_key_retry(db_path):
    with connect(db_path) as controller:
        controller.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            svc.complete_payment(db_path, 1, 4, "success", "retry-after-lock")
    assert svc.get_booking(db_path, 1, 4)["status"] == "pending_payment"
    with connect(db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE booking_id=4"
            ).fetchone()[0]
            == 0
        )
    attempt, replayed = svc.complete_payment(
        db_path, 1, 4, "success", "retry-after-lock"
    )
    assert not replayed and attempt["outcome"] == "succeeded"
