from __future__ import annotations

import asyncio
import json
import enum

import pytest
from langchain_core.tools import StructuredTool

if not hasattr(enum, "StrEnum"):
    class StrEnum(str, enum.Enum):
        pass

    enum.StrEnum = StrEnum

from app.agents import (
    AgentRuntimeServices,
    AgentState,
    AgentTaskEvent,
    AgentToolRuntimeBase,
    LangGraphAgentRuntime,
    route_intent,
    sse_encode,
)
from app.models.api import (
    MemoryProposalActionResponse,
    MemorySearchResponse,
    MemorySearchResult,
    QueryArchiveLintResponse,
    TaskCreateResponse,
    WikiIngestPagePlan,
    WikiIngestPreviewResponse,
    WikiIngestReviewFinding,
    WikiIngestReviewResponse,
    WikiLintProposal,
    WikiLintIssue,
    WikiPageResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
)
from app.models.enums import AgentIntent
from app.agents import AgentToolSet
from app.services.chat_model import AgentId, AgentModelRegistry, ChatModelRunResult


class FakeRetrieval:
    def __init__(self) -> None:
        self.calls = []

    def search(
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

    def search(self, query: str, top_k: int = 5, mode: str = "fts") -> MemorySearchResponse:
        self.calls.append((query, top_k, mode))
        return MemorySearchResponse(results=[])


class FakeScopedRetrieval:
    def __init__(self) -> None:
        self.calls = []

    def search(
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

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> MemorySearchResponse:
        self.calls.append((query, top_k, mode, source_scope))
        if source_scope == "daily_chat":
            return MemorySearchResponse(
                results=[
                    MemorySearchResult(
                        note_id="daily-1",
                        chunk_id="daily-chunk-1",
                        relative_path="Memories/Daily/2026/05/第1周_05-01至05-07/星期一/2026-05-04.md",
                        title="2026-05-04 聊天记忆",
                        heading="10:00:00",
                        snippet="用户说自己喜欢苹果。",
                        score=0.8,
                        source_scope="daily_chat",
                    )
                ]
            )
        return MemorySearchResponse(results=[])


class FakeMultiScopeRetrieval:
    def __init__(self) -> None:
        self.calls = []

    def search(
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

    def create_proposal(self, request):
        self.requests.append(request)
        return MemoryProposalActionResponse(proposal_id="proposal-1", status="pending")


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

    def manage_page(self, request):
        self.requests.append(request)
        return WikiPageResponse(
            title=request.title,
            relative_path="Wiki/Runtime.md",
            operation=request.operation,
            status="updated",
            index_job_id="scheduled:vault-1",
        )


class FakeWikiWorkflow:
    def __init__(self) -> None:
        self.preview_requests = []
        self.review_requests = []
        self.query_archive_requests = []
        self.synthesis_requests = []
        self.lint_requests = []

    def preview_ingest(self, request):
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
            reviewer_agent_id="wiki_manager_agent",
        )

    def lint_query_archive(self, request):
        raise AssertionError("lint_query_archive should not be called in these tests")

    def plan_query_archive(self, request):
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

    def plan_synthesis(self, request):
        self.synthesis_requests.append(request)
        return WikiSynthesisProposal(
            title=request.title,
            target_path=request.target_path or "Wiki/Syntheses/Runtime-Synthesis.md",
            tags=["synthesis", *request.tags],
            links=[*request.links, *request.source_paths],
            source_paths=request.source_paths,
            markdown_preview=f"## 综合整理\n\n{request.content}",
        )

    def plan_lint(self, request):
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
            markdown_preview="## Wiki Lint Proposal",
        )


class FakeChatModel:
    def __init__(self, response: str = "模型回复：你好") -> None:
        self.response = response
        self.calls = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        return self.response


class FailingChatModel:
    def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
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
            await by_name["search_memory"].ainvoke({"query": "Ada", "top_k": 5, "mode": "fts"})
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
            await by_name["search_memory"].ainvoke({"query": "Ada", "top_k": 5, "mode": "fts"})
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



@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("hello there", AgentIntent.CHAT),
        ("search memory for Ada", AgentIntent.SEARCH_MEMORY),
        ("add to wiki: Runtime: Wiki manager owns knowledge pages", AgentIntent.MANAGE_WIKI),
        ("please remember Ada likes concise updates", AgentIntent.PROPOSE_MEMORY),
        ("remind me to stretch tomorrow", AgentIntent.CREATE_TASK),
        ("\u0035\u6708\u0033\u53f7\u6211\u8bf4\u4e86\u4ec0\u4e48", AgentIntent.SEARCH_MEMORY),
        ("搜索记忆 Ada", AgentIntent.SEARCH_MEMORY),
        ("记住：Ada 喜欢简洁的状态更新", AgentIntent.PROPOSE_MEMORY),
        ("提醒我明天伸展", AgentIntent.CREATE_TASK),
        ("5秒钟后提醒我写笔记", AgentIntent.CREATE_TASK),
    ],
)
def test_route_intent(message: str, intent: AgentIntent) -> None:
    assert route_intent(message).intent == intent


