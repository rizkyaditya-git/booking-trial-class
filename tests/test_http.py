import json
import re

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.main import create_app
from app.services import bookings_svc as svc


def test_json_flow(client):
    headers = {"X-Demo-Parent-Id": "1", "Idempotency-Key": "flow"}
    assert client.get("/v1/parents").json()["data"][0]["id"] == 1
    students = client.get("/v1/students", headers=headers)
    assert [row["id"] for row in students.json()["data"]] == [1, 2]
    assert client.get("/v1/trial-classes").json()["data"][0]["seatsRemaining"] == 4
    created = client.post(
        "/v1/bookings", headers=headers, json={"studentId": 1, "trialClassId": 1}
    )
    assert created.status_code == 201
    booking = created.json()["data"][0]
    location = f"/v1/bookings/{booking['id']}"
    assert created.headers["Location"] == location
    assert created.json()["meta"] == {"replayed": False}
    assert "idempotencyKey" not in booking
    assert booking["status"] == "pending_payment"
    paid = client.post(
        location + "/payment-attempts",
        headers=headers,
        json={"requestedOutcome": "success"},
    )
    assert paid.status_code == 201
    assert paid.json()["data"][0]["bookingStatus"] == "confirmed"
    assert client.get(paid.headers["Location"], headers=headers).json() == {
        "data": paid.json()["data"],
        "meta": {},
    }
    replay = client.post(
        location + "/payment-attempts",
        headers=headers,
        json={"requestedOutcome": "success"},
    )
    assert replay.status_code == 200 and replay.json()["meta"] == {"replayed": True}
    assert (
        client.get(location, headers=headers).json()["data"][0]["status"] == "confirmed"
    )
    roster = client.get("/v1/trial-classes/1/roster")
    assert roster.json()["data"] == [
        {"bookingId": booking["id"], "studentId": 1, "studentName": "Avery Tan"}
    ]
    assert roster.json()["meta"] == {
        "trialClassId": 1,
        "capacity": 4,
        "confirmedCount": 1,
    }
    assert roster.headers["Cache-Control"] == "no-store"
    assert roster.headers["X-Request-ID"] != created.headers["X-Request-ID"]


def test_json_validation_and_problem(client):
    response = client.post(
        "/v1/bookings",
        json={"studentId": "1", "trialClassId": 1, "status": "confirmed"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error" and body["errors"]
    assert body["instance"] == "/v1/bookings"
    assert body["requestId"] == response.headers["X-Request-ID"]
    assert response.headers["Content-Type"].startswith("application/problem+json")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"json": {"studentId": "1", "trialClassId": 1}},
        {"json": {"studentId": True, "trialClassId": 1}},
        {"json": {"studentId": 1.0, "trialClassId": 1}},
        {"json": {"studentId": 0, "trialClassId": 1}},
        {"json": {"student_id": 1, "trialClassId": 1}},
        {"json": {"studentId": 1, "trialClassId": 1, "status": "confirmed"}},
        {"json": {"studentId": 1, "trialClassId": None}},
        {"content": "{", "headers": {"Content-Type": "application/json"}},
    ],
)
def test_strict_json_payload(client, kwargs):
    headers = {
        "X-Demo-Parent-Id": "1",
        "Idempotency-Key": "strict",
        **kwargs.pop("headers", {}),
    }
    result = client.post("/v1/bookings", headers=headers, **kwargs)
    assert result.status_code == 422 and result.json()["errors"]


