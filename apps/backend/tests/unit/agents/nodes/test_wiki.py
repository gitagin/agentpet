from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.agents.events import AgentActionEvent, AgentErrorEvent, AgentTokenEvent, AgentWikiProposalEvent
from app.agents.nodes.wiki import _fallback_manage_wiki, _fallback_plan_wiki, _wiki_node
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState
from app.agents.tools import AgentToolResult
from app.models.api import (
    QueryArchiveLintResponse,
    WikiIngestPagePlan,
    WikiIngestPreviewResponse,
    WikiIngestReviewResponse,
    WikiPageResponse,
    WikiQueryArchiveProposal,
)


def _state(message: str = "整理 Wiki 页面：苹果偏好") -> AgentState:
    return AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message=message,
    )


def _graph_state(message: str = "整理 Wiki 页面：苹果偏好") -> dict:
    return {"agent_state": _state(message), "events": []}


class WikiService:
    def __init__(self) -> None:
        self.manage_page = AsyncMock(
            return_value=WikiPageResponse(
                title="苹果偏好",
                relative_path="Wiki/apple.md",
                operation="append",
                status="updated",
                action_id="action-1",
            )
        )


class WikiWorkflow:
    def __init__(self) -> None:
        self.preview_ingest = AsyncMock(
            return_value=WikiIngestPreviewResponse(
                run_id="run-wiki-1",
                source_id="source-1",
                source_hash="hash-1",
                status="planned",
                page_plans=[WikiIngestPagePlan(title="苹果偏好", target_path="Wiki/apple.md", content="苹果")],
                summary="1 page",
            )
        )
        self.review_ingest = AsyncMock(
            return_value=WikiIngestReviewResponse(
                review_id="review-1",
                run_id="run-wiki-1",
                status="reviewed",
                summary="ok",
                recommended_targets=["Wiki/apple.md"],
            )
        )
        self.plan_query_archive = AsyncMock(
            return_value=WikiQueryArchiveProposal(
                status="planned",
                title="Query archive - test",
                target_path="Wiki/Reports/test.md",
                lint=QueryArchiveLintResponse(passed=True),
            )
        )


class Registry:
    def __init__(self, model: object = object()) -> None:
        self.model = model

    def get(self, _agent_id):
        return self.model


def _has_wiki_action_result(results) -> bool:
    return any(result.name in {"manage_wiki_page", "plan_wiki_ingest", "plan_wiki_query_archive"} for result in results)


@pytest.mark.asyncio
async def test_wiki_node_writes_page_on_happy_path() -> None:
    graph_state = _graph_state()
    wiki = WikiService()

    result = await _wiki_node(
        graph_state,
        AgentRuntimeServices(wiki=wiki),
        AsyncMock(),
        _has_wiki_action_result,
    )

    assert result["agent_state"].response_text == "已自动整理到 Wiki 页面：Wiki/apple.md。"
    assert any(isinstance(event, AgentActionEvent) for event in result["events"])
    assert any(isinstance(event, AgentTokenEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_wiki_node_returns_empty_when_model_returns_empty_result() -> None:
    graph_state = _graph_state()
    wiki = WikiService()
    run_model_agent_with_tools = AsyncMock(return_value=("", []))

    result = await _wiki_node(
        graph_state,
        AgentRuntimeServices(wiki=wiki, model_registry=Registry()),
        run_model_agent_with_tools,
        _has_wiki_action_result,
    )

    assert result["agent_state"].response_text == "已自动整理到 Wiki 页面：Wiki/apple.md。"
    assert any(isinstance(event, AgentActionEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_wiki_node_handles_invalid_json_from_model() -> None:
    graph_state = _graph_state()
    page = WikiPageResponse(
        title="苹果偏好",
        relative_path="Wiki/apple.md",
        operation="append",
        status="updated",
        action_id="action-2",
    )
    run_model_agent_with_tools = AsyncMock(
        return_value=("{not-json", [AgentToolResult(name="manage_wiki_page", value=page)])
    )

    result = await _wiki_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry()),
        run_model_agent_with_tools,
        _has_wiki_action_result,
    )

    assert result["agent_state"].response_text == "{not-json"
    assert any(isinstance(event, AgentActionEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_wiki_node_returns_empty_when_model_times_out() -> None:
    graph_state = _graph_state()
    run_model_agent_with_tools = AsyncMock(side_effect=TimeoutError("model timed out"))

    result = await _wiki_node(
        graph_state,
        AgentRuntimeServices(model_registry=Registry()),
        run_model_agent_with_tools,
        _has_wiki_action_result,
    )

    assert result["failed"] is True
    assert result["agent_state"].error_code == "TimeoutError"
    assert any(isinstance(event, AgentErrorEvent) for event in result["events"])


@pytest.mark.asyncio
async def test_fallback_plan_wiki_creates_query_archive_plan() -> None:
    workflow = WikiWorkflow()

    response, tool_results = await _fallback_plan_wiki(
        AgentRuntimeServices(wiki_workflow=workflow),
        _state("请归档查询回答：测试回答"),
    )

    assert response == "Prepared Wiki query archive plan: Wiki/Reports/test.md."
    assert tool_results[0].name == "plan_wiki_query_archive"


@pytest.mark.asyncio
async def test_fallback_manage_wiki_records_workflow_exception() -> None:
    workflow = WikiWorkflow()
    workflow.preview_ingest.side_effect = RuntimeError("workflow unavailable")

    with pytest.raises(RuntimeError):
        await _fallback_manage_wiki(AgentRuntimeServices(wiki_workflow=workflow), _state())


@pytest.mark.asyncio
async def test_wiki_node_emits_confirmation_plan_when_auto_organize_is_disabled() -> None:
    graph_state = _graph_state()
    workflow = WikiWorkflow()
    automation = type("Automation", (), {"auto_wiki_organize": False})()

    result = await _wiki_node(
        graph_state,
        AgentRuntimeServices(wiki_workflow=workflow, automation_settings=automation),
        AsyncMock(),
        _has_wiki_action_result,
    )

    assert "Prepared a confirmation-required Wiki organization plan" in result["agent_state"].response_text
    assert any(isinstance(event, AgentWikiProposalEvent) for event in result["events"])