def test_runtime_searches_memory_through_protocol() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        runtime = AgentToolRuntimeBase(
            AgentRuntimeServices(retrieval=retrieval)
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls == [("Ada", 5, "fts")]
    assert_langgraph_events(events, ["citation", "token", "done"])
    assert first_event(events, "citation").citation.relative_path == "People/Ada.md"
    assert "Ada prefers concise status updates." in events[2].text


def test_runtime_creates_memory_proposal_without_writing_storage() -> None:
    async def run_case():
        memory = FakeMemory()
        runtime = AgentToolRuntimeBase(AgentRuntimeServices(memory=memory))

        events = [
            event
            async for event in runtime.run(
                make_state("remember this: Ada prefers concise updates")
            )
        ]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests[0].content == "Ada prefers concise updates"
    assert memory.requests[0].target_path == "Inbox/Pending Memories.md"
    assert [event.event for event in events] == [
        "status",
        "memory_proposal",
        "token",
        "done",
    ]
    assert first_event(events, "memory_proposal").proposal_id == "proposal-1"


def test_runtime_rejects_sensitive_memory_without_proposal_event() -> None:
    secret = "sk-agent-memory-secret-1234567890"

    async def run_case():
        memory = FakeMemory()
        runtime = AgentToolRuntimeBase(AgentRuntimeServices(memory=memory))

        events = [
            event
            async for event in runtime.run(
                make_state(f"remember this: use api key {secret}")
            )
        ]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests == []
    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "sensitive_memory_rejected"
    assert secret not in events[1].message


def test_runtime_creates_task_through_protocol() -> None:
    async def run_case():
        tasks = FakeTasks()
        runtime = AgentToolRuntimeBase(AgentRuntimeServices(tasks=tasks))

        events = [
            event async for event in runtime.run(make_state("remind me to stretch tomorrow"))
        ]

        return tasks, events

    tasks, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "stretch tomorrow"
    assert [event.event for event in events] == ["status", "task", "token", "done"]
    assert first_event(events, "task").task_id == "task-1"
    assert events[1].reminder_id == "reminder-1"
    assert events[1].title == "stretch tomorrow"
    assert first_event(events, "task").reminder_status == "scheduled"
    assert events[1].remind_at == "2026-05-02T07:00:00Z"
    assert events[1].timezone_label == "北京时间"


def test_runtime_manages_wiki_through_protocol() -> None:
    async def run_case():
        wiki_workflow = FakeWikiWorkflow()
        runtime = AgentToolRuntimeBase(AgentRuntimeServices(wiki_workflow=wiki_workflow))

        events = [
            event async for event in runtime.run(make_state("add to wiki: Runtime: Wiki manager owns pages"))
        ]

        return wiki_workflow, events

    wiki_workflow, events = asyncio.run(run_case())

    assert wiki_workflow.preview_requests[0].title == "Runtime"
    assert wiki_workflow.preview_requests[0].content == "Runtime: Wiki manager owns pages"
    assert wiki_workflow.review_requests[0].run_id == "wiki-run-1"
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    proposal = first_event(events, "wiki_proposal")
    assert proposal.run_id == "wiki-run-1"
    assert proposal.review_id == "review-1"
    assert proposal.recommended_targets == ["Wiki/Sources/Runtime.md"]
    assert "确认后才会写入 Markdown" in first_event(events, "token").text


def test_langgraph_wiki_manager_can_plan_query_archive_without_writing_markdown() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel("plan_wiki_query_archive", "已创建查询归档提案，等待确认。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("archive to wiki query archive: Runtime answer"))
        ]
        return wiki, wiki_workflow, wiki_model, events

    wiki, wiki_workflow, wiki_model, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_model.calls[0][2] == [
        "plan_wiki_ingest",
        "plan_wiki_query_archive",
        "plan_wiki_synthesis",
        "plan_wiki_lint",
    ]
    assert wiki_workflow.query_archive_requests[0].answer == "Runtime answer."
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    proposal = first_event(events, "wiki_proposal")
    assert proposal.proposal_type == "query_archive"
    assert proposal.target_paths == ["Wiki/Reports/Runtime-Answer.md"]
    assert proposal.markdown_preview.startswith("## 查询归档")


def test_langgraph_wiki_manager_can_plan_synthesis_without_writing_markdown() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel("plan_wiki_synthesis", "已创建综合整理提案，等待确认。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("add to wiki synthesis: Runtime synthesis"))
        ]
        return wiki, wiki_workflow, events

    wiki, wiki_workflow, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_workflow.synthesis_requests[0].title == "Runtime Synthesis"
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    proposal = first_event(events, "wiki_proposal")
    assert proposal.proposal_type == "synthesize"
    assert proposal.target_paths == ["Wiki/Syntheses/Runtime-Synthesis.md"]
    assert proposal.markdown_preview.startswith("## 综合整理")


def test_langgraph_wiki_manager_can_plan_lint_without_writing_markdown() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel("plan_wiki_lint", "已创建 lint 提案，等待确认。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("add to wiki lint report"))]
        return wiki, wiki_workflow, events

    wiki, wiki_workflow, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_workflow.lint_requests[0].write_report is True
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    proposal = first_event(events, "wiki_proposal")
    assert proposal.proposal_type == "lint"
    assert proposal.write_report is True
    assert proposal.target_paths == ["Wiki/Reports/Lint-2026-05-11.md"]
    assert proposal.lint_summary == {"issues": 1, "warnings": 1, "errors": 0}


def test_runtime_handles_chinese_memory_and_task_commands() -> None:
    async def run_case():
        memory = FakeMemory()
        tasks = FakeTasks()
        runtime = AgentToolRuntimeBase(AgentRuntimeServices(memory=memory, tasks=tasks))

        memory_events = [
            event async for event in runtime.run(make_state("记住：Ada 喜欢简洁的状态更新"))
        ]
        task_events = [event async for event in runtime.run(make_state("提醒我明天伸展"))]

        return memory, tasks, memory_events, task_events

    memory, tasks, memory_events, task_events = asyncio.run(run_case())

    assert memory.requests[0].content == "Ada 喜欢简洁的状态更新"
    assert memory.requests[0].target_path == "Inbox/Pending Memories.md"
    assert memory_events[-2].text == "我已创建一条待确认的记忆提案，请审核后再写入。"
    assert tasks.requests[0].title == "明天伸展"
    assert task_events[-2].text == "我已创建任务。"


def test_runtime_uses_configured_chat_model_for_plain_chat() -> None:
    async def run_case():
        chat_model = FakeChatModel("这是模型生成的回复。")
        runtime = AgentToolRuntimeBase(
            AgentRuntimeServices(chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "你好"
    assert "桌宠伙伴" in chat_model.calls[0][1]
    assert_langgraph_events(events, ["token", "done"])
    assert events[1].text == "这是模型生成的回复。"
    assert events[-1].text == "这是模型生成的回复。"


def test_runtime_falls_back_when_chat_model_fails() -> None:
    async def run_case():
        runtime = AgentToolRuntimeBase(
            AgentRuntimeServices(chat_model=FailingChatModel())
        )

        return [event async for event in runtime.run(make_state("你好"))]

    events = asyncio.run(run_case())

    assert [event.event for event in events] == ["status", "error"]
    assert first_event(events, "error").code == "model_invocation_failed"
    assert events[1].message == "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。"


def test_runtime_does_not_call_chat_model_for_search_intent() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeChatModel()
        runtime = AgentToolRuntimeBase(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [("Ada", 5, "fts")]
    assert chat_model.calls == []
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_runtime_preserves_core_search_event_contract() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(retrieval=retrieval))

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert events[0].event == "status"
    assert [event.citation.source_scope for event in events if event.event == "citation"] == [
        "personal_memory",
        "knowledge_base",
    ]
    assert any(event.event == "token" for event in events)
    assert events[-1].event == "done"
    assert first_event(events, "citation").citation.relative_path == "People/Ada.md"


def test_langgraph_runtime_preserves_core_tool_agents() -> None:
    async def run_case():
        memory = FakeMemory()
        tasks = FakeTasks()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(memory=memory, tasks=tasks)
        )

        memory_events = [
            event async for event in runtime.run(make_state("remember this: Ada likes tests"))
        ]
        task_events = [
            event async for event in runtime.run(make_state("remind me to review tests"))
        ]

        return memory, tasks, memory_events, task_events

    memory, tasks, memory_events, task_events = asyncio.run(run_case())

    assert memory.requests[0].content == "Ada likes tests"
    assert tasks.requests[0].title == "review tests"
    assert_langgraph_events(memory_events, ["memory_proposal", "token", "done"])
    assert_langgraph_events(task_events, ["task", "token", "done"])


def test_langgraph_runtime_uses_langchain_structured_tools_for_core_services() -> None:
    toolset = AgentToolSet(
        retrieval=FakeRetrieval(),
        memory=FakeMemory(),
        tasks=FakeTasks(),
    )

    tools = toolset.all_tools()

    assert all(isinstance(tool, StructuredTool) for tool in tools)
    assert [tool.name for tool in tools] == [
        "search_memory",
        "propose_memory",
        "plan_wiki_ingest",
        "plan_wiki_query_archive",
        "plan_wiki_synthesis",
        "plan_wiki_lint",
        "manage_wiki_page",
        "create_task",
    ]


def test_agent_model_registry_returns_stable_agent_clients() -> None:
    chat_model = FakeRegistryChatModel(None, "chat")
    registry = AgentModelRegistry({AgentId.CHAT_AGENT: chat_model})

    assert registry.get(AgentId.CHAT_AGENT) is chat_model
    assert registry.get("chat_agent") is chat_model

    with pytest.raises(Exception) as exc_info:
        registry.get(AgentId.TASK_AGENT)
    assert getattr(exc_info.value, "code") == "agent_model_not_configured"
    assert getattr(exc_info.value, "agent_id") == AgentId.TASK_AGENT


def test_langgraph_runtime_uses_independent_registry_models_and_allowed_tools() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        memory = FakeMemory()
        tasks = FakeTasks()
        wiki_workflow = FakeWikiWorkflow()
        chat_model = FakeRegistryChatModel(None, "chat-only")
        semantic_model = FakeKeywordSemanticModel()
        memory_retrieval_model = FakeRegistryChatModel("search_memory", "memory answer")
        knowledge_retrieval_model = FakeRegistryChatModel("search_memory", "knowledge answer")
        wiki_model = FakeRegistryChatModel("plan_wiki_ingest", "wiki answer")
        memory_model = FakeRegistryChatModel("propose_memory", "memory answer")
        task_model = FakeRegistryChatModel("create_task", "task answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                memory=memory,
                tasks=tasks,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.CHAT_AGENT: chat_model,
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.KNOWLEDGE_RETRIEVAL_AGENT: knowledge_retrieval_model,
                        AgentId.WIKI_MANAGER_AGENT: wiki_model,
                        AgentId.MEMORY_PROPOSAL_AGENT: memory_model,
                        AgentId.TASK_AGENT: task_model,
                    }
                ),
            )
        )

        chat_events = [event async for event in runtime.run(make_state("hello"))]
        search_events = [event async for event in runtime.run(make_state("search memory for Ada"))]
        wiki_events = [event async for event in runtime.run(make_state("add to wiki: Runtime: Wiki content"))]
        memory_events = [event async for event in runtime.run(make_state("remember this: Ada likes tests"))]
        task_events = [event async for event in runtime.run(make_state("remind me to review tests"))]

        return (
            retrieval,
            chat_model,
            semantic_model,
            memory_retrieval_model,
            knowledge_retrieval_model,
            wiki_model,
            memory_model,
            task_model,
            chat_events,
            search_events,
            wiki_events,
            memory_events,
            task_events,
        )

    (
        retrieval,
        chat_model,
        semantic_model,
        memory_retrieval_model,
        knowledge_retrieval_model,
        wiki_model,
        memory_model,
        task_model,
        chat_events,
        search_events,
        wiki_events,
        memory_events,
        task_events,
    ) = asyncio.run(run_case())

    assert chat_model.calls[0][2] == []
    assert semantic_model.calls
    assert memory_retrieval_model.calls[0][2] == ["search_memory"]
    assert knowledge_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert wiki_model.calls[0][2] == [
        "plan_wiki_ingest",
        "plan_wiki_query_archive",
        "plan_wiki_synthesis",
        "plan_wiki_lint",
    ]
    assert memory_model.calls[0][2] == ["propose_memory"]
    assert task_model.calls[0][2] == []
    assert_langgraph_events(chat_events, ["token", "done"])
    search_event_names = non_status_event_names(search_events)
    assert search_event_names == ["citation", "citation", "token", "done"]
    assert [event.citation.source_scope for event in search_events if event.event == "citation"] == [
        "personal_memory",
        "knowledge_base",
    ]
    assert_langgraph_events(wiki_events, ["wiki_proposal", "token", "done"])
    assert_langgraph_events(memory_events, ["memory_proposal", "token", "done"])
    assert_langgraph_events(task_events, ["task", "token", "done"])


