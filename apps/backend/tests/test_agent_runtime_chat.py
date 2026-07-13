from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.agent_runtime_fakes import (
    FakeChatModel,
    FakeContinuity,
    FakeContinuityWithSignal,
    FakeEmptyRetrieval,
    FakeMemory,
    FakeMultiScopeRetrieval,
    FakeNonToolCallingChatModel,
    FakeRetrieval,
    FakeToolCallingChatModel,
    FakeWiki,
    FailingChatModel,
    assert_langgraph_events,
    first_event,
    make_state,
)

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.models.api import MemoryRecallPermissions, MemorySearchResponse, MemorySearchResult
from app.services.chat_model import AgentId, AgentModelRegistry


class StreamingChatModel:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks
        self.calls = []
        self.complete_calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.complete_calls.append((user_message, system_prompt))
        return "".join(self.chunks)

    async def stream_complete(self, *, user_message: str, system_prompt: str | None = None):
        self.calls.append((user_message, system_prompt))
        for chunk in self.chunks:
            await asyncio.sleep(0)
            yield chunk


class CandidateOnlyRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    note_id="candidate-1",
                    chunk_id="candidate-1",
                    relative_path="MemoryGraph/LongTerm",
                    title="待确认记忆",
                    heading="preference",
                    snippet="用户喜欢蓝莓 (status=candidate)",
                    score=0.92,
                    source_scope=source_scope,
                    retrieval_mode="graph_activation",
                    recall_permissions=MemoryRecallPermissions(can_answer_context=True),
                    lifecycle_status="candidate",
                    candidate_id="candidate-1",
                )
            ]
        )


def test_langgraph_runtime_streams_plain_chat_tokens_when_model_supports_streaming() -> None:
    async def run_case():
        chat_model = StreamingChatModel(["你", "好"])
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(chat_model=chat_model))

        events = [event async for event in runtime.run(make_state("hello"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.complete_calls == []
    assert chat_model.calls
    assert [event.text for event in events if event.event == "token"] == ["你", "好"]


def test_langgraph_runtime_local_privacy_mode_uses_fts_without_model_call() -> None:
    async def run_case():
        chat_model = StreamingChatModel(["不应调用"])
        retrieval = FakeRetrieval()
        state = make_state("api_key=private-value-123456")
        state.local_privacy_mode = True
        state.local_privacy_sensitive_reason = "password_assignment"
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=chat_model, retrieval=retrieval)
        )

        events = [event async for event in runtime.run(state)]

        return chat_model, retrieval, events

    chat_model, retrieval, events = asyncio.run(run_case())

    assert chat_model.calls == []
    assert chat_model.complete_calls == []
    assert retrieval.calls == [("api_key=private-value-123456", 5, "fts", "all")]
    assert events[0].event == "status"
    assert events[0].stage == "local_privacy_guard"
    assert [event.event for event in events] == ["status", "token", "done"]
    token_text = "".join(event.text for event in events if event.event == "token")
    assert "没有把原文发送到模型 API" in token_text
    assert "关键词检索" in token_text
    assert events[-1].event == "done"
    assert events[-1].text == token_text


def test_langgraph_runtime_uses_configured_chat_model_for_plain_chat() -> None:
    async def run_case():
        chat_model = FakeChatModel("LangGraph 聊天回复")
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(chat_model=chat_model))

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "你好"
    assert "本地长期记忆陪伴体" in chat_model.calls[0][1]
    assert "温和、稳定、有分寸的中文" in chat_model.calls[0][1]
    assert "只有在相关时才引用检索到的记忆" in chat_model.calls[0][1]
    assert "候选、待确认、被拒绝、隔离" in chat_model.calls[0][1]
    assert "不要编造用户过去说过的话" in chat_model.calls[0][1]
    assert "我可能记错了" in chat_model.calls[0][1]
    assert "健康、法律、金钱、关系危机" in chat_model.calls[0][1]
    assert "避免客服式或工具式开场" in chat_model.calls[0][1]
    assert "有什么可以帮你" in chat_model.calls[0][1]
    assert_langgraph_events(events, ["token", "done"])
    assert first_event(events, "token").text == "LangGraph 聊天回复"
    assert events[-1].text == "LangGraph 聊天回复"


