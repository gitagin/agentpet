from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field

from app.models.api import (
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResponse,
    MemorySearchResult,
    QueryArchiveRequest,
    QueryArchiveResponse,
    WikiIngestPagePlan,
    WikiIngestPreviewRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewFinding,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiLintReportResponse,
    WikiLintProposal,
    WikiLintRequest,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeResponse,
    WikiSynthesizeRequest,
    WikiPageResponse,
    WikiPageWriteRequest,
)
from app.models.enums import MemoryProposalType
from app.models.event_payloads import WikiProposalCoreFields
from app.services.memory_policy import evaluate_memory_content
from app.utils.coerce import coerce_model

from .services import (
    MemoryProposalServiceProtocol,
    RetrievalServiceProtocol,
    TaskServiceProtocol,
    WikiServiceProtocol,
    WikiWorkflowServiceProtocol,
)


DEFAULT_MEMORY_TARGET_PATH = "Inbox/Pending Memories.md"


class AgentToolName(StrEnum):
    SEARCH_MEMORY = "search_memory"
    PROPOSE_MEMORY = "propose_memory"
    PLAN_WIKI_INGEST = "plan_wiki_ingest"
    PLAN_WIKI_QUERY_ARCHIVE = "plan_wiki_query_archive"
    PLAN_WIKI_SYNTHESIS = "plan_wiki_synthesis"
    PLAN_WIKI_LINT = "plan_wiki_lint"
    MANAGE_WIKI = "manage_wiki_page"
    CREATE_TASK = "create_task"


class AgentToolUnavailableError(Exception):
    code = "agent_tool_unavailable"

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"{tool_name} 工具暂不可用。")


class SensitiveMemoryRejectedError(Exception):
    code = "sensitive_memory_rejected"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "sensitive_content"
        super().__init__("疑似密钥或凭据的敏感内容不能保存为长期记忆。")


class ModelInvocationFailedError(Exception):
    code = "model_invocation_failed"

    def __init__(self) -> None:
        super().__init__("模型调用失败，请检查模型服务地址、模型名称和 API 密钥。")


@dataclass(frozen=True, slots=True)
class AgentToolResult:
    name: str
    value: (
        MemorySearchResponse
        | MemoryProposalActionResponse
        | TaskCreateResponse
        | WikiPageResponse
        | QueryArchiveResponse
        | WikiSynthesizeResponse
        | WikiLintReportResponse
        | "WikiIngestProposal"
        | WikiQueryArchiveProposal
        | WikiSynthesisProposal
        | WikiLintProposal
    )


class AgentToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchMemoryInput(AgentToolInput):
    query: str = Field(min_length=1, description="需要从知识库中检索的关键词或问题")
    top_k: int = Field(default=5, ge=1, le=20, description="最多返回的片段数量")
    mode: str = Field(default="fts", description="检索模式，v0.1 使用 fts")
    source_scope: str = Field(
        default="all",
        description="检索范围：none、personal_memory、daily_chat、knowledge_base 或 all",
    )


class ProposeMemoryInput(AgentToolInput):
    content: str = Field(min_length=1, description="需要用户确认后写入的长期记忆内容")
    target_path: str = Field(
        default=DEFAULT_MEMORY_TARGET_PATH,
        description="待确认记忆的目标 Markdown 相对路径",
    )
    source_message_id: str | None = Field(default=None, description="来源消息 ID")


class CreateTaskInput(AgentToolInput):
    title: str = Field(min_length=1, description="任务标题")
    description: str = Field(default="", description="任务描述")
    due_at: str | None = Field(default=None, description="截止时间 ISO 字符串")
    remind_at: str | None = Field(default=None, description="提醒时间 ISO 字符串")
    timezone: str | None = Field(default=None, description="任务时区")
    source_text: str | None = Field(default=None, description="用户原始输入")


