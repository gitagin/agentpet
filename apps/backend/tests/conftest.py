from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


FORBIDDEN_HEALTH_KEYS = {
    "active_vault_id",
    "vault_id",
    "vault_path",
    "root_path",
    "model_provider",
    "model_base_url",
    "chat_model",
    "model_config",
    "api_key",
    "token",
    "authorization",
    "username",
}


def auth_headers(token: str = "test-token", *, request_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if request_id is not None:
        headers["X-Request-ID"] = request_id
    return headers


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


def iter_keys(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key)
            yield from iter_keys(nested)
    elif isinstance(value, list):
        for item in value:
            yield from iter_keys(item)


def parse_sse_events(body: str) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        current[field] = value.lstrip()
    if current:
        events.append(current)
    return events


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


@pytest.fixture()
def client_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[..., Iterator[TestClient]]:
    @contextmanager
    def create(
        *,
        session_token: str = "test-token",
        sqlite_name: str = "state.sqlite3",
        data_dir: Path | None = None,
    ) -> Iterator[TestClient]:
        monkeypatch.setenv("AGENT_PET_SESSION_TOKEN", session_token)
        monkeypatch.setenv("AGENT_PET_SQLITE_PATH", str(tmp_path / sqlite_name))
        if session_token != "hardening-token":
            monkeypatch.setenv("AGENT_PET_ALLOW_INSECURE_FILE_CREDENTIALS", "1")
        # 未显式指定 data_dir 时也隔离到 tmp：否则所有 TestClient 应用共享
        # 真实 %LOCALAPPDATA%\AgentPet 数据目录（vector-index/.lock、凭据、缓存），
        # 前序测试的 Qdrant 客户端会把后续应用的健康状态污染成 degraded。
        monkeypatch.setenv("AGENT_PET_DATA_DIR", str(data_dir or tmp_path / "data-dir"))

        from app.main import create_app

        with TestClient(create_app()) as client:
            yield client

    return create


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live-model",
        action="store_true",
        default=False,
        help="run tests marked live_model that call a real model provider",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live-model"):
        return
    skip_live = pytest.mark.skip(reason="live model tests require --run-live-model")
    for item in items:
        if "live_model" in item.keywords:
            item.add_marker(skip_live)