def test_langgraph_runtime_does_not_fabricate_memory_when_no_context_exists() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(AgentRuntimeServices())

        events = [event async for event in runtime.run(make_state("你还记得我喜欢什么吗？"))]

        return events

    events = asyncio.run(run_case())

    token_text = "".join(event.text for event in events if event.event == "token")
    assert "没有找到能引用的记录" in token_text
    assert "记得你喜欢" not in token_text
    assert "你喜欢" not in token_text
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_injects_confirmed_continuity_context() -> None:
    async def run_case():
        chat_model = FakeChatModel("continuity-aware answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuity(
                    "Confirmed continuity context (user-reviewed; compact runtime state):\n"
                    "- current mood: User is tired."
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert "Confirmed continuity context" in chat_model.calls[0][0]
    assert "Companion presence behavior" in chat_model.calls[0][0]
    assert "User is tired." in chat_model.calls[0][0]
    assert "Current user message:\nhello" in chat_model.calls[0][0]
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_emits_confirmed_continuity_signal_before_reply() -> None:
    async def run_case():
        chat_model = FakeChatModel("continuity-aware answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuityWithSignal(
                    "Confirmed continuity context (user-reviewed; compact runtime state):\n"
                    "- unresolved threads: continue this tomorrow"
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    signal = first_event(events, "continuity_signal")
    assert signal.kind == "open_thread"
    assert signal.intensity == "high"
    assert signal.source_state_keys == ["unresolved_threads"]
    assert "Companion presence behavior" in chat_model.calls[0][0]
    assert_langgraph_events(events, ["continuity_signal", "token", "done"])


def test_langgraph_runtime_does_not_inject_pending_continuity_when_adapter_is_empty() -> None:
    async def run_case():
        chat_model = FakeChatModel("plain answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuity(""),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "hello"
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_injects_immediate_understanding_for_current_reply() -> None:
    async def run_case():
        chat_model = FakeChatModel("direct critique")
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(chat_model=chat_model))

        events = [
            event
            async for event in runtime.run(
                make_state("For this turn only, be blunt and review this backend migration.")
            )
        ]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    user_message = chat_model.calls[0][0]
    assert "Current-turn understanding (state-only, not durable memory)" in user_message
    assert "interaction_style: direct" in user_message
    assert "current_task:" in user_message
    assert "scope: this turn only" in user_message
    assert "Current user message:" in user_message
    assert "source_hash:" in user_message
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_does_not_carry_this_turn_style_to_new_state_or_write_memory() -> None:
    async def run_case():
        first_model = FakeChatModel("first")
        first_memory = FakeMemory()
        first_runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=first_model, memory=first_memory)
        )
        first_events = [
            event
            async for event in first_runtime.run(
                make_state("Only this time, be blunt with the critique.")
            )
        ]

        second_model = FakeChatModel("second")
        second_memory = FakeMemory()
        second_runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=second_model, memory=second_memory)
        )
        second_events = [event async for event in second_runtime.run(make_state("Let's continue normally."))]
        return first_model, second_model, first_memory, second_memory, first_events, second_events

    first_model, second_model, first_memory, second_memory, first_events, second_events = asyncio.run(run_case())

    assert "interaction_style: direct" in first_model.calls[0][0]
    assert "interaction_style: direct" not in second_model.calls[0][0]
    assert first_memory.requests == []
    assert second_memory.requests == []
    assert_langgraph_events(first_events, ["token", "done"])
    assert_langgraph_events(second_events, ["token", "done"])


def test_langgraph_runtime_emits_error_without_done_when_chat_model_fails() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=FailingChatModel())
        )

        return [event async for event in runtime.run(make_state("你好"))]

    events = asyncio.run(run_case())

    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "model_invocation_failed"
    assert first_event(events, "error").message == "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。"


