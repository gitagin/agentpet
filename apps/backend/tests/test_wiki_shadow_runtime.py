import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.agents.events import AgentDoneEvent, AgentErrorEvent
from app.agents.graph_runtime import LangGraphAgentRuntime
from app.api.services.factory import AppContext
from app.api.services.wiki_shadow import WikiShadowRuntime
from app.models.config import AutomationSettingsRequest
from app.models.enums import AgentIntent
from app.services.settings import SettingsStore
from tests.conftest import auth_headers
from tests.test_wiki_shadow import eligible_state, metric_store


def runtime_fixture(tmp_path):
    store = metric_store(tmp_path)
    app = SimpleNamespace(state=SimpleNamespace(
        database=store.database, chat_runs={}, chat_runs_lock=threading.Lock(),
        active_vault_id="vault-a",
    ))
    settings = SettingsStore(store.database)
    settings.set_automation_settings(AutomationSettingsRequest(wiki_shadow_enabled=True))
    settings.close()
    return WikiShadowRuntime(AppContext(app))


def test_success_uses_minimal_input_and_pending_foreground_skips(tmp_path, monkeypatch):
    runtime = runtime_fixture(tmp_path)
    state = eligible_state()
    state.response_text = "PRIVATE_ANSWER"
    observed = []

    async def evaluate(candidate, services, *, permitted, old_citation_count):
        assert permitted()
        assert candidate.response_text == ""
        assert not candidate.citations and not candidate.recent_turns
        assert candidate.conversation_id == "shadow"
        observed.append(old_citation_count)

    monkeypatch.setattr(runtime.evaluator, "evaluate", evaluate)
    monkeypatch.setattr(runtime, "_services", lambda: object())

    async def run():
        scope = runtime.foreground_started()
        runtime.foreground_finished(state, scope)
        await runtime._task
        assert observed == [0]
        scope = runtime.foreground_started()
        runtime.context.app.state.chat_runs["pending"] = object()
        runtime.foreground_finished(state, scope)
        assert runtime._task is None or runtime._task.done()
        await runtime.shutdown()

    asyncio.run(run())
    assert state.response_text == "PRIVATE_ANSWER"