class ManageWikiPageInput(AgentToolInput):
    title: str = Field(min_length=1, description="Wiki page title")
    content: str = Field(min_length=1, description="Markdown content to write into the wiki page")
    operation: str = Field(default="append", description="create, append, or replace_section")
    target_path: str | None = Field(default=None, description="Optional Wiki/*.md relative target path")
    section: str | None = Field(default=None, description="Optional section heading")
    tags: list[str] = Field(default_factory=list, description="Optional wiki tags")
    links: list[str] = Field(default_factory=list, description="Optional related wiki links")
    source_message_id: str | None = Field(default=None, description="Source message ID")


class PlanWikiIngestInput(AgentToolInput):
    title: str = Field(min_length=1, description="Title for the Vault/Wiki ingest plan")
    content: str = Field(min_length=1, description="Source Markdown or note text to plan into the Vault")
    source_type: str = Field(default="agent_chat", description="Source type, for example agent_chat or manual")
    source_uri: str | None = Field(default=None, description="Optional source URI or local reference")
    tags: list[str] = Field(default_factory=list, description="Optional wiki tags")
    links: list[str] = Field(default_factory=list, description="Optional related wiki links")
    max_pages: int = Field(default=5, ge=1, le=15, description="Maximum planned wiki pages")
    source_message_id: str | None = Field(default=None, description="Source message ID")


class PlanWikiQueryArchiveInput(AgentToolInput):
    question: str = Field(min_length=1, description="Question that produced the answer to archive")
    answer: str = Field(min_length=1, description="Answer markdown/text to archive after user confirmation")
    citations: list[MemorySearchResult] = Field(default_factory=list, description="Knowledge-base citations")
    title: str | None = Field(default=None, description="Optional query archive title")
    target_path: str | None = Field(default=None, description="Optional Wiki/Reports/*.md target path")
    section: str | None = Field(default=None, description="Optional section heading")
    tags: list[str] = Field(default_factory=list, description="Optional wiki tags")
    agent_run_id: str | None = Field(default=None, description="Agent run ID")
    source_message_id: str | None = Field(default=None, description="Source message ID")
    allow_mixed_sources: bool = Field(default=False, description="Allow non-knowledge citations")


class PlanWikiSynthesisInput(AgentToolInput):
    title: str = Field(min_length=1, description="Synthesis page title")
    content: str = Field(min_length=1, description="Synthesis markdown/text to write after confirmation")
    source_paths: list[str] = Field(default_factory=list, description="Source Wiki page paths")
    target_path: str | None = Field(default=None, description="Optional Wiki/Syntheses/*.md target path")
    tags: list[str] = Field(default_factory=list, description="Optional wiki tags")
    links: list[str] = Field(default_factory=list, description="Optional related wiki links")
    source_message_id: str | None = Field(default=None, description="Source message ID")


class PlanWikiLintInput(AgentToolInput):
    write_report: bool = Field(default=True, description="Whether confirmation should write a lint report")
    source_message_id: str | None = Field(default=None, description="Source message ID")


class WikiIngestProposal(WikiProposalCoreFields):
    proposal_type: str = "ingest"
    run_id: str
    source_id: str
    source_hash: str
    summary: str = ""
    page_plans: list[WikiIngestPagePlan] = Field(default_factory=list)
    review_id: str | None = None
    review_status: str | None = None
    review_summary: str = ""
    review_findings: list[WikiIngestReviewFinding] = Field(default_factory=list)
    recommended_targets: list[str] = Field(default_factory=list)
    model_error: str | None = None

    @classmethod
    def from_preview_review(
        cls,
        *,
        title: str,
        preview: WikiIngestPreviewResponse,
        review: WikiIngestReviewResponse | None,
        source_message_id: str | None,
    ) -> "WikiIngestProposal":
        return cls(
            title=title,
            status=preview.status,
            run_id=preview.run_id,
            source_id=preview.source_id,
            source_hash=preview.source_hash,
            summary=preview.summary,
            page_plans=preview.page_plans,
            review_id=review.review_id if review else None,
            review_status=review.status if review else None,
            review_summary=review.summary if review else "",
            review_findings=review.findings if review else [],
            recommended_targets=review.recommended_targets if review else [],
            model_error=review.model_error if review else None,
            source_message_id=source_message_id,
        )


