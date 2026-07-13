from __future__ import annotations

from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.models.api import (
    AgentActionResponse,
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResponse,
    QueryArchiveLintResponse,
    QueryArchiveResponse,
    QueryArchiveRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiLintProposal,
    WikiLintReportResponse,
    WikiLintRequest,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeResponse,
    WikiSynthesizeRequest,
)
from app.services.chat_model import AgentModelRegistry, ChatModelRunResult
from app.agents.checkpointer import SQLiteCheckpointStore

class RetrievalServiceProtocol(Protocol):
    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse: ...


class MemoryProposalServiceProtocol(Protocol):
    async def create_proposal(
        self, request: MemoryProposalCreateRequest
    ) -> MemoryProposalActionResponse: ...


class TaskServiceProtocol(Protocol):
    async def create(self, request: TaskCreateRequest) -> TaskCreateResponse: ...


class WikiServiceProtocol(Protocol):
    async def manage_page(self, request: WikiPageWriteRequest) -> WikiPageResponse: ...


class WikiWorkflowServiceProtocol(Protocol):
    async def preview_ingest(
        self, request: WikiIngestPreviewRequest
    ) -> WikiIngestPreviewResponse: ...

    async def review_ingest(
        self, request: WikiIngestReviewRequest
    ) -> WikiIngestReviewResponse: ...

    async def lint_query_archive(
        self, request: QueryArchiveRequest
    ) -> QueryArchiveLintResponse: ...

    async def archive_query(
        self, request: QueryArchiveRequest
    ) -> QueryArchiveResponse: ...

    async def plan_query_archive(
        self, request: QueryArchiveRequest
    ) -> WikiQueryArchiveProposal: ...

    async def synthesize(
        self, request: WikiSynthesizeRequest
    ) -> WikiSynthesizeResponse: ...

    async def plan_synthesis(
        self, request: WikiSynthesizeRequest
    ) -> WikiSynthesisProposal: ...

    async def run_lint(
        self, request: WikiLintRequest
    ) -> WikiLintReportResponse: ...

    async def plan_lint(
        self, request: WikiLintRequest
    ) -> WikiLintProposal: ...

    async def apply_ingest(
        self, request: WikiIngestApplyRequest
    ) -> WikiIngestApplyResponse: ...


@runtime_checkable
class ChatModelServiceProtocol(Protocol):
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str: ...


@runtime_checkable
class ToolCallingChatModelProtocol(Protocol):
    def complete_with_tools(
        self,
        *,
        user_message: str,
        system_prompt: str | None = None,
        tools: Sequence[object] = (),
    ) -> ChatModelRunResult | Awaitable[ChatModelRunResult]: ...


@runtime_checkable
class ContinuitySignalProtocol(Protocol):
    kind: str
    title: str
    summary: str
    intensity: str
    display_hint: str
    source_state_keys: tuple[str, ...]


@runtime_checkable
class ContinuityServiceProtocol(Protocol):
    def context_block(self) -> str: ...
    def presence_context_block(self) -> str: ...
    def presence_signal(self) -> ContinuitySignalProtocol | None: ...


class AgentActionRecorderProtocol(Protocol):
    def __call__(self, action: Any) -> AgentActionResponse: ...


class MemoryActivationRecorderProtocol(Protocol):
    def record_usage(
        self,
        *,
        result: Any,
        conversation_id: str,
        message_id: str,
        agent_run_id: str,
        used_for_style: bool,
        used_for_answer_context: bool,
        used_for_proactive_mention: bool,
        used_for_action_suggestion: bool,
        filtered_reason: str | None = None,
    ) -> None: ...


class PromptProfileProviderProtocol(Protocol):
    def select(
        self,
        *,
        user_message: str = "",
        semantic_analysis: Any | None = None,
    ) -> Any: ...


@dataclass(slots=True)
class AgentRuntimeServices:
    retrieval: RetrievalServiceProtocol | None = None
    memory: MemoryProposalServiceProtocol | None = None
    tasks: TaskServiceProtocol | None = None
    wiki: WikiServiceProtocol | None = None
    wiki_workflow: WikiWorkflowServiceProtocol | None = None
    continuity: ContinuityServiceProtocol | None = None
    companion_retrieval_reports: Any | None = None
    chat_model: ChatModelServiceProtocol | None = None
    model_registry: AgentModelRegistry | None = None
    automation_settings: Any | None = None
    agent_action_recorder: AgentActionRecorderProtocol | None = None
    memory_activation_recorder: MemoryActivationRecorderProtocol | None = None
    prompt_profile_provider: PromptProfileProviderProtocol | None = None
    checkpoint_store: SQLiteCheckpointStore | None = None


class AgentServices(Protocol):
    retrieval: RetrievalServiceProtocol | None
    memory: MemoryProposalServiceProtocol | None
    tasks: TaskServiceProtocol | None
    wiki: WikiServiceProtocol | None
    wiki_workflow: WikiWorkflowServiceProtocol | None
    continuity: ContinuityServiceProtocol | None
    chat_model: ChatModelServiceProtocol | None
    model_registry: AgentModelRegistry | None
