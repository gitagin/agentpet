from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.api import MemorySearchResult
from app.models.enums import AgentIntent
from app.models.event_payloads import (
    AgentActionDecisionFields,
    AgentMemoryProposalFields,
    AgentTaskFields,
    AgentWikiProposalFields,
    ContextBudgetFields,
    ContinuityProposalFields,
)


class AgentEventBase(BaseModel):
    event: str
    agent_run_id: str


class AgentStatusEvent(AgentEventBase):
    event: Literal["status"] = "status"
    status: str
    intent: AgentIntent | None = None
    message: str = ""
    stage: str | None = None


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


class NegotiationStepEvent(AgentEventBase):
    event: Literal["negotiation_step"] = "negotiation_step"
    round: int
    agent: str
    action: Literal["invoking", "reviewing", "revising", "synthesizing"]
    reasoning: str
    confidence: float
    message: str


class NegotiationDoneEvent(AgentEventBase):
    event: Literal["negotiation_done"] = "negotiation_done"
    total_rounds: int
    agents_invoked: list[str] = Field(default_factory=list)
    total_latency_ms: int
    final_confidence: float
    fallback: bool


class AgentErrorEvent(AgentEventBase):
    event: Literal["error"] = "error"
    code: str
    message: str


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
    | AgentDoneEvent
    | NegotiationStepEvent
    | NegotiationDoneEvent
    | AgentErrorEvent,
    Field(discriminator="event"),
]


def sse_encode(event: AgentEventBase) -> str:
    payload = event.model_dump(mode="json", exclude={"event"})
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.event}\ndata: {data}\n\n"


async def sse_stream(events: AsyncIterable[AgentEventBase]) -> AsyncIterator[str]:
    async for event in events:
        yield sse_encode(event)
