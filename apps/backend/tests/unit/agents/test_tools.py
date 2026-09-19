from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.agents.tools import (
    AgentToolResult,
    AgentToolSet,
    AgentToolUnavailableError,
    CreateTaskInput,
    ManageWikiPageInput,
    PlanWikiIngestInput,
    PlanWikiLintInput,
    PlanWikiQueryArchiveInput,
    PlanWikiSynthesisInput,
    ProposeMemoryInput,
    SearchMemoryInput,
)
from app.models.api import (
    MemoryProposalActionResponse,
    MemorySearchResponse,
    MemorySearchResult,
    QueryArchiveLintResponse,
    TaskCreateResponse,
    WikiIngestPagePlan,
    WikiIngestPreviewResponse,
    WikiIngestReviewResponse,
    WikiLintProposal,
    WikiPageResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
)
from app.utils.coerce import coerce_field


@dataclass(frozen=True)
class ToolCase:
    name: str
    method_name: str
    service_attr: str
    service_method: str
    kwargs: dict
    service_result: object
    empty_result: object
    expected_type: type
    expected_empty_attr: str
    expected_empty_value: object


def _memory_result() -> MemorySearchResult:
    return MemorySearchResult(
        note_id="note-1",
        chunk_id="chunk-1",
        relative_path="Memories/test.md",
        title="Test",
        snippet="hello",
        score=0.9,
    )


def _page_response() -> WikiPageResponse:
    return WikiPageResponse(
        title="Page",
        relative_path="Wiki/page.md",
        operation="append",
        status="updated",
        action_id="action-1",
    )


def _lint_response() -> QueryArchiveLintResponse:
    return QueryArchiveLintResponse(passed=True)


def _ingest_preview(page_plans: list[WikiIngestPagePlan] | None = None) -> WikiIngestPreviewResponse:
    return WikiIngestPreviewResponse(
        run_id="run-1",
        source_id="source-1",
        source_hash="hash-1",
        status="planned",
        page_plans=page_plans or [],
        summary="summary",
    )


def _ingest_review() -> WikiIngestReviewResponse:
    return WikiIngestReviewResponse(
        review_id="review-1",
        run_id="run-1",
        status="reviewed",
        summary="ok",
    )


def _query_archive_proposal() -> WikiQueryArchiveProposal:
    return WikiQueryArchiveProposal(
        status="planned",
        title="Archive",
        target_path="Wiki/Reports/archive.md",
        lint=_lint_response(),
    )


def _synthesis_proposal() -> WikiSynthesisProposal:
    return WikiSynthesisProposal(
        title="Synthesis",
        target_path="Wiki/Syntheses/synthesis.md",
        markdown_preview="content",
    )


def _lint_proposal() -> WikiLintProposal:
    return WikiLintProposal(
        status="planned",
        title="Wiki Lint Report",
        summary={"errors": 0},
    )


def _tool_cases() -> list[ToolCase]:
    return [
        ToolCase(
            name="search_memory",
            method_name="search_memory",
            service_attr="retrieval",
            service_method="search",
            kwargs={"query": "apple", "top_k": 2},
            service_result=MemorySearchResponse(results=[_memory_result()]),
            empty_result=MemorySearchResponse(results=[]),
            expected_type=MemorySearchResponse,
            expected_empty_attr="results",
            expected_empty_value=[],
        ),
        ToolCase(
            name="propose_memory",
            method_name="propose_memory",
            service_attr="memory",
            service_method="create_proposal",
            kwargs={"content": "- 用户喜欢苹果"},
            service_result=MemoryProposalActionResponse(proposal_id="proposal-1", status="pending"),
            empty_result=MemoryProposalActionResponse(proposal_id="", status="pending"),
            expected_type=MemoryProposalActionResponse,
            expected_empty_attr="proposal_id",
            expected_empty_value="",
        ),
        ToolCase(
            name="create_task",
            method_name="create_task",
            service_attr="tasks",
            service_method="create",
            kwargs={"title": "Buy apples"},
            service_result=TaskCreateResponse(task_id="task-1", status="created"),
            empty_result=TaskCreateResponse(task_id="", status="created"),
            expected_type=TaskCreateResponse,
            expected_empty_attr="task_id",
            expected_empty_value="",
        ),
        ToolCase(
            name="manage_wiki_page",
            method_name="manage_wiki_page",
            service_attr="wiki",
            service_method="manage_page",
            kwargs={"title": "Page", "content": "content"},
            service_result=_page_response(),
            empty_result=WikiPageResponse(title="", relative_path="", operation="append", status="updated"),
            expected_type=WikiPageResponse,
            expected_empty_attr="relative_path",
            expected_empty_value="",
        ),
        ToolCase(
            name="plan_wiki_ingest",
            method_name="plan_wiki_ingest",
            service_attr="wiki_workflow",
            service_method="preview_ingest",
            kwargs={"title": "Ingest", "content": "content"},
            service_result={"preview": _ingest_preview([WikiIngestPagePlan(title="Page", target_path="Wiki/page.md", content="content")]), "review": _ingest_review()},
            empty_result={"preview": _ingest_preview([]), "review": _ingest_review()},
            expected_type=object,
            expected_empty_attr="page_plans",
            expected_empty_value=[],
        ),
        ToolCase(
            name="plan_wiki_query_archive",
            method_name="plan_wiki_query_archive",
            service_attr="wiki_workflow",
            service_method="plan_query_archive",
            kwargs={"question": "Q?", "answer": "A"},
            service_result=_query_archive_proposal(),
            empty_result=WikiQueryArchiveProposal(status="planned", title="", target_path="", lint=_lint_response()),
            expected_type=WikiQueryArchiveProposal,
            expected_empty_attr="target_path",
            expected_empty_value="",
        ),
        ToolCase(
            name="plan_wiki_synthesis",
            method_name="plan_wiki_synthesis",
            service_attr="wiki_workflow",
            service_method="plan_synthesis",
            kwargs={"title": "Synthesis", "content": "content"},
            service_result=_synthesis_proposal(),
            empty_result=WikiSynthesisProposal(title="", target_path="", markdown_preview=""),
            expected_type=WikiSynthesisProposal,
            expected_empty_attr="target_path",
            expected_empty_value="",
        ),
        ToolCase(
            name="plan_wiki_lint",
            method_name="plan_wiki_lint",
            service_attr="wiki_workflow",
            service_method="plan_lint",
            kwargs={},
            service_result=_lint_proposal(),
            empty_result=WikiLintProposal(status="planned", title="Wiki Lint Report", summary={}),
            expected_type=WikiLintProposal,
            expected_empty_attr="summary",
            expected_empty_value={},
        ),
    ]


