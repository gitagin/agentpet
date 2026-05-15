from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", "test-token")
    monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("AGENT_PET_DATA_DIR", str(tmp_path / "data"))

    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


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
    assert key.json()["masked"] == "sk...et"
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
