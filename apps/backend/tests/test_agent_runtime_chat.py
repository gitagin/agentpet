from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tests.agent_runtime_fakes import (
    FakeChatModel,
    FakeContinuity,
    FakeContinuityWithSignal,
    FakeEmptyRetrieval,
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
from app.services.chat_model import AgentId, AgentModelRegistry


def test_langgraph_runtime_uses_configured_chat_model_for_plain_chat() -> None:
    async def run_case():
        chat_model = FakeChatModel("LangGraph 聊天回复")
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(chat_model=chat_model))

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "你好"
    assert "桌宠伙伴" in chat_model.calls[0][1]
    assert_langgraph_events(events, ["token", "done"])
    assert first_event(events, "token").text == "LangGraph 聊天回复"
    assert events[-1].text == "LangGraph 聊天回复"


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

        events = [event async for event in runtime.run(make_state("What does Ada prefer?"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == []
    assert chat_model.calls[0][2] == []
    assert events[0].event == "status"
    assert events[-1].event == "done"
    token_text = "".join(event.text for event in events if event.event == "token")
    assert token_text == "model-only answer"


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
    assert "Ada prefers concise status updates." in token_text


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