def test_langgraph_runtime_uses_chat_model_to_answer_search_intent() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeChatModel("我翻到 Ada 喜欢简洁的状态更新。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert chat_model.calls
    assert "Ada prefers concise status updates." in chat_model.calls[0][0]
    assert_langgraph_events(events, ["citation", "citation", "token", "done"])
    assert first_event(events, "token").text == "我翻到 Ada 喜欢简洁的状态更新。"


def test_langgraph_chat_agent_maps_model_search_tool_call_to_citation_event() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel("已根据记忆回答。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert chat_model.calls[0][2] == []
    assert_langgraph_events(events, ["citation", "citation", "token", "done"])
    assert first_event(events, "citation").citation.relative_path == "People/Ada.md"
    assert first_event(events, "token").text == "已根据记忆回答。"


def test_langgraph_chat_agent_does_not_search_for_plain_question_when_model_skips_tool() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel("model-only answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("Tell me a tiny greeting."))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == []
    assert chat_model.calls[0][2] == []
    assert events[0].event == "status"
    assert events[-1].event == "done"
    token_text = "".join(event.text for event in events if event.event == "token")
    assert token_text == "model-only answer"


def test_langgraph_chat_agent_retrieves_memory_route_before_default_negotiation_local_synthesis() -> None:
    async def run_case():
        retrieval = FakeMultiScopeRetrieval()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("Do I prefer concise status updates?"))
        ]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Do I prefer concise status updates?", 5, "fts", "personal_memory"),
        ("Do I prefer concise status updates?", 5, "fts", "diary_objects"),
        ("Do I prefer concise status updates?", 5, "fts", "daily_chat"),
    ]
    assert events[0].event == "status"
    assert events[-1].event == "done"
    assert first_event(events, "context_budget").selected_count == 4
    assert len([event for event in events if event.event == "citation"]) == 4
    assert any(event.event == "token" for event in events)
    token_text = "".join(event.text for event in events if event.event == "token")
    assert "相关线索" in token_text
    assert "原始记录" in token_text
    assert "Ada prefers concise status updates." not in token_text


def test_langgraph_chat_agent_does_not_treat_candidate_memory_as_confirmed() -> None:
    async def run_case():
        retrieval = CandidateOnlyRetrieval()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("你记得我喜欢什么水果吗？"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls
    token_text = "".join(event.text for event in events if event.event == "token")
    assert "蓝莓" not in token_text
    assert "确认" not in token_text
    assert "没有找到能引用的记录" in token_text
    event_names = [event.event for event in events if event.event != "status"]
    assert event_names[-2:] == ["token", "done"]
    assert "citation" not in event_names


def test_langgraph_chat_agent_can_surface_wiki_manager_for_obsidian_note_request() -> None:
    async def run_case():
        wiki = FakeWiki()
        chat_model = FakeToolCallingChatModel("manage_wiki_page", "I organized it into the Wiki.")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                model_registry=AgentModelRegistry({AgentId.CHAT_AGENT: chat_model}),
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("Turn this into an Obsidian note: Runtime: Wiki manager owns pages")
            )
        ]

        return wiki, chat_model, events

    wiki, chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][2] == ["manage_wiki_page"]
    assert wiki.requests[0].title == "Runtime"
    assert wiki.requests[0].content == "Wiki content"
    assert_langgraph_events(events, ["agent_action", "token", "done"])
    assert first_event(events, "agent_action").action_type == "wiki.page.write"
    assert first_event(events, "token").text == "I organized it into the Wiki."


def test_langgraph_chat_agent_executes_text_search_tool_call_instead_of_echoing() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel(
            "<tool_call><function=search_notes> <parameter=query>5月3号</parameter> </function> </tool_call>"
        )
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("tell me about that day"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert len(retrieval.calls) == 1
    assert retrieval.calls[0][1:] == (5, "fts", "all")
    assert events[0].event == "status"
    assert first_event(events, "citation").event == "citation"
    assert events[-1].event == "done"
    token_text = "".join(event.text for event in events if event.event == "token")
    assert "<tool_call>" not in token_text
    assert "相关线索" in token_text
    assert "原始记录" in token_text
    assert "Ada prefers concise status updates." not in token_text


def test_langgraph_chat_agent_answers_naturally_when_search_is_empty() -> None:
    async def run_case():
        retrieval = FakeEmptyRetrieval()
        chat_model = FakeNonToolCallingChatModel("我翻了下记忆本，暂时没有找到能引用的记录。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                chat_model=chat_model,
                automation_settings=SimpleNamespace(use_negotiation=False),
            )
        )

        events = [event async for event in runtime.run(make_state("你记得我喜欢什么吗"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls
    assert all(call == ("你记得我喜欢什么吗", 5, "fts") for call in retrieval.calls)
    assert_langgraph_events(events, ["token", "done"])
    assert "翻了下记忆本" in first_event(events, "token").text
