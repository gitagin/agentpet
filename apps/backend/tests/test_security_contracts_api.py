from collections.abc import Iterator
from typing import Any

import pytest

from fastapi.testclient import TestClient


FORBIDDEN_HEALTH_KEYS = {
    "active_vault_id",
    "vault_id",
    "vault_path",
    "root_path",
    "model_provider",
    "model_config",
    "api_key",
    "token",
    "authorization",
    "username",
}


def iter_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from iter_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from iter_keys(item)


@pytest.fixture()
def client() -> TestClient:
    main = pytest.importorskip(
        "app.main",
        reason="FastAPI entrypoint app.main is not implemented yet; endpoint contracts activate once it exists.",
    )
    app = getattr(main, "app", None)
    if app is None:
        pytest.skip("app.main must expose a FastAPI instance named app.")
    return TestClient(app)


def assert_error_shape(payload: dict[str, Any]) -> None:
    assert set(payload) == {"error"}
    error = payload["error"]
    assert isinstance(error, dict)
    assert {"code", "message", "request_id", "details"}.issubset(error)
    assert isinstance(error["code"], str)
    assert error["code"]
    assert isinstance(error["message"], str)
    assert error["message"]
    assert isinstance(error["request_id"], str)
    assert error["request_id"]
    assert isinstance(error["details"], dict)


def test_health_endpoint_is_unauthenticated_and_does_not_leak_vault_state(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert FORBIDDEN_HEALTH_KEYS.isdisjoint({key.lower() for key in iter_keys(payload)})


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/vaults/status"),
        ("POST", "/api/vaults/init"),
        ("POST", "/api/chat"),
        ("GET", "/api/chat/runs/test-run-id/events"),
        ("POST", "/api/memory/search"),
        ("POST", "/api/memory/proposals"),
        ("POST", "/api/tasks"),
        ("PUT", "/api/settings/model-key"),
        ("PUT", "/api/settings/model-config"),
        ("POST", "/api/settings/model-test"),
    ],
)
def test_non_health_endpoints_require_authorization(
    client: TestClient,
    method: str,
    path: str,
) -> None:
    response = client.request(method, path, json={})

    assert response.status_code == 401
    assert_error_shape(response.json())


@pytest.mark.parametrize(
    "authorization",
    [
        "",
        "Bearer",
        "Basic abc123",
        "Bearer invalid-session-token",
    ],
)
def test_invalid_authorization_is_rejected_with_error_shape(
    client: TestClient,
    authorization: str,
) -> None:
    headers = {"Authorization": authorization} if authorization else {}
    response = client.get("/api/vaults/status", headers=headers)

    assert response.status_code == 401
    assert_error_shape(response.json())
