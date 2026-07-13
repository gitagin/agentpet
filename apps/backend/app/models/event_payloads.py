from dataclasses import dataclass
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentTraceAgentId(str, Enum):
    ORCHESTRATOR = "orchestrator"
    RETRIEVAL_AGENT = "retrieval_agent"
    SYNTHESIZER = "synthesizer"


class AgentTracePhase(str, Enum):
    INVOKING = "invoking"
    REVIEWING = "reviewing"
    REVISING = "revising"
    SYNTHESIZING = "synthesizing"
    COMPLETED = "completed"


class AgentTraceStatus(str, Enum):
    RUNNING = "running"
    FALLBACK = "fallback"
    COMPLETED = "completed"


class AgentTraceSourceScope(str, Enum):
    NONE = "none"
    PERSONAL_MEMORY = "personal_memory"
    DIARY_OBJECTS = "diary_objects"
    DAILY_CHAT = "daily_chat"
    KNOWLEDGE_BASE = "knowledge_base"
    PENDING_MEMORY = "pending_memory"
    MIXED = "mixed"


class AgentTraceReasonCode(str, Enum):
    ADDITIONAL_CONTEXT_REQUIRED = "additional_context_required"
    EVIDENCE_REVIEW = "evidence_review"
    EVIDENCE_REVISED = "evidence_revised"
    EVIDENCE_READY = "evidence_ready"
    MAX_ROUNDS_REACHED = "max_rounds_reached"
    DUPLICATE_AGENT_QUERY = "duplicate_agent_query"
    UNSUPPORTED_AGENT_REQUEST = "unsupported_agent_request"
    INVALID_AGENT_REQUEST = "invalid_agent_request"
    ORCHESTRATOR_MODEL_UNAVAILABLE = "orchestrator_model_unavailable"
    ORCHESTRATOR_TIMEOUT = "orchestrator_timeout"
    ORCHESTRATOR_INVALID_RESPONSE = "orchestrator_invalid_response"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_INVOCATION_FAILED = "agent_invocation_failed"
    NEGOTIATION_FALLBACK = "negotiation_fallback"
    NEGOTIATION_COMPLETED = "negotiation_completed"
    NEGOTIATION_COMPLETED_WITH_FALLBACK = "negotiation_completed_with_fallback"


_AGENT_TRACE_SAFE_SUMMARIES: dict[AgentTraceReasonCode, str] = {
    AgentTraceReasonCode.ADDITIONAL_CONTEXT_REQUIRED: "需要补充本地证据，正在进行有界检索。",
    AgentTraceReasonCode.EVIDENCE_REVIEW: "正在核验已收集的本地证据。",
    AgentTraceReasonCode.EVIDENCE_REVISED: "已按核验结果调整处理步骤。",
    AgentTraceReasonCode.EVIDENCE_READY: "已有信息足够，正在合成回复。",
    AgentTraceReasonCode.MAX_ROUNDS_REACHED: "已达到协商轮次上限，正在整理已有结果。",
    AgentTraceReasonCode.DUPLICATE_AGENT_QUERY: "已阻止重复检索，正在整理已有结果。",
    AgentTraceReasonCode.UNSUPPORTED_AGENT_REQUEST: "已阻止不受支持的协作请求，正在整理已有结果。",
    AgentTraceReasonCode.INVALID_AGENT_REQUEST: "未找到可用的协作步骤，正在整理已有结果。",
    AgentTraceReasonCode.ORCHESTRATOR_MODEL_UNAVAILABLE: "协调能力暂不可用，正在基于本地证据完成回复。",
    AgentTraceReasonCode.ORCHESTRATOR_TIMEOUT: "协调步骤超时，正在基于已有本地证据完成回复。",
    AgentTraceReasonCode.ORCHESTRATOR_INVALID_RESPONSE: "协调结果无效，正在基于已有本地证据完成回复。",
    AgentTraceReasonCode.AGENT_TIMEOUT: "检索步骤超时，正在基于已有本地证据完成回复。",
    AgentTraceReasonCode.AGENT_INVOCATION_FAILED: "检索步骤未完成，正在基于已有本地证据完成回复。",
    AgentTraceReasonCode.NEGOTIATION_FALLBACK: "协作已安全停止，正在整理已有结果。",
    AgentTraceReasonCode.NEGOTIATION_COMPLETED: "协作已完成。",
    AgentTraceReasonCode.NEGOTIATION_COMPLETED_WITH_FALLBACK: "协作已通过安全兜底完成。",
}


