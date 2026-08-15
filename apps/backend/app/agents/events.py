from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.api import MemorySearchResult
from app.models.enums import AgentIntent
from app.models.event_payloads import (
    AgentActionDecisionFields,
    AgentMemoryProposalFields,
    AgentTaskFields,
    AgentTraceCounts,
    AgentTracePhase,
    AgentTraceReasonCode,
    AgentTraceSourceScope,
    AgentTraceStatus,
    AgentWikiProposalFields,
    ContextBudgetFields,
    ContinuityProposalFields,
    agent_trace_safe_summary,
)


class AgentSseEventBase(BaseModel):
    event: str


class AgentEventBase(AgentSseEventBase):
    agent_run_id: str


class AgentTraceEventBase(AgentSseEventBase):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["agent-trace.v1"] = "agent-trace.v1"
    run_id: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    branch_id: Literal["foreground"] = "foreground"
    stage_id: Literal["negotiation"] = "negotiation"
    # Keep the allowlisted ids readable while preserving unknown values for
    # telemetry instead of misattributing them to the orchestrator.
    agent_id: str = Field(
        min_length=1,
        max_length=96,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    )
    phase: AgentTracePhase
    status: AgentTraceStatus
    round: int = Field(ge=0)
    sequence: int = Field(ge=1)
    duration_ms: int = Field(default=0, ge=0)
    reason_code: AgentTraceReasonCode
    safe_summary: str = ""
    counts: AgentTraceCounts = Field(default_factory=AgentTraceCounts)
    source_scope: AgentTraceSourceScope = AgentTraceSourceScope.NONE

    @model_validator(mode="after")
    def derive_safe_summary(self) -> "AgentTraceEventBase":
        self.safe_summary = agent_trace_safe_summary(self.reason_code)
        return self


class AgentStatusEvent(AgentEventBase):
    event: Literal["status"] = "status"
    status: str
    intent: AgentIntent | None = None
    message: str = ""
    stage: str | None = None
    source_scopes: list[str] = Field(default_factory=list)


class AgentTokenEvent(AgentEventBase):
    event: Literal["token"] = "token"
    text: str


class AgentCitationEvent(AgentEventBase):
    event: Literal["citation"] = "citation"
    citation: MemorySearchResult


class AgentMemoryProposalEvent(AgentMemoryProposalFields, AgentEventBase):
    event: Literal["memory_proposal"] = "memory_proposal"


class AgentContinuityProposalEvent(ContinuityProposalFields, AgentEventBase):
    event: Literal["continuity_proposal"] = "continuity_proposal"


class AgentContinuitySignalEvent(AgentEventBase):
    event: Literal["continuity_signal"] = "continuity_signal"
    kind: str
    title: str
    summary: str
    intensity: str
    display_hint: str
    source_state_keys: list[str] = Field(default_factory=list)


class AgentContextBudgetEvent(ContextBudgetFields, AgentEventBase):
    event: Literal["context_budget"] = "context_budget"


class AgentActionEvent(AgentActionDecisionFields, AgentEventBase):
    event: Literal["agent_action"] = "agent_action"
    risk_tier: Literal["low", "medium", "high"] = "low"
    decision: Literal["auto", "notify", "ask"] = "auto"
    requires_confirmation: bool = False


class AgentWikiProposalEvent(AgentWikiProposalFields, AgentEventBase):
    event: Literal["wiki_proposal"] = "wiki_proposal"


class AgentTaskEvent(AgentTaskFields, AgentEventBase):
    event: Literal["task"] = "task"


class AgentDoneEvent(AgentEventBase):
    event: Literal["done"] = "done"
    intent: AgentIntent
    text: str = ""


class AgentReplyReadyEvent(AgentEventBase):
    event: Literal["reply_ready"] = "reply_ready"
    intent: AgentIntent
    text: str = ""


class NegotiationStepEvent(AgentTraceEventBase):
    event: Literal["negotiation_step"] = "negotiation_step"


