from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AGENT_CONTRACT_VERSION = "agent-contracts.v1"
ROLE_REGISTRY_VERSION = "agent-role-registry.v1"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrivacyClass(str, Enum):
    PUBLIC_SAFE = "P0"
    LOCAL_CONTROL = "P1"
    PRIVATE_EPHEMERAL = "P2"


class IndependentAgentRoleId(str, Enum):
    RETRIEVAL = "vault_retrieval"
    MEMORY = "structured_memory"
    ANALYST_PLANNER = "analyst_planner"
    REVIEWER = "reviewer"
    ACTION_PROPOSAL = "action_proposal"
    VERIFIER = "verifier"
    SYNTHESIZER = "synthesizer"


class AgentToolId(str, Enum):
    SEARCH_VAULT_FTS = "search_vault_fts"
    SEARCH_VAULT_VECTOR = "search_vault_vector"
    SEARCH_ACTIVE_MEMORY = "search_active_memory"
    SEARCH_DIARY_OBJECTS = "search_diary_objects"
    SEARCH_DAILY_CHAT = "search_daily_chat"
    SEARCH_SQLITE_GRAPH = "search_sqlite_graph"
    ACTION_SCHEMA_LOOKUP = "action_schema_lookup"
    READ_TASK_RECEIPT_STATE = "read_task_receipt_state"
    READ_LEDGER_RECEIPT_STATE = "read_ledger_receipt_state"
    READ_MEMORY_RECEIPT_STATE = "read_memory_receipt_state"
    READ_VAULT_RECEIPT_STATE = "read_vault_receipt_state"


class ExecutionBudget(_ContractModel):
    schema_version: Literal["execution-budget.v1"] = "execution-budget.v1"
    max_calls: int = Field(ge=1, le=2)
    timeout_seconds: float = Field(gt=0.0, le=30.0)
    max_input_tokens: int = Field(ge=1, le=8_000)
    max_output_tokens: int = Field(ge=1, le=2_500)
    max_tool_calls: int = Field(ge=0, le=2)
    max_cost_usd: float = Field(ge=0.0, le=0.04)


