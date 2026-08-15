from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.models.memory import AgentActionResponse, MemoryProposalCreateRequest, MemorySearchResult
from app.models.tasks import TaskCreateRequest
from app.models.wiki import (
    QueryArchiveRequest,
    WikiIngestPreviewRequest,
    WikiLintRequest,
    WikiPageWriteRequest,
    WikiSynthesizeRequest,
)
from app.models.enums import MemoryProposalType
from app.services.agent_actions import AgentActionCreate
from app.utils.time import utc_now_iso

from .contracts import ActionProposal, ExecutionClaim, ExecutionReceipt, PolicyDecision
from .nodes.executor import ActionLifecycleCoordinator, AdapterExecutionResult
from .services import AgentActionRecorderProtocol, AgentRuntimeServices


class _EphemeralLedger:
    def __init__(self, recorder: AgentActionRecorderProtocol | None = None) -> None:
        self._actions: dict[str, AgentActionResponse] = {}
        self._recorder = recorder

    def claim_execution(
        self,
        request: AgentActionCreate,
        *,
        idempotency_key: str,
    ) -> tuple[AgentActionResponse, bool]:
        existing = self._actions.get(idempotency_key)
        if existing is not None:
            if existing.status == "pending_confirmation":
                metadata = dict(existing.metadata)
                metadata.pop("execution_receipt", None)
                metadata.pop("verification_result", None)
                metadata.update(request.metadata)
                metadata.update(
                    {
                        "control_state": "claimed",
                        "idempotency_key": idempotency_key,
                    }
                )
                promoted = existing.model_copy(
                    update={
                        "status": "claimed",
                        "metadata": metadata,
                        "error": None,
                        "updated_at": utc_now_iso(),
                        "completed_at": None,
                    }
                )
                self._actions[idempotency_key] = promoted
                return promoted, True
            return existing, False
        action = self._new_action(request, idempotency_key=idempotency_key, status="claimed")
        self._actions[idempotency_key] = action
        if self._recorder is not None:
            self._recorder(request)
        return action, True

    def record_policy_decision(
        self,
        request: AgentActionCreate,
        *,
        idempotency_key: str,
        status: str,
    ) -> tuple[AgentActionResponse, bool]:
        existing = self._actions.get(idempotency_key)
        if existing is not None:
            return existing, False
        action = self._new_action(request, idempotency_key=idempotency_key, status=status)
        self._actions[idempotency_key] = action
        if self._recorder is not None:
            self._recorder(request)
        return action, True

    def find_execution(self, idempotency_key: str) -> AgentActionResponse | None:
        return self._actions.get(idempotency_key)

    def begin_execution(
        self,
        action_id: str,
        *,
        owner_id: str,
        takeover: bool = False,
    ) -> tuple[AgentActionResponse, bool]:
        key = next((key for key, value in self._actions.items() if value.action_id == action_id), None)
        if key is None:
            raise KeyError(action_id)
        current = self._actions[key]
        interrupted = bool(current.metadata.get("execution_interrupted"))
        current_owner = str(current.metadata.get("lifecycle_owner") or "")
        can_start = current.status == "claimed" or (
            takeover
            and current.status in {"executing", "verifying"}
            and (interrupted or current_owner != owner_id)
        )
        if not can_start:
            return current, False
        metadata = dict(current.metadata)
        metadata["lifecycle_owner"] = owner_id
        metadata.pop("execution_interrupted", None)
        metadata.pop("execution_interrupted_owner", None)
        updated = current.model_copy(
            update={
                "status": "executing",
                "metadata": metadata,
                "error": None,
                "updated_at": utc_now_iso(),
            }
        )
        self._actions[key] = updated
        return updated, True

    def mark_execution_interrupted(
        self,
        action_id: str,
        *,
        owner_id: str,
    ) -> AgentActionResponse:
        key = next((key for key, value in self._actions.items() if value.action_id == action_id), None)
        if key is None:
            raise KeyError(action_id)
        current = self._actions[key]
        current_owner = str(current.metadata.get("lifecycle_owner") or "")
        if current.status not in {"claimed", "executing", "verifying"} or (
            current_owner and current_owner != owner_id
        ):
            return current
        return self.update_execution(
            action_id,
            status="executing",
            metadata={
                "control_state": "executing",
                "execution_interrupted": True,
                "execution_interrupted_owner": owner_id,
            },
            error="execution_interrupted",
        )

    def update_execution(self, action_id: str, **kwargs: Any) -> AgentActionResponse:
        key = next((key for key, value in self._actions.items() if value.action_id == action_id), None)
        if key is None:
            raise KeyError(action_id)
        current = self._actions[key]
        metadata = dict(current.metadata)
        metadata.update(kwargs.get("metadata") or {})
        raw_target_paths = kwargs.get("target_paths")
        target_paths = (
            list(current.target_paths)
            if raw_target_paths is None
            else [str(path) for path in raw_target_paths if str(path).strip()]
        )
        updated = current.model_copy(
            update={
                "status": kwargs.get("status", current.status),
                "before_snapshot": kwargs.get("before_snapshot", current.metadata.get("before_snapshot")),
                "after_snapshot": kwargs.get("after_snapshot", current.metadata.get("after_snapshot")),
                "target_paths": target_paths,
                "metadata": metadata,
                "reversible": current.reversible if kwargs.get("reversible") is None else kwargs["reversible"],
                "error": kwargs.get("error"),
                "updated_at": utc_now_iso(),
            }
        )
        self._actions[key] = updated
        return updated

    @staticmethod
    def _new_action(request: AgentActionCreate, *, idempotency_key: str, status: str) -> AgentActionResponse:
        now = utc_now_iso()
        return AgentActionResponse(
            action_id=request.action_id or f"action-{idempotency_key}",
            action_type=request.action_type,
            risk_tier=request.risk_tier,
            decision=request.decision,
            status=status,
            title=request.title,
            summary=request.summary,
            target_paths=list(request.target_paths),
            reversible=request.reversible,
            metadata={**request.metadata, "idempotency_key": idempotency_key},
            source_agent_run_id=request.source_agent_run_id,
            source_conversation_id=request.source_conversation_id,
            source_message_id=request.source_message_id,
            created_at=now,
            updated_at=now,
        )


