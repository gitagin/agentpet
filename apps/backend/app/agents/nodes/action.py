from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.agent_actions import AgentActionCreate, AutomationPolicy
from app.services.memory_policy import evaluate_memory_content

from ..contracts import ActionProposal, PolicyDecision
from ..events import AgentActionEvent
from ..events_helpers import _agent_state, _emit_tool_results, _events, _record_node_error
from ..intent import is_high_risk_mutation_request, route_intent
from ..retrieval.router import _automation_enabled
from ..runtime_helpers import _strip_memory_command, _strip_wiki_command, _task_title, _wiki_title
from ..services import AgentRuntimeServices
from ..state import ActionPlan, AgentState
from ..tools import DEFAULT_MEMORY_TARGET_PATH, AgentToolResult, AgentToolSet, SensitiveMemoryRejectedError
from .wiki import _fallback_manage_wiki, _fallback_plan_wiki, _wiki_proposal_kind
from .policy_guard import evaluate_action_proposal


async def _action_planner_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        plans = _build_action_plans(state, services)
        proposals: list[ActionProposal] = []
        policies: list[PolicyDecision] = []
        for index, plan in enumerate(plans):
            proposal = _proposal_for_plan(state, plan, index=index)
            policy = evaluate_action_proposal(proposal)
            proposal = proposal.model_copy(
                update={
                    "normalized_target": policy.normalized_target,
                    "idempotency_key": policy.idempotency_key,
                }
            )
            plan.proposal_id = proposal.proposal_id
            plan.policy_version = policy.policy_version
            plan.idempotency_key = policy.idempotency_key
            plan.control_state = "policy_checked"
            plan.risk_score = policy.risk_tier
            plan.decision = "auto" if policy.decision == "approved" else "ask"
            if policy.decision == "pending_confirmation":
                plan.status = "pending_confirm"
                plan.control_state = "pending_confirmation"
            elif policy.decision == "denied":
                plan.status = "skipped"
                plan.control_state = "denied"
            else:
                plan.control_state = "approved"
            proposals.append(proposal)
            policies.append(policy)
        state.action_plans = plans
        state.action_plan = plans[0]
        state.action_proposals = proposals
        state.policy_decisions = policies
        state.response_text = _action_response_text(plans)
        _persist_pending_checkpoint(state, proposals, policies, plans, services)
        if len(plans) > 1 or plans[0].action_type == "confirmation":
            graph_state["deterministic_action_response"] = True
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


def _persist_pending_checkpoint(
    state: AgentState,
    proposals: list[ActionProposal],
    policies: list[PolicyDecision],
    plans: list[ActionPlan],
    services: AgentRuntimeServices,
) -> None:
    if services.checkpoint_store is None or state.checkpoint_id is not None:
        return
    pending_index = next(
        (index for index, policy in enumerate(policies) if policy.decision == "pending_confirmation"),
        None,
    )
    if pending_index is None:
        return
    plan = plans[pending_index]
    proposal = proposals[pending_index]
    policy = policies[pending_index]
    checkpoint_id = f"checkpoint-{state.agent_run_id}-{proposal.proposal_id}"
    now = datetime.now(timezone.utc)
    decision_id = secrets.token_urlsafe(24)
    decision_expires_at = now + timedelta(minutes=15)
    services.checkpoint_store.save_pending(
        checkpoint_id=checkpoint_id,
        thread_id=state.conversation_id,
        run_id=state.agent_run_id,
        graph_version="agent-graph-v1",
        state_version="agent-state-v1",
        node_name="action_agent",
        state={
            "conversation_id": state.conversation_id,
            "message_id": state.message_id,
            "agent_run_id": state.agent_run_id,
            "action_plan": plan.model_dump(mode="json"),
            "action_proposal": proposal.model_dump(mode="json"),
            "policy_decision": policy.model_dump(mode="json"),
            "decision_id": decision_id,
            "decision_expires_at": decision_expires_at.isoformat(),
            "action_label": policy.action_type,
            "safe_target_summary": policy.normalized_target,
            "risk_tier": policy.risk_tier,
            "reversible": plan.reversible,
        },
        expires_at=now + timedelta(hours=24),
        action_proposal_id=proposal.proposal_id,
        idempotency_key=policy.idempotency_key,
    )
    state.checkpoint_id = checkpoint_id
    state.checkpoint_status = "pending_confirmation"


