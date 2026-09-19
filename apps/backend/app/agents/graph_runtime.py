from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.models.api import MemorySearchResponse
from app.models.event_payloads import (
    AgentTraceAgentId,
    AgentTraceCounts,
    AgentTracePhase,
    AgentTraceReasonCode,
    AgentTraceSourceScope,
    AgentTraceStatus,
)
from app.models.enums import AgentIntent, AgentRunStatus
from app.services.agent_actions import AgentActionCreate
from app.services.chat_model import ChatModelError, StreamingChatModelClientProtocol
from app.models.enums import AgentId
from .agent_runner import run_agent
from .events import AgentDoneEvent, AgentErrorEvent, AgentStatusEvent, AgentTokenEvent, NegotiationDoneEvent, NegotiationStepEvent, public_agent_error
from .events_helpers import _agent_state, _append_status, _events, _record_node_error
from .ephemeral_lifecycle import build_ephemeral_lifecycle
from .immediate_understanding import extract_immediate_understanding
from .intent import is_high_risk_mutation_request, route_intent
from .memory_router import route_memory
from .checkpointer import CheckpointConflictError, CheckpointError, CheckpointExpiredError
from .contracts import MAX_PLANNING_ROUNDS, ActionProposal, PolicyDecision
from .negotiation_graph import build_negotiation_graph
from .nodes.action import _action_planner_node, _canonical_payload_hash, _execute_action_plan
from .nodes.chat import _chat_node, _message_with_runtime_context
from .nodes.finish import _finish_node
from .nodes.orchestrator import OrchestratorNode
from .nodes.policy_guard import evaluate_action_proposal
from .nodes.retrieval import _retrieval_node
from .prompts.system import _semantic_system_prompt
from .registry import AgentRegistry, default_agent_registry
from .retrieval.router import _chat_agent_tool_names, _mentions_time_topic
from .retrieval.scoping import (
    _force_search_memory_source_scope,
    _explicit_tool_scopes,
    _retrieval_top_k_for_state,
    _select_retrieval_entry_node,
    _semantic_from_memory_route,
)
from .runtime_helpers import _chat_system_prompt, _continuity_signal, _continuity_signal_event
from .semantic import _fallback_classifier, _fallback_semantic_analysis, _parse_classifier_analysis
from .services import AgentRuntimeServices, ToolCallingChatModelProtocol
from .state import ActionPlan, AgentRoute, AgentState, NegotiationState, SemanticAnalysisResult
from .tools import AgentToolResult, AgentToolSet, AgentToolName


logger = logging.getLogger(__name__)


_MAX_NEGOTIATION_ROUNDS = MAX_PLANNING_ROUNDS
_NEGOTIATION_AGENT_TIMEOUT_SECONDS = 15.0


