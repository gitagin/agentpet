from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from app.config import get_settings
from app.agents import AgentRuntimeServices, LangGraphAgentRuntime
from app.agents.checkpointer import SQLiteCheckpointStore
from app.agents.contracts import (
    ActionProposal,
    ExecutionClaim,
    ExecutionReceipt,
    PolicyDecision,
    reflection_contract_error,
)
from app.agents.nodes.executor import (
    ActionLifecycleCoordinator,
    ActionLifecycleOutcome,
    AdapterExecutionResult,
)
from app.agents.nodes.policy_guard import evaluate_action_proposal
from app.models.api import (
    ContinuityProposalActionResponse,
    MemoryHygieneActionRequest,
    MemoryHygieneActionResponse,
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResult,
    MemorySearchResponse,
    QueryArchiveLintResponse,
    QueryArchiveRequest,
    QueryArchiveResponse,
    ReflectionProposalActionResponse,
    RetrospectiveReportRequest,
    RetrospectiveReportResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiIngestApplyRequest,
    WikiIngestApplyResponse,
    WikiIngestPreviewRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewResponse,
    WikiIngestReviewRequest,
    WikiIngestReviewResponse,
    WikiLintReportResponse,
    WikiLintRequest,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiSynthesizeRequest,
    WikiSynthesizeResponse,
)
from app.models.memory import MemoryFeedbackRequest, MemoryFeedbackResponse
from app.models.enums import MemoryProposalStatus, MemoryProposalType, ReminderStatus, TaskStatus
from app.services.agent_actions import ScopedAgentActionLedger, markdown_snapshot
from app.services.continuity import (
    CONFIRMED,
    PENDING,
    REJECTED,
    ContinuityProposalNotFoundError,
    ContinuityProposalStateError,
)
from app.services.memory_read import (
    DiaryMemorySourceAdapter,
    GraphMemorySourceAdapter,
    RetrievalMemorySourceAdapter,
    SearchResultMemorySourceAdapter,
    UnifiedMemorySearchService,
)
from app.services.memory import (
    MemoryProposal,
    MemoryProposalNotFoundError,
    MemoryProposalStateError,
    MemoryProposalStore,
)
from app.services.memory_feedback import MemoryFeedbackService
from app.services.memory_lifecycle import MemoryLifecycleService, MemoryLifecycleTransitionError
from app.services.memory_hygiene_suggestions import (
    MemoryHygieneSuggestionConfirmationRequired,
    MemoryHygieneSuggestionExpired,
    MemoryHygieneSuggestionService,
)
from app.services.reflection_proposals import (
    PENDING as REFLECTION_PENDING,
    ReflectionProposalStateError,
)
from app.services.reminder_delivery import (
    DeliveryAttempt,
    ReminderDeliveryNotFound,
    ReminderDeliveryService,
    ReminderDeliveryValidationError,
)
from app.services.product_metrics import (
    MetricPayloadConflict,
    ProductMetricsService,
    is_public_reference,
)
from app.services.retrospectives import REPORT_ACTION_TYPES
from app.services.tasks import (
    ReminderNotFoundError,
    Task,
    TaskService,
    TaskNotFoundError,
    display_timezone_name,
    normalize_timezone_name,
)
from app.services.wiki import (
    WIKI_INDEX_PATH,
    WIKI_LOG_PATH,
    WikiIngestPreviewTokenError,
    resolve_wiki_path,
)
from app.utils.time import utc_now_iso

from .factory import (
    AppContext,
    active_vault_root,
    active_vault_id,
    agent_action_service,
    agent_model_registry,
    companion_retrieval_report_store,
    continuity_service,
    database,
    diary_memory_service,
    memory_activation_recorder,
    memory_entity_graph_store,
    memory_service,
    prompt_profile_provider,
    record_agent_action,
    reflection_proposal_service,
    retrospective_service,
    retrieval_service,
    settings_store,
    task_service,
    wiki_lint_service,
    wiki_service,
    wiki_workflow_service,
    cached_active_vault_id,
)


class RuntimeRetrievalAdapter:
    def __init__(self, request: Request):
        self.request = request

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> Any:
        # 同步检索（SQLite FTS + 本地 ONNX 向量 + 重排）放到线程池执行，
        # 避免阻塞事件循环里的并发会话与 SSE 心跳。
        return await asyncio.to_thread(
            lambda: UnifiedMemorySearchService(
                (
                    RetrievalMemorySourceAdapter(
                        retrieval_service(self.request),
                        vault_id=active_vault_id(self.request),
                    ),
                    GraphMemorySourceAdapter(
                        lambda: memory_entity_graph_store(self.request),
                        answerable_only=True,
                        vault_id=active_vault_id(self.request),
                    ),
                    DiaryMemorySourceAdapter(lambda: diary_memory_service(self.request)),
                )
            ).search(
                query=query,
                top_k=top_k,
                mode=mode,
                source_scope=source_scope,
            )
        )


def prepend_graph_memory_results(
    request: Request,
    response: MemorySearchResponse,
    *,
    query: str,
    top_k: int,
) -> MemorySearchResponse:
    return UnifiedMemorySearchService(
        (
            SearchResultMemorySourceAdapter(
                "retrieval",
                response,
                supported_scopes=("all", "personal_memory"),
            ),
            GraphMemorySourceAdapter(
                lambda: memory_entity_graph_store(request),
                answerable_only=True,
                vault_id=active_vault_id(request),
            ),
        )
    ).search(
        query=query,
        top_k=top_k,
        mode="fts",
        source_scope="personal_memory",
    )


class RuntimeMemoryAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def create_proposal(
        self,
        create_request: MemoryProposalCreateRequest,
    ) -> MemoryProposalActionResponse:
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="memory.proposal",
            target_ref=create_request.target_path,
            parameters={
                "type": create_request.type.value,
                "content": create_request.content,
                "target_path": create_request.target_path,
            },
            expected_effect="创建一条待确认的本地记忆提案。",
            source_message_id=create_request.source_message_id,
            reversible=False,
        )
        result = _verified_result(outcome)
        return MemoryProposalActionResponse(
            proposal_id=str(result.get("proposal_id") or ""),
            status=str(result.get("status") or "failed_recovery"),
            action_id=outcome.action.action_id,
        )

    async def confirm_proposal(self, proposal_id: str) -> MemoryProposalActionResponse:
        proposal = self._proposal_for_mutation(proposal_id, allow_status=MemoryProposalStatus.CONFIRMED)
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="memory.proposal.confirm",
            target_ref=proposal.target_path,
            parameters={
                "proposal_id": proposal.id,
                "content": proposal.content,
                "target_path": proposal.target_path,
                "target_content_hash": proposal.target_content_hash,
            },
            expected_effect="把一条已确认的记忆提案写入其权威 Markdown 目标。",
            source_message_id=proposal.source_message_id,
            reversible=False,
            explicit_confirmation=True,
        )
        result = _verified_result(outcome)
        return MemoryProposalActionResponse(
            proposal_id=str(result.get("proposal_id") or proposal.id),
            status=str(result.get("status") or "failed_recovery"),
            written_path=_optional_string(result.get("written_path")),
            index_job_id=_optional_string(result.get("index_job_id")),
            action_id=outcome.action.action_id,
        )

    async def reject_proposal(self, proposal_id: str, reason: str) -> MemoryProposalActionResponse:
        proposal = self._proposal_for_mutation(
            proposal_id,
            allow_status=MemoryProposalStatus.REJECTED,
            rejected_reason=reason,
        )
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="memory.proposal.reject",
            target_ref=proposal.target_path,
            parameters={
                "proposal_id": proposal.id,
                "reason": reason,
                "target_path": proposal.target_path,
                "target_content_hash": proposal.target_content_hash,
            },
            expected_effect="拒绝一条待确认的记忆提案，不改动 Markdown。",
            source_message_id=proposal.source_message_id,
            reversible=False,
        )
        result = _verified_result(outcome)
        return MemoryProposalActionResponse(
            proposal_id=str(result.get("proposal_id") or proposal.id),
            status=str(result.get("status") or "failed_recovery"),
            action_id=outcome.action.action_id,
        )

    def _proposal_for_mutation(
        self,
        proposal_id: str,
        *,
        allow_status: MemoryProposalStatus,
        rejected_reason: str | None = None,
    ) -> MemoryProposal:
        service = memory_service(self.request)
        try:
            proposal = service.store.get(proposal_id)
            if proposal.status == MemoryProposalStatus.PENDING:
                return proposal
            if proposal.status != allow_status:
                raise MemoryProposalStateError(f"记忆提案当前状态为 {proposal.status}")
            if allow_status == MemoryProposalStatus.REJECTED and proposal.rejected_reason != rejected_reason:
                raise MemoryProposalStateError(f"记忆提案当前状态为 {proposal.status}")
            return proposal
        finally:
            service.close()


class RuntimeMemoryFeedbackAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def apply(self, feedback_request: MemoryFeedbackRequest) -> MemoryFeedbackResponse:
        digest = hashlib.sha256(
            json.dumps(
                feedback_request.model_dump(mode="json"),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="memory.feedback.apply",
            target_ref=f"intent:memory-feedback:{digest[:32]}",
            parameters=feedback_request.model_dump(mode="json"),
            expected_effect="应用一条已复核的记忆生命周期转换并记录证据事件。",
            source_message_id=feedback_request.source_message_id or f"memory-feedback:{digest[:24]}",
            source_run_id=feedback_request.source_agent_run_id,
            source_conversation_id=feedback_request.source_conversation_id,
            reversible=False,
        )
        result = _verified_result(outcome)
        return MemoryFeedbackResponse(
            target_type=str(result.get("target_type") or feedback_request.target_type),
            target_id=str(result.get("target_id") or feedback_request.target_id),
            operation=str(result.get("operation") or feedback_request.operation),
            status=str(result.get("status") or "failed_recovery"),
            feedback_event_id=str(result.get("feedback_event_id") or ""),
            replacement_target_id=_optional_string(result.get("replacement_target_id")),
            action_id=outcome.action.action_id,
        )


def _find_hygiene_action_id(request: Request | AppContext, suggestion_id: str) -> str | None:
    source_message_id = f"memory-hygiene:{suggestion_id}"
    with database(request).session() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM agent_actions
            WHERE action_type = 'memory.hygiene.apply'
              AND source_message_id = ?
            ORDER BY created_at DESC, rowid DESC
            LIMIT 1
            """,
            (source_message_id,),
        ).fetchone()
    return str(row["id"]) if row is not None else None


class RuntimeMemoryHygieneAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def apply(self, action_request: MemoryHygieneActionRequest) -> MemoryHygieneActionResponse:
        if not action_request.confirmed:
            raise MemoryHygieneSuggestionConfirmationRequired("hygiene_confirmation_required")
        service = MemoryHygieneSuggestionService(database(self.request).path)
        try:
            suggestion = next(
                (item for item in service.preview() if item.id == action_request.suggestion_id),
                None,
            )
            parameters: dict[str, object] | None = None
            if suggestion is not None:
                parameters = {
                    "suggestion_id": suggestion.id,
                    "suggestion_type": suggestion.type,
                    "target_type": suggestion.target_type,
                    "target_id": suggestion.target_id,
                    "from_status": suggestion.from_status,
                    "to_status": suggestion.to_status,
                    "confirmed": True,
                }
            else:
                action_id = _find_hygiene_action_id(self.request, action_request.suggestion_id)
                if action_id is not None:
                    parameters = service.recover_action_parameters(
                        suggestion_id=action_request.suggestion_id,
                        agent_action_id=action_id,
                    )
        finally:
            service.close()
        if parameters is None:
            raise MemoryHygieneSuggestionExpired("hygiene_suggestion_expired")
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="memory.hygiene.apply",
            target_ref=f"intent:memory-hygiene:{action_request.suggestion_id}",
            parameters=parameters,
            expected_effect="应用一条已确认的记忆整理生命周期转换。",
            source_message_id=f"memory-hygiene:{action_request.suggestion_id}",
            reversible=False,
            explicit_confirmation=True,
        )
        result = _verified_result(outcome)
        return MemoryHygieneActionResponse(
            ok=True,
            suggestion_id=str(result.get("suggestion_id") or action_request.suggestion_id),
            type=str(result.get("suggestion_type") or parameters["suggestion_type"]),
            status=str(result.get("status") or "failed_recovery"),
            action_id=outcome.action.action_id,
        )


class RuntimeRetrospectiveAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def write_report(
        self,
        report_request: RetrospectiveReportRequest,
    ) -> RetrospectiveReportResponse:
        report_kind = report_request.period or "retrospective"
        action_type = REPORT_ACTION_TYPES[report_kind]
        cycle_key = _retrospective_cycle_key(
            report_kind,
            days=report_request.days,
        )
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type=action_type,
            target_ref=f"intent:retrospective-report:{report_kind}:{cycle_key}",
            parameters={
                "days": report_request.days,
                "period": report_request.period,
                "report_kind": report_kind,
                "cycle_key": cycle_key,
            },
            expected_effect="写一份本地来源的复盘 Markdown 报告并绑定回执。",
            source_message_id=f"retrospective-report:{report_kind}:{cycle_key}",
            reversible=True,
        )
        result = _verified_result(outcome)
        target_path = str(result.get("target_path") or "")
        content_hash = str(result.get("content_hash") or "")
        service = retrospective_service(self.request)
        try:
            markdown = service.read_bound_report_markdown(
                target_path,
                action_id=outcome.action.action_id,
                action_type=action_type,
                report_kind=report_kind,
                content_hash=content_hash,
            )
        finally:
            service.close()
        return RetrospectiveReportResponse(
            page=WikiPageResponse(
                title=str(result.get("title") or "Local retrospective report"),
                relative_path=target_path,
                operation=str(result.get("operation") or "replace"),
                status=str(result.get("status") or "updated"),
                index_job_id=_optional_string(result.get("index_job_id")),
                action_id=outcome.action.action_id,
            ),
            action=outcome.action,
            markdown=markdown,
        )


class RuntimeTaskAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def create(self, create_request: TaskCreateRequest) -> TaskCreateResponse:
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="task.create",
            target_ref=f"task:{create_request.title}",
            parameters=create_request.model_dump(mode="json"),
            expected_effect="创建一条本地任务及其可选提醒。",
            source_message_id=None,
            reversible=False,
        )
        result = _verified_result(outcome)
        task_id = str(result.get("task_id") or "")
        reminder_id = _optional_string(result.get("reminder_id"))
        metadata = result.get("metadata")
        metadata_dict = {
            str(key): str(value)
            for key, value in (metadata.items() if isinstance(metadata, Mapping) else ())
        }
        for key in ("title", "reminder_status", "remind_at", "timezone", "timezone_label"):
            if result.get(key) is not None:
                metadata_dict[key] = str(result[key])
        return TaskCreateResponse(
            task_id=task_id,
            reminder_id=reminder_id,
            status=str(result.get("status") or "failed_recovery"),
            metadata=metadata_dict,
        )

    async def complete(self, task_id: str) -> dict[str, object]:
        return await self._mutate(
            action_type="task.complete",
            task_id=task_id,
            parameters={},
            expected_effect="完成任务并取消它绑定的所有未触发提醒。",
        )

    async def approve(self, task_id: str) -> dict[str, object]:
        return await self._mutate(
            action_type="task.approve",
            task_id=task_id,
            parameters={},
            expected_effect="确认一条待处理的本地任务，不重复创建。",
        )

    async def reject(self, task_id: str) -> dict[str, object]:
        return await self._mutate(
            action_type="task.reject",
            task_id=task_id,
            parameters={},
            expected_effect="拒绝一条本地任务并取消其绑定的所有未触发提醒。",
        )

    async def cancel(self, task_id: str) -> dict[str, object]:
        return await self._mutate(
            action_type="task.cancel",
            task_id=task_id,
            parameters={},
            expected_effect="取消一条本地任务及其绑定的所有未触发提醒。",
        )

    async def patch(self, task_id: str, patch: dict[str, str]) -> dict[str, object]:
        return await self._mutate(
            action_type="task.patch",
            task_id=task_id,
            parameters=patch,
            expected_effect="应用一条受支持的任务状态补丁，不重复创建。",
        )

    async def _mutate(
        self,
        *,
        action_type: str,
        task_id: str,
        parameters: dict[str, object],
        expected_effect: str,
    ) -> dict[str, object]:
        service = task_service(self.request)
        try:
            service.store.get_task(task_id)
        finally:
            service.close()
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type=action_type,
            target_ref=f"task:{task_id}",
            parameters=parameters,
            expected_effect=expected_effect,
            source_message_id=None,
            reversible=False,
        )
        return _verified_result(outcome)


class RuntimeReminderDeliveryAdapter:
    def __init__(
        self,
        request: Request | AppContext,
        action_lifecycle: ActionLifecycleCoordinator | None = None,
    ) -> None:
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def reserve(
        self,
        *,
        reminder_id: str,
        trigger_at: str,
        dispatch_kind: str,
        delivery_idempotency_key: str,
    ) -> dict[str, Any]:
        target_digest = hashlib.sha256(reminder_id.encode("utf-8")).hexdigest()
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="reminder.delivery.reserve",
            target_ref=f"intent:reminder-delivery:{target_digest[:32]}",
            parameters={
                "reminder_id": reminder_id,
                "trigger_at": trigger_at,
                "dispatch_kind": dispatch_kind,
                "delivery_idempotency_key": delivery_idempotency_key,
            },
            expected_effect="在系统通知调用前持久化一条派发预留。",
            source_message_id=delivery_idempotency_key,
            reversible=False,
        )
        return _verified_result(outcome)

    async def display(
        self,
        *,
        attempt_id: str,
        result_code: str,
        error: str | None,
    ) -> dict[str, Any]:
        target_digest = hashlib.sha256(attempt_id.encode("utf-8")).hexdigest()
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="reminder.delivery.display",
            target_ref=f"intent:reminder-delivery-display:{target_digest[:32]}",
            parameters={
                "attempt_id": attempt_id,
                "result_code": result_code,
                "error": error,
            },
            expected_effect=(
                "记录系统显示 API 已被调用，但未声称送达或读取。"
            ),
            source_message_id=None,
            reversible=False,
        )
        return _verified_result(outcome)

    async def recover(
        self,
        *,
        recovery_run_id: str,
        reason: str,
    ) -> dict[str, Any]:
        target_digest = hashlib.sha256(recovery_run_id.encode("utf-8")).hexdigest()
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="reminder.delivery.recover",
            target_ref=f"intent:reminder-delivery-recovery:{target_digest[:32]}",
            parameters={"recovery_run_id": recovery_run_id, "reason": reason},
            expected_effect=(
                "把每条未完成的派发预留标记为未知，且不重试系统调用。"
            ),
            source_message_id=None,
            reversible=False,
        )
        return _verified_result(outcome)


class RuntimeContinuityAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    def context_block(self) -> str:
        service = continuity_service(self.request)
        try:
            return service.context_block()
        finally:
            service.close()

    def presence_context_block(self) -> str:
        service = continuity_service(self.request)
        try:
            return service.presence_context_block()
        finally:
            service.close()

    def presence_signal(self):
        service = continuity_service(self.request)
        try:
            return service.presence_signal()
        finally:
            service.close()

    async def confirm_proposal(self, proposal_id: str) -> ContinuityProposalActionResponse:
        proposal = self._proposal_for_mutation(proposal_id, allowed_terminal_status=CONFIRMED)
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="continuity.proposal.confirm",
            target_ref=f"intent:continuity-proposal:{proposal.id}",
            parameters={"proposal_id": proposal.id, "kind": proposal.kind},
            expected_effect="确认一条连续性提案并投影到运行时连续性状态。",
            source_message_id=proposal.source_message_id,
            reversible=False,
            explicit_confirmation=True,
        )
        result = _verified_result(outcome)
        return ContinuityProposalActionResponse(
            proposal_id=str(result.get("proposal_id") or proposal.id),
            status=str(result.get("status") or "failed_recovery"),
            action_id=outcome.action.action_id,
        )

    async def reject_proposal(self, proposal_id: str, reason: str) -> ContinuityProposalActionResponse:
        proposal = self._proposal_for_mutation(
            proposal_id,
            allowed_terminal_status=REJECTED,
            rejected_reason=reason,
        )
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="continuity.proposal.reject",
            target_ref=f"intent:continuity-proposal:{proposal.id}",
            parameters={"proposal_id": proposal.id, "kind": proposal.kind, "reason": reason},
            expected_effect="拒绝一条连续性提案，不改动运行时连续性状态。",
            source_message_id=proposal.source_message_id,
            reversible=False,
        )
        result = _verified_result(outcome)
        return ContinuityProposalActionResponse(
            proposal_id=str(result.get("proposal_id") or proposal.id),
            status=str(result.get("status") or "failed_recovery"),
            action_id=outcome.action.action_id,
        )

    def _proposal_for_mutation(
        self,
        proposal_id: str,
        *,
        allowed_terminal_status: str,
        rejected_reason: str | None = None,
    ):
        service = continuity_service(self.request)
        try:
            proposal = service.get_proposal(proposal_id)
        finally:
            service.close()
        if proposal.status == PENDING:
            return proposal
        # 「下次接着聊」的 open_thread 会被自动确认(见 api/chat.py):
        # 用户对它点「不再继续」= 撤销接续,拒绝已确认的该线程是合法操作,
        # 服务层会同步把话题从在场状态中移除。
        if (
            allowed_terminal_status == REJECTED
            and proposal.status == CONFIRMED
            and proposal.kind == "open_thread"
        ):
            return proposal
        if proposal.status != allowed_terminal_status:
            raise ContinuityProposalStateError(f"proposal {proposal_id} is {proposal.status}")
        if allowed_terminal_status == REJECTED and proposal.rejected_reason != rejected_reason:
            raise ContinuityProposalStateError(f"proposal {proposal_id} is {proposal.status}")
        return proposal


async def execute_continuity_activation(
    request: Request | AppContext,
    *,
    proposal_id: str,
    kind: str,
    source_message_id: str | None,
    source_run_id: str,
    source_conversation_id: str | None,
):
    digest = hashlib.sha256(f"{proposal_id}:{kind}".encode("utf-8")).hexdigest()[:24]
    return await _execute_registered_action(
        request,
        action_lifecycle=production_action_lifecycle(request),
        action_type="continuity.proposal.activate",
        target_ref=f"intent:continuity-activation:{digest}",
        parameters={"proposal_id": proposal_id, "kind": kind},
        expected_effect="确认一条低风险的陪伴连续性提案。",
        source_message_id=source_message_id,
        reversible=False,
        source_run_id=source_run_id,
        source_conversation_id=source_conversation_id,
    )


class RuntimeReflectionAdapter:
    """Review-queue actions for background reflection proposals.

    Memory suggestions run the registered memory proposal lifecycle. Wiki
    summaries run their dedicated writer and reader. Both paths validate the
    stored kind/action/target contract before producing any external effect.
    """

    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    def list_proposals(self, *, statuses: Sequence[str] | None = None, limit: int = 50) -> list[Any]:
        service = reflection_proposal_service(self.request)
        try:
            return service.list_proposals(statuses=statuses, limit=limit)
        finally:
            service.close()

    async def confirm_proposal(self, proposal_id: str) -> ReflectionProposalActionResponse:
        proposal = self._claim(proposal_id)
        # 尝试次数进动作身份:账本会按原键回放已存的失败回执,重试若不换身份就是个
        # 什么都不做的按钮(见 services/reflection_proposals.claim_for_apply)。
        attempt = proposal.apply_attempts
        try:
            contract_error = reflection_contract_error(
                proposal_kind=proposal.proposal_kind,
                action_type=proposal.action_type,
                target_ref=proposal.target_ref,
                content=proposal.content,
            )
            if contract_error is not None:
                raise ReflectionProposalStateError(contract_error)
            if proposal.proposal_kind == "wiki_summary":
                outcome = await _execute_registered_action(
                    self.request,
                    action_lifecycle=self.action_lifecycle,
                    action_type="wiki.answer_summary.write",
                    target_ref=str(proposal.target_ref),
                    parameters={
                        "content": proposal.content,
                        "proposal_kind": proposal.proposal_kind,
                        "target_path": proposal.target_ref,
                    },
                    expected_effect="将反思建议写入 Wiki 摘要页面。",
                    source_message_id=proposal.source_message_id,
                    reversible=proposal.reversible,
                    explicit_confirmation=True,
                    source_run_id=proposal.agent_run_id,
                    source_conversation_id=proposal.source_conversation_id,
                    attempt=attempt,
                )
                result = _verified_result(outcome)
                applied = self._mark(proposal.id, applied_ref=str(result.get("target_path") or proposal.target_ref or proposal.id))
                return ReflectionProposalActionResponse(proposal_id=applied.id, status=applied.status, action_id=outcome.action.action_id)
            created = await _execute_registered_action(
                self.request,
                action_lifecycle=self.action_lifecycle,
                action_type="memory.proposal",
                target_ref=f"intent:reflection-proposal:{proposal.id}",
                parameters={"content": proposal.content, "type": _reflection_memory_proposal_type(proposal.proposal_kind), "proposal_kind": proposal.proposal_kind},
                expected_effect="将一条反思建议登记为已确认记忆。",
                source_message_id=proposal.source_message_id,
                reversible=True,
                source_run_id=proposal.agent_run_id,
                source_conversation_id=proposal.source_conversation_id,
                attempt=attempt,
            )
            created_result = _verified_result(created)
            memory_proposal_id = str(created_result.get("proposal_id") or "")
            if not memory_proposal_id:
                raise RuntimeError("reflection_memory_proposal_missing")
            await _execute_registered_action(
                self.request,
                action_lifecycle=self.action_lifecycle,
                action_type="memory.proposal.confirm",
                target_ref=f"intent:reflection-proposal-confirm:{proposal.id}",
                parameters={"proposal_id": memory_proposal_id},
                expected_effect="确认该建议生成的记忆提案，写入本地 Markdown。",
                source_message_id=proposal.source_message_id,
                reversible=False,
                explicit_confirmation=True,
                source_run_id=proposal.agent_run_id,
                source_conversation_id=proposal.source_conversation_id,
                attempt=attempt,
            )
            applied = self._mark(proposal.id, applied_ref=memory_proposal_id)
            return ReflectionProposalActionResponse(proposal_id=applied.id, status=applied.status, action_id=created.action.action_id, memory_proposal_id=memory_proposal_id)
        except Exception as exc:
            self._fail(proposal.id, error=str(exc))
            raise
    async def reject_proposal(self, proposal_id: str, reason: str) -> ReflectionProposalActionResponse:
        service = reflection_proposal_service(self.request)
        try:
            rejected = service.reject(proposal_id, reason)
        finally:
            service.close()
        return ReflectionProposalActionResponse(
            proposal_id=rejected.id,
            status=rejected.status,
        )

    def _claim(self, proposal_id: str):
        service = reflection_proposal_service(self.request)
        try:
            proposal = service.claim_for_apply(proposal_id)
        finally:
            service.close()
        if proposal.status != "applying":
            # 已处理过的建议不会因为重复点击而再次落地。
            raise ReflectionProposalStateError(f"proposal {proposal_id} is {proposal.status}")
        return proposal

    def _mark(self, proposal_id: str, *, applied_ref: str):
        service = reflection_proposal_service(self.request)
        try:
            return service.mark_applied(proposal_id, applied_ref=applied_ref)
        finally:
            service.close()

    def _fail(self, proposal_id: str, *, error: str):
        service = reflection_proposal_service(self.request)
        try:
            return service.mark_failed(proposal_id, error=error)
        finally:
            service.close()


def _reflection_memory_proposal_type(proposal_kind: str) -> str:
    """记忆提案类型:日记观察偏"事件",其余按"事实"登记。"""
    return MemoryProposalType.EVENT.value if proposal_kind == "daily_diary" else MemoryProposalType.FACT.value


class RuntimeWikiAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def manage_page(self, write_request: WikiPageWriteRequest) -> WikiPageResponse:
        outcome = await _execute_registered_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.page.write",
            target_ref=resolve_wiki_path(write_request.title, write_request.target_path),
            parameters=write_request.model_dump(mode="json"),
            expected_effect=f"写入 Wiki 页面：{write_request.title}。",
            source_message_id=write_request.source_message_id,
            reversible=True,
        )
        result = _verified_result(outcome)
        raw_response = result.get("response")
        if isinstance(raw_response, Mapping):
            return WikiPageResponse.model_validate(raw_response).model_copy(update={"action_id": outcome.action.action_id})
        return WikiPageResponse(
            title=str(result.get("title") or write_request.title),
            relative_path=str(result.get("target_path") or resolve_wiki_path(write_request.title, write_request.target_path)),
            operation=str(result.get("operation") or write_request.operation),
            status=str(result.get("status") or "verified"),
            index_job_id=_optional_string(result.get("index_job_id")),
            action_id=outcome.action.action_id,
        )


class RuntimeWikiWorkflowAdapter:
    def __init__(self, request: Request, action_lifecycle: ActionLifecycleCoordinator | None = None):
        self.request = request
        self.action_lifecycle = action_lifecycle

    async def preview_ingest(self, ingest_request: WikiIngestPreviewRequest) -> WikiIngestPreviewResponse:
        return wiki_workflow_service(self.request).preview_ingest(ingest_request)

    async def confirm_ingest(self, confirm_request: WikiIngestConfirmRequest) -> WikiIngestPreviewResponse:
        if not confirm_request.user_confirmed:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_not_confirmed")
        service = wiki_workflow_service(self.request)
        intent_key = service.ingest_intent_key(confirm_request.preview_token)
        vault_id = active_vault_id(self.request)
        try:
            outcome = await _execute_workflow_action(
                self.request,
                action_lifecycle=self.action_lifecycle,
                action_type="wiki.ingest.confirm",
                target_ref=f"intent:wiki-ingest-confirm:{vault_id}:{intent_key}",
                parameters={
                    "intent_key": intent_key,
                    "user_confirmed": True,
                    "vault_id": vault_id,
                },
                expected_effect="确认一个 Wiki 导入预览并持久化其来源与运行记录。",
                source_message_id=None,
                reversible=False,
            )
        finally:
            service.discard_ingest_preview(confirm_request.preview_token)
        return _model_result(outcome, WikiIngestPreviewResponse)

    async def review_ingest(self, review_request: WikiIngestReviewRequest) -> WikiIngestReviewResponse:
        outcome = await _execute_workflow_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.ingest.review",
            target_ref=f"intent:wiki-ingest-review:{review_request.run_id}",
            parameters=review_request.model_dump(mode="json"),
            expected_effect="复核一个已确认的 Wiki 导入运行并持久化复核结果。",
            source_message_id=None,
            reversible=False,
        )
        return _model_result(outcome, WikiIngestReviewResponse)

    async def lint_query_archive(self, archive_request: QueryArchiveRequest) -> QueryArchiveLintResponse:
        return wiki_workflow_service(self.request).lint_query_archive(archive_request)

    async def archive_query(self, archive_request: QueryArchiveRequest) -> QueryArchiveResponse:
        outcome = await _execute_workflow_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.query_archive.write",
            target_ref=archive_request.target_path or archive_request.title or archive_request.question,
            parameters=archive_request.model_dump(mode="json"),
            expected_effect="把一条带引用的回答归档为 Wiki 页面和查询记录。",
            source_message_id=archive_request.source_message_id,
            reversible=True,
        )
        response = _model_result(outcome, QueryArchiveResponse)
        return response.model_copy(
            update={
                "action_id": outcome.action.action_id,
                "page": response.page.model_copy(update={"action_id": outcome.action.action_id}),
            }
        )

    async def plan_query_archive(self, archive_request: QueryArchiveRequest):
        return wiki_workflow_service(self.request).plan_query_archive(archive_request)

    async def synthesize(self, synthesize_request: WikiSynthesizeRequest) -> WikiSynthesizeResponse:
        outcome = await _execute_workflow_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.synthesize.write",
            target_ref=synthesize_request.target_path or synthesize_request.title,
            parameters=synthesize_request.model_dump(mode="json"),
            expected_effect="把带引用的 Wiki 来源综合成一个类型化页面。",
            source_message_id=None,
            reversible=True,
        )
        response = _model_result(outcome, WikiSynthesizeResponse)
        return response.model_copy(
            update={
                "action_id": outcome.action.action_id,
                "page": response.page.model_copy(update={"action_id": outcome.action.action_id}),
            }
        )

    async def plan_synthesis(self, synthesize_request):
        return wiki_workflow_service(self.request).plan_synthesis(synthesize_request)

    async def run_lint(self, lint_request: WikiLintRequest) -> WikiLintReportResponse:
        if not lint_request.write_report:
            lint_service = wiki_lint_service(self.request)
            try:
                return lint_service.run(lint_request)
            finally:
                lint_service.close()
        outcome = await _execute_workflow_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.lint.report",
            target_ref="Wiki/Reports/Lint-Report.md",
            parameters=lint_request.model_dump(mode="json"),
            expected_effect="运行 Wiki 检查并持久化带引用的报告页。",
            source_message_id=None,
            reversible=True,
        )
        response = _model_result(outcome, WikiLintReportResponse)
        report_page = response.report_page
        return response.model_copy(
            update={
                "action_id": outcome.action.action_id,
                "report_page": report_page.model_copy(update={"action_id": outcome.action.action_id})
                if report_page is not None
                else None,
            }
        )

    async def plan_lint(self, lint_request):
        return wiki_workflow_service(self.request).plan_lint(lint_request)

    async def apply_ingest(self, apply_request: WikiIngestApplyRequest) -> WikiIngestApplyResponse:
        outcome = await _execute_workflow_action(
            self.request,
            action_lifecycle=self.action_lifecycle,
            action_type="wiki.ingest.apply",
            target_ref=f"intent:wiki-ingest-apply:{apply_request.run_id}",
            parameters=apply_request.model_dump(mode="json"),
            expected_effect="精确应用一次已批准的 Wiki 导入目标。",
            source_message_id=apply_request.run_id,
            reversible=False,
            explicit_confirmation=apply_request.review_acknowledged,
        )
        return _model_result(outcome, WikiIngestApplyResponse)


async def _execute_registered_action(
    request: Request | AppContext,
    *,
    action_lifecycle: ActionLifecycleCoordinator | None,
    action_type: str,
    target_ref: str,
    parameters: dict[str, object],
    expected_effect: str,
    source_message_id: str | None,
    reversible: bool,
    explicit_confirmation: bool = False,
    source_run_id: str | None = None,
    source_conversation_id: str | None = None,
    attempt: int = 1,
):
    seed_payload: dict[str, object] = {
        "action_type": action_type,
        "target_ref": target_ref,
        "parameters": parameters,
        "source_message_id": source_message_id or "",
    }
    if attempt > 1:
        # 第一次尝试保持原身份:否则升级后已存在的动作会被当成新动作重复执行。
        # 重试必须是新身份,因为账本按原幂等键回放已存的失败回执
        # (ActionLifecycleCoordinator._terminal_outcome),同键重试不会重跑适配器。
        seed_payload["apply_attempt"] = attempt
    canonical_seed = json.dumps(
        seed_payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(canonical_seed.encode("utf-8")).hexdigest()
    proposal = ActionProposal(
        proposal_id=f"proposal-runtime-{digest[:24]}",
        explicit_intent_ref=f"runtime:{action_type}:{digest[:32]}",
        action_type=action_type,
        target_ref=target_ref,
        parameters=parameters,
        expected_effect=expected_effect,
        reversible=reversible,
        source_message_id=source_message_id,
    )
    policy = evaluate_action_proposal(proposal)
    if explicit_confirmation and policy.decision == "pending_confirmation":
        policy = policy.model_copy(
            update={
                "decision": "approved",
                "requires_confirmation": False,
                "confirmed_by_user": True,
            }
        )
    request_id = getattr(request, "request_id", None) or getattr(getattr(request, "state", None), "request_id", None)
    lifecycle = action_lifecycle or production_action_lifecycle(request)
    outcome = await lifecycle.execute(
        proposal,
        policy,
        source_run_id=str(source_run_id or request_id or f"runtime-{digest[:24]}"),
        source_conversation_id=source_conversation_id,
    )
    _record_action_metrics(request, policy, outcome)
    return outcome


def _record_action_metrics(
    request: Request | AppContext,
    policy: PolicyDecision,
    outcome: ActionLifecycleOutcome,
) -> None:
    try:
        metrics = ProductMetricsService(database(request).path)
        try:
            action_key = policy.idempotency_key
            action_digest = hashlib.sha256(action_key.encode("utf-8")).hexdigest()
            dimensions: dict[str, object] = {
                "action_type": policy.action_type,
                "status": outcome.receipt.status,
            }
            if outcome.receipt.safe_error_code:
                dimensions["failure_code"] = outcome.receipt.safe_error_code
            metrics.record(
                event_type="action_attempted",
                idempotency_key=f"action-attempted:{action_digest}:{outcome.receipt.status}",
                subject_id=action_key,
                dimensions=dimensions,
            )
            if outcome.duplicate:
                metrics.record(
                    event_type="duplicate_prevented",
                    idempotency_key=f"duplicate-prevented:{action_digest}:{outcome.receipt.status}",
                    subject_id=action_key,
                    dimensions={"action_type": policy.action_type, "status": outcome.receipt.status},
                )
            if outcome.receipt.status != "verified":
                return
            _record_authoritative_action_metrics(
                metrics,
                policy=policy,
                outcome=outcome,
                action_digest=action_digest,
            )
            effect_reference = _metric_effect_reference(outcome)
            if effect_reference is None:
                return
            effect_hash = metrics.subject_token(effect_reference)
            previous_effects = metrics.effect_hashes_for_action(action_key)
            metrics.record(
                event_type="business_effect_committed",
                idempotency_key=f"effect-committed:{action_digest}:{effect_hash}",
                subject_id=action_key,
                dimensions={
                    "action_type": policy.action_type,
                    "effect_id_hash": effect_hash,
                },
            )
            if previous_effects and effect_hash not in previous_effects:
                metrics.record(
                    event_type="duplicate_effect_detected",
                    idempotency_key=f"duplicate-effect:{action_digest}:{effect_hash}",
                    subject_id=action_key,
                    dimensions={
                        "action_type": policy.action_type,
                        "effect_id_hash": effect_hash,
                    },
                )
        finally:
            metrics.close()
    except Exception:
        return


def _record_authoritative_action_metrics(
    metrics: ProductMetricsService,
    *,
    policy: PolicyDecision,
    outcome: ActionLifecycleOutcome,
    action_digest: str,
) -> None:
    projection = _metric_projection(outcome)
    action_type = policy.action_type
    if action_type in {"memory.consolidation.candidate", "memory.consolidation.safety_event"}:
        for candidate_id in _string_values(projection.get("candidate_ids")):
            metrics.record(
                event_type="candidate_created",
                idempotency_key=f"candidate-created:{candidate_id}",
                subject_id=candidate_id,
                dimensions={"source_scope": "personal_memory", "status": "candidate"},
            )
        for candidate_id in _string_values(projection.get("active_candidate_ids")):
            metrics.record(
                event_type="activated",
                idempotency_key=f"activated:{action_digest}:{candidate_id}",
                subject_id=candidate_id,
                dimensions={"source_scope": "personal_memory", "status": "active"},
            )
        for fact_id in _string_values(projection.get("active_fact_ids")):
            metrics.record(
                event_type="activated",
                idempotency_key=f"activated:{action_digest}:{fact_id}",
                subject_id=fact_id,
                dimensions={"source_scope": "personal_memory", "status": "active"},
            )

    if action_type.startswith("memory.graph.") or action_type == "memory.feedback.apply":
        if str(projection.get("status") or "") == "active":
            target_id = _first_metric_reference(
                projection.get("candidate_id"),
                projection.get("fact_id"),
                projection.get("entity_id"),
                policy.canonical_parameters.get("target_id"),
            )
            if target_id:
                metrics.record(
                    event_type="activated",
                    idempotency_key=f"activated:{action_digest}:{target_id}",
                    subject_id=target_id,
                    dimensions={"source_scope": "personal_memory", "status": "active"},
                )

    if action_type == "reminder.delivery.reserve":
        attempt_id = _first_metric_reference(projection.get("attempt_id"))
        if attempt_id:
            metrics.record(
                event_type="reminder_triggered",
                idempotency_key=f"reminder-triggered:{attempt_id}",
                subject_id=attempt_id,
                dimensions={"status": "reserved"},
            )
    elif action_type == "reminder.delivery.display":
        attempt_id = _first_metric_reference(
            projection.get("attempt_id"),
            policy.canonical_parameters.get("attempt_id"),
        )
        if attempt_id:
            result_code = str(
                projection.get("result_code")
                or policy.canonical_parameters.get("result_code")
                or "unknown"
            )
            metrics.record(
                event_type="reminder_display_attempted",
                idempotency_key=f"reminder-display-attempted:{attempt_id}",
                subject_id=attempt_id,
                dimensions={"result": result_code},
            )
    elif action_type == "reminder.delivery.recover":
        for attempt_id in _string_values(projection.get("unknown_attempt_ids")):
            metrics.record(
                event_type="reminder_display_unknown",
                idempotency_key=f"reminder-display-unknown:{attempt_id}",
                subject_id=attempt_id,
                dimensions={"result": "unknown_after_crash"},
            )

    if action_type == "wiki.lint.report":
        _record_wiki_lint_metric(metrics, projection, action_digest=action_digest)


def _metric_projection(outcome: ActionLifecycleOutcome) -> dict[str, object]:
    projection: dict[str, object] = {}
    for source in (outcome.receipt.result, outcome.receipt.after_snapshot):
        if not isinstance(source, Mapping):
            continue
        expected = source.get("expected_state")
        if isinstance(expected, Mapping):
            projection.update(expected)
        projection.update(source)
    return projection


def _first_metric_reference(*values: object) -> str | None:
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if (
            normalized
            and len(normalized) <= 256
            and not any(char.isspace() or ord(char) < 32 for char in normalized)
            and "/" not in normalized
            and "\\" not in normalized
        ):
            return normalized
    return None


def _record_wiki_lint_metric(
    metrics: ProductMetricsService,
    projection: Mapping[str, object],
    *,
    action_digest: str,
) -> None:
    response = projection.get("response")
    if not isinstance(response, Mapping):
        return
    raw_summary = response.get("summary")
    summary = raw_summary if isinstance(raw_summary, Mapping) else {}
    try:
        active_pages = max(0, int(summary.get("pages", 0)))
        error_count = max(0, int(summary.get("errors", 0)))
        warning_count = max(0, int(summary.get("warnings", 0)))
    except (TypeError, ValueError):
        return
    raw_issues = response.get("issues")
    issues = raw_issues if isinstance(raw_issues, list) else []
    error_paths = {
        str(issue.get("path"))
        for issue in issues
        if isinstance(issue, Mapping)
        and str(issue.get("severity") or "") == "error"
        and issue.get("path")
    }
    passed_pages = max(0, active_pages - len(error_paths))
    status = "passed" if error_count == 0 else "failed"
    metrics.record(
        event_type="wiki_lint_result",
        idempotency_key=f"wiki-lint:{action_digest}",
        subject_id=f"wiki-lint:{action_digest}",
        value=passed_pages,
        dimensions={
            "status": status,
            "active_pages": active_pages,
            "passed_pages": passed_pages,
            "error_count": error_count,
            "warning_count": warning_count,
        },
    )


def _metric_effect_reference(outcome: ActionLifecycleOutcome) -> str | None:
    for projection in (outcome.receipt.result, outcome.receipt.after_snapshot):
        candidate = projection.get("state_ref")
        if not isinstance(candidate, str):
            continue
        normalized = candidate.strip()
        if (
            normalized
            and len(normalized) <= 256
            and not any(char.isspace() or ord(char) < 32 for char in normalized)
            and "/" not in normalized
            and "\\" not in normalized
        ):
            return normalized
    verification = outcome.verification
    if verification is not None:
        candidate = verification.checked_state_ref
        if isinstance(candidate, str):
            normalized = candidate.strip()
            if (
                normalized
                and len(normalized) <= 256
                and not any(char.isspace() or ord(char) < 32 for char in normalized)
                and "/" not in normalized
                and "\\" not in normalized
            ):
                return normalized
    return None


async def _execute_workflow_action(
    request: Request | AppContext,
    *,
    action_lifecycle: ActionLifecycleCoordinator | None,
    action_type: str,
    target_ref: str,
    parameters: dict[str, object],
    expected_effect: str,
    source_message_id: str | None,
    reversible: bool,
    explicit_confirmation: bool = False,
):
    return await _execute_registered_action(
        request,
        action_lifecycle=action_lifecycle,
        action_type=action_type,
        target_ref=target_ref,
        parameters=parameters,
        expected_effect=expected_effect,
        source_message_id=source_message_id,
        reversible=reversible,
        explicit_confirmation=explicit_confirmation,
    )


def _model_result(outcome: Any, model_type):
    result = _verified_result(outcome)
    raw = result.get("response")
    if not isinstance(raw, Mapping):
        raise RuntimeError("action_lifecycle_response_missing")
    return model_type.model_validate(raw)


def _verified_result(outcome: Any) -> dict[str, Any]:
    receipt = outcome.receipt
    if receipt.status != "verified":
        error_code = receipt.safe_error_code or receipt.status
        raise RuntimeError(f"action_lifecycle_{error_code}")
    return dict(receipt.result)


def _stable_effect_id(prefix: str, idempotency_key: str) -> str:
    return f"{prefix}-{idempotency_key}"


def _task_action_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        task_id = _stable_effect_id("task", claim.idempotency_key)
        reminder_id = _stable_effect_id("reminder", claim.idempotency_key)
        service = task_service(request)
        try:
            created = service.create(
                title=str(params.get("title") or proposal.normalized_target or "Local task"),
                description=str(params.get("description") or ""),
                due_at=_optional_string(params.get("due_at")),
                remind_at=_optional_string(params.get("remind_at")),
                timezone=_optional_string(params.get("timezone")),
                source_text=_optional_string(params.get("source_text")),
                task_id=task_id,
                reminder_id=reminder_id,
            )
        finally:
            service.close()
        expected_state: dict[str, object] = {
            "task_id": created.task.id,
            "title": created.task.title,
            "status": created.task.status.value,
            "due_at": created.task.due_at_utc,
            "target_ref": f"task:{created.task.id}",
        }
        if created.reminder is not None:
            expected_state["reminder_id"] = created.reminder.id
            expected_state["reminder_status"] = created.reminder.status.value
            expected_state["remind_at"] = created.reminder.remind_at_utc
            expected_state["timezone"] = created.reminder.time_parse_timezone
            expected_state["timezone_label"] = display_timezone_name(created.reminder.time_parse_timezone)
        else:
            expected_state.update(
                {
                    "reminder_id": None,
                    "reminder_status": None,
                    "remind_at": None,
                    "timezone": created.metadata.get("timezone"),
                    "timezone_label": created.metadata.get("timezone_label"),
                }
            )
        return AdapterExecutionResult(
            result={
                "expected_state": expected_state,
                # Keep the task fields at the receipt's top level so event
                # projection remains useful after recovery, when there is no
                # adapter response to unwrap.
                **expected_state,
                "metadata": created.metadata,
            },
            after_snapshot=expected_state,
        )

    return execute


def _task_action_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        parameters = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        # New claims always use a deterministic task ID.  The expected-state
        # fallback keeps already persisted pre-lifecycle receipts readable,
        # but is never preferred when canonical parameters are present.
        task_id = _stable_effect_id("task", receipt.idempotency_key)
        if parameters is None:
            legacy_task_id = expected.get("task_id")
            if isinstance(legacy_task_id, str):
                task_id = legacy_task_id
        service = task_service(request)
        try:
            try:
                task = service.store.get_task(task_id)
            except TaskNotFoundError:
                return None
            expected_title = _optional_string(parameters.get("title")) if parameters is not None else None
            if expected_title is not None and task.title != expected_title:
                raise ValueError("task_authoritative_title_mismatch")
            observed: dict[str, object] = {
                "task_id": task.id,
                "title": task.title,
                "status": task.status.value,
                "due_at": task.due_at_utc,
                "target_ref": f"task:{task.id}",
                "state_ref": f"task:{task.id}",
            }
            reminder_id = _stable_effect_id("reminder", receipt.idempotency_key)
            try:
                reminder = service.store.get_reminder(reminder_id)
            except ReminderNotFoundError:
                if parameters is not None:
                    reminder = None
                else:
                    # Pre-lifecycle tasks did not reserve a deterministic
                    # reminder ID; retain their historical projection.
                    reminder = service.store.get_reminder_for_task(task.id)
            if reminder is not None and reminder.task_id != task.id:
                raise ValueError("task_authoritative_reminder_binding_mismatch")
            if reminder is None and parameters is not None:
                # A new claim must never accept a different reminder as its
                # effect.  Any reminder attached to this task without the
                # deterministic ID is an uncertain prior state.
                if service.store.list_reminders_for_task(task.id):
                    return None
                if _optional_string(parameters.get("remind_at")):
                    return None
            if reminder is not None:
                observed["reminder_id"] = reminder.id
                observed["reminder_status"] = reminder.status.value
                observed["remind_at"] = reminder.remind_at_utc
                observed["timezone"] = reminder.time_parse_timezone
                observed["timezone_label"] = display_timezone_name(reminder.time_parse_timezone)
            else:
                has_due_at = bool(parameters and _optional_string(parameters.get("due_at")))
                timezone = (
                    normalize_timezone_name(parameters.get("timezone"), "UTC")
                    if has_due_at and parameters is not None
                    else _optional_string(expected.get("timezone"))
                )
                observed.update(
                    {
                        "reminder_id": None,
                        "reminder_status": None,
                        "remind_at": None,
                        "timezone": timezone,
                        "timezone_label": display_timezone_name(timezone) if timezone else None,
                    }
                )
            return observed
        finally:
            service.close()

    return read


def _task_mutation_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        task_id = str(params.get("task_id") or policy.normalized_target.removeprefix("task:"))
        service = task_service(request)
        try:
            task = _apply_task_mutation(service, policy.action_type, task_id, params)
            expected_state = _task_mutation_state(service, policy.action_type, task)
        finally:
            service.close()
        return AdapterExecutionResult(
            result={"expected_state": expected_state, **expected_state},
            after_snapshot=expected_state,
        )

    return execute


def _task_mutation_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        canonical_parameters = _receipt_canonical_parameters(receipt)
        params = canonical_parameters or _receipt_expected_state(receipt)
        task_id = str(params.get("task_id") or receipt.normalized_target.removeprefix("task:"))
        service = task_service(request)
        try:
            try:
                task = service.store.get_task(task_id)
            except TaskNotFoundError:
                return None
            required_status = _required_task_status(receipt.action_type, params)
            if required_status is not None and task.status != required_status:
                return None
            if _task_mutation_cancels_reminders(receipt.action_type, params):
                reminders = service.store.list_reminders_for_task(task.id)
                if any(
                    reminder.status not in {ReminderStatus.TRIGGERED, ReminderStatus.CANCELLED}
                    for reminder in reminders
                ):
                    return None
            return _task_mutation_state(service, receipt.action_type, task)
        finally:
            service.close()

    return read


def _apply_task_mutation(
    service: TaskService,
    action_type: str,
    task_id: str,
    parameters: Mapping[str, object],
) -> Task:
    if action_type == "task.complete":
        return service.complete(task_id)
    if action_type == "task.approve":
        return service.approve(task_id)
    if action_type == "task.reject":
        return service.reject(task_id)
    if action_type == "task.cancel":
        return service.cancel(task_id)
    if action_type == "task.patch":
        patch_status = _optional_string(parameters.get("status"))
        if patch_status == TaskStatus.DONE.value:
            return service.complete(task_id)
        if patch_status == TaskStatus.CANCELLED.value:
            return service.cancel(task_id)
        return service.store.get_task(task_id)
    raise ValueError("unsupported_task_mutation")


def _task_mutation_state(
    service: TaskService,
    action_type: str,
    task: Task,
) -> dict[str, object]:
    state: dict[str, object] = {
        "task_id": task.id,
        "status": task.status.value,
        "target_ref": f"task:{task.id}",
        "state_ref": f"task:{task.id}",
    }
    if action_type == "task.approve":
        state.update({"approved": True, "rejected": False})
    elif action_type == "task.reject":
        state.update({"approved": False, "rejected": True})
    if _task_mutation_cancels_reminders(action_type, {"status": task.status.value}):
        reminder_states = [
            {"reminder_id": reminder.id, "status": reminder.status.value}
            for reminder in service.store.list_reminders_for_task(task.id)
        ]
        state["reminder_states"] = reminder_states
        state["untriggered_reminders_cancelled"] = all(
            reminder["status"] in {ReminderStatus.TRIGGERED.value, ReminderStatus.CANCELLED.value}
            for reminder in reminder_states
        )
    return state


def _required_task_status(
    action_type: str,
    parameters: Mapping[str, object],
) -> TaskStatus | None:
    if action_type == "task.complete":
        return TaskStatus.DONE
    if action_type in {"task.reject", "task.cancel"}:
        return TaskStatus.CANCELLED
    if action_type == "task.patch":
        patch_status = _optional_string(parameters.get("status"))
        if patch_status in {TaskStatus.DONE.value, TaskStatus.CANCELLED.value}:
            return TaskStatus(patch_status)
    return None


def _task_mutation_cancels_reminders(
    action_type: str,
    parameters: Mapping[str, object],
) -> bool:
    return _required_task_status(action_type, parameters) in {TaskStatus.DONE, TaskStatus.CANCELLED}


class _LifecycleAdapterError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _metrics_feedback_contract(params: Mapping[str, object]) -> tuple[str, dict[str, object], str, str | None, float]:
    """Normalize the public feedback payload into the anonymous event contract."""
    signal = str(params.get("signal") or "").strip()
    if signal in {"helpful", "incorrect", "missing"}:
        event_type = "feedback_recorded"
    elif signal in {"context_repeated", "context_not_repeated"}:
        event_type = "context_repetition_reported"
    elif signal == "wiki_reused":
        event_type = "wiki_reused"
    else:
        raise _LifecycleAdapterError("invalid_metric_signal")
    external_key = str(params.get("external_idempotency_key") or "").strip()
    reference = str(params.get("reference") or "").strip()
    if not external_key or not reference or not is_public_reference(reference):
        raise _LifecycleAdapterError("invalid_metric_feedback")
    for field_name in ("answer_reference", "wiki_reference"):
        candidate = params.get(field_name)
        if candidate is not None and (not isinstance(candidate, str) or not is_public_reference(candidate)):
            raise _LifecycleAdapterError("invalid_metric_reference")
    dimensions: dict[str, object] = {
        "signal": signal,
        "source_scope": str(params.get("source_scope") or "personal_memory"),
    }
    duration_ms = params.get("duration_ms")
    if duration_ms is not None:
        dimensions["duration_ms"] = int(duration_ms)
    repetition_count = params.get("repetition_count")
    if repetition_count is not None:
        dimensions["repetition_count"] = int(repetition_count)
    if params.get("answer_reference"):
        dimensions["reference_type"] = "answer"
    elif params.get("wiki_reference"):
        dimensions["reference_type"] = "wiki"
    value = float(repetition_count) if event_type == "context_repetition_reported" and repetition_count is not None else 1.0
    return event_type, dimensions, external_key, reference, value


def _metrics_feedback_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        event_type, dimensions, external_key, reference, value = _metrics_feedback_contract(policy.canonical_parameters)
        service = ProductMetricsService(database(request).path)
        try:
            try:
                event = service.record(
                    event_type=event_type,
                    idempotency_key=external_key,
                    subject_id=reference,
                    value=value,
                    dimensions=dimensions,
                )
            except MetricPayloadConflict as exc:
                raise _LifecycleAdapterError("metric_payload_conflict") from exc
            payload_hash = service.payload_hash_for(
                event_type=event_type,
                idempotency_key=external_key,
                subject_id=reference,
                value=value,
                dimensions=dimensions,
            )
        finally:
            service.close()
        expected = {
            "event_id": event.id,
            "event_type": event.event_type,
            "external_idempotency_key": external_key,
            "event_payload_hash": payload_hash,
            "state_ref": f"metric-event:{event.id}",
        }
        return AdapterExecutionResult(
            result={
                "expected_state": expected,
                "canonical_parameters": dict(policy.canonical_parameters),
                **expected,
            },
            after_snapshot=expected,
        )

    return execute


def _metrics_feedback_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        raw = receipt.result.get("canonical_parameters")
        params = raw if isinstance(raw, Mapping) else receipt.result
        event_type, dimensions, external_key, reference, value = _metrics_feedback_contract(params)
        service = ProductMetricsService(database(request).path)
        try:
            row = service.event_by_idempotency_key(external_key)
            expected_hash = service.payload_hash_for(
                event_type=event_type,
                idempotency_key=external_key,
                subject_id=reference,
                value=value,
                dimensions=dimensions,
            )
        finally:
            service.close()
        if row is None or str(row["payload_hash"]) != expected_hash or str(row["event_type"]) != event_type:
            return None
        return {
            "event_id": str(row["id"]),
            "event_type": event_type,
            "external_idempotency_key": external_key,
            "event_payload_hash": expected_hash,
            "state_ref": f"metric-event:{row['id']}",
            "observed_effect": "metric_event_recorded",
        }

    return read


def _memory_feedback_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = dict(policy.canonical_parameters)
        try:
            feedback_request = MemoryFeedbackRequest.model_validate(params)
        except Exception as exc:
            raise _LifecycleAdapterError("memory_feedback_payload_invalid") from exc
        if feedback_request.source_agent_run_id is None and claim.source_run_id:
            feedback_request = feedback_request.model_copy(
                update={"source_agent_run_id": claim.source_run_id}
            )
        with database(request).session() as conn:
            metrics = ProductMetricsService(conn)
            try:
                service = MemoryFeedbackService(
                    conn,
                    lifecycle_factory=lambda: MemoryLifecycleService(conn),
                    metric_recorder=metrics.record,
                    correction_recorder=metrics.record_correction,
                )
                try:
                    result = service.apply_effect(
                        feedback_request,
                        agent_action_id=claim.claim_id,
                    )
                except KeyError as exc:
                    raise _LifecycleAdapterError("memory_feedback_target_not_found") from exc
                except MemoryLifecycleTransitionError as exc:
                    code = str(exc).strip()
                    if not code or not all(char.isalnum() or char == "_" for char in code):
                        code = "memory_feedback_invalid"
                    raise _LifecycleAdapterError(code) from exc
                projected = service.read_effect(
                    feedback_event_id=result.feedback_event_id,
                    target_type=result.target_type,
                    target_id=result.target_id,
                    operation=result.operation,
                    agent_action_id=claim.claim_id,
                )
                if projected is None:
                    raise _LifecycleAdapterError("memory_feedback_effect_incomplete")
            finally:
                metrics.close()
        return AdapterExecutionResult(
            result={
                "expected_state": projected,
                "canonical_parameters": params,
                **projected,
            },
            after_snapshot=projected,
        )

    return execute


def _memory_feedback_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        if params is None:
            return None
        feedback_event_id = _optional_string(receipt.result.get("feedback_event_id"))
        try:
            feedback_request = MemoryFeedbackRequest.model_validate(params)
        except Exception:
            return None
        with database(request).session() as conn:
            service = MemoryFeedbackService(
                conn,
                lifecycle_factory=lambda: MemoryLifecycleService(conn),
            )
            return service.read_effect(
                feedback_event_id=feedback_event_id,
                target_type=feedback_request.target_type,
                target_id=feedback_request.target_id,
                operation=feedback_request.operation,
                agent_action_id=receipt.claim_id,
            )

    return read


def _memory_hygiene_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        suggestion_id = str(params.get("suggestion_id") or "")
        suggestion_type = str(params.get("suggestion_type") or "")
        target_type = str(params.get("target_type") or "")
        target_id = str(params.get("target_id") or "")
        to_status = str(params.get("to_status") or "")
        if (
            not suggestion_id
            or not suggestion_type
            or target_type not in {"candidate", "fact"}
            or not target_id
            or not to_status
            or params.get("confirmed") is not True
        ):
            raise _LifecycleAdapterError("memory_hygiene_payload_invalid")
        service = MemoryHygieneSuggestionService(database(request).path)
        try:
            try:
                result = service.apply(
                    suggestion_id,
                    confirmed=True,
                    agent_action_id=claim.claim_id,
                )
            except MemoryHygieneSuggestionExpired as exc:
                raise _LifecycleAdapterError("hygiene_suggestion_expired") from exc
            except MemoryHygieneSuggestionConfirmationRequired as exc:
                raise _LifecycleAdapterError("hygiene_confirmation_required") from exc
            except (KeyError, MemoryLifecycleTransitionError, ValueError) as exc:
                raise _LifecycleAdapterError("hygiene_suggestion_apply_failed") from exc
            projected = service.read_effect(
                suggestion_id=suggestion_id,
                suggestion_type=suggestion_type,
                target_type=target_type,
                target_id=target_id,
                to_status=to_status,
                agent_action_id=claim.claim_id,
            )
            if projected is None or result.status != projected["status"]:
                raise _LifecycleAdapterError("memory_hygiene_effect_incomplete")
        finally:
            service.close()
        public_state = _public_hygiene_effect(projected)
        return AdapterExecutionResult(
            result={
                "expected_state": public_state,
                **public_state,
            },
            after_snapshot=public_state,
        )

    return execute


def _memory_hygiene_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        service = MemoryHygieneSuggestionService(database(request).path)
        try:
            if params is None:
                expected = _receipt_expected_state(receipt)
                suggestion_id = str(
                    receipt.result.get("suggestion_id")
                    or expected.get("suggestion_id")
                    or ""
                )
                params = service.recover_action_parameters(
                    suggestion_id=suggestion_id,
                    agent_action_id=receipt.claim_id,
                )
            if params is None:
                return None
            effect = service.read_effect(
                suggestion_id=str(params.get("suggestion_id") or ""),
                suggestion_type=str(params.get("suggestion_type") or ""),
                target_type=str(params.get("target_type") or ""),
                target_id=str(params.get("target_id") or ""),
                to_status=str(params.get("to_status") or ""),
                agent_action_id=receipt.claim_id,
            )
            return _public_hygiene_effect(effect) if effect is not None else None
        finally:
            service.close()

    return read


def _public_hygiene_effect(effect: Mapping[str, object]) -> dict[str, object]:
    return {
        "suggestion_id": str(effect.get("suggestion_id") or ""),
        "suggestion_type": str(effect.get("suggestion_type") or ""),
        "status": str(effect.get("status") or ""),
        "state_ref": str(effect.get("state_ref") or ""),
        "observed_effect": str(effect.get("observed_effect") or ""),
    }


def _retrospective_report_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        report_kind = str(params.get("report_kind") or "")
        action_type = policy.action_type
        if REPORT_ACTION_TYPES.get(report_kind) != action_type:
            raise _LifecycleAdapterError("retrospective_report_binding_invalid")
        raw_days = params.get("days", 7)
        if isinstance(raw_days, bool):
            raise _LifecycleAdapterError("retrospective_report_days_invalid")
        try:
            days = int(raw_days)
        except (TypeError, ValueError) as exc:
            raise _LifecycleAdapterError("retrospective_report_days_invalid") from exc
        period = params.get("period")
        if report_kind == "retrospective":
            if period is not None:
                raise _LifecycleAdapterError("retrospective_report_binding_invalid")
        elif period != report_kind:
            raise _LifecycleAdapterError("retrospective_report_binding_invalid")
        service = retrospective_service(request)
        try:
            draft = service.prepare_report(
                days=days,
                period=period if isinstance(period, str) else None,
            )
            if draft.report_kind != report_kind or draft.action_type != action_type:
                raise _LifecycleAdapterError("retrospective_report_binding_invalid")
            before = markdown_snapshot(service.writer, [draft.relative_path]) if service.writer is not None else {}
            written = service.write_report_draft(
                draft,
                action_id=claim.claim_id,
                action_type=action_type,
            )
            matches = service.read_report_effects(
                action_id=claim.claim_id,
                action_type=action_type,
                report_kind=report_kind,
                expected_relative_path=written.relative_path,
                expected_content_hash=written.content_hash,
            )
            if len(matches) != 1:
                raise _LifecycleAdapterError("retrospective_report_effect_incomplete")
            state = dict(matches[0])
            state["index_job_id"] = written.index_job_id
            state["canonical_parameters"] = dict(params)
            state["expected_state"] = {
                key: value
                for key, value in state.items()
                if key not in {"canonical_parameters", "expected_state", "index_job_id"}
            }
            return AdapterExecutionResult(
                result={
                    **state,
                    "expected_state": state["expected_state"],
                    "canonical_parameters": dict(params),
                    "action_metadata": {
                        "report_kind": report_kind,
                        "report_content_hash": written.content_hash,
                        "report_action_id": claim.claim_id,
                    },
                },
                before_snapshot=before,
                after_snapshot=state["expected_state"],
                target_paths=(written.relative_path,),
            )
        finally:
            service.close()

    return execute


def _retrospective_report_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | tuple[dict[str, object], ...] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        values = params or expected
        report_kind = str(values.get("report_kind") or "")
        if REPORT_ACTION_TYPES.get(report_kind) != receipt.action_type:
            return None
        target_path = _optional_string(expected.get("target_path")) if params is not None else None
        content_hash = _optional_string(expected.get("content_hash")) if params is not None else None
        service = retrospective_service(request)
        try:
            matches = service.read_report_effects(
                action_id=receipt.claim_id,
                action_type=receipt.action_type,
                report_kind=report_kind,
                expected_relative_path=target_path,
                expected_content_hash=content_hash,
            )
        finally:
            service.close()
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0]
        return matches

    return read


def _retrospective_cycle_key(report_kind: str, *, days: int) -> str:
    now = datetime.now(timezone.utc)
    if report_kind == "weekly":
        iso = now.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if report_kind == "monthly":
        return now.strftime("%Y-%m")
    return f"{now.strftime('%Y-%m-%d')}:{days}"


async def execute_metrics_feedback(
    request: Request | AppContext,
    *,
    idempotency_key: str,
    payload: dict[str, object],
):
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:24]
    return await _execute_registered_action(
        request,
        action_lifecycle=production_action_lifecycle(request),
        action_type="metrics.feedback",
        target_ref=f"intent:metrics-feedback:{digest}",
        parameters={**payload, "external_idempotency_key": idempotency_key},
        expected_effect="记录一条匿名的本地产品反馈事件。",
        source_message_id=f"metrics-feedback:{digest}",
        reversible=True,
    )


def _reminder_delivery_reserve_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        service = ReminderDeliveryService(database(request).path)
        try:
            try:
                attempt, duplicate = service.reserve(
                    str(params.get("reminder_id") or ""),
                    str(params.get("trigger_at") or ""),
                    idempotency_key=str(params.get("delivery_idempotency_key") or ""),
                    dispatch_kind=str(params.get("dispatch_kind") or "automatic"),
                )
            except ReminderDeliveryNotFound as exc:
                raise _LifecycleAdapterError("reminder_not_found") from exc
            except ReminderDeliveryValidationError as exc:
                code = "idempotency_key_conflict" if "conflict" in str(exc) else "invalid_reminder_delivery"
                raise _LifecycleAdapterError(code) from exc
        finally:
            service.close()
        state = _reminder_delivery_attempt_state(attempt, duplicate=duplicate)
        return AdapterExecutionResult(
            result={"expected_state": _reminder_delivery_authoritative_state(attempt), **state},
            after_snapshot=state,
        )

    return execute


def _reminder_delivery_reserve_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or _receipt_expected_state(receipt)
        service = ReminderDeliveryService(database(request).path)
        try:
            try:
                found = service.find_reservation(
                    str(params.get("reminder_id") or ""),
                    str(params.get("trigger_at") or ""),
                    idempotency_key=str(
                        params.get("delivery_idempotency_key") or params.get("idempotency_key") or ""
                    ),
                    dispatch_kind=str(params.get("dispatch_kind") or "automatic"),
                )
            except ReminderDeliveryValidationError:
                return None
            if found is None:
                return None
            attempt, duplicate = found
            return _reminder_delivery_attempt_state(attempt, duplicate=duplicate)
        finally:
            service.close()

    return read


def _reminder_delivery_display_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        service = ReminderDeliveryService(database(request).path)
        try:
            try:
                attempt = service.mark_display_invoked(
                    str(params.get("attempt_id") or ""),
                    result_code=str(params.get("result_code") or ""),
                    error=_optional_string(params.get("error")),
                )
            except ReminderDeliveryNotFound as exc:
                raise _LifecycleAdapterError("reminder_delivery_attempt_not_found") from exc
            except ReminderDeliveryValidationError as exc:
                raise _LifecycleAdapterError("invalid_reminder_delivery_result") from exc
        finally:
            service.close()
        state = _reminder_delivery_attempt_state(attempt)
        return AdapterExecutionResult(
            result={"expected_state": _reminder_delivery_authoritative_state(attempt), **state},
            after_snapshot=state,
        )

    return execute


def _reminder_delivery_display_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or _receipt_expected_state(receipt)
        attempt_id = str(params.get("attempt_id") or "")
        result_code = str(params.get("result_code") or "")
        required_status = "display_invoked" if result_code == "shown" else result_code
        service = ReminderDeliveryService(database(request).path)
        try:
            try:
                attempt = service.get(attempt_id)
            except (ReminderDeliveryNotFound, ReminderDeliveryValidationError):
                return None
            if attempt.status != required_status or attempt.result_code != result_code:
                return None
            return _reminder_delivery_attempt_state(attempt)
        finally:
            service.close()

    return read


def _reminder_delivery_recover_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        marker = _reminder_delivery_recovery_marker(
            str(params.get("reason") or "resident_runtime_recovery"),
            claim.idempotency_key,
        )
        service = ReminderDeliveryService(database(request).path)
        try:
            unknown_attempts = service.recover_reserved(reason=marker)
            recovered = service.list_unknown_by_reason(marker)
        finally:
            service.close()
        state = {
            "unknown_attempts": unknown_attempts,
            "unknown_attempt_ids": [attempt.attempt_id for attempt in recovered],
            "recovery_marker": marker,
            "state_ref": f"reminder-delivery-recovery:{claim.idempotency_key}",
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot=state,
        )

    return execute


def _reminder_delivery_recover_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or _receipt_expected_state(receipt)
        marker = str(params.get("recovery_marker") or "")
        if not marker:
            marker = _reminder_delivery_recovery_marker(
                str(params.get("reason") or "resident_runtime_recovery"),
                receipt.idempotency_key,
            )
        service = ReminderDeliveryService(database(request).path)
        try:
            recovered = service.list_unknown_by_reason(marker)
            if not recovered and service.list_reserved():
                return None
        finally:
            service.close()
        return {
            "unknown_attempts": len(recovered),
            "unknown_attempt_ids": [attempt.attempt_id for attempt in recovered],
            "recovery_marker": marker,
            "state_ref": f"reminder-delivery-recovery:{receipt.idempotency_key}",
        }

    return read


def _reminder_delivery_authoritative_state(attempt: DeliveryAttempt) -> dict[str, object]:
    state = attempt.as_dict()
    state.pop("duplicate", None)
    state["state_ref"] = f"reminder-delivery:{attempt.attempt_id}"
    return state


def _reminder_delivery_attempt_state(
    attempt: DeliveryAttempt,
    *,
    duplicate: bool = False,
) -> dict[str, object]:
    return {
        **attempt.as_dict(duplicate=duplicate),
        "state_ref": f"reminder-delivery:{attempt.attempt_id}",
    }


def _reminder_delivery_recovery_marker(reason: str, idempotency_key: str) -> str:
    normalized_reason = " ".join(reason.split()).strip() or "resident_runtime_recovery"
    return f"{normalized_reason[:55]}:{idempotency_key}"


def _memory_action_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        proposal_id = _stable_effect_id("memory-proposal", claim.idempotency_key)
        raw_type = str(params.get("type") or MemoryProposalType.FACT.value)
        proposal_type = MemoryProposalType(raw_type)
        service = memory_service(request)
        try:
            created = service.create_proposal(
                type=proposal_type,
                content=str(params.get("content") or ""),
                target_path=str(params.get("target_path") or "Inbox/Pending Memories.md"),
                source_message_id=proposal.source_message_id,
                proposal_id=proposal_id,
            )
        finally:
            service.close()
        expected_state = {
            "proposal_id": created.id,
            "status": created.status.value,
            "target_path": created.target_path,
            "target_ref": f"memory-proposal:{created.id}",
        }
        return AdapterExecutionResult(
            result={"expected_state": expected_state, **expected_state},
            after_snapshot=expected_state,
        )

    return execute


def _memory_defer_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        handoff_id = _stable_effect_id("memory-handoff", claim.idempotency_key)
        state = {
            "handoff_id": handoff_id,
            "status": "deferred",
            "target_path": str(params.get("target_path") or "Inbox/Pending Memories.md"),
            "target_ref": f"memory-handoff:{handoff_id}",
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot=state,
        )

    return execute


def _memory_defer_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or {}
        handoff_id = _stable_effect_id("memory-handoff", receipt.idempotency_key)
        return {
            "handoff_id": handoff_id,
            "status": "deferred",
            "target_path": str(params.get("target_path") or "Inbox/Pending Memories.md"),
            "target_ref": f"memory-handoff:{handoff_id}",
            "state_ref": f"memory-handoff:{handoff_id}",
        }

    return read


def _memory_action_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        parameters = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        proposal_id = _stable_effect_id("memory-proposal", receipt.idempotency_key)
        if parameters is None:
            legacy_proposal_id = expected.get("proposal_id")
            if isinstance(legacy_proposal_id, str):
                proposal_id = legacy_proposal_id
        store = MemoryProposalStore(database(request).path)
        try:
            try:
                proposal = store.get(proposal_id)
            except MemoryProposalNotFoundError:
                return None
            expected_content = _optional_string(parameters.get("content")) if parameters is not None else None
            expected_target = _optional_string(parameters.get("target_path")) if parameters is not None else None
            if expected_content is not None and proposal.content != expected_content:
                raise ValueError("memory_authoritative_content_mismatch")
            if expected_target is not None and proposal.target_path != expected_target:
                raise ValueError("memory_authoritative_target_mismatch")
            return {
                "proposal_id": proposal.id,
                "status": proposal.status.value,
                "target_path": proposal.target_path,
                "target_ref": f"memory-proposal:{proposal.id}",
                "state_ref": f"memory-proposal:{proposal.id}",
            }
        finally:
            store.close()

    return read


def _memory_confirm_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        proposal_id = str(params.get("proposal_id") or "")
        confirmation_marker = _memory_confirmation_marker(claim.idempotency_key)
        service = memory_service(request)
        try:
            pending = service.store.get(proposal_id)
            target_paths = (pending.target_path,)
            before_snapshot = markdown_snapshot(service.writer, target_paths)
            result = service.confirm_proposal(
                proposal_id,
                lifecycle_marker=confirmation_marker,
            )
            confirmed = service.store.get(proposal_id)
            state = _confirmed_memory_state(confirmed, confirmation_marker)
            after_snapshot = {
                **state,
                "markdown": markdown_snapshot(service.writer, target_paths),
            }
        finally:
            service.close()
        return AdapterExecutionResult(
            result={
                "expected_state": state,
                **state,
                "index_job_id": result.index_job_id,
            },
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            target_paths=target_paths,
        )

    return execute


def _memory_confirm_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        proposal_id = str((params or expected).get("proposal_id") or "")
        confirmation_marker = _memory_confirmation_marker(receipt.idempotency_key)
        service = memory_service(request)
        try:
            try:
                proposal = service.store.get(proposal_id)
            except MemoryProposalNotFoundError:
                return None
            if params is not None and not _memory_proposal_matches_parameters(proposal, params):
                raise ValueError("memory_confirmation_binding_mismatch")
            reconciled = service.reconcile_confirmation(
                proposal_id,
                lifecycle_marker=confirmation_marker,
            )
            if reconciled is None:
                return None
            proposal = service.store.get(proposal_id)
            if proposal.status != MemoryProposalStatus.CONFIRMED:
                return None
            target = service.writer.resolve_markdown_path(proposal.target_path)
            if proposal.written_path != str(target) or not target.exists():
                return None
            if service.writer.current_hash(proposal.target_path) == proposal.target_content_hash:
                return None
            markdown = target.read_text(encoding="utf-8")
            if not _markdown_has_memory_confirmation(
                markdown,
                proposal.content,
                confirmation_marker,
            ):
                return None
            state = _confirmed_memory_state(proposal, confirmation_marker)
            state["index_job_id"] = reconciled.index_job_id
            return state
        finally:
            service.close()

    return read


def _memory_reject_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        proposal_id = str(params.get("proposal_id") or "")
        reason = str(params.get("reason") or "")
        service = memory_service(request)
        try:
            rejected = service.reject_proposal(proposal_id, reason)
            state = _rejected_memory_state(rejected)
        finally:
            service.close()
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot=state,
            target_paths=(rejected.target_path,),
        )

    return execute


def _memory_reject_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        proposal_id = str((params or expected).get("proposal_id") or "")
        service = memory_service(request)
        try:
            try:
                proposal = service.store.get(proposal_id)
            except MemoryProposalNotFoundError:
                return None
            if proposal.status != MemoryProposalStatus.REJECTED:
                return None
            if params is not None and not _memory_proposal_matches_parameters(proposal, params):
                raise ValueError("memory_rejection_binding_mismatch")
            expected_reason = str((params or expected).get("reason") or (params or expected).get("rejected_reason") or "")
            if proposal.rejected_reason != expected_reason:
                return None
            return _rejected_memory_state(proposal)
        finally:
            service.close()

    return read


def _continuity_confirm_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        proposal_id = str(params.get("proposal_id") or "")
        service = continuity_service(request)
        try:
            confirmed = service.confirm_proposal(proposal_id)
        finally:
            service.close()
        state = _continuity_proposal_state(confirmed)
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot=state,
        )

    return execute


def _continuity_confirm_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        values = params or expected
        service = continuity_service(request)
        try:
            try:
                proposal = service.get_proposal(str(values.get("proposal_id") or ""))
            except ContinuityProposalNotFoundError:
                return None
        finally:
            service.close()
        if proposal.status != CONFIRMED:
            return None
        if params is not None and proposal.kind != str(params.get("kind") or ""):
            raise ValueError("continuity_confirmation_binding_mismatch")
        return _continuity_proposal_state(proposal)

    return read


def _continuity_reject_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        proposal_id = str(params.get("proposal_id") or "")
        reason = str(params.get("reason") or "")
        service = continuity_service(request)
        try:
            rejected = service.reject_proposal(proposal_id, reason)
        finally:
            service.close()
        state = _continuity_proposal_state(rejected)
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot=state,
        )

    return execute


def _continuity_reject_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        values = params or expected
        service = continuity_service(request)
        try:
            try:
                proposal = service.get_proposal(str(values.get("proposal_id") or ""))
            except ContinuityProposalNotFoundError:
                return None
        finally:
            service.close()
        if proposal.status != REJECTED:
            return None
        if params is not None and proposal.kind != str(params.get("kind") or ""):
            raise ValueError("continuity_rejection_binding_mismatch")
        expected_reason = str(values.get("reason") or values.get("rejected_reason") or "")
        if proposal.rejected_reason != expected_reason:
            return None
        return _continuity_proposal_state(proposal)

    return read


def _continuity_proposal_state(proposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.id,
        "kind": proposal.kind,
        "status": proposal.status,
        "rejected_reason": proposal.rejected_reason,
        "target_ref": f"continuity-proposal:{proposal.id}",
        "state_ref": f"continuity-proposal:{proposal.id}",
    }


def _memory_proposal_matches_parameters(
    proposal: MemoryProposal,
    parameters: Mapping[str, object],
) -> bool:
    return (
        proposal.id == str(parameters.get("proposal_id") or "")
        and proposal.target_path == str(parameters.get("target_path") or "")
        and proposal.target_content_hash == parameters.get("target_content_hash")
        and (
            "content" not in parameters
            or proposal.content == str(parameters.get("content") or "")
        )
    )


def _confirmed_memory_state(
    proposal: MemoryProposal,
    confirmation_marker: str,
) -> dict[str, object]:
    return {
        "proposal_id": proposal.id,
        "status": proposal.status.value,
        "target_path": proposal.target_path,
        "written_path": proposal.written_path,
        "confirmation_marker": confirmation_marker,
        "target_ref": f"memory-proposal:{proposal.id}",
        "state_ref": f"memory-proposal:{proposal.id}",
    }


def _rejected_memory_state(proposal: MemoryProposal) -> dict[str, object]:
    return {
        "proposal_id": proposal.id,
        "status": proposal.status.value,
        "target_path": proposal.target_path,
        "rejected_reason": proposal.rejected_reason,
        "target_ref": f"memory-proposal:{proposal.id}",
        "state_ref": f"memory-proposal:{proposal.id}",
    }


def _memory_confirmation_marker(idempotency_key: str) -> str:
    return f"<!-- llmwiki-memory-confirm:{idempotency_key} -->"


def _markdown_has_memory_confirmation(
    markdown: str,
    proposal_content: str,
    confirmation_marker: str,
) -> bool:
    normalized_markdown = markdown.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    normalized_proposal = proposal_content.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")
    expected = f"{normalized_proposal}\n\n{confirmation_marker}"
    return bool(normalized_proposal) and normalized_markdown.endswith(expected)


def _workflow_action_marker(idempotency_key: str) -> str:
    return f"<!-- llmwiki-action:{idempotency_key} -->"


def _wiki_ingest_confirm_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        intent_key = str(policy.canonical_parameters.get("intent_key") or "")
        vault_id = str(policy.canonical_parameters.get("vault_id") or "")
        user_confirmed = policy.canonical_parameters.get("user_confirmed") is True
        if len(intent_key) != 64 or any(char not in "0123456789abcdef" for char in intent_key):
            raise WikiIngestPreviewTokenError("wiki_ingest_intent_invalid")
        if not user_confirmed:
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_not_confirmed")
        if not vault_id or vault_id != active_vault_id(request):
            raise WikiIngestPreviewTokenError("wiki_ingest_preview_scope_changed")
        run_id = _stable_effect_id("wiki-ingest", claim.idempotency_key)
        response = wiki_workflow_service(request).confirm_ingest_intent(
            intent_key,
            user_confirmed=user_confirmed,
            run_id=run_id,
        )
        state = {
            "run_id": response.run_id,
            "source_id": response.source_id,
            "status": response.status,
            "target_ref": f"wiki-ingest:{response.run_id}",
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot={"run_id": response.run_id, "source_id": response.source_id},
        )

    return execute


def _wiki_ingest_confirm_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        run_id = _stable_effect_id("wiki-ingest", receipt.idempotency_key)
        with database(request).session() as conn:
            row = conn.execute(
                "SELECT source_id, status, result_json FROM wiki_workflow_runs WHERE id = ? AND workflow_type = 'ingest'",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            response = WikiIngestPreviewResponse.model_validate_json(str(row["result_json"]))
        except (TypeError, ValueError):
            return None
        if response.run_id != run_id or response.source_id != str(row["source_id"]):
            return None
        return {
            "run_id": run_id,
            "source_id": response.source_id,
            "status": str(row["status"]),
            "target_ref": f"wiki-ingest:{run_id}",
            "state_ref": f"wiki-ingest:{run_id}",
            "response": response.model_dump(mode="json"),
        }

    return read


def _wiki_ingest_review_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        review_request = WikiIngestReviewRequest.model_validate(policy.canonical_parameters)
        review_id = _stable_effect_id("wiki-review", claim.idempotency_key)
        response = await wiki_workflow_service(request).review_ingest(
            review_request,
            review_id=review_id,
        )
        state = {
            "review_id": response.review_id,
            "run_id": response.run_id,
            "status": response.status,
            "target_ref": f"wiki-review:{response.review_id}",
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot={"review_id": response.review_id, "run_id": response.run_id},
        )

    return execute


def _wiki_ingest_review_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        review_id = _stable_effect_id("wiki-review", receipt.idempotency_key)
        response = wiki_workflow_service(request).get_ingest_review(review_id)
        if response is None:
            return None
        return {
            "review_id": response.review_id,
            "run_id": response.run_id,
            "status": response.status,
            "target_ref": f"wiki-review:{response.review_id}",
            "state_ref": f"wiki-review:{response.review_id}",
            "response": response.model_dump(mode="json"),
        }

    return read


def _wiki_query_archive_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        archive_request = QueryArchiveRequest.model_validate(policy.canonical_parameters)
        service = wiki_workflow_service(request)
        plan = service.plan_query_archive(archive_request)
        marker = _workflow_action_marker(claim.idempotency_key)
        paths = [plan.target_path, WIKI_INDEX_PATH, WIKI_LOG_PATH]
        before = markdown_snapshot(service.wiki.writer, paths)
        archive_id = _stable_effect_id("wiki-archive", claim.idempotency_key)
        try:
            response = service.archive_query(
                archive_request,
                archive_id=archive_id,
                action_marker=marker,
            )
        except Exception:
            # Retry only when the first pass left an observable stage behind.
            # Replaying a clean failure can duplicate external work or hide a
            # permanent validation error; a marker/row proves this is a
            # recoverable partial workflow and the stable IDs make the replay
            # idempotent.
            if not _wiki_query_archive_has_partial_effect(
                service,
                archive_id=archive_id,
                target_path=plan.target_path,
                marker=marker,
            ):
                raise
            response = service.archive_query(
                archive_request,
                archive_id=archive_id,
                action_marker=marker,
            )
        after = markdown_snapshot(service.wiki.writer, paths)
        state = {
            "archive_id": response.archive_id,
            "target_path": response.page.relative_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "target_ref": response.page.relative_path,
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(response.page.relative_path,),
        )

    return execute


def _wiki_query_archive_has_partial_effect(
    service: Any,
    *,
    archive_id: str,
    target_path: str,
    marker: str,
) -> bool:
    """Detect a durable stage before attempting a workflow resume."""
    try:
        path = service.wiki.writer.resolve_markdown_path(target_path)
        if path.exists() and marker in path.read_text(encoding="utf-8"):
            return True
    except (OSError, UnicodeDecodeError):
        pass
    try:
        with service.database.session() as conn:
            row = conn.execute(
                "SELECT 1 FROM wiki_query_archives WHERE id = ?",
                (archive_id,),
            ).fetchone()
    except Exception:
        return False
    return row is not None


def _wiki_query_archive_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        expected = _receipt_expected_state(receipt)
        archive_id = _stable_effect_id("wiki-archive", receipt.idempotency_key)
        service = wiki_workflow_service(request)
        try:
            detail = service.get_query_archive(archive_id)
        except Exception:
            return None
        marker = _workflow_action_marker(receipt.idempotency_key)
        if not _wiki_marked_effect_exists(
            service.wiki,
            target_path=detail.target_path,
            marker=marker,
            require_index=True,
            require_log=True,
        ):
            return None
        parameters = _receipt_canonical_parameters(receipt)
        if parameters is not None:
            archive_request = QueryArchiveRequest.model_validate(parameters)
            response = QueryArchiveResponse(
                archive_id=archive_id,
                page=detail.page,
                lint=service.lint_query_archive(archive_request),
            )
        else:
            response_raw = expected.get("response")
            if not isinstance(response_raw, Mapping):
                return None
            response = QueryArchiveResponse.model_validate(response_raw)
        return {
            "archive_id": archive_id,
            "target_path": detail.target_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "target_ref": detail.target_path,
            "state_ref": f"wiki-archive:{archive_id}",
            "response": response.model_dump(mode="json"),
        }

    return read


def _wiki_synthesis_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        synthesize_request = WikiSynthesizeRequest.model_validate(policy.canonical_parameters)
        service = wiki_workflow_service(request)
        plan = service.plan_synthesis(synthesize_request)
        marker = _workflow_action_marker(claim.idempotency_key)
        paths = [plan.target_path, WIKI_INDEX_PATH, WIKI_LOG_PATH]
        before = markdown_snapshot(service.wiki.writer, paths)
        response = service.synthesize(synthesize_request, action_marker=marker)
        after = markdown_snapshot(service.wiki.writer, paths)
        state = {
            "target_path": response.page.relative_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "target_ref": response.page.relative_path,
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(response.page.relative_path,),
        )

    return execute


def _wiki_synthesis_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        parameters = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        target_path = expected.get("target_path")
        if not isinstance(target_path, str) and parameters is not None:
            title = str(parameters.get("title") or receipt.normalized_target)
            target_path = resolve_wiki_path(title, _optional_string(parameters.get("target_path")))
        marker = _workflow_action_marker(receipt.idempotency_key)
        service = wiki_workflow_service(request)
        if not isinstance(target_path, str) or not _wiki_marked_effect_exists(
            service.wiki,
            target_path=target_path,
            marker=marker,
            require_index=True,
            require_log=True,
        ):
            return None
        response_raw = expected.get("response")
        if not isinstance(response_raw, Mapping):
            response_raw = {
                "page": {
                    "title": str(parameters.get("title") if parameters else receipt.normalized_target),
                    "relative_path": target_path,
                    "operation": "replace_section",
                    "status": "updated",
                },
                "index_updated": True,
                "log_appended": True,
            }
        return {
            "target_path": target_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "target_ref": target_path,
            "state_ref": target_path,
            "response": dict(response_raw),
        }

    return read


def _wiki_lint_report_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        lint_request = WikiLintRequest.model_validate(policy.canonical_parameters)
        marker = _workflow_action_marker(claim.idempotency_key)
        lint_service = wiki_lint_service(request)
        try:
            before = markdown_snapshot(lint_service.wiki.writer, [WIKI_INDEX_PATH, WIKI_LOG_PATH])
            response = lint_service.run(lint_request, action_marker=marker)
            if response.report_page is None:
                raise RuntimeError("wiki_lint_report_missing")
            lint_service.wiki.refresh_index()
            paths = [response.report_page.relative_path, WIKI_INDEX_PATH, WIKI_LOG_PATH]
            after = markdown_snapshot(lint_service.wiki.writer, paths)
        finally:
            lint_service.close()
        state = {
            "target_path": response.report_page.relative_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "summary": response.summary,
            "target_ref": response.report_page.relative_path,
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(response.report_page.relative_path,),
        )

    return execute


def _wiki_lint_report_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        expected = _receipt_expected_state(receipt)
        marker = _workflow_action_marker(receipt.idempotency_key)
        service = wiki_service(request)
        target_path = expected.get("target_path")
        if not isinstance(target_path, str):
            target_path = _find_marked_wiki_page(service, marker, prefix="Wiki/Reports/Lint-")
        if not isinstance(target_path, str) or not _wiki_marked_effect_exists(
            service,
            target_path=target_path,
            marker=marker,
            require_index=True,
            require_log=True,
        ):
            return None
        response_raw = expected.get("response")
        if not isinstance(response_raw, Mapping):
            return None
        return {
            "target_path": target_path,
            "action_marker": marker,
            "index_updated": True,
            "log_appended": True,
            "summary": expected.get("summary") or {},
            "target_ref": target_path,
            "state_ref": target_path,
            "response": dict(response_raw),
        }

    return read


def _wiki_ingest_apply_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        apply_request = WikiIngestApplyRequest.model_validate(policy.canonical_parameters)
        marker = _workflow_action_marker(claim.idempotency_key)
        service = wiki_workflow_service(request)
        response = service.apply_ingest(apply_request, action_marker=marker)
        target_paths = [
            result.relative_path
            for result in response.page_results
            if result.status in {"created", "updated"}
        ]
        state = {
            "run_id": response.run_id,
            "target_paths": target_paths,
            "action_marker": marker,
            "index_updated": response.index_updated,
            "log_appended": response.log_appended,
            "status": response.status,
            "pages_written": response.pages_written,
            "target_ref": f"wiki-ingest:{response.run_id}",
            "response": response.model_dump(mode="json"),
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state},
            after_snapshot={"run_id": response.run_id, "target_paths": target_paths},
            target_paths=tuple(target_paths),
        )

    return execute


def _wiki_ingest_apply_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        expected = _receipt_expected_state(receipt)
        run_id = str(expected.get("run_id") or "")
        marker = _workflow_action_marker(receipt.idempotency_key)
        if not run_id:
            params = _receipt_canonical_parameters(receipt) or {}
            run_id = str(params.get("run_id") or "")
        if not run_id:
            return None
        with database(request).session() as conn:
            row = conn.execute(
                "SELECT status, result_json FROM wiki_workflow_runs WHERE id = ? AND workflow_type = 'ingest'",
                (run_id,),
            ).fetchone()
        if row is None or str(row["status"]) not in {"applied", "partial", "failed"}:
            return None
        target_paths = _string_values(expected.get("target_paths"))
        service = wiki_service(request)
        if target_paths and any(
            not _wiki_marked_effect_exists(
                service,
                target_path=path,
                marker=marker,
                require_index=str(row["status"]) != "failed",
                require_log=str(row["status"]) != "failed",
            )
            for path in target_paths
        ):
            return None
        response_raw = expected.get("response")
        if not isinstance(response_raw, Mapping):
            return None
        return {
            "run_id": run_id,
            "target_paths": target_paths,
            "action_marker": marker,
            "index_updated": bool(expected.get("index_updated")),
            "log_appended": bool(expected.get("log_appended")),
            "status": str(row["status"]),
            "pages_written": int(expected.get("pages_written") or 0),
            "target_ref": f"wiki-ingest:{run_id}",
            "state_ref": f"wiki-ingest:{run_id}",
            "response": dict(response_raw),
        }

    return read


def _wiki_marked_effect_exists(
    service,
    *,
    target_path: str,
    marker: str,
    require_index: bool,
    require_log: bool,
) -> bool:
    path = service.writer.resolve_markdown_path(target_path)
    try:
        if not path.exists() or marker not in path.read_text(encoding="utf-8"):
            return False
        if require_index:
            index = service.writer.resolve_markdown_path(WIKI_INDEX_PATH)
            if not index.exists() or target_path not in index.read_text(encoding="utf-8"):
                return False
        if require_log:
            log = service.writer.resolve_markdown_path(WIKI_LOG_PATH)
            if not log.exists() or marker not in log.read_text(encoding="utf-8"):
                return False
    except (OSError, UnicodeDecodeError):
        return False
    return True


def _find_marked_wiki_page(service, marker: str, *, prefix: str) -> str | None:
    root = service.writer.vault_root
    matches: list[str] = []
    for path in root.rglob("*.md"):
        try:
            relative = path.relative_to(root).as_posix()
            if relative.startswith(prefix) and marker in path.read_text(encoding="utf-8"):
                matches.append(relative)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
    return matches[0] if len(matches) == 1 else None


def _wiki_action_target(policy: PolicyDecision) -> tuple[str, str, str]:
    params = policy.canonical_parameters
    title = str(params.get("title") or policy.normalized_target or "Knowledge note")
    target_path = resolve_wiki_path(title, _optional_string(params.get("target_path")))
    content = str(params.get("content") or "")
    return title, target_path, content


def _wiki_answer_summary_target(policy: PolicyDecision) -> tuple[str, str, str]:
    params = policy.canonical_parameters
    raw_target = _optional_string(params.get("target_path")) or _optional_string(params.get("target_ref"))
    if not raw_target:
        raise ValueError("wiki_summary_target_missing")
    target_path = raw_target.replace("\\", "/")
    if not target_path.startswith("Wiki/Companion/Summaries/") or not target_path.endswith(".md"):
        raise ValueError("wiki_summary_target_invalid")
    title = str(params.get("title") or target_path.rsplit("/", 1)[-1][:-3]).strip()
    content = str(params.get("content") or "").strip()
    if not content:
        raise ValueError("wiki_summary_content_missing")
    return title, target_path, content


def _wiki_answer_summary_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        title, target_path, content = _wiki_answer_summary_target(policy)
        marker = _workflow_action_marker(claim.idempotency_key)
        service = wiki_service(request)
        paths = [target_path, WIKI_INDEX_PATH, WIKI_LOG_PATH]
        before = markdown_snapshot(service.writer, paths)
        response = service.write_page(
            WikiPageWriteRequest.model_validate(
                {
                    "title": title,
                    "content": f"{marker}\n{content}",
                    "operation": "replace_section",
                    "target_path": target_path,
                    "section": "来源摘要",
                    "tags": _string_values(policy.canonical_parameters.get("tags"))
                    or ["companion-summary", "auto-wiki", "chat-distilled"],
                    "links": _string_values(policy.canonical_parameters.get("links")),
                    "source_message_id": proposal.source_message_id,
                    "type": "source",
                    "confidence": "medium",
                    "authors": _string_values(policy.canonical_parameters.get("authors"))
                    or ["chat_answer_wiki_summary_agent"],
                    "sources": _string_values(policy.canonical_parameters.get("sources")),
                }
            ),
            action_marker=marker,
        )
        service.refresh_index()
        service.append_log(
            "auto-summary",
            title,
            str(policy.canonical_parameters.get("log_details") or f"- Page: `{target_path}`"),
            dedupe_marker=marker,
        )
        after = markdown_snapshot(service.writer, paths)
        state = {
            "target_path": response.relative_path,
            "title": response.title,
            "action_marker": marker,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "index_updated": True,
            "log_appended": True,
            "target_ref": response.relative_path,
        }
        return AdapterExecutionResult(
            result={"expected_state": state, **state, "response": response.model_dump(mode="json")},
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(response.relative_path,),
        )

    return execute


def _wiki_answer_summary_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        if params is not None:
            target_path = _optional_string(params.get("target_path")) or _optional_string(params.get("target_ref"))
            content = str(params.get("content") or "").strip()
        else:
            target_path = expected.get("target_path")
            content = ""
        marker = _workflow_action_marker(receipt.idempotency_key)
        if not isinstance(target_path, str) or not target_path.startswith("Wiki/Companion/Summaries/") or not target_path.endswith(".md"):
            return None
        service = wiki_service(request)
        if not _wiki_marked_effect_exists(service, target_path=target_path, marker=marker, require_index=True, require_log=True):
            return None
        path = service.writer.resolve_markdown_path(target_path)
        try:
            page = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        if content and content not in page:
            return None
        expected_hash = _optional_string(expected.get("content_hash"))
        observed_content = content or _wiki_summary_section_content(page, marker)
        if observed_content is None:
            return None
        if expected_hash and hashlib.sha256(observed_content.encode("utf-8")).hexdigest() != expected_hash:
            return None
        return {
            "target_path": target_path,
            "target_ref": target_path,
            "action_marker": marker,
            "title": str(expected.get("title") or target_path.rsplit("/", 1)[-1][:-3]),
            "index_updated": True,
            "log_appended": True,
            "content_hash": expected_hash or (hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None),
        }

    return read


def _wiki_summary_section_content(page: str, marker: str) -> str | None:
    """Extract the content written under the summary section for recovery.

    Normal receipts retain canonical parameters, but a process can be
    interrupted after the adapter writes and before its receipt is durable.
    Recovery then has only the expected hash, so parse the known section and
    remove the metadata block that ``WikiService`` appends after the content.
    """
    match = re.search(
        r"^##\s+来源摘要\s*$\n(.*?)(?=^##\s+|\Z)",
        page,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        return None
    body = match.group(1).strip()
    if not body.startswith(marker):
        return None
    content = body[len(marker):].strip()
    metadata = re.search(r"\n(?:Tags|Links):\s", content)
    if metadata is not None:
        content = content[: metadata.start()].rstrip()
    return content or None


def _wiki_action_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        title, target_path, content = _wiki_action_target(policy)
        params = policy.canonical_parameters
        marker = f"<!-- llmwiki-action:{claim.idempotency_key} -->"
        body = f"{marker}\n{content}".rstrip()
        service = wiki_service(request)
        refresh_wiki_index = bool(params.get("refresh_wiki_index"))
        append_wiki_log = bool(params.get("append_wiki_log"))
        snapshot_paths = [target_path]
        if refresh_wiki_index:
            snapshot_paths.append(WIKI_INDEX_PATH)
        if append_wiki_log:
            snapshot_paths.append(WIKI_LOG_PATH)
        before = markdown_snapshot(service.writer, snapshot_paths)
        response = service.write_page(
            _wiki_page_write_request(
                proposal=proposal,
                policy=policy,
                content=body,
                idempotency_key=claim.idempotency_key,
            )
        )
        if refresh_wiki_index:
            service.refresh_index()
        if append_wiki_log:
            service.append_log(
                str(params.get("log_operation") or "agent-action"),
                str(params.get("log_title") or title),
                str(params.get("log_details") or f"- Page: `{response.relative_path}`"),
                dedupe_marker=marker,
            )
        after = markdown_snapshot(service.writer, snapshot_paths)
        expected_state = {
            "target_path": response.relative_path,
            "action_marker": marker,
            "title": response.title,
            "target_ref": response.relative_path,
            "index_updated": refresh_wiki_index,
            "log_appended": append_wiki_log,
        }
        return AdapterExecutionResult(
            result={
                "expected_state": expected_state,
                **expected_state,
                "target_path": response.relative_path,
                "title": response.title,
                "operation": response.operation,
                "status": response.status,
                "index_job_id": response.index_job_id,
                "response": response.model_dump(mode="json"),
            },
            before_snapshot=before,
            after_snapshot=after,
            target_paths=(response.relative_path,),
        )

    return execute


def _wiki_page_write_request(
    *,
    proposal: ActionProposal,
    policy: PolicyDecision,
    content: str,
    idempotency_key: str,
) -> WikiPageWriteRequest:
    params = policy.canonical_parameters
    title, target_path, _ = _wiki_action_target(policy)
    operation = str(params.get("operation") or "replace_section")
    if operation not in {"create", "append", "replace_section"}:
        raise ValueError("wiki_operation_invalid")
    section = _optional_string(params.get("section"))
    if operation == "replace_section" and section is None:
        section = f"Agent action {idempotency_key[:12]}"
    return WikiPageWriteRequest.model_validate(
        {
            "title": title,
            "content": content,
            "operation": operation,
            "target_path": target_path,
            "section": section,
            "tags": _string_values(params.get("tags")) or ["agent-chat"],
            "links": _string_values(params.get("links")),
            "source_message_id": proposal.source_message_id,
            "type": _optional_string(params.get("page_type")),
            "confidence": _optional_string(params.get("confidence")),
            "expiry": _optional_string(params.get("expiry")),
            "authors": _string_values(params.get("authors")),
            "contributors": _string_values(params.get("contributors")),
            "disputed": bool(params.get("disputed")),
            "aliases": _string_values(params.get("aliases")),
            "sources": _string_values(params.get("sources")),
            "entity_ids": _string_values(params.get("entity_ids")),
            "fact_ids": _string_values(params.get("fact_ids")),
            "inference": bool(params.get("inference")),
            "target_content_hash": _optional_string(params.get("target_content_hash")),
        }
    )


def _wiki_action_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        parameters = _receipt_canonical_parameters(receipt)
        expected = _receipt_expected_state(receipt)
        if parameters is not None:
            title = str(parameters.get("title") or receipt.normalized_target or "Knowledge note")
            target_path = resolve_wiki_path(title, _optional_string(parameters.get("target_path")))
            marker = f"<!-- llmwiki-action:{receipt.idempotency_key} -->"
        else:
            target_path = expected.get("target_path")
            marker = expected.get("action_marker")
            if not isinstance(target_path, str) or not isinstance(marker, str):
                return None
        service = wiki_service(request)
        path = service.writer.resolve_markdown_path(target_path)
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8")
        if marker not in content:
            return None
        index_updated = bool(parameters.get("refresh_wiki_index")) if parameters is not None else bool(expected.get("index_updated"))
        log_appended = bool(parameters.get("append_wiki_log")) if parameters is not None else bool(expected.get("log_appended"))
        if index_updated:
            index_path = service.writer.resolve_markdown_path(WIKI_INDEX_PATH)
            if not index_path.exists() or target_path not in index_path.read_text(encoding="utf-8"):
                return None
        if log_appended:
            log_path = service.writer.resolve_markdown_path(WIKI_LOG_PATH)
            if not log_path.exists() or marker not in log_path.read_text(encoding="utf-8"):
                return None
        return {
            "target_path": target_path,
            "action_marker": marker,
            "title": str(parameters.get("title") or receipt.normalized_target)
            if parameters is not None
            else str(expected.get("title") or receipt.normalized_target),
            "target_ref": target_path,
            "state_ref": target_path,
            "index_updated": index_updated,
            "log_appended": log_appended,
        }

    return read


def _wiki_plan_action_adapter(request: Request):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        kind = str(params.get("kind") or "ingest")
        title = str(params.get("title") or "Knowledge note")
        content = str(params.get("content") or "")
        target_path = _optional_string(params.get("target_path"))
        workflow = RuntimeWikiWorkflowAdapter(request)
        if kind == "query_archive":
            planned = await workflow.plan_query_archive(
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
            planned = await workflow.plan_synthesis(
                WikiSynthesizeRequest(
                    title=title,
                    content=content,
                    source_paths=_string_values(params.get("source_paths")),
                    target_path=target_path,
                )
            )
        elif kind == "lint":
            planned = await workflow.plan_lint(WikiLintRequest(write_report=True))
        else:
            planned = await workflow.preview_ingest(
                WikiIngestPreviewRequest(
                    title=title,
                    content=content,
                    tags=["agent-chat", "wiki-proposal"],
                    max_pages=5,
                )
            )
        state, raw = _wiki_plan_projection(
            planned,
            idempotency_key=claim.idempotency_key,
            fallback_title=title,
        )
        return AdapterExecutionResult(
            result={"expected_state": state, "proposal": raw, **state},
            after_snapshot=state,
            target_paths=tuple(_string_values(state.get("target_paths"))),
        )

    return execute


def _wiki_plan_action_reader(request: Request):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        # Wiki planning APIs are intentionally read-only.  Their verified
        # result is the immutable proposal stored in the action receipt; a
        # Markdown lookup here would incorrectly turn a plan into a write.
        expected = _receipt_expected_state(receipt)
        return expected or None

    return read


def _wiki_plan_projection(
    planned: object,
    *,
    idempotency_key: str,
    fallback_title: str,
) -> tuple[dict[str, object], dict[str, object]]:
    dumped = planned.model_dump(mode="json") if hasattr(planned, "model_dump") else {}
    raw = dict(dumped) if isinstance(dumped, Mapping) else {}
    proposal_type = str(raw.get("proposal_type") or "ingest")
    target_path = raw.get("target_path")
    targets = [str(target_path)] if isinstance(target_path, str) and target_path else []
    page_plans = raw.get("page_plans")
    if not targets and isinstance(page_plans, list):
        targets = [
            str(item.get("target_path"))
            for item in page_plans
            if isinstance(item, Mapping) and item.get("target_path")
        ]
    recommended = _string_values(raw.get("recommended_targets")) or targets
    state: dict[str, object] = {
        "proposal_type": proposal_type,
        "status": str(raw.get("status") or "planned"),
        "title": str(raw.get("title") or fallback_title),
        "target_paths": targets,
        "recommended_targets": recommended,
        "markdown_preview": str(raw.get("markdown_preview") or ""),
        "summary": str(raw.get("summary") or ""),
        "state_ref": f"wiki-plan:{idempotency_key}",
    }
    for key in ("run_id", "source_id", "source_hash", "review_id", "review_status", "source_message_id"):
        value = raw.get(key)
        if value is not None:
            state[key] = value
    lint = raw.get("lint")
    if isinstance(lint, Mapping):
        state["errors"] = _string_values(lint.get("errors"))
        state["warnings"] = _string_values(lint.get("warnings"))
    if proposal_type == "lint":
        state["write_report"] = bool(raw.get("write_report"))
        summary = raw.get("summary")
        state["lint_summary"] = dict(summary) if isinstance(summary, Mapping) else {}
        issues = raw.get("issues")
        state["findings"] = list(issues) if isinstance(issues, list) else []
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


def _string_values(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _memory_graph_action_adapter(request: Request | AppContext):
    def execute(proposal: ActionProposal, policy: PolicyDecision, claim: ExecutionClaim):
        from app.api.memory.graph import execute_graph_action_effect

        return execute_graph_action_effect(request, proposal, claim)

    return execute


def _memory_graph_action_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt):
        from app.api.memory.graph import read_graph_action_state

        return read_graph_action_state(request, receipt)

    return read


def _memory_graph_rebuild_adapter(request: Request | AppContext):
    def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        del proposal, policy
        from app.services.memory_graph_kuzu import KuzuGraphService

        settings = get_settings()
        vault_id = cached_active_vault_id(request)
        service = KuzuGraphService(
            database(request).path,
            settings.data_dir / "memory-graph",
            vault_id=vault_id,
            vault_root=active_vault_root(request) if vault_id else None,
        )
        try:
            report = service.rebuild()
        finally:
            service.close()
        state: dict[str, object] = {
            "status": report.generation.status,
            "backend": "kuzu",
            "generation_id": report.generation.id,
            "source_revision": report.source_revision,
            "degraded": report.fallback_reason is not None,
            "fallback_code": report.fallback_reason,
            "state_ref": f"memory-graph-generation:{report.generation.id}",
        }
        return AdapterExecutionResult(
            result={
                "expected_state": state,
                "node_count": report.node_count,
                "edge_count": report.edge_count,
                **state,
            },
            after_snapshot=state,
        )

    return execute


def _memory_graph_rebuild_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        expected = _receipt_expected_state(receipt)
        generation_id = _optional_string(expected.get("generation_id"))
        with database(request).session() as conn:
            revision_row = conn.execute("SELECT revision FROM graph_source_state WHERE id = 1").fetchone()
            source_revision = int(revision_row[0]) if revision_row is not None else 0
            if generation_id:
                row = conn.execute(
                    "SELECT id, source_revision, status, error_code FROM graph_projection_generations WHERE id = ?",
                    (generation_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT id, source_revision, status, error_code
                    FROM graph_projection_generations
                    WHERE backend = 'kuzu'
                    ORDER BY COALESCE(built_at, '' ) DESC, id DESC
                    LIMIT 1
                    """
                ).fetchone()
        if row is None or int(row[1]) != source_revision:
            return None
        status = str(row[2])
        fallback_code = str(row[3] or "") or None
        if generation_id and str(row[0]) != generation_id:
            return None
        if not generation_id:
            try:
                action = agent_action_service(request).get(receipt.claim_id)
            except Exception:
                return None
            built_at = _generation_built_at(request, str(row[0]))
            if built_at is None or built_at < str(action.created_at):
                return None
        return {
            "status": status,
            "backend": "kuzu",
            "generation_id": str(row[0]),
            "source_revision": source_revision,
            "degraded": status != "active" or fallback_code is not None,
            "fallback_code": fallback_code,
            "state_ref": f"memory-graph-generation:{row[0]}",
        }

    return read