def test_langgraph_runtime_returns_stable_error_when_registry_missing_agent_model() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(model_registry=AgentModelRegistry({}))
        )

        return [event async for event in runtime.run(make_state("hello"))]

    events = asyncio.run(run_case())

    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "agent_model_not_configured"


def test_langgraph_semantic_agent_drives_memory_retrieval_before_chat() -> None:
    async def run_case():
        retrieval = FakeScopedRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "concise",
                "confidence": 0.92,
                "reason": "personal preference question",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "我翻到记录里写着你喜欢苹果。")
        memory_model = FakeRegistryChatModel("propose_memory", "memory answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                        AgentId.MEMORY_PROPOSAL_AGENT: memory_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("Can you use the earlier context?"))]
        return retrieval, semantic_model, memory_retrieval_model, chat_model, memory_model, events

    retrieval, semantic_model, memory_retrieval_model, chat_model, memory_model, events = asyncio.run(run_case())

    assert semantic_model.calls[0][0] == "Can you use the earlier context?"
    assert memory_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [("用户喜欢什么水果", 5, "fts", "personal_memory")]
    assert memory_model.calls == []
    assert "用户喜欢苹果" in chat_model.calls[-1][0]
    assert "Memories/Preferences.md" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])
    assert first_event(events, "token").text == "我翻到记录里写着你喜欢苹果。"


