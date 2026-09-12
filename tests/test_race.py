from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from itertools import count
from threading import Event
from time import monotonic

from app.db.connection import connect
from app.services import bookings_svc as svc


def concurrent_completions(db_path, monkeypatch, calls):
    ready = [Event(), Event()]
    connections = count()
    real_connect = svc.connect

    @contextmanager
    def traced_connect(path):
        assert path == db_path
        event = ready[next(connections)]
        with real_connect(path) as db:
            db.set_trace_callback(
                lambda sql: event.set() if sql == "BEGIN IMMEDIATE" else None
            )
            yield db

    with real_connect(db_path) as controller, ThreadPoolExecutor(max_workers=2) as pool:
        controller.execute("BEGIN IMMEDIATE")
        with monkeypatch.context() as patch:
            patch.setattr(svc, "connect", traced_connect)
            futures = [
                pool.submit(svc.complete_payment, db_path, *args) for args in calls
            ]
            try:
                deadline = monotonic() + 2
                for event in ready:
                    assert event.wait(max(0, deadline - monotonic())), (
                        "Both connections must reach BEGIN IMMEDIATE"
                    )
            finally:
                controller.rollback()
            results = [future.result(timeout=10) for future in futures]
    assert next(connections) == 2
    return results


def assert_last_seat(db_path, booking_ids):
    with connect(db_path) as db:
        bookings = db.execute(
            "SELECT status,status_reason FROM bookings WHERE id IN (?,?) ORDER BY status",
            booking_ids,
        ).fetchall()
        assert [tuple(row) for row in bookings] == [
            ("cancelled", "class_full"),
            ("confirmed", None),
        ]
        attempts = db.execute(
            "SELECT outcome,reason FROM payment_attempts WHERE booking_id IN (?,?) ORDER BY outcome",
            booking_ids,
        ).fetchall()
        assert [tuple(row) for row in attempts] == [
            ("blocked", "class_full"),
            ("succeeded", None),
        ]
    assert len(svc.get_roster(db_path, 2)) == 4


def test_a_starts_first_b_completes_first(db_path):
    a, _ = svc.create_booking(db_path, 1, 1, 2, "a-first")
    b, _ = svc.create_booking(db_path, 2, 3, 2, "b-second")
    assert a["id"] < b["id"]
    winner, _ = svc.complete_payment(db_path, 2, b["id"], "success", "b-pay")
    loser, _ = svc.complete_payment(db_path, 1, a["id"], "success", "a-pay")
    assert winner["outcome"] == "succeeded"
    assert loser["outcome"] == "blocked" and loser["reason"] == "class_full"
    assert svc.complete_payment(db_path, 1, a["id"], "success", "a-pay") == (
        loser,
        True,
    )
    assert_last_seat(db_path, (a["id"], b["id"]))


def test_concurrent_last_seat(db_path, monkeypatch):
    a, _ = svc.create_booking(db_path, 1, 1, 2, "a")
    b, _ = svc.create_booking(db_path, 2, 3, 2, "b")
    results = concurrent_completions(
        db_path,
        monkeypatch,
        [(1, a["id"], "success", "a-pay"), (2, b["id"], "success", "b-pay")],
    )
    assert sorted(row[0]["outcome"] for row in results) == ["blocked", "succeeded"]
    assert not any(row[1] for row in results)
    assert_last_seat(db_path, (a["id"], b["id"]))


def test_concurrent_same_child_with_spare_capacity(db_path, monkeypatch):
    a, _ = svc.create_booking(db_path, 1, 1, 1, "a")
    b, _ = svc.create_booking(db_path, 1, 1, 1, "b")
    results = concurrent_completions(
        db_path,
        monkeypatch,
        [(1, a["id"], "success", "a-pay"), (1, b["id"], "success", "b-pay")],
    )
    assert sorted(row[0]["outcome"] for row in results) == ["blocked", "succeeded"]
    loser = next(row[0] for row in results if row[0]["outcome"] == "blocked")
    assert loser["reason"] == "duplicate_booking"
    with connect(db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM bookings WHERE student_id=1 AND trial_class_id=1 AND status='confirmed'"
            ).fetchone()[0]
            == 1
        )
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE outcome='blocked' AND reason='duplicate_booking'"
            ).fetchone()[0]
            == 1
        )
    assert len(svc.get_roster(db_path, 1)) == 1


def test_concurrent_identical_payment_key(db_path, monkeypatch):
    results = concurrent_completions(
        db_path, monkeypatch, [(1, 4, "success", "same"), (1, 4, "success", "same")]
    )
    assert results[0][0] == results[1][0]
    assert sorted(row[1] for row in results) == [False, True]
    with connect(db_path) as db:
        assert (
            db.execute(
                "SELECT count(*) FROM payment_attempts WHERE booking_id=4"
            ).fetchone()[0]
            == 1
        )
    assert len(svc.get_roster(db_path, 1)) == 1
