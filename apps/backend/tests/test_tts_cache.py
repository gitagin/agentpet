from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.conftest import auth_headers


@pytest.fixture()
def client(client_factory, tmp_path: Path) -> Iterator[TestClient]:
    with client_factory(data_dir=tmp_path / "data") as test_client:
        yield test_client


def configure_custom_tts(client: TestClient) -> None:
    response = client.put(
        "/api/settings/tts",
        headers=auth_headers(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "provider": "custom-http",
            "base_url": "https://tts.example.test/synthesize",
            "voice": {"id": "voice-1", "provider": "custom-http", "label": "Voice 1"},
            "speed": 1,
            "volume": 1,
            "response_format": "mp3",
            "cache_enabled": True,
            "requires_api_key": False,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_tts_synthesis_uses_disk_cache_and_can_clear_it(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status = 200
        headers = {"content-type": "audio/mpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return f"audio-{len(calls)}".encode("utf-8")

    def fake_urlopen(request, timeout):
        calls.append({"body": json.loads(request.data.decode("utf-8")), "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("app.services.tts.urllib.request.urlopen", fake_urlopen)
    configure_custom_tts(client)

    request = {"text": "hello cache", "provider": "custom-http", "speed": 1, "volume": 1}
    first = client.post("/api/tts/synthesize", headers=auth_headers(), json=request)
    second = client.post("/api/tts/synthesize", headers=auth_headers(), json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is True
    assert second.json()["audio_base64"] == base64.b64encode(b"audio-1").decode("ascii")
    assert len(calls) == 1

    cache_root = get_settings().data_dir / "cache" / "tts"
    assert cache_root.exists()
    assert list(cache_root.rglob("*.audio"))

    cleared = client.delete("/api/tts/cache", headers=auth_headers())
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "cleared"
    assert cleared.json()["cleared_entries"] >= 2
    assert list(cache_root.rglob("*")) == []

    third = client.post("/api/tts/synthesize", headers=auth_headers(), json=request)
    assert third.status_code == 200
    assert third.json()["cache_hit"] is False
    assert len(calls) == 2


def test_tts_cache_skips_sensitive_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    class FakeResponse:
        status = 200
        headers = {"content-type": "audio/mpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b"audio-sensitive"

    def fake_urlopen(request, timeout):
        nonlocal calls
        calls += 1
        return FakeResponse()

    monkeypatch.setattr("app.services.tts.urllib.request.urlopen", fake_urlopen)
    configure_custom_tts(client)

    request = {"text": "api_key=secret-value-123", "provider": "custom-http", "speed": 1, "volume": 1}
    first = client.post("/api/tts/synthesize", headers=auth_headers(), json=request)
    second = client.post("/api/tts/synthesize", headers=auth_headers(), json=request)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["cache_hit"] is False
    assert second.json()["cache_hit"] is False
    assert calls == 2