class NegotiationDoneEvent(AgentTraceEventBase):
    event: Literal["negotiation_done"] = "negotiation_done"


class AgentErrorEvent(AgentEventBase):
    event: Literal["error"] = "error"
    code: str
    message: str


_PUBLIC_AGENT_ERROR_MESSAGES: dict[str, str] = {
    "action_lifecycle_unavailable": "本地动作生命周期暂不可用，未执行任何写入。",
    "agent_model_not_configured": "尚未配置可用的聊天模型。",
    "authentication_failed": "模型鉴权失败，请检查模型配置。",
    "unsupported_model": "当前模型配置不可用，请检查模型名称。",
    "rate_limited": "模型服务暂时繁忙，请稍后重试。",
    "quota_exhausted": "模型服务配额已用尽，请更新额度或计费设置后重试。",
    "provider_bad_request": "模型请求未被服务接受，请检查模型配置。",
    "provider_timeout": "模型服务响应超时，请稍后重试。",
    "provider_unreachable": "暂时无法连接模型服务，请稍后重试。",
    "dependency_missing": "当前模型运行依赖不可用。",
    "invalid_response": "模型服务返回了无效响应。",
    "model_invocation_failed": "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。",
    "empty_response": "模型服务返回了空回复。",
    "agent_timeout": "协作步骤超时，正在使用稳定路径。",
    "agent_invocation_failed": "协作步骤未完成，正在使用稳定路径。",
    "agent_error": "协作步骤未完成，正在使用稳定路径。",
    "agent_tool_timeout": "本地工具执行超时，请稍后重试。",
    "agent_tool_unavailable": "所需本地工具暂不可用。",
    "sensitive_memory_rejected": "疑似密钥或凭据的敏感内容不能保存为长期记忆。",
    "runtime_error": "回复处理失败，请稍后重试。",
    "late_error": "回复处理失败，请稍后重试。",
    "agent_run_not_found": "回复流已过期、已启动或已被取消。",
    "stream_ended_without_terminal_event": "回复流未正常完成。",
    "stream_cancelled": "回复流已取消。",
    "internal_error": "回复处理失败，请稍后重试。",
}


def public_agent_error(code: object) -> tuple[str, str]:
    normalized = str(code or "").strip().casefold()
    if normalized not in _PUBLIC_AGENT_ERROR_MESSAGES:
        normalized = "internal_error"
    return normalized, _PUBLIC_AGENT_ERROR_MESSAGES[normalized]


AgentEvent = Annotated[
    AgentStatusEvent
    | AgentTokenEvent
    | AgentCitationEvent
    | AgentMemoryProposalEvent
    | AgentContinuityProposalEvent
    | AgentContinuitySignalEvent
    | AgentContextBudgetEvent
    | AgentActionEvent
    | AgentWikiProposalEvent
    | AgentTaskEvent
    | AgentReplyReadyEvent
    | AgentDoneEvent
    | NegotiationStepEvent
    | NegotiationDoneEvent
    | AgentErrorEvent,
    Field(discriminator="event"),
]


_AGENT_TRACE_PUBLIC_FIELDS = frozenset(
    {
        "contract_version",
        "run_id",
        "branch_id",
        "stage_id",
        "agent_id",
        "phase",
        "status",
        "round",
        "sequence",
        "duration_ms",
        "reason_code",
        "safe_summary",
        "counts",
        "source_scope",
    }
)


def sse_encode(event: AgentSseEventBase) -> str:
    if isinstance(event, AgentTraceEventBase):
        payload = event.model_dump(mode="json", include=_AGENT_TRACE_PUBLIC_FIELDS)
    else:
        payload = event.model_dump(mode="json", exclude={"event"})
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"


async def sse_stream(events: AsyncIterable[AgentSseEventBase]) -> AsyncIterator[str]:
    async for event in events:
        yield sse_encode(event)
