from __future__ import annotations

import enum
import json

if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum

from app.agents import AgentState
from app.models.api import (
    MemoryProposalActionResponse,
    MemorySearchResponse,
    MemorySearchResult,
    QueryArchiveLintResponse,
    QueryArchiveResponse,
    TaskCreateResponse,
    WikiIngestPagePlan,
    WikiIngestPreviewResponse,
    WikiIngestReviewFinding,
    WikiIngestReviewResponse,
    WikiLintIssue,
    WikiLintProposal,
    WikiLintReportResponse,
    WikiPageResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeResponse,
)
from app.services.chat_model import ChatModelRunResult


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str | None = None,
    ) -> MemorySearchResponse:
        if source_scope is None:
            self.calls.append((query, top_k, mode))
        else:
            self.calls.append((query, top_k, mode, source_scope))
        scope = source_scope or "personal_memory"
        relative_path = "Wiki/Ada.md" if scope == "knowledge_base" else "People/Ada.md"
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    note_id="note-1",
                    chunk_id="chunk-1",
                    relative_path=relative_path,
                    title="Ada",
                    heading="Preferences",
                    snippet="Ada prefers concise status updates.",
                    score=0.9,
                    source_scope=scope,
                )
            ]
        )


class FakeEmptyRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(self, query: str, top_k: int = 5, mode: str = "fts") -> MemorySearchResponse:
        self.calls.append((query, top_k, mode))
        return MemorySearchResponse(results=[])


class FakeScopedRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        if source_scope == "knowledge_base":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="knowledge-1",
                        chunk_id="knowledge-chunk-1",
                        relative_path="Wiki/Runtime.md",
                        title="Runtime",
                        heading="Agent Flow",
                        snippet="Knowledge retrieval searches durable Wiki documents.",
                        score=0.91,
                        source_scope="knowledge_base",
                    )
                ]
            )
        return MemorySearchResponse(
            results=[
                MemorySearchResult(
                    note_id="memory-1",
                    chunk_id="memory-chunk-1",
                    relative_path="Memories/Preferences.md",
                    title="Preferences",
                    heading="水果",
                    snippet="用户喜欢苹果。",
                    score=0.95,
                    source_scope="personal_memory",
                )
            ]
        )


class FakePersonalEmptyDailyRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        if source_scope == "daily_chat":
            snippets = (
                "用户说自己喜欢苹果。",
                "用户问了北京天气。",
                "用户询问昨天的重要记录。",
                "用户要求回顾 5 月 4 日的聊天。",
                "用户希望被称为测试员。",
                "用户给助手取名为零。",
                "用户说自己喜欢旅游，并询问了旅行推荐。",
            )
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id=f"daily-{index}",
                        chunk_id=f"daily-chunk-{index}",
                        relative_path="Memories/Daily/2026/05/第1周_05-01至05-07/星期一/2026-05-04.md",
                        title="2026-05-04 聊天记忆",
                        heading=f"{9 + index:02d}:00:00",
                        snippet=snippet,
                        score=0.8,
                        source_scope="daily_chat",
                    )
                    for index, snippet in enumerate(snippets[:top_k], start=1)
                ]
            )
        return MemorySearchResponse(results=[])


