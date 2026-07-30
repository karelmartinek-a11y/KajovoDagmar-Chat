from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from kajovodagmar.config import get_settings
from kajovodagmar.main import create_app

pytestmark = pytest.mark.integration

PASSWORD = "Bezpečná integrační věta pro rok 2026"


def assert_status(response, expected: int) -> dict:
    assert response.status_code == expected, response.text
    return response.json() if response.content else {}


def database_dsn() -> str:
    return os.environ["KAJOVODAGMAR_TEST_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )


def test_operations_audit_and_backup_lifecycle(api_client: TestClient) -> None:
    login = assert_status(
        api_client.post(
            "/api/v1/auth/login",
            json={"username": "Karmar78", "password": PASSWORD},
        ),
        200,
    )
    csrf = {"X-CSRF-Token": login["csrf_token"]}

    startup = assert_status(api_client.get("/api/v1/health/startup"), 200)
    assert startup["specification_revision"] == "v0021"
    status = assert_status(api_client.get("/api/v1/operations/status"), 200)
    assert status["components"]["database"]["state"] == "ready"
    assert status["components"]["providers"]["state"] == "limited"

    initial_audit = assert_status(
        api_client.get("/api/v1/operations/audit", params={"limit": 1}), 200
    )
    assert len(initial_audit["items"]) == 1
    assert initial_audit["next_before_id"] is not None
    newest = initial_audit["items"][0]
    detail = assert_status(
        api_client.get(f"/api/v1/operations/audit/{newest['id']}"), 200
    )
    assert detail["event_hash"] == newest["event_hash"]
    assert api_client.get("/api/v1/operations/audit/999999999").status_code == 404
    integrity = assert_status(api_client.get("/api/v1/operations/audit/integrity"), 200)
    assert integrity["state"] == "valid"
    assert integrity["events_checked"] > 0

    filters = {
        "before_id": newest["id"] + 1,
        "from_time": "2020-01-01T00:00:00Z",
        "to_time": datetime.now(UTC).isoformat(),
        "area": newest["area"],
        "result": newest["result"],
        "actor_type": newest["actor_type"],
        "event_name": newest["event_name"],
        "limit": 100,
    }
    if newest["target_type"]:
        filters["target_type"] = newest["target_type"]
    if newest["correlation_id"]:
        filters["correlation_id"] = newest["correlation_id"]
    filtered = assert_status(
        api_client.get("/api/v1/operations/audit", params=filters), 200
    )
    assert any(item["id"] == newest["id"] for item in filtered["items"])

    assert assert_status(api_client.get("/api/v1/operations/backups"), 200) == {
        "items": []
    }
    request = {
        "purpose": "Ruční integrační ověření",
        "idempotency_key": "operations-create-0001",
    }
    backup = assert_status(
        api_client.post("/api/v1/operations/backups", headers=csrf, json=request),
        202,
    )
    assert backup["state"] == "queued"
    repeated = assert_status(
        api_client.post("/api/v1/operations/backups", headers=csrf, json=request),
        202,
    )
    assert repeated["id"] == backup["id"]
    assert (
        assert_status(api_client.get("/api/v1/operations/backups"), 200)["items"][0][
            "id"
        ]
        == backup["id"]
    )

    queued_action = {
        "expected_version": backup["version"],
        "idempotency_key": "operations-verify-queued-0001",
    }
    assert (
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/verify",
            headers=csrf,
            json=queued_action,
        ).status_code
        == 409
    )
    assert (
        api_client.post(
            f"/api/v1/operations/backups/{uuid4()}/verify",
            headers=csrf,
            json=queued_action,
        ).status_code
        == 404
    )

    with psycopg.connect(database_dsn()) as connection:
        completed = connection.execute(
            """
            UPDATE backup_record
            SET state='completed', completed_at=now(), verified_at=now(),
                backup_label='integration-full', manifest_digest=%s,
                size_bytes=4096, version=version+1, updated_at=now()
            WHERE id=%s
            RETURNING version
            """,
            ("a" * 64, backup["id"]),
        ).fetchone()
        assert completed is not None
        completed_version = int(completed[0])

    wrong_version = {
        "expected_version": completed_version + 1,
        "idempotency_key": "operations-verify-wrong-0001",
    }
    assert (
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/verify",
            headers=csrf,
            json=wrong_version,
        ).status_code
        == 409
    )
    verify_request = {
        "expected_version": completed_version,
        "idempotency_key": "operations-verify-0001",
    }
    verified = assert_status(
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/verify",
            headers=csrf,
            json=verify_request,
        ),
        202,
    )
    assert verified["state"] == "completed"
    assert_status(
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/verify",
            headers=csrf,
            json=verify_request,
        ),
        202,
    )
    assert (
        api_client.post(
            f"/api/v1/operations/backups/{uuid4()}/verify",
            headers=csrf,
            json=verify_request,
        ).status_code
        == 404
    )

    invalid_restore = {
        "expected_version": completed_version,
        "idempotency_key": "operations-restore-invalid-0001",
        "confirmation": "NE",
    }
    assert (
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/restore-test",
            headers=csrf,
            json=invalid_restore,
        ).status_code
        == 422
    )
    restore_request = {
        "expected_version": completed_version,
        "idempotency_key": "operations-restore-0001",
        "confirmation": "OBNOVIT DO IZOLOVANÉHO PROSTŘEDÍ",
    }
    restored = assert_status(
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/restore-test",
            headers=csrf,
            json=restore_request,
        ),
        202,
    )
    assert restored["backup_label"] == "integration-full"
    assert_status(
        api_client.post(
            f"/api/v1/operations/backups/{backup['id']}/restore-test",
            headers=csrf,
            json=restore_request,
        ),
        202,
    )

    updated_status = assert_status(api_client.get("/api/v1/operations/status"), 200)
    assert updated_status["components"]["backups"]["state"] == "ready"
    assert updated_status["last_backup"]["verified_at"] is not None

    backup_audit = assert_status(
        api_client.get(
            "/api/v1/operations/audit",
            params={"area": "backup", "result": "success", "limit": 100},
        ),
        200,
    )
    assert {item["event_name"] for item in backup_audit["items"]} >= {
        "backup.requested",
        "backup.verify_requested",
        "backup.restore_test_requested",
    }
    target_filtered = assert_status(
        api_client.get(
            "/api/v1/operations/audit",
            params={"target_type": "backup_record", "limit": 100},
        ),
        200,
    )
    assert target_filtered["items"]

    second_login = assert_status(
        api_client.post(
            "/api/v1/auth/login",
            json={"username": "Karmar78", "password": PASSWORD},
        ),
        200,
    )
    csrf = {"X-CSRF-Token": second_login["csrf_token"]}
    sessions = assert_status(api_client.get("/api/v1/auth/sessions"), 200)["items"]
    other = next(item for item in sessions if not item["current"])
    assert (
        api_client.delete(f"/api/v1/auth/sessions/{uuid4()}", headers=csrf).status_code
        == 204
    )
    assert (
        api_client.delete(
            f"/api/v1/auth/sessions/{other['id']}", headers=csrf
        ).status_code
        == 204
    )

    assert_status(
        api_client.post("/api/v1/auth/password/forgot", json={"username": "nikdo"}),
        202,
    )
    assert_status(
        api_client.post("/api/v1/auth/password/forgot", json={"username": "Karmar78"}),
        202,
    )
    mismatched = {
        "token": "synthetic-invalid-reset-token",
        "new_password": "Nové bezpečné integrační heslo 2026",
        "confirmation": "jiné potvrzení",
    }
    assert (
        api_client.post("/api/v1/auth/password/reset", json=mismatched).status_code
        == 422
    )
    invalid_token = {
        **mismatched,
        "confirmation": mismatched["new_password"],
    }
    assert (
        api_client.post("/api/v1/auth/password/reset", json=invalid_token).status_code
        == 400
    )

    mismatch_change = {
        "current_password": PASSWORD,
        "new_password": "Změněné bezpečné integrační heslo 2026",
        "confirmation": "jiné potvrzení",
    }
    assert (
        api_client.post(
            "/api/v1/auth/password/change",
            headers=csrf,
            json=mismatch_change,
        ).status_code
        == 422
    )
    changed = assert_status(
        api_client.post(
            "/api/v1/auth/password/change",
            headers=csrf,
            json={
                **mismatch_change,
                "confirmation": mismatch_change["new_password"],
            },
        ),
        200,
    )
    assert changed["other_sessions_revoked"] is True


def test_metrics_token_is_not_an_observability_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "KAJOVODAGMAR_DATABASE_URL", os.environ["KAJOVODAGMAR_TEST_DATABASE_URL"]
    )
    monkeypatch.setenv("KAJOVODAGMAR_ENVIRONMENT", "test")
    monkeypatch.setenv("KAJOVODAGMAR_PUBLIC_ORIGIN", "https://testserver")
    monkeypatch.setenv("KAJOVODAGMAR_METRICS_TOKEN", "synthetic-metrics-token")
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="https://testserver") as client:
        assert client.get("/api/v1/metrics").status_code == 404
        accepted = client.get(
            "/api/v1/metrics",
            headers={"Authorization": "Bearer synthetic-metrics-token"},
        )
        assert accepted.status_code == 200
        assert "kajovodagmar_http_requests_total" in accepted.text
    get_settings.cache_clear()