class LangGraphAgentRuntime:
    """LangGraph-backed Agent coordinator for the v0.1 core tool paths.

    Chat uses LangChain v1 `create_agent` through the configured chat model
    service. Search, memory proposal, and task nodes invoke LangChain
    `StructuredTool` objects, while LangGraph coordinates routing and event
    emission for the desktop SSE contract.
    """

    def __init__(self, services: AgentRuntimeServices | None = None) -> None:
        self.services = services or AgentRuntimeServices()
        if (
            self.services.allow_ephemeral_lifecycle
            and self.services.action_lifecycle is None
        ):
            self.services.action_lifecycle = build_ephemeral_lifecycle(self.services)
        self.toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
            wiki_reader=self.services.wiki_reader,
        )
        self.agent_registry = self._build_agent_registry()
        self.graph = self._build_graph()
        self.negotiation_graph = self._build_negotiation_graph()

    async def run(self, state: AgentState):
        self.completed_state = None
        if state.local_privacy_mode and state.local_privacy_sensitive_reason:
            async for event in self._run_local_privacy_mode(state):
                yield event
            return

        use_negotiation = self._should_use_negotiation(state)
        if not use_negotiation:
            streaming_graph_state = await self._prepare_streaming_chat_fast_path(state)
            if streaming_graph_state is not None:
                async for event in self._run_streaming_chat_fast_path(streaming_graph_state):
                    if isinstance(event, AgentDoneEvent):
                        self.completed_state = _agent_state(streaming_graph_state)
                    yield event
                return

        graph_state: dict[str, Any] = {
            "agent_state": state,
            "events": [],
            "failed": False,
        }
        yielded = 0
        active_graph = self.negotiation_graph if use_negotiation else self.graph
        async for update in active_graph.astream(graph_state, stream_mode="updates"):
            for node_state in update.values():
                events = node_state.get("events", [])
                for event in events[yielded:]:
                    if isinstance(event, AgentDoneEvent):
                        self.completed_state = node_state.get("agent_state")
                    yield event
                yielded = len(events)

    async def resume_checkpoint(
        self,
        checkpoint_id: str,
        *,
        decision_id: str,
        decision: str,
        policy_version: str,
    ) -> dict[str, Any]:
        store = self.services.checkpoint_store
        if store is None:
            raise CheckpointError("checkpoint_store_unavailable")
        if decision not in {"approved", "rejected"}:
            raise CheckpointError("invalid_decision")
        record = store.get(checkpoint_id)
        if record.graph_version != "agent-graph-v1" or record.state_version != "agent-state-v1":
            raise CheckpointConflictError("checkpoint_version_mismatch")
        if record.status in {"completed", "cancelled", "expired", "failed_recovery"}:
            return {
                "checkpoint_id": checkpoint_id,
                "status": record.status,
                "effect_applied": False,
            }
        if record.status == "rejected":
            payload, _plan, proposal, stored_policy = self._checkpoint_action_contract(record)
            await self._record_checkpoint_rejection(
                checkpoint_id=checkpoint_id,
                proposal=proposal,
                stored_policy=stored_policy,
                payload=payload,
            )
            return {
                "checkpoint_id": checkpoint_id,
                "status": "rejected",
                "effect_applied": False,
            }
        payload = record.state
        if str(payload.get("decision_id") or "") != decision_id:
            raise CheckpointConflictError("decision_id_mismatch")
        decision_expires_at = datetime.fromisoformat(str(payload["decision_expires_at"]))
        if decision_expires_at <= datetime.now(timezone.utc):
            store.expire_checkpoint(checkpoint_id)
            raise CheckpointExpiredError(checkpoint_id)
        payload, plan, proposal, stored_policy = self._checkpoint_action_contract(record)
        if stored_policy.policy_version != policy_version:
            raise CheckpointConflictError("policy_version_mismatch")
        outcome = store.claim_decision(
            checkpoint_id=checkpoint_id,
            decision_id=decision_id,
            decision=decision,
            policy_version=policy_version,
        )
        if outcome.decision != "approved":
            if outcome.decision == "rejected":
                await self._record_checkpoint_rejection(
                    checkpoint_id=checkpoint_id,
                    proposal=proposal,
                    stored_policy=stored_policy,
                    payload=payload,
                )
            return {
                "checkpoint_id": checkpoint_id,
                "status": outcome.decision,
                "effect_applied": False,
            }


        rechecked = evaluate_action_proposal(proposal)
        if (
            rechecked.decision == "denied"
            or rechecked.idempotency_key != stored_policy.idempotency_key
            # 检查点保存后若该动作的风险等级被调高（medium→high），
            # 不能再借 confirmed_by_user 绕过 high-risk 校验，应要求重新确认。
            or (rechecked.risk_tier == "high" and stored_policy.risk_tier != "high")
        ):
            store.mark_status(checkpoint_id, "failed_recovery")
            raise CheckpointConflictError("policy_revalidation_failed")
        approved_policy = rechecked.model_copy(
            update={
                "decision": "approved",
                "requires_confirmation": False,
                "confirmed_by_user": True,
            }
        )
        plan.decision = "auto"
        plan.control_state = "approved"
        state = AgentState(
            conversation_id=str(payload["conversation_id"]),
            message_id=str(payload["message_id"]),
            agent_run_id=str(payload["agent_run_id"]),
            user_message=str(payload.get("user_message") or proposal.parameters.get("source_text") or ""),
            action_plan=plan,
            action_plans=[plan],
            action_proposals=[proposal],
            policy_decisions=[approved_policy],
            checkpoint_id=checkpoint_id,
            checkpoint_status="approved",
        )
        graph_state: dict[str, Any] = {"agent_state": state, "events": [], "failed": False}
        await _execute_action_plan(graph_state, self.services)
        if plan.control_state == "completed" and plan.executed:
            receipt_ref = plan.receipt_ref
            store.mark_status(checkpoint_id, "completed", terminal_receipt_ref=receipt_ref)
            return {
                "checkpoint_id": checkpoint_id,
                "status": "completed",
                "effect_applied": not plan.duplicate,
            }
        store.mark_status(checkpoint_id, "failed_recovery")
        return {
            "checkpoint_id": checkpoint_id,
            "status": "failed_recovery",
            "effect_applied": False,
        }

    @staticmethod
    def _checkpoint_action_contract(
        record: Any,
    ) -> tuple[dict[str, Any], ActionPlan, ActionProposal, PolicyDecision]:
        payload = dict(record.state)
        plan = ActionPlan.model_validate(payload["action_plan"])
        proposal = ActionProposal.model_validate(payload["action_proposal"])
        stored_policy = PolicyDecision.model_validate(payload["policy_decision"])
        if record.run_id != str(payload["agent_run_id"]):
            raise CheckpointConflictError("run_id_mismatch")
        if record.action_proposal_id != proposal.proposal_id:
            raise CheckpointConflictError("proposal_id_mismatch")
        canonical_payload_hash = payload.get("canonical_payload_hash")
        if (
            canonical_payload_hash is not None
            and str(canonical_payload_hash) != _canonical_payload_hash(stored_policy)
        ):
            raise CheckpointConflictError("canonical_payload_mismatch")
        return payload, plan, proposal, stored_policy

    async def _record_checkpoint_rejection(
        self,
        *,
        checkpoint_id: str,
        proposal: ActionProposal,
        stored_policy: PolicyDecision,
        payload: dict[str, Any],
    ) -> None:
        coordinator = self.services.action_lifecycle
        if coordinator is None:
            return
        denied_policy = stored_policy.model_copy(
            update={
                "decision": "denied",
                "requires_confirmation": False,
                "confirmation_digest": None,
                "confirmed_by_user": False,
            }
        )
        try:
            outcome = await coordinator.execute(
                proposal,
                denied_policy,
                source_run_id=str(payload["agent_run_id"]),
                source_conversation_id=str(payload["conversation_id"]),
            )
        except Exception as exc:
            if self.services.checkpoint_store is not None:
                self.services.checkpoint_store.mark_status(checkpoint_id, "failed_recovery")
            raise CheckpointConflictError("rejection_action_record_failed") from exc
        if (
            outcome.receipt.status != "denied"
            or outcome.action.status != "denied"
            or outcome.receipt.idempotency_key != stored_policy.idempotency_key
        ):
            if self.services.checkpoint_store is not None:
                self.services.checkpoint_store.mark_status(checkpoint_id, "failed_recovery")
            raise CheckpointConflictError("rejection_action_state_mismatch")

    async def _run_local_privacy_mode(self, state: AgentState) -> AsyncIterator[Any]:
        state.status = AgentRunStatus.RUNNING
        state.route = AgentRoute(
            intent=AgentIntent.CHAT,
            confidence=1.0,
            reason="local_privacy_mode_sensitive_input",
        )
        yield AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=AgentIntent.CHAT,
            message="已启用本地隐私模式；这条敏感内容只做本机关键词检索，不发送到模型 API。",
            stage="local_privacy_guard",
        )

        match_count = 0
        retrieval_error: str | None = None
        if self.services.retrieval is not None:
            try:
                search_response = await self.services.retrieval.search(
                    query=state.user_message,
                    top_k=5,
                    mode="fts",
                    source_scope="all",
                )
            except Exception as exc:
                # A failed local probe is different from a successful empty
                # search.  Keep the safe response generic, but expose that
                # distinction to the user and retain the traceback in logs.
                logger.warning(
                    "Local-privacy retrieval probe failed for agent_run_id=%s.",
                    state.agent_run_id,
                    exc_info=True,
                )
                retrieval_error = type(exc).__name__
            else:
                match_count = len(search_response.results)

        response = _local_privacy_response(
            match_count,
            state.local_privacy_sensitive_reason,
            retrieval_error=retrieval_error,
        )
        state.response_text = response
        state.status = AgentRunStatus.SUCCESS
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
        yield AgentDoneEvent(
            agent_run_id=state.agent_run_id,
            intent=AgentIntent.CHAT,
            text=response,
            answer_basis=state.answer_basis,
        )

    async def _prepare_streaming_chat_fast_path(self, state: AgentState) -> dict[str, Any] | None:
        if _requires_graph_execution(state.user_message):
            return None
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
            state.error_code, state.error_message = public_agent_error(exc.code)
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=state.error_code,
                message=state.error_message,
            )
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
            answer_basis=state.answer_basis,
        )

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("route", self._route_node)
        graph.add_node("semantic_analysis_agent", self._semantic_node)
        graph.add_node("retrieval_agent", self._retrieval_node_adapter)
        graph.add_node("action_agent", self._action_node_adapter)
        graph.add_node("chat_agent", self._chat_node_adapter)
        graph.add_node("finish", self._finish_node_adapter)

        graph.add_edge(START, "route")
        graph.add_edge("route", "semantic_analysis_agent")
        graph.add_conditional_edges(
            "semantic_analysis_agent",
            self._select_agent_node,
            {
                "chat_agent": "chat_agent",
                "retrieval_agent": "retrieval_agent",
                "action_agent": "action_agent",
            },
        )
        graph.add_edge("chat_agent", "finish")
        graph.add_edge("retrieval_agent", "chat_agent")
        graph.add_edge("action_agent", "chat_agent")
        graph.add_edge("finish", END)
        return graph.compile()

    def _build_negotiation_graph(self):
        return build_negotiation_graph(
            route_node=self._route_node,
            semantic_node=self._semantic_node,
            select_after_semantic=self._select_after_semantic_for_negotiation,
            orchestrator_node=self._orchestrator_node_adapter,
            invoke_agent_node=self._invoke_agent_node_adapter,
            action_node=self._action_node_adapter,
            synthesizer_node=self._synthesizer_node_adapter,
            finish_node=self._finish_node_adapter,
        )


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
        if (
            state.route is not None
            and state.route.intent == AgentIntent.CHAT
            and _mentions_time_topic(state.user_message)
        ):
            # 时间是确定性问题：直接交给聊天 agent 调用 get_current_time 工具，
            # 不经语义模型分类，也不允许被路由成记忆检索（会反刍旧对话里的错误答案）。
            state.semantic_analysis = SemanticAnalysisResult(
                needs_context=False,
                source_scope="none",
                query=state.user_message,
                answer_style="casual",
                confidence=0.99,
                reason="deterministic_time_question",
            )
            state.classifier = _fallback_classifier(state)
            _append_status(graph_state, "时间问题由本机时钟工具回答。", stage="classifier")
            return graph_state

        # 模型裁决模糊意图；用户明确指定的读取来源仍由本机路由形成执行约束，
        # 避免分类波动把知识库查询扩大到个人记忆或聊天日记。
        state.memory_route = route_memory(state.user_message)
        route_semantic = _semantic_from_memory_route(state.memory_route, state)
        state.semantic_analysis = route_semantic
        state.classifier = _fallback_classifier(state)
        _append_status(graph_state, "正在调用语义分析 Agent。", stage="semantic_analysis")
        try:
            semantic_model = self._model_for(AgentId.SEMANTIC_ANALYSIS_AGENT)
            if semantic_model is None:
                _apply_offline_action_route(graph_state, state)
                _append_status(graph_state, "语义模型未配置，使用确定性路由。", stage="memory_router")
                return graph_state
            response = await semantic_model.complete(
                user_message=state.user_message,
                system_prompt=_semantic_system_prompt(),
            )
            classifier, semantic = _parse_classifier_analysis(response, state.user_message)
            state.classifier = classifier
            state.semantic_analysis = semantic
            _apply_classifier_route(state)
        except Exception:
            logger.warning("Semantic analysis agent failed; using fallback semantic analysis", exc_info=True)
            _apply_offline_action_route(graph_state, state)
        return graph_state

    def _select_agent_node(self, graph_state: dict[str, Any]) -> str:
        state = _agent_state(graph_state)
        if state.route.intent in {
            AgentIntent.PROPOSE_MEMORY,
            AgentIntent.MANAGE_WIKI,
            AgentIntent.CREATE_TASK,
        }:
            return "action_agent"
        if state.classifier is not None and state.classifier.intent == "action":
            return "action_agent"
        if state.route.intent == AgentIntent.SEARCH_MEMORY:
            _select_retrieval_entry_node(graph_state)
            return "retrieval_agent"
        if state.classifier is not None and state.classifier.intent == "need_retrieval":
            _select_retrieval_entry_node(graph_state)
            return "retrieval_agent"
        if state.semantic_analysis and state.semantic_analysis.needs_context:
            _select_retrieval_entry_node(graph_state)
            return "retrieval_agent"
        return "chat_agent"

    def _select_after_semantic_for_negotiation(self, graph_state: dict[str, Any]) -> str:
        state = _negotiation_state(graph_state)
        state.max_rounds = _MAX_NEGOTIATION_ROUNDS
        state.confidence_threshold = float(
            getattr(self.services.automation_settings, "confidence_threshold", state.confidence_threshold)
        )
        if _is_action_state(state):
            return "action_agent"
        return "orchestrator" if _needs_chat_context(state) else "synthesizer"

    async def _orchestrator_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _negotiation_state(graph_state)
        model = self._model_for(AgentId.CHAT_AGENT)
        if model is None:
            return _fallback_negotiation(
                graph_state,
                state,
                reason="orchestrator_model_unavailable",
            )
        try:
            result = await OrchestratorNode(
                _PromptOnlyModel(model),
                self.agent_registry,
                max_rounds=_MAX_NEGOTIATION_ROUNDS,
                confidence_threshold=float(
                    getattr(self.services.automation_settings, "confidence_threshold", state.confidence_threshold)
                ),
                timeout_seconds=_NEGOTIATION_AGENT_TIMEOUT_SECONDS,
            )(state)
        except ChatModelError as exc:
            graph_state["next"] = "synthesize"
            return _record_node_error(graph_state, exc)
        except (TimeoutError, asyncio.TimeoutError):
            return _fallback_negotiation(
                graph_state,
                state,
                reason="orchestrator_timeout",
            )
        except Exception:
            logger.warning("Negotiation orchestrator failed; synthesizing from bounded local context", exc_info=True)
            return _fallback_negotiation(
                graph_state,
                state,
                reason="orchestrator_invalid_response",
            )
        state.orchestrator_decisions = result.get("orchestrator_decisions", state.orchestrator_decisions)
        state.fallback_triggered = result.get("fallback_triggered", state.fallback_triggered)
        _append_negotiation_step_event(graph_state, state, result)
        graph_state.update(result)
        return graph_state

    async def _invoke_agent_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _negotiation_state(graph_state)
        next_agent = graph_state.get("next_agent")
        if isinstance(next_agent, str):
            try:
                next_agent = AgentId(next_agent)
            except ValueError:
                next_agent = None
        if not isinstance(next_agent, AgentId):
            return _fallback_negotiation(
                graph_state,
                state,
                reason="invalid_agent_request",
            )

        next_agent = _canonical_runtime_agent_id(next_agent)
        if next_agent != AgentId.RETRIEVAL_AGENT:
            return _fallback_negotiation(
                graph_state,
                state,
                reason="unsupported_agent_request",
            )

        agent_input = str(graph_state.get("agent_input") or state.user_message).strip()
        if _has_duplicate_invocation(state, next_agent, agent_input):
            return _fallback_negotiation(
                graph_state,
                state,
                reason="duplicate_agent_query",
            )

        invocation = await run_agent(
            next_agent,
            agent_input,
            state,
            self.agent_registry,
            timeout_seconds=_NEGOTIATION_AGENT_TIMEOUT_SECONDS,
        )
        invocation, inner_events = _separate_invocation_events(invocation)
        _append_negotiation_inner_events(graph_state, inner_events)
        state.citations = _dedupe_citations(state.citations)
        state.invocation_history.append(invocation)
        state.round += 1
        if _invocation_failed(invocation):
            return _fallback_negotiation(
                graph_state,
                state,
                reason=_invocation_error_code(invocation),
            )
        state.collected_context = _append_collected_context(state.collected_context, invocation)
        graph_state["next"] = "orchestrator"
        return graph_state


    async def _synthesizer_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        state = _agent_state(graph_state)
        if isinstance(state, NegotiationState):
            original_message = state.user_message
            try:
                if state.collected_context:
                    state.user_message = _message_with_negotiation_context(state)
                result = await self._chat_node_adapter(graph_state)
            finally:
                state.user_message = original_message
            if (
                not graph_state.get("failed")
                and (state.orchestrator_decisions or state.invocation_history or state.fallback_triggered)
            ):
                _append_negotiation_done_event(graph_state, state)
                self._record_negotiation_stats(state)
            return result
        return await self._chat_node_adapter(graph_state)

    def _should_use_negotiation(self, state: AgentState) -> bool:
        return bool(
            getattr(self.services.automation_settings, "use_negotiation", False)
            and _is_memory_or_retrieval_request(state.user_message)
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
            original_semantic = state.semantic_analysis
            citation_keys_before = {_citation_key(citation) for citation in state.citations}
            state.user_message = input_query
            canonical_agent_id = _canonical_runtime_agent_id(agent_id)
            try:
                if canonical_agent_id == AgentId.RETRIEVAL_AGENT:
                    if state.semantic_analysis is not None:
                        semantic_update: dict[str, Any] = {"query": input_query}
                        if state.round > 0:
                            semantic_update["source_scope"] = "all"
                        state.semantic_analysis = state.semantic_analysis.model_copy(update=semantic_update)
                    _select_retrieval_entry_node(graph_state)
                    await self._retrieval_node_adapter(graph_state)
                elif canonical_agent_id == AgentId.ACTION_AGENT:
                    await self._action_node_adapter(graph_state)
                else:
                    await self._chat_node_adapter(graph_state)
            finally:
                state.user_message = original_message
                state.semantic_analysis = original_semantic
            new_citations = [
                citation
                for citation in state.citations
                if _citation_key(citation) not in citation_keys_before
            ]
            return {
                "result": state.response_text,
                "citations": new_citations,
                "proposal_id": state.proposal_id,
                "task_id": state.task_id,
                "confidence": 0.9 if any(_is_answer_evidence(item) for item in new_citations) else 0.0,
                "failed": bool(graph_state.get("failed")),
                "error_code": state.error_code,
                "_events": list(_events(graph_state)),
            }

        return handler

    async def _run_model_agent_with_tools(
        self,
        *,
        agent_id: AgentId,
        state: AgentState,
        tools: tuple[AgentToolName, ...],
        system_prompt: str,
        forced_source_scope: str | None = None,
    ) -> tuple[str, list[AgentToolResult]]:
        tool_results: list[AgentToolResult] = []
        observed_toolset = AgentToolSet(
            retrieval=self.services.retrieval,
            memory=self.services.memory,
            tasks=self.services.tasks,
            wiki=self.services.wiki,
            wiki_workflow=self.services.wiki_workflow,
            wiki_reader=self.services.wiki_reader,
            observer=tool_results.append,
        )
        chat_model = self._model_for(agent_id)
        if isinstance(chat_model, ToolCallingChatModelProtocol):
            tools_for_agent = observed_toolset.allowed_tools(tools)
            tools_for_agent = _force_search_memory_source_scope(
                tools_for_agent,
                system_prompt,
                forced_source_scope=forced_source_scope,
                allowed_source_scopes=_explicit_tool_scopes(state),
                forced_top_k=(
                    _retrieval_top_k_for_state(state)
                    if agent_id == AgentId.RETRIEVAL_AGENT
                    else None
                ),
            )
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
        state = _agent_state(graph_state)
        if state.checkpoint_id and state.checkpoint_status == "pending_confirmation":
            _append_status(graph_state, "高风险操作等待确认，尚未执行任何目标写入。", stage="pending_confirmation")
            return graph_state
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
        _select_retrieval_entry_node(graph_state)
        await self._retrieval_node_adapter(graph_state)

    async def _retrieval_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _retrieval_node(
            graph_state,
            self.services,
            self._run_model_agent_with_tools,
            _has_tool_result,
            _has_empty_search_result,
        )

    async def _action_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        return await _action_planner_node(graph_state, self.services)

    async def _finish_node_adapter(self, graph_state: dict[str, Any]) -> dict[str, Any]:
        if not graph_state.get("failed"):
            await _execute_action_plan(graph_state, self.services)
        return await _finish_node(graph_state)

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
                    title="已完成证据复核",
                    summary=f"复核 {state.round} 轮，执行 {len(agents_invoked)} 个只读检索步骤。",
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


def _canonical_runtime_agent_id(agent_id: AgentId) -> AgentId:
    if agent_id in {
        AgentId.MEMORY_RETRIEVAL_AGENT,
        AgentId.KNOWLEDGE_RETRIEVAL_AGENT,
    }:
        return AgentId.RETRIEVAL_AGENT
    if agent_id in {
        AgentId.WIKI_MANAGER_AGENT,
        AgentId.MEMORY_PROPOSAL_AGENT,
        AgentId.TASK_AGENT,
    }:
        return AgentId.ACTION_AGENT
    if agent_id in {
        AgentId.DIARY_MEMORY_EXTRACTOR_AGENT,
        AgentId.CONTINUITY_AGENT,
    }:
        return AgentId.REFLECTION_AGENT
    return agent_id


def _negotiation_state(graph_state: dict[str, Any]) -> NegotiationState:
    state = _agent_state(graph_state)
    if isinstance(state, NegotiationState):
        return state
    negotiation_state = NegotiationState(**state.model_dump())
    graph_state["agent_state"] = negotiation_state
    return negotiation_state


def _fallback_negotiation(
    graph_state: dict[str, Any],
    state: NegotiationState,
    *,
    reason: str,
) -> dict[str, Any]:
    state.fallback_triggered = True
    state.status = AgentRunStatus.RUNNING
    state.error_code = None
    state.error_message = None
    graph_state.update(
        {
            "next": "synthesize",
            "fallback_triggered": True,
            "fallback_reason": reason,
        }
    )
    _append_safe_negotiation_step(
        graph_state,
        state,
        agent_id=AgentTraceAgentId.ORCHESTRATOR,
        phase=AgentTracePhase.SYNTHESIZING,
        status=AgentTraceStatus.FALLBACK,
        reason_code=_safe_trace_reason_code(reason),
    )
    return graph_state


def _separate_invocation_events(invocation: Any) -> tuple[Any, list[Any]]:
    output = invocation.output
    if not isinstance(output, dict):
        return invocation, []
    sanitized = dict(output)
    events = sanitized.pop("_events", [])
    if not isinstance(events, list):
        events = []
    return invocation.model_copy(update={"output": sanitized}), events


def _append_negotiation_inner_events(graph_state: dict[str, Any], inner_events: list[Any]) -> None:
    existing_citation_keys = {
        _citation_key(event.citation)
        for event in _events(graph_state)
        if getattr(event, "event", None) == "citation" and hasattr(event, "citation")
    }
    for event in inner_events:
        if isinstance(event, AgentErrorEvent):
            continue
        if getattr(event, "event", None) == "citation" and hasattr(event, "citation"):
            key = _citation_key(event.citation)
            if key in existing_citation_keys:
                continue
            existing_citation_keys.add(key)
        _events(graph_state).append(event)


def _invocation_error_code(invocation: Any) -> str:
    output = invocation.output
    if not isinstance(output, dict):
        return "agent_invocation_failed"
    code = str(output.get("error_code") or "agent_invocation_failed")
    return code if code in {"agent_timeout", "agent_invocation_failed"} else "agent_invocation_failed"


def _invocation_failed(invocation: Any) -> bool:
    output = invocation.output
    return bool(
        isinstance(output, dict)
        and (output.get("failed") or output.get("error_code") or output.get("error"))
    )


def _has_duplicate_invocation(state: NegotiationState, agent_id: AgentId, input_query: str) -> bool:
    normalized_query = " ".join(input_query.casefold().split())
    for invocation in state.invocation_history:
        try:
            previous_agent = _canonical_runtime_agent_id(AgentId(invocation.agent_id))
        except ValueError:
            continue
        previous_query = " ".join(invocation.input_query.casefold().split())
        if previous_agent == agent_id and previous_query == normalized_query:
            return True
    return False


def _citation_key(citation: Any) -> tuple[str, str, str]:
    return (
        str(getattr(citation, "note_id", "")),
        str(getattr(citation, "chunk_id", "")),
        str(getattr(citation, "relative_path", "")),
    )


def _dedupe_citations(citations: list[Any]) -> list[Any]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[Any] = []
    for citation in citations:
        key = _citation_key(citation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(citation)
    return deduped


def _is_answer_evidence(citation: Any) -> bool:
    snippet = str(getattr(citation, "snippet", "")).strip()
    permissions = getattr(citation, "recall_permissions", None)
    return bool(snippet and getattr(permissions, "can_answer_context", True))


def _apply_classifier_route(state: AgentState) -> None:
    classifier = state.classifier
    if classifier is None:
        return
    if classifier.intent == "action":
        intent = {
            "task": AgentIntent.CREATE_TASK,
            "wiki": AgentIntent.MANAGE_WIKI,
            "memory_proposal": AgentIntent.PROPOSE_MEMORY,
        }.get(classifier.action_type or "", AgentIntent.CHAT)
    elif classifier.intent == "need_retrieval":
        intent = AgentIntent.SEARCH_MEMORY
    else:
        intent = AgentIntent.CHAT
    state.route = AgentRoute(
        intent=intent,
        confidence=classifier.confidence,
        reason=classifier.reason or "classifier",
    )


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
            "证据复核已收集本地上下文：",
            state.collected_context,
            "请基于以上上下文，用桌宠口吻给出简短自然回复。",
        ]
    )