@pytest.mark.parametrize(
    "method,path,kwargs,status,code",
    [
        ("get", "/v1/students", {}, 422, "validation_error"),
        (
            "get",
            "/v1/students",
            {"headers": {"X-Demo-Parent-Id": "1.0"}},
            422,
            "validation_error",
        ),
        (
            "get",
            "/v1/students",
            {"headers": {"X-Demo-Parent-Id": "+1"}},
            422,
            "validation_error",
        ),
        (
            "get",
            "/v1/students",
            {"headers": {"X-Demo-Parent-Id": "99"}},
            404,
            "parent_not_found",
        ),
        (
            "get",
            "/v1/bookings/4",
            {"headers": {"X-Demo-Parent-Id": "2"}},
            403,
            "ownership_violation",
        ),
        (
            "get",
            "/v1/payment-attempts/1",
            {"headers": {"X-Demo-Parent-Id": "2"}},
            403,
            "ownership_violation",
        ),
        (
            "get",
            "/v1/bookings/999",
            {"headers": {"X-Demo-Parent-Id": "1"}},
            404,
            "booking_not_found",
        ),
        (
            "get",
            "/v1/payment-attempts/999",
            {"headers": {"X-Demo-Parent-Id": "1"}},
            404,
            "payment_attempt_not_found",
        ),
        ("get", "/v1/trial-classes/999/roster", {}, 404, "trial_class_not_found"),
        (
            "get",
            "/v1/bookings/1.0",
            {"headers": {"X-Demo-Parent-Id": "1"}},
            422,
            "validation_error",
        ),
        ("get", "/v1/parents?extra=value", {}, 422, "validation_error"),
        ("get", "/v1/missing", {}, 404, "not_found"),
        ("get", "/v1/parents/", {}, 404, "not_found"),
        ("post", "/v1/parents", {}, 405, "method_not_allowed"),
        ("post", "/v1/bookings/", {}, 404, "not_found"),
        (
            "post",
            "/v1/bookings",
            {"content": "plain text"},
            415,
            "unsupported_media_type",
        ),
        (
            "post",
            "/v1/bookings",
            {
                "json": {"studentId": 1, "trialClassId": 1},
                "headers": {"X-Demo-Parent-Id": "1"},
            },
            422,
            "validation_error",
        ),
        (
            "post",
            "/v1/bookings/4/payment-attempts",
            {
                "json": {"requestedOutcome": "other"},
                "headers": {"X-Demo-Parent-Id": "1", "Idempotency-Key": "key"},
            },
            422,
            "validation_error",
        ),
    ],
)
def test_http_errors(client, method, path, kwargs, status, code):
    result = getattr(client, method)(path, **kwargs)
    assert result.status_code == status
    assert result.json()["code"] == code
    assert result.json()["type"] == "about:blank"
    if status == 405:
        assert "GET" in result.headers["Allow"]


def test_decline_conflict_and_blocked_replay_contract(client, db_path):
    headers = {"X-Demo-Parent-Id": "1", "Idempotency-Key": "decline"}
    decline = client.post(
        "/v1/bookings/4/payment-attempts",
        headers=headers,
        json={"requestedOutcome": "failure"},
    )
    assert (
        decline.status_code == 201
        and decline.json()["data"][0]["bookingStatus"] == "payment_failed"
    )
    changed = client.post(
        "/v1/bookings/4/payment-attempts",
        headers=headers,
        json={"requestedOutcome": "success"},
    )
    assert (
        changed.status_code == 409 and changed.json()["code"] == "idempotency_conflict"
    )
    headers["Idempotency-Key"] = "fresh"
    terminal = client.post(
        "/v1/bookings/4/payment-attempts",
        headers=headers,
        json={"requestedOutcome": "success"},
    )
    assert (
        terminal.status_code == 409 and terminal.json()["code"] == "invalid_transition"
    )
    duplicate = client.post(
        "/v1/bookings", headers=headers, json={"studentId": 2, "trialClassId": 2}
    )
    assert duplicate.status_code == 409 and duplicate.json()["existingBookingId"] == 1
    assert "paymentAttemptId" not in duplicate.json()
    a, _ = svc.create_booking(db_path, 1, 1, 2, "a")
    b, _ = svc.create_booking(db_path, 2, 3, 2, "b")
    svc.complete_payment(db_path, 2, b["id"], "success", "b")
    url = f"/v1/bookings/{a['id']}/payment-attempts"
    result = client.post(url, headers=headers, json={"requestedOutcome": "success"})
    replay = client.post(url, headers=headers, json={"requestedOutcome": "success"})
    for response in (result, replay):
        assert response.status_code == 409
        body = response.json()
        assert body["code"] == "class_full" and body["bookingStatus"] == "cancelled"
        assert body["bookingId"] == a["id"]
    assert result.json()["paymentAttemptId"] == replay.json()["paymentAttemptId"]
    attempt = client.get(
        f"/v1/payment-attempts/{result.json()['paymentAttemptId']}", headers=headers
    )
    assert (
        attempt.status_code == 200 and attempt.json()["data"][0]["outcome"] == "blocked"
    )


def test_openapi_headers_no_slashes_and_restart(client, db_path):
    document = client.get("/openapi.json").json()
    paths = document["paths"]
    expected = {
        "/v1/health": "get",
        "/v1/parents": "get",
        "/v1/students": "get",
        "/v1/trial-classes": "get",
        "/v1/bookings": "post",
        "/v1/bookings/{bookingId}": "get",
        "/v1/bookings/{bookingId}/payment-attempts": "post",
        "/v1/payment-attempts/{paymentAttemptId}": "get",
        "/v1/trial-classes/{trialClassId}/roster": "get",
    }
    assert {
        path: method for path, method in expected.items() if method in paths[path]
    } == expected
    for path, method in expected.items():
        operation = paths[path][method]
        assert (
            "application/json"
            in operation["responses"]["201" if method == "post" else "200"]["content"]
        )
        for status in ("422", "500", "503"):
            assert set(operation["responses"][status]["content"]) == {
                "application/problem+json"
            }
        concrete = (
            path.replace("{bookingId}", "4")
            .replace("{paymentAttemptId}", "1")
            .replace("{trialClassId}", "1")
        )
        assert (
            client.request(
                method.upper(), concrete + "/", json={} if method == "post" else None
            ).status_code
            == 404
        )
    assert client.get("/docs").status_code == 200
    assert client.head("/v1/parents").content == b""
    request_schema = document["components"]["schemas"]["CreateBooking"]
    assert request_schema["additionalProperties"] is False
    assert set(request_schema["properties"]) == {"studentId", "trialClassId"}
    created, _ = svc.create_booking(db_path, 1, 1, 1, "restart")
    with TestClient(create_app(db_path), follow_redirects=False) as restarted:
        result = restarted.get(
            f"/v1/bookings/{created['id']}", headers={"X-Demo-Parent-Id": "1"}
        )
        assert result.json()["data"][0]["id"] == created["id"]


