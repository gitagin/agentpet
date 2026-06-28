from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Iterator

from fastapi.testclient import TestClient

from tests.conftest import auth_headers, parse_sse_events


def auth() -> dict[str, str]:
    return auth_headers()


class RecordingModelServer(ThreadingHTTPServer):
    request_count: int
    request_bodies: list[str]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), RecordingModelHandler)
        self.request_count = 0
        self.request_bodies = []


class RecordingModelHandler(BaseHTTPRequestHandler):
    server: RecordingModelServer

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0") or "0")
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        self.server.request_count += 1
        self.server.request_bodies.append(body)
        payload = {
            "id": "local-test-response",
            "object": "chat.completion",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "remote model should not be called"},
                    "finish_reason": "stop",
                }
            ],
        }
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextmanager
def fake_model_server() -> Iterator[tuple[RecordingModelServer, str]]:
    server = RecordingModelServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield server, f"http://{host}:{port}/v1"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def stream_chat(client: TestClient, message: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    accepted = client.post("/api/chat", headers=auth(), json={"message": message})
    assert accepted.status_code == 200
    payload = accepted.json()
    with client.stream("GET", payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    return payload, parse_sse_events(body)


def test_local_privacy_mode_blocks_sensitive_chat_from_model_network(client_factory) -> None:
    with fake_model_server() as (server, base_url), client_factory() as client:
        config = client.put(
            "/api/settings/model-config",
            headers=auth(),
            json={
                "provider": "openai-compatible",
                "base_url": base_url,
                "model": "network-sentinel-model",
            },
        )
        assert config.status_code == 200
        key = client.put(
            "/api/settings/model-key",
            headers=auth(),
            json={
                "provider": "openai-compatible",
                "api_key": "test-local-model-key",
            },
        )
        assert key.status_code == 200
        automation = client.put(
            "/api/settings/automation",
            headers=auth(),
            json={
                "auto_chat_diary": True,
                "auto_structured_memory": True,
                "auto_long_term_memory": True,
                "auto_wiki_organize": True,
                "local_privacy_mode": True,
                "use_negotiation": True,
                "max_rounds": 2,
            },
        )
        assert automation.status_code == 200
        assert automation.json()["local_privacy_mode"] is True

        payload, events = stream_chat(
            client,
            "请记一下：api_key=private-value-123456，这是我想保护的敏感内容。",
        )

        event_names = [event["event"] for event in events]
        assert event_names == ["status", "token", "reply_ready", "done"]
        token_text = "".join(
            json.loads(event["data"])["text"]
            for event in events
            if event["event"] == "token"
        )
        assert "本地隐私模式" in token_text
        assert "没有把原文发送到模型 API" in token_text
        assert "关键词检索" in token_text

        time.sleep(0.2)
        assert server.request_count == 0
        assert server.request_bodies == []

        with sqlite3.connect(client.app.state.database.path) as conn:
            user_message = conn.execute(
                """
                SELECT content
                FROM messages
                WHERE conversation_id = ? AND role = 'user'
                """,
                (payload["conversation_id"],),
            ).fetchone()[0]
            conversation_title = conn.execute(
                "SELECT title FROM conversations WHERE id = ?",
                (payload["conversation_id"],),
            ).fetchone()[0]

        assert user_message.startswith("[local privacy mode redacted sensitive user message]")
        assert conversation_title.startswith("[local privacy mode redacted sensitive user message]")
        assert "private-value-123456" not in user_message
        assert "private-value-123456" not in conversation_title
