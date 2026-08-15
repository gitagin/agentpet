from fastapi import APIRouter, Depends, Request, status

from ..errors import AppError

from ..models.api import (
    CurrentTaskResponse,
    ReminderDeliveryAttemptResponse,
    ReminderDeliveryReserveRequest,
    ReminderDeliveryResultRequest,
    ReminderRuntimeRecoveryResponse,
    TaskApprovalResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskListResponse,
    TaskLogsResponse,
    TaskStepsResponse,
    TaskWorkspaceItem,
)
from ..services.tasks import TaskService, display_timezone_name
from .idempotency import IdempotencyKeyHeader
from .services.adapters import RuntimeReminderDeliveryAdapter, RuntimeTaskAdapter
from .wiring import audit_reason, map_task_error, record_audit, task_service_dependency
from .wiring import production_action_lifecycle

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post(
    "/reminder-delivery/reservations",
    response_model=ReminderDeliveryAttemptResponse,
)
async def reserve_reminder_delivery(
    delivery_request: ReminderDeliveryReserveRequest,
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
) -> ReminderDeliveryAttemptResponse:
    try:
        result = await RuntimeReminderDeliveryAdapter(
            request,
            production_action_lifecycle(request),
        ).reserve(
            reminder_id=delivery_request.reminder_id,
            trigger_at=delivery_request.trigger_at,
            dispatch_kind=delivery_request.dispatch_kind,
            delivery_idempotency_key=idempotency_key,
        )
        return ReminderDeliveryAttemptResponse.model_validate(result)
    except RuntimeError as exc:
        raise _map_reminder_delivery_error(exc) from exc


@router.post(
    "/reminder-delivery/attempts/{attempt_id}/display",
    response_model=ReminderDeliveryAttemptResponse,
)
async def record_reminder_display_attempt(
    attempt_id: str,
    result_request: ReminderDeliveryResultRequest,
    request: Request,
) -> ReminderDeliveryAttemptResponse:
    try:
        result = await RuntimeReminderDeliveryAdapter(
            request,
            production_action_lifecycle(request),
        ).display(
            attempt_id=attempt_id,
            result_code=result_request.result_code,
            error=result_request.error,
        )
        return ReminderDeliveryAttemptResponse.model_validate(result)
    except RuntimeError as exc:
        raise _map_reminder_delivery_error(exc) from exc


@router.post(
    "/reminder-delivery/recover",
    response_model=ReminderRuntimeRecoveryResponse,
)
async def recover_reminder_runtime(
    request: Request,
    task_service: TaskService = Depends(task_service_dependency),
) -> ReminderRuntimeRecoveryResponse:
    try:
        lifecycle_result = await RuntimeReminderDeliveryAdapter(
            request,
            production_action_lifecycle(request),
        ).recover(
            recovery_run_id=str(request.state.request_id),
            reason="resident_runtime_recovery",
        )
    except RuntimeError as exc:
        raise _map_reminder_delivery_error(exc) from exc
    recovered = task_service.recover_reminders()
    return ReminderRuntimeRecoveryResponse(
        unknown_attempts=int(lifecycle_result.get("unknown_attempts") or 0),
        recovered_reminders=len(recovered),
    )


