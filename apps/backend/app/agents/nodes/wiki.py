from __future__ import annotations

import re
from typing import Any

from app.models.api import QueryArchiveRequest, WikiLintRequest, WikiPageWriteRequest, WikiSynthesizeRequest
from app.models.enums import AgentId
from app.services.wiki import slugify_wiki_title

from ..events import AgentTokenEvent
from ..events_helpers import _agent_state, _emit_tool_results, _events, _record_node_error
from ..prompts.system import _wiki_system_prompt
from ..retrieval.router import _automation_enabled
from ..runtime_helpers import _chunk_text, _strip_wiki_command, _wiki_title
from ..services import AgentRuntimeServices
from ..state import AgentState
from ..tools import AgentToolName, AgentToolResult, AgentToolSet

# 从 graph_runtime.py 迁移，原函数名：_fallback_manage_wiki, _fallback_plan_wiki, _wiki_node, _wiki_proposal_kind, _extract_wiki_paths


async def _fallback_manage_wiki(
    services: AgentRuntimeServices,
    state: AgentState,
    *,
    auto_organize: bool = True,
) -> tuple[str, list[AgentToolResult]]:
    tool_results: list[AgentToolResult] = []
    if not auto_organize:
        return await _fallback_plan_wiki(services, state)

    kind = _wiki_proposal_kind(state.user_message)
    title = _wiki_title(state.user_message)
    content = _strip_wiki_command(state.user_message)
    if kind == "query_archive":
        if services.wiki_workflow is not None and state.citations:
            response = await services.wiki_workflow.archive_query(
                QueryArchiveRequest(
                    question=title,
                    answer=content,
                    citations=state.citations,
                    title=f"查询归档 - {title}",
                    tags=["agent-chat", "query-archive"],
                    agent_run_id=state.agent_run_id,
                    source_message_id=state.message_id,
                    allow_mixed_sources=True,
                )
            )
            tool_results.append(AgentToolResult(name="archive_wiki_query", value=response))
            return f"已自动归档查询回答：{response.page.relative_path}。", tool_results
        if services.wiki is not None:
            target_path = f"Wiki/Reports/{slugify_wiki_title('查询归档 - ' + title)}.md"
            response = await services.wiki.manage_page(
                WikiPageWriteRequest(
                    title=f"查询归档 - {title}",
                    content=content,
                    operation="replace_section",
                    target_path=target_path,
                    section="自动归档",
                    tags=["agent-chat", "query-archive"],
                    source_message_id=state.message_id,
                )
            )
            tool_results.append(AgentToolResult(name="manage_wiki_page", value=response))
            return f"已自动整理到 Wiki 报告：{response.relative_path}。", tool_results
    if kind == "synthesize":
        if services.wiki_workflow is not None:
            response = await services.wiki_workflow.synthesize(
                WikiSynthesizeRequest(
                    title=title,
                    content=content,
                    source_paths=_extract_wiki_paths(content),
                    tags=["agent-chat", "synthesis"],
                    links=[],
                )
            )
            tool_results.append(AgentToolResult(name="synthesize_wiki", value=response))
            return f"已自动写入 Wiki 综合整理：{response.page.relative_path}。", tool_results
    if kind == "lint":
        if services.wiki_workflow is not None:
            response = await services.wiki_workflow.run_lint(WikiLintRequest(write_report=True))
            tool_results.append(AgentToolResult(name="run_wiki_lint", value=response))
            target = response.report_page.relative_path if response.report_page else "只读体检结果"
            return f"已完成 Wiki 体检：{target}。", tool_results

    if services.wiki is not None:
        response = await services.wiki.manage_page(
            WikiPageWriteRequest(
                title=title,
                content=content,
                operation="append",
                tags=["agent-chat", "auto-organized"],
                source_message_id=state.message_id,
            )
        )
        tool_results.append(AgentToolResult(name="manage_wiki_page", value=response))
        return f"已自动整理到 Wiki 页面：{response.relative_path}。", tool_results

    observed_toolset = AgentToolSet(
        wiki_workflow=services.wiki_workflow,
        observer=tool_results.append,
    )
    proposal = await observed_toolset.plan_wiki_ingest(
        title=title,
        content=content,
        tags=["agent-chat", "wiki-proposal"],
        max_pages=5,
        source_message_id=state.message_id,
    )
    targets = proposal.recommended_targets or [plan.target_path for plan in proposal.page_plans]
    return (
        f"已准备 Wiki 整理计划：{proposal.run_id}。"
        f"需要确认的目标 {len(targets)} 个。"
    ), tool_results