@dataclass(slots=True)
class AgentToolSet:
    retrieval: RetrievalServiceProtocol | None = None
    memory: MemoryProposalServiceProtocol | None = None
    tasks: TaskServiceProtocol | None = None
    wiki: WikiServiceProtocol | None = None
    wiki_workflow: WikiWorkflowServiceProtocol | None = None
    observer: Callable[[AgentToolResult], None] | None = None

    def search_memory_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.search_memory,
            name="search_memory",
            description="从已索引的 Obsidian Markdown 知识库中检索记忆片段。",
            args_schema=SearchMemoryInput,
        )

    def propose_memory_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.propose_memory,
            name="propose_memory",
            description="创建一条必须由用户确认后才能写入 Markdown 的长期记忆提案。",
            args_schema=ProposeMemoryInput,
        )

    def create_task_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.create_task,
            name="create_task",
            description="创建本地任务或提醒记录。",
            args_schema=CreateTaskInput,
        )

    def manage_wiki_page_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.manage_wiki_page,
            name="manage_wiki_page",
            description=(
                "Create or update a low-risk Markdown page under Wiki/. "
                "Use this for private desktop-pet auto-organization. Do not use it for deletes, moves, or sensitive content."
            ),
            args_schema=ManageWikiPageInput,
        )

    def plan_wiki_ingest_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.plan_wiki_ingest,
            name="plan_wiki_ingest",
            description=(
                "Plan a Vault/Wiki ingest from source text and review it. "
                "This does not write Markdown; the user must confirm apply separately."
            ),
            args_schema=PlanWikiIngestInput,
        )

    def plan_wiki_query_archive_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.plan_wiki_query_archive,
            name="plan_wiki_query_archive",
            description=(
                "Plan a query-answer archive under Wiki/Reports. "
                "This only lints and previews Markdown; it does not write files."
            ),
            args_schema=PlanWikiQueryArchiveInput,
        )

    def plan_wiki_synthesis_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.plan_wiki_synthesis,
            name="plan_wiki_synthesis",
            description=(
                "Plan a synthesized Wiki page from provided content and source paths. "
                "This does not write Markdown; the user must confirm separately."
            ),
            args_schema=PlanWikiSynthesisInput,
        )

    def plan_wiki_lint_tool(self) -> StructuredTool:
        return StructuredTool.from_function(
            coroutine=self.plan_wiki_lint,
            name="plan_wiki_lint",
            description=(
                "Plan a Wiki lint run or lint report write. "
                "This does not write a report until the user confirms."
            ),
            args_schema=PlanWikiLintInput,
        )

    def all_tools(self) -> list[StructuredTool]:
        return [
            self.search_memory_tool(),
            self.propose_memory_tool(),
            self.plan_wiki_ingest_tool(),
            self.plan_wiki_query_archive_tool(),
            self.plan_wiki_synthesis_tool(),
            self.plan_wiki_lint_tool(),
            self.manage_wiki_page_tool(),
            self.create_task_tool(),
        ]

    def allowed_tools(self, names: tuple[AgentToolName, ...]) -> list[StructuredTool]:
        tools_by_name = {
            AgentToolName.SEARCH_MEMORY: self.search_memory_tool,
            AgentToolName.PROPOSE_MEMORY: self.propose_memory_tool,
            AgentToolName.PLAN_WIKI_INGEST: self.plan_wiki_ingest_tool,
            AgentToolName.PLAN_WIKI_QUERY_ARCHIVE: self.plan_wiki_query_archive_tool,
            AgentToolName.PLAN_WIKI_SYNTHESIS: self.plan_wiki_synthesis_tool,
            AgentToolName.PLAN_WIKI_LINT: self.plan_wiki_lint_tool,
            AgentToolName.MANAGE_WIKI: self.manage_wiki_page_tool,
            AgentToolName.CREATE_TASK: self.create_task_tool,
        }
        return [tools_by_name[name]() for name in names]

    async def search_memory(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        if self.retrieval is None:
            raise AgentToolUnavailableError("search_memory")
        try:
            value = await self.retrieval.search(query, top_k=top_k, mode=mode, source_scope=source_scope)
        except TypeError:
            value = await self.retrieval.search(query, top_k=top_k, mode=mode)
        response = _coerce_search_response(value)
        self._notify("search_memory", response)
        return response

    async def propose_memory(
        self,
        content: str,
        target_path: str = DEFAULT_MEMORY_TARGET_PATH,
        source_message_id: str | None = None,
    ) -> MemoryProposalActionResponse:
        if self.memory is None:
            raise AgentToolUnavailableError("propose_memory")

        policy = evaluate_memory_content(content)
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        request = MemoryProposalCreateRequest(
            type=MemoryProposalType.FACT,
            content=content,
            target_path=target_path,
            source_message_id=source_message_id,
        )
        value = await self.memory.create_proposal(request)
        response = _coerce_memory_response(value)
        self._notify("propose_memory", response)
        return response

    async def create_task(
        self,
        title: str,
        description: str = "",
        due_at: str | None = None,
        remind_at: str | None = None,
        timezone: str | None = None,
        source_text: str | None = None,
    ) -> TaskCreateResponse:
        if self.tasks is None:
            raise AgentToolUnavailableError("create_task")

        request = TaskCreateRequest(
            title=title,
            description=description,
            due_at=due_at,
            remind_at=remind_at,
            timezone=timezone,
            source_text=source_text,
        )
        value = await self.tasks.create(request)
        response = _coerce_task_response(value)
        self._notify("create_task", response)
        return response

    async def manage_wiki_page(
        self,
        title: str,
        content: str,
        operation: str = "append",
        target_path: str | None = None,
        section: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        source_message_id: str | None = None,
    ) -> WikiPageResponse:
        if self.wiki is None:
            raise AgentToolUnavailableError("manage_wiki_page")

        policy = evaluate_memory_content(f"{title}\n{content}")
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        request = WikiPageWriteRequest(
            title=title,
            content=content,
            operation=operation,  # type: ignore[arg-type]
            target_path=target_path,
            section=section,
            tags=tags or [],
            links=links or [],
            source_message_id=source_message_id,
        )
        value = await self.wiki.manage_page(request)
        response = _coerce_wiki_response(value)
        self._notify("manage_wiki_page", response)
        return response

    async def plan_wiki_ingest(
        self,
        title: str,
        content: str,
        source_type: str = "agent_chat",
        source_uri: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        max_pages: int = 5,
        source_message_id: str | None = None,
    ) -> WikiIngestProposal:
        if self.wiki_workflow is None:
            raise AgentToolUnavailableError("plan_wiki_ingest")

        policy = evaluate_memory_content(f"{title}\n{content}")
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        preview = _coerce_wiki_ingest_preview(
            await self.wiki_workflow.preview_ingest(
                WikiIngestPreviewRequest(
                    title=title,
                    content=content,
                    source_type=source_type,
                    source_uri=source_uri,
                    tags=tags or [],
                    links=links or [],
                    max_pages=max_pages,
                )
            )
        )
        review = _coerce_wiki_ingest_review(
            await self.wiki_workflow.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id))
        )
        proposal = WikiIngestProposal.from_preview_review(
            title=title,
            preview=preview,
            review=review,
            source_message_id=source_message_id,
        )
        self._notify("plan_wiki_ingest", proposal)
        return proposal

    async def plan_wiki_query_archive(
        self,
        question: str,
        answer: str,
        citations: list[MemorySearchResult] | None = None,
        title: str | None = None,
        target_path: str | None = None,
        section: str | None = None,
        tags: list[str] | None = None,
        agent_run_id: str | None = None,
        source_message_id: str | None = None,
        allow_mixed_sources: bool = False,
    ) -> WikiQueryArchiveProposal:
        if self.wiki_workflow is None:
            raise AgentToolUnavailableError("plan_wiki_query_archive")

        policy = evaluate_memory_content(f"{question}\n{answer}")
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        request = QueryArchiveRequest(
            question=question,
            answer=answer,
            citations=citations or [],
            title=title,
            target_path=target_path,
            section=section,
            tags=tags or [],
            agent_run_id=agent_run_id,
            source_message_id=source_message_id,
            allow_mixed_sources=allow_mixed_sources,
        )
        response = _coerce_wiki_query_archive_proposal(await self.wiki_workflow.plan_query_archive(request))
        self._notify("plan_wiki_query_archive", response)
        return response

    async def plan_wiki_synthesis(
        self,
        title: str,
        content: str,
        source_paths: list[str] | None = None,
        target_path: str | None = None,
        tags: list[str] | None = None,
        links: list[str] | None = None,
        source_message_id: str | None = None,
    ) -> WikiSynthesisProposal:
        if self.wiki_workflow is None:
            raise AgentToolUnavailableError("plan_wiki_synthesis")

        policy = evaluate_memory_content(f"{title}\n{content}")
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        request = WikiSynthesizeRequest(
            title=title,
            content=content,
            source_paths=source_paths or [],
            target_path=target_path,
            tags=tags or [],
            links=links or [],
        )
        response = _coerce_wiki_synthesis_proposal(await self.wiki_workflow.plan_synthesis(request))
        response = response.model_copy(update={"source_message_id": source_message_id})
        self._notify("plan_wiki_synthesis", response)
        return response

    async def plan_wiki_lint(
        self,
        write_report: bool = True,
        source_message_id: str | None = None,
    ) -> WikiLintProposal:
        if self.wiki_workflow is None:
            raise AgentToolUnavailableError("plan_wiki_lint")

        response = _coerce_wiki_lint_proposal(
            await self.wiki_workflow.plan_lint(WikiLintRequest(write_report=write_report))
        )
        response = response.model_copy(update={"source_message_id": source_message_id})
        self._notify("plan_wiki_lint", response)
        return response

    def _notify(
        self,
        name: str,
        value: (
            MemorySearchResponse
            | MemoryProposalActionResponse
            | TaskCreateResponse
            | WikiPageResponse
            | QueryArchiveResponse
            | WikiSynthesizeResponse
            | WikiLintReportResponse
            | WikiIngestProposal
            | WikiQueryArchiveProposal
            | WikiSynthesisProposal
            | WikiLintProposal
        ),
    ) -> None:
        if self.observer is not None:
            self.observer(AgentToolResult(name=name, value=value))


