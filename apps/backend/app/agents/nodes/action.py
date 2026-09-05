from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, cast

from app.services.agent_actions import AutomationPolicy
from app.services.memory_policy import evaluate_memory_content

from ..contracts import ActionProposal, PolicyDecision
from ..events import AgentActionEvent, AgentMemoryProposalEvent, AgentTaskEvent, AgentWikiProposalEvent
from ..events_helpers import _agent_state, _events, _record_node_error
from ..exceptions import ActionLifecycleUnavailableError
from ..intent import is_high_risk_mutation_request, route_intent
from ..retrieval.router import _automation_enabled
from ..runtime_helpers import _strip_memory_command, _strip_wiki_command, _task_title, _wiki_title
from ..services import AgentRuntimeServices
from ..state import ActionPlan, AgentState
from ..tools import DEFAULT_MEMORY_TARGET_PATH, SensitiveMemoryRejectedError
from .wiki import _wiki_proposal_kind
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
                plan.status = "pending_confirmation"
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
            "user_message": state.user_message,
            "action_plan": plan.model_dump(mode="json"),
            "action_proposal": proposal.model_dump(mode="json"),
            "policy_decision": policy.model_dump(mode="json"),
            "canonical_payload_hash": _canonical_payload_hash(policy),
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


def _canonical_payload_hash(policy: PolicyDecision) -> str:
    canonical = json.dumps(
        policy.canonical_parameters,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _execute_action_plan(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    state = _agent_state(graph_state)
    plans = state.action_plans or ([state.action_plan] if state.action_plan is not None else [])
    if not plans:
        return graph_state
    coordinator = services.action_lifecycle
    if coordinator is None:
        return _record_node_error(graph_state, ActionLifecycleUnavailableError())
    for plan in plans:
        if plan.executed:
            continue
        proposal = next((item for item in state.action_proposals if item.proposal_id == plan.proposal_id), None)
        policy = next((item for item in state.policy_decisions if item.proposal_id == plan.proposal_id), None)
        if proposal is None or policy is None:
            plan.status = "failed"
            plan.control_state = "failed_recovery"
            continue
        plan.control_state = "claimed" if policy.decision == "approved" else plan.control_state
        try:
            outcome = await coordinator.execute(
                proposal,
                policy,
                source_run_id=state.agent_run_id,
                source_conversation_id=state.conversation_id,
            )
        except Exception as exc:
            plan.status = "failed"
            plan.control_state = "failed_recovery"
            _append_lifecycle_event(
                graph_state,
                state,
                action_id=None,
                action_type=policy.action_type,
                status="failed_recovery",
                title="动作恢复失败",
                summary="本地动作未能确认是否已完成，请查看恢复记录。",
                target_paths=list(policy.canonical_parameters.get("target_paths") or ()),
                reversible=False,
                error=str(exc),
                metadata={"safe_error_code": "action_lifecycle_failed"},
            )
            continue
        _project_lifecycle_outcome(
            graph_state,
            state,
            plan,
            policy,
            outcome,
            emit_durable_action_events=not services.allow_ephemeral_lifecycle,
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
        requested_confirmation=_plan_requires_execution_confirmation(plan),
    )


def _plan_requires_execution_confirmation(plan: ActionPlan) -> bool:
    if plan.action_type == "wiki" and not bool(plan.payload.get("auto_organize")):
        return False
    return plan.decision == "ask"


def _plan_action_type(plan: ActionPlan) -> str:
    if plan.action_type == "task":
        return "task.create"
    if plan.action_type == "memory_proposal":
        return "memory.proposal.defer" if bool(plan.payload.get("auto_long_term_memory")) else "memory.proposal"
    if plan.action_type == "confirmation":
        return "local.destructive_request"
    mode = "write" if bool(plan.payload.get("auto_organize")) else "plan"
    if plan.payload.get("kind") == "lint":
        return "wiki.lint.report"
    return f"wiki.{plan.payload.get('kind', 'ingest')}.{mode}"


def _plan_target_ref(plan: ActionPlan, fallback: str) -> str:
    if plan.payload.get("target_path"):
        return str(plan.payload["target_path"])
    if plan.payload.get("target_ref"):
        return str(plan.payload["target_ref"])
    if plan.action_type == "task":
        return f"task:{str(plan.payload.get('title') or '').casefold()}"[:256]
    if plan.action_type == "wiki":
        return f"wiki-title:{str(plan.payload.get('title') or '').casefold()}"[:256]
    return fallback


def _build_action_plans(state: AgentState, services: AgentRuntimeServices) -> list[ActionPlan]:
    if is_high_risk_mutation_request(state.user_message):
        state.suppress_post_reply_automation = True
        destructive_word = re.search(r"删除|移走|移动|批量|覆盖|delete|move|bulk|overwrite", state.user_message, re.IGNORECASE)
        has_explicit_target = bool(state.classifier and state.classifier.action_params.get("target_path"))
        if (
            state.classifier is not None
            and state.classifier.action_type in {"task", "wiki", "memory_proposal"}
            and (destructive_word is None or has_explicit_target)
        ):
            plans = _build_regular_action_plans(state, services)
            for plan in plans:
                plan.decision = "ask"
                plan.status = "pending_confirmation"
                plan.confirm_text = (
                    "这是高风险本地变更。我已保留原始目标，确认后才会执行："
                    f"{plan.payload.get('title') or plan.payload.get('content') or state.user_message[:120]}"
                )
            return plans
        return [_confirmation_plan(state)]

    return _build_regular_action_plans(state, services)


def _build_regular_action_plans(state: AgentState, services: AgentRuntimeServices) -> list[ActionPlan]:

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
    decision = AutomationPolicy().decide("task.create", confidence=state.route.confidence if state.route else None, reversible=False)
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
    request_text = " ".join(state.user_message.strip().split())[:500]
    request_digest = hashlib.sha256(request_text.encode("utf-8")).hexdigest()[:24]
    return ActionPlan(
        action_type="confirmation",
        payload={
            # Keep the original intent available for a human decision and a
            # later capability check.  The stable intent prefix is accepted
            # by the policy target validator while the request text remains
            # an informational, non-executable field.
            "request_text": request_text,
            "requested_operation": "unsupported_local_mutation",
            "requested_target": request_text,
            "target_ref": f"intent:unsupported-mutation:{request_digest}",
            "target_paths": [],
        },
        risk_score=decision.risk_tier,
        decision=decision.decision,
        status="pending_confirmation",
        confirm_text="这个本地变更类型当前没有安全执行器；确认后仍会先做能力检查，不会把未知目标当作成功。",
        reversible=False,
    )


def _wiki_plan(state: AgentState, services: AgentRuntimeServices) -> ActionPlan:
    params = _action_params(state)
    raw_content = params.get("content")
    content = str(raw_content).strip() if raw_content and str(raw_content).strip() != state.user_message.strip() else _strip_wiki_command(state.user_message)
    content = content.strip() or state.user_message
    title = str(params.get("title") or _wiki_title(state.user_message)).strip() or "Knowledge Note"
    kind = str(params.get("kind") or _wiki_proposal_kind(state.user_message))
    auto_organize = _automation_enabled(services, "auto_wiki_organize") and _wiki_write_available(
        services,
        kind,
    )
    action_type = f"wiki.{kind}.{'write' if auto_organize else 'plan'}"
    decision = AutomationPolicy().decide(action_type, confidence=state.route.confidence if state.route else None, reversible=auto_organize)
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
            "target_path": _optional_text(params.get("target_path")),
            "auto_organize": auto_organize,
            "citations": [citation.model_dump(mode="json") for citation in state.citations],
        },
        risk_score=decision.risk_tier,
        decision=decision.decision,
        confirm_text=(
            f"好，我会把这段整理到 Wiki：{title}"
            if auto_organize
            else f"我会先生成一份 Wiki 整理计划，你确认后才会真正写入：{title}"
        ),
        reversible=decision.reversible,
    )


