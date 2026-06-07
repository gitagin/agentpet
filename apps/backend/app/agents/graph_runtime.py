from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.models.api import MemorySearchResponse
from app.models.enums import AgentIntent, AgentRunStatus
from app.services.agent_actions import AgentActionCreate
from app.services.chat_model import ChatModelError, StreamingChatModelClientProtocol
from app.models.enums import AgentId
from .agent_runner import run_agent
from .events import AgentDoneEvent, AgentErrorEvent, AgentStatusEvent, AgentTokenEvent, NegotiationDoneEvent, NegotiationStepEvent
from .events_helpers import _agent_state, _append_status, _events
from .immediate_understanding import extract_immediate_understanding
from .intent import route_intent
from .memory_router import route_memory
from .negotiation_graph import build_negotiation_graph
from .nodes.chat import _chat_node, _message_with_runtime_context
from .nodes.finish import _finish_node
from .nodes.memory import _memory_node
from .nodes.orchestrator import OrchestratorNode
from .nodes.retrieval import _knowledge_retrieval_node, _memory_retrieval_node
from .nodes.task import _task_node
from .nodes.wiki import _wiki_node
from .prompts.system import _semantic_system_prompt
from .registry import AgentRegistry, default_agent_registry
from .retrieval.router import _chat_agent_tool_names, _select_after_memory_retrieval
from .retrieval.scoping import _force_search_memory_source_scope, _select_retrieval_entry_node, _semantic_from_memory_route
from .runtime_helpers import _chat_system_prompt, _continuity_signal, _continuity_signal_event
from .semantic import _fallback_semantic_analysis, _parse_semantic_analysis
from .services import AgentRuntimeServices, ToolCallingChatModelProtocol
from .state import AgentState, NegotiationState, SemanticAnalysisResult
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
        self.agent_registry = self._build_agent_registry()
        self.graph = self._build_graph()

    async def run(self, state: AgentState):
        streaming_graph_state = await self._prepare_streaming_chat_fast_path(state)
        if streaming_graph_state is not None:
            async for event in self._run_streaming_chat_fast_path(streaming_graph_state):
                yield event
            return

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

    async def _prepare_streaming_chat_fast_path(self, state: AgentState) -> dict[str, Any] | None:
        try:
            chat_model = self._model_for(AgentId.CHAT_AGENT)
        except Exception:
            return None
        if not isinstance(chat_model, StreamingChatModelClientProtocol):
            return None

        graph_state: dict[str, Any] = {
            "agent_state": state.model_copy(deep=True),
            "events": [],
            "failed": False,
        }
        await self._route_node(graph_state)
        await self._semantic_node(graph_state)
        if graph_state.get("failed"):
            return None

        prepared_state = _agent_state(graph_state)
        if prepared_state.route is None or prepared_state.route.intent != AgentIntent.CHAT:
            return None
        if prepared_state.citations or _needs_chat_context(prepared_state):
            return None
        if _chat_agent_tool_names(prepared_state, self.services):
            return None
        return graph_state

    async def _run_streaming_chat_fast_path(self, graph_state: dict[str, Any]) -> AsyncIterator[Any]:
        state = _agent_state(graph_state)
        for event in _events(graph_state):
            yield event

        signal = _continuity_signal(self.services.continuity)
        if signal is not None:
            yield _continuity_signal_event(state.agent_run_id, signal)

        yield AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=state.route.intent if state.route else None,
            message="正在生成桌宠回复。",
            stage="chat_generation",
        )

        chat_model = self._model_for(AgentId.CHAT_AGENT)
        if not isinstance(chat_model, StreamingChatModelClientProtocol):
            return

        chunks: list[str] = []
        try:
            async for chunk in chat_model.stream_complete(
                user_message=_message_with_runtime_context(self.services, state),
                system_prompt=_chat_system_prompt(),
            ):
                if not chunk:
                    continue
                chunks.append(chunk)
                yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
        except ChatModelError as exc:
            state.status = AgentRunStatus.FAILED
            state.error_code = exc.code
            state.error_message = str(exc)
            yield AgentErrorEvent(agent_run_id=state.agent_run_id, code=exc.code, message=str(exc))
            return
        except Exception:
            state.status = AgentRunStatus.FAILED
            state.error_code = "model_invocation_failed"
            state.error_message = "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。"
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=state.error_code,
                message=state.error_message,
            )
            return

        response = "".join(chunks).strip()
        if not response:
            state.status = AgentRunStatus.FAILED
            state.error_code = "empty_response"
            state.error_message = "模型服务返回了空回复。"
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=state.error_code,
                message=state.error_message,
            )
            return

        state.response_text = response
        state.status = AgentRunStatus.SUCCESS
        yield AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=state.route.intent if state.route else None,
            message="回复已完成，后台保存聊天记忆。",
            stage="background_memory",
        )
        yield AgentDoneEvent(
            agent_run_id=state.agent_run_id,
            intent=state.route.intent,
            text=response,
        )

    def _build_graph(self):
        if self._should_use_negotiation():
            return build_negotiation_graph(
                route_node=self._route_node,
                semantic_node=self._semantic_node,
                select_after_semantic=self._select_after_semantic_for_negotiation,
                orchestrator_node=self._orchestrator_node_adapter,
                invoke_agent_node=self._invoke_agent_node_adapter,
                synthesizer_node=self._synthesizer_node_adapter,
                finish_node=_finish_node,
            )

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
        state.immediate_understanding = extract_immediate_understanding(
            state.user_message,
            existing=state.immediate_understanding,
        )
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
            _append_status(graph_state, "已选择上下文范围。", stage="memory_router")
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

    def _select_after_semantic_for_negotiation(self, graph_state: dict[str, Any]) -> str:
        state = _negotiation_state(graph_state)
        state.max_rounds = int(getattr(self.services.automation_settings, "max_rounds", state.max_rounds))
        state.confidence_threshold = float(
            getattr(self.services.automation_settings, "confidence_threshold", state.confidence_threshold)
        )
        return "synthesizer" if self._should_use_fast_path(state) else "orchestrator"

    async def _orchestrator_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _negotiation_state(graph_state)
        model = self._model_for(AgentId.CHAT_AGENT)
        if model is None:
            graph_state.update({"next": "synthesize"})
            return graph_state
        result = await OrchestratorNode(
            _PromptOnlyModel(model),
            self.agent_registry,
            max_rounds=int(getattr(self.services.automation_settings, "max_rounds", state.max_rounds)),
            confidence_threshold=float(
                getattr(self.services.automation_settings, "confidence_threshold", state.confidence_threshold)
            ),
        )(state)
        state.orchestrator_decisions = result.get("orchestrator_decisions", state.orchestrator_decisions)
        state.fallback_triggered = result.get("fallback_triggered", state.fallback_triggered)
        _append_negotiation_step_event(graph_state, state, result)
        graph_state.update(result)
        return graph_state

    async def _invoke_agent_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _negotiation_state(graph_state)
        next_agent = graph_state.get("next_agent")
        if isinstance(next_agent, str):
            next_agent = AgentId(next_agent)
        if not isinstance(next_agent, AgentId):
            graph_state["next"] = "synthesize"
            return graph_state

        agent_input = graph_state.get("agent_input") or state.user_message
        invocation = await run_agent(next_agent, agent_input, state, self.agent_registry)
        state.invocation_history.append(invocation)
        state.round += 1
        state.collected_context = _append_collected_context(state.collected_context, invocation)
        graph_state["next"] = "synthesize"
        return graph_state

    async def _synthesizer_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        if isinstance(state, NegotiationState):
            if state.collected_context:
                state.user_message = _message_with_negotiation_context(state)
            result = await self._chat_node_adapter(graph_state)
            if state.orchestrator_decisions or state.invocation_history or state.fallback_triggered:
                _append_negotiation_done_event(graph_state, state)
                self._record_negotiation_stats(state)
            return result
        return await self._chat_node_adapter(graph_state)

    def _should_use_negotiation(self) -> bool:
        return bool(getattr(self.services.automation_settings, "use_negotiation", True))

    def _should_use_fast_path(self, state: AgentState) -> bool:
        semantic = state.semantic_analysis
        semantic_confidence = semantic.confidence if semantic is not None else 1.0
        if semantic is not None and not semantic.needs_context:
            semantic_confidence = max(semantic_confidence, 0.9)
        return bool(
            semantic_confidence >= 0.9
            and state.route is not None
            and state.route.intent == AgentIntent.CHAT
            and getattr(state, "round", 0) == 0
        )

    def _build_agent_registry(self) -> AgentRegistry:
        registry = AgentRegistry()
        for capability in default_agent_registry.all_capabilities():
            registry.register(capability, self._agent_handler_for(capability.agent_id))
        return registry

    def _agent_handler_for(self, agent_id: AgentId):
        async def handler(input_query: str, state: NegotiationState) -> dict[str, Any]:
            graph_state: dict[str, Any] = {"agent_state": state, "events": [], "failed": False}
            original_message = state.user_message
            state.user_message = input_query
            try:
                if agent_id == AgentId.MEMORY_RETRIEVAL_AGENT:
                    await self._memory_retrieval_node_adapter(graph_state)
                elif agent_id == AgentId.KNOWLEDGE_RETRIEVAL_AGENT:
                    await self._knowledge_retrieval_node_adapter(graph_state)
                elif agent_id == AgentId.WIKI_MANAGER_AGENT:
                    await self._wiki_node_adapter(graph_state)
                elif agent_id == AgentId.MEMORY_PROPOSAL_AGENT:
                    await self._memory_node_adapter(graph_state)
                elif agent_id == AgentId.TASK_AGENT:
                    await self._task_node_adapter(graph_state)
                else:
                    await self._chat_node_adapter(graph_state)
            finally:
                state.user_message = original_message
            return {
                "result": state.response_text,
                "citations": state.citations,
                "proposal_id": state.proposal_id,
                "task_id": state.task_id,
                "confidence": 0.6,
            }

        return handler

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
        await self._ensure_pre_chat_context(graph_state)
        if graph_state.get("failed"):
            return graph_state
        return await _chat_node(graph_state, self.services, _has_empty_search_result)

    async def _ensure_pre_chat_context(self, graph_state: dict[str, Any]) -> None:
        state = _agent_state(graph_state)
        if state.citations or graph_state.get("pre_chat_context_attempted") or graph_state.get("retrieval_plan"):
            return
        if not _needs_chat_context(state):
            return

        graph_state["pre_chat_context_attempted"] = True
        entry_node = _select_retrieval_entry_node(graph_state)
        if entry_node == "memory_retrieval_agent":
            await self._memory_retrieval_node_adapter(graph_state)
            if graph_state.get("failed"):
                return
            if _select_after_memory_retrieval(graph_state) == "knowledge_retrieval_agent":
                await self._knowledge_retrieval_node_adapter(graph_state)
            return
        if entry_node == "knowledge_retrieval_agent":
            await self._knowledge_retrieval_node_adapter(graph_state)

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

    def _record_negotiation_stats(self, state: NegotiationState) -> None:
        recorder = self.services.agent_action_recorder
        if recorder is None:
            return
        agents_invoked = [str(invocation.agent_id) for invocation in state.invocation_history]
        total_latency_ms = sum(invocation.latency_ms for invocation in state.invocation_history)
        try:
            recorder(
                AgentActionCreate(
                    action_type="agent.negotiation",
                    title="已完成多 Agent 协商",
                    summary=f"协商 {state.round} 轮，调用 {len(agents_invoked)} 个子 Agent。",
                    source_agent_run_id=state.agent_run_id,
                    source_conversation_id=state.conversation_id,
                    source_message_id=state.message_id,
                    risk_tier="low",
                    decision="auto",
                    status="completed",
                    metadata={
                        "agents_invoked": agents_invoked,
                        "fallback": state.fallback_triggered,
                        "final_confidence": _latest_negotiation_confidence(state),
                    },
                    reversible=False,
                    negotiation_rounds=state.round,
                    total_tokens=0,
                    total_latency_ms=total_latency_ms,
                )
            )
        except Exception:
            logger.warning("Failed to record negotiation stats", exc_info=True)


