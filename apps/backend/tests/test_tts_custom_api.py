from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers


@pytest.fixture()
def client(client_factory) -> TestClient:
    with client_factory() as test_client:
        yield test_client


def test_custom_tts_settings_key_and_synthesis_do_not_leak_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    secret = "tts-secret-value-1234567890"
    audio = b"fake-mp3-audio"

    class FakeResponse:
        status = 200
        headers = {"content-type": "audio/mpeg"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return audio

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("app.services.tts.urllib.request.urlopen", fake_urlopen)

    settings_response = client.put(
        "/api/settings/tts",
        headers=auth_headers(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "provider": "custom-http",
            "base_url": "https://tts.example.test/synthesize",
            "model": "user-model",
            "voice": {"id": "voice-1", "provider": "custom-http", "label": "Voice 1"},
            "speed": 1.1,
            "volume": 0.7,
            "response_format": "mp3",
            "requires_api_key": True,
        },
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["status"] == "credential_missing"

    key_response = client.put(
        "/api/settings/tts-key",
        headers=auth_headers(),
        json={"provider": "custom-http", "api_key": secret},
    )
    assert key_response.status_code == 200
    assert secret not in key_response.text
    assert key_response.json()["masked"] != secret

    status_response = client.get("/api/settings/tts", headers=auth_headers())
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "ready"
    assert status_response.json()["key_configured"] is True
    assert secret not in status_response.text

    synthesis_response = client.post(
        "/api/tts/synthesize",
        headers=auth_headers(),
        json={"text": "hello", "provider": "custom-http", "speed": 1.2, "volume": 0.5},
    )
    assert synthesis_response.status_code == 200
    payload = synthesis_response.json()
    assert payload["provider"] == "custom-http"
    assert payload["mime_type"] == "audio/mpeg"
    assert base64.b64decode(payload["audio_base64"]) == audio
    assert captured["url"] == "https://tts.example.test/synthesize"
    assert captured["headers"]["Authorization"] == f"Bearer {secret}"
    assert captured["body"] == {
        "text": "hello",
        "model": "user-model",
        "voice": "voice-1",
        "voice_label": "Voice 1",
        "speed": 1.2,
        "volume": 0.5,
        "response_format": "mp3",
    }
    assert secret not in synthesis_response.text


def test_tts_synthesis_requires_configured_provider(client: TestClient) -> None:
    response = client.post(
        "/api/tts/synthesize",
        headers=auth_headers(),
        json={"text": "hello", "provider": "custom-http", "speed": 1, "volume": 1},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "disabled"


def test_xiaomi_mimo_tts_preset_uses_user_selected_api_shape(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    secret = "mimo-secret-value-1234567890"
    audio = base64.b64encode(b"fake-wav-audio").decode("ascii")

    class FakeResponse:
        status = 200
        headers = {"content-type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return json.dumps({"choices": [{"message": {"audio": {"data": audio}}}]}).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("app.services.tts.urllib.request.urlopen", fake_urlopen)

    settings_response = client.put(
        "/api/settings/tts",
        headers=auth_headers(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "provider": "xiaomi-mimo",
            "base_url": "https://api.xiaomimimo.com/v1/chat/completions",
            "model": "tts11-voice",
            "voice": {"id": "tts11-voice", "provider": "xiaomi-mimo", "label": "tts11-voice"},
            "response_format": "mp3",
            "requires_api_key": True,
            "auth_header_name": "api-key",
            "audio_json_path": "choices.0.message.audio.data",
            "mime_type": "audio/wav",
        },
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["model"] == "mimo-v2.5-tts"
    assert settings_response.json()["voice"]["id"] == "Chloe"
    assert settings_response.json()["response_format"] == "wav"

    key_response = client.put(
        "/api/settings/tts-key",
        headers=auth_headers(),
        json={"provider": "xiaomi-mimo", "api_key": secret},
    )
    assert key_response.status_code == 200

    synthesis_response = client.post(
        "/api/tts/synthesize",
        headers=auth_headers(),
        json={"text": "hello", "provider": "xiaomi-mimo", "speed": 1, "volume": 1},
    )

    assert synthesis_response.status_code == 200
    payload = synthesis_response.json()
    assert payload["provider"] == "xiaomi-mimo"
    assert payload["mime_type"] == "audio/wav"
    assert base64.b64decode(payload["audio_base64"]) == b"fake-wav-audio"
    assert captured["url"] == "https://api.xiaomimimo.com/v1/chat/completions"
    assert captured["headers"]["Api-key"] == secret
    assert "Authorization" not in captured["headers"]
    assert captured["body"] == {
        "model": "mimo-v2.5-tts",
        "messages": [
            {"role": "user", "content": "Please read the assistant text naturally."},
            {"role": "assistant", "content": "hello"},
        ],
        "audio": {"voice": "Chloe", "format": "wav"},
    }
    assert secret not in synthesis_response.text


def test_tts_synthesis_rejects_non_audio_response(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResponse:
        status = 200
        headers = {"content-type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self) -> bytes:
            return b"not audio"

    def fake_urlopen(request, timeout):
        return FakeResponse()

    monkeypatch.setattr("app.services.tts.urllib.request.urlopen", fake_urlopen)
    settings_response = client.put(
        "/api/settings/tts",
        headers=auth_headers(),
        json={
            "enabled": True,
            "auto_play_assistant_reply": True,
            "provider": "custom-http",
            "base_url": "https://tts.example.test/synthesize",
            "speed": 1,
            "volume": 1,
            "response_format": "mp3",
            "requires_api_key": False,
        },
    )
    assert settings_response.status_code == 200
    assert settings_response.json()["status"] == "ready"

    response = client.post(
        "/api/tts/synthesize",
        headers=auth_headers(),
        json={"text": "hello", "provider": "custom-http", "speed": 1, "volume": 1},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "invalid_audio"