def _coerce_search_response(value) -> MemorySearchResponse:
    if isinstance(value, MemorySearchResponse):
        return value
    if isinstance(value, dict):
        return MemorySearchResponse.model_validate(value)
    return MemorySearchResponse(results=list(value))


def _coerce_memory_response(value) -> MemoryProposalActionResponse:
    return coerce_model(value, MemoryProposalActionResponse)


def _coerce_task_response(value) -> TaskCreateResponse:
    return coerce_model(value, TaskCreateResponse)


def _coerce_wiki_response(value) -> WikiPageResponse:
    return coerce_model(value, WikiPageResponse)


def _coerce_wiki_ingest_preview(value) -> WikiIngestPreviewResponse:
    return coerce_model(value, WikiIngestPreviewResponse)


def _coerce_wiki_ingest_review(value) -> WikiIngestReviewResponse:
    return coerce_model(value, WikiIngestReviewResponse)


def _coerce_wiki_query_archive_proposal(value) -> WikiQueryArchiveProposal:
    return coerce_model(value, WikiQueryArchiveProposal)


def _coerce_wiki_synthesis_proposal(value) -> WikiSynthesisProposal:
    return coerce_model(value, WikiSynthesisProposal)


def _coerce_wiki_lint_proposal(value) -> WikiLintProposal:
    return coerce_model(value, WikiLintProposal)
