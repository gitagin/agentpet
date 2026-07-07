from __future__ import annotations

import logging
from typing import Any, Callable

from app.models.api import MemorySearchResponse, MemorySearchResult
from app.models.enums import AgentId
from app.services.chat_model import AgentModelNotConfiguredError
from app.services.memory_permissions import (
    MemoryPromptSections,
    record_prompt_section_usage,
)
from app.services.prompt_memory_assembler import (
    PromptMemoryAssembler,
    PromptMemoryAssemblyInput,
    format_recall_prompt_sections,
)

from ..events import AgentTokenEvent
from ..events_helpers import _agent_state, _append_status, _emit_tool_results, _events, _record_node_error
from ..prompts.system import _knowledge_not_found_chat_prompt
from ..retrieval.router import _chat_agent_tool_names
from ..retrieval.scoping import _source_scope_label
from ..runtime_helpers import (
    _chat_system_prompt,
    _chunk_text,
    _continuity_presence_context_block,
    _continuity_signal,
    _continuity_signal_event,
)
from ..services import AgentRuntimeServices, ToolCallingChatModelProtocol
from ..tools import ModelInvocationFailedError
from ..semantic import _parse_text_search_tool_call
from ..state import AgentState
from ..tools import AgentToolResult, AgentToolSet, AgentToolUnavailableError, SensitiveMemoryRejectedError

logger = logging.getLogger(__name__)

# 从 graph_runtime.py 迁移，原函数名：_chat_node, _run_model_chat_with_tools, _fallback_text_search_tool_call, _answer_with_chat_model, _fallback_grounded_search, _grounded_response_from_search, _grounded_response_from_citations, _local_knowledge_not_found_response, _message_with_citation_context


async def _chat_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        signal = _continuity_signal(services.continuity)
        if signal is not None and not graph_state.get("continuity_signal_emitted"):
            _events(graph_state).append(_continuity_signal_event(state.agent_run_id, signal))
            graph_state["continuity_signal_emitted"] = True
        _append_status(graph_state, "正在生成桌宠回复。", stage="chat_generation")
        try:
            chat_model = _model_for_chat(services, AgentId.CHAT_AGENT)
        except AgentModelNotConfiguredError as exc:
            if state.action_plan is not None and state.response_text:
                chat_model = None
            else:
                raise exc
        if chat_model is not None:
            if state.citations:
                response = await _answer_with_chat_model(services, state)
            else:
                response, tool_results = await _run_model_chat_with_tools(services, state)
                text_tool_fallback = await _fallback_text_search_tool_call(services, state, response)
                if text_tool_fallback is not None:
                    response, fallback_tool_results = text_tool_fallback
                    tool_results.extend(fallback_tool_results)
                _emit_tool_results(graph_state, tool_results)
                if has_empty_search_result(tool_results):
                    response = await _answer_with_chat_model(services, state, _knowledge_not_found_chat_prompt())
            if state.semantic_analysis and state.semantic_analysis.needs_context and not state.citations:
                response = await _answer_with_chat_model(services, state, _knowledge_not_found_chat_prompt())
        elif state.citations:
            response = _grounded_response_from_citations(state.citations)
        elif state.semantic_analysis and state.semantic_analysis.needs_context:
            response = _local_knowledge_not_found_response()
        else:
            response = state.response_text or "我在呀。你先丢给我一句想法，我陪你慢慢整理。"

        state.response_text = response
        for chunk in _chunk_text(response):
            _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk))
        return graph_state
    except (AgentToolUnavailableError, SensitiveMemoryRejectedError) as exc:
        return _record_node_error(graph_state, exc)
    except Exception as exc:
        if services.model_registry is not None or services.chat_model is not None:
            return _record_node_error(graph_state, exc if hasattr(exc, "code") else ModelInvocationFailedError())
        return _record_node_error(graph_state, exc)


async def _run_model_chat_with_tools(
    services: AgentRuntimeServices,
    state: AgentState,
) -> tuple[str, list[AgentToolResult]]:
    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(
        retrieval=services.retrieval,
        memory=services.memory,
        tasks=services.tasks,
        wiki=services.wiki,
        wiki_workflow=services.wiki_workflow,
        observer=tool_results.append,
    )
    chat_model = _model_for_chat(services, AgentId.CHAT_AGENT)
    if isinstance(chat_model, ToolCallingChatModelProtocol):
        tool_names = _chat_agent_tool_names(state, services)
        result = await chat_model.complete_with_tools(
            user_message=_message_with_runtime_context(services, state),
            system_prompt=_chat_system_prompt(),
            tools=observed_toolset.allowed_tools(tool_names),
        )
        return result.text, tool_results

    response = await chat_model.complete(
        user_message=_message_with_runtime_context(services, state),
        system_prompt=_chat_system_prompt(),
    )
    return response, tool_results


async def _fallback_text_search_tool_call(
    services: AgentRuntimeServices,
    state: AgentState,
    response: str,
) -> tuple[str, list[AgentToolResult]] | None:
    query = _parse_text_search_tool_call(response)
    if query is None:
        return None
    if state.citations:
        return state.response_text or _grounded_response_from_citations(state.citations), []
    if services.retrieval is None:
        return _local_knowledge_not_found_response(), []

    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(retrieval=services.retrieval, observer=tool_results.append)
    search_response = await observed_toolset.search_memory(query=query or state.user_message, top_k=5, mode="fts")
    if not search_response.results:
        return _local_knowledge_not_found_response(), tool_results
    return _grounded_response_from_search(search_response), tool_results