class FakeMultiScopeRetrieval:
    def __init__(self) -> None:
        self.calls = []

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        if source_scope == "personal_memory":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="personal-1",
                        chunk_id="personal-chunk-1",
                        relative_path="MemoryGraph/LongTerm",
                        title="Structured Long-Term Memory",
                        heading="coding style",
                        snippet="Ada prefers concise status updates.",
                        score=0.97,
                        source_scope="personal_memory",
                        retrieval_mode="graph",
                    ),
                    MemorySearchResult(
                        note_id="personal-2",
                        chunk_id="personal-chunk-2",
                        relative_path="Memories/LongTerm/Profile.md",
                        title="Profile",
                        heading="coding style",
                        snippet="Ada values direct engineering summaries.",
                        score=0.91,
                        source_scope="personal_memory",
                    ),
                    MemorySearchResult(
                        note_id="personal-3",
                        chunk_id="personal-chunk-3",
                        relative_path="Memories/LongTerm/Profile.md",
                        title="Profile",
                        heading="extra",
                        snippet="This lower priority personal memory should be compressed away.",
                        score=0.4,
                        source_scope="personal_memory",
                    ),
                ]
            )
        if source_scope == "diary_objects":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="diary-1",
                        chunk_id="diary-1",
                        relative_path="DiaryMemory/diary-1",
                        title="Structured Diary Memory",
                        heading="work",
                        snippet="Ada felt focused after a refactor review.",
                        score=1.4,
                        source_scope="diary_objects",
                        retrieval_mode="diary_object",
                    )
                ]
            )
        if source_scope == "daily_chat":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="daily-1",
                        chunk_id="daily-chunk-1",
                        relative_path="Memories/Daily/2026/05/week/2026-05-04.md",
                        title="2026-05-04 chat",
                        heading="10:00",
                        snippet="Ada prefers concise status updates.",
                        score=0.8,
                        source_scope="daily_chat",
                    )
                ]
            )
        return MemorySearchResponse(results=[])


class FakeMemory:
    def __init__(self) -> None:
        self.requests = []

    async def create_proposal(self, request):
        self.requests.append(request)
        return MemoryProposalActionResponse(proposal_id="proposal-1", status="pending")


class FakeCompanionReportStore:
    def __init__(self) -> None:
        self.records = []

    def record(self, *, agent_run_id: str, query: str, telemetry) -> None:
        self.records.append((agent_run_id, query, telemetry))


class FakeContinuity:
    def __init__(self, context: str) -> None:
        self.context = context

    def context_block(self) -> str:
        return self.context

    def presence_context_block(self) -> str:
        return (
            f"{self.context}\nCompanion presence behavior:\n"
            "- Carry confirmed continuity with high presence."
            if self.context
            else ""
        )

    def presence_signal(self):
        return None


class FakePresenceSignal:
    kind = "open_thread"
    title = "有个话题还没收好"
    summary = "我还记着这个未完话题：continue this tomorrow"
    intensity = "high"
    display_hint = "可以自然接上，不创建提醒或写入 Vault。"
    source_state_keys = ("unresolved_threads",)


class FakeContinuityWithSignal(FakeContinuity):
    def presence_signal(self):
        return FakePresenceSignal()


class FakeTasks:
    def __init__(self) -> None:
        self.requests = []

    async def create(self, request):
        self.requests.append(request)
        return TaskCreateResponse(
            task_id="task-1",
            reminder_id="reminder-1",
            status="pending",
            metadata={
                "title": request.title,
                "reminder_status": "scheduled",
                "remind_at": "2026-05-02T07:00:00Z",
                "timezone": "Asia/Shanghai",
                "timezone_label": "北京时间",
            },
        )


class FakeWiki:
    def __init__(self) -> None:
        self.requests = []

    async def manage_page(self, request):
        self.requests.append(request)
        return WikiPageResponse(
            title=request.title,
            relative_path="Wiki/Runtime.md",
            operation=request.operation,
            status="updated",
            index_job_id="scheduled:vault-1",
            action_id="action-wiki-1",
        )


