from __future__ import annotations

from typing import Any

from app.models.api import (
    MemoryProposalActionResponse,
    MemorySearchResponse,
    QueryArchiveResponse,
    TaskCreateResponse,
    WikiLintProposal,
    WikiLintReportResponse,
    WikiPageResponse,
    WikiQueryArchiveProposal,
    WikiSynthesisProposal,
    WikiSynthesizeResponse,
)
from app.models.enums import AgentRunStatus
from app.services.memory_permissions import ensure_recall_permissions

from .events import (
    AgentActionEvent,
    AgentCitationEvent,
    AgentErrorEvent,
    AgentEventBase,
    AgentMemoryProposalEvent,
    AgentStatusEvent,
    AgentTaskEvent,
    AgentWikiProposalEvent,
)
from .state import AgentState
from .tools import DEFAULT_MEMORY_TARGET_PATH, AgentToolResult, WikiIngestProposal

# 从 graph_runtime.py 迁移，原函数名：_agent_state, _events, _append_status, _emit_tool_results, _append_agent_action_event, _wiki_proposal_event, _record_node_error


def _agent_state(graph_state: dict[str, Any]) -> AgentState:
    return graph_state["agent_state"]


def _events(graph_state: dict[str, Any]) -> list[AgentEventBase]:
    return graph_state["events"]


def _append_status(
    graph_state: dict[str, Any],
    message: str,
    *,
    stage: str | None = None,
    source_scopes: list[str] | tuple[str, ...] | None = None,
) -> None:
    state = _agent_state(graph_state)
    _events(graph_state).append(
        AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=state.route.intent if state.route else None,
            message=message,
            stage=stage,
            source_scopes=list(source_scopes or ()),
        )
    )


def _emit_tool_results(graph_state: dict[str, Any], results: list[AgentToolResult]) -> None:
    state = _agent_state(graph_state)
    for result in results:
        value = result.value
        if result.name == "search_memory" and isinstance(value, MemorySearchResponse):
            citations = [ensure_recall_permissions(citation) for citation in value.results]
            state.citations = [*state.citations, *citations]
            for citation in citations:
                _events(graph_state).append(
                    AgentCitationEvent(agent_run_id=state.agent_run_id, citation=citation)
                )
        elif result.name == "propose_memory" and isinstance(value, MemoryProposalActionResponse):
            state.proposal_id = value.proposal_id
            _events(graph_state).append(
                AgentMemoryProposalEvent(
                    agent_run_id=state.agent_run_id,
                    proposal_id=value.proposal_id,
                    status=value.status,
                    target_path=DEFAULT_MEMORY_TARGET_PATH,
                )
            )
        elif result.name == "create_task" and isinstance(value, TaskCreateResponse):
            state.task_id = value.task_id
            state.reminder_id = value.reminder_id
            _events(graph_state).append(
                AgentTaskEvent(
                    agent_run_id=state.agent_run_id,
                    task_id=value.task_id,
                    status=value.status,
                    reminder_id=value.reminder_id,
                    title=value.metadata.get("title") or None,
                    reminder_status=value.metadata.get("reminder_status") or None,
                    remind_at=value.metadata.get("remind_at") or None,
                    timezone=value.metadata.get("timezone") or None,
                    timezone_label=value.metadata.get("timezone_label") or None,
                )
            )
        elif result.name == "plan_wiki_ingest" and isinstance(value, WikiIngestProposal):
            state.proposal_id = value.run_id
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_query_archive" and isinstance(value, WikiQueryArchiveProposal):
            state.proposal_id = value.target_path
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_synthesis" and isinstance(value, WikiSynthesisProposal):
            state.proposal_id = value.target_path
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "plan_wiki_lint" and isinstance(value, WikiLintProposal):
            state.proposal_id = value.target_path or "wiki-lint"
            _events(graph_state).append(_wiki_proposal_event(state, value))
        elif result.name == "manage_wiki_page" and isinstance(value, WikiPageResponse):
            state.response_text = state.response_text or f"Wiki 页面已更新：{value.relative_path}"
            _append_agent_action_event(
                graph_state,
                action_id=value.action_id,
                action_type="wiki.page.write",
                status=value.status,
                title=f"已整理 Wiki 页面：{value.title}",
                summary=f"{value.operation} -> {value.relative_path}",
                target_paths=[value.relative_path],
                reversible=bool(value.action_id),
            )
        elif result.name == "archive_wiki_query" and isinstance(value, QueryArchiveResponse):
            state.response_text = state.response_text or f"查询回答已归档：{value.page.relative_path}"
            _append_agent_action_event(
                graph_state,
                action_id=value.action_id,
                action_type="wiki.query_archive.write",
                status=value.page.status,
                title=f"已归档查询：{value.page.title}",
                summary=f"写入 {value.page.relative_path}",
                target_paths=[value.page.relative_path],
                reversible=bool(value.action_id),
            )
        elif result.name == "synthesize_wiki" and isinstance(value, WikiSynthesizeResponse):
            state.response_text = state.response_text or f"Wiki 综合整理已写入：{value.page.relative_path}"
            _append_agent_action_event(
                graph_state,
                action_id=value.action_id,
                action_type="wiki.synthesize.write",
                status=value.page.status,
                title=f"已综合整理：{value.page.title}",
                summary=f"写入 {value.page.relative_path}",
                target_paths=[value.page.relative_path],
                reversible=bool(value.action_id),
            )
        elif result.name == "run_wiki_lint" and isinstance(value, WikiLintReportResponse):
            target_paths = [value.report_page.relative_path] if value.report_page else []
            _append_agent_action_event(
                graph_state,
                action_id=value.action_id,
                action_type="wiki.lint.report",
                status="completed",
                title="已完成 Wiki 体检",
                summary=f"问题 {value.summary.get('issues', 0)} 个，错误 {value.summary.get('errors', 0)} 个。",
                target_paths=target_paths,
                reversible=bool(value.action_id),
            )


