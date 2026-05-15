from __future__ import annotations

from collections.abc import Awaitable, Sequence
from typing import Protocol

from app.models.api import (
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResponse,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiLintProposal,
    WikiLintRequest,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeRequest,
)
from app.services.chat_model import AgentModelRegistry, ChatModelRunResult

MemorySearchReturn = MemorySearchResponse | Awaitable[MemorySearchResponse]
MemoryProposalReturn = MemoryProposalActionResponse | Awaitable[MemoryProposalActionResponse]
TaskCreateReturn = TaskCreateResponse | Awaitable[TaskCreateResponse]
WikiManageReturn = WikiPageResponse | Awaitable[WikiPageResponse]
WikiIngestPreviewReturn = WikiIngestPreviewResponse | Awaitable[WikiIngestPreviewResponse]
WikiIngestReviewReturn = WikiIngestReviewResponse | Awaitable[WikiIngestReviewResponse]
QueryArchiveLintReturn = QueryArchiveLintResponse | Awaitable[QueryArchiveLintResponse]
WikiQueryArchiveProposalReturn = WikiQueryArchiveProposal | Awaitable[WikiQueryArchiveProposal]
WikiSynthesisProposalReturn = WikiSynthesisProposal | Awaitable[WikiSynthesisProposal]
WikiLintProposalReturn = WikiLintProposal | Awaitable[WikiLintProposal]
ChatModelReturn = str | Awaitable[str]


class RetrievalServiceProtocol(Protocol):
    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchReturn: ...


class MemoryProposalServiceProtocol(Protocol):
    def create_proposal(
        self, request: MemoryProposalCreateRequest
    ) -> MemoryProposalReturn: ...


class TaskServiceProtocol(Protocol):
    def create(self, request: TaskCreateRequest) -> TaskCreateReturn: ...


class WikiServiceProtocol(Protocol):
    def manage_page(self, request: WikiPageWriteRequest) -> WikiManageReturn: ...


class WikiWorkflowServiceProtocol(Protocol):
    def preview_ingest(
        self, request: WikiIngestPreviewRequest
    ) -> WikiIngestPreviewReturn: ...

    def review_ingest(
        self, request: WikiIngestReviewRequest
    ) -> WikiIngestReviewReturn: ...

    def lint_query_archive(
        self, request: QueryArchiveRequest
    ) -> QueryArchiveLintReturn: ...

    def plan_query_archive(
        self, request: QueryArchiveRequest
    ) -> WikiQueryArchiveProposalReturn: ...

    def plan_synthesis(
        self, request: WikiSynthesizeRequest
    ) -> WikiSynthesisProposalReturn: ...

    def plan_lint(
        self, request: WikiLintRequest
    ) -> WikiLintProposalReturn: ...


class ChatModelServiceProtocol(Protocol):
    def complete(self, *, user_message: str, system_prompt: str | None = None) -> ChatModelReturn: ...
    def complete_with_tools(
        self,
        *,
        user_message: str,
        system_prompt: str | None = None,
        tools: Sequence[object] = (),
    ) -> ChatModelRunResult | Awaitable[ChatModelRunResult]: ...


class ContinuityServiceProtocol(Protocol):
    def context_block(self) -> str: ...
    def presence_context_block(self) -> str: ...
    def presence_signal(self) -> object | None: ...


class AgentServices(Protocol):
    retrieval: RetrievalServiceProtocol | None
    memory: MemoryProposalServiceProtocol | None
    tasks: TaskServiceProtocol | None
    wiki: WikiServiceProtocol | None
    wiki_workflow: WikiWorkflowServiceProtocol | None
    continuity: ContinuityServiceProtocol | None
    chat_model: ChatModelServiceProtocol | None
    model_registry: AgentModelRegistry | None
