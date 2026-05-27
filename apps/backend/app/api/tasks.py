from fastapi import APIRouter, Depends, Request

from ..models.api import (
    CurrentTaskResponse,
    TaskApprovalResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskListResponse,
    TaskLogsResponse,
    TaskStepsResponse,
    TaskWorkspaceItem,
)
from ..services.tasks import TaskService, display_timezone_name
from .wiring import audit_reason, map_task_error, record_audit, task_service_dependency

router = APIRouter(prefix="/tasks", tags=["tasks"])


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
    service: TaskService = Depends(task_service_dependency),
) -> TaskCreateResponse:
    try:
        result = service.create(
            title=create_request.title,
            description=create_request.description,
            due_at=create_request.due_at,
            remind_at=create_request.remind_at,
            timezone=create_request.timezone,
            source_text=create_request.source_text,
        )
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
            task_id=result.task.id,
            reminder_id=result.reminder.id if result.reminder else None,
        ),
    )
    return TaskCreateResponse(
        task_id=result.task.id,
        reminder_id=result.reminder.id if result.reminder else None,
        status=result.task.status.value,
        metadata={
            **result.metadata,
            "title": result.task.title,
            "reminder_status": result.reminder.status.value if result.reminder else "",
            "remind_at": result.reminder.remind_at_utc if result.reminder else "",
            "timezone": result.reminder.time_parse_timezone if result.reminder else result.metadata.get("timezone", ""),
            "timezone_label": display_timezone_name(result.reminder.time_parse_timezone) if result.reminder else result.metadata.get("timezone_label", ""),
        },
    )


@router.post("/{task_id}/complete")
async def complete_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(task_service_dependency),
) -> dict[str, str]:
    try:
        task = service.complete(task_id)
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
        reason=audit_reason(request, task_id=task.id),
    )
    return {"task_id": task.id, "status": task.status.value}


@router.post("/{task_id}/approve", response_model=TaskApprovalResponse)
async def approve_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(task_service_dependency),
) -> TaskApprovalResponse:
    try:
        task = service.approve(task_id)
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
        reason=audit_reason(request, task_id=task.id),
    )
    return TaskApprovalResponse(task_id=task.id, status=task.status.value, approved=True)


@router.post("/{task_id}/reject", response_model=TaskApprovalResponse)
async def reject_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(task_service_dependency),
) -> TaskApprovalResponse:
    try:
        task = service.reject(task_id)
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
        reason=audit_reason(request, task_id=task.id),
    )
    return TaskApprovalResponse(task_id=task.id, status=task.status.value, rejected=True)


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
    service: TaskService = Depends(task_service_dependency),
) -> dict[str, str]:
    try:
        task = service.cancel(task_id)
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
        reason=audit_reason(request, task_id=task.id),
    )
    return {"task_id": task.id, "status": task.status.value}


@router.patch("/{task_id}")
async def patch_task(
    task_id: str,
    patch: dict[str, str],
    request: Request,
    service: TaskService = Depends(task_service_dependency),
) -> dict[str, str]:
    status = patch.get("status")
    if status == "done":
        return await complete_task(task_id, request, service)
    if status == "cancelled":
        return await cancel_task(task_id, request, service)
    try:
        task = service.store.get_task(task_id)
    except Exception as exc:
        raise map_task_error(exc) from exc
    return {"task_id": task.id, "status": task.status.value}


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
