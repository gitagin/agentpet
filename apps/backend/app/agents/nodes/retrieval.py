from __future__ import annotations

import logging
from typing import Any, Callable

from app.models.api import MemorySearchResponse
from app.models.enums import AgentId
from app.services.companion_retrieval import rerank_memory_context

from ..events import AgentContextBudgetEvent
from ..events_helpers import _agent_state, _append_status, _emit_tool_results, _events, _record_node_error
from ..prompts.system import _knowledge_retrieval_system_prompt, _memory_retrieval_system_prompt
from ..retrieval.scoping import _context_source_scope, _effective_retrieval_source_scope, _memory_aggregation_scopes, _retrieval_query, _source_scope_label, _stage_for_source_scope
from ..services import AgentRuntimeServices
from ..semantic import _fallback_semantic_analysis
from ..state import AgentState, SemanticAnalysisResult
from ..tools import AgentToolName, AgentToolResult, AgentToolSet


logger = logging.getLogger(__name__)

# 从 graph_runtime.py 迁移，原函数名：_memory_retrieval_node, _aggregate_memory_retrieval_node, _knowledge_retrieval_node, _split_retrieval_node, _emit_daily_chat_fallback, _fallback_daily_chat_context, _fallback_scoped_retrieval

MEMORY_CONTEXT_LIMIT = 5
MEMORY_CONTEXT_PER_SCOPE_LIMIT = 2


async def _memory_retrieval_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    run_model_agent_with_tools,
    has_tool_result: Callable[[list[AgentToolResult], str], bool],
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
) -> dict[str, Any]:
    state = _agent_state(graph_state)
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    aggregation_scopes = _memory_aggregation_scopes(state, semantic)
    if aggregation_scopes:
        memory_scopes = tuple(scope for scope in aggregation_scopes if scope != "knowledge_base")
        graph_state["retrieval_plan"] = {"memory": bool(memory_scopes), "knowledge": "knowledge_base" in aggregation_scopes}
        if memory_scopes:
            return await _aggregate_memory_retrieval_node(graph_state, services, scopes=memory_scopes)
        return graph_state

    effective_scope = _effective_retrieval_source_scope(state, semantic)
    if effective_scope == "diary_objects":
        graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
        return await _split_retrieval_node(
            graph_state, services, run_model_agent_with_tools, has_tool_result, has_empty_search_result,
            agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
            source_scope="diary_objects",
            stage=_stage_for_source_scope("diary_objects"),
            system_prompt_factory=_memory_retrieval_system_prompt,
            daily_chat_fallback=True,
            update_state_scope=False,
        )
    graph_state["retrieval_plan"] = {"memory": True, "knowledge": effective_scope == "all"}
    source_scope = "daily_chat" if effective_scope == "daily_chat" else "personal_memory"
    return await _split_retrieval_node(
        graph_state, services, run_model_agent_with_tools, has_tool_result, has_empty_search_result,
        agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
        source_scope=source_scope,
        stage=_stage_for_source_scope(source_scope),
        system_prompt_factory=_memory_retrieval_system_prompt,
        daily_chat_fallback=source_scope == "personal_memory",
        update_state_scope=effective_scope != "all",
    )