def test_langgraph_semantic_agent_drives_knowledge_retrieval_before_chat() -> None:
    async def run_case():
        retrieval = FakeScopedRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "knowledge_base",
                "query": "runtime docs",
                "answer_style": "grounded",
                "confidence": 0.92,
                "reason": "knowledge-base question",
            }
        )
        knowledge_retrieval_model = FakeRegistryChatModel(None, "knowledge checked")
        chat_model = FakeRegistryChatModel(None, "knowledge answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.KNOWLEDGE_RETRIEVAL_AGENT: knowledge_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("search docs for runtime"))]
        return retrieval, knowledge_retrieval_model, chat_model, events

    retrieval, knowledge_retrieval_model, chat_model, events = asyncio.run(run_case())

    assert knowledge_retrieval_model.calls[0][2] == ["search_memory"]
    assert retrieval.calls == [("runtime docs", 5, "fts", "knowledge_base")]
    assert "Wiki/Runtime.md" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_falls_back_to_daily_chat_as_weak_evidence_when_personal_memory_empty() -> None:
    async def run_case():
        retrieval = FakePersonalEmptyDailyRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "concise",
                "confidence": 0.9,
                "reason": "personal preference question",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "我只在聊天日记里看到你提过苹果，还没沉淀为长期记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                        {
                            AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                            AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                            AgentId.CHAT_AGENT: chat_model,
                        }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("Can you use the earlier context?"))]
        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("用户喜欢什么水果", 5, "fts", "personal_memory"),
        ("用户喜欢什么水果", 5, "fts", "daily_chat"),
    ]
    assert "上下文范围：daily_chat" in chat_model.calls[-1][0]
    assert "还没沉淀为长期记忆" in chat_model.calls[-1][0]
    assert first_event(events, "citation").citation.source_scope == "daily_chat"
    assert any(getattr(event, "stage", None) == "daily_chat_fallback" for event in events)
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_forces_date_recall_to_daily_chat_even_when_semantic_model_misroutes() -> None:
    async def run_case():
        retrieval = FakePersonalEmptyDailyRetrieval()
        semantic_model = FakeSemanticModel(
            {
                "needs_context": True,
                "source_scope": "personal_memory",
                "query": "用户喜欢什么水果",
                "answer_style": "grounded",
                "confidence": 0.9,
                "reason": "bad model route",
            }
        )
        memory_retrieval_model = FakeRegistryChatModel(None, "memory checked")
        chat_model = FakeRegistryChatModel(None, "5月4号的聊天日记里，你说过自己喜欢苹果。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.SEMANTIC_ANALYSIS_AGENT: semantic_model,
                        AgentId.MEMORY_RETRIEVAL_AGENT: memory_retrieval_model,
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("我在5月4号说了什么事情吗？"))]
        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [("我在5月4号说了什么事情吗？", 5, "fts", "daily_chat")]
    assert "上下文范围：daily_chat" in chat_model.calls[-1][0]
    assert "用户说自己喜欢苹果" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "token", "done"])


