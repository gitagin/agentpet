from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool

from app.models.api import MemorySearchResponse
from app.models.enums import AgentIntent

from ..events_helpers import _agent_state
from ..runtime_helpers import _strip_search_command
from ..state import AgentState, SemanticAnalysisResult
from ..memory_router import MemoryRoute
from ..semantic import _fallback_semantic_analysis
from .compression import filter_search_response

# 从 graph_runtime.py 迁移，原函数名：_select_retrieval_entry_node, _effective_retrieval_source_scope, _retrieval_query, _semantic_from_memory_route, _source_scope_from_memory_route, _memory_aggregation_scopes, _force_search_memory_source_scope, _source_scope_from_prompt, _context_source_weight, _context_source_scope, _source_scope_label, _stage_for_source_scope

logger = logging.getLogger(__name__)


def _select_retrieval_entry_node(graph_state: dict[str, object]) -> str:
    state = _agent_state(graph_state)
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    aggregation_scopes = _memory_aggregation_scopes(state, semantic)
    if aggregation_scopes:
        graph_state["retrieval_plan"] = {
            "memory": any(scope != "knowledge_base" for scope in aggregation_scopes),
            "knowledge": "knowledge_base" in aggregation_scopes,
        }
        return "retrieval_agent"
    effective_scope = _effective_retrieval_source_scope(state, semantic)
    if effective_scope == "knowledge_base":
        graph_state["retrieval_plan"] = {"memory": False, "knowledge": True}
        return "retrieval_agent"
    if effective_scope == "diary_objects":
        graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
        return "retrieval_agent"
    if effective_scope == "all":
        graph_state["retrieval_plan"] = {"memory": True, "knowledge": True}
        return "retrieval_agent"
    graph_state["retrieval_plan"] = {"memory": True, "knowledge": False}
    return "retrieval_agent"


def _effective_retrieval_source_scope(state: AgentState, semantic: SemanticAnalysisResult) -> str:
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY and semantic.source_scope == "none":
        return "all"
    return semantic.source_scope


def _retrieval_query(state: AgentState, semantic: SemanticAnalysisResult) -> str:
    if semantic.query.strip():
        return semantic.query
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return _strip_search_command(state.user_message)
    return state.user_message


def _retrieval_top_k_for_state(state: AgentState) -> int:
    if state.memory_route is None:
        return 5
    return state.memory_route.retrieval_top_k


def _semantic_from_memory_route(route: MemoryRoute, state: AgentState) -> SemanticAnalysisResult:
    source_scope = _source_scope_from_memory_route(route)
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY and source_scope == "none":
        source_scope = "all"
    return SemanticAnalysisResult(
        needs_context=source_scope != "none",
        source_scope=source_scope,
        query=_strip_search_command(route.query or state.user_message),
        answer_style=route.answer_style,
        confidence=route.confidence,
        reason=route.reason,
    )


def _source_scope_from_memory_route(route: MemoryRoute) -> str:
    scopes = route.all_scopes
    if not scopes or scopes == ("none",):
        return "none"
    if not route.primary_scopes:
        return route.legacy_source_scope
    first = route.primary_scopes[0] if route.primary_scopes else scopes[0]
    if first == "graph_facts":
        return "personal_memory" if len(scopes) == 1 else route.legacy_source_scope
    if first in {"knowledge_base", "personal_memory", "diary_objects", "daily_chat"}:
        return first
    return route.legacy_source_scope


def _memory_aggregation_scopes(state: AgentState, semantic: SemanticAnalysisResult) -> tuple[str, ...]:
    route = state.memory_route
    if route is None or not semantic.needs_context:
        return ()
    if route.semantic_fallback:
        return ()
    if route.reason not in {
        "long_term_preference",
        "personal_experience_or_emotional_continuity",
    }:
        return ()
    scopes = _tool_scopes_from_memory_route(route)
    if len(scopes) <= 1:
        return ()
    effective_scope = _effective_retrieval_source_scope(state, semantic)
    if effective_scope == "all":
        return scopes
    if semantic.reason != route.reason:
        return ()
    return scopes


def _force_search_memory_source_scope(
    tools: list[StructuredTool],
    system_prompt: str,
    *,
    forced_source_scope: str | None = None,
    forced_top_k: int | None = None,
) -> list[StructuredTool]:
    """Force the retrieval scope onto search_memory.

    Prefer the structured `forced_source_scope` passed by the caller; parsing the
    scope back out of the prompt text is only a legacy fallback (the prompt is
    presentation, so re-parsing it couples wording to enforcement).
    """
    source_scope = forced_source_scope
    if source_scope is None:
        source_scope = _source_scope_from_prompt(system_prompt)
    return _guard_search_memory_tools(
        tools,
        forced_source_scope=source_scope,
        forced_top_k=forced_top_k,
    )


