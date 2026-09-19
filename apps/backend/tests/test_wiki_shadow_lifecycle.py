import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models.config import AutomationSettingsRequest
from app.services.settings import SettingsStore
from app.services.wiki.shadow import ShadowMetricStore
from app.storage.database import Database, MigrationRunner
from tests.conftest import auth_headers


def make_database(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    MigrationRunner(database).apply()
    return database


def test_shadow_api_opt_in_and_startup_retention(client_factory, tmp_path):
    database = make_database(tmp_path)
    metrics = ShadowMetricStore(database)
    now = datetime.now(timezone.utc)
    recent_id = metrics.reserve(now=now - timedelta(days=1))
    metrics.reserve(now=now - timedelta(days=8))
    with client_factory() as client:
        headers = auth_headers()
        assert client.get("/api/settings/automation", headers=headers).json()["wiki_shadow_enabled"] is False
        with database.session() as conn:
            saved = json.loads(conn.execute(
                "SELECT value FROM app_state WHERE key = 'wiki_shadow_metrics_v1'"
            ).fetchone()["value"])
        assert [item["id"] for item in saved] == [recent_id]
        enabled = client.put(
            "/api/settings/automation", headers=headers, json={"wiki_shadow_enabled": True},
        )
        assert enabled.status_code == 200
        assert enabled.json()["wiki_shadow_enabled"] is True
        legacy = client.put(
            "/api/settings/automation", headers=headers, json={"auto_wiki_organize": False},
        )
        assert legacy.json()["wiki_shadow_enabled"] is True
        rejected = client.put(
            "/api/settings/automation", headers=headers, json={"wiki_shadow_enabled": "true"},
        )
        assert rejected.status_code == 422
        disabled = client.put(
            "/api/settings/automation", headers=headers, json={"wiki_shadow_enabled": False},
        )
        assert disabled.json()["wiki_shadow_enabled"] is False


def test_shadow_setting_reopen_and_invalid_storage_fail_closed(tmp_path):
    database = make_database(tmp_path)
    store = SettingsStore(database)
    store.set_automation_settings(AutomationSettingsRequest(wiki_shadow_enabled=True))
    store.close()
    reopened = SettingsStore(database)
    try:
        assert reopened.get_automation_settings().wiki_shadow_enabled is True
        for value in ('"true"', "1", "null", "invalid"):
            with reopened.conn:
                reopened.conn.execute(
                    "UPDATE app_state SET value = ? WHERE key = 'wiki_shadow_enabled'", (value,),
                )
            assert reopened.get_automation_settings().wiki_shadow_enabled is False
        for value in ("true", 1, None):
            with pytest.raises(ValidationError):
                AutomationSettingsRequest(wiki_shadow_enabled=value)
    finally:
        reopened.close()


def test_cleanup_loop_retries_without_logging_private_errors(tmp_path, monkeypatch, caplog):
    from app import main

    database = make_database(tmp_path)
    app = SimpleNamespace(state=SimpleNamespace(database=database))
    calls = []

    def prune(self):
        calls.append("prune")
        if len(calls) == 1:
            raise ValueError("PRIVATE_METRIC_CONTENT")

    async def sleep(_seconds):
        if len(calls) == 2:
            raise asyncio.CancelledError()

    monkeypatch.setattr(main.ShadowMetricStore, "prune", prune)
    monkeypatch.setattr(main, "expire_chat_runs", lambda _: None)
    monkeypatch.setattr(main.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._cleanup_expired_chat_runs(app))
    assert calls == ["prune", "prune"]
    assert "PRIVATE_METRIC_CONTENT" not in caplog.text
    assert "retention cleanup failed" in caplog.text
