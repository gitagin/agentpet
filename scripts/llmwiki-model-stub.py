from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


_WIKI_TARGET = re.compile(r"\bWiki/[A-Za-z0-9._/-]+\.md\b")


def _message_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return " ".join(
                str(item.get("text") or "")
                for item in content
                if isinstance(item, dict) and item.get("type") == "text"
            )
    return ""


def _classifier_payload(user_message: str) -> dict[str, Any]:
    target_match = _WIKI_TARGET.search(user_message.replace("\\", "/"))
    target_path = target_match.group(0) if target_match is not None else None
    if target_path is None or ".." in target_path.split("/"):
        return {
            "intent": "action",
            "retrieval_scope": None,
            "retrieval_query": None,
            "action_type": "wiki",
            "action_params": {
                "kind": "page",
                "title": "Unbound high-risk request",
                "content": "No explicit safe Wiki target was available.",
            },
            "confidence": 0.0,
            "reason": "explicit_target_missing",
        }
    title = target_path.rsplit("/", 1)[-1].removesuffix(".md")
    return {
        "intent": "action",
        "retrieval_scope": None,
        "retrieval_query": None,
        "action_type": "wiki",
        "action_params": {
            "kind": "page",
            "title": title,
            "content": f"Verified high-risk checkpoint evidence for {title}.",
            "target_path": target_path,
        },
        "confidence": 0.99,
        "reason": "explicit_high_risk_target",
    }


class ModelStubHandler(BaseHTTPRequestHandler):
    server: ThreadingHTTPServer

    def do_GET(self) -> None:
        if self.path != "/health":
            self.send_error(404)
            return
        self._write_json({"status": "ok"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400)
            return
        if not isinstance(payload, dict):
            self.send_error(400)
            return
        classifier = _classifier_payload(_message_text(payload))
        target = classifier["action_params"].get("target_path", "unbound")
        print(f"MODEL_STUB_REQUEST target={target}", flush=True)
        self._write_json(
            {
                "id": f"llmwiki-stub-{time.time_ns()}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": str(payload.get("model") or "llmwiki-stub"),
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(classifier, ensure_ascii=False),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 1,
                    "total_tokens": 2,
                },
            }
        )

    def _write_json(self, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ModelStubHandler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
