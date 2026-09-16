from __future__ import annotations

from pydantic import BaseModel, Field

from .event_payloads import MemoryProposalActionFields


class ReflectionProposalResponse(BaseModel):
    proposal_id: str
    # 读取路径不假设库里的取值一定合契约:一个不合契约的行不应该让整张队列 500。
    # 写入路径由契约(ReflectionProposal.model_validate)在入库前把关。
    proposal_kind: str
    action_type: str
    content: str
    confidence: float
    reversible: bool
    status: str
    target_ref: str | None = None
    rejected_reason: str | None = None
    error: str | None = None
    applied_ref: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    agent_run_id: str | None = None
    created_at: str
    updated_at: str


class ReflectionProposalListResponse(BaseModel):
    proposals: list[ReflectionProposalResponse] = Field(default_factory=list)


class ReflectionProposalActionResponse(MemoryProposalActionFields):
    action_id: str | None = None
    memory_proposal_id: str | None = None