async def _fallback_plan_wiki(
    services: AgentRuntimeServices,
    state: AgentState,
) -> tuple[str, list[AgentToolResult]]:
    tool_results: list[AgentToolResult] = []
    if services.wiki_workflow is None:
        return "Vault maintenance is unavailable.", tool_results

    observed_toolset = AgentToolSet(
        wiki_workflow=services.wiki_workflow,
        observer=tool_results.append,
    )
    kind = _wiki_proposal_kind(state.user_message)
    title = _wiki_title(state.user_message)
    content = _strip_wiki_command(state.user_message)
    if kind == "query_archive":
        proposal = await observed_toolset.plan_wiki_query_archive(
            question=title,
            answer=content,
            citations=state.citations,
            title=f"Query archive - {title}",
            tags=["agent-chat", "query-archive"],
            agent_run_id=state.agent_run_id,
            source_message_id=state.message_id,
            allow_mixed_sources=True,
        )
        return f"Prepared Wiki query archive plan: {proposal.target_path}.", tool_results
    if kind == "synthesize":
        proposal = await observed_toolset.plan_wiki_synthesis(
            title=title,
            content=content,
            source_paths=_extract_wiki_paths(content),
            tags=["agent-chat", "synthesis"],
            source_message_id=state.message_id,
        )
        return f"Prepared Wiki synthesis plan: {proposal.target_path}.", tool_results
    if kind == "lint":
        proposal = await observed_toolset.plan_wiki_lint(
            write_report=True,
            source_message_id=state.message_id,
        )
        target = proposal.target_path or "read-only lint"
        return f"Prepared Wiki lint plan: {target}.", tool_results

    proposal = await observed_toolset.plan_wiki_ingest(
        title=title,
        content=content,
        tags=["agent-chat", "wiki-proposal"],
        max_pages=5,
        source_message_id=state.message_id,
    )
    targets = proposal.recommended_targets or [plan.target_path for plan in proposal.page_plans]
    return (
        f"Prepared a confirmation-required Wiki organization plan: {proposal.run_id}. "
        f"Targets: {len(targets)}."
    ), tool_results


async def _wiki_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    run_model_agent_with_tools,
    has_wiki_action_result,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        auto_organize = _automation_enabled(services, "auto_wiki_organize")
        chat_model = _model_for_wiki(services)
        if chat_model is not None:
            wiki_tools = (
                (AgentToolName.MANAGE_WIKI,)
                if auto_organize
                else (
                    AgentToolName.PLAN_WIKI_INGEST,
                    AgentToolName.PLAN_WIKI_QUERY_ARCHIVE,
                    AgentToolName.PLAN_WIKI_SYNTHESIS,
                    AgentToolName.PLAN_WIKI_LINT,
                )
            )
            response, tool_results = await run_model_agent_with_tools(
                agent_id=AgentId.ACTION_AGENT,
                state=state,
                tools=wiki_tools,
                system_prompt=_wiki_system_prompt(auto_organize=auto_organize),
            )
            _emit_tool_results(graph_state, tool_results)
            if not has_wiki_action_result(tool_results):
                fallback_response, fallback_results = await _fallback_manage_wiki(
                    services,
                    state,
                    auto_organize=auto_organize,
                )
                _emit_tool_results(graph_state, fallback_results)
                response = fallback_response
            state.response_text = response
            for chunk in _chunk_text(response):
                _events(graph_state).append(
                    AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                )
            return graph_state

        response, tool_results = await _fallback_manage_wiki(
            services,
            state,
            auto_organize=auto_organize,
        )
        _emit_tool_results(graph_state, tool_results)
        state.response_text = response
        _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=response))
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


def _wiki_proposal_kind(message: str) -> str:
    normalized = message.casefold()
    if any(
        marker in normalized
        for marker in (
            "query archive",
            "archive query",
            "archive answer",
            "归档回答",
            "归档查询",
            "查询归档",
        )
    ):
        return "query_archive"
    if any(
        marker in normalized
        for marker in (
            "synthesize",
            "synthesis",
            "综合整理",
            "综合成",
            "整合成",
            "整理综合",
        )
    ):
        return "synthesize"
    if any(
        marker in normalized
        for marker in (
            "wiki lint",
            "lint report",
            "lint wiki",
            "wiki health",
            "检查 wiki",
            "wiki 检查",
            "wiki 体检",
            "质量报告",
        )
    ):
        return "lint"
    return "ingest"


def _extract_wiki_paths(text: str) -> list[str]:
    paths = re.findall(r"Wiki/[A-Za-z0-9_./\-一-鿿 ]+\.md", text)
    seen: set[str] = set()
    result: list[str] = []
    for path in paths:
        normalized = path.strip().replace("\\", "/")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:10]


def _model_for_wiki(services: AgentRuntimeServices):
    if services.model_registry is not None:
        return services.model_registry.get(AgentId.ACTION_AGENT)
    return None
