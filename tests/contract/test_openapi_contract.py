from __future__ import annotations

from kajovodagmar.main import create_app


def test_versioned_rest_and_realtime_paths_exist() -> None:
    app = create_app()
    # Starlette 1.x keeps included routers nested. OpenAPI is the public REST
    # contract and therefore the stable source for versioned HTTP paths.
    paths = set(app.openapi()["paths"])
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/memory/search" in paths
    assert "/api/v1/history/search" in paths
    websocket_paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/realtime" in websocket_paths


def test_openapi_has_stable_error_capable_endpoints() -> None:
    schema = create_app().openapi()
    assert schema["info"]["version"] == "1.0.0"
    assert "/api/v1/conversations/{conversation_id}/turns" in schema["paths"]
