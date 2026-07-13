from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from app.agents.contracts import (
    ActionProposal,
    AgentResultEnvelope,
    AgentTask,
    EvidenceEnvelope,
    ExecutionBudget,
    IndependentAgentRoleId,
    PrivacyClass,
    RetrievalProvenance,
    ReviewDecision,
    VerificationResult,
)
from app.agents.registry import AgentRegistryError, default_agent_registry
from app.agents.roles import action_proposal_agent
from app.agents.roles import analyst_planner_agent
from app.agents.roles import memory_agent
from app.agents.roles import retrieval_agent
from app.agents.roles import reviewer_agent
from app.agents.roles import synthesizer_agent
from app.agents.roles import verifier_agent


@dataclass(frozen=True)
class _Tool:
    name: str


class _StructuredModel:
    def __init__(self) -> None:
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)
        return _StructuredInvoker()


class _StructuredInvoker:
    async def ainvoke(self, messages):
        raise AssertionError("construction tests do not invoke the provider")


def _budget() -> ExecutionBudget:
    return ExecutionBudget(
        max_calls=1,
        timeout_seconds=8,
        max_input_tokens=1_000,
        max_output_tokens=500,
        max_tool_calls=1,
        max_cost_usd=0.001,
    )


def test_all_required_pydantic_contracts_are_versioned_frozen_and_extra_forbidden() -> None:
    task = AgentTask(
        task_id="task-1",
        role_id=IndependentAgentRoleId.RETRIEVAL.value,
        input_ref="input:approved:1",
        expected_output_schema="AgentResultEnvelope",
        requested_tools=("search_vault_fts",),
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        budget=_budget(),
        requested_by="supervisor",
    )
    evidence = EvidenceEnvelope(
        citation_id="citation:agent-pet:v1:abc123",
        source="knowledge_base:Wiki/Runtime.md",
        chunk_id="chunk-1",
        permitted_excerpt="The runtime uses bounded role contracts.",
        lifecycle_status="active",
        confidence=0.9,
        retrieval_provenance=(
            RetrievalProvenance(channel="fts", rank=1, score_component=0.01),
        ),
    )
    review = ReviewDecision(
        evidence_status="supported",
        decision="pass",
        supported_claim_ids=("claim-1",),
        usable_citation_ids=(evidence.citation_id,),
        confidence=0.8,
        next_permitted_action="synthesize",
        safe_summary_code="evidence_supported",
    )
    proposal = ActionProposal(
        proposal_id="proposal-1",
        explicit_intent_ref="intent:1",
        action_type="task.create",
        parameters={"title": "Review contracts"},
    )
    verification = VerificationResult(
        receipt_ref="receipt:1",
        status="verified",
        checked_state_ref="state:task:1",
        matched_checks=("title",),
    )
    result = AgentResultEnvelope(
        task_id=task.task_id,
        role_id=IndependentAgentRoleId.RETRIEVAL,
        status="success",
        output_schema="EvidenceBatch",
        output={"accepted_count": 1},
        citation_ids=(evidence.citation_id,),
    )

    assert task.schema_version == "agent-task.v1"
    assert task.budget.schema_version == "execution-budget.v1"
    assert evidence.schema_version == "evidence-envelope.v1"
    assert review.schema_version == "review-decision.v1"
    assert proposal.schema_version == "action-proposal.v1"
    assert verification.schema_version == "verification-result.v1"
    assert result.schema_version == "agent-result-envelope.v1"
    with pytest.raises(ValidationError, match="frozen"):
        task.role_id = "reviewer"
    with pytest.raises(ValidationError, match="Extra inputs"):
        AgentTask(**task.model_dump(), arbitrary_role_class="module.CustomAgent")


def test_review_action_and_result_contracts_reject_authority_and_reasoning_leaks() -> None:
    with pytest.raises(ValidationError, match="confidence"):
        ReviewDecision(
            evidence_status="supported",
            decision="pass",
            confidence=0.79,
            next_permitted_action="synthesize",
            safe_summary_code="evidence_supported",
        )
    with pytest.raises(ValidationError, match="approval or execution"):
        ActionProposal(
            proposal_id="proposal-1",
            explicit_intent_ref="intent:1",
            action_type="vault.write",
            parameters={"approved": True},
        )
    with pytest.raises(ValidationError, match="forbidden reasoning or prompt"):
        AgentResultEnvelope(
            task_id="task-1",
            role_id=IndependentAgentRoleId.ANALYST_PLANNER,
            status="success",
            output_schema="AnalysisPlan",
            output={"nested": {"raw_reasoning": "private chain"}},
        )


