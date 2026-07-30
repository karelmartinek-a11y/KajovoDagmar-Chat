from __future__ import annotations

from fastapi.testclient import TestClient

import pytest

pytestmark = pytest.mark.integration

PASSWORD = "Bezpečná integrační věta pro rok 2026"
INITIALIZATION_SECRET = "synthetic-e2e-initialization-secret"


def assert_status(response, expected: int) -> dict:
    assert response.status_code == expected, response.text
    return response.json() if response.content else {}


def test_authenticated_api_lifecycle(api_client: TestClient) -> None:
    assert assert_status(api_client.get("/api/v1/health/live"), 200) == {"status": "ok"}
    assert assert_status(api_client.get("/api/v1/auth/state"), 200)[
        "instance_state"
    ] == ("uninitialized")
    validation = api_client.post("/api/v1/auth/login", json={})
    assert assert_status(validation, 422)["error"]["code"] == "validation_failed"

    initialized = assert_status(
        api_client.post(
            "/api/v1/auth/initialize",
            json={
                "username": "Karmar78",
                "initialization_secret": INITIALIZATION_SECRET,
                "password": PASSWORD,
                "password_confirmation": PASSWORD,
                "display_name": "Integrační správce",
                "email": "integration@example.com",
            },
        ),
        201,
    )
    assert initialized["state"] == "active"
    assert (
        assert_status(api_client.get("/api/v1/auth/state"), 200)["instance_state"]
        == "active"
    )

    bad_login = api_client.post(
        "/api/v1/auth/login",
        json={"username": "Karmar78", "password": "nesprávné heslo"},
    )
    assert bad_login.status_code == 401
    login = assert_status(
        api_client.post(
            "/api/v1/auth/login", json={"username": "Karmar78", "password": PASSWORD}
        ),
        200,
    )
    csrf = {"X-CSRF-Token": login["csrf_token"]}

    me = assert_status(api_client.get("/api/v1/auth/me"), 200)
    assert me["profile"]["display_name"] == "Integrační správce"
    assert (
        len(assert_status(api_client.get("/api/v1/auth/sessions"), 200)["items"]) == 1
    )
    assert (
        assert_status(api_client.get("/api/v1/profile"), 200)["username"] == "Karmar78"
    )
    assert (
        assert_status(api_client.get("/api/v1/health/ready"), 200)["status"] == "ready"
    )
    assert (
        assert_status(api_client.get("/api/v1/operations/status"), 200)["jobs_pending"]
        == 0
    )
    assert api_client.get("/api/v1/metrics").status_code == 200

    settings = assert_status(api_client.get("/api/v1/settings"), 200)
    assert settings["conversation"]["verbosity"]["value"] == "balanced"
    changed = assert_status(
        api_client.put(
            "/api/v1/settings/conversation",
            headers=csrf,
            json={"changes": {"verbosity": {"value": "detailed", "version": 0}}},
        ),
        200,
    )
    assert changed["verbosity"]["version"] == 1
    history = assert_status(
        api_client.get("/api/v1/settings/conversation/verbosity/history"), 200
    )
    assert history["items"][0]["value"] == "detailed"
    restored = assert_status(
        api_client.post(
            "/api/v1/settings/conversation/verbosity/restore",
            headers=csrf,
            json={"revision_number": 1, "expected_version": 1},
        ),
        200,
    )
    assert restored["version"] == 2

    memory = assert_status(
        api_client.post(
            "/api/v1/memory",
            headers=csrf,
            json={
                "content": "Integrační správce upřednostňuje stručný ranní přehled.",
                "category": "preference",
                "origin_type": "manual",
                "confirmed": True,
            },
        ),
        201,
    )
    memory_id = memory["id"]
    assert assert_status(api_client.get(f"/api/v1/memory/{memory_id}"), 200)[
        "content"
    ].startswith("Integrační")
    assert (
        assert_status(
            api_client.post(
                "/api/v1/memory/search",
                json={"query": "", "states": ["active"], "limit": 20, "offset": 0},
            ),
            200,
        )["count"]
        == 1
    )
    updated = assert_status(
        api_client.put(
            f"/api/v1/memory/{memory_id}",
            headers=csrf,
            json={
                "expected_version": memory["version"],
                "content": "Integrační správce upřednostňuje podrobný ranní přehled.",
            },
        ),
        200,
    )
    deleted = assert_status(
        api_client.request(
            "DELETE",
            f"/api/v1/memory/{memory_id}",
            headers=csrf,
            json={"expected_version": updated["version"]},
        ),
        200,
    )
    restored_memory = assert_status(
        api_client.post(
            f"/api/v1/memory/{memory_id}/restore",
            headers=csrf,
            json={"expected_version": deleted["version"]},
        ),
        200,
    )
    assert restored_memory["state"] == "active"

    conversation = assert_status(
        api_client.post(
            "/api/v1/conversations",
            headers=csrf,
            json={"input_mode": "text", "language": "cs"},
        ),
        201,
    )
    conversation_id = conversation["id"]
    ended = assert_status(
        api_client.post(
            f"/api/v1/conversations/{conversation_id}/end",
            headers=csrf,
            json={"reason": "integration_complete"},
        ),
        200,
    )
    metadata = assert_status(
        api_client.put(
            f"/api/v1/history/{conversation_id}/metadata",
            headers=csrf,
            json={
                "expected_version": ended["version"],
                "title": "Integrační konverzace",
                "summary": "Ověřený lifecycle.",
            },
        ),
        200,
    )
    assert (
        assert_status(api_client.get(f"/api/v1/history/{conversation_id}"), 200)[
            "conversation"
        ]["title"]
        == "Integrační konverzace"
    )
    continued = assert_status(
        api_client.post(f"/api/v1/history/{conversation_id}/continue", headers=csrf),
        201,
    )
    assert continued["continuation_of_id"] == conversation_id
    removed = assert_status(
        api_client.request(
            "DELETE",
            f"/api/v1/history/{conversation_id}",
            headers=csrf,
            json={"expected_version": metadata["version"]},
        ),
        200,
    )
    assert (
        assert_status(
            api_client.post(
                f"/api/v1/history/{conversation_id}/restore",
                headers=csrf,
                json={"expected_version": removed["version"]},
            ),
            200,
        )["state"]
        == "completed"
    )

    export = assert_status(
        api_client.post(
            "/api/v1/exports",
            headers=csrf,
            json={"kind": "memory", "format": "json", "scope": {"all": True}},
        ),
        202,
    )
    assert assert_status(api_client.get("/api/v1/exports"), 200)["items"]
    assert assert_status(api_client.get(f"/api/v1/exports/{export['id']}"), 200)[
        "state"
    ] == ("queued")
    assert api_client.get(f"/api/v1/exports/{export['id']}/download").status_code == 409
    assert assert_status(api_client.post("/api/v1/realtime/ticket", headers=csrf), 200)[
        "ticket"
    ]

    assert api_client.post("/api/v1/auth/logout", headers=csrf).status_code == 204
    assert api_client.get("/api/v1/auth/me").status_code == 401