def _generation_built_at(request: Request | AppContext, generation_id: str) -> str | None:
    with database(request).session() as conn:
        row = conn.execute(
            "SELECT built_at FROM graph_projection_generations WHERE id = ?",
            (generation_id,),
        ).fetchone()
    return str(row[0]) if row is not None and row[0] else None


# Post-reply stages are background writes, but they are still ordinary
# production actions.  Keeping their adapters beside the other production
# adapters makes the claim -> effect -> authoritative readback contract
# visible in one registry.  The stage modules are imported lazily so tests
# can replace their service factories without bypassing the registry.
def _post_reply_stage_service(request: Request | AppContext, stage: str):
    if stage == "daily":
        from app.services.chat_pipeline import diary as stage_module

        return stage_module.chat_auto_memory_service(request)
    if stage == "structured":
        from app.services.chat_pipeline import diary_memory as stage_module

        return stage_module.diary_memory_service(request)
    if stage == "consolidation":
        from app.services.chat_pipeline import consolidation as stage_module

        return stage_module.memory_consolidation_service(request)
    raise ValueError("post_reply_stage_invalid")


def _post_reply_daily_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        service = _post_reply_stage_service(request, "daily")
        try:
            result = service.append_chat_exchange(
                conversation_id=str(params.get("conversation_id") or ""),
                user_message_id=str(params.get("user_message_id") or ""),
                assistant_message_id=str(params.get("assistant_message_id") or ""),
                agent_run_id=str(params.get("agent_run_id") or claim.source_run_id),
                user_question=str(params.get("user_question") or ""),
                assistant_answer=str(params.get("assistant_answer") or ""),
            )
            entry = result.entry
            state: dict[str, object] = {
                "entry_id": entry.id,
                "conversation_id": entry.conversation_id,
                "user_message_id": entry.user_message_id,
                "assistant_message_id": entry.assistant_message_id,
                "agent_run_id": entry.agent_run_id,
                "entry_hash": entry.entry_hash,
                "memory_date": entry.memory_date,
                "memory_time": entry.memory_time,
                "timezone": entry.timezone,
                "markdown_path": entry.markdown_path,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "state_ref": f"chat-daily:{entry.id}",
            }
            action_metadata = {
                "entry_id": entry.id,
                "index_job_id": result.index_job_id,
            }
            return AdapterExecutionResult(
                result={
                    "expected_state": state,
                    "action_metadata": action_metadata,
                    "written": bool(result.written),
                    "index_job_id": result.index_job_id,
                    **state,
                },
                after_snapshot=state,
                target_paths=(entry.markdown_path,),
            )
        finally:
            service.close()

    return execute