def test_langgraph_aggregates_and_compresses_companion_memory_route_scopes() -> None:
    async def run_case():
        retrieval = FakeMultiScopeRetrieval()
        chat_model = FakeRegistryChatModel(None, "companion memory answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                retrieval=retrieval,
                model_registry=AgentModelRegistry(
                    {
                        AgentId.CHAT_AGENT: chat_model,
                    }
                ),
            )
        )

        events = [
            event
            async for event in runtime.run(make_state("What do you remember about my coding style?"))
        ]
        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("What do you remember about my coding style?", 5, "fts", "personal_memory"),
        ("What do you remember about my coding style?", 5, "fts", "diary_objects"),
        ("What do you remember about my coding style?", 5, "fts", "daily_chat"),
    ]
    citation_events = [event for event in events if event.event == "citation"]
    assert [event.citation.source_scope for event in citation_events] == [
        "personal_memory",
        "personal_memory",
        "diary_objects",
        "daily_chat",
    ]
    assert "Ada prefers concise status updates." in chat_model.calls[-1][0]
    assert "Ada felt focused after a refactor review." in chat_model.calls[-1][0]
    assert "This lower priority personal memory should be compressed away." not in chat_model.calls[-1][0]
    assert "上下文范围：all" in chat_model.calls[-1][0]
    assert_langgraph_events(events, ["citation", "citation", "citation", "citation", "token", "done"])


