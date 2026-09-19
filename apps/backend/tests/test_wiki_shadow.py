import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from app.services.wiki.shadow import (
    ShadowMetrics, ShadowMetricStore, WikiShadowEvaluator, shadow_eligible,
)
from app.storage.database import Database, MigrationRunner
from tests.test_wiki_read_tools import read_tools
from tests.test_wiki_publication import published


def eligible_state():
    state = AgentState(
        conversation_id="PRIVATE_CONVERSATION", message_id="PRIVATE_MESSAGE",
        agent_run_id="0", user_message="PRIVATE_QUESTION supplier",
        semantic_analysis=SemanticAnalysisResult(
            needs_context=True, source_scope="knowledge_base", query="supplier",
        ),
    )
    for index in range(1000):
        state.agent_run_id = str(index)
        if shadow_eligible(state, enabled=True):
            return state
    raise AssertionError("no sampled run")


def metric_store(tmp_path):
    database = Database(tmp_path / "metrics.sqlite")
    MigrationRunner(database).apply()
    return ShadowMetricStore(database)


def records(store):
    with store.database.session() as conn:
        row = conn.execute(
            "SELECT value FROM app_state WHERE key = 'wiki_shadow_metrics_v1'"
        ).fetchone()
        return json.loads(row["value"]) if row else []


def test_shadow_requires_opt_in_scope_and_retention_permission():
    state = eligible_state()
    assert not shadow_eligible(state)
    assert not shadow_eligible(state, enabled="true")
    assert shadow_eligible(state, enabled=True) == shadow_eligible(state, enabled=True)
    for field in ("local_privacy_mode", "suppress_post_reply_automation"):
        assert not shadow_eligible(state.model_copy(update={field: True}), enabled=True)
    for scope in ("all", "none", "personal_memory", "daily_chat"):
        copy = state.model_copy(deep=True)
        copy.semantic_analysis.source_scope = scope
        assert not shadow_eligible(copy, enabled=True)


def test_shadow_quota_survives_reopen_and_metrics_expire(tmp_path):
    store = metric_store(tmp_path)
    now = datetime(2026, 9, 19, tzinfo=timezone.utc)
    ids = [store.reserve(now=now) for _ in range(20)]
    assert all(ids) and len(set(ids)) == 20
    reopened = ShadowMetricStore(store.database)
    assert reopened.reserve(now=now) is None
    with pytest.raises(ValidationError):
        ShadowMetrics(question="PRIVATE_QUESTION")
    store.finish(ids[0], ShadowMetrics(status="failed"), now=now)
    reopened.prune(now=now + timedelta(days=7))
    assert records(store) == []
    assert reopened.reserve(now=now + timedelta(days=7))


def test_real_query_is_isolated_and_persists_only_metrics(tmp_path, read_tools):
    tools, _, _, _, _ = read_tools
    state = eligible_state()
    original = state.model_dump(mode="json")
    store = metric_store(tmp_path)

    class Model:
        async def complete(self, **kwargs):
            return "PRIVATE_INVALID_MODEL_RESPONSE"

    services = AgentRuntimeServices(
        wiki_reader=tools.wiki_reader,
        model_registry=SimpleNamespace(get=lambda _: Model()),
        wiki=object(), wiki_workflow=object(), memory=object(), tasks=object(),
        agent_action_recorder=lambda _: pytest.fail("no actions in shadow"),
    )
    evaluator = WikiShadowEvaluator(store)
    result = asyncio.run(evaluator.evaluate(state, services, permitted=lambda: True))
    assert result == "completed"
    assert state.model_dump(mode="json") == original
    saved = records(store)
    assert len(saved) == 1
    assert saved[0]["metrics"]["page_read_count"] > 0
    assert saved[0]["metrics"]["correctness"] == "unknown"
    assert saved[0]["metrics"]["token_count"] is None
    serialized = json.dumps(saved)
    for secret in (
        "PRIVATE_QUESTION", "PRIVATE_CONVERSATION", "PRIVATE_MESSAGE",
        "PRIVATE_INVALID_MODEL_RESPONSE", "relative_path", "snippet", "generation",
    ):
        assert secret not in serialized


def test_busy_and_revoked_runs_do_not_continue_reading(tmp_path):
    store = metric_store(tmp_path)
    evaluator = WikiShadowEvaluator(store)
    state = eligible_state()
    entered = asyncio.Event()
    release = asyncio.Event()
    allowed = True

    class Reader:
        calls = 0

        async def search_pages(self, *args, **kwargs):
            self.calls += 1
            entered.set()
            await release.wait()
            return {"generation": "g", "candidates": []}

        async def read_page(self, *args, **kwargs):
            pytest.fail("revoked run must stop")

    reader = Reader()
    services = AgentRuntimeServices(
        wiki_reader=reader, model_registry=SimpleNamespace(get=lambda _: object()),
    )

    async def run():
        nonlocal allowed
        task = asyncio.create_task(evaluator.evaluate(state, services, permitted=lambda: allowed))
        await entered.wait()
        assert await evaluator.evaluate(state, services, permitted=lambda: True) == "skipped"
        allowed = False
        release.set()
        assert await task == "failed"
        assert await evaluator.evaluate(state, services, permitted=lambda: False) == "skipped"

    asyncio.run(run())
    assert reader.calls == 1
    assert len(records(store)) == 1
    assert records(store)[0]["metrics"]["status"] == "failed"
