from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from apps.backend.tests._schema import migrate_db
from app.config import get_settings
from app.services.retrieval import RetrievalService
from app.utils.time import local_timezone_label, local_timezone_name


def test_local_timezone_name_is_valid_iana_matching_local_offset() -> None:
    name = local_timezone_name()
    zone = ZoneInfo(name)  # 绝不抛 ZoneInfoNotFoundError
    now = datetime.now()
    assert zone.utcoffset(now) == now.astimezone().utcoffset()
    assert local_timezone_label()


def test_habit_quiet_window_follows_parameterized_hours() -> None:
    from app.services.habit_loop import _is_quiet_time, _next_quiet_end

    evening = datetime(2026, 6, 7, 23, 30, tzinfo=timezone.utc)
    morning = datetime(2026, 6, 8, 7, 30, tzinfo=timezone.utc)
    day = datetime(2026, 6, 7, 12, 0, tzinfo=timezone.utc)

    assert _is_quiet_time(evening, 22, 8)
    assert _is_quiet_time(morning, 22, 8)
    assert not _is_quiet_time(day, 22, 8)

    # 自定义窗口（23-9）：22:00 不再是静默时段
    assert not _is_quiet_time(datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc), 23, 9)
    assert _is_quiet_time(evening, 23, 9)
    assert _next_quiet_end(morning, 9).hour == 9
    assert _next_quiet_end(day, 9).day == day.day + 1


def test_habit_policy_respects_tuning_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_PET_TUNING_HABIT_DAILY_LIMIT", "7")
    monkeypatch.setenv("AGENT_PET_TUNING_HABIT_COOLDOWN_MINUTES", "11")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.tuning_habit_daily_limit == 7
    finally:
        get_settings.cache_clear()


def test_retrieval_rrf_k_and_fts_weight_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_PET_TUNING_RRF_K", "42")
    monkeypatch.setenv("AGENT_PET_TUNING_FTS_EXACT_WEIGHT", "5.0")
    get_settings.cache_clear()
    try:
        db = Database_for_test(tmp_path)
        service = RetrievalService(db)
        service.initialize()
        vault = tmp_path / "vault"
        vault.mkdir()
        (vault / "Memory.md").write_text("# M\n\nAPOLLO-17 checklist lives here.", encoding="utf-8")
        vault_id = service.bind_vault(str(vault))
        service.rebuild_index(vault_id)

        response = service.search(vault_id=vault_id, query="APOLLO-17 是什么？", mode="hybrid", top_k=5)

        assert response.metadata["fusion"]["rrf_k"] == 42
        assert response.metadata["fusion"]["channel_weights"].get("fts") == 5.0
    finally:
        get_settings.cache_clear()


def Database_for_test(tmp_path: Path):
    from app.storage.database import Database

    return Database(tmp_path / "retrieval.sqlite3")


def test_stream_retry_recovers_before_first_chunk() -> None:
    from app.services.chat_model import LangChainGraphChatClient

    class FlakyStreamingModel:
        def __init__(self) -> None:
            self.attempts = 0

        async def astream(self, messages):
            self.attempts += 1
            if self.attempts == 1:
                class RateLimitError(Exception):
                    status_code = 429

                raise RateLimitError("rate limit reached")
            for chunk in ("你", "好"):
                payload = type("_M", (), {"content": chunk})()
                yield payload

    model = FlakyStreamingModel()
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: model,
    )

    collect = asyncio.run(_collect(client))

    assert collect == ["你", "好"]
    assert model.attempts == 2


async def _collect(client) -> list[str]:
    return [chunk async for chunk in client.stream_complete(user_message="hello")]