def _post_reply_daily_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or {}
        expected = _receipt_expected_state(receipt)
        agent_run_id = str(params.get("agent_run_id") or expected.get("agent_run_id") or "")
        if not agent_run_id:
            return None
        service = _post_reply_stage_service(request, "daily")
        try:
            entry = service.store.get_by_agent_run_id(agent_run_id)
            if entry is None:
                return None
            path = service.writer.resolve_markdown_path(entry.markdown_path)
            if not path.exists():
                return None
            content = path.read_text(encoding="utf-8")
            # The SQLite row and the Markdown entry are both required.  This
            # prevents a receipt from being recovered after only one half of
            # the daily archive write was applied.
            for marker in (entry.agent_run_id, entry.user_message_id, entry.assistant_message_id):
                if marker not in content:
                    return None
            state = {
                "entry_id": entry.id,
                "conversation_id": entry.conversation_id,
                "user_message_id": entry.user_message_id,
                "assistant_message_id": entry.assistant_message_id,
                "agent_run_id": entry.agent_run_id,
                "entry_hash": entry.entry_hash,
                "memory_date": entry.memory_date,
                "memory_time": entry.memory_time,
                "timezone": entry.timezone,
                "markdown_path": entry.markdown_path,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "target_paths": [entry.markdown_path],
                "written": False,
                "index_job_id": None,
                "state_ref": f"chat-daily:{entry.id}",
            }
            state["action_metadata"] = {
                "entry_id": entry.id,
                "index_job_id": None,
            }
            state["written"] = False
            state["index_job_id"] = None
            return state
        finally:
            service.close()

    return read