async def _execute_action_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    state = _agent_state(graph_state)
    plans = state.action_plans or ([state.action_plan] if state.action_plan is not None else [])
    if not plans:
        return graph_state
    for plan in plans:
        if plan.executed:
            continue
        proposal = next(
            (item for item in state.action_proposals if item.proposal_id == plan.proposal_id),
            None,
        )
        policy = next(
            (item for item in state.policy_decisions if item.proposal_id == plan.proposal_id),
            None,
        )
        if proposal is None or policy is None:
            plan.status = "failed"
            plan.control_state = "failed_recovery"
            continue
        if policy.decision != "approved":
            _record_policy_blocked_plan(graph_state, services, state, plan, policy)
            plan.executed = True
            continue
        if policy.idempotency_key in state.executed_action_keys:
            plan.executed = True
            plan.status = "executed"
            plan.control_state = "completed"
            continue
        plan.control_state = "executing"
        try:
            if plan.action_type == "task":
                await _execute_task_plan(graph_state, services, state, plan)
            elif plan.action_type == "memory_proposal":
                await _execute_memory_plan(graph_state, services, state, plan)
            elif plan.action_type == "wiki":
                await _execute_wiki_plan(graph_state, services, state, plan)
            else:
                await _execute_confirmation_plan(graph_state, services, state, plan)
            plan.executed = True
            state.executed_action_keys.add(policy.idempotency_key)
            plan.control_state = "completed" if plan.status == "executed" else "pending_confirmation"
        except Exception as exc:
            plan.status = "failed"
            plan.control_state = "failed_recovery"
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


def _proposal_for_plan(state: AgentState, plan: ActionPlan, *, index: int) -> ActionProposal:
    action_type = _plan_action_type(plan)
    explicit_intent_ref = f"intent:{state.message_id}:{index}"
    proposal_id = "proposal-" + hashlib.sha256(explicit_intent_ref.encode("utf-8")).hexdigest()[:24]
    target_ref = _plan_target_ref(plan, explicit_intent_ref)
    expected_effect = {
        "task": "Create one local task or reminder.",
        "memory_proposal": "Create one non-executing memory proposal or background handoff.",
        "wiki": "Create one bounded Wiki plan or reversible Wiki update.",
        "confirmation": "Record a pending confirmation without changing the target.",
    }[plan.action_type]
    return ActionProposal(
        proposal_id=proposal_id,
        explicit_intent_ref=explicit_intent_ref,
        action_type=action_type,
        target_ref=target_ref,
        parameters=dict(plan.payload),
        expected_effect=expected_effect,
        reversible=plan.reversible,
        source_message_id=state.message_id,
        requested_confirmation=plan.decision == "ask",
    )


def _plan_action_type(plan: ActionPlan) -> str:
    if plan.action_type == "task":
        return "task.create"
    if plan.action_type == "memory_proposal":
        return "memory.proposal"
    if plan.action_type == "confirmation":
        return "local.destructive_request"
    mode = "write" if bool(plan.payload.get("auto_organize")) else "plan"
    return f"wiki.{plan.payload.get('kind', 'ingest')}.{mode}"


def _plan_target_ref(plan: ActionPlan, fallback: str) -> str:
    if plan.payload.get("target_path"):
        return str(plan.payload["target_path"])
    if plan.action_type == "task":
        return f"task:{str(plan.payload.get('title') or '').casefold()}"[:256]
    if plan.action_type == "wiki":
        return f"wiki-title:{str(plan.payload.get('title') or '').casefold()}"[:256]
    return fallback


def _record_policy_blocked_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    plan: ActionPlan,
    policy: PolicyDecision,
) -> None:
    pending = policy.decision == "pending_confirmation"
    plan.status = "pending_confirm" if pending else "skipped"
    plan.control_state = "pending_confirmation" if pending else "denied"
    _record_planned_action(
        graph_state,
        services,
        state,
        action_type=policy.action_type,
        title="动作等待确认" if pending else "动作已被策略拒绝",
        summary="目标尚未发生任何修改。",
        plan=plan,
        status="pending_confirm" if pending else "denied",
        metadata={
            "policy_version": policy.policy_version,
            "policy_reason": policy.reason_code,
            "idempotency_key": policy.idempotency_key,
            "control_state": plan.control_state,
            "confirmation_digest": policy.confirmation_digest,
        },
    )