def test_health_is_read_only_and_missing_files_stay_missing(client, db_path, tmp_path):
    before = db_path.read_bytes()
    assert client.get("/v1/health").json() == {"data": [{"status": "ok"}], "meta": {}}
    assert db_path.read_bytes() == before
    missing = tmp_path / "missing.sqlite3"
    for target in (missing, tmp_path):
        with TestClient(create_app(target), follow_redirects=False) as unhealthy:
            result = unhealthy.get("/v1/health")
            assert (
                result.status_code == 503
                and result.json()["code"] == "database_unavailable"
            )
            assert result.headers["Retry-After"] == "1"
    assert not missing.exists()
    with connect(db_path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TABLE parents")
    before = db_path.read_bytes()
    assert client.get("/v1/health").status_code == 503
    assert db_path.read_bytes() == before


def test_logs_exclude_sensitive_data_and_rollback_is_not_committed(
    app, db_path, caplog, monkeypatch
):
    with connect(db_path) as db:
        db.execute(
            "CREATE TRIGGER fault BEFORE UPDATE ON bookings WHEN OLD.id=4 BEGIN SELECT RAISE(ABORT,'private SQL fault'); END"
        )
    with TestClient(
        app, follow_redirects=False, raise_server_exceptions=False
    ) as client:
        failed = client.post(
            "/v1/bookings/4/payment-attempts",
            headers={
                "X-Demo-Parent-Id": "1",
                "Idempotency-Key": "SECRET-KEY",
                "X-Request-ID": "CLIENT-ID",
            },
            json={"requestedOutcome": "success"},
        )
        assert failed.status_code == 500 and failed.json()["code"] == "internal_error"
        assert "SQL" not in failed.text
        assert failed.headers["X-Request-ID"] != "CLIENT-ID"
        logs = [
            json.loads(row.message)
            for row in caplog.records
            if row.name == "trial_booking"
        ]
        assert logs[-1]["level"] == "ERROR"
        assert not any(row["event"] == "payment_completed" for row in logs)
        with connect(db_path) as db:
            db.execute("DROP TRIGGER fault")
        paid = client.post(
            "/v1/bookings/4/payment-attempts",
            headers={"X-Demo-Parent-Id": "1", "Idempotency-Key": "SECRET-KEY"},
            json={"requestedOutcome": "success"},
        )
        assert paid.status_code == 201
    logs = [
        json.loads(row.message) for row in caplog.records if row.name == "trial_booking"
    ]
    assert any(
        row["event"] == "payment_completed"
        and row["outcome"] == "succeeded"
        and not row["replayed"]
        for row in logs
    )
    assert all("requestId" in row and "durationMs" in row for row in logs)
    serialized = json.dumps(logs)
    for sensitive in (
        "SECRET-KEY",
        "CLIENT-ID",
        "Avery",
        "requestedOutcome",
        "private SQL",
    ):
        assert sensitive not in serialized

    assert any(
        row["route"] == "/v1/bookings/{bookingId}/payment-attempts" for row in logs
    )
    from app.main import logger

    def broken_sink(*args, **kwargs):
        raise OSError("log sink unavailable")

    monkeypatch.setattr(logger, "log", broken_sink)
    with TestClient(app, follow_redirects=False) as client:
        replay = client.post(
            "/v1/bookings/4/payment-attempts",
            headers={"X-Demo-Parent-Id": "1", "Idempotency-Key": "SECRET-KEY"},
            json={"requestedOutcome": "success"},
        )
    assert replay.status_code == 200 and replay.json()["meta"]["replayed"]
    assert svc.get_booking(db_path, 1, 4)["status"] == "confirmed"


def test_database_busy_http_translation(client, db_path):
    with connect(db_path) as controller:
        controller.execute("BEGIN IMMEDIATE")
        result = client.post(
            "/v1/bookings/4/payment-attempts",
            headers={"X-Demo-Parent-Id": "1", "Idempotency-Key": "busy"},
            json={"requestedOutcome": "success"},
        )
    assert result.status_code == 503 and result.json()["code"] == "database_busy"
    assert result.headers["Retry-After"] == "1"


def form_key(html):
    return re.search(r'name="idempotencyKey" value="([^"]+)"', html)[1]


@pytest.mark.parametrize(
    "outcome,expected",
    [("success", "Your child has a seat"), ("failure", "Payment did not go through")],
)
def test_form_flow_redirects_and_refresh(client, db_path, outcome, expected):
    selection = client.get("/v1/ui/bookings/new")
    assert selection.status_code == 200 and "Demo parent" in selection.text
    assert 'name="studentId"' not in selection.text
    page = client.get("/v1/ui/bookings/new?demoParentId=1")
    assert (
        page.status_code == 200
        and "Avery Tan" in page.text
        and "class-choice" in page.text
    )
    form = {
        "demoParentId": "1",
        "studentId": "1",
        "trialClassId": "1",
        "idempotencyKey": form_key(page.text),
    }
    created = client.post("/v1/ui/bookings", data=form)
    assert created.status_code == 303
    assert created.headers["Location"].endswith("?demoParentId=1")
    assert (
        client.post("/v1/ui/bookings", data=form).headers["Location"]
        == created.headers["Location"]
    )
    status = client.get(created.headers["Location"])
    assert status.status_code == 200 and "Payment is pending" in status.text
    payment_url = created.headers["Location"].split("?")[0] + "/payment-attempts"
    pay_form = {
        "demoParentId": "1",
        "requestedOutcome": outcome,
        "idempotencyKey": form_key(status.text),
    }
    payment = client.post(payment_url, data=pay_form)
    assert (
        payment.status_code == 303
        and payment.headers["Location"] == created.headers["Location"]
    )
    final = client.get(payment.headers["Location"])
    assert expected in final.text and "Simulate success" not in final.text
    before = db_path.read_bytes()
    assert client.get(payment.headers["Location"]).status_code == 200
    assert db_path.read_bytes() == before
    roster = client.get("/v1/ui/trial-classes/1/roster")
    assert ("Avery Tan" in roster.text) == (outcome == "success")
    assert ("No confirmed students yet" in roster.text) == (outcome == "failure")


def test_form_inline_errors_keep_values_and_key(client, db_path):
    form = {
        "demoParentId": "1",
        "studentId": "2",
        "trialClassId": "2",
        "idempotencyKey": "preserved-key",
    }
    duplicate = client.post("/v1/ui/bookings", data=form)
    assert duplicate.status_code == 409 and "Already booked" in duplicate.text
    assert "/v1/ui/bookings/1?demoParentId=1" in duplicate.text
    assert form_key(duplicate.text) == "preserved-key"
    assert re.search(r'<option value="2"\s+selected', duplicate.text)
    invalid = client.post("/v1/ui/bookings", data={**form, "trialClassId": "bad"})
    assert invalid.status_code == 422 and "Check the submitted fields" in invalid.text
    assert form_key(invalid.text) == "preserved-key"
    assert "Submitted class: bad" in invalid.text
    unknown = client.post("/v1/ui/bookings", data={**form, "status": "confirmed"})
    assert unknown.status_code == 422 and "text/html" in unknown.headers["Content-Type"]
    before = db_path.read_bytes()
    forbidden = client.get("/v1/ui/bookings/4?demoParentId=2")
    assert forbidden.status_code == 403 and "another demo parent" in forbidden.text
    assert "Avery Tan" not in forbidden.text
    assert db_path.read_bytes() == before
    assert client.get("/v1/ui/bookings/new?demoParentId=1&extra=1").status_code == 422
    assert client.get("/v1/ui/bookings/4").status_code == 422


def test_form_lost_seat_is_inline_409_and_roster_link(client, db_path):
    a, _ = svc.create_booking(db_path, 1, 1, 2, "a")
    b, _ = svc.create_booking(db_path, 2, 3, 2, "b")
    svc.complete_payment(db_path, 2, b["id"], "success", "b")
    form = {
        "demoParentId": "1",
        "requestedOutcome": "success",
        "idempotencyKey": "a-pay",
    }
    response = client.post(f"/v1/ui/bookings/{a['id']}/payment-attempts", data=form)
    assert response.status_code == 409 and "The last seat was taken" in response.text
    assert (
        "Blocked: class full" in response.text
        and "Simulate success" not in response.text
    )
    assert "/v1/ui/trial-classes/2/roster" in response.text
    roster = client.get("/v1/ui/trial-classes/2/roster")
    assert (
        "4 / 4" in roster.text
        and "Riley Lim" in roster.text
        and "Avery Tan" not in roster.text
    )
    new_form = client.get("/v1/ui/bookings/new?demoParentId=1")
    assert re.search(r'value="2"[^>]*disabled', new_form.text)