def _append_negotiation_step_event(
    graph_state: dict[str, Any], state: NegotiationState, result: dict[str, Any]
) -> None:
    if result.get("fallback_triggered"):
        reason = str(result.get("fallback_reason") or "negotiation_fallback")
        _append_safe_negotiation_step(
            graph_state,
            state,
            agent_id=AgentTraceAgentId.ORCHESTRATOR,
            phase=AgentTracePhase.SYNTHESIZING,
            status=AgentTraceStatus.FALLBACK,
            reason_code=_safe_trace_reason_code(reason),
        )
        return

    decision = state.orchestrator_decisions[-1] if state.orchestrator_decisions else None
    if not isinstance(decision, dict):
        return
    next_agent = result.get("next_agent") or decision.get("agent") or "synthesizer"
    invoking = result.get("next") == "invoke_agent"
    _append_safe_negotiation_step(
        graph_state,
        state,
        agent_id=_safe_trace_agent_id(next_agent),
        phase=AgentTracePhase.INVOKING if invoking else AgentTracePhase.SYNTHESIZING,
        status=AgentTraceStatus.RUNNING,
        reason_code=(
            AgentTraceReasonCode.ADDITIONAL_CONTEXT_REQUIRED
            if invoking
            else AgentTraceReasonCode.EVIDENCE_READY
        ),
        round_value=state.round + 1 if invoking else state.round,
    )