async def _aggregate_memory_retrieval_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    *,
    scopes: tuple[str, ...],
) -> dict[str, Any]:
    state = _agent_state(graph_state)
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    if services.retrieval is None:
        return graph_state

    query = _retrieval_query(state, semantic)
    _append_status(graph_state, "retrieving multi-source companion memory", stage="multi_source_memory_retrieval")
    observed_toolset = AgentToolSet(retrieval=services.retrieval)
    collected = []
    searched_scopes: list[str] = []
    for scope in scopes:
        try:
            response = await observed_toolset.search_memory(
                query=query,
                top_k=MEMORY_CONTEXT_LIMIT,
                mode="fts",
                source_scope=scope,
            )
        except Exception:
            logger.warning(
                "Multi-source memory retrieval failed for scope; skipping scope",
                exc_info=True,
                extra={"source_scope": scope},
            )
            continue
        searched_scopes.append(scope)
        collected.extend(response.results)

    reranked = rerank_memory_context(
        collected,
        preferred_scopes=scopes,
        limit=MEMORY_CONTEXT_LIMIT,
        per_scope_limit=MEMORY_CONTEXT_PER_SCOPE_LIMIT,
    )
    compressed = list(reranked.selected)
    if compressed:
        state.semantic_analysis = semantic.model_copy(
            update={"source_scope": _context_source_scope(compressed, semantic.source_scope), "query": query}
        )
    telemetry = reranked.telemetry
    if telemetry.candidate_count > 0 and services.companion_retrieval_reports is not None:
        try:
            services.companion_retrieval_reports.record(agent_run_id=state.agent_run_id, query=query, telemetry=telemetry)
        except Exception:
            logger.warning("Companion retrieval telemetry recording failed; continuing", exc_info=True)
    if telemetry.candidate_count > 0:
        _events(graph_state).append(
            AgentContextBudgetEvent(
                agent_run_id=state.agent_run_id,
                strategy=telemetry.strategy,
                candidate_count=telemetry.candidate_count,
                selected_count=telemetry.selected_count,
                duplicate_drop_count=telemetry.duplicate_drop_count,
                per_scope_drop_count=telemetry.per_scope_drop_count,
                budget_drop_count=telemetry.budget_drop_count,
                item_budget=telemetry.item_budget,
                per_scope_limit=telemetry.per_scope_limit,
                char_budget=telemetry.char_budget,
                used_chars=telemetry.used_chars,
                source_counts=telemetry.source_counts,
                selected_scopes=list(telemetry.selected_scopes),
            )
        )
    _emit_tool_results(graph_state, [_memory_search_result(compressed, searched_scopes, telemetry)])
    return graph_state


async def _knowledge_retrieval_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    run_model_agent_with_tools,
    has_tool_result: Callable[[list[AgentToolResult], str], bool],
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
) -> dict[str, Any]:
    return await _split_retrieval_node(
        graph_state, services, run_model_agent_with_tools, has_tool_result, has_empty_search_result,
        agent_id=AgentId.KNOWLEDGE_RETRIEVAL_AGENT,
        source_scope="knowledge_base",
        stage="knowledge_base_retrieval",
        system_prompt_factory=_knowledge_retrieval_system_prompt,
        daily_chat_fallback=False,
        update_state_scope=False,
    )


async def _split_retrieval_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    run_model_agent_with_tools,
    has_tool_result: Callable[[list[AgentToolResult], str], bool],
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
    *,
    agent_id: AgentId,
    source_scope: str,
    stage: str,
    system_prompt_factory,
    daily_chat_fallback: bool,
    update_state_scope: bool,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
        scoped_semantic = semantic.model_copy(update={"source_scope": source_scope, "query": _retrieval_query(state, semantic)})
        if update_state_scope:
            state.semantic_analysis = scoped_semantic
        _append_status(graph_state, f"retrieving {_source_scope_label(source_scope)}", stage=stage)
        if _model_for_retrieval(services, agent_id) is not None:
            response, tool_results = await run_model_agent_with_tools(
                agent_id=agent_id,
                state=state,
                tools=(AgentToolName.SEARCH_MEMORY,),
                system_prompt=system_prompt_factory(scoped_semantic),
            )
            _emit_tool_results(graph_state, tool_results)
            await _maybe_emit_daily_chat_fallback(
                graph_state, services, state, scoped_semantic, tool_results,
                has_empty_search_result=has_empty_search_result,
                daily_chat_fallback=daily_chat_fallback,
                update_state_scope=update_state_scope,
            )
            if not has_tool_result(tool_results, "search_memory"):
                response, fallback_results = await _fallback_scoped_retrieval(services, state, scoped_semantic)
                _emit_tool_results(graph_state, fallback_results)
                await _maybe_emit_daily_chat_fallback(
                    graph_state, services, state, scoped_semantic, fallback_results,
                    has_empty_search_result=has_empty_search_result,
                    daily_chat_fallback=daily_chat_fallback,
                    update_state_scope=update_state_scope,
                )
            state.response_text = "" if has_tool_result(tool_results, "search_memory") else response
            return graph_state

        _, tool_results = await _fallback_scoped_retrieval(services, state, scoped_semantic)
        _emit_tool_results(graph_state, tool_results)
        await _maybe_emit_daily_chat_fallback(
            graph_state, services, state, scoped_semantic, tool_results,
            has_empty_search_result=has_empty_search_result,
            daily_chat_fallback=daily_chat_fallback,
            update_state_scope=update_state_scope,
        )
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


