from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.models.enums import AgentId

from .contracts import (
    AgentRolePolicy,
    AgentTask,
    AgentToolId,
    ExecutionBudget,
    IndependentAgentRoleId,
    PrivacyClass,
    RetryPolicy,
)
from .prompts.system import role_prompt_id


AgentHandler = Callable[..., Any]
RoleBuilder = Callable[..., Any]


DETERMINISTIC_COMPONENT_IDS = frozenset(
    {
        "router",
        "policy_guard",
        "executor",
        "merger",
        "formatter",
        "capability_registry",
        "registry_dispatcher",
        "budget_manager",
        "terminal_arbiter",
    }
)


class AgentRegistryError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class AgentCapability:
    agent_id: AgentId
    description: str
    input_schema: str
    output_schema: str
    typical_latency_ms: int
    can_retry: bool
    max_retries: int


@dataclass(frozen=True, slots=True)
class AgentRoleCapability:
    policy: AgentRolePolicy
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    builder: RoleBuilder


class AgentRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[AgentId, AgentCapability] = {}
        self._handlers: dict[AgentId, AgentHandler] = {}
        self._role_capabilities: dict[IndependentAgentRoleId, AgentRoleCapability] = {}

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

    def register_role(self, capability: AgentRoleCapability) -> None:
        role_id = capability.policy.role_id
        if role_id.value in DETERMINISTIC_COMPONENT_IDS:
            raise AgentRegistryError("deterministic_component_not_agent")
        if role_id in self._role_capabilities:
            raise AgentRegistryError("duplicate_role")
        if capability.policy.input_schema != capability.input_model.__name__:
            raise AgentRegistryError("input_schema_mismatch")
        if capability.policy.output_schema != capability.output_model.__name__:
            raise AgentRegistryError("output_schema_mismatch")
        self._role_capabilities[role_id] = capability

    def get_role_capability(self, role_id: IndependentAgentRoleId | str) -> AgentRoleCapability:
        normalized = _normalize_role_id(role_id)
        capability = self._role_capabilities.get(normalized)
        if capability is None:
            raise AgentRegistryError("unknown_role")
        return capability

    def advertised_role_policies(self) -> tuple[AgentRolePolicy, ...]:
        return tuple(capability.policy for capability in self._role_capabilities.values())

    def validate_task(self, task: AgentTask) -> AgentRoleCapability:
        capability = self.get_role_capability(task.role_id)
        policy = capability.policy
        if task.expected_output_schema != policy.output_schema:
            raise AgentRegistryError("output_schema_mismatch")
        if _privacy_rank(task.privacy_class) > _privacy_rank(policy.privacy_class):
            raise AgentRegistryError("privacy_escalation")
        _validate_budget(task.budget, policy.budget)
        _validate_requested_tools(task.requested_tools, policy.allowed_tools)
        return capability

    def build_role(
        self,
        role_id: IndependentAgentRoleId | str,
        *,
        model: Any,
        tools: tuple[Any, ...] | list[Any] = (),
    ) -> Any:
        capability = self.get_role_capability(role_id)
        tool_names = tuple(_tool_name(tool) for tool in tools)
        _validate_requested_tools(tool_names, capability.policy.allowed_tools)
        return capability.builder(model=model, tools=tuple(tools))

    def describe_roles_for_supervisor(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "registry_version": policy.registry_version,
                "role_id": policy.role_id.value,
                "model_slot": policy.model_slot,
                "prompt_id": policy.prompt_id,
                "allowed_tools": [tool.value for tool in policy.allowed_tools],
                "input_schema": policy.input_schema,
                "output_schema": policy.output_schema,
                "privacy_class": policy.privacy_class.value,
                "timeout_seconds": policy.budget.timeout_seconds,
                "max_calls": policy.budget.max_calls,
                "max_input_tokens": policy.budget.max_input_tokens,
                "max_output_tokens": policy.budget.max_output_tokens,
                "max_tool_calls": policy.budget.max_tool_calls,
                "max_cost_usd": policy.budget.max_cost_usd,
                "max_retries": policy.retry_policy.max_retries,
                "trace_label": policy.trace_label,
                "fallback": policy.fallback,
            }
            for policy in self.advertised_role_policies()
        )


