from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

from app.agents.contracts import (
    AgentResultEnvelope,
    EvidenceEnvelope,
    ExecutionPlan,
    IndependentAgentRoleId,
    PrivacyClass,
    ReviewDecision,
    ReviewInput,
    RetrievalProvenance,
    WorkItem,
)
from app.agents.nodes.supervisor import SupervisorNode
from app.agents.registry import default_agent_registry
from app.agents.state import MultiAgentGraphState
from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from tests.agent_runtime_fakes import make_state


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _item(work_item_id: str, role_id: IndependentAgentRoleId, input_key: str) -> WorkItem:
    policy = default_agent_registry.get_role_capability(role_id).policy
    return WorkItem(
        work_item_id=work_item_id,
        role_id=role_id.value,
        input_ref=f"input:{input_key}",
        normalized_input_hash=_hash(input_key),
        expected_output_schema=policy.output_schema,
        privacy_class=PrivacyClass.PRIVATE_EPHEMERAL,
        timeout_ms=int(policy.budget.timeout_seconds * 1_000),
    )


def _state() -> MultiAgentGraphState:
    return MultiAgentGraphState(
        run_id="review-run",
        source_message_id="review-message",
        input_ref="message:review-message",
    )


def _evidence(citation_id: str, excerpt: str) -> dict:
    envelope = EvidenceEnvelope(
        citation_id=citation_id,
        source="vault_note:Wiki/Runtime.md",
        chunk_id="chunk-1",
        permitted_excerpt=excerpt,
        lifecycle_status="active",
        confidence=0.95,
        retrieval_provenance=(RetrievalProvenance(channel="fts", rank=1, score_component=1.0),),
    )
    return {
        "stable_id": citation_id,
        "content_hash": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        "source_scope": "vault_note",
        "permission_allowed": True,
        "evidence": envelope.model_dump(mode="json"),
    }


def _result(item: WorkItem, *, excerpt: str = "bounded evidence") -> AgentResultEnvelope:
    citation_id = "citation:review:1"
    return AgentResultEnvelope(
        task_id=item.work_item_id,
        role_id=IndependentAgentRoleId(item.role_id),
        status="success",
        output_schema=item.expected_output_schema,
        output={
            "draft_claims": [
                {
                    "claim_id": "claim:review:1",
                    "text": "The bounded workflow is documented.",
                    "citation_ids": [citation_id],
                }
            ],
            "evidence_candidates": [_evidence(citation_id, excerpt)],
        },
        input_tokens=10,
        output_tokens=5,
        estimated_cost_usd=0.001,
    )


def _plan(item: WorkItem) -> dict:
    return {
        "plan": ExecutionPlan(plan_id="review-plan", planning_round=1, work_items=(item,)).model_dump(
            mode="json"
        ),
        "input_tokens": 20,
        "output_tokens": 10,
        "estimated_cost_usd": 0.001,
    }


def _pass() -> ReviewDecision:
    return ReviewDecision(
        evidence_status="supported",
        decision="pass",
        supported_claim_ids=("claim:review:1",),
        usable_citation_ids=("citation:review:1",),
        confidence=0.95,
        next_permitted_action="synthesize",
        safe_summary_code="evidence_supported",
    )