def _enforceable_source_scope(value: str | None) -> str | None:
    """The scope a tool call must use, or None when this turn decided nothing.

    "none" is a decision about retrieval, not a searchable scope, so it is never
    forwarded as a tool argument; the guard reports the resulting free choice
    instead of pretending a constraint is in force.
    """
    if value in {"personal_memory", "diary_objects", "daily_chat", "knowledge_base", "all"}:
        return value
    return None


def _guard_search_memory_tools(
    tools: list[StructuredTool],
    *,
    forced_source_scope: str | None = None,
    forced_top_k: int | None = None,
) -> list[StructuredTool]:
    wrapped = []
    for tool in tools:
        if tool.name != "search_memory":
            wrapped.append(tool)
            continue

        forced_scope = _enforceable_source_scope(forced_source_scope)
        if forced_scope is None:
            # 没有可执行的范围决定时,搜索范围由模型自选(缺省 all)。这条曾经是静默的:
            # 调用方没给结构化范围、提示词又反解析不出来时,约束就没了,而日志里看不出
            # 任何异常。宁可吵一点,也不要"以为在管、其实没管"。
            logger.warning(
                "search_memory is called without an enforced source scope; the model chooses it"
            )

        async def search_memory_with_scope(
            query: str,
            top_k: int = 5,
            source_scope: str = "",
            _tool=tool,
            _forced_scope: str = forced_scope,
            _forced_top_k: int | None = forced_top_k,
        ):
            effective_scope = _forced_scope or source_scope or "all"
            response = await _tool.ainvoke(
                {
                    "query": query,
                    "top_k": _forced_top_k if _forced_top_k is not None else top_k,
                    "source_scope": effective_scope,
                }
            )
            if isinstance(response, MemorySearchResponse):
                return filter_search_response(response)
            return response

        wrapped.append(
            StructuredTool.from_function(
                coroutine=search_memory_with_scope,
                name=tool.name,
                description=tool.description,
                args_schema=tool.args_schema,
            )
        )
    return wrapped


def _source_scope_from_prompt(system_prompt: str) -> str | None:
    marker = "source_scope="
    start = system_prompt.find(marker)
    if start < 0:
        return None
    rest = system_prompt[start + len(marker) :]
    if not rest:
        return None
    quote = rest[0]
    if quote not in {"'", '"'}:
        return None
    end = rest.find(quote, 1)
    if end < 0:
        return None
    scope = rest[1:end]
    if scope in {"personal_memory", "diary_objects", "daily_chat", "knowledge_base", "all"}:
        return scope
    return None


def _tool_scopes_from_memory_route(route: MemoryRoute) -> tuple[str, ...]:
    scopes: list[str] = []
    for scope in route.all_scopes:
        if scope == "none":
            continue
        tool_scope = "personal_memory" if scope == "graph_facts" else scope
        if tool_scope in scopes:
            continue
        scopes.append(tool_scope)
    return tuple(scopes)


def _context_source_weight(source_scope: str) -> int:
    return {
        "graph_facts": 5,
        "personal_memory": 4,
        "diary_objects": 3,
        "daily_chat": 2,
        "knowledge_base": 1,
    }.get(source_scope, 0)


def _context_source_scope(results, fallback: str) -> str:
    scopes = []
    for result in results:
        if result.source_scope not in scopes:
            scopes.append(result.source_scope)
    if len(scopes) == 1:
        return scopes[0]
    if scopes:
        return "all"
    return fallback


def _source_scope_label(source_scope: str) -> str:
    return {
        "personal_memory": "记忆本",
        "diary_objects": "结构化聊天日记",
        "daily_chat": "聊天日记",
        "knowledge_base": "资料库",
        "all": "记忆/资料",
    }.get(source_scope, "记忆/资料")


def _stage_for_source_scope(source_scope: str) -> str:
    return {
        "personal_memory": "personal_memory_retrieval",
        "diary_objects": "diary_object_retrieval",
        "daily_chat": "daily_chat_retrieval",
        "knowledge_base": "knowledge_base_retrieval",
        "all": "multi_source_retrieval",
    }.get(source_scope, "multi_source_retrieval")
