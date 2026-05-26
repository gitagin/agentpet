from collections.abc import Iterator

import pytest

from fastapi.testclient import TestClient

from tests.conftest import FORBIDDEN_HEALTH_KEYS, assert_error_shape, iter_keys


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


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
