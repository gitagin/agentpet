from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.agents.contracts import MAX_PLANNING_ROUNDS
from app.agents.registry import AgentRegistry
from app.agents.state import AgentInvocationResult, NegotiationState
from app.models.enums import AgentId


class OrchestratorDecision(BaseModel):
    action: Literal["invoke_agent", "synthesize", "escalate_to_user"]
    agent: AgentId | None = None
    agent_input: str | None = None
    reasoning: str
    confidence: float = Field(ge=0.0, le=1.0)
    expected_outcome: str


class OrchestratorNode:
    def __init__(
        self,
        model: Any,
        agent_registry: AgentRegistry,
        max_rounds: int = 5,
        confidence_threshold: float = 0.8,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.model = model
        self.agent_registry = agent_registry
        self.max_rounds = min(max(int(max_rounds), 1), MAX_PLANNING_ROUNDS)
        self.confidence_threshold = confidence_threshold
        self.timeout_seconds = max(float(timeout_seconds), 0.001)

    async def __call__(self, state: NegotiationState) -> dict[str, Any]:
        max_rounds = min(state.max_rounds, self.max_rounds)
        confidence_threshold = max(state.confidence_threshold, self.confidence_threshold)
        if state.round >= max_rounds:
            return {
                "next": "synthesize",
                "fallback_triggered": True,
                "fallback_reason": "max_rounds_reached",
            }

        if _requires_initial_retrieval(state):
            decision = OrchestratorDecision(
                action="invoke_agent",
                agent=AgentId.RETRIEVAL_AGENT,
                agent_input=state.semantic_analysis.query or state.user_message,
                reasoning="当前问题需要本地证据，先执行只读检索步骤。",
                confidence=0.0,
                expected_outcome="获得可引用的本地证据，或确认本地证据为空。",
            )
            return {
                "next": "invoke_agent",
                "next_agent": decision.agent,
                "agent_input": decision.agent_input,
                "orchestrator_decisions": [
                    *state.orchestrator_decisions,
                    self._decision_to_dict(decision),
                ],
            }

        prompt = self._build_prompt(state)
        decision = await self._call_llm(prompt)
        decisions = [*state.orchestrator_decisions, self._decision_to_dict(decision)]

        if decision.confidence >= confidence_threshold or decision.action != "invoke_agent":
            return {"next": "synthesize", "orchestrator_decisions": decisions}

        if decision.agent != AgentId.RETRIEVAL_AGENT or not (decision.agent_input or "").strip():
            return {
                "next": "synthesize",
                "orchestrator_decisions": decisions,
                "fallback_triggered": True,
                "fallback_reason": "unsupported_agent_request",
            }

        if _is_duplicate_invocation(state, decision.agent, decision.agent_input):
            return {
                "next": "synthesize",
                "orchestrator_decisions": decisions,
                "fallback_triggered": True,
                "fallback_reason": "duplicate_agent_query",
            }

        return {
            "next": "invoke_agent",
            "next_agent": decision.agent,
            "agent_input": decision.agent_input,
            "orchestrator_decisions": decisions,
        }

    def _build_prompt(self, state: NegotiationState) -> str:
        invocation_history = "\n".join(self._format_invocation(result) for result in state.invocation_history)
        if not invocation_history:
            invocation_history = "暂无。"

        collected_context = state.collected_context.strip() or "暂无。"

        return "\n".join(
            [
                "你负责查询规划。根据已有信息判断是否足够回复用户。",
                "如果信息足够（confidence >= 0.8），返回 action=synthesize。",
                "如果需要更多信息，选择最合适的 agent 并精炼输入 query。",
                "禁止用相同 query 重复调用同一 agent。",
                "只返回 JSON，不要有任何前缀或 markdown 代码块。",
                "",
                "JSON 字段：action, agent, agent_input, reasoning, confidence, expected_outcome。",
                "action 只能是 invoke_agent、synthesize 或 escalate_to_user。",
                "",
                f"用户原始消息：{state.user_message}",
                "",
                "已收集上下文：",
                collected_context,
                "",
                "历史调用：",
                invocation_history,
                "",
                "可用 Agent 能力清单：",
                self.agent_registry.describe_for_orchestrator(),
            ]
        )

    async def _call_llm(self, prompt: str) -> OrchestratorDecision:
        raw_result = await self._invoke_model(prompt)
        if isinstance(raw_result, OrchestratorDecision):
            return raw_result
        if isinstance(raw_result, dict):
            return OrchestratorDecision(**raw_result)
        return OrchestratorDecision(**self._parse_json_response(self._extract_text(raw_result)))

    async def _invoke_model(self, prompt: str) -> Any:
        if hasattr(self.model, "complete"):
            result = self.model.complete(prompt)
        elif hasattr(self.model, "ainvoke"):
            result = self.model.ainvoke(prompt)
        elif hasattr(self.model, "invoke"):
            result = self.model.invoke(prompt)
        elif callable(self.model):
            result = self.model(prompt)
        else:
            raise TypeError("Orchestrator model must be callable or expose complete/ainvoke/invoke.")

        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=self.timeout_seconds)
        return result

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                stripped = "\n".join(lines[1:-1]).strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
        return json.loads(stripped)

    def _extract_text(self, raw_result: Any) -> str:
        if isinstance(raw_result, str):
            return raw_result
        if hasattr(raw_result, "text"):
            return str(raw_result.text)
        if hasattr(raw_result, "content"):
            return str(raw_result.content)
        return str(raw_result)

    def _format_invocation(self, result: AgentInvocationResult) -> str:
        return (
            f"- agent={result.agent_id}; query={result.input_query}; "
            f"confidence={result.confidence:.2f}; output={self._summarize_output(result.output)}"
        )

    def _summarize_output(self, output: Any) -> str:
        if isinstance(output, str):
            summary = output
        else:
            summary = json.dumps(output, ensure_ascii=False, default=str)
        return summary if len(summary) <= 500 else f"{summary[:500]}..."

    def _decision_to_dict(self, decision: OrchestratorDecision) -> dict[str, Any]:
        if hasattr(decision, "model_dump"):
            return decision.model_dump(mode="json")
        return decision.dict()


def _requires_initial_retrieval(state: NegotiationState) -> bool:
    semantic = state.semantic_analysis
    return bool(
        state.round == 0
        and not state.invocation_history
        and semantic is not None
        and semantic.needs_context
        and semantic.source_scope != "none"
    )


def _is_duplicate_invocation(
    state: NegotiationState,
    agent_id: AgentId,
    input_query: str,
) -> bool:
    normalized_query = " ".join(input_query.casefold().split())
    for invocation in state.invocation_history:
        try:
            previous_agent = AgentId(invocation.agent_id)
        except ValueError:
            continue
        previous_query = " ".join(invocation.input_query.casefold().split())
        if previous_agent == agent_id and previous_query == normalized_query:
            return True
    return False
