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


def test_health_all_default(client: TestClient) -> None:
    response = client.get("/api/settings/model-health", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "global_configured",
        "agents_configured",
        "agents_fallback_to_global",
        "agents_fallback_to_default",
        "agent_details",
    }
    assert payload["global_configured"] is False
    assert payload["agents_configured"] == 0
    assert payload["agents_fallback_to_global"] == 0
    assert payload["agents_fallback_to_default"] == 9
    assert len(payload["agent_details"]) == 9
    assert {detail["source"] for detail in payload["agent_details"]} == {"hardcoded_default"}


def test_health_global_only(client: TestClient) -> None:
    config = client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://model.example.test/v1",
            "model": "global-model",
        },
    )
    key = client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-global-secret"},
    )

    response = client.get("/api/settings/model-health", headers=auth())

    assert config.status_code == 200
    assert key.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert payload["global_configured"] is True
    assert payload["agents_configured"] == 0
    assert payload["agents_fallback_to_global"] == 9
    assert payload["agents_fallback_to_default"] == 0
    assert {detail["source"] for detail in payload["agent_details"]} == {"global_fallback"}
    assert {detail["model"] for detail in payload["agent_details"]} == {"global-model"}


def test_update_settings_reports_agents_using_global(client: TestClient) -> None:
    key = client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-global-secret"},
    )
    update = client.patch(
        "/api/settings",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://model.example.test/v1",
            "model": "global-model",
        },
    )
    health = client.get("/api/settings/model-health", headers=auth())

    assert key.status_code == 200
    assert update.status_code == 200
    assert health.status_code == 200
    assert "agents_using_global" in update.json()
    assert update.json()["agents_using_global"] == health.json()["agents_fallback_to_global"]


def test_health_mixed(client: TestClient) -> None:
    client.put(
        "/api/settings/model-config",
        headers=auth(),
        json={
            "provider": "openai-compatible",
            "base_url": "https://model.example.test/v1",
            "model": "global-model",
        },
    )
    client.put(
        "/api/settings/model-key",
        headers=auth(),
        json={"provider": "openai-compatible", "api_key": "sk-global-secret"},
    )
    for agent_id in ("chat_agent", "task_agent"):
        response = client.put(
            f"/api/settings/agent-models/{agent_id}/config",
            headers=auth(),
            json={
                "provider": "openai-compatible",
                "base_url": "https://agent.example.test/v1",
                "model": f"{agent_id}-model",
                "enabled": True,
            },
        )
        assert response.status_code == 200

    response = client.get("/api/settings/model-health", headers=auth())

    assert response.status_code == 200
    payload = response.json()
    assert payload["global_configured"] is True
    assert payload["agents_configured"] == 2
    assert payload["agents_fallback_to_global"] == 7
    assert payload["agents_fallback_to_default"] == 0
    details = {detail["agent_id"]: detail for detail in payload["agent_details"]}
    assert details["chat_agent"]["source"] == "agent_specific"
    assert details["task_agent"]["source"] == "agent_specific"