class FakeWikiWorkflow:
    def __init__(self) -> None:
        self.preview_requests = []
        self.review_requests = []
        self.query_archive_requests = []
        self.synthesis_requests = []
        self.lint_requests = []

    async def preview_ingest(self, request):
        self.preview_requests.append(request)
        return WikiIngestPreviewResponse(
            run_id="wiki-run-1",
            source_id="source-1",
            source_hash="hash-1",
            status="planned",
            summary="Planned source and concept pages.",
            page_plans=[
                WikiIngestPagePlan(
                    title=request.title,
                    target_path="Wiki/Sources/Runtime.md",
                    operation="replace_section",
                    section="Source Summary",
                    content=request.content,
                    tags=request.tags,
                    links=request.links,
                )
            ],
        )

    async def review_ingest(self, request):
        self.review_requests.append(request)
        return WikiIngestReviewResponse(
            review_id="review-1",
            run_id=request.run_id,
            status="reviewed",
            summary="Review accepted the planned page.",
            findings=[
                WikiIngestReviewFinding(
                    severity="info",
                    code="source_claims_extracted",
                    message="One source page is ready for confirmation.",
                    target_path="Wiki/Sources/Runtime.md",
                )
            ],
            recommended_targets=["Wiki/Sources/Runtime.md"],
            reviewer_agent_id="action_agent",
        )

    async def lint_query_archive(self, request):
        raise AssertionError("lint_query_archive should not be called in these tests")

    async def plan_query_archive(self, request):
        self.query_archive_requests.append(request)
        lint = QueryArchiveLintResponse(
            passed=bool(request.citations),
            errors=[] if request.citations else ["archive_requires_at_least_one_citation"],
            warnings=[],
            normalized_citations=request.citations,
            markdown_preview=f"## 查询归档\n\n{request.answer}",
        )
        return WikiQueryArchiveProposal(
            status="planned" if lint.passed else "rejected",
            title=request.title or "查询归档 - Runtime",
            target_path=request.target_path or "Wiki/Reports/Runtime-Answer.md",
            section=request.section or "查询归档 - run-1",
            tags=["query-archive", *request.tags],
            lint=lint,
            markdown_preview=lint.markdown_preview,
            agent_run_id=request.agent_run_id,
            source_message_id=request.source_message_id,
        )

    async def archive_query(self, request):
        self.query_archive_requests.append(request)
        lint = QueryArchiveLintResponse(
            passed=True,
            errors=[],
            warnings=[],
            normalized_citations=request.citations,
            markdown_preview=f"## Query archive\n\n{request.answer}",
        )
        return QueryArchiveResponse(
            archive_id="archive-1",
            page=WikiPageResponse(
                title=request.title or "Query archive - Runtime",
                relative_path=request.target_path or "Wiki/Reports/Runtime-Answer.md",
                operation="replace_section",
                status="updated",
                index_job_id="scheduled:vault-1",
            ),
            lint=lint,
            action_id="action-query-1",
        )

    async def plan_synthesis(self, request):
        self.synthesis_requests.append(request)
        return WikiSynthesisProposal(
            title=request.title,
            target_path=request.target_path or "Wiki/Syntheses/Runtime-Synthesis.md",
            tags=["synthesis", *request.tags],
            links=[*request.links, *request.source_paths],
            source_paths=request.source_paths,
            markdown_preview=f"## 综合整理\n\n{request.content}",
        )

    async def synthesize(self, request):
        self.synthesis_requests.append(request)
        return WikiSynthesizeResponse(
            page=WikiPageResponse(
                title=request.title,
                relative_path=request.target_path or "Wiki/Syntheses/Runtime-Synthesis.md",
                operation="replace_section",
                status="updated",
                index_job_id="scheduled:vault-1",
            ),
            index_updated=True,
            log_appended=True,
            action_id="action-synthesis-1",
        )

    async def plan_lint(self, request):
        self.lint_requests.append(request)
        return WikiLintProposal(
            write_report=request.write_report,
            target_path="Wiki/Reports/Lint-2026-05-11.md" if request.write_report else None,
            summary={"issues": 1, "warnings": 1, "errors": 0},
            issues=[
                WikiLintIssue(
                    severity="warning",
                    code="missing_wiki_link",
                    message="Missing link target.",
                    path="Wiki/Runtime.md",
                    target="Missing",
                )
            ],
            markdown_preview="## Wiki Lint 提案",
        )

    async def run_lint(self, request):
        self.lint_requests.append(request)
        return WikiLintReportResponse(
            generated_at="2026-05-11T00:00:00Z",
            summary={"issues": 1, "warnings": 1, "errors": 0},
            issues=[
                WikiLintIssue(
                    severity="warning",
                    code="missing_wiki_link",
                    message="Missing link target.",
                    path="Wiki/Runtime.md",
                    target="Missing",
                )
            ],
            report_page=WikiPageResponse(
                title="Wiki Lint Report",
                relative_path="Wiki/Reports/Lint-2026-05-11.md",
                operation="replace_section",
                status="updated",
                index_job_id="scheduled:vault-1",
            ),
            action_id="action-lint-1",
        )