def _append_negotiation_done_event(graph_state: dict[str, Any], state: NegotiationState) -> None:
    _events(graph_state).append(
        NegotiationDoneEvent(
            run_id=state.agent_run_id,
            agent_id=AgentTraceAgentId.ORCHESTRATOR,
            phase=AgentTracePhase.COMPLETED,
            status=AgentTraceStatus.COMPLETED,
            round=state.round,
            sequence=_next_trace_sequence(graph_state),
            duration_ms=sum(invocation.latency_ms for invocation in state.invocation_history),
            reason_code=(
                AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK
                if state.fallback_triggered
                else AgentTraceReasonCode.NEGOTIATION_COMPLETED
            ),
            counts=_trace_counts(state),
            source_scope=_trace_source_scope(state),
        )
    )



def _append_safe_negotiation_step(
    graph_state: dict[str, Any],
    state: NegotiationState,
    *,
    agent_id: str,
    phase: AgentTracePhase,
    status: AgentTraceStatus,
    reason_code: AgentTraceReasonCode,
    round_value: int | None = None,
) -> None:
    _events(graph_state).append(
        NegotiationStepEvent(
            run_id=state.agent_run_id,
            agent_id=agent_id,
            phase=phase,
            status=status,
            round=state.round if round_value is None else max(0, round_value),
            sequence=_next_trace_sequence(graph_state),
            reason_code=reason_code,
            counts=_trace_counts(state),
            source_scope=_trace_source_scope(state),
        )
    )


