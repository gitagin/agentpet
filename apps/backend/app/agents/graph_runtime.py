from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.models.api import MemorySearchResponse
from app.models.enums import AgentIntent
from app.models.enums import AgentId
from .events import AgentStatusEvent
from .events_helpers import _agent_state, _append_status, _events
from .intent import route_intent
from .memory_router import route_memory
from .services import AgentRuntimeServices, ToolCallingChatModelProtocol
from .nodes.chat import _chat_node
from .nodes.finish import _finish_node
from .nodes.memory import _memory_node
from .nodes.retrieval import _knowledge_retrieval_node, _memory_retrieval_node
from .nodes.task import _task_node
from .nodes.wiki import _wiki_node
from .prompts.system import _semantic_system_prompt
from .retrieval.router import _select_after_memory_retrieval
from .retrieval.scoping import _force_search_memory_source_scope, _select_retrieval_entry_node, _semantic_from_memory_route
from .semantic import _fallback_semantic_analysis, _parse_semantic_analysis
from .state import AgentState, SemanticAnalysisResult
from .tools import AgentToolResult, AgentToolSet, AgentToolName


logger = logging.getLogger(__name__)


class LangGraphAgentRuntime:
    """LangGraph-backed Agent coordinator for the v0.1 core tool paths.

    Chat uses LangChain v1 `create_agent` through the configured chat model
    service. Search, memory proposal, and task nodes invoke LangChain
    `StructuredTool` objects, while LangGraph coordinates routing and event
    emission for the desktop SSE contract.
    """

    def __init__(self, services: AgentRuntimeServices | None = None) -> None:
        self.services = services or AgentRuntimeServices()
        self.toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
        )
        self.graph = self._build_graph()

    async def run(self, state: AgentState):
        graph_state: dict[str, Any] = {
            "agent_state": state,
            "events": [],
            "failed": False,
        }
        yielded = 0
        async for update in self.graph.astream(graph_state, stream_mode="updates"):
            for node_state in update.values():
                events = node_state.get("events", [])
                for event in events[yielded:]:
                    yield event
                yielded = len(events)

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("route", self._route_node)
        graph.add_node("semantic_analysis_agent", self._semantic_node)
        graph.add_node("memory_retrieval_agent", self._memory_retrieval_node_adapter)
        graph.add_node("knowledge_retrieval_agent", self._knowledge_retrieval_node_adapter)
        graph.add_node("chat_agent", self._chat_node_adapter)
        graph.add_node("wiki_manager_agent", self._wiki_node_adapter)
        graph.add_node("memory_proposal_agent", self._memory_node_adapter)
        graph.add_node("task_agent", self._task_node_adapter)
        graph.add_node("finish", _finish_node)

        graph.add_edge(START, "route")
        graph.add_edge("route", "semantic_analysis_agent")
        graph.add_conditional_edges(
            "semantic_analysis_agent",
            self._select_agent_node,
            {
                "chat_agent": "chat_agent",
                "memory_retrieval_agent": "memory_retrieval_agent",
                "knowledge_retrieval_agent": "knowledge_retrieval_agent",
                "wiki_manager_agent": "wiki_manager_agent",
                "memory_proposal_agent": "memory_proposal_agent",
                "task_agent": "task_agent",
            },
        )
        graph.add_edge("chat_agent", "finish")
        graph.add_conditional_edges(
            "memory_retrieval_agent",
            _select_after_memory_retrieval,
            {
                "knowledge_retrieval_agent": "knowledge_retrieval_agent",
                "chat_agent": "chat_agent",
            },
        )
        graph.add_edge("knowledge_retrieval_agent", "chat_agent")
        graph.add_edge("wiki_manager_agent", "finish")
        graph.add_edge("memory_proposal_agent", "finish")
        graph.add_edge("task_agent", "finish")
        graph.add_edge("finish", END)
        return graph.compile()

    async def _route_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        state.route = route_intent(state.user_message)
        _events(graph_state).append(
            AgentStatusEvent(
                agent_run_id=state.agent_run_id,
                status=state.status,
                intent=state.route.intent,
                message="正在分析语义和上下文需求。",
                stage="route",
            )
        )
        return graph_state

    async def _semantic_node(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        state.memory_route = route_memory(state.user_message)
        route_semantic = _semantic_from_memory_route(state.memory_route, state)
        state.semantic_analysis = route_semantic
        if not _should_call_semantic_agent(state):
            _append_status(graph_state, "memory router selected context scope", stage="memory_router")
            return graph_state
        _append_status(graph_state, "正在调用语义分析 Agent。", stage="semantic_analysis")
        try:
            semantic_model = self._model_for(AgentId.SEMANTIC_ANALYSIS_AGENT)
            response = await semantic_model.complete(
                user_message=state.user_message,
                system_prompt=_semantic_system_prompt(),
            )
            state.semantic_analysis = _parse_semantic_analysis(response, state.user_message)
        except Exception:
            logger.warning("Semantic analysis agent failed; using fallback semantic analysis", exc_info=True)
            state.semantic_analysis = route_semantic or _fallback_semantic_analysis(state)
        return graph_state

    def _select_agent_node(self, graph_state: dict[str, Any]) -> str:
        state = _agent_state(graph_state)
        if state.route.intent == AgentIntent.PROPOSE_MEMORY:
            return "memory_proposal_agent"
        if state.route.intent == AgentIntent.MANAGE_WIKI:
            return "wiki_manager_agent"
        if state.route.intent == AgentIntent.CREATE_TASK:
            return "task_agent"
        if state.route.intent == AgentIntent.SEARCH_MEMORY:
            return _select_retrieval_entry_node(graph_state)
        if state.semantic_analysis and state.semantic_analysis.needs_context:
            return _select_retrieval_entry_node(graph_state)
        return "chat_agent"

    async def _run_model_agent_with_tools(
        self,
        *,
        agent_id: AgentId,
        state: AgentState,
        tools: tuple[AgentToolName, ...],
        system_prompt: str,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
            observer=tool_results.append,
        )
        chat_model = self._model_for(agent_id)
        if isinstance(chat_model, ToolCallingChatModelProtocol):
            tools_for_agent = observed_toolset.allowed_tools(tools)
            tools_for_agent = _force_search_memory_source_scope(tools_for_agent, system_prompt)
            result = await chat_model.complete_with_tools(
                user_message=state.user_message,
                system_prompt=system_prompt,
                tools=tools_for_agent,
            )
            return result.text, tool_results

        response = await chat_model.complete(
            user_message=state.user_message,
            system_prompt=system_prompt,
        )
        return response, tool_results

    def _model_for(self, agent_id: AgentId):
        if self.services.model_registry is not None:
            return self.services.model_registry.get(agent_id)
        if agent_id == AgentId.CHAT_AGENT:
            return self.services.chat_model
        return None

    async def _chat_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _chat_node(graph_state, self.services, _has_empty_search_result)

    async def _memory_retrieval_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _memory_retrieval_node(
            graph_state,
            self.services,
            self._run_model_agent_with_tools,
            _has_tool_result,
            _has_empty_search_result,
        )

    async def _knowledge_retrieval_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _knowledge_retrieval_node(
            graph_state,
            self.services,
            self._run_model_agent_with_tools,
            _has_tool_result,
            _has_empty_search_result,
        )

    async def _memory_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _memory_node(
            graph_state,
            self.services,
            self.toolset,
            self._run_model_agent_with_tools,
            _has_tool_result,
        )

    async def _wiki_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _wiki_node(
            graph_state,
            self.services,
            self._run_model_agent_with_tools,
            _has_wiki_action_result,
        )

    async def _task_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _task_node(graph_state, self.services)


def _should_call_semantic_agent(state: AgentState) -> bool:
    if state.memory_route and state.memory_route.semantic_fallback:
        return True
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    return False


def _has_tool_result(results: list[AgentToolResult], name: str) -> bool:
    return any(result.name == name for result in results)


def _has_empty_search_result(results: list[AgentToolResult]) -> bool:
    return any(
        result.name == "search_memory"
        and isinstance(result.value, MemorySearchResponse)
        and not result.value.results
        for result in results
    )


def _has_wiki_action_result(results: list[AgentToolResult]) -> bool:
    return any(
        result.name
        in {
            "manage_wiki_page",
            "archive_wiki_query",
            "synthesize_wiki",
            "run_wiki_lint",
            "plan_wiki_ingest",
            "plan_wiki_query_archive",
            "plan_wiki_synthesis",
            "plan_wiki_lint",
        }
        for result in results
    )