def agent_trace_safe_summary(reason_code: AgentTraceReasonCode) -> str:
    return _AGENT_TRACE_SAFE_SUMMARIES[reason_code]


class AgentTraceCounts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agents_invoked: int = Field(default=0, ge=0)
    citations: int = Field(default=0, ge=0)
    rounds: int = Field(default=0, ge=0)


class MemoryProposalActionFields(BaseModel):
    proposal_id: str
    status: str


class AgentMemoryProposalFields(MemoryProposalActionFields):
    target_path: str | None = None


class ContinuityProposalFields(BaseModel):
    proposal_id: str
    kind: Literal["identity", "relationship", "mood", "energy", "open_thread"]
    summary: str
    evidence: str
    confidence: float
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    status: str


class ContextBudgetFields(BaseModel):
    strategy: str
    candidate_count: int
    selected_count: int
    duplicate_drop_count: int = 0
    per_scope_drop_count: int = 0
    budget_drop_count: int = 0
    item_budget: int
    per_scope_limit: int
    char_budget: int
    used_chars: int
    source_counts: dict[str, int] = Field(default_factory=dict)
    selected_scopes: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ContextBudgetData:
    strategy: str
    candidate_count: int
    selected_count: int
    duplicate_drop_count: int
    per_scope_drop_count: int
    budget_drop_count: int
    item_budget: int
    per_scope_limit: int
    char_budget: int
    used_chars: int
    source_counts: dict[str, int]
    selected_scopes: tuple[str, ...]


class AgentActionFields(BaseModel):
    action_id: str
    action_type: str


class AgentActionDecisionFields(AgentActionFields):
    risk_tier: Literal["low", "medium", "high"]
    decision: Literal["auto", "notify", "ask"]
    status: str
    title: str
    summary: str = ""
    target_paths: list[str] = Field(default_factory=list)
    reversible: bool = False
    metadata: dict[str, object] = Field(default_factory=dict)
    source_agent_run_id: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    reverted_by: str | None = None
    reverts_action_id: str | None = None
    error: str | None = None
    source: dict[str, str] = Field(default_factory=dict)
    diff_summary: str = ""
    created_at: str | None = None
    updated_at: str | None = None
    completed_at: str | None = None


class TaskCreateFields(BaseModel):
    task_id: str
    reminder_id: str | None = None
    status: str


class AgentTaskFields(TaskCreateFields):
    title: str | None = None
    reminder_status: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    timezone_label: str | None = None


class WikiProposalCoreFields(BaseModel):
    status: str
    title: str
    markdown_preview: str = ""
    source_message_id: str | None = None


class WikiTargetProposalFields(WikiProposalCoreFields):
    target_path: str


class AgentWikiProposalFields(WikiProposalCoreFields):
    proposal_type: Literal["ingest", "query_archive", "synthesize", "lint"] = "ingest"
    run_id: str | None = None
    source_id: str | None = None
    source_hash: str | None = None
    review_id: str | None = None
    review_status: str | None = None
    summary: str = ""
    review_summary: str = ""
    target_paths: list[str] = Field(default_factory=list)
    recommended_targets: list[str] = Field(default_factory=list)
    findings: list[dict[str, object]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    lint_summary: dict[str, object] = Field(default_factory=dict)
    write_report: bool | None = None
