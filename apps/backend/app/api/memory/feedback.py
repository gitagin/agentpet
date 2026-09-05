"""记忆反馈与周回顾端点。

周回顾操作此前直接 `await` /feedback 端点函数，同一个用户操作会写两条审计
（memory.feedback.apply + memory.review.action）。现在两个端点共享
`_apply_feedback_and_record`，各自只记一条审计（backlog #12）。
周回顾的裸 SQL 已下沉到 services.memory_review.MemoryReviewQueries。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryFeedbackRequest,
    MemoryFeedbackResponse,
    MemoryReviewActionRequest,
    MemoryReviewResponse,
)
from ...services.memory_review import MemoryReviewService
from ..services.adapters import RuntimeMemoryFeedbackAdapter
from ..wiring import audit_reason, production_action_lifecycle, record_audit
from .dependencies import (
    memory_review_service_dependency,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/feedback", response_model=MemoryFeedbackResponse)
async def apply_memory_feedback(
    feedback_request: MemoryFeedbackRequest,
    request: Request,
) -> MemoryFeedbackResponse:
    return await apply_feedback_and_record(request, feedback_request)


async def apply_feedback_and_record(
    request: Request,
    feedback_request: MemoryFeedbackRequest,
    *,
    audit_action: str = "memory.feedback.apply",
    extra_success_reason: dict[str, str] | None = None,
) -> MemoryFeedbackResponse:
    """Apply a lifecycle feedback operation and record exactly one audit entry."""
    try:
        response = await RuntimeMemoryFeedbackAdapter(
            request,
            production_action_lifecycle(request),
        ).apply(feedback_request)
    except RuntimeError as exc:
        error_code = str(exc).removeprefix("action_lifecycle_")
        if error_code != "memory_feedback_target_not_found":
            record_audit(
                request,
                action=audit_action,
                result="failed",
                reason=audit_reason(
                    request,
                    code=error_code or "memory_feedback_invalid",
                    target_type=feedback_request.target_type,
                    target_id=feedback_request.target_id,
                    operation=feedback_request.operation,
                ),
            )
            raise AppError(
                code=error_code or "memory_feedback_invalid",
                message="记忆反馈操作无法应用。",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"operation": feedback_request.operation, "target_type": feedback_request.target_type},
            ) from exc
        record_audit(
            request,
            action=audit_action,
            result="failed",
            reason=audit_reason(
                request,
                code="memory_feedback_target_not_found",
                target_type=feedback_request.target_type,
                target_id=feedback_request.target_id,
            ),
        )
        raise AppError(
            code="memory_feedback_target_not_found",
            message="未找到要反馈的记忆目标。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"target_type": feedback_request.target_type, "target_id": feedback_request.target_id},
        ) from exc
    record_audit(
        request,
        action=audit_action,
        result="success",
        reason=audit_reason(
            request,
            target_type=response.target_type,
            target_id=response.target_id,
            operation=response.operation,
            feedback_event_id=response.feedback_event_id,
            **(extra_success_reason or {}),
        ),
    )
    return response


@router.get("/reviews/weekly", response_model=MemoryReviewResponse)
async def get_weekly_memory_review(
    request: Request,
    days: int = 7,
    limit: int = 30,
    service: MemoryReviewService = Depends(memory_review_service_dependency),
) -> MemoryReviewResponse:
    response = service.build(days=days, limit=limit)
    record_audit(
        request,
        action="memory.review.read",
        result="success",
        reason=audit_reason(
            request,
            days=str(response.window_days),
            item_count=str(len(response.items)),
        ),
    )
    return response


@router.post("/reviews/weekly/actions", response_model=MemoryFeedbackResponse)
async def apply_weekly_memory_review_action(
    action_request: MemoryReviewActionRequest,
    request: Request,
) -> MemoryFeedbackResponse:
    operation = "make_temporary" if action_request.action == "only_this_week" else action_request.action
    expires_at = None
    if action_request.action == "only_this_week":
        expires_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    return await apply_feedback_and_record(
        request,
        MemoryFeedbackRequest(
            target_type=action_request.target_type,
            target_id=action_request.target_id,
            operation=operation,
            feedback_text=action_request.feedback_text or f"weekly_review:{action_request.action}",
            replacement_text=action_request.replacement_text,
            replacement_subject=action_request.replacement_subject,
            replacement_predicate=action_request.replacement_predicate,
            replacement_object=action_request.replacement_object,
            expires_at=expires_at,
        ),
        audit_action="memory.review.action",
        extra_success_reason={"action": action_request.action},
    )