def test_langgraph_runtime_uses_configured_chat_model_for_plain_chat() -> None:
    async def run_case():
        chat_model = FakeChatModel("LangGraph 聊天回复")
        runtime = LangGraphAgentRuntime(AgentRuntimeServices(chat_model=chat_model))

        events = [event async for event in runtime.run(make_state("你好"))]

        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "你好"
    assert "桌宠伙伴" in chat_model.calls[0][1]
    assert_langgraph_events(events, ["token", "done"])
    assert first_event(events, "token").text == "LangGraph 聊天回复"
    assert events[-1].text == "LangGraph 聊天回复"


def test_langgraph_runtime_injects_confirmed_continuity_context() -> None:
    async def run_case():
        chat_model = FakeChatModel("continuity-aware answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuity(
                    "Confirmed continuity context (user-reviewed; compact runtime state):\n"
                    "- current mood: User is tired."
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert "Confirmed continuity context" in chat_model.calls[0][0]
    assert "Companion presence behavior" in chat_model.calls[0][0]
    assert "User is tired." in chat_model.calls[0][0]
    assert "Current user message:\nhello" in chat_model.calls[0][0]
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_emits_confirmed_continuity_signal_before_reply() -> None:
    async def run_case():
        chat_model = FakeChatModel("continuity-aware answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuityWithSignal(
                    "Confirmed continuity context (user-reviewed; compact runtime state):\n"
                    "- unresolved threads: continue this tomorrow"
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    signal = first_event(events, "continuity_signal")
    assert signal.kind == "open_thread"
    assert signal.intensity == "high"
    assert signal.source_state_keys == ["unresolved_threads"]
    assert "Companion presence behavior" in chat_model.calls[0][0]
    assert_langgraph_events(events, ["continuity_signal", "token", "done"])


def test_langgraph_runtime_does_not_inject_pending_continuity_when_adapter_is_empty() -> None:
    async def run_case():
        chat_model = FakeChatModel("plain answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                chat_model=chat_model,
                continuity=FakeContinuity(""),
            )
        )

        events = [event async for event in runtime.run(make_state("hello"))]
        return chat_model, events

    chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][0] == "hello"
    assert_langgraph_events(events, ["token", "done"])