class AgentTask(_ContractModel):
    schema_version: Literal["agent-task.v1"] = "agent-task.v1"
    task_id: str = Field(min_length=1, max_length=128)
    role_id: str = Field(min_length=1, max_length=64)
    input_ref: str = Field(min_length=1, max_length=256)
    expected_output_schema: str = Field(min_length=1, max_length=128)
    requested_tools: tuple[str, ...] = ()
    privacy_class: PrivacyClass
    budget: ExecutionBudget
    requested_by: Literal["router", "supervisor", "managed_job"]

    @field_validator("requested_tools")
    @classmethod
    def _unique_requested_tools(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("requested_tools must be unique")
        return value


class RetrievalProvenance(_ContractModel):
    channel: str = Field(min_length=1, max_length=64)
    rank: int = Field(ge=1)
    score_component: float = Field(ge=0.0)


class EvidenceEnvelope(_ContractModel):
    schema_version: Literal["evidence-envelope.v1"] = "evidence-envelope.v1"
    citation_id: str = Field(pattern=r"^citation:[A-Za-z0-9:_-]+$")
    source: str = Field(min_length=1, max_length=512)
    chunk_id: str = Field(min_length=1, max_length=256)
    permitted_excerpt: str = Field(min_length=1, max_length=4_000)
    lifecycle_status: Literal["active", "indexed", "historical_approved"]
    confidence: float = Field(ge=0.0, le=1.0)
    retrieval_provenance: tuple[RetrievalProvenance, ...]


class ParallelEvidenceCandidate(_ContractModel):
    schema_version: Literal["parallel-evidence-candidate.v1"] = "parallel-evidence-candidate.v1"
    stable_id: str = Field(pattern=r"^citation:[A-Za-z0-9:_-]+$")
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_scope: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    permission_allowed: bool
    evidence: EvidenceEnvelope


class EvidenceMergeResult(_ContractModel):
    schema_version: Literal["parallel-evidence-merge.v1"] = "parallel-evidence-merge.v1"
    accepted: tuple[EvidenceEnvelope, ...] = ()
    input_count: int = Field(default=0, ge=0)
    filtered_count: int = Field(default=0, ge=0)
    conflicting_identity_count: int = Field(default=0, ge=0)


class UnsupportedClaim(_ContractModel):
    claim_id: str = Field(min_length=1, max_length=128)
    reason_code: Literal[
        "missing_evidence",
        "contradictory_evidence",
        "citation_mismatch",
        "unsafe_claim",
        "exact_value_mismatch",
    ]


class RejectedCitation(_ContractModel):
    citation_id: str = Field(min_length=1, max_length=256)
    reason_code: Literal[
        "unknown_citation",
        "unsupported_claim",
        "contradicted",
        "unsafe",
        "exact_value_mismatch",
    ]


class DraftClaim(_ContractModel):
    schema_version: Literal["draft-claim.v1"] = "draft-claim.v1"
    claim_id: str = Field(pattern=r"^claim:[A-Za-z0-9:_-]+$", max_length=128)
    text: str = Field(min_length=1, max_length=1_000)
    citation_ids: tuple[str, ...] = Field(default=(), max_length=5)

    @field_validator("citation_ids")
    @classmethod
    def _citation_ids_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("claim citation IDs must be unique")
        return value


class ReviewInput(_ContractModel):
    schema_version: Literal["review-input.v1"] = "review-input.v1"
    input_ref: str = Field(min_length=1, max_length=256)
    review_attempt: int = Field(ge=1, le=2)
    repair_already_used: bool = False
    draft_claims: tuple[DraftClaim, ...] = Field(default=(), max_length=16)
    accepted_evidence: tuple[EvidenceEnvelope, ...] = Field(default=(), max_length=5)

    @model_validator(mode="after")
    def _identities_are_unique(self) -> "ReviewInput":
        claim_ids = [claim.claim_id for claim in self.draft_claims]
        citation_ids = [evidence.citation_id for evidence in self.accepted_evidence]
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("review claim IDs must be unique")
        if len(set(citation_ids)) != len(citation_ids):
            raise ValueError("review evidence IDs must be unique")
        return self


class ReviewDecision(_ContractModel):
    schema_version: Literal["review-decision.v1"] = "review-decision.v1"
    evidence_status: Literal["supported", "insufficient", "contradictory", "unsafe"]
    decision: Literal["pass", "retry", "replan", "escalate", "reject"]
    supported_claim_ids: tuple[str, ...] = ()
    unsupported_claims: tuple[UnsupportedClaim, ...] = ()
    usable_citation_ids: tuple[str, ...] = ()
    rejected_citations: tuple[RejectedCitation, ...] = ()
    missing_evidence_needs: tuple[str, ...] = ()
    required_scopes: tuple[str, ...] = ()
    confidence: float = Field(ge=0.0, le=1.0)
    next_permitted_action: Literal[
        "synthesize",
        "propose_action",
        "retry_read",
        "replan",
        "ask_user",
        "abstain",
    ]
    retry_role_id: IndependentAgentRoleId | None = None
    immutable_input_ref: str | None = Field(default=None, max_length=256)
    safe_summary_code: Literal[
        "evidence_supported",
        "evidence_insufficient",
        "evidence_contradictory",
        "evidence_unsafe",
    ]

    @model_validator(mode="after")
    def _supported_pass_requires_confidence(self) -> "ReviewDecision":
        if self.decision == "pass" and (self.evidence_status != "supported" or self.confidence < 0.8):
            raise ValueError("review pass requires supported evidence and confidence >= 0.8")
        if self.retry_role_id is not None and self.decision not in {"retry", "replan"}:
            raise ValueError("retry_role_id is allowed only for retry or replan")
        permitted_actions = {
            "pass": {"synthesize", "propose_action"},
            "retry": {"retry_read"},
            "replan": {"replan"},
            "escalate": {"ask_user"},
            "reject": {"abstain"},
        }
        if self.next_permitted_action not in permitted_actions[self.decision]:
            raise ValueError("review decision and next action do not match")
        if self.decision == "retry" and self.retry_role_id not in {
            IndependentAgentRoleId.RETRIEVAL,
            IndependentAgentRoleId.MEMORY,
        }:
            raise ValueError("review retry requires one named read-only retrieval role")
        if self.decision in {"retry", "replan"} and not self.immutable_input_ref:
            raise ValueError("review repair requires an immutable input reference")
        supported_ids = set(self.supported_claim_ids)
        unsupported_ids = {claim.claim_id for claim in self.unsupported_claims}
        if supported_ids.intersection(unsupported_ids):
            raise ValueError("supported and unsupported claim IDs must be disjoint")
        for field_name, values in (
            ("supported_claim_ids", self.supported_claim_ids),
            ("usable_citation_ids", self.usable_citation_ids),
            ("missing_evidence_needs", self.missing_evidence_needs),
            ("required_scopes", self.required_scopes),
        ):
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must be unique")
        return self


class ActionProposal(_ContractModel):
    schema_version: Literal["action-proposal.v1"] = "action-proposal.v1"
    proposal_id: str = Field(min_length=1, max_length=128)
    explicit_intent_ref: str = Field(min_length=1, max_length=256)
    action_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.-]*$")
    target_ref: str | None = Field(default=None, max_length=256)
    normalized_target: str | None = Field(default=None, max_length=256)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_effect: str = Field(default="", max_length=512)
    reversible: bool = False
    source_message_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    requires_policy_review: Literal[True] = True
    requested_confirmation: bool = False

    @field_validator("parameters")
    @classmethod
    def _proposal_has_no_execution_authority(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_forbidden_keys(value)
        forbidden = {"approved", "execute", "executor", "policy_decision", "confirmation_granted"}
        if forbidden.intersection(key.casefold() for key in value):
            raise ValueError("action proposal cannot contain approval or execution authority")
        return value


class PolicyDecision(_ContractModel):
    schema_version: Literal["policy-decision.v1"] = "policy-decision.v1"
    proposal_id: str = Field(min_length=1, max_length=128)
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=128)
    normalized_target: str = Field(min_length=1, max_length=256)
    canonical_parameters: dict[str, Any] = Field(default_factory=dict)
    risk_tier: Literal["low", "medium", "high"]
    decision: Literal["denied", "pending_confirmation", "approved"]
    requires_confirmation: bool
    policy_version: Literal["action-policy.v1"] = "action-policy.v1"
    confirmation_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    confirmed_by_user: bool = False
    reason_code: Literal[
        "allowlisted_low_risk",
        "confirmation_required",
        "unknown_action_type",
        "unsafe_target",
        "sensitive_content",
        "invalid_proposal",
    ]
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("canonical_parameters")
    @classmethod
    def _canonical_parameters_have_no_authority(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_forbidden_keys(value)
        forbidden = {"approved", "execute", "confirmation_granted", "policy_decision"}
        if forbidden.intersection(key.casefold() for key in value):
            raise ValueError("policy parameters cannot contain authority fields")
        return value

    @model_validator(mode="after")
    def _decision_matches_confirmation(self) -> "PolicyDecision":
        if self.decision == "approved" and self.requires_confirmation:
            raise ValueError("approved policy decision cannot require confirmation")
        if self.decision == "pending_confirmation" and not self.requires_confirmation:
            raise ValueError("pending confirmation must require confirmation")
        if self.risk_tier == "high" and self.decision == "approved" and not self.confirmed_by_user:
            raise ValueError("high-risk action cannot be auto-approved")
        return self


class ExecutionClaim(_ContractModel):
    schema_version: Literal["execution-claim.v1"] = "execution-claim.v1"
    claim_id: str = Field(min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)
    source_run_id: str = Field(min_length=1, max_length=128)
    policy_version: Literal["action-policy.v1"] = "action-policy.v1"
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=128)
    normalized_target: str = Field(min_length=1, max_length=256)
    state: Literal["claimed"] = "claimed"