def _post_reply_structured_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        agent_run_id = str(params.get("agent_run_id") or claim.source_run_id)
        service = _post_reply_stage_service(request, "structured")
        try:
            result = await service.archive_chat_exchange(
                conversation_id=str(params.get("conversation_id") or ""),
                user_message_id=str(params.get("user_message_id") or ""),
                assistant_message_id=str(params.get("assistant_message_id") or ""),
                agent_run_id=agent_run_id,
                user_question=str(params.get("user_question") or ""),
                assistant_answer=str(params.get("assistant_answer") or ""),
                occurred_at=str(params.get("occurred_at") or utc_now_iso()),
                markdown_path=_optional_string(params.get("markdown_path")),
            )
            # 效果校验只看这次 run 是否真的拥有日记对象。抽取由模型完成,两次
            # 调用的条数本来就不稳定:拿"预估条数"当期望值,既会把正常偏差误判成
            # structured_diary_effect_count_mismatch,也会让幂等键(含参数哈希)
            # 随预估条数漂移,重试时变成另一个动作而重复写入。
            objects_seen = int(result.objects_seen)
            state = _post_reply_structured_state(
                service,
                agent_run_id=agent_run_id,
                # 这次抽取一条都没有 => "完成但零效果"是一个合法的已验证结果。
                # reader 用回执里的同一个数字复现这个判断,两边必须一致。
                allow_empty=objects_seen <= 0,
            )
            if state is None:
                raise _LifecycleAdapterError("structured_diary_effect_incomplete")
            return AdapterExecutionResult(
                result={
                    "expected_state": state,
                    "objects_seen": result.objects_seen,
                    "objects_written": result.objects_written,
                    **state,
                },
                after_snapshot=state,
            )
        finally:
            service.close()

    return execute