class FakeChatModel:
    def __init__(self, response: str = "模型回复：你好") -> None:
        self.response = response
        self.calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        return self.response


class FailingChatModel:
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        raise RuntimeError("model down")


class FakeToolCallingChatModel:
    def __init__(self, tool_name: str, response: str) -> None:
        self.tool_name = tool_name
        self.response = response
        self.calls = []

    async def complete_with_tools(self, *, user_message: str, system_prompt: str | None, tools):
        self.calls.append((user_message, system_prompt, [tool.name for tool in tools]))
        by_name = {tool.name: tool for tool in tools}
        if self.tool_name == "search_memory":
            await by_name["search_memory"].ainvoke({"query": "Ada", "top_k": 5})
        elif self.tool_name == "propose_memory":
            await by_name["propose_memory"].ainvoke(
                {
                    "content": "Ada likes tests",
                    "target_path": "Inbox/Pending Memories.md",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "create_task":
            await by_name["create_task"].ainvoke(
                {
                    "title": "review tests",
                    "source_text": user_message,
                }
            )
        elif self.tool_name == "manage_wiki_page":
            await by_name["manage_wiki_page"].ainvoke(
                {
                    "title": "Runtime",
                    "content": "Wiki content",
                    "operation": "append",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_ingest":
            await by_name["plan_wiki_ingest"].ainvoke(
                {
                    "title": "Runtime",
                    "content": "Wiki content",
                    "source_type": "agent_chat",
                    "tags": ["agent-chat"],
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_query_archive":
            await by_name["plan_wiki_query_archive"].ainvoke(
                {
                    "question": "What did Runtime say?",
                    "answer": "Runtime answer.",
                    "citations": [_citation_payload("Wiki/Runtime.md")],
                    "title": "Runtime Answer",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_synthesis":
            await by_name["plan_wiki_synthesis"].ainvoke(
                {
                    "title": "Runtime Synthesis",
                    "content": "Runtime synthesis.",
                    "source_paths": ["Wiki/Runtime.md"],
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_lint":
            await by_name["plan_wiki_lint"].ainvoke(
                {
                    "write_report": True,
                    "source_message_id": "message-1",
                }
            )
        return ChatModelRunResult(text=self.response, raw_result={"messages": []})


class FakeNonToolCallingChatModel:
    def __init__(self, response: str = "model-only answer") -> None:
        self.response = response
        self.calls = []

    async def complete_with_tools(self, *, user_message: str, system_prompt: str | None, tools):
        self.calls.append((user_message, system_prompt, [tool.name for tool in tools]))
        return ChatModelRunResult(text=self.response, raw_result={"messages": []})


class FakeFailingToolCallingChatModel:
    async def complete_with_tools(self, *, user_message: str, system_prompt: str | None, tools):
        by_name = {tool.name: tool for tool in tools}
        await by_name["propose_memory"].ainvoke(
            {
                "content": "use api key sk-agent-memory-secret-1234567890",
                "target_path": "Inbox/Pending Memories.md",
                "source_message_id": "message-1",
            }
        )
        return ChatModelRunResult(text="不应该成功", raw_result={})


class FakeBadRequestTaskModel:
    def __init__(self) -> None:
        self.calls = []

    async def complete_with_tools(self, *, user_message: str, system_prompt: str | None, tools):
        self.calls.append((user_message, system_prompt, [tool.name for tool in tools]))

        class BadRequestError(Exception):
            status_code = 400

        raise BadRequestError("tools are not supported")


class FakeRegistryChatModel:
    def __init__(self, tool_name: str | None, response: str) -> None:
        self.tool_name = tool_name
        self.response = response
        self.calls = []

    async def complete_with_tools(self, *, user_message: str, system_prompt: str | None, tools):
        tool_names = [tool.name for tool in tools]
        self.calls.append((user_message, system_prompt, tool_names))
        by_name = {tool.name: tool for tool in tools}
        if self.tool_name == "search_memory":
            await by_name["search_memory"].ainvoke({"query": "Ada", "top_k": 5})
        elif self.tool_name == "propose_memory":
            await by_name["propose_memory"].ainvoke(
                {
                    "content": "Ada likes tests",
                    "target_path": "Inbox/Pending Memories.md",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "create_task":
            await by_name["create_task"].ainvoke(
                {
                    "title": "review tests",
                    "source_text": user_message,
                }
            )
        elif self.tool_name == "manage_wiki_page":
            await by_name["manage_wiki_page"].ainvoke(
                {
                    "title": "Runtime",
                    "content": "Wiki content",
                    "operation": "append",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_ingest":
            await by_name["plan_wiki_ingest"].ainvoke(
                {
                    "title": "Runtime",
                    "content": "Wiki content",
                    "source_type": "agent_chat",
                    "tags": ["agent-chat"],
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_query_archive":
            await by_name["plan_wiki_query_archive"].ainvoke(
                {
                    "question": "What did Runtime say?",
                    "answer": "Runtime answer.",
                    "citations": [_citation_payload("Wiki/Runtime.md")],
                    "title": "Runtime Answer",
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_synthesis":
            await by_name["plan_wiki_synthesis"].ainvoke(
                {
                    "title": "Runtime Synthesis",
                    "content": "Runtime synthesis.",
                    "source_paths": ["Wiki/Runtime.md"],
                    "source_message_id": "message-1",
                }
            )
        elif self.tool_name == "plan_wiki_lint":
            await by_name["plan_wiki_lint"].ainvoke(
                {
                    "write_report": True,
                    "source_message_id": "message-1",
                }
            )
        return ChatModelRunResult(text=self.response, raw_result={"messages": []})

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt, []))
        return self.response


class FakeSemanticModel:
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload
        self.calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        if isinstance(self.payload, str):
            return self.payload
        return json.dumps(self.payload, ensure_ascii=False)


class FakeKeywordSemanticModel:
    def __init__(self) -> None:
        self.calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        needs_context = "search" in user_message.lower()
        return json.dumps(
            {
                "needs_context": needs_context,
                "source_scope": "all" if needs_context else "none",
                "query": "Ada" if needs_context else user_message,
                "answer_style": "grounded" if needs_context else "casual",
                "confidence": 0.9,
                "reason": "test",
            },
            ensure_ascii=False,
        )


def make_state(message: str) -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message=message,
    )


def _citation_payload(relative_path: str) -> dict[str, object]:
    return MemorySearchResult(
        note_id=f"note-{relative_path}",
        chunk_id=f"chunk-{relative_path}",
        relative_path=relative_path,
        title=relative_path.rsplit("/", 1)[-1].removesuffix(".md"),
        heading="Summary",
        snippet="Relevant wiki snippet.",
        score=1.0,
        source_scope="knowledge_base",
        retrieval_mode="fts",
    ).model_dump()


def non_status_event_names(events) -> list[str]:
    return [event.event for event in events if event.event != "status"]


def first_event(events, name: str):
    return next(event for event in events if event.event == name)


def assert_langgraph_events(events, expected: list[str]) -> None:
    assert events[0].event == "status"
    assert non_status_event_names(events) == expected