def _toolset_for(case: ToolCase, result: object, observer=None) -> AgentToolSet:
    service = type("Service", (), {})()
    if case.name == "plan_wiki_ingest":
        service.preview_ingest = AsyncMock(return_value=result["preview"])
        service.review_ingest = AsyncMock(return_value=result["review"])
    else:
        setattr(service, case.service_method, AsyncMock(return_value=result))
    return AgentToolSet(**{case.service_attr: service, "observer": observer})


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _tool_cases(), ids=lambda case: case.name)
async def test_tool_method_returns_service_result(case: ToolCase) -> None:
    observed: list[AgentToolResult] = []
    toolset = _toolset_for(case, case.service_result, observed.append)

    response = await getattr(toolset, case.method_name)(**case.kwargs)

    if case.name == "plan_wiki_ingest":
        assert response.run_id == case.service_result["preview"].run_id
    else:
        assert isinstance(response, case.expected_type)
    assert observed == [AgentToolResult(name=case.name, value=response)]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _tool_cases(), ids=lambda case: case.name)
async def test_tool_method_returns_empty_result(case: ToolCase) -> None:
    toolset = _toolset_for(case, case.empty_result)

    response = await getattr(toolset, case.method_name)(**case.kwargs)

    assert getattr(response, case.expected_empty_attr) == case.expected_empty_value


@pytest.mark.asyncio
@pytest.mark.parametrize("claimed_type", ["manual", "file", "user_message", "agent_chat"])
async def test_ingest_tool_cannot_assign_itself_root_provenance(claimed_type) -> None:
    case = next(item for item in _tool_cases() if item.name == "plan_wiki_ingest")
    toolset = _toolset_for(case, case.service_result)

    await toolset.plan_wiki_ingest(
        title="Agent text", content="An assistant claim.", source_type=claimed_type,
        source_uri="source:claimed-original", source_message_id="claimed-user-message",
    )

    request = toolset.wiki_workflow.preview_ingest.call_args.args[0]
    assert request.source_type == "assistant_output"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", _tool_cases(), ids=lambda case: case.name)
async def test_tool_method_when_service_is_none(case: ToolCase) -> None:
    toolset = AgentToolSet()

    with pytest.raises(AgentToolUnavailableError) as exc:
        await getattr(toolset, case.method_name)(**case.kwargs)

    assert exc.value.tool_name == case.name


def test_coerce_field_with_correct_type() -> None:
    assert coerce_field(3, int, 0) == 3


def test_coerce_field_with_convertible_type() -> None:
    assert coerce_field("3", int, 0) == 3


def test_coerce_field_with_unconvertible_type_returns_default() -> None:
    assert coerce_field("not-a-number", int, 0) == 0


@pytest.mark.parametrize(
    ("tool_factory", "input_type", "required_field"),
    [
        (AgentToolSet().search_memory_tool, SearchMemoryInput, "query"),
        (AgentToolSet().propose_memory_tool, ProposeMemoryInput, "content"),
        (AgentToolSet().plan_wiki_ingest_tool, PlanWikiIngestInput, "title"),
        (AgentToolSet().plan_wiki_query_archive_tool, PlanWikiQueryArchiveInput, "question"),
        (AgentToolSet().plan_wiki_synthesis_tool, PlanWikiSynthesisInput, "title"),
        (AgentToolSet().plan_wiki_lint_tool, PlanWikiLintInput, "write_report"),
        (AgentToolSet().manage_wiki_page_tool, ManageWikiPageInput, "title"),
        (AgentToolSet().create_task_tool, CreateTaskInput, "title"),
    ],
)
def test_tool_schema_has_required_fields(tool_factory, input_type, required_field: str) -> None:
    tool = tool_factory()

    assert tool.args_schema is input_type
    assert required_field in tool.args_schema.model_json_schema()["properties"]


@pytest.mark.parametrize(
    "input_type,valid_payload",
    [
        (SearchMemoryInput, {"query": "apple"}),
        (ProposeMemoryInput, {"content": "- 用户喜欢苹果"}),
        (PlanWikiIngestInput, {"title": "Ingest", "content": "content"}),
        (PlanWikiQueryArchiveInput, {"question": "Q?", "answer": "A"}),
        (PlanWikiSynthesisInput, {"title": "Synthesis", "content": "content"}),
        (PlanWikiLintInput, {}),
        (ManageWikiPageInput, {"title": "Page", "content": "content"}),
        (CreateTaskInput, {"title": "Task"}),
    ],
)
def test_tool_schema_rejects_extra_fields(input_type, valid_payload: dict) -> None:
    with pytest.raises(ValidationError):
        input_type.model_validate({**valid_payload, "unexpected": "value"})