def _negotiation_state(graph_state: dict[str, Any]) -> NegotiationState:
    state = _agent_state(graph_state)
    if isinstance(state, NegotiationState):
        return state
    negotiation_state = NegotiationState(**state.model_dump())
    graph_state["agent_state"] = negotiation_state
    return negotiation_state


class _PromptOnlyModel:
    def __init__(self, model: Any) -> None:
        self.model = model

    async def complete(self, prompt: str) -> Any:
        return await self.model.complete(user_message=prompt, system_prompt="orchestrator-json-only")


def _append_collected_context(current: str, invocation: Any) -> str:
    output = invocation.output
    if not isinstance(output, str):
        output = str(output)
    line = f"[{invocation.agent_id}] {output}"
    return "\n".join(part for part in (current.strip(), line) if part)


def _message_with_negotiation_context(state: NegotiationState) -> str:
    return "\n\n".join(
        [
            f"用户原始问题：{state.user_message}",
            "多 Agent 协商已收集上下文：",
            state.collected_context,
            "请基于以上上下文，用桌宠口吻给出简短自然回复。",
        ]
    )


def _append_negotiation_step_event(
    graph_state: dict[str, Any], state: NegotiationState, result: dict[str, Any]
) -> None:
    if result.get("fallback_triggered"):
        _events(graph_state).append(
            NegotiationStepEvent(
                agent_run_id=state.agent_run_id,
                round=state.round,
                agent="orchestrator",
                action="synthesizing",
                reasoning="达到协商轮次上限，转入最终合成。",
                confidence=_latest_negotiation_confidence(state),
                message="达到轮次上限，正在整理已有结果。",
            )
        )
        return

    decision = state.orchestrator_decisions[-1] if state.orchestrator_decisions else None
    if not isinstance(decision, dict):
        return
    next_agent = result.get("next_agent") or decision.get("agent") or "synthesizer"
    action = "invoking" if result.get("next") == "invoke_agent" else "synthesizing"
    message = "正在调用子 Agent 补充信息。" if action == "invoking" else "已有信息足够，正在合成回复。"
    _events(graph_state).append(
        NegotiationStepEvent(
            agent_run_id=state.agent_run_id,
            round=state.round,
            agent=str(next_agent),
            action=action,
            reasoning=str(decision.get("reasoning") or ""),
            confidence=float(decision.get("confidence") or 0.0),
            message=message,
        )
    )