class ExecutionReceipt(_ContractModel):
    schema_version: Literal["execution-receipt.v1"] = "execution-receipt.v1"
    receipt_ref: str = Field(min_length=1, max_length=256)
    claim_id: str = Field(min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(pattern=r"^[a-f0-9]{64}$")
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=128)
    normalized_target: str = Field(min_length=1, max_length=256)
    status: Literal[
        "pending_confirmation",
        "denied",
        "applied",
        "verified",
        "failed_recovery",
    ]
    result: dict[str, Any] = Field(default_factory=dict)
    before_snapshot: dict[str, Any] = Field(default_factory=dict)
    after_snapshot: dict[str, Any] = Field(default_factory=dict)
    safe_error_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$", max_length=128)
    reversible: bool = False

    @field_validator("result", "before_snapshot", "after_snapshot")
    @classmethod
    def _receipt_has_no_private_runtime_fields(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_forbidden_keys(value)
        return value


class VerificationResult(_ContractModel):
    schema_version: Literal["verification-result.v1"] = "verification-result.v1"
    receipt_ref: str = Field(min_length=1, max_length=256)
    status: Literal["verified", "mismatch", "not_found", "read_failed"]
    checked_state_ref: str | None = Field(default=None, max_length=256)
    matched_checks: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    safe_error_code: str | None = Field(default=None, max_length=128)
    expected_effect: str | None = Field(default=None, max_length=512)
    observed_effect: str | None = Field(default=None, max_length=512)
    policy_version: Literal["action-policy.v1"] | None = None
    repair_permitted: Literal[False] = False


class ReflectionProposal(_ContractModel):
    schema_version: Literal["reflection-proposal.v1"] = "reflection-proposal.v1"
    proposal_id: str = Field(pattern=r"^proposal:[A-Za-z0-9:_-]+$", max_length=256)
    source_message_id: str = Field(min_length=1, max_length=128)
    proposal_kind: Literal["daily_diary", "structured_memory", "long_term_memory", "wiki_summary"]
    action_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$", max_length=128)
    target_ref: str | None = Field(default=None, max_length=256)
    content: str = Field(min_length=1, max_length=4_000)
    confidence: float = Field(ge=0.0, le=1.0)
    reversible: bool = True

    @field_validator("content")
    @classmethod
    def _content_has_no_runtime_secrets(cls, value: str) -> str:
        _reject_forbidden_keys({"content": value})
        return value


class ReflectionProposalBatch(_ContractModel):
    schema_version: Literal["reflection-proposal-batch.v1"] = "reflection-proposal-batch.v1"
    proposals: tuple[ReflectionProposal, ...] = Field(default=(), max_length=4)

    @model_validator(mode="after")
    def _proposal_ids_are_unique(self) -> "ReflectionProposalBatch":
        ids = [proposal.proposal_id for proposal in self.proposals]
        if len(ids) != len(set(ids)):
            raise ValueError("reflection proposal IDs must be unique")
        return self


class AgentResultEnvelope(_ContractModel):
    schema_version: Literal["agent-result-envelope.v1"] = "agent-result-envelope.v1"
    task_id: str = Field(min_length=1, max_length=128)
    role_id: IndependentAgentRoleId
    status: Literal["success", "failed", "fallback"]
    output_schema: str = Field(min_length=1, max_length=128)
    output: dict[str, Any] = Field(default_factory=dict)
    citation_ids: tuple[str, ...] = ()
    receipt_refs: tuple[str, ...] = ()
    safe_error_code: str | None = Field(default=None, max_length=128)
    calls_used: int = Field(default=1, ge=0, le=2)
    input_tokens: int | None = Field(default=None, ge=0, le=8_000)
    output_tokens: int | None = Field(default=None, ge=0, le=2_500)
    estimated_cost_usd: float | None = Field(default=None, ge=0.0, le=0.04)

    @field_validator("output")
    @classmethod
    def _no_raw_reasoning_or_prompt(cls, value: dict[str, Any]) -> dict[str, Any]:
        _reject_forbidden_keys(value)
        return value


class RetryPolicy(_ContractModel):
    max_retries: int = Field(ge=0, le=1)
    retryable_error_codes: tuple[Literal["provider_timeout", "provider_unavailable"], ...] = ()


class AgentRolePolicy(_ContractModel):
    registry_version: Literal["agent-role-registry.v1"] = "agent-role-registry.v1"
    role_id: IndependentAgentRoleId
    model_slot: str = Field(pattern=r"^[a-z][a-z0-9_]*_model$", max_length=64)
    prompt_id: str = Field(min_length=1, max_length=128)
    allowed_tools: tuple[AgentToolId, ...]
    input_schema: str = Field(min_length=1, max_length=128)
    output_schema: str = Field(min_length=1, max_length=128)
    privacy_class: PrivacyClass
    budget: ExecutionBudget
    retry_policy: RetryPolicy
    trace_label: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=64)
    fallback: str = Field(min_length=1, max_length=128)
    uses_tools: bool

    @model_validator(mode="after")
    def _tool_flag_matches_allowlist(self) -> "AgentRolePolicy":
        if self.uses_tools != bool(self.allowed_tools):
            raise ValueError("uses_tools must match allowed_tools")
        return self