def _unbound_agent_handler(*args, **kwargs) -> None:
    raise NotImplementedError("Agent handler is not bound in the default registry.")


def create_default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for capability in DEFAULT_AGENT_CAPABILITIES:
        registry.register(capability, _unbound_agent_handler)
    for capability in DEFAULT_INDEPENDENT_ROLE_CAPABILITIES:
        registry.register_role(capability)
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


def _role_capability(
    *,
    role_id: IndependentAgentRoleId,
    allowed_tools: tuple[AgentToolId, ...],
    output_model: type[BaseModel],
    timeout_seconds: float,
    max_calls: int,
    max_input_tokens: int,
    max_output_tokens: int,
    max_tool_calls: int,
    max_cost_usd: float,
    max_retries: int,
    trace_label: str,
    fallback: str,
    builder: RoleBuilder,
) -> AgentRoleCapability:
    policy = AgentRolePolicy(
        role_id=role_id,
        model_slot=f"{role_id.value}_model",
        prompt_id=role_prompt_id(role_id),
        allowed_tools=allowed_tools,
        input_schema=AgentTask.__name__,
        output_schema=output_model.__name__,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        budget=ExecutionBudget(
            max_calls=max_calls,
            timeout_seconds=timeout_seconds,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            max_tool_calls=max_tool_calls,
            max_cost_usd=max_cost_usd,
        ),
        retry_policy=RetryPolicy(
            max_retries=max_retries,
            retryable_error_codes=("provider_timeout", "provider_unavailable") if max_retries else (),
        ),
        trace_label=trace_label,
        fallback=fallback,
        uses_tools=bool(allowed_tools),
    )
    return AgentRoleCapability(
        policy=policy,
        input_model=AgentTask,
        output_model=output_model,
        builder=builder,
    )


def _independent_role_capabilities() -> tuple[AgentRoleCapability, ...]:
    from .contracts import ActionProposal, AgentResultEnvelope, ReviewDecision, VerificationResult
    from .roles.action_proposal_agent import build_role_agent as build_action_proposal
    from .roles.analyst_planner_agent import build_role_agent as build_analyst_planner
    from .roles.memory_agent import build_role_agent as build_memory
    from .roles.retrieval_agent import build_role_agent as build_retrieval
    from .roles.reviewer_agent import build_role_agent as build_reviewer
    from .roles.synthesizer_agent import build_role_agent as build_synthesizer
    from .roles.verifier_agent import build_role_agent as build_verifier

    return (
        _role_capability(
            role_id=IndependentAgentRoleId.RETRIEVAL,
            allowed_tools=(AgentToolId.SEARCH_VAULT_FTS, AgentToolId.SEARCH_VAULT_VECTOR),
            output_model=AgentResultEnvelope,
            timeout_seconds=8,
            max_calls=2,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_tool_calls=2,
            max_cost_usd=0.005,
            max_retries=1,
            trace_label="vault_retrieval",
            fallback="sequential_fts",
            builder=build_retrieval,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.MEMORY,
            allowed_tools=(
                AgentToolId.SEARCH_ACTIVE_MEMORY,
                AgentToolId.SEARCH_DIARY_OBJECTS,
                AgentToolId.SEARCH_DAILY_CHAT,
                AgentToolId.SEARCH_SQLITE_GRAPH,
            ),
            output_model=AgentResultEnvelope,
            timeout_seconds=8,
            max_calls=2,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_tool_calls=2,
            max_cost_usd=0.005,
            max_retries=1,
            trace_label="structured_memory",
            fallback="approved_fts_and_structured_reads",
            builder=build_memory,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.ANALYST_PLANNER,
            allowed_tools=(),
            output_model=AgentResultEnvelope,
            timeout_seconds=10,
            max_calls=2,
            max_input_tokens=8_000,
            max_output_tokens=1_500,
            max_tool_calls=0,
            max_cost_usd=0.01,
            max_retries=1,
            trace_label="analyst_planner",
            fallback="deterministic_claim_support_gate",
            builder=build_analyst_planner,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.REVIEWER,
            allowed_tools=(),
            output_model=ReviewDecision,
            timeout_seconds=10,
            max_calls=2,
            max_input_tokens=8_000,
            max_output_tokens=1_500,
            max_tool_calls=0,
            max_cost_usd=0.01,
            max_retries=1,
            trace_label="reviewer",
            fallback="deterministic_claim_support_gate_or_abstain",
            builder=build_reviewer,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.ACTION_PROPOSAL,
            allowed_tools=(AgentToolId.ACTION_SCHEMA_LOOKUP,),
            output_model=ActionProposal,
            timeout_seconds=10,
            max_calls=1,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_tool_calls=1,
            max_cost_usd=0.005,
            max_retries=0,
            trace_label="action_proposal",
            fallback="deterministic_schema_only_proposal",
            builder=build_action_proposal,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.VERIFIER,
            allowed_tools=(
                AgentToolId.READ_TASK_RECEIPT_STATE,
                AgentToolId.READ_LEDGER_RECEIPT_STATE,
                AgentToolId.READ_MEMORY_RECEIPT_STATE,
                AgentToolId.READ_VAULT_RECEIPT_STATE,
            ),
            output_model=VerificationResult,
            timeout_seconds=8,
            max_calls=1,
            max_input_tokens=4_000,
            max_output_tokens=1_000,
            max_tool_calls=1,
            max_cost_usd=0.005,
            max_retries=0,
            trace_label="verifier",
            fallback="receipt_state_check_unavailable",
            builder=build_verifier,
        ),
        _role_capability(
            role_id=IndependentAgentRoleId.SYNTHESIZER,
            allowed_tools=(),
            output_model=AgentResultEnvelope,
            timeout_seconds=15,
            max_calls=1,
            max_input_tokens=8_000,
            max_output_tokens=2_500,
            max_tool_calls=0,
            max_cost_usd=0.02,
            max_retries=0,
            trace_label="synthesizer",
            fallback="approved_evidence_summary_or_abstain",
            builder=build_synthesizer,
        ),
    )