def build_ephemeral_lifecycle(services: AgentRuntimeServices) -> ActionLifecycleCoordinator:
    ledger = _EphemeralLedger(services.agent_action_recorder)
    observed: dict[str, dict[str, object]] = {}

    async def task_adapter(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        if services.tasks is None:
            raise RuntimeError("task_service_unavailable")
        params = policy.canonical_parameters
        response = await services.tasks.create(
            TaskCreateRequest(
                title=str(params.get("title") or proposal.expected_effect),
                description=str(params.get("description") or ""),
                due_at=_text(params.get("due_at")),
                remind_at=_text(params.get("remind_at")),
                timezone=_text(params.get("timezone")),
                source_text=_text(params.get("source_text")),
            )
        )
        state: dict[str, object] = {
            "task_id": response.task_id,
            "title": response.metadata.get("title") or str(params.get("title") or ""),
            "status": response.status,
            "state_ref": f"task:{response.task_id}",
        }
        if response.reminder_id:
            state["reminder_id"] = response.reminder_id
        observed[claim.idempotency_key] = state
        return AdapterExecutionResult(
            result={"expected_state": state, "task_id": response.task_id, "reminder_id": response.reminder_id, **response.metadata},
            after_snapshot=state,
        )

    async def memory_adapter(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        if services.memory is None:
            raise RuntimeError("memory_service_unavailable")
        params = policy.canonical_parameters
        if bool(params.get("auto_long_term_memory")):
            state: dict[str, object] = {
                "status": "deferred",
                "target_path": str(params.get("target_path") or "Inbox/Pending Memories.md"),
                "state_ref": f"memory-deferred:{claim.idempotency_key}",
            }
            observed[claim.idempotency_key] = state
            return AdapterExecutionResult(result={"expected_state": state, "mode": "auto_background", **state}, after_snapshot=state)
        response = await services.memory.create_proposal(
            MemoryProposalCreateRequest(
                type=MemoryProposalType.FACT,
                content=str(params.get("content") or ""),
                target_path=str(params.get("target_path") or "Inbox/Pending Memories.md"),
                source_message_id=proposal.source_message_id,
            )
        )
        state = {
            "proposal_id": response.proposal_id,
            "status": response.status,
            "state_ref": f"memory-proposal:{response.proposal_id}",
        }
        observed[claim.idempotency_key] = state
        return AdapterExecutionResult(result={"expected_state": state, **state}, after_snapshot=state)

    async def memory_defer_adapter(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        params = policy.canonical_parameters
        handoff_id = f"memory-handoff:{claim.idempotency_key}"
        state: dict[str, object] = {
            "handoff_id": handoff_id,
            "status": "deferred",
            "target_path": str(params.get("target_path") or "Inbox/Pending Memories.md"),
            "state_ref": handoff_id,
        }
        observed[claim.idempotency_key] = state
        return AdapterExecutionResult(result={"expected_state": state, **state}, after_snapshot=state)

    async def wiki_adapter(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        params = policy.canonical_parameters
        kind = str(params.get("kind") or "ingest")
        response: Any
        if kind == "query_archive" and services.wiki_workflow is not None:
            response = await services.wiki_workflow.archive_query(
                QueryArchiveRequest(
                    question=str(params.get("title") or ""),
                    answer=str(params.get("content") or ""),
                    citations=[],
                    title=str(params.get("title") or "Query archive"),
                    target_path=_text(params.get("target_path")),
                    agent_run_id=claim.source_run_id,
                    source_message_id=proposal.source_message_id,
                    allow_mixed_sources=True,
                )
            )
            page = response.page
        elif kind == "synthesize" and services.wiki_workflow is not None:
            response = await services.wiki_workflow.synthesize(
                WikiSynthesizeRequest(
                    title=str(params.get("title") or "Synthesis"),
                    content=str(params.get("content") or ""),
                    source_paths=list(params.get("source_paths") or []),
                    target_path=_text(params.get("target_path")),
                )
            )
            page = response.page
        elif kind == "lint" and services.wiki_workflow is not None:
            response = await services.wiki_workflow.run_lint(WikiLintRequest(write_report=True))
            page = response.report_page
            if page is None:
                raise RuntimeError("wiki_lint_did_not_write_report")
        elif services.wiki is not None:
            page = await services.wiki.manage_page(
                WikiPageWriteRequest(
                    title=str(params.get("title") or "Knowledge note"),
                    content=str(params.get("content") or ""),
                    operation="append",
                    target_path=_text(params.get("target_path")),
                    source_message_id=proposal.source_message_id,
                )
            )
        else:
            raise RuntimeError("wiki_service_unavailable")
        state: dict[str, object] = {
            "target_path": page.relative_path,
            "status": page.status,
            "state_ref": page.relative_path,
        }
        observed[claim.idempotency_key] = state
        return AdapterExecutionResult(
            result={"expected_state": state, "target_path": page.relative_path, "title": page.title, "operation": page.operation},
            after_snapshot=state,
            target_paths=(page.relative_path,),
        )

    async def wiki_plan_adapter(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        """Build a confirmation proposal without touching the Vault."""
        if services.wiki_workflow is None:
            raise RuntimeError("wiki_workflow_service_unavailable")
        params = policy.canonical_parameters
        kind = str(params.get("kind") or "ingest")
        title = str(params.get("title") or "Knowledge note")
        content = str(params.get("content") or "")
        target_path = _text(params.get("target_path"))
        if kind == "query_archive":
            planned = await services.wiki_workflow.plan_query_archive(
                QueryArchiveRequest(
                    question=title,
                    answer=content,
                    citations=_memory_search_results(params.get("citations")),
                    title=title,
                    target_path=target_path,
                    agent_run_id=claim.source_run_id,
                    source_message_id=proposal.source_message_id,
                    allow_mixed_sources=True,
                )
            )
        elif kind == "synthesize":
            planned = await services.wiki_workflow.plan_synthesis(
                WikiSynthesizeRequest(
                    title=title,
                    content=content,
                    source_paths=[str(path) for path in params.get("source_paths") or []],
                    target_path=target_path,
                )
            )
        elif kind == "lint":
            planned = await services.wiki_workflow.plan_lint(WikiLintRequest(write_report=True))
        else:
            planned = await services.wiki_workflow.preview_ingest(
                # ``preview_ingest`` is the workflow's read-only plan API.
                # It may allocate a preview token, but it never writes a
                # Wiki page or an action receipt.
                WikiIngestPreviewRequest(
                    title=title,
                    content=content,
                    tags=["agent-chat", "wiki-proposal"],
                    max_pages=5,
                )
            )
        state, raw = _wiki_plan_state(planned, claim.idempotency_key, fallback_title=title)
        target_paths = state.get("target_paths")
        return AdapterExecutionResult(
            result={"expected_state": state, "proposal": raw, **state},
            after_snapshot=state,
            target_paths=(
                tuple(str(path) for path in target_paths)
                if isinstance(target_paths, list)
                else ()
            ),
        )

    def reader(receipt: ExecutionReceipt):
        return observed.get(receipt.idempotency_key)

    def plan_reader(receipt: ExecutionReceipt):
        raw = receipt.result.get("expected_state")
        return dict(raw) if isinstance(raw, Mapping) else None

    adapters: dict[str, Any] = {
        "task.create": task_adapter,
        "memory.proposal": memory_adapter,
        "memory.proposal.defer": memory_defer_adapter,
    }
    for action_type in (
        "wiki.page.write",
        "wiki.ingest.write",
        "wiki.ingest.plan",
        "wiki.query_archive.write",
        "wiki.query_archive.plan",
        "wiki.synthesize.write",
        "wiki.synthesize.plan",
        "wiki.lint.write",
        "wiki.lint.report",
        "wiki.lint.plan",
    ):
        adapters[action_type] = wiki_adapter
    for action_type in (
        "wiki.ingest.plan",
        "wiki.query_archive.plan",
        "wiki.synthesize.plan",
        "wiki.lint.plan",
    ):
        adapters[action_type] = wiki_plan_adapter
    readers = {
        action_type: (plan_reader if action_type.endswith(".plan") else reader)
        for action_type in adapters
    }
    return ActionLifecycleCoordinator(ledger=ledger, adapters=adapters, readers=readers)


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _wiki_plan_state(
    proposal: Any,
    idempotency_key: str,
    *,
    fallback_title: str,
) -> tuple[dict[str, object], dict[str, object]]:
    raw_value = proposal.model_dump(mode="json") if hasattr(proposal, "model_dump") else {}
    raw = dict(raw_value) if isinstance(raw_value, Mapping) else {}
    proposal_type = str(raw.get("proposal_type") or "ingest")
    title = str(raw.get("title") or fallback_title)
    target_path = raw.get("target_path")
    targets = [str(target_path)] if isinstance(target_path, str) and target_path else []
    if not targets and isinstance(raw.get("page_plans"), list):
        targets = [
            str(item.get("target_path"))
            for item in raw["page_plans"]
            if isinstance(item, Mapping) and item.get("target_path")
        ]
    state: dict[str, object] = {
        "proposal_type": proposal_type,
        "status": str(raw.get("status") or "planned"),
        "title": title,
        "target_paths": targets,
        "markdown_preview": str(raw.get("markdown_preview") or ""),
        "summary": str(raw.get("summary") or ""),
        "recommended_targets": [str(item) for item in raw.get("recommended_targets") or targets],
        "state_ref": f"wiki-plan:{idempotency_key}",
    }
    for key in ("run_id", "source_id", "source_hash", "review_id", "review_status", "source_message_id"):
        value = raw.get(key)
        if value is not None:
            state[key] = value
    if isinstance(raw.get("lint"), Mapping):
        lint = raw["lint"]
        state["errors"] = [str(item) for item in lint.get("errors") or []]
        state["warnings"] = [str(item) for item in lint.get("warnings") or []]
    if proposal_type == "lint":
        state["write_report"] = bool(raw.get("write_report"))
        state["lint_summary"] = dict(raw.get("summary") or {})
    return state, raw


def _memory_search_results(value: object) -> list[MemorySearchResult]:
    if not isinstance(value, list):
        return []
    results: list[MemorySearchResult] = []
    for item in value:
        try:
            results.append(MemorySearchResult.model_validate(item))
        except (TypeError, ValueError):
            continue
    return results