def test_new_foreground_preempts_and_shutdown_prevents_rescheduling(tmp_path, monkeypatch):
    runtime = runtime_fixture(tmp_path)
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def evaluate(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(runtime.evaluator, "evaluate", evaluate)
    monkeypatch.setattr(runtime, "_services", lambda: object())

    async def run():
        scope = runtime.foreground_started()
        runtime.foreground_finished(eligible_state(), scope)
        task = runtime._task
        await asyncio.wait_for(entered.wait(), timeout=1)
        next_scope = runtime.foreground_started()
        await asyncio.wait_for(cancelled.wait(), timeout=1)
        assert task.cancelled()
        runtime.foreground_finished(None, next_scope)
        await runtime.shutdown()
        runtime.foreground_finished(eligible_state(), scope)
        assert runtime._task is None or runtime._task.done()

    asyncio.run(run())


def test_live_scope_revokes_for_privacy_settings_vault_and_model_changes(tmp_path):
    runtime = runtime_fixture(tmp_path)
    scope = runtime._scope()
    assert runtime._permitted(scope)
    runtime.context.app.state.active_vault_id = "vault-b"
    assert not runtime._permitted(scope)
    runtime.context.app.state.active_vault_id = "vault-a"
    settings = SettingsStore(runtime.context.app.state.database)
    try:
        settings.set_automation_settings(AutomationSettingsRequest(
            wiki_shadow_enabled=True, local_privacy_mode=True,
        ))
        assert not runtime._permitted(scope)
        settings.set_automation_settings(AutomationSettingsRequest(wiki_shadow_enabled=False))
        assert not runtime._permitted(scope)
        settings.set_automation_settings(AutomationSettingsRequest(wiki_shadow_enabled=True))
        assert runtime._permitted(scope)
        with settings.conn:
            settings.conn.execute("DELETE FROM agent_model_configs")
            settings.conn.execute(
                "INSERT INTO app_state(key,value,updated_at) VALUES ('unrelated','true','now')"
            )
        # The real registry configuration fingerprint, not arbitrary app_state, is the boundary.
        with settings.conn:
            settings.conn.execute("UPDATE model_config SET model = 'different-model'")
        # Empty installations may have no model_config; use an existing seeded table row.
        if runtime._scope() == scope:
            with settings.conn:
                settings.conn.execute(
                    "INSERT INTO model_config(id,provider,base_url,model,created_at,updated_at) "
                    "VALUES (1,'test','https://invalid.example','different-model','now','now')"
                )
        assert not runtime._permitted(scope)
    finally:
        settings.close()


def test_chat_hook_submits_actual_terminal_state_only_after_clean_success(monkeypatch):
    from app.api import chat

    original = eligible_state()
    completed = original.model_copy(deep=True)
    calls = []
    shadow = SimpleNamespace(
        foreground_started=lambda: "scope",
        foreground_finished=lambda state, scope: calls.append((state, scope)),
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(wiki_shadow=shadow)))
    monkeypatch.setattr(chat, "claim_chat_run", lambda *args: True)
    monkeypatch.setattr(chat, "_insert_assistant_message", lambda *args: None)
    monkeypatch.setattr(chat, "pop_chat_run", lambda *args: None)
    monkeypatch.setattr(chat, "_persist_stream_terminal_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(chat, "_schedule_post_reply_work", lambda *args: None)

    class Persister:
        def __init__(self, *args):
            pass

        async def persist_terminal(self, *args):
            pass

        async def close(self):
            pass

    class Runtime:
        completed_state = completed
        fail = False

        async def run(self, state):
            if self.fail:
                yield AgentErrorEvent(agent_run_id=state.agent_run_id, code="failed", message="failed")
            else:
                yield AgentDoneEvent(agent_run_id=state.agent_run_id, intent=AgentIntent.CHAT, text="answer")

    runtime = Runtime()
    monkeypatch.setattr(chat, "_StreamPartialPersister", Persister)
    monkeypatch.setattr(chat, "agent_runtime", lambda _: runtime)

    async def run():
        events = [event async for event in chat._persisting_stream(request, original)]
        assert [event.event for event in events] == ["reply_ready", "done"]
        assert calls[-1] == (completed, "scope") and calls[-1][0] is not original
        runtime.fail = True
        _ = [event async for event in chat._persisting_stream(request, original)]
        assert calls[-1] == (None, "scope")
        runtime.fail = False
        stream = chat._persisting_stream(request, original)
        await anext(stream)
        await stream.aclose()
        assert calls[-1] == (None, "scope")

    asyncio.run(run())


def test_runtime_exports_fast_path_and_graph_terminal_states(monkeypatch):
    runtime = LangGraphAgentRuntime.__new__(LangGraphAgentRuntime)
    state = eligible_state()
    terminal = state.model_copy(deep=True)
    event = AgentDoneEvent(agent_run_id=state.agent_run_id, intent=AgentIntent.CHAT, text="answer")
    monkeypatch.setattr(runtime, "_should_use_negotiation", lambda _: False)

    async def prepare(_state):
        return {"agent_state": terminal}

    async def stream(_graph):
        yield event

    monkeypatch.setattr(runtime, "_prepare_streaming_chat_fast_path", prepare)
    monkeypatch.setattr(runtime, "_run_streaming_chat_fast_path", stream)

    async def run():
        _ = [item async for item in runtime.run(state)]
        assert runtime.completed_state is terminal

        async def no_fast_path(_state):
            return None

        class Graph:
            async def astream(self, *args, **kwargs):
                yield {"finish": {"agent_state": terminal, "events": [event]}}

        monkeypatch.setattr(runtime, "_prepare_streaming_chat_fast_path", no_fast_path)
        runtime.graph = Graph()
        _ = [item async for item in runtime.run(state)]
        assert runtime.completed_state is terminal

    asyncio.run(run())


def test_http_stream_schedules_opted_in_shadow_after_reply(client_factory, monkeypatch):
    from app.api import chat

    state = eligible_state()
    ids = iter(("user-message", state.agent_run_id, "assistant-message"))
    monkeypatch.setattr(chat, "new_id", lambda: next(ids))
    monkeypatch.setattr(chat, "_schedule_post_reply_work", lambda *args: None)
    observed = []
    evaluated = threading.Event()

    class Runtime:
        async def run(self, original):
            self.completed_state = original.model_copy(deep=True)
            self.completed_state.semantic_analysis = state.semantic_analysis.model_copy(deep=True)
            yield AgentDoneEvent(
                agent_run_id=original.agent_run_id, intent=AgentIntent.CHAT, text="foreground answer",
            )

    monkeypatch.setattr(chat, "agent_runtime", lambda _: Runtime())

    async def evaluate(candidate, services, *, permitted, old_citation_count):
        observed.append((candidate.user_message, permitted(), candidate.response_text))
        evaluated.set()

    with client_factory() as client:
        shadow = client.app.state.wiki_shadow
        monkeypatch.setattr(shadow, "_services", lambda: object())
        monkeypatch.setattr(shadow.evaluator, "evaluate", evaluate)
        client.app.state.active_vault_id = "test-vault"
        headers = auth_headers()
        enabled = client.put(
            "/api/settings/automation", headers=headers, json={"wiki_shadow_enabled": True},
        )
        assert enabled.status_code == 200
        accepted = client.post(
            "/api/chat", headers=headers,
            json={"message": "supplier", "conversation_id": "conversation"},
        )
        assert accepted.status_code == 200
        reply = client.get(accepted.json()["stream_url"], headers=headers)
        assert reply.status_code == 200 and "foreground answer" in reply.text
        assert evaluated.wait(timeout=2)
        assert observed == [("supplier", True, "")]


def test_shadow_read_only_services_expose_database_and_pin() -> None:
    """shadow 路径必须能解析逐来源新鲜度：此前 _ReadOnlyServices 缺 database/pin，"""
    """导致 _resolve_citation_freshness 恒 return None，评测永远只看到 unknown。"""
    from app.services.wiki.shadow import _ReadOnlyServices

    class _Reader:
        database = "DB"

        def pin(self, *args, **kwargs):
            return SimpleNamespace(vault_id="vault-a")

    services = SimpleNamespace(wiki_reader=_Reader(), retrieval=None)
    reader = _ReadOnlyServices(services, model=None, permitted=lambda: True)

    assert reader.database == "DB"
    assert reader.pin().vault_id == "vault-a"

    # 权限撤回后必须拒绝，不得借新暴露的能力绕过
    denied = _ReadOnlyServices(services, model=None, permitted=lambda: False)
    with pytest.raises(PermissionError):
        _ = denied.database
    with pytest.raises(PermissionError):
        denied.pin()


def test_shadow_metrics_accept_three_state_freshness() -> None:
    """ShadowMetrics.freshness 必须与 gate 三态一致，否则拿到 fresh/stale 时校验失败。"""
    from app.services.wiki.shadow import ShadowMetrics

    for value in ("fresh", "unknown", "stale"):
        assert ShadowMetrics(freshness=value).freshness == value