def _append_negotiation_done_event(graph_state: dict[str, Any], state: NegotiationState) -> None:
    _events(graph_state).append(
        NegotiationDoneEvent(
            agent_run_id=state.agent_run_id,
            total_rounds=state.round,
            agents_invoked=[str(invocation.agent_id) for invocation in state.invocation_history],
            total_latency_ms=sum(invocation.latency_ms for invocation in state.invocation_history),
            final_confidence=_latest_negotiation_confidence(state),
            fallback=state.fallback_triggered,
        )
    )


def _latest_negotiation_confidence(state: NegotiationState) -> float:
    decision = state.orchestrator_decisions[-1] if state.orchestrator_decisions else None
    if isinstance(decision, dict):
        confidence = decision.get("confidence")
        if isinstance(confidence, int | float):
            return float(confidence)
    if state.invocation_history:
        return float(state.invocation_history[-1].confidence)
    return 0.0


def _should_call_semantic_agent(state: AgentState) -> bool:
    if state.memory_route and state.memory_route.semantic_fallback:
        return True
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    return False


def _needs_chat_context(state: AgentState) -> bool:
    semantic = state.semantic_analysis
    if semantic is not None and semantic.needs_context and semantic.source_scope != "none":
        return True
    if state.route is not None and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    route = state.memory_route
    return (
        route is not None
        and not route.semantic_fallback
        and bool(route.all_scopes)
        and route.all_scopes != ("none",)
    )


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


