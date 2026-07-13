from __future__ import annotations

import pytest

from app.agents.contracts import (
    AgentTask,
    ExecutionBudget,
    IndependentAgentRoleId,
    PrivacyClass,
)
from app.agents.registry import (
    DETERMINISTIC_COMPONENT_IDS,
    AgentCapability,
    AgentRegistry,
    AgentRegistryError,
    default_agent_registry,
)
from app.models.enums import AgentId


def test_default_registry_contains_all_agent_ids() -> None:
    capabilities = default_agent_registry.all_capabilities()

    assert {capability.agent_id for capability in capabilities} == {
        AgentId.CHAT_AGENT,
        AgentId.SEMANTIC_ANALYSIS_AGENT,
        AgentId.RETRIEVAL_AGENT,
        AgentId.ACTION_AGENT,
        AgentId.REFLECTION_AGENT,
    }


def test_describe_for_orchestrator_contains_all_agents() -> None:
    description = default_agent_registry.describe_for_orchestrator()

    assert description
    for agent_id in {
        AgentId.CHAT_AGENT,
        AgentId.SEMANTIC_ANALYSIS_AGENT,
        AgentId.RETRIEVAL_AGENT,
        AgentId.ACTION_AGENT,
        AgentId.REFLECTION_AGENT,
    }:
        assert f"## {agent_id.value}" in description


def test_registry_returns_registered_handler_and_capability() -> None:
    registry = AgentRegistry()

    def handler() -> str:
        return "ok"

    capability = AgentCapability(
        agent_id=AgentId.RETRIEVAL_AGENT,
        description="检索用户记忆库，支持全文和语义搜索。",
        input_schema="搜索关键词字符串。",
        output_schema="相关记忆列表。",
        typical_latency_ms=800,
        can_retry=True,
        max_retries=1,
    )

    registry.register(capability, handler)

    assert registry.get_handler(AgentId.RETRIEVAL_AGENT) is handler
    assert registry.get_capability(AgentId.RETRIEVAL_AGENT) == capability
    assert registry.get_handler(AgentId.RETRIEVAL_AGENT)() == "ok"


def test_default_registry_advertises_all_independent_roles_with_inspectable_policy() -> None:
    policies = default_agent_registry.advertised_role_policies()

    assert {policy.role_id for policy in policies} == set(IndependentAgentRoleId)
    assert len({policy.model_slot for policy in policies}) == 7
    for policy in policies:
        assert policy.model_slot.endswith("_model")
        assert policy.prompt_id.endswith(".v1")
        assert policy.input_schema == "AgentTask"
        assert policy.output_schema
        assert policy.privacy_class is PrivacyClass.PRIVATE_EPHEMERAL
        assert policy.budget.timeout_seconds > 0
        assert policy.budget.max_calls > 0
        assert policy.budget.max_input_tokens > 0
        assert policy.budget.max_output_tokens > 0
        assert policy.retry_policy.max_retries in {0, 1}
        assert policy.trace_label
        assert policy.fallback


def test_deterministic_components_are_not_registered_or_advertised_as_agents() -> None:
    advertised = {policy.role_id.value for policy in default_agent_registry.advertised_role_policies()}

    assert advertised.isdisjoint(DETERMINISTIC_COMPONENT_IDS)
    for component_id in DETERMINISTIC_COMPONENT_IDS:
        with pytest.raises(AgentRegistryError) as exc_info:
            default_agent_registry.get_role_capability(component_id)
        assert exc_info.value.code == "deterministic_component_not_agent"


def test_supervisor_description_is_public_safe_and_does_not_expose_prompts() -> None:
    snapshot = default_agent_registry.describe_roles_for_supervisor()
    text = repr(snapshot).casefold()

    assert len(snapshot) == 7
    assert "prompt_id" in text
    assert "model_slot" in text
    assert "system_prompt" not in text
    assert "raw_reasoning" not in text
    assert "chain_of_thought" not in text


def test_unknown_role_tool_escalation_and_budget_escalation_fail_closed() -> None:
    base_budget = ExecutionBudget(
        max_calls=1,
        timeout_seconds=8,
        max_input_tokens=1_000,
        max_output_tokens=500,
        max_tool_calls=1,
        max_cost_usd=0.001,
    )

    def task(**updates) -> AgentTask:
        values = {
            "task_id": "task-1",
            "role_id": IndependentAgentRoleId.RETRIEVAL.value,
            "input_ref": "input:approved:1",
            "expected_output_schema": "AgentResultEnvelope",
            "requested_tools": ("search_vault_fts",),
            "privacy_class": PrivacyClass.PRIVATE_EPHEMERAL,
            "budget": base_budget,
            "requested_by": "supervisor",
        }
        values.update(updates)
        return AgentTask(**values)

    cases = (
        (task(role_id="user_named_role"), "unknown_role"),
        (task(role_id="executor"), "deterministic_component_not_agent"),
        (task(requested_tools=("delete_vault",)), "unknown_tool"),
        (task(requested_tools=("search_active_memory",)), "tool_escalation"),
        (task(expected_output_schema="ActionProposal"), "output_schema_mismatch"),
        (
            task(
                budget=ExecutionBudget(
                    max_calls=2,
                    timeout_seconds=30,
                    max_input_tokens=8_000,
                    max_output_tokens=2_500,
                    max_tool_calls=2,
                    max_cost_usd=0.04,
                )
            ),
            "budget_exceeded",
        ),
    )
    for invalid_task, expected_code in cases:
        with pytest.raises(AgentRegistryError) as exc_info:
            default_agent_registry.validate_task(invalid_task)
        assert exc_info.value.code == expected_code