def _project_lifecycle_outcome(
    graph_state: dict[str, Any],
    state: AgentState,
    plan: ActionPlan,
    policy: PolicyDecision,
    outcome: Any,
    *,
    emit_durable_action_events: bool,
) -> None:
    receipt = outcome.receipt
    verification = outcome.verification
    result_metadata = receipt.result.get("metadata")
    if isinstance(result_metadata, dict):
        result = {**result_metadata, **{key: value for key, value in receipt.result.items() if key != "metadata"}}
    else:
        result = receipt.result
    state.execution_receipts.append(receipt)
    if verification is not None:
        state.verification_results.append(verification)
    plan.receipt_ref = receipt.receipt_ref
    plan.verification_status = verification.status if verification is not None else None
    plan.duplicate = bool(outcome.duplicate)
    plan.executed = True
    if receipt.status == "verified":
        plan.status = "executed"
        plan.control_state = "completed"
        state.task_id = _optional_text(result.get("task_id")) or state.task_id
        state.reminder_id = _optional_text(result.get("reminder_id")) or state.reminder_id
        state.proposal_id = _optional_text(result.get("proposal_id")) or state.proposal_id
        if policy.action_type == "task.create":
            state.response_text = state.response_text or f"已创建本地提醒：{result.get('title') or plan.payload.get('title', '')}"
        elif policy.action_type == "memory.proposal":
            state.response_text = state.response_text or "已创建一条待确认的长期记忆提案。"
        elif policy.action_type == "memory.proposal.defer":
            state.response_text = state.response_text or "已把这条信息交给后台慢记忆整理；它不会直接进入回答上下文。"
        elif policy.action_type.endswith(".plan"):
            state.response_text = state.response_text or "已生成 Wiki 整理提案，尚未写入页面。"
        elif policy.action_type.startswith("wiki."):
            state.response_text = state.response_text or f"已写入 Wiki 页面：{result.get('target_path') or policy.normalized_target}"
    elif receipt.status == "pending_confirmation":
        plan.status = "pending_confirmation"
        plan.control_state = "pending_confirmation"
        plan.decision = "ask"
    elif receipt.status == "denied":
        plan.status = "skipped"
        plan.control_state = "denied"
    else:
        plan.status = "failed"
        plan.control_state = "failed_recovery"
        state.response_text = "本地动作未能确认是否已完成，已保留恢复记录。"
    action = outcome.action
    target_paths = list(action.target_paths)
    if not target_paths:
        target_path = receipt.result.get("target_path")
        if isinstance(target_path, str) and target_path:
            target_paths = [target_path]
    if policy.action_type == "task.create" and receipt.status == "verified":
        _events(graph_state).append(
            AgentTaskEvent(
                agent_run_id=state.agent_run_id,
                task_id=str(result.get("task_id") or ""),
                reminder_id=_optional_text(result.get("reminder_id")),
                status=str(result.get("status") or "pending"),
                title=_optional_text(result.get("title")),
                reminder_status=_optional_text(result.get("reminder_status")),
                remind_at=_optional_text(result.get("remind_at")),
                timezone=_optional_text(result.get("timezone")),
                timezone_label=_optional_text(result.get("timezone_label")),
            )
        )
    if policy.action_type == "memory.proposal" and receipt.status == "verified":
        _events(graph_state).append(
            AgentMemoryProposalEvent(
                agent_run_id=state.agent_run_id,
                proposal_id=str(result.get("proposal_id") or ""),
                status=str(result.get("status") or receipt.status),
                target_path=str(result.get("target_path") or DEFAULT_MEMORY_TARGET_PATH),
            )
        )
    if policy.action_type.endswith(".plan"):
        _append_wiki_proposal_event(graph_state, state, plan, policy, receipt, result)
    # Production lifecycle records are visible alongside their domain event;
    # the in-memory test fallback keeps the narrower historical event shape.
    emit_action = (
        policy.action_type != "memory.proposal"
        and (policy.action_type != "memory.proposal.defer" or emit_durable_action_events)
        and not policy.action_type.endswith(".plan")
        and not (
            policy.action_type == "task.create"
            and receipt.status == "verified"
            and not emit_durable_action_events
        )
    )
    if not emit_action:
        return
    _append_lifecycle_event(
        graph_state,
        state,
        action_id=action.action_id,
        action_type=action.action_type,
        risk_tier=action.risk_tier,
        decision=action.decision,
        status=action.status,
        title=action.title,
        summary=action.summary,
        target_paths=target_paths,
        reversible=action.reversible,
        error=action.error,
        metadata={**action.metadata, "duplicate": bool(outcome.duplicate)},
    )


