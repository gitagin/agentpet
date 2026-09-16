from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

from app.models.api import MemorySearchResponse
from app.models.enums import AgentId
from app.models.memory import RetrievalContribution
from app.services.companion_retrieval import (
    DEFAULT_CONTEXT_CHAR_BUDGET,
    CompanionContextBudgetTelemetry,
    CompanionRerankResult,
)
from app.services.retrieval_fusion import FusionCandidate, reciprocal_rank_fusion

from ..events import AgentContextBudgetEvent
from ..events_helpers import _agent_state, _append_status, _emit_tool_results, _events, _record_node_error
from ..prompts.system import _knowledge_retrieval_system_prompt, _memory_retrieval_system_prompt
from ..retrieval.compression import UNTRUSTED_EVIDENCE_SYSTEM_POLICY
from ..retrieval.scoping import (
    _context_source_scope,
    _effective_retrieval_source_scope,
    _memory_aggregation_scopes,
    _retrieval_query,
    _retrieval_top_k_for_state,
    _source_scope_label,
    _stage_for_source_scope,
)
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
            agent_id=AgentId.RETRIEVAL_AGENT,
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
        agent_id=AgentId.RETRIEVAL_AGENT,
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
    _append_status(
        graph_state,
        "正在检索多源陪伴记忆。",
        stage="multi_source_memory_retrieval",
        source_scopes=scopes,
    )
    observed_toolset = AgentToolSet(retrieval=services.retrieval)
    collected = []
    searched_scopes: list[str] = []
    for scope in scopes:
        try:
            response = await observed_toolset.search_memory(
                query=query,
                top_k=MEMORY_CONTEXT_LIMIT,
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

    fused = _fuse_structured_memory_results(collected, preferred_scopes=scopes)
    reranked = _select_fused_memory_context(
        fused,
        collected,
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
        agent_id=AgentId.RETRIEVAL_AGENT,
        source_scope="knowledge_base",
        stage="knowledge_base_retrieval",
        system_prompt_factory=_knowledge_retrieval_system_prompt,
        daily_chat_fallback=False,
        update_state_scope=False,
    )


async def _retrieval_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    run_model_agent_with_tools,
    has_tool_result: Callable[[list[AgentToolResult], str], bool],
    has_empty_search_result: Callable[[list[AgentToolResult]], bool],
) -> dict[str, Any]:
    plan = graph_state.get("retrieval_plan")
    if not isinstance(plan, dict):
        state = _agent_state(graph_state)
        semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
        aggregation_scopes = _memory_aggregation_scopes(state, semantic)
        if aggregation_scopes:
            plan = {
                "memory": any(scope != "knowledge_base" for scope in aggregation_scopes),
                "knowledge": "knowledge_base" in aggregation_scopes,
            }
        else:
            effective_scope = _effective_retrieval_source_scope(state, semantic)
            plan = {
                "memory": effective_scope != "knowledge_base",
                "knowledge": effective_scope in {"all", "knowledge_base"},
            }
        graph_state["retrieval_plan"] = plan

    if plan.get("memory"):
        await _memory_retrieval_node(
            graph_state,
            services,
            run_model_agent_with_tools,
            has_tool_result,
            has_empty_search_result,
        )
        if graph_state.get("failed"):
            return graph_state
        updated_plan = graph_state.get("retrieval_plan")
        if isinstance(updated_plan, dict):
            plan = updated_plan

    if plan.get("knowledge"):
        await _knowledge_retrieval_node(
            graph_state,
            services,
            run_model_agent_with_tools,
            has_tool_result,
            has_empty_search_result,
        )
    return graph_state


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
        _append_status(
            graph_state,
            f"正在检索{_source_scope_label(source_scope)}。",
            stage=stage,
            source_scopes=(source_scope,),
        )
        if _model_for_retrieval(services, agent_id) is not None:
            system_prompt = (
                f"{system_prompt_factory(scoped_semantic)}\n\n"
                f"Evidence boundary:\n{UNTRUSTED_EVIDENCE_SYSTEM_POLICY}"
            )
            response, tool_results = await run_model_agent_with_tools(
                agent_id=agent_id,
                state=state,
                tools=(AgentToolName.SEARCH_MEMORY,),
                system_prompt=system_prompt,
                # 结构化传递检索范围：不再依赖从 prompt 文本反解析（措辞一变就静默失约束）。
                forced_source_scope=source_scope,
            )
            _emit_tool_results(graph_state, tool_results)
            await _maybe_emit_daily_chat_fallback(
                graph_state, services, state, scoped_semantic, tool_results,
                has_empty_search_result=has_empty_search_result,
                daily_chat_fallback=daily_chat_fallback,
                update_state_scope=update_state_scope,
            )
            if not has_tool_result(tool_results, "search_memory"):
                response, fallback_results = await _fallback_scoped_retrieval(
                    services,
                    state,
                    scoped_semantic,
                    top_k=_retrieval_top_k_for_state(state),
                )
                _emit_tool_results(graph_state, fallback_results)
                await _maybe_emit_daily_chat_fallback(
                    graph_state, services, state, scoped_semantic, fallback_results,
                    has_empty_search_result=has_empty_search_result,
                    daily_chat_fallback=daily_chat_fallback,
                    update_state_scope=update_state_scope,
                )
            state.response_text = "" if has_tool_result(tool_results, "search_memory") else response
            return graph_state

        _, tool_results = await _fallback_scoped_retrieval(
            services,
            state,
            scoped_semantic,
            top_k=_retrieval_top_k_for_state(state),
        )
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
        _append_status(
            graph_state,
            "长期记忆未命中，正在补查聊天日记。",
            stage="daily_chat_fallback",
            source_scopes=("daily_chat",),
        )
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
    *,
    top_k: int = 5,
) -> tuple[str, list[AgentToolResult]]:
    if services.retrieval is None:
        return "", []
    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(retrieval=services.retrieval, observer=tool_results.append)
    try:
        search_response = await observed_toolset.search_memory(
            query=semantic.query or state.user_message,
            top_k=top_k,
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


def _fuse_structured_memory_results(results, *, preferred_scopes: tuple[str, ...]):
    normalized_scopes = tuple(_fusion_scope(scope, "") for scope in preferred_scopes)
    scope_positions = {scope: index for index, scope in enumerate(normalized_scopes)}
    ranked_channels: dict[str, list[tuple[int, int, str, FusionCandidate]]] = {}
    for result in results:
        candidate = FusionCandidate(
            stable_id=_structured_result_identity(result),
            content_hash=result.content_hash or _structured_result_hash(result),
            source_scope=_fusion_scope(result.source_scope, result.relative_path),
            payload=result,
            permission_allowed=_has_any_recall_permission(result),
            lifecycle_status=result.lifecycle_status or _default_result_lifecycle(result.retrieval_mode),
            metadata_filter_passed=(
                result.filtered_reason is None
                and (result.risk_tier or "").casefold() not in {"high", "sensitive", "sensitive_blocked"}
            ),
        )
        channels = tuple(result.retrieval_channels) or (_structured_result_channel(result),)
        for channel in channels:
            declared_rank = int(result.channel_ranks.get(channel, len(ranked_channels.get(channel, ())) + 1))
            ranked_channels.setdefault(channel, []).append(
                (
                    scope_positions.get(candidate.source_scope, len(scope_positions)),
                    declared_rank,
                    candidate.stable_id,
                    candidate,
                )
            )
    channels = {
        channel: [
            candidate
            for _, _, _, candidate in sorted(items, key=lambda item: (item[0], item[1], item[2]))
        ]
        for channel, items in ranked_channels.items()
    }
    fusion = reciprocal_rank_fusion(
        channels,
        approved_scopes=normalized_scopes,
        top_k=min(40, max(1, len(results))),
    )
    return tuple(
        fused.payload.model_copy(
            update={
                "score": fused.score,
                "content_hash": fused.content_hash,
                "retrieval_channels": list(fused.channels),
                "channel_ranks": fused.channel_ranks,
                "retrieval_contributions": [
                    RetrievalContribution(
                        channel=contribution.channel,
                        rank=contribution.rank,
                        rrf_component=contribution.component,
                    )
                    for contribution in fused.contributions
                ],
            }
        )
        for fused in fusion.candidates
    )


def _select_fused_memory_context(
    fused_results,
    original_results,
    *,
    limit: int,
    per_scope_limit: int,
    char_budget: int = DEFAULT_CONTEXT_CHAR_BUDGET,
) -> CompanionRerankResult:
    source_counts: dict[str, int] = {}
    for item in original_results:
        source_counts[item.source_scope] = source_counts.get(item.source_scope, 0) + 1
    selected = []
    per_scope_seen: dict[str, int] = {}
    per_scope_drop_count = 0
    budget_drop_count = 0
    used_chars = 0
    for item in fused_results:
        if len(selected) >= max(1, limit):
            budget_drop_count += 1
            continue
        scope_count = per_scope_seen.get(item.source_scope, 0)
        if scope_count >= max(1, per_scope_limit):
            per_scope_drop_count += 1
            continue
        item_chars = len(item.snippet)
        if used_chars + item_chars > max(1, char_budget):
            budget_drop_count += 1
            continue
        selected.append(item)
        per_scope_seen[item.source_scope] = scope_count + 1
        used_chars += item_chars
    telemetry = CompanionContextBudgetTelemetry(
        strategy="deterministic_v1",
        candidate_count=len(original_results),
        selected_count=len(selected),
        duplicate_drop_count=max(
            0,
            len(original_results)
            - len({_structured_result_identity(item) for item in original_results}),
        ),
        per_scope_drop_count=per_scope_drop_count,
        budget_drop_count=budget_drop_count,
        item_budget=max(1, limit),
        per_scope_limit=max(1, per_scope_limit),
        char_budget=max(1, char_budget),
        used_chars=used_chars,
        source_counts=source_counts,
        selected_scopes=tuple(item.source_scope for item in selected),
    )
    return CompanionRerankResult(selected=tuple(selected), telemetry=telemetry)


def _structured_result_channel(result) -> str:
    mode = result.retrieval_mode
    if mode in {"graph", "graph_activation", "active_memory"}:
        return "active_memory"
    if mode in {"diary", "diary_object"} or result.source_scope == "diary_objects":
        return "diary"
    if result.source_scope == "daily_chat":
        return "daily_chat"
    if mode in {"fts", "vector"}:
        return mode
    return "fts"


def _structured_result_identity(result) -> str:
    if result.fact_id:
        return f"fact:{result.fact_id}"
    if result.candidate_id:
        return f"candidate:{result.candidate_id}"
    if result.relative_path.startswith("DiaryMemory/"):
        return f"diary:{result.chunk_id}"
    if result.relative_path.startswith("MemoryGraph/"):
        return f"graph:{result.chunk_id}"
    return f"chunk:{result.chunk_id}"


def _structured_result_hash(result) -> str:
    value = "\n".join(
        (
            _structured_result_identity(result),
            result.relative_path,
            result.title,
            result.heading or "",
            result.snippet,
        )
    )
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _has_any_recall_permission(result) -> bool:
    permissions = result.recall_permissions
    return any(
        (
            permissions.can_style_response,
            permissions.can_answer_context,
            permissions.can_proactively_mention,
            permissions.can_suggest_action,
        )
    )


def _default_result_lifecycle(retrieval_mode: str) -> str:
    return "indexed" if retrieval_mode in {"fts", "vector"} else "active"


def _fusion_scope(source_scope: str, relative_path: str) -> str:
    if source_scope == "diary_objects":
        return "diary"
    if source_scope == "knowledge_base":
        return "wiki" if relative_path.replace("\\", "/").startswith("Wiki/") else "vault_note"
    return source_scope