def test_langgraph_runtime_emits_error_without_done_when_chat_model_fails() -> None:
    async def run_case():
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(chat_model=FailingChatModel())
        )

        return [event async for event in runtime.run(make_state("你好"))]

    events = asyncio.run(run_case())

    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "model_invocation_failed"
    assert first_event(events, "error").message == "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。"


def test_langgraph_runtime_uses_chat_model_to_answer_search_intent() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeChatModel("我翻到 Ada 喜欢简洁的状态更新。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert chat_model.calls
    assert "Ada prefers concise status updates." in chat_model.calls[0][0]
    assert_langgraph_events(events, ["citation", "citation", "token", "done"])
    assert first_event(events, "token").text == "我翻到 Ada 喜欢简洁的状态更新。"


def test_langgraph_chat_agent_maps_model_search_tool_call_to_citation_event() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel("已根据记忆回答。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("search memory for Ada"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == [
        ("Ada", 5, "fts", "personal_memory"),
        ("Ada", 5, "fts", "knowledge_base"),
    ]
    assert chat_model.calls[0][2] == []
    assert_langgraph_events(events, ["citation", "citation", "token", "done"])
    assert first_event(events, "citation").citation.relative_path == "People/Ada.md"
    assert first_event(events, "token").text == "已根据记忆回答。"


def test_langgraph_chat_agent_does_not_search_for_plain_question_when_model_skips_tool() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel("model-only answer")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("What does Ada prefer?"))]

        return retrieval, chat_model, events

    retrieval, chat_model, events = asyncio.run(run_case())

    assert retrieval.calls == []
    assert chat_model.calls[0][2] == []
    assert events[0].event == "status"
    assert events[-1].event == "done"
    token_text = "".join(event.text for event in events if event.event == "token")
    assert token_text == "model-only answer"


def test_langgraph_chat_agent_can_surface_wiki_manager_for_obsidian_note_request() -> None:
    async def run_case():
        wiki_workflow = FakeWikiWorkflow()
        chat_model = FakeToolCallingChatModel("plan_wiki_ingest", "I drafted a Vault proposal for confirmation.")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.CHAT_AGENT: chat_model}),
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("Turn this into an Obsidian note: Runtime: Wiki manager owns pages")
            )
        ]

        return wiki_workflow, chat_model, events

    wiki_workflow, chat_model, events = asyncio.run(run_case())

    assert chat_model.calls[0][2] == ["plan_wiki_ingest"]
    assert wiki_workflow.preview_requests[0].title == "Runtime"
    assert wiki_workflow.preview_requests[0].content == "Wiki content"
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    assert first_event(events, "wiki_proposal").review_id == "review-1"
    assert first_event(events, "token").text == "I drafted a Vault proposal for confirmation."


