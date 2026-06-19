from __future__ import annotations

from typing import Any

from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.memory_policy import evaluate_memory_content

from ..events import AgentActionEvent
from ..events_helpers import _agent_state, _emit_tool_results, _events, _record_node_error
from ..retrieval.router import _automation_enabled
from ..runtime_helpers import _strip_memory_command, _strip_wiki_command, _task_title, _wiki_title
from ..services import AgentRuntimeServices
from ..state import ActionPlan, AgentState
from ..tools import DEFAULT_MEMORY_TARGET_PATH, AgentToolResult, AgentToolSet, SensitiveMemoryRejectedError
from .wiki import _fallback_manage_wiki, _fallback_plan_wiki, _wiki_proposal_kind


async def _action_planner_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        action_type = _action_type(state)
        if action_type == "task":
            plan = _task_plan(state)
        elif action_type == "wiki":
            plan = _wiki_plan(state, services)
        else:
            plan = _memory_plan(state, services)
        state.action_plan = plan
        state.response_text = plan.confirm_text
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


async def _execute_action_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    state = _agent_state(graph_state)
    plan = state.action_plan
    if plan is None or plan.executed:
        return graph_state
    try:
        if plan.action_type == "task":
            await _execute_task_plan(graph_state, services, state, plan)
        elif plan.action_type == "memory_proposal":
            await _execute_memory_plan(graph_state, services, state, plan)
        elif plan.action_type == "wiki":
            await _execute_wiki_plan(graph_state, services, state, plan)
        plan.executed = True
        return graph_state
    except Exception as exc:
        plan.status = "failed"
        _record_planned_action(
            graph_state,
            services,
            state,
            action_type=f"{plan.action_type}.failed",
            title="动作执行失败",
            summary=str(exc),
            plan=plan,
            status="failed",
            metadata={"error": str(exc)},
        )
        return graph_state


def _action_type(state: AgentState) -> str:
    classifier = state.classifier
    if classifier is not None and classifier.action_type:
        return classifier.action_type
    if state.route is not None:
        if state.route.intent.value == "create_task":
            return "task"
        if state.route.intent.value == "manage_wiki":
            return "wiki"
    return "memory_proposal"


def _action_params(state: AgentState) -> dict[str, Any]:
    if state.classifier is None:
        return {}
    return dict(state.classifier.action_params)


def _task_plan(state: AgentState) -> ActionPlan:
    params = _action_params(state)
    title = str(params.get("title") or _task_title(state.user_message)).strip() or state.user_message.strip()
    payload = {
        "title": title,
        "description": str(params.get("description") or ""),
        "due_at": _optional_text(params.get("due_at")),
        "remind_at": _optional_text(params.get("remind_at")),
        "timezone": _optional_text(params.get("timezone")),
        "source_text": state.user_message,
    }
    decision = AutomationPolicy().decide("task.create", reversible=False)
    return ActionPlan(
        action_type="task",
        payload=payload,
        risk_score=decision.risk_tier,
        decision=decision.decision,
        confirm_text=f"好，我先把它整理成一个本地提醒：{title}",
        reversible=decision.reversible,
    )


def _memory_plan(state: AgentState, services: AgentRuntimeServices) -> ActionPlan:
    params = _action_params(state)
    raw_content = params.get("content")
    content = str(raw_content or _strip_memory_command(state.user_message)).strip()
    if content == state.user_message.strip():
        content = _strip_memory_command(content)
    policy = evaluate_memory_content(content)
    if not policy.allowed:
        raise SensitiveMemoryRejectedError(policy.reason)
    payload = {
        "content": content,
        "target_path": str(params.get("target_path") or DEFAULT_MEMORY_TARGET_PATH),
        "source_message_id": state.message_id,
        "auto_long_term_memory": _automation_enabled(services, "auto_long_term_memory"),
    }
    decision = AutomationPolicy().decide("memory.proposal", confidence=state.route.confidence if state.route else None)
    confirm_text = (
        "我会把这条放进后台长期记忆整理流程；如果策略判断风险高，会先向你确认。"
        if payload["auto_long_term_memory"]
        else "我会先创建一条待确认的长期记忆提案。"
    )
    return ActionPlan(
        action_type="memory_proposal",
        payload=payload,
        risk_score=decision.risk_tier,
        decision=decision.decision,
        confirm_text=confirm_text,
        reversible=decision.reversible,
    )


def _wiki_plan(state: AgentState, services: AgentRuntimeServices) -> ActionPlan:
    params = _action_params(state)
    content = str(params.get("content") or _strip_wiki_command(state.user_message)).strip() or state.user_message
    title = str(params.get("title") or _wiki_title(state.user_message)).strip() or "Knowledge Note"
    kind = str(params.get("kind") or _wiki_proposal_kind(state.user_message))
    auto_organize = _automation_enabled(services, "auto_wiki_organize")
    action_type = f"wiki.{kind}.{'write' if auto_organize else 'plan'}"
    decision = AutomationPolicy().decide(action_type, reversible=auto_organize)
    if not auto_organize:
        decision = decision.__class__(
            action_type=decision.action_type,
            risk_tier="medium",
            decision="ask",
            reversible=False,
            reason="wiki_auto_organize_disabled",
        )
    return ActionPlan(
        action_type="wiki",
        payload={
            "kind": kind,
            "title": title,
            "content": content,
            "auto_organize": auto_organize,
        },
        risk_score=decision.risk_tier,
        decision=decision.decision,
        confirm_text=(
            f"好，我会把这段整理到 Wiki：{title}"
            if auto_organize
            else f"我会先准备一份需要你确认的 Wiki 整理计划：{title}"
        ),
        reversible=decision.reversible,
    )