class WorkItem(_ContractModel):
    schema_version: Literal["work-item.v1"] = "work-item.v1"
    work_item_id: str = Field(min_length=1, max_length=128)
    role_id: str = Field(min_length=1, max_length=64)
    input_ref: str = Field(min_length=1, max_length=256)
    normalized_input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_output_schema: str = Field(min_length=1, max_length=128)
    depends_on: tuple[str, ...] = ()
    branch_id: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    privacy_class: PrivacyClass
    requested_tools: tuple[str, ...] = ()
    timeout_ms: int = Field(ge=1, le=30_000)
    context_characters: int = Field(default=0, ge=0, le=48_000)
    retry_policy: Literal["none", "transient_read_once"] = "none"
    terminal_condition: Literal["required", "optional", "first_supported"] = "required"

    @model_validator(mode="after")
    def _dependencies_are_unique_and_not_self(self) -> "WorkItem":
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError("work item dependencies must be unique")
        if self.work_item_id in self.depends_on:
            raise ValueError("work item cannot depend on itself")
        if len(set(self.requested_tools)) != len(self.requested_tools):
            raise ValueError("work item tools must be unique")
        return self


class BranchExecutionRecord(_ContractModel):
    schema_version: Literal["branch-execution-record.v1"] = "branch-execution-record.v1"
    branch_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    work_item_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(default=1, ge=1, le=2)
    role_id: IndependentAgentRoleId
    status: Literal["success", "failed", "fallback", "timed_out", "cancelled"]
    started_offset_ms: float = Field(ge=0.0)
    finished_offset_ms: float = Field(ge=0.0)
    duration_ms: float = Field(ge=0.0)
    safe_error_code: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[a-z][a-z0-9_]*$",
    )

    @model_validator(mode="after")
    def _finish_follows_start(self) -> "BranchExecutionRecord":
        if self.finished_offset_ms < self.started_offset_ms:
            raise ValueError("branch finish must not precede start")
        return self