def _append_agent_action_event(
    graph_state: dict[str, Any],
    *,
    action_id: str | None,
    action_type: str,
    status: str,
    title: str,
    summary: str,
    target_paths: list[str],
    reversible: bool,
) -> None:
    if not action_id:
        return
    state = _agent_state(graph_state)
    _events(graph_state).append(
        AgentActionEvent(
            agent_run_id=state.agent_run_id,
            action_id=action_id,
            action_type=action_type,
            risk_tier="low",
            decision="auto",
            status=status,
            title=title,
            summary=summary,
            target_paths=target_paths,
            reversible=reversible,
            requires_confirmation=False,
        )
    )


def _wiki_proposal_event(
    state: AgentState,
    proposal: WikiIngestProposal | WikiQueryArchiveProposal | WikiSynthesisProposal | WikiLintProposal,
) -> AgentWikiProposalEvent:
    if isinstance(proposal, WikiQueryArchiveProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="query_archive",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path],
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
            errors=proposal.lint.errors,
            warnings=proposal.lint.warnings,
            findings=[
                {
                    "severity": "error",
                    "code": error,
                    "message": error,
                    "target_path": proposal.target_path,
                }
                for error in proposal.lint.errors
            ],
        )
    if isinstance(proposal, WikiSynthesisProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="synthesize",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path],
            recommended_targets=[proposal.target_path],
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
        )
    if isinstance(proposal, WikiLintProposal):
        return AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type="lint",
            status=proposal.status,
            title=proposal.title,
            target_paths=[proposal.target_path] if proposal.target_path else [],
            recommended_targets=[proposal.target_path] if proposal.target_path else [],
            findings=[issue.model_dump(mode="json") for issue in proposal.issues],
            lint_summary=proposal.summary,
            write_report=proposal.write_report,
            markdown_preview=proposal.markdown_preview,
            source_message_id=proposal.source_message_id,
        )
    return AgentWikiProposalEvent(
        agent_run_id=state.agent_run_id,
        proposal_type="ingest",
        status=proposal.status,
        title=proposal.title,
        run_id=proposal.run_id,
        source_id=proposal.source_id,
        source_hash=proposal.source_hash,
        review_id=proposal.review_id,
        review_status=proposal.review_status,
        summary=proposal.summary,
        review_summary=proposal.review_summary,
        target_paths=[plan.target_path for plan in proposal.page_plans],
        recommended_targets=proposal.recommended_targets,
        findings=[finding.model_dump(mode="json") for finding in proposal.review_findings],
        source_message_id=proposal.source_message_id,
    )


def _record_node_error(graph_state: dict[str, Any], exc: Exception) -> dict[str, Any]:
    state = _agent_state(graph_state)
    graph_state["failed"] = True
    state.status = AgentRunStatus.FAILED
    state.error_code = getattr(exc, "code", exc.__class__.__name__)
    state.error_message = str(exc)
    _events(graph_state).append(
        AgentErrorEvent(
            agent_run_id=state.agent_run_id,
            code=state.error_code,
            message=state.error_message,
        )
    )
    return graph_state