async def _answer_with_chat_model(
    services: AgentRuntimeServices,
    state: AgentState,
    system_prompt: str | None = None,
) -> str:
    chat_model = _model_for_chat(services, AgentId.CHAT_AGENT)
    if chat_model is None:
        return _local_knowledge_not_found_response()
    if isinstance(chat_model, ToolCallingChatModelProtocol):
        result = await chat_model.complete_with_tools(
            user_message=_message_with_runtime_context(services, state),
            system_prompt=system_prompt or _chat_system_prompt(),
            tools=(),
        )
        return result.text
    response = await chat_model.complete(
        user_message=_message_with_runtime_context(services, state),
        system_prompt=system_prompt or _chat_system_prompt(),
    )
    return response


async def _fallback_grounded_search(
    services: AgentRuntimeServices,
    state: AgentState,
) -> tuple[str, list[AgentToolResult]]:
    if services.retrieval is None:
        return "", []

    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(retrieval=services.retrieval, observer=tool_results.append)
    try:
        search_response = await observed_toolset.search_memory(query=state.user_message, top_k=5, mode="fts")
    except Exception:
        return "", []
    if not search_response.results:
        return "", []
    return _grounded_response_from_search(search_response), tool_results


def _message_with_runtime_context(services: AgentRuntimeServices, state: AgentState) -> str:
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message=state.user_message,
            immediate_understanding=state.immediate_understanding,
            semantic_analysis=state.semantic_analysis,
            citations=state.citations,
            action_plan=state.action_plan,
            continuity_block=_continuity_presence_context_block(services.continuity),
            recent_turns=state.recent_turns,
            stable_profile_items=_stable_profile_items(services, state),
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            agent_run_id=state.agent_run_id,
        )
    )
    if assembly.recall_sections is not None:
        record_prompt_section_usage(
            services.memory_activation_recorder,
            sections=assembly.recall_sections,
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            agent_run_id=state.agent_run_id,
        )
    return assembly.prompt_text


def _stable_profile_items(services: AgentRuntimeServices, state: AgentState) -> tuple[object, ...]:
    provider = services.prompt_profile_provider
    if provider is None:
        return ()
    try:
        selection = provider.select(user_message=state.user_message, semantic_analysis=state.semantic_analysis)
    except Exception:
        logger.warning("Prompt profile provider failed; continuing without stable profile.", exc_info=True)
        return ()
    return tuple(getattr(selection, "items", ()) or ())


def _grounded_response_from_search(search_response: MemorySearchResponse) -> str:
    return _grounded_response_from_citations(search_response.results)


def _grounded_response_from_citations(results) -> str:
    eligible_results = [
        result
        for result in results[:3]
        if _can_use_result_as_answer_context(result)
    ]
    if not eligible_results:
        return _local_knowledge_not_found_response()
    source_scope = getattr(eligible_results[0], "source_scope", "all")
    source_label = _source_scope_label(source_scope)
    count_label = "一条" if len(eligible_results) == 1 else f"{len(eligible_results)} 条"
    caution = (
        "这些还只是聊天日记里的弱线索，"
        if source_scope == "daily_chat"
        else ""
    )
    return (
        f"我翻到{source_label}里有{count_label}相关线索。"
        f"{caution}我会把它当作背景来回答，不直接复述原始记录；"
        "如果你愿意，我可以继续帮你整理成一句更短的结论。"
    )


def _local_knowledge_not_found_response() -> str:
    return "我翻了下记忆本，暂时没有找到能引用的记录，所以这部分我不装懂。你可以告诉我一点背景，我也可以先按一般经验陪你分析。"


def _message_with_citation_context(state: AgentState, *, sections: MemoryPromptSections | None = None) -> str:
    return PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message=state.user_message,
            semantic_analysis=state.semantic_analysis,
            citations=state.citations,
            recent_turns=state.recent_turns,
            conversation_id=state.conversation_id,
            message_id=state.message_id,
            agent_run_id=state.agent_run_id,
            recall_sections=sections,
        )
    ).prompt_text


def _recall_prompt_sections_text(sections: MemoryPromptSections) -> str:
    return format_recall_prompt_sections(sections)


def _can_use_result_as_answer_context(result: MemorySearchResult) -> bool:
    if not result.snippet.strip() or not result.recall_permissions.can_answer_context:
        return False
    inactive_statuses = {
        "candidate",
        "pending",
        "quarantined",
        "rejected",
        "archived",
        "forgotten",
        "sensitive_blocked",
        "wrong",
        "superseded",
        "reverted",
    }
    if result.lifecycle_status and result.lifecycle_status.casefold() in inactive_statuses:
        return False
    snippet = result.snippet.casefold()
    return not any(f"status={status}" in snippet for status in inactive_statuses)


def _model_for_chat(services: AgentRuntimeServices, agent_id: AgentId):
    if services.model_registry is not None:
        return services.model_registry.get(agent_id)
    if agent_id == AgentId.CHAT_AGENT:
        return services.chat_model
    return None