def test_reviewer_receives_only_accepted_evidence_and_only_approved_claims_reach_output() -> None:
    item = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "review-query")
    seen: list[ReviewInput] = []

    async def reviewer(payload: ReviewInput) -> ReviewDecision:
        seen.append(payload)
        assert len(payload.accepted_evidence) == 1
        assert payload.accepted_evidence[0].citation_id == "citation:review:1"
        assert payload.draft_claims[0].claim_id == "claim:review:1"
        return _pass()

    async def handler(work_item, state):
        return _result(work_item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(item),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
            reviewer=reviewer,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert outcome.state.review_decision is not None
    assert outcome.state.approved_claims[0].claim_id == "claim:review:1"
    assert outcome.state.approved_evidence[0].citation_id == "citation:review:1"
    assert outcome.state.review_attempts == 1
    assert len(seen) == 1


def test_reviewer_can_retry_one_named_read_only_role_then_pass() -> None:
    item = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "review-query")
    calls = 0

    async def reviewer(payload: ReviewInput) -> ReviewDecision:
        if payload.review_attempt == 1:
            return ReviewDecision(
                evidence_status="insufficient",
                decision="retry",
                missing_evidence_needs=("the runtime workflow source",),
                required_scopes=("vault_note",),
                confidence=0.4,
                next_permitted_action="retry_read",
                retry_role_id=IndependentAgentRoleId.RETRIEVAL,
                immutable_input_ref="input:review-repair",
                safe_summary_code="evidence_insufficient",
            )
        return _pass()

    async def handler(work_item, state):
        nonlocal calls
        calls += 1
        return _result(work_item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(item),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
            reviewer=reviewer,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert calls == 2
    assert outcome.state.budget_usage.repairs == 1
    assert outcome.state.review_attempts == 2
    assert outcome.state.review_decision is not None
    assert outcome.state.review_decision.decision == "pass"


def test_reviewer_replan_is_second_and_final_supervisor_round() -> None:
    first = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "replan-first")
    second = _item("read-2", IndependentAgentRoleId.RETRIEVAL, "replan-second")
    planner_calls = 0

    async def reviewer(payload: ReviewInput) -> ReviewDecision:
        if payload.review_attempt == 1:
            return ReviewDecision(
                evidence_status="insufficient",
                decision="replan",
                missing_evidence_needs=("the missing runtime note",),
                required_scopes=("vault_note",),
                confidence=0.3,
                next_permitted_action="replan",
                immutable_input_ref="input:replan",
                safe_summary_code="evidence_insufficient",
            )
        return _pass()

    async def planner(payload):
        nonlocal planner_calls
        planner_calls += 1
        item = first if planner_calls == 1 else second
        plan = ExecutionPlan(
            plan_id=f"replan-{planner_calls}",
            planning_round=planner_calls,
            work_items=(item,),
        )
        return {
            "plan": plan.model_dump(mode="json"),
            "input_tokens": 20,
            "output_tokens": 10,
            "estimated_cost_usd": 0.001,
        }

    async def handler(work_item, state):
        return _result(work_item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=planner,
            registry=default_agent_registry,
            role_handlers={first.role_id: handler},
            reviewer=reviewer,
        )(_state())
    )

    assert outcome.fallback_reason is None
    assert planner_calls == 2
    assert outcome.state.budget_usage.planning_rounds == 2
    assert outcome.state.budget_usage.repairs == 1
    assert outcome.state.review_attempts == 2
    assert outcome.state.review_decision is not None
    assert outcome.state.review_decision.decision == "pass"


def test_reviewer_fabricated_citation_fails_closed_without_approved_evidence() -> None:
    item = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "review-query")

    async def reviewer(payload: ReviewInput) -> ReviewDecision:
        return _pass().model_copy(update={"usable_citation_ids": ("citation:made-up",)})

    async def handler(work_item, state):
        return _result(work_item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(item),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
            reviewer=reviewer,
        )(_state())
    )

    assert outcome.fallback_reason == "reviewer_invalid_response"
    assert outcome.state.approved_claims == ()
    assert outcome.state.approved_evidence == ()


def test_reviewer_provider_failure_falls_back_to_abstention_state() -> None:
    item = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "review-query")

    async def reviewer(payload: ReviewInput):
        raise RuntimeError("provider payload must not escape")

    async def handler(work_item, state):
        return _result(work_item)

    outcome = asyncio.run(
        SupervisorNode(
            planner=lambda payload: _plan(item),
            registry=default_agent_registry,
            role_handlers={item.role_id: handler},
            reviewer=reviewer,
        )(_state())
    )

    assert outcome.fallback_reason == "reviewer_invalid_response"
    assert outcome.state.approved_evidence == ()
    assert outcome.state.review_decision is None


class _RuntimeReviewerModel:
    def __init__(self, plan: dict) -> None:
        self.plan = plan
        self.prompts: list[str | None] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.prompts.append(system_prompt)
        if system_prompt == "supervisor-plan-v1":
            return json.dumps(self.plan)
        if system_prompt == "reviewer-decision-v1":
            return _pass().model_dump_json()
        return "仅使用已批准证据完成回复"


class _ReviewerRuntime(LangGraphAgentRuntime):
    def __init__(self, model: _RuntimeReviewerModel, item: WorkItem) -> None:
        self._item = item
        super().__init__(
            AgentRuntimeServices(
                chat_model=model,
                automation_settings=SimpleNamespace(
                    use_negotiation=True,
                    use_supervisor=True,
                    use_reviewer=True,
                ),
            )
        )

    def _supervisor_role_handlers(self):
        async def handler(work_item, state):
            return _result(work_item)

        return {self._item.role_id: handler}


def test_runtime_reviewer_path_emits_safe_terminal_and_never_calls_legacy_retrieval() -> None:
    item = _item("read-1", IndependentAgentRoleId.RETRIEVAL, "runtime-review")
    model = _RuntimeReviewerModel(_plan(item))

    async def run_case():
        runtime = _ReviewerRuntime(model, item)
        return [event async for event in runtime.run(make_state("search memory for runtime"))]

    events = asyncio.run(run_case())
    names = [event.event for event in events]
    assert names[-1] == "done"
    assert sum(name in {"done", "error"} for name in names) == 1
    assert "reviewer-decision-v1" in model.prompts
    assert "retrieval_agent" not in model.prompts
