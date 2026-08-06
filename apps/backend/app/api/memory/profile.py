"""画像投影端点与画像记忆操作。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryProfileActionRequest,
    MemoryProfileActionResponse,
    MemoryProfileAvailableActionResponse,
    MemoryProfileDetailResponse,
    MemoryProfileProjectionItemResponse,
    MemoryProfileProjectionResponse,
    MemoryProfileSourceSummaryResponse,
)
from ...models.common import new_id
from ...services.agent_actions import AgentActionCreate
from ...services.memory_profile_actions import (
    MemoryProfileActionError,
    MemoryProfileActionResult,
    MemoryProfileActionService,
)
from ...services.memory_profile_projection import (
    MemoryProfileProjection,
    MemoryProfileProjectionAction,
    MemoryProfileProjectionDetail,
    MemoryProfileProjectionItem,
    MemoryProfileProjectionService,
    MemoryProfileProjectionSourceSummary,
)
from ..wiring import (
    audit_reason,
    database,
    record_agent_action,
    record_audit,
)
from .dependencies import memory_profile_projection_service_dependency

router = APIRouter(prefix="/memory", tags=["memory"])


async def memory_profile_action_service_dependency(request: Request) -> AsyncIterator[MemoryProfileActionService]:
    # Resolve through the package-level compatibility symbol so existing
    # callers can override the lifecycle factory without depending on this module.
    from app.api import memory as memory_api

    lifecycle = memory_api.memory_lifecycle_service(request)
    try:
        yield MemoryProfileActionService(database(request), lifecycle)
    finally:
        lifecycle.close()


@router.get("/profile-projection", response_model=MemoryProfileProjectionResponse)
async def get_memory_profile_projection(
    limit: int = 120,
    service: MemoryProfileProjectionService = Depends(memory_profile_projection_service_dependency),
) -> MemoryProfileProjectionResponse:
    capped_limit = max(1, min(limit, 300))
    projection = service.build(limit=capped_limit)
    return _memory_profile_projection_response(projection)


@router.get("/profile-projection/items/{item_id}", response_model=MemoryProfileDetailResponse)
async def get_memory_profile_projection_item(
    item_id: str,
    service: MemoryProfileProjectionService = Depends(memory_profile_projection_service_dependency),
) -> MemoryProfileDetailResponse:
    detail = service.get_detail(item_id)
    if detail is None:
        raise AppError(
            code="memory_profile_item_not_found",
            message="没有找到这条记忆详情，请刷新后重试。",
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return _memory_profile_detail_response(detail)


@router.post("/profile-projection/items/{item_id}/actions", response_model=MemoryProfileActionResponse)
async def apply_memory_profile_projection_action(
    item_id: str,
    action_request: MemoryProfileActionRequest,
    request: Request,
    service: MemoryProfileActionService = Depends(memory_profile_action_service_dependency),
) -> MemoryProfileActionResponse:
    try:
        result = service.apply(
            item_id=item_id,
            action=action_request.action,
            confirmed=action_request.confirmed is True,
            expires_at=action_request.expires_at,
        )
    except MemoryProfileActionError as exc:
        if exc.code == "memory_profile_action_failed":
            record_audit(
                request,
                action="memory.profile.action",
                result="failed",
                reason=audit_reason(request, profile_action=action_request.action, code=exc.code),
            )
        raise AppError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
        ) from exc

    _record_profile_action(request, service, result)
    return MemoryProfileActionResponse(ok=True, message=result.user_message, item_id=item_id)


def _record_profile_action(
    request: Request,
    service: MemoryProfileActionService,
    result: MemoryProfileActionResult,
) -> None:
    action = record_agent_action(
        request,
        AgentActionCreate(
            action_id=new_id(),
            action_type="memory.profile.action",
            title="画像记忆已更新",
            summary=result.agent_summary,
            risk_tier="low",
            decision="auto",
            status="completed",
            target_paths=(),
            metadata={
                "profile_item_id": result.item_id,
                "profile_action": result.action,
                "category_label": result.category_label,
                "status_label": result.status_label,
            },
            reversible=False,
        ),
    )
    if result.feedback_event_id:
        service.link_feedback_event_to_action(
            feedback_event_id=result.feedback_event_id,
            action_id=action.action_id,
        )
    record_audit(
        request,
        action="memory.profile.action",
        result="success",
        reason=audit_reason(request, profile_action=result.action),
    )


def _memory_profile_projection_response(projection: MemoryProfileProjection) -> MemoryProfileProjectionResponse:
    return MemoryProfileProjectionResponse(
        generated_at=projection.generated_at,
        identity=[_memory_profile_projection_item_response(item) for item in projection.identity],
        preferences=[_memory_profile_projection_item_response(item) for item in projection.preferences],
        boundaries=[_memory_profile_projection_item_response(item) for item in projection.boundaries],
        projects=[_memory_profile_projection_item_response(item) for item in projection.projects],
        relationships=[_memory_profile_projection_item_response(item) for item in projection.relationships],
        recent_state=[_memory_profile_projection_item_response(item) for item in projection.recent_state],
        conflicts=[_memory_profile_projection_item_response(item) for item in projection.conflicts],
        needs_confirmation=[_memory_profile_projection_item_response(item) for item in projection.needs_confirmation],
        filtered=[_memory_profile_projection_item_response(item) for item in projection.filtered],
    )


def _memory_profile_projection_item_response(item: MemoryProfileProjectionItem) -> MemoryProfileProjectionItemResponse:
    return MemoryProfileProjectionItemResponse(
        id=item.id,
        category=item.category,
        summary=item.summary,
        confidence=item.confidence,
        importance=item.importance,
        status_label=item.status_label,
        risk_label=item.risk_label,
        source_label=item.source_label,
        updated_at=item.updated_at,
        permissions_summary=item.permissions_summary,
        can_revoke=item.can_revoke,
        available_actions=item.available_actions,
    )


def _memory_profile_detail_response(detail: MemoryProfileProjectionDetail) -> MemoryProfileDetailResponse:
    return MemoryProfileDetailResponse(
        id=detail.id,
        summary=detail.summary,
        category_label=detail.category_label,
        status_label=detail.status_label,
        confidence_label=detail.confidence_label,
        importance_label=detail.importance_label,
        source_label=detail.source_label,
        permissions=detail.permissions,
        safety_note=detail.safety_note,
        updated_at=detail.updated_at,
        source_summary=_memory_profile_source_summary_response(detail.source_summary),
        available_actions=[_memory_profile_action_response(action) for action in detail.available_actions],
    )


def _memory_profile_source_summary_response(
    summary: MemoryProfileProjectionSourceSummary | None,
) -> MemoryProfileSourceSummaryResponse | None:
    if summary is None:
        return None
    return MemoryProfileSourceSummaryResponse(
        label=summary.label,
        description=summary.description,
        evidence_count_label=summary.evidence_count_label,
        last_seen_label=summary.last_seen_label,
        safety_note=summary.safety_note,
    )


def _memory_profile_action_response(action: MemoryProfileProjectionAction) -> MemoryProfileAvailableActionResponse:
    return MemoryProfileAvailableActionResponse(
        action=action.action,  # type: ignore[arg-type]
        label=action.label,
        requires_confirmation=action.requires_confirmation,
    )