def test_langgraph_chat_agent_executes_text_search_tool_call_instead_of_echoing() -> None:
    async def run_case():
        retrieval = FakeRetrieval()
        chat_model = FakeNonToolCallingChatModel(
            "<tool_call><function=search_notes> <parameter=query>5月3号</parameter> </function> </tool_call>"
        )
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("tell me about that day"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert len(retrieval.calls) == 1
    assert retrieval.calls[0][1:] == (5, "fts", "all")
    assert events[0].event == "status"
    assert first_event(events, "citation").event == "citation"
    assert events[-1].event == "done"
    token_text = "".join(event.text for event in events if event.event == "token")
    assert "<tool_call>" not in token_text
    assert "Ada prefers concise status updates." in token_text


def test_langgraph_chat_agent_answers_naturally_when_search_is_empty() -> None:
    async def run_case():
        retrieval = FakeEmptyRetrieval()
        chat_model = FakeNonToolCallingChatModel("我翻了下记忆本，暂时没有找到能引用的记录。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(retrieval=retrieval, chat_model=chat_model)
        )

        events = [event async for event in runtime.run(make_state("你记得我喜欢什么吗"))]

        return retrieval, events

    retrieval, events = asyncio.run(run_case())

    assert retrieval.calls
    assert all(call == ("你记得我喜欢什么吗", 5, "fts") for call in retrieval.calls)
    assert_langgraph_events(events, ["token", "done"])
    assert "翻了下记忆本" in first_event(events, "token").text


def test_langgraph_chat_agent_maps_model_memory_tool_call_to_proposal_event() -> None:
    async def run_case():
        memory = FakeMemory()
        memory_model = FakeToolCallingChatModel("propose_memory", "已创建待确认记忆。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.MEMORY_PROPOSAL_AGENT: memory_model}
                ),
            )
        )

        events = [
            event
            async for event in runtime.run(
                make_state("请把 Ada likes tests 作为长期偏好保存下来")
            )
        ]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests[0].content == "Ada likes tests"
    assert_langgraph_events(events, ["memory_proposal", "token", "done"])
    assert first_event(events, "memory_proposal").proposal_id == "proposal-1"
    assert first_event(events, "token").text == "已创建待确认记忆。"


def test_langgraph_task_agent_uses_model_for_confirmation_after_local_task_create() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeRegistryChatModel(None, "已创建任务。")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.TASK_AGENT: task_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("安排一次测试事项"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "安排一次测试事项"
    assert task_model.calls[0][2] == []
    assert_langgraph_events(events, ["task", "token", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").title == "安排一次测试事项"
    assert first_event(events, "task").reminder_status == "scheduled"
    assert first_event(events, "task").timezone_label == "北京时间"
    assert first_event(events, "token").text == "已创建任务。"


def test_langgraph_task_agent_creates_task_when_provider_rejects_model_params() -> None:
    async def run_case():
        tasks = FakeTasks()
        task_model = FakeBadRequestTaskModel()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                tasks=tasks,
                model_registry=AgentModelRegistry({AgentId.TASK_AGENT: task_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("5秒钟后提醒我写笔记"))]

        return tasks, task_model, events

    tasks, task_model, events = asyncio.run(run_case())

    assert tasks.requests[0].title == "写笔记"
    assert tasks.requests[0].source_text == "5秒钟后提醒我写笔记"
    assert task_model.calls[0][2] == []
    assert_langgraph_events(events, ["task", "token", "done"])
    assert first_event(events, "task").task_id == "task-1"
    assert first_event(events, "task").reminder_id == "reminder-1"
    assert first_event(events, "token").text == "我已创建任务。"


def test_langgraph_chat_agent_returns_error_when_model_tool_call_fails() -> None:
    async def run_case():
        memory = FakeMemory()
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                memory=memory,
                model_registry=AgentModelRegistry(
                    {AgentId.MEMORY_PROPOSAL_AGENT: FakeFailingToolCallingChatModel()}
                ),
            )
        )

        events = [event async for event in runtime.run(make_state("请把这个密钥保存到长期偏好里"))]

        return memory, events

    memory, events = asyncio.run(run_case())

    assert memory.requests == []
    assert_langgraph_events(events, ["error"])
    assert first_event(events, "error").code == "sensitive_memory_rejected"
    assert "敏感内容" in first_event(events, "error").message


def test_sse_encode_uses_event_name_and_json_data() -> None:
    encoded = sse_encode(
        AgentTaskEvent(
            agent_run_id="run-1",
            task_id="task-1",
            reminder_id=None,
            status="pending",
        )
    )

    event_line, data_line, blank = encoded.splitlines()
    assert event_line == "event: task"
    assert blank == ""
    payload = json.loads(data_line.removeprefix("data: "))
    assert payload == {
        "agent_run_id": "run-1",
        "task_id": "task-1",
        "reminder_id": None,
        "status": "pending",
        "title": None,
        "reminder_status": None,
        "remind_at": None,
        "timezone": None,
        "timezone_label": None,
    }
