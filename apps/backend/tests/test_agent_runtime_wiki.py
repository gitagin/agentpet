from __future__ import annotations

import asyncio

from tests.agent_runtime_fakes import (
    FakeRegistryChatModel,
    FakeWiki,
    FakeWikiWorkflow,
    _citation_payload,
    assert_langgraph_events,
    first_event,
    make_state,
)

from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.models.api import AutomationSettingsResponse, MemorySearchResult
from app.services.chat_model import AgentId, AgentModelRegistry


def test_langgraph_wiki_manager_archives_query_by_default() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel(None, "model skipped wiki tool")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
            )
        )
        state = make_state("archive to wiki query archive: Runtime answer")
        state.citations = [MemorySearchResult.model_validate(_citation_payload("Wiki/Runtime.md"))]

        events = [event async for event in runtime.run(state)]
        return wiki, wiki_workflow, wiki_model, events

    wiki, wiki_workflow, wiki_model, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_model.calls[0][2] == ["manage_wiki_page"]
    assert wiki_workflow.query_archive_requests[0].answer == "Runtime answer"
    assert_langgraph_events(events, ["agent_action", "token", "done"])
    action = first_event(events, "agent_action")
    assert action.action_type == "wiki.query_archive.write"
    assert action.target_paths == ["Wiki/Reports/Runtime-Answer.md"]


def test_langgraph_wiki_manager_synthesizes_by_default() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel(None, "model skipped wiki tool")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
            )
        )

        events = [event async for event in runtime.run(make_state("add to wiki synthesis: Runtime synthesis"))]
        return wiki, wiki_workflow, events

    wiki, wiki_workflow, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_workflow.synthesis_requests[0].title == "Runtime synthesis"
    assert_langgraph_events(events, ["agent_action", "token", "done"])
    action = first_event(events, "agent_action")
    assert action.action_type == "wiki.synthesize.write"
    assert action.target_paths == ["Wiki/Syntheses/Runtime-Synthesis.md"]


def test_langgraph_wiki_manager_runs_lint_report_by_default() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel(None, "model skipped wiki tool")
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
    assert_langgraph_events(events, ["agent_action", "token", "done"])
    action = first_event(events, "agent_action")
    assert action.action_type == "wiki.lint.report"
    assert action.target_paths == ["Wiki/Reports/Lint-2026-05-11.md"]


def test_langgraph_wiki_manager_falls_back_to_proposal_flow_when_auto_organize_disabled() -> None:
    async def run_case():
        wiki = FakeWiki()
        wiki_workflow = FakeWikiWorkflow()
        wiki_model = FakeRegistryChatModel(None, "model skipped wiki tool")
        runtime = LangGraphAgentRuntime(
            AgentRuntimeServices(
                wiki=wiki,
                wiki_workflow=wiki_workflow,
                model_registry=AgentModelRegistry({AgentId.WIKI_MANAGER_AGENT: wiki_model}),
                automation_settings=AutomationSettingsResponse(auto_wiki_organize=False),
            )
        )
        state = make_state("archive to wiki query archive: Runtime answer")
        state.citations = [MemorySearchResult.model_validate(_citation_payload("Wiki/Runtime.md"))]

        events = [event async for event in runtime.run(state)]
        return wiki, wiki_workflow, wiki_model, events

    wiki, wiki_workflow, wiki_model, events = asyncio.run(run_case())

    assert wiki.requests == []
    assert wiki_model.calls[0][2] == ["plan_wiki_ingest", "plan_wiki_query_archive", "plan_wiki_synthesis", "plan_wiki_lint"]
    assert wiki_workflow.query_archive_requests[0].answer == "Runtime answer"
    assert_langgraph_events(events, ["wiki_proposal", "token", "done"])
    proposal = first_event(events, "wiki_proposal")
    assert proposal.proposal_type == "query_archive"
    assert proposal.target_paths == ["Wiki/Reports/Runtime-Answer.md"]