def _wiki_write_available(services: AgentRuntimeServices, kind: str) -> bool:
    # Production adapters resolve request-bound services at execution time,
    # so their registry is the capability boundary. An ephemeral lifecycle
    # captures injected services directly; there an adapter name alone does
    # not prove that its dependency exists.
    lifecycle = services.action_lifecycle
    adapters = getattr(lifecycle, "adapters", {}) if lifecycle is not None else {}
    adapter_names = (
        set(adapters)
        if isinstance(adapters, dict) and not services.allow_ephemeral_lifecycle
        else set()
    )
    if kind == "page":
        return "wiki.page.write" in adapter_names or services.wiki is not None
    if kind == "ingest":
        return "wiki.ingest.write" in adapter_names or services.wiki is not None
    if kind in {"synthesize", "lint"}:
        return (
            f"wiki.{kind}.write" in adapter_names
            or services.wiki_workflow is not None
        )
    if kind == "query_archive":
        return (
            "wiki.query_archive.write" in adapter_names
            or services.wiki_workflow is not None
            or services.wiki is not None
        )
    return False


def _append_wiki_proposal_event(
    graph_state: dict[str, Any],
    state: AgentState,
    plan: ActionPlan,
    policy: PolicyDecision,
    receipt: Any,
    result: dict[str, Any],
) -> None:
    """Project a read-only Wiki plan into the public proposal event.

    Planning is an observable result, not a Markdown side effect.  Keeping
    this projection at the lifecycle boundary means the UI receives the
    original proposal even when a plan is recovered from its durable receipt.
    """
    raw = result.get("proposal")
    proposal = raw if isinstance(raw, dict) else {}
    raw_proposal_type = str(result.get("proposal_type") or proposal.get("proposal_type") or "ingest")
    proposal_type = cast(
        Literal["ingest", "query_archive", "synthesize", "lint"],
        raw_proposal_type
        if raw_proposal_type in {"ingest", "query_archive", "synthesize", "lint"}
        else _wiki_proposal_type(policy.action_type),
    )
    raw_targets = result.get("target_paths") or proposal.get("target_paths") or []
    target_paths = _string_list(raw_targets)
    if not target_paths:
        target_path = result.get("target_path") or proposal.get("target_path")
        if isinstance(target_path, str) and target_path:
            target_paths = [target_path]
    raw_recommended = result.get("recommended_targets") or proposal.get("recommended_targets") or target_paths
    recommended_targets = _string_list(raw_recommended)
    title = str(result.get("title") or proposal.get("title") or plan.payload.get("title") or "Wiki proposal")
    status = str(result.get("status") or proposal.get("status") or receipt.status)
    markdown_preview = str(result.get("markdown_preview") or proposal.get("markdown_preview") or "")
    errors = _string_list(result.get("errors") or proposal.get("errors"))
    warnings = _string_list(result.get("warnings") or proposal.get("warnings"))
    findings = result.get("findings") or proposal.get("findings") or []
    if not isinstance(findings, list):
        findings = []
    lint_summary = result.get("lint_summary") or proposal.get("summary") or {}
    if not isinstance(lint_summary, dict):
        lint_summary = {}
    state.proposal_id = _optional_text(
        result.get("run_id") or proposal.get("run_id") or (target_paths[0] if target_paths else None)
    ) or state.proposal_id
    _events(graph_state).append(
        AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_type=proposal_type,
            status=status,
            title=title,
            markdown_preview=markdown_preview,
            source_message_id=_optional_text(
                result.get("source_message_id") or proposal.get("source_message_id") or state.message_id
            ),
            run_id=_optional_text(result.get("run_id") or proposal.get("run_id")),
            source_id=_optional_text(result.get("source_id") or proposal.get("source_id")),
            source_hash=_optional_text(result.get("source_hash") or proposal.get("source_hash")),
            review_id=_optional_text(result.get("review_id") or proposal.get("review_id")),
            review_status=_optional_text(result.get("review_status") or proposal.get("review_status")),
            summary=str(result.get("summary") or proposal.get("summary") or ""),
            review_summary=str(result.get("review_summary") or proposal.get("review_summary") or ""),
            target_paths=target_paths,
            recommended_targets=recommended_targets,
            findings=[item for item in findings if isinstance(item, dict)],
            errors=errors,
            warnings=warnings,
            lint_summary=lint_summary,
            write_report=(
                bool(result.get("write_report"))
                if result.get("write_report") is not None
                else proposal.get("write_report")
            ),
        )
    )


