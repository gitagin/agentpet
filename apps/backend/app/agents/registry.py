from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models.enums import AgentId


AgentHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AgentCapability:
    agent_id: AgentId
    description: str
    input_schema: str
    output_schema: str
    typical_latency_ms: int
    can_retry: bool
    max_retries: int


class AgentRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[AgentId, AgentCapability] = {}
        self._handlers: dict[AgentId, AgentHandler] = {}

    def register(self, capability: AgentCapability, handler: AgentHandler) -> None:
        self._capabilities[capability.agent_id] = capability
        self._handlers[capability.agent_id] = handler

    def get_handler(self, agent_id: AgentId) -> AgentHandler:
        return self._handlers[agent_id]

    def get_capability(self, agent_id: AgentId) -> AgentCapability:
        return self._capabilities[agent_id]

    def all_capabilities(self) -> tuple[AgentCapability, ...]:
        return tuple(self._capabilities.values())

    def describe_for_orchestrator(self) -> str:
        sections: list[str] = []
        for capability in self._capabilities.values():
            retry_policy = "retryable" if capability.can_retry else "no_retry"
            sections.append(
                "\n".join(
                    [
                        f"## {capability.agent_id.value}",
                        f"capability: {capability.description}",
                        f"input: {capability.input_schema}",
                        f"output: {capability.output_schema}",
                        f"typical_latency_ms: {capability.typical_latency_ms}",
                        f"retry: {retry_policy}, max={capability.max_retries}",
                    ]
                )
            )
        return "\n\n".join(sections)


def _unbound_agent_handler(*args, **kwargs) -> None:
    raise NotImplementedError("Agent handler is not bound in the default registry.")


def create_default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for capability in DEFAULT_AGENT_CAPABILITIES:
        registry.register(capability, _unbound_agent_handler)
    return registry


DEFAULT_AGENT_CAPABILITIES: tuple[AgentCapability, ...] = (
    AgentCapability(
        agent_id=AgentId.CHAT_AGENT,
        description="The only natural-language reply outlet. It turns already-planned context/action drafts into the user-facing response.",
        input_schema="user message, optional retrieved context, optional action confirmation draft, continuity summary",
        output_schema="natural-language response",
        typical_latency_ms=1200,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.SEMANTIC_ANALYSIS_AGENT,
        description="V2 Classifier: the single foreground authority for intent, retrieval scope, query, and action type.",
        input_schema="user message, recent conversation summary, confirmed continuity summary",
        output_schema="intent, retrieval_scope, retrieval_query, action_type, action_params, confidence, reason",
        typical_latency_ms=500,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.RETRIEVAL_AGENT,
        description="Unified retrieval over personal memory, diary objects, daily chat, and Markdown/Vault knowledge, selected by scope.",
        input_schema="query, source scope, top_k",
        output_schema="context snippets, source citations, retrieval telemetry",
        typical_latency_ms=900,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.ACTION_AGENT,
        description="Unified action planner for task, wiki, and memory-proposal actions. Execution is deterministic and ledgered.",
        input_schema="classifier action_type and action_params",
        output_schema="action_type, payload, risk_score, decision, confirm_text",
        typical_latency_ms=300,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.REFLECTION_AGENT,
        description="Post-reply background reflection for diary objects, long-term memory candidates, continuity updates, and wiki summaries.",
        input_schema="completed exchange and daily diary context",
        output_schema="diary_objects, long_term_memory_candidates, continuity_updates, wiki_summary_candidate",
        typical_latency_ms=900,
        can_retry=True,
        max_retries=1,
    ),
)


default_agent_registry = create_default_agent_registry()