def _next_trace_sequence(graph_state: dict[str, Any]) -> int:
    return 1 + sum(
        getattr(event, "event", None) in {"negotiation_step", "negotiation_done"}
        for event in _events(graph_state)
    )


def _trace_counts(state: NegotiationState) -> AgentTraceCounts:
    return AgentTraceCounts(
        agents_invoked=len(state.invocation_history),
        citations=len(state.citations),
        rounds=state.round,
    )


def _trace_source_scope(state: NegotiationState) -> AgentTraceSourceScope:
    allowed = {
        scope.value: scope
        for scope in AgentTraceSourceScope
        if scope not in {AgentTraceSourceScope.NONE, AgentTraceSourceScope.MIXED}
    }
    scopes: set[AgentTraceSourceScope] = set()
    for citation in state.citations:
        raw_scope = getattr(citation, "source_scope", "")
        scope_value = getattr(raw_scope, "value", raw_scope)
        if isinstance(scope_value, str) and scope_value in allowed:
            scopes.add(allowed[scope_value])
    if not scopes:
        return AgentTraceSourceScope.NONE
    if len(scopes) > 1:
        return AgentTraceSourceScope.MIXED
    return next(iter(scopes))


def _safe_trace_agent_id(value: Any) -> str:
    raw_value = getattr(value, "value", value)
    mapping = {
        AgentTraceAgentId.ORCHESTRATOR.value: AgentTraceAgentId.ORCHESTRATOR,
        AgentTraceAgentId.RETRIEVAL_AGENT.value: AgentTraceAgentId.RETRIEVAL_AGENT,
        AgentTraceAgentId.SYNTHESIZER.value: AgentTraceAgentId.SYNTHESIZER,
    }
    key = str(raw_value)
    if key not in mapping:
        # Preserve the distinction in telemetry.  Normalize arbitrary input
        # before putting it on the SSE contract so it cannot inject control
        # characters or unbounded data into logs/UI payloads.
        normalized = re.sub(r"[^A-Za-z0-9_.:-]+", "_", key).strip("_")[:80] or "empty"
        unknown = f"unknown:{normalized}"
        logger.warning("Unknown trace agent id %r; recording as %s.", raw_value, unknown)
        return unknown
    return mapping[key].value


