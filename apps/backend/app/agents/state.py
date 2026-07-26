from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.api import MemorySearchResult
from app.models.enums import AgentIntent, AgentRunStatus
from app.services.prompt_context_types import PromptRecentTurn

from .immediate_understanding import ImmediateUnderstanding
from .memory_router import MemoryRoute
from .contracts import (
    ActionProposal,
    ExecutionReceipt,
    PolicyDecision,
    VerificationResult,
)


class AgentRoute(BaseModel):
    intent: AgentIntent
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class SemanticAnalysisResult(BaseModel):
    needs_context: bool = False
    source_scope: Literal["none", "personal_memory", "diary_objects", "daily_chat", "knowledge_base", "all"] = "none"
    query: str = ""
    answer_style: Literal["casual", "concise", "grounded", "clarifying"] = "casual"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class ClassifierResult(BaseModel):
    intent: Literal["chat", "need_retrieval", "action"] = "chat"
    retrieval_scope: Literal["personal_memory", "knowledge_base", "both"] | None = None
    retrieval_query: str | None = None
    action_type: Literal["task", "wiki", "memory_proposal"] | None = None
    action_params: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""


class ActionPlan(BaseModel):
    action_type: Literal["task", "wiki", "memory_proposal", "confirmation"]
    payload: dict[str, Any] = Field(default_factory=dict)
    risk_score: Literal["low", "medium", "high"] = "low"
    decision: Literal["auto", "notify", "ask"] = "auto"
    status: Literal["planned", "executed", "pending_confirm", "skipped", "failed"] = "planned"
    confirm_text: str = ""
    reversible: bool = False
    executed: bool = False
    proposal_id: str | None = None
    policy_version: str | None = None
    idempotency_key: str | None = None
    control_state: Literal[
        "proposed",
        "policy_checked",
        "denied",
        "pending_confirmation",
        "approved",
        "claimed",
        "executing",
        "applied",
        "verifying",
        "verified",
        "completed",
        "failed_recovery",
    ] = "proposed"
    receipt_ref: str | None = None
    verification_status: Literal["verified", "mismatch", "not_found", "read_failed"] | None = None


class AgentState(BaseModel):
    conversation_id: str
    message_id: str
    agent_run_id: str
    user_message: str
    status: AgentRunStatus = AgentRunStatus.RUNNING
    route: AgentRoute | None = None
    memory_route: MemoryRoute | None = None
    semantic_analysis: SemanticAnalysisResult | None = None
    classifier: ClassifierResult | None = None
    action_plan: ActionPlan | None = None
    action_plans: list[ActionPlan] = Field(default_factory=list)
    action_proposals: list[ActionProposal] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    execution_receipts: list[ExecutionReceipt] = Field(default_factory=list)
    verification_results: list[VerificationResult] = Field(default_factory=list)
    executed_action_keys: set[str] = Field(default_factory=set)
    immediate_understanding: ImmediateUnderstanding | None = None
    citations: list[MemorySearchResult] = Field(default_factory=list)
    recent_turns: list[PromptRecentTurn] = Field(default_factory=list)
    response_text: str = ""
    proposal_id: str | None = None
    task_id: str | None = None
    reminder_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    local_privacy_mode: bool = False
    local_privacy_sensitive_reason: str | None = None
    suppress_post_reply_automation: bool = False
    checkpoint_id: str | None = None
    checkpoint_status: Literal[
        "pending_confirmation",
        "approved",
        "rejected",
        "expired",
        "cancelled",
        "completed",
        "failed_recovery",
    ] | None = None

    @property
    def intent(self) -> AgentIntent | None:
        return self.route.intent if self.route else None


class AgentInvocationResult(BaseModel):
    agent_id: str
    round: int
    input_query: str
    output: Any
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: int
    tool_calls: list[str]


class NegotiationState(AgentState):
    round: int = 0
    max_rounds: int = 5
    confidence_threshold: float = 0.8
    invocation_history: list[AgentInvocationResult] = Field(default_factory=list)
    orchestrator_decisions: list[Any] = Field(default_factory=list)
    collected_context: str = ""
    pending_proposals: list[dict[str, Any]] = Field(default_factory=list)
    fallback_triggered: bool = False


