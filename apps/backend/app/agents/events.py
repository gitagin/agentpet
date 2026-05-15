from __future__ import annotations

import json
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.models.api import MemorySearchResult
from app.models.enums import AgentIntent


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


class AgentMemoryProposalEvent(AgentEventBase):
    event: Literal["memory_proposal"] = "memory_proposal"
    proposal_id: str
    status: str
    target_path: str | None = None


class AgentContinuityProposalEvent(AgentEventBase):
    event: Literal["continuity_proposal"] = "continuity_proposal"
    proposal_id: str
    kind: Literal["identity", "relationship", "mood", "energy", "open_thread"]
    summary: str
    evidence: str
    confidence: float
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    status: str


class AgentContinuitySignalEvent(AgentEventBase):
    event: Literal["continuity_signal"] = "continuity_signal"
    kind: str
    title: str
    summary: str
    intensity: str
    display_hint: str
    source_state_keys: list[str] = Field(default_factory=list)


class AgentWikiProposalEvent(AgentEventBase):
    event: Literal["wiki_proposal"] = "wiki_proposal"
    proposal_type: Literal["ingest", "query_archive", "synthesize", "lint"] = "ingest"
    status: str
    title: str
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
    markdown_preview: str = ""
    source_message_id: str | None = None


class AgentTaskEvent(AgentEventBase):
    event: Literal["task"] = "task"
    task_id: str
    status: str
    reminder_id: str | None = None
    title: str | None = None
    reminder_status: str | None = None
    remind_at: str | None = None
    timezone: str | None = None
    timezone_label: str | None = None


class AgentDoneEvent(AgentEventBase):
    event: Literal["done"] = "done"
    intent: AgentIntent
    text: str = ""


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
    | AgentWikiProposalEvent
    | AgentTaskEvent
    | AgentDoneEvent
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
