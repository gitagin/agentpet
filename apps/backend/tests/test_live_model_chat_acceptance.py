from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.conftest import auth_headers, parse_sse_events


REQUIRED_LIVE_MODEL_ENV = (
    "LIVE_MODEL_BASE_URL",
    "LIVE_CHAT_MODEL",
    "LIVE_MODEL_API_KEY",
)


def auth() -> dict[str, str]:
    return auth_headers()


@pytest.mark.live_model
def test_live_model_chat_stream_uses_vault_citation_when_configured(
    tmp_path: Path,
    client_factory,
) -> None:
    live_env = {name: os.getenv(name) for name in REQUIRED_LIVE_MODEL_ENV}
    missing = [name for name, value in live_env.items() if not value]
    if missing:
        pytest.skip(f"live model gate skipped; missing env vars: {', '.join(missing)}")

    with client_factory() as client:
        vault = tmp_path / "Vault"
        vault.mkdir()
        (vault / "LiveGate.md").write_text(
            "# Live Gate\n\n"
            "The live acceptance sentinel is zircon-raven-482. "
            "Ada prefers concise status updates.\n",
            encoding="utf-8",
        )

        bind = client.post(
            "/api/vaults/init",
            headers=auth(),
            json={"path": str(vault), "create_if_missing": False, "confirmed": True},
        )
        assert bind.status_code == 200
        indexed = client.post(f"/api/vaults/{bind.json()['vault_id']}/index", headers=auth())
        assert indexed.status_code == 200
        assert indexed.json()["files_indexed"] == 1

        config = client.put(
            "/api/settings/model-config",
            headers=auth(),
            json={
                "provider": "openai-compatible",
                "base_url": live_env["LIVE_MODEL_BASE_URL"],
                "model": live_env["LIVE_CHAT_MODEL"],
            },
        )
        assert config.status_code == 200
        key = client.put(
            "/api/settings/model-key",
            headers=auth(),
            json={
                "provider": "openai-compatible",
                "api_key": live_env["LIVE_MODEL_API_KEY"],
            },
        )
        assert key.status_code == 200

        model_test = client.post("/api/settings/model-test", headers=auth())
        assert model_test.status_code == 200
        assert model_test.json()["status"] == "ok", model_test.json()

        chat = client.post(
            "/api/chat",
            headers=auth(),
            json={"message": "What does the vault say about zircon-raven-482 and Ada preference?"},
        )
        assert chat.status_code == 200
        with client.stream("GET", chat.json()["stream_url"], headers=auth()) as stream:
            events = parse_sse_events("".join(stream.iter_text()))

        event_names = [event.get("event") for event in events]
        assert "error" not in event_names
        assert "citation" in event_names
        assert "token" in event_names
        assert event_names[-1] == "done"

        citation_payloads = [
            json.loads(event["data"])
            for event in events
            if event.get("event") == "citation"
        ]
        assert any(
            payload["citation"]["relative_path"] == "LiveGate.md"
            for payload in citation_payloads
        )
        token_text = "".join(
            json.loads(event["data"])["text"]
            for event in events
            if event.get("event") == "token"
        )
        assert token_text.strip()