def _normalize_role_id(role_id: IndependentAgentRoleId | str) -> IndependentAgentRoleId:
    raw = role_id.value if isinstance(role_id, IndependentAgentRoleId) else str(role_id)
    if raw in DETERMINISTIC_COMPONENT_IDS:
        raise AgentRegistryError("deterministic_component_not_agent")
    try:
        return IndependentAgentRoleId(raw)
    except ValueError as exc:
        raise AgentRegistryError("unknown_role") from exc


def _tool_name(tool: Any) -> str:
    value = getattr(tool, "name", None)
    if not isinstance(value, str) or not value:
        raise AgentRegistryError("unknown_tool")
    return value


def _validate_requested_tools(
    requested_tools: tuple[str, ...],
    allowed_tools: tuple[AgentToolId, ...],
) -> None:
    known = {tool.value for tool in AgentToolId}
    allowed = {tool.value for tool in allowed_tools}
    for tool_name in requested_tools:
        if tool_name not in known:
            raise AgentRegistryError("unknown_tool")
        if tool_name not in allowed:
            raise AgentRegistryError("tool_escalation")


def _validate_budget(requested: ExecutionBudget, maximum: ExecutionBudget) -> None:
    numeric_fields = (
        "max_calls",
        "timeout_seconds",
        "max_input_tokens",
        "max_output_tokens",
        "max_tool_calls",
        "max_cost_usd",
    )
    if any(getattr(requested, field) > getattr(maximum, field) for field in numeric_fields):
        raise AgentRegistryError("budget_exceeded")


def _privacy_rank(value: PrivacyClass) -> int:
    return {
        PrivacyClass.PUBLIC_SAFE: 0,
        PrivacyClass.LOCAL_CONTROL: 1,
        PrivacyClass.PRIVATE_EPHEMERAL: 2,
    }[value]


DEFAULT_INDEPENDENT_ROLE_CAPABILITIES = _independent_role_capabilities()


default_agent_registry = create_default_agent_registry()