def _post_reply_structured_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or {}
        expected = _receipt_expected_state(receipt)
        agent_run_id = str(params.get("agent_run_id") or expected.get("agent_run_id") or "")
        if not agent_run_id:
            return None
        # 只有回执明确声明"这次抽取一条都没抽到"时,空集才算合法结果。
        # 崩溃留下的回执没有这个数字:那时库里真有对象就恢复成功(写入是原子的),
        # 库里没有对象就必须保持未验证,让幂等重试有机会补上。
        allow_empty = _receipt_count(receipt.result.get("objects_seen")) == 0
        service = _post_reply_stage_service(request, "structured")
        try:
            return _post_reply_structured_state(
                service,
                agent_run_id=agent_run_id,
                allow_empty=allow_empty,
            )
        finally:
            service.close()

    return read


def _post_reply_consolidation_adapter(request: Request | AppContext):
    async def execute(
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> AdapterExecutionResult:
        params = policy.canonical_parameters
        user_message, assistant_answer = _post_reply_exchange_text(request, params)
        agent_run_id = _optional_string(params.get("agent_run_id")) or claim.source_run_id
        expected_count = _expected_effect_count(
            params,
            {},
            key="expected_candidate_count",
            fallback_key="candidate_count",
        )
        if expected_count is None:
            raise _LifecycleAdapterError("memory_consolidation_expected_count_missing")
        service = _post_reply_stage_service(request, "consolidation")
        try:
            result = service.consolidate(
                user_message=user_message,
                assistant_answer=assistant_answer,
                conversation_id=_optional_string(params.get("conversation_id")),
                user_message_id=_optional_string(params.get("user_message_id")),
                assistant_message_id=_optional_string(params.get("assistant_message_id")),
                agent_run_id=agent_run_id,
                diary_object_ids=tuple(str(item) for item in params.get("diary_object_ids") or ()),
                diary_markdown_path=_optional_string(params.get("diary_markdown_path")),
            )
            if result.candidate_count != expected_count or result.evidence_count != expected_count:
                raise _LifecycleAdapterError("memory_consolidation_effect_count_mismatch")
            projected = _post_reply_consolidation_state(
                service,
                agent_run_id=agent_run_id,
                expected_count=expected_count,
            )
            if projected is None:
                raise _LifecycleAdapterError("memory_consolidation_effect_incomplete")
            state, action_metadata = projected
            state["skipped_reason"] = result.skipped_reason
            return AdapterExecutionResult(
                result={"expected_state": state, "action_metadata": action_metadata, **state},
                after_snapshot=state,
            )
        finally:
            service.close()

    return execute


def _post_reply_consolidation_reader(request: Request | AppContext):
    def read(receipt: ExecutionReceipt) -> dict[str, object] | None:
        params = _receipt_canonical_parameters(receipt) or {}
        expected = _receipt_expected_state(receipt)
        agent_run_id = str(params.get("agent_run_id") or expected.get("agent_run_id") or "")
        expected_count = _expected_effect_count(
            params,
            expected,
            key="expected_candidate_count",
            fallback_key="candidate_count",
        )
        if not agent_run_id or expected_count is None:
            return None
        service = _post_reply_stage_service(request, "consolidation")
        try:
            projected = _post_reply_consolidation_state(
                service,
                agent_run_id=agent_run_id,
                expected_count=expected_count,
            )
            if projected is None:
                return None
            state, action_metadata = projected
            return {**state, "action_metadata": action_metadata}
        finally:
            service.close()

    return read


def _post_reply_structured_state(
    service: Any,
    *,
    agent_run_id: str,
    allow_empty: bool,
) -> dict[str, object] | None:
    """Authoritative post-effect state for one structured-diary action.

    Used by both the executor and the recovery reader, so the predicate has to
    be knowable from the database plus the receipt: a verified effect means this
    agent run owns the diary objects that this call accounted for.

    ``allow_empty`` carries the one case the database cannot distinguish on its
    own: an extraction that legitimately produced nothing is a completed action
    with zero effects, whereas a crash *before* the first write must stay
    unverified -- otherwise the idempotent retry would be suppressed and the
    memory lost for good.  Only a receipt that declares ``objects_seen == 0``
    grants it, and the executor passes the same flag from its own extraction, so
    both sides always agree.  A crash that landed the effect needs no flag at
    all: the rows are there and the atomic write guarantees they are the whole
    set.
    """
    rows = service.store.conn.execute(
        """
        SELECT DISTINCT o.id
        FROM diary_memory_objects AS o
        JOIN diary_memory_object_sources AS s ON s.object_id = o.id
        WHERE o.vault_id = ? AND s.agent_run_id = ?
        ORDER BY o.id
        """,
        (service.vault_id, agent_run_id),
    ).fetchall()
    object_ids = [str(row[0]) for row in rows]
    if not object_ids and not allow_empty:
        return None
    return {
        "agent_run_id": agent_run_id,
        "object_ids": object_ids,
        "state_ref": f"diary-memory:{agent_run_id}",
        "action_metadata": {"object_ids": object_ids},
    }


def _post_reply_consolidation_state(
    service: Any,
    *,
    agent_run_id: str,
    expected_count: int,
) -> tuple[dict[str, object], dict[str, object]] | None:
    rows = service.store.conn.execute(
        """
        SELECT DISTINCT
            c.id,
            c.status,
            c.memory_kind,
            c.risk_tier,
            c.fact_id,
            c.source_track,
            f.status AS fact_status,
            f.statement_kind,
            EXISTS (
                SELECT 1
                FROM memory_evidence AS bound
                WHERE bound.agent_run_id = ?
                  AND bound.candidate_id = c.id
                  AND bound.fact_id = c.fact_id
            ) AS evidence_bound_to_fact
        FROM memory_candidates AS c
        JOIN memory_evidence AS e ON e.candidate_id = c.id
        LEFT JOIN memory_graph_facts AS f ON f.id = c.fact_id
        WHERE e.agent_run_id = ?
        ORDER BY c.id
        """,
        (agent_run_id, agent_run_id),
    ).fetchall()
    evidence_count = int(
        service.store.conn.execute(
            "SELECT COUNT(*) FROM memory_evidence WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()[0]
    )
    if len(rows) != expected_count or evidence_count != expected_count:
        return None
    explicit_active_rows = [
        row
        for row in rows
        if str(row[1]) == "active"
        and str(row[5]) == "explicit_user"
        and str(row[2]) in {"fact", "preference"}
    ]
    for row in explicit_active_rows:
        if not row[4] or str(row[6]) != "active" or int(row[8]) != 1:
            return None
        # 偏好事实落库为 prefers 关系（relation），普通事实落库为整句 claim。
        expected_kind = "relation" if str(row[2]) == "preference" else "claim"
        if str(row[7]) != expected_kind:
            return None
    candidate_ids = [str(row[0]) for row in rows]
    active_candidate_ids = [str(row[0]) for row in rows if str(row[1]) == "active"]
    active_fact_ids = [str(row[4]) for row in rows if str(row[1]) == "active" and row[4]]
    rejected_count = sum(1 for row in rows if str(row[1]) == "rejected")
    highest_risk_tier = max(
        (str(row[3]) for row in rows),
        key={"low": 0, "medium": 1, "high": 2}.get,
    )
    state: dict[str, object] = {
        "agent_run_id": agent_run_id,
        "expected_candidate_count": expected_count,
        "candidate_ids": candidate_ids,
        "active_candidate_ids": active_candidate_ids,
        "active_fact_ids": active_fact_ids,
        "candidate_count": expected_count,
        "evidence_count": evidence_count,
        "rejected_count": rejected_count,
        "highest_risk_tier": highest_risk_tier,
        "state_ref": f"memory-consolidation:{agent_run_id}",
    }
    action_metadata: dict[str, object] = {
        "candidate_ids": candidate_ids,
        "active_candidate_ids": active_candidate_ids,
        "active_fact_ids": active_fact_ids,
        "candidate_count": expected_count,
        "evidence_count": evidence_count,
        "rejected_count": rejected_count,
        "highest_risk_tier": highest_risk_tier,
        "kinds": sorted({str(row[2]) for row in rows}),
        "statuses": sorted({str(row[1]) for row in rows}),
    }
    return state, action_metadata


def _receipt_count(raw: object) -> int | None:
    """Read a non-negative count from a receipt result.

    0 is a legitimate value here ("the action completed with zero effects"), and
    it is the flag the reader needs to reproduce the executor's own judgement.
    """
    if raw is None or isinstance(raw, bool):
        return None
    try:
        count = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return count if count >= 0 else None


def _expected_effect_count(
    params: Mapping[str, object],
    expected: Mapping[str, object],
    *,
    key: str,
    fallback_key: str,
) -> int | None:
    raw = params.get(key)
    if raw is None:
        raw = expected.get(key)
    if raw is None:
        raw = expected.get(fallback_key)
    if isinstance(raw, bool):
        return None
    try:
        count = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return count if count > 0 else None


def _post_reply_exchange_text(
    request: Request | AppContext,
    params: Mapping[str, object],
) -> tuple[str, str]:
    user_message = str(params.get("user_message") or "")
    assistant_answer = str(params.get("assistant_answer") or "")
    if user_message and assistant_answer:
        return user_message, assistant_answer
    user_message_id = str(params.get("user_message_id") or "")
    assistant_message_id = str(params.get("assistant_message_id") or "")
    if not user_message_id or not assistant_message_id:
        return user_message, assistant_answer
    with database(request).session() as conn:
        rows = conn.execute(
            "SELECT id, content FROM messages WHERE id IN (?, ?)",
            (user_message_id, assistant_message_id),
        ).fetchall()
    values = {str(row[0]): str(row[1] or "") for row in rows}
    return values.get(user_message_id, user_message), values.get(assistant_message_id, assistant_answer)


def production_action_lifecycle(request: Request | AppContext) -> ActionLifecycleCoordinator:
    task_mutation_types = (
        "task.complete",
        "task.approve",
        "task.reject",
        "task.cancel",
        "task.patch",
    )
    wiki_write_types = (
        "wiki.page.write",
        "wiki.answer_summary.write",
        "wiki.ingest.write",
        "wiki.lint.write",
    )
    wiki_plan_types = (
        "wiki.ingest.plan",
        "wiki.query_archive.plan",
        "wiki.synthesize.plan",
        "wiki.lint.plan",
    )
    wiki_adapter = _wiki_action_adapter(request)
    wiki_reader = _wiki_action_reader(request)
    wiki_answer_summary_adapter = _wiki_answer_summary_adapter(request)
    wiki_answer_summary_reader = _wiki_answer_summary_reader(request)
    wiki_plan_adapter = _wiki_plan_action_adapter(request)
    wiki_plan_reader = _wiki_plan_action_reader(request)
    task_mutation_adapter = _task_mutation_adapter(request)
    task_mutation_reader = _task_mutation_reader(request)
    memory_graph_adapter = _memory_graph_action_adapter(request)
    memory_graph_reader = _memory_graph_action_reader(request)
    memory_graph_rebuild_adapter = _memory_graph_rebuild_adapter(request)
    memory_graph_rebuild_reader = _memory_graph_rebuild_reader(request)
    retrospective_report_adapters = {
        action_type: _retrospective_report_adapter(request)
        for action_type in REPORT_ACTION_TYPES.values()
    }
    retrospective_report_readers = {
        action_type: _retrospective_report_reader(request)
        for action_type in REPORT_ACTION_TYPES.values()
    }
    memory_graph_types = (
        "memory.graph.entity",
        "memory.graph.statement",
        "memory.graph.relation",
    )
    post_reply_adapters = {
        "chat.daily_archive": _post_reply_daily_adapter(request),
        "diary.structured_memory": _post_reply_structured_adapter(request),
        "memory.consolidation.candidate": _post_reply_consolidation_adapter(request),
        "memory.consolidation.safety_event": _post_reply_consolidation_adapter(request),
    }
    post_reply_readers = {
        "chat.daily_archive": _post_reply_daily_reader(request),
        "diary.structured_memory": _post_reply_structured_reader(request),
        "memory.consolidation.candidate": _post_reply_consolidation_reader(request),
        "memory.consolidation.safety_event": _post_reply_consolidation_reader(request),
    }
    adapters = {
        "task.create": _task_action_adapter(request),
        "reminder.delivery.reserve": _reminder_delivery_reserve_adapter(request),
        "reminder.delivery.display": _reminder_delivery_display_adapter(request),
        "reminder.delivery.recover": _reminder_delivery_recover_adapter(request),
        "memory.proposal": _memory_action_adapter(request),
        "memory.proposal.confirm": _memory_confirm_adapter(request),
        "memory.proposal.reject": _memory_reject_adapter(request),
        "memory.proposal.defer": _memory_defer_adapter(request),
        "memory.feedback.apply": _memory_feedback_adapter(request),
        "memory.hygiene.apply": _memory_hygiene_adapter(request),
        "metrics.feedback": _metrics_feedback_adapter(request),
        "continuity.proposal.confirm": _continuity_confirm_adapter(request),
        "continuity.proposal.activate": _continuity_confirm_adapter(request),
        "continuity.proposal.reject": _continuity_reject_adapter(request),
        "wiki.ingest.confirm": _wiki_ingest_confirm_adapter(request),
        "wiki.ingest.review": _wiki_ingest_review_adapter(request),
        "wiki.ingest.apply": _wiki_ingest_apply_adapter(request),
        "wiki.query_archive.write": _wiki_query_archive_adapter(request),
        "wiki.synthesize.write": _wiki_synthesis_adapter(request),
        "wiki.lint.report": _wiki_lint_report_adapter(request),
        **{action_type: memory_graph_adapter for action_type in memory_graph_types},
        "memory.graph.rebuild": memory_graph_rebuild_adapter,
        **{action_type: task_mutation_adapter for action_type in task_mutation_types},
        **{action_type: wiki_adapter for action_type in wiki_write_types if action_type != "wiki.answer_summary.write"},
        "wiki.answer_summary.write": wiki_answer_summary_adapter,
        **{action_type: wiki_plan_adapter for action_type in wiki_plan_types},
        **retrospective_report_adapters,
        **post_reply_adapters,
    }
    readers = {
        "task.create": _task_action_reader(request),
        "reminder.delivery.reserve": _reminder_delivery_reserve_reader(request),
        "reminder.delivery.display": _reminder_delivery_display_reader(request),
        "reminder.delivery.recover": _reminder_delivery_recover_reader(request),
        "memory.proposal": _memory_action_reader(request),
        "memory.proposal.confirm": _memory_confirm_reader(request),
        "memory.proposal.reject": _memory_reject_reader(request),
        "memory.proposal.defer": _memory_defer_reader(request),
        "memory.feedback.apply": _memory_feedback_reader(request),
        "memory.hygiene.apply": _memory_hygiene_reader(request),
        "metrics.feedback": _metrics_feedback_reader(request),
        "continuity.proposal.confirm": _continuity_confirm_reader(request),
        "continuity.proposal.activate": _continuity_confirm_reader(request),
        "continuity.proposal.reject": _continuity_reject_reader(request),
        "wiki.ingest.confirm": _wiki_ingest_confirm_reader(request),
        "wiki.ingest.review": _wiki_ingest_review_reader(request),
        "wiki.ingest.apply": _wiki_ingest_apply_reader(request),
        "wiki.query_archive.write": _wiki_query_archive_reader(request),
        "wiki.synthesize.write": _wiki_synthesis_reader(request),
        "wiki.lint.report": _wiki_lint_report_reader(request),
        **{action_type: memory_graph_reader for action_type in memory_graph_types},
        "memory.graph.rebuild": memory_graph_rebuild_reader,
        **{action_type: task_mutation_reader for action_type in task_mutation_types},
        **{action_type: wiki_reader for action_type in wiki_write_types if action_type != "wiki.answer_summary.write"},
        "wiki.answer_summary.write": wiki_answer_summary_reader,
        **{action_type: wiki_plan_reader for action_type in wiki_plan_types},
        **retrospective_report_readers,
        **post_reply_readers,
    }
    return ActionLifecycleCoordinator(
        ledger=ScopedAgentActionLedger(lambda: agent_action_service(request)),
        adapters=adapters,
        readers=readers,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _receipt_canonical_parameters(receipt: ExecutionReceipt) -> dict[str, Any] | None:
    if "canonical_parameters" not in receipt.result:
        return None
    raw = receipt.result.get("canonical_parameters")
    if not isinstance(raw, Mapping):
        raise ValueError("canonical_parameters_invalid")
    return {str(key): value for key, value in raw.items()}


def _receipt_expected_state(receipt: ExecutionReceipt) -> dict[str, Any]:
    raw = receipt.result.get("expected_state")
    if not isinstance(raw, Mapping):
        return {}
    return {str(key): value for key, value in raw.items()}


def agent_runtime(request: Request) -> LangGraphAgentRuntime:
    registry = agent_model_registry(request)
    store = settings_store(request)
    try:
        automation = store.get_automation_settings()
    finally:
        store.close()
    action_lifecycle = production_action_lifecycle(request)
    return LangGraphAgentRuntime(
        AgentRuntimeServices(
            retrieval=RuntimeRetrievalAdapter(request),
            memory=RuntimeMemoryAdapter(request, action_lifecycle),
            tasks=RuntimeTaskAdapter(request, action_lifecycle),
            continuity=RuntimeContinuityAdapter(request, action_lifecycle),
            wiki=RuntimeWikiAdapter(request, action_lifecycle),
            wiki_workflow=RuntimeWikiWorkflowAdapter(request, action_lifecycle),
            companion_retrieval_reports=companion_retrieval_report_store(request),
            model_registry=registry if registry.clients else None,
            automation_settings=automation,
            agent_action_recorder=lambda action: record_agent_action(request, action),
            memory_activation_recorder=memory_activation_recorder(request),
            prompt_profile_provider=prompt_profile_provider(request),
            checkpoint_store=SQLiteCheckpointStore(database(request)),
            action_lifecycle=action_lifecycle,
            allow_ephemeral_lifecycle=False,
        )
    )