async def _execute_task_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    plan: ActionPlan,
) -> None:
    if plan.decision == "ask":
        plan.status = "pending_confirm"
        _record_planned_action(
            graph_state,
            services,
            state,
            action_type="task.create",
            title=f"待确认本地提醒：{plan.payload.get('title', '')}",
            summary=state.user_message,
            plan=plan,
            status="pending_confirm",
        )
        return

    tool_results: list[AgentToolResult] = []
    toolset = AgentToolSet(tasks=services.tasks, observer=tool_results.append)
    response = await toolset.create_task(
        title=str(plan.payload.get("title") or state.user_message),
        description=str(plan.payload.get("description") or ""),
        due_at=_optional_text(plan.payload.get("due_at")),
        remind_at=_optional_text(plan.payload.get("remind_at")),
        timezone=_optional_text(plan.payload.get("timezone")),
        source_text=str(plan.payload.get("source_text") or state.user_message),
    )
    _emit_tool_results(graph_state, tool_results)
    plan.status = "executed"
    _record_planned_action(
        graph_state,
        services,
        state,
        action_type="task.create",
        title=f"已创建本地提醒：{response.metadata.get('title') or plan.payload.get('title')}",
        summary=state.user_message,
        plan=plan,
        status="completed",
        metadata={
            "task_id": response.task_id,
            "reminder_id": response.reminder_id,
            "reminder_status": response.metadata.get("reminder_status", ""),
        },
    )


async def _execute_memory_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    plan: ActionPlan,
) -> None:
    if bool(plan.payload.get("auto_long_term_memory")):
        plan.status = "executed"
        _record_planned_action(
            graph_state,
            services,
            state,
            action_type="memory.proposal.defer",
            title="已进入后台长期记忆整理",
            summary=str(plan.payload.get("content") or ""),
            plan=plan,
            status="completed",
            metadata={"target_path": plan.payload.get("target_path"), "mode": "auto_background"},
        )
        return

    tool_results: list[AgentToolResult] = []
    toolset = AgentToolSet(memory=services.memory, observer=tool_results.append)
    response = await toolset.propose_memory(
        content=str(plan.payload.get("content") or ""),
        target_path=str(plan.payload.get("target_path") or DEFAULT_MEMORY_TARGET_PATH),
        source_message_id=state.message_id,
    )
    _emit_tool_results(graph_state, tool_results)
    plan.status = "pending_confirm"
    _record_planned_action(
        graph_state,
        services,
        state,
        action_type="memory.proposal",
        title="已创建待确认长期记忆提案",
        summary=str(plan.payload.get("content") or ""),
        plan=plan,
        status="pending_confirm",
        metadata={"proposal_id": response.proposal_id, "target_path": plan.payload.get("target_path")},
    )


async def _execute_wiki_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    plan: ActionPlan,
) -> None:
    auto_organize = bool(plan.payload.get("auto_organize"))
    if auto_organize and plan.decision != "ask":
        _, tool_results = await _fallback_manage_wiki(services, state, auto_organize=True)
        _emit_tool_results(graph_state, tool_results)
        plan.status = "executed"
        return

    _, tool_results = await _fallback_plan_wiki(services, state)
    _emit_tool_results(graph_state, tool_results)
    plan.status = "pending_confirm"
    _record_planned_action(
        graph_state,
        services,
        state,
        action_type=f"wiki.{plan.payload.get('kind', 'ingest')}.plan",
        title=f"已准备 Wiki 整理计划：{plan.payload.get('title', '')}",
        summary=str(plan.payload.get("content") or ""),
        plan=plan,
        status="pending_confirm",
        metadata={"kind": plan.payload.get("kind")},
    )


def _record_planned_action(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    *,
    action_type: str,
    title: str,
    summary: str,
    plan: ActionPlan,
    status: str,
    metadata: dict[str, object] | None = None,
) -> None:
    recorder = services.agent_action_recorder
    if recorder is None:
        return
    action = recorder(
        AgentActionCreate(
            action_type=action_type,
            title=title,
            summary=summary,
            source_agent_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            source_message_id=state.message_id,
            risk_tier=plan.risk_score,
            decision=plan.decision,
            status=status,
            metadata={
                "action_payload": plan.payload,
                "confirm_text": plan.confirm_text,
                **(metadata or {}),
            },
            reversible=plan.reversible,
        )
    )
    _events(graph_state).append(
        AgentActionEvent(
            agent_run_id=state.agent_run_id,
            action_id=action.action_id,
            source_agent_run_id=action.source_agent_run_id,
            source_conversation_id=action.source_conversation_id,
            source_message_id=action.source_message_id,
            action_type=action.action_type,
            risk_tier=action.risk_tier,
            decision=action.decision,
            status=action.status,
            title=action.title,
            summary=action.summary,
            target_paths=action.target_paths,
            reversible=action.reversible,
            reverted_by=action.reverted_by,
            reverts_action_id=action.reverts_action_id,
            error=action.error,
            source=action.source,
            diff_summary=action.diff_summary,
            requires_confirmation=action.decision == "ask",
            metadata=action.metadata,
            created_at=action.created_at,
            updated_at=action.updated_at,
            completed_at=action.completed_at,
        )
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