def test_role_tool_allowlists_match_the_frozen_capability_matrix() -> None:
    policies = {policy.role_id: policy for policy in default_agent_registry.advertised_role_policies()}

    assert {tool.value for tool in policies[IndependentAgentRoleId.RETRIEVAL].allowed_tools} == {
        "search_vault_fts",
        "search_vault_vector",
    }
    assert {tool.value for tool in policies[IndependentAgentRoleId.MEMORY].allowed_tools} == {
        "search_active_memory",
        "search_diary_objects",
        "search_daily_chat",
        "search_sqlite_graph",
    }
    assert policies[IndependentAgentRoleId.ANALYST_PLANNER].allowed_tools == ()
    assert policies[IndependentAgentRoleId.REVIEWER].allowed_tools == ()
    assert {tool.value for tool in policies[IndependentAgentRoleId.ACTION_PROPOSAL].allowed_tools} == {
        "action_schema_lookup"
    }
    assert {tool.value for tool in policies[IndependentAgentRoleId.VERIFIER].allowed_tools} == {
        "read_task_receipt_state",
        "read_ledger_receipt_state",
        "read_memory_receipt_state",
        "read_vault_receipt_state",
    }
    assert policies[IndependentAgentRoleId.SYNTHESIZER].allowed_tools == ()
    assert all("write" not in tool.value and "delete" not in tool.value for policy in policies.values() for tool in policy.allowed_tools)


def test_tool_using_roles_construct_separate_create_agent_instances_with_only_allowed_tools() -> None:
    calls = []

    def factory(**kwargs):
        instance = object()
        calls.append((instance, kwargs))
        return instance

    instances = (
        retrieval_agent.build_role_agent(
            model="model-retrieval",
            tools=(_Tool("search_vault_fts"),),
            agent_factory=factory,
        ),
        memory_agent.build_role_agent(
            model="model-memory",
            tools=(_Tool("search_active_memory"),),
            agent_factory=factory,
        ),
        action_proposal_agent.build_role_agent(
            model="model-action",
            tools=(_Tool("action_schema_lookup"),),
            agent_factory=factory,
        ),
        verifier_agent.build_role_agent(
            model="model-verifier",
            tools=(_Tool("read_task_receipt_state"),),
            agent_factory=factory,
        ),
    )

    assert len({id(instance) for instance in instances}) == 4
    assert len(calls) == 4
    assert [call[1]["model"] for call in calls] == [
        "model-retrieval",
        "model-memory",
        "model-action",
        "model-verifier",
    ]
    assert [call[1]["tools"][0].name for call in calls] == [
        "search_vault_fts",
        "search_active_memory",
        "action_schema_lookup",
        "read_task_receipt_state",
    ]
    assert len({call[1]["system_prompt"] for call in calls}) == 4
    assert all(call[1]["response_format"] for call in calls)


@pytest.mark.parametrize(
    "builder",
    (
        retrieval_agent.build_role_agent,
        memory_agent.build_role_agent,
        action_proposal_agent.build_role_agent,
        verifier_agent.build_role_agent,
    ),
)
def test_tool_using_role_builders_reject_direct_tool_escalation(builder) -> None:
    with pytest.raises(ValueError, match="tool_not_allowed_for_role"):
        builder(model="model", tools=(_Tool("delete_vault"),), agent_factory=lambda **kwargs: kwargs)


def test_no_tool_roles_use_separate_structured_output_models_and_reject_tools() -> None:
    builders = (
        analyst_planner_agent.build_role_agent,
        reviewer_agent.build_role_agent,
        synthesizer_agent.build_role_agent,
    )
    agents = []
    schemas = []
    for builder in builders:
        model = _StructuredModel()
        agents.append(builder(model=model))
        schemas.extend(model.schemas)

    assert len({id(agent) for agent in agents}) == 3
    assert schemas == [AgentResultEnvelope, ReviewDecision, AgentResultEnvelope]
    for builder in builders:
        with pytest.raises(ValueError, match="does not allow tools"):
            builder(model=_StructuredModel(), tools=(_Tool("search_vault_fts"),))


def test_registry_build_rejects_unknown_and_escalated_tools_before_agent_construction() -> None:
    with pytest.raises(AgentRegistryError) as unknown:
        default_agent_registry.build_role(
            IndependentAgentRoleId.RETRIEVAL,
            model="unused",
            tools=(_Tool("arbitrary_user_tool"),),
        )
    assert unknown.value.code == "unknown_tool"

    with pytest.raises(AgentRegistryError) as escalation:
        default_agent_registry.build_role(
            IndependentAgentRoleId.REVIEWER,
            model="unused",
            tools=(_Tool("search_vault_fts"),),
        )
    assert escalation.value.code == "tool_escalation"