def _safe_trace_reason_code(reason: str) -> AgentTraceReasonCode:
    mapping = {code.value: code for code in AgentTraceReasonCode}
    if reason not in mapping:
        logger.warning("Unknown trace reason code %r; recording as AGENT_INVOCATION_FAILED fallback.", reason)
    return mapping.get(reason, AgentTraceReasonCode.AGENT_INVOCATION_FAILED)


def _latest_negotiation_confidence(state: NegotiationState) -> float:
    decision = state.orchestrator_decisions[-1] if state.orchestrator_decisions else None
    if isinstance(decision, dict):
        confidence = decision.get("confidence")
        if isinstance(confidence, int | float):
            return float(confidence)
    if state.invocation_history:
        return float(state.invocation_history[-1].confidence)
    return 0.0


def _needs_chat_context(state: AgentState) -> bool:
    semantic = state.semantic_analysis
    if semantic is not None and semantic.needs_context and semantic.source_scope != "none":
        return True
    if state.route is not None and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    # 语义模型在线时由它裁决是否检索；确定性 memory_route 只在模型
    # 不可用（semantic_analysis 为 None）时作为离线兜底。
    route = state.memory_route
    return (
        semantic is None
        and route is not None
        and not route.semantic_fallback
        and bool(route.all_scopes)
        and route.all_scopes != ("none",)
    )


