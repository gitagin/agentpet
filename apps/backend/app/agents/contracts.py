from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AGENT_CONTRACT_VERSION = "agent-contracts.v1"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)



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



# Single source of truth for the negotiation planning-round bound
# (consumed by graph_runtime._MAX_NEGOTIATION_ROUNDS).
MAX_PLANNING_ROUNDS = 2



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