class ExecutionPlan(_ContractModel):
    schema_version: Literal["execution-plan.v1"] = "execution-plan.v1"
    plan_id: str = Field(min_length=1, max_length=128)
    planning_round: int = Field(ge=1, le=2)
    registry_version: Literal["agent-role-registry.v1"] = "agent-role-registry.v1"
    work_items: tuple[WorkItem, ...] = Field(min_length=1, max_length=8)
    completion_rule: Literal["all_required", "approved_partial_read"] = "all_required"

    @model_validator(mode="after")
    def _work_ids_are_unique(self) -> "ExecutionPlan":
        work_ids = [item.work_item_id for item in self.work_items]
        if len(set(work_ids)) != len(work_ids):
            raise ValueError("execution plan work_item_id values must be unique")
        return self


class GlobalExecutionBudget(_ContractModel):
    schema_version: Literal["global-execution-budget.v1"] = "global-execution-budget.v1"
    max_planning_rounds: Literal[2] = 2
    max_supervisor_calls: Literal[2] = 2
    max_model_calls: Literal[10] = 10
    max_specialist_dispatches: Literal[8] = 8
    max_tool_calls: Literal[12] = 12
    max_tool_calls_per_role: Literal[4] = 4
    max_repairs: Literal[1] = 1
    max_context_characters: Literal[48000] = 48_000
    max_input_tokens: Literal[32000] = 32_000
    max_output_tokens: Literal[8000] = 8_000
    max_elapsed_ms: Literal[45000] = 45_000
    max_estimated_cost_usd: Literal[0.1] = 0.1


class BudgetUsage(_ContractModel):
    schema_version: Literal["budget-usage.v1"] = "budget-usage.v1"
    planning_rounds: int = Field(default=0, ge=0)
    supervisor_calls: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    specialist_dispatches: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    repairs: int = Field(default=0, ge=0)
    context_characters: int = Field(default=0, ge=0)
    reserved_input_tokens: int = Field(default=0, ge=0)
    reserved_output_tokens: int = Field(default=0, ge=0)
    reserved_estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    observed_input_tokens: int | None = Field(default=None, ge=0)
    observed_output_tokens: int | None = Field(default=None, ge=0)
    observed_estimated_cost_usd: float | None = Field(default=None, ge=0.0)
    provider_usage_complete: bool = True
    active_elapsed_ms: int = Field(default=0, ge=0)
    tool_calls_by_role: dict[str, int] = Field(default_factory=dict)

    @field_validator("tool_calls_by_role")
    @classmethod
    def _role_tool_counts_are_non_negative(cls, value: dict[str, int]) -> dict[str, int]:
        if any(count < 0 for count in value.values()):
            raise ValueError("tool call counts must be non-negative")
        return value


_FORBIDDEN_RESULT_KEYS = frozenset(
    {
        "reasoning",
        "raw_reasoning",
        "chain_of_thought",
        "system_prompt",
        "prompt",
        "raw_prompt",
        "tool_arguments",
        "raw_tool_output",
    }
)


def _reject_forbidden_keys(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).casefold() in _FORBIDDEN_RESULT_KEYS:
                raise ValueError("role result contains forbidden reasoning or prompt field")
            _reject_forbidden_keys(nested)
    elif isinstance(value, list | tuple):
        for nested in value:
            _reject_forbidden_keys(nested)