def _build_action_plans(state: AgentState, services: AgentRuntimeServices) -> list[ActionPlan]:
    if is_high_risk_mutation_request(state.user_message):
        state.suppress_post_reply_automation = True
        return [_confirmation_plan(state)]

    compound = _split_task_and_memory_request(state.user_message)
    if compound is not None:
        task_text, memory_text = compound
        return [
            _task_plan(state, source_text=task_text),
            _memory_plan(state, services, content=memory_text),
        ]

    action_type = _action_type(state)
    if action_type == "task":
        return [_task_plan(state)]
    if action_type == "wiki":
        return [_wiki_plan(state, services)]
    return [_memory_plan(state, services)]


def _action_response_text(plans: list[ActionPlan]) -> str:
    if len(plans) == 2 and {plan.action_type for plan in plans} == {"task", "memory_proposal"}:
        return "我会同时处理两件事：先创建本地提醒，再按当前策略整理这条偏好。两个结果会分别显示在下方。"
    return plans[0].confirm_text


def _split_task_and_memory_request(message: str) -> tuple[str, str] | None:
    match = re.search(
        r"(?:[,，;；。]?\s*)(?:并且|并)?(?:帮我)?(?:记住|记得)\s*(?:[:：])?\s*(?P<memory>.+)$",
        message.strip(),
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    task_text = message[: match.start()].strip(" ,，;；。")
    memory_text = match.group("memory").strip(" :：,，;；。")
    if not task_text or not memory_text or route_intent(task_text).intent.value != "create_task":
        return None
    return task_text, memory_text


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


def _task_plan(state: AgentState, *, source_text: str | None = None) -> ActionPlan:
    params = _action_params(state)
    task_source = (source_text or state.user_message).strip()
    # A compound request is split deterministically before execution.  Do not
    # let a classifier title derived from the unsplit message pull the memory
    # clause back into the task receipt.
    inferred_title = _task_title(task_source)
    title = str(inferred_title if source_text is not None else params.get("title") or inferred_title).strip() or task_source
    payload = {
        "title": title,
        "description": str(params.get("description") or ""),
        "due_at": _optional_text(params.get("due_at")),
        "remind_at": _optional_text(params.get("remind_at")),
        "timezone": _optional_text(params.get("timezone")),
        "source_text": task_source,
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


def _memory_plan(state: AgentState, services: AgentRuntimeServices, *, content: str | None = None) -> ActionPlan:
    params = _action_params(state)
    raw_content = params.get("content")
    memory_content = str(content or raw_content or _strip_memory_command(state.user_message)).strip()
    if memory_content == state.user_message.strip():
        memory_content = _strip_memory_command(memory_content)
    policy = evaluate_memory_content(memory_content)
    if not policy.allowed:
        raise SensitiveMemoryRejectedError(policy.reason)
    payload = {
        "content": memory_content,
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


def _confirmation_plan(state: AgentState) -> ActionPlan:
    decision = AutomationPolicy().decide("markdown.bulk_rewrite", destructive=True)
    return ActionPlan(
        action_type="confirmation",
        payload={
            "request_summary": state.user_message.strip()[:500],
            "confirmation_only": True,
        },
        risk_score=decision.risk_tier,
        decision=decision.decision,
        status="pending_confirm",
        confirm_text=(
            "这个请求可能删除、移动或批量改写本地内容。我已经停在确认前，没有修改任何目标；"
            "请先核对操作范围，再决定是否继续。"
        ),
        reversible=False,
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


async def _execute_confirmation_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    state: AgentState,
    plan: ActionPlan,
) -> None:
    plan.status = "pending_confirm"
    _record_planned_action(
        graph_state,
        services,
        state,
        action_type="local.destructive_request",
        title="高风险本地操作等待确认",
        summary="请求已拦截，尚未修改任何本地目标。",
        plan=plan,
        status="pending_confirm",
        metadata={"confirmation_only": True},
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
                "proposal_id": plan.proposal_id,
                "policy_version": plan.policy_version,
                "idempotency_key": plan.idempotency_key,
                "control_state": plan.control_state,
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