def _is_action_state(state: AgentState) -> bool:
    return bool(
        (state.route is not None and state.route.intent in {
            AgentIntent.PROPOSE_MEMORY,
            AgentIntent.MANAGE_WIKI,
            AgentIntent.CREATE_TASK,
        })
        or (state.classifier is not None and state.classifier.intent == "action")
    )


def _is_memory_or_retrieval_request(message: str) -> bool:
    route = route_intent(message)
    if route.intent in {
        AgentIntent.PROPOSE_MEMORY,
        AgentIntent.MANAGE_WIKI,
        AgentIntent.CREATE_TASK,
    }:
        return False
    if route.intent == AgentIntent.SEARCH_MEMORY:
        return True
    memory_route = route_memory(message)
    return bool(
        memory_route.semantic_fallback
        or any(scope != "none" for scope in memory_route.all_scopes)
    )


def _requires_graph_execution(message: str) -> bool:
    route = route_intent(message)
    return bool(
        route.intent in {
            AgentIntent.PROPOSE_MEMORY,
            AgentIntent.MANAGE_WIKI,
            AgentIntent.CREATE_TASK,
            AgentIntent.SEARCH_MEMORY,
        }
        or _is_memory_or_retrieval_request(message)
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


def _local_privacy_response(
    match_count: int,
    reason: str | None,
    *,
    retrieval_error: str | None = None,
) -> str:
    reason_text = _local_privacy_reason_label(reason)
    if retrieval_error is not None:
        return (
            f"本地隐私模式已接管这条消息（命中：{reason_text}）。"
            "我没有把原文发送到模型 API，只尝试了本机关键词检索，但检索暂时失败，无法判断是否有匹配记录。"
            "请稍后重试或打开记忆页检查本地索引状态。"
        )
    if match_count > 0:
        return (
            f"本地隐私模式已接管这条消息（命中：{reason_text}）。"
            f"我没有把原文发送到模型 API，只在本机记忆里做了关键词检索，找到 {match_count} 条可能相关的记录。"
            "为了避免复述敏感细节，我先不展开内容；你可以到记忆页查看、撤回或继续用更概括的说法和我聊。"
        )
    return (
        f"本地隐私模式已接管这条消息（命中：{reason_text}）。"
        "我没有把原文发送到模型 API，只在本机记忆里做了关键词检索，暂时没有找到可引用的本机记录。"
        "你可以改用不含敏感细节的概括说法继续聊。"
    )


def _local_privacy_reason_label(reason: str | None) -> str:
    labels = {
        "api_key": "疑似 API Key",
        "bearer_token": "疑似 Bearer token",
        "password_assignment": "疑似密码或密钥字段",
        "private_key": "疑似私钥",
        "credential": "疑似凭据",
        "identity": "身份信息",
        "contact": "联系信息",
        "health": "健康信息",
        "financial": "财务信息",
        "crisis": "危机内容",
    }
    return labels.get(reason or "", "敏感内容")

def _apply_offline_action_route(graph_state: dict[str, Any], state: AgentState) -> None:
    """语义模型缺失或失败时的离线兜底：
    动作意图（任务/记忆/wiki）优先于记忆范围路由，
    避免「提醒我回邮件」被 memory_router 判成检索而丢失任务创建。
    语义模型可用时这里不会被调用：分类器是唯一裁决者。
    """
    if (
        state.route
        and state.route.intent
        in {
            AgentIntent.PROPOSE_MEMORY,
            AgentIntent.MANAGE_WIKI,
            AgentIntent.CREATE_TASK,
        }
        and not is_high_risk_mutation_request(state.user_message)
    ):
        state.semantic_analysis = SemanticAnalysisResult(
            needs_context=False,
            source_scope="none",
            query=state.user_message,
            answer_style="concise",
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
        state.classifier = _fallback_classifier(state)
        return
    state.semantic_analysis = state.semantic_analysis or _fallback_semantic_analysis(state)
    state.classifier = _fallback_classifier(state)