def _wiki_proposal_type(action_type: str) -> str:
    kind = action_type.removeprefix("wiki.").removesuffix(".plan")
    return kind if kind in {"ingest", "query_archive", "synthesize", "lint"} else "ingest"


def _string_list(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _append_lifecycle_event(
    graph_state: dict[str, Any],
    state: AgentState,
    *,
    action_id: str | None,
    action_type: str,
    status: str,
    title: str,
    summary: str,
    target_paths: list[str],
    reversible: bool,
    risk_tier: str = "low",
    decision: str = "auto",
    error: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    if action_id is None:
        return
    normalized_risk_tier = cast(
        Literal["low", "medium", "high"],
        risk_tier if risk_tier in {"low", "medium", "high"} else "high",
    )
    normalized_decision = cast(
        Literal["auto", "notify", "ask"],
        decision if decision in {"auto", "notify", "ask"} else "ask",
    )
    _events(graph_state).append(
        AgentActionEvent(
            agent_run_id=state.agent_run_id,
            action_id=action_id,
            action_type=action_type,
            risk_tier=normalized_risk_tier,
            decision=normalized_decision,
            status=status,
            title=title,
            summary=summary,
            target_paths=target_paths,
            reversible=reversible,
            error=error,
            requires_confirmation=status == "pending_confirmation",
            metadata=metadata or {},
        )
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
