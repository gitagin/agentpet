from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers


@pytest.fixture()
def client(client_factory, tmp_path: Path) -> Iterator[TestClient]:
    with client_factory(data_dir=tmp_path / "data") as test_client:
        yield test_client


def auth() -> dict[str, str]:
    return auth_headers()


def test_embedding_settings_are_persisted_separately_from_chat_model(client: TestClient) -> None:
    config = client.put(
        "/api/settings/embedding-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://embed.example.test/v1/",
            "model": "text-embedding-3-small",
            "dimensions": 128,
        },
    )
    key = client.put(
        "/api/settings/embedding-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-embedding-secret"},
    )
    status = client.get("/api/settings", headers=auth())

    assert config.status_code == 200
    assert config.json()["status"] == "missing_key"
    assert key.status_code == 200
    assert key.json()["configured"] is True
    assert key.json()["masked"] == "****cret"
    payload = status.json()
    assert payload["embedding_base_url"] == "https://embed.example.test/v1"
    assert payload["embedding_model"] == "text-embedding-3-small"
    assert payload["embedding_dimensions"] == 128
    assert payload["embedding_configured"] is True
    assert "sk-embedding-secret" not in status.text


def test_embedding_test_reports_missing_key(client: TestClient) -> None:
    response = client.post("/api/settings/embedding-test", headers=auth())

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error_code"] == "not_configured"