async def _maybe_emit_daily_chat_fallback(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    semantic: SemanticAnalysisResult,
    tool_results: list[AgentToolResult],
    *,
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
    daily_chat_fallback: bool,
    update_state_scope: bool,
) -> None:
    if not daily_chat_fallback or not has_empty_search_result(tool_results):
        return
    fallback_daily_results = await _fallback_daily_chat_context(
        services,
        state,
        semantic,
        update_state_scope=update_state_scope,
    )
    if fallback_daily_results:
        _append_status(graph_state, "personal memory missed; checking daily chat", stage="daily_chat_fallback")
        _emit_tool_results(graph_state, fallback_daily_results)


async def _fallback_daily_chat_context(
    services: AgentRuntimeServices,
    state: AgentState,
    semantic: SemanticAnalysisResult,
    *,
    update_state_scope: bool = True,
) -> list[AgentToolResult]:
    if semantic.source_scope not in {"personal_memory", "diary_objects"} or services.retrieval is None:
        return []
    observed_toolset = AgentToolSet(retrieval=services.retrieval)
    try:
        response = await observed_toolset.search_memory(
            query=semantic.query or state.user_message,
            top_k=5,
            mode="fts",
            source_scope="daily_chat",
        )
    except Exception:
        logger.warning("Daily chat fallback retrieval failed; returning empty results", exc_info=True)
        return []
    if not response.results:
        return []
    if update_state_scope:
        state.semantic_analysis = semantic.model_copy(update={"source_scope": "daily_chat"})
    return [AgentToolResult(name="search_memory", value=response)]


async def _fallback_scoped_retrieval(
    services: AgentRuntimeServices,
    state: AgentState,
    semantic: SemanticAnalysisResult,
) -> tuple[str, list[AgentToolResult]]:
    if services.retrieval is None:
        return "", []
    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(retrieval=services.retrieval, observer=tool_results.append)
    try:
        search_response = await observed_toolset.search_memory(
            query=semantic.query or state.user_message,
            top_k=5,
            mode="fts",
            source_scope=semantic.source_scope,
        )
    except Exception:
        logger.warning(
            "Scoped fallback retrieval failed; returning empty results",
            exc_info=True,
            extra={"source_scope": semantic.source_scope},
        )
        return "", []
    if not search_response.results:
        return "", tool_results
    return "", tool_results


def _memory_search_result(results, searched_scopes: list[str], telemetry) -> AgentToolResult:
    metadata = {
        "semantic_available": False,
        "retrieval_mode": "multi_source",
        "source_scopes": searched_scopes,
        "compressed_limit": MEMORY_CONTEXT_LIMIT,
        "context_budget": {
            "strategy": telemetry.strategy, "candidate_count": telemetry.candidate_count,
            "selected_count": telemetry.selected_count, "used_chars": telemetry.used_chars, "char_budget": telemetry.char_budget,
        },
    }
    return AgentToolResult(name="search_memory", value=MemorySearchResponse(results=results, metadata=metadata))


def _model_for_retrieval(services: AgentRuntimeServices, agent_id: AgentId):
    return services.model_registry.get(agent_id) if services.model_registry is not None else None