def _map_reminder_delivery_error(exc: RuntimeError) -> AppError:
    raw_code = str(exc)
    code = raw_code.removeprefix("action_lifecycle_") if raw_code.startswith("action_lifecycle_") else ""
    if code == "reminder_not_found":
        return AppError(
            code,
            "未找到对应提醒，未调用系统通知。",
            status.HTTP_404_NOT_FOUND,
        )
    if code == "reminder_delivery_attempt_not_found":
        return AppError(
            code,
            "未找到通知派发记录。",
            status.HTTP_404_NOT_FOUND,
        )
    if code == "idempotency_key_conflict":
        return AppError(
            code,
            "通知派发请求与已保存记录不一致。",
            status.HTTP_409_CONFLICT,
        )
    if code in {"invalid_reminder_delivery", "invalid_reminder_delivery_result"}:
        return AppError(
            code,
            "系统通知记录请求无效。",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return AppError(
        "reminder_delivery_recovery_required",
        "通知派发状态无法权威确认，系统不会自动重试通知。",
        status.HTTP_409_CONFLICT,
    )


@router.get("", response_model=TaskListResponse)
async def list_tasks(service: TaskService = Depends(task_service_dependency)) -> TaskListResponse:
    return TaskListResponse(tasks=[_task_item(service, task.id) for task in service.list()])


@router.get("/today", response_model=TaskListResponse)
async def list_today_tasks(
    timezone: str | None = None,
    service: TaskService = Depends(task_service_dependency),
) -> TaskListResponse:
    try:
        return TaskListResponse(tasks=[_task_item(service, task.id) for task in service.list_today(timezone)])
    except Exception as exc:
        raise map_task_error(exc) from exc


@router.get("/current", response_model=CurrentTaskResponse)
async def get_current_task(service: TaskService = Depends(task_service_dependency)) -> CurrentTaskResponse:
    task = service.current()
    if task is None:
        return CurrentTaskResponse(task=None)
    return CurrentTaskResponse(task=_workspace_task_item(task))


@router.get("/{task_id}/steps", response_model=TaskStepsResponse)
async def list_task_steps(
    task_id: str,
    service: TaskService = Depends(task_service_dependency),
) -> TaskStepsResponse:
    try:
        return TaskStepsResponse(steps=service.steps_for_task(task_id))
    except Exception as exc:
        raise map_task_error(exc) from exc


@router.get("/{task_id}/logs", response_model=TaskLogsResponse)
async def list_task_logs(
    task_id: str,
    service: TaskService = Depends(task_service_dependency),
) -> TaskLogsResponse:
    try:
        return TaskLogsResponse(logs=service.logs_for_task(task_id))
    except Exception as exc:
        raise map_task_error(exc) from exc


@router.post("", response_model=TaskCreateResponse)
async def create_task(
    create_request: TaskCreateRequest,
    request: Request,
) -> TaskCreateResponse:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).create(create_request)
    except Exception as exc:
        record_audit(
            request,
            action="task.create",
            result="failed",
            reason=audit_reason(request, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.create",
        result="success",
        reason=audit_reason(
            request,
            task_id=result.task_id,
            reminder_id=result.reminder_id,
        ),
    )
    return result


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: str,
    request: Request,
) -> dict[str, str]:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).complete(task_id)
    except Exception as exc:
        record_audit(
            request,
            action="task.complete",
            result="failed",
            reason=audit_reason(request, task_id=task_id, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.complete",
        result="success",
        reason=audit_reason(request, task_id=result["task_id"]),
    )
    return {"task_id": str(result["task_id"]), "status": str(result["status"])}


@router.post("/{task_id}/approve", response_model=TaskApprovalResponse)
async def approve_task(
    task_id: str,
    request: Request,
) -> TaskApprovalResponse:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).approve(task_id)
    except Exception as exc:
        record_audit(
            request,
            action="task.approve",
            result="failed",
            reason=audit_reason(request, task_id=task_id, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.approve",
        result="success",
        reason=audit_reason(request, task_id=result["task_id"]),
    )
    return TaskApprovalResponse(
        task_id=str(result["task_id"]),
        status=str(result["status"]),
        approved=bool(result.get("approved")),
        rejected=bool(result.get("rejected")),
    )


@router.post("/{task_id}/reject", response_model=TaskApprovalResponse)
async def reject_task(
    task_id: str,
    request: Request,
) -> TaskApprovalResponse:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).reject(task_id)
    except Exception as exc:
        record_audit(
            request,
            action="task.reject",
            result="failed",
            reason=audit_reason(request, task_id=task_id, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.reject",
        result="success",
        reason=audit_reason(request, task_id=result["task_id"]),
    )
    return TaskApprovalResponse(
        task_id=str(result["task_id"]),
        status=str(result["status"]),
        approved=bool(result.get("approved")),
        rejected=bool(result.get("rejected")),
    )


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
) -> dict[str, str]:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).cancel(task_id)
    except Exception as exc:
        record_audit(
            request,
            action="task.cancel",
            result="failed",
            reason=audit_reason(request, task_id=task_id, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.cancel",
        result="success",
        reason=audit_reason(request, task_id=result["task_id"]),
    )
    return {"task_id": str(result["task_id"]), "status": str(result["status"])}


@router.patch("/{task_id}")
async def patch_task(
    task_id: str,
    patch: dict[str, str],
    request: Request,
) -> dict[str, str]:
    try:
        result = await RuntimeTaskAdapter(
            request,
            production_action_lifecycle(request),
        ).patch(task_id, patch)
    except Exception as exc:
        record_audit(
            request,
            action="task.patch",
            result="failed",
            reason=audit_reason(request, task_id=task_id, code=exc.__class__.__name__),
        )
        raise map_task_error(exc) from exc
    record_audit(
        request,
        action="task.patch",
        result="success",
        reason=audit_reason(request, task_id=result["task_id"]),
    )
    return {"task_id": str(result["task_id"]), "status": str(result["status"])}


def _task_item(service, task_id: str) -> dict[str, str]:
    task = service.store.get_task(task_id)
    reminder = service.reminder_for_task(task_id)
    item = {
        "task_id": task.id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "due_at": task.due_at_utc or "",
        "source_text": task.source_text or "",
    }
    if reminder is not None:
        item["reminder_id"] = reminder.id
        item["remind_at"] = reminder.remind_at_utc
        item["timezone"] = reminder.time_parse_timezone
        item["timezone_label"] = display_timezone_name(reminder.time_parse_timezone)
        item["reminder_status"] = reminder.status.value
        if reminder.triggered_at:
            item["triggered_at"] = reminder.triggered_at
    return item


def _workspace_task_item(task) -> TaskWorkspaceItem:
    return TaskWorkspaceItem(
        task_id=task.id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        due_at=task.due_at_utc or "",
        source_text=task.source_text or "",
    )
