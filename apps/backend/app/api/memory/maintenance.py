"""记忆维护端点：整理建议（hygiene）与回顾报告（retrospectives）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, status

from ...errors import AppError
from ...models.api import (
    MemoryHygieneActionRequest,
    MemoryHygieneActionResponse,
    MemoryHygienePreviewResponse,
    MemoryHygieneSuggestionResponse,
    RetrospectiveReportRequest,
    RetrospectiveReportResponse,
    RetrospectiveResponse,
)
from ...services.memory_hygiene_suggestions import (
    MemoryHygieneSuggestion,
    MemoryHygieneSuggestionConfirmationRequired,
    MemoryHygieneSuggestionExpired,
    MemoryHygieneSuggestionService,
)
from ...services.memory_lifecycle import MemoryLifecycleTransitionError
from ...services.retrospectives import RetrospectiveService
from ...utils.time import utc_now_iso
from ..services.adapters import RuntimeMemoryHygieneAdapter, RuntimeRetrospectiveAdapter
from ..wiring import audit_reason, production_action_lifecycle, record_audit
from .dependencies import (
    memory_hygiene_suggestion_service_dependency,
    retrospective_service_dependency,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/hygiene/preview", response_model=MemoryHygienePreviewResponse)
async def preview_memory_hygiene(
    limit: int = 30,
    service: MemoryHygieneSuggestionService = Depends(memory_hygiene_suggestion_service_dependency),
) -> MemoryHygienePreviewResponse:
    suggestions = service.preview(limit=max(1, min(limit, 100)))
    return MemoryHygienePreviewResponse(
        generated_at=datetime.now(timezone.utc).isoformat(),
        suggestions=[_memory_hygiene_suggestion_response(item) for item in suggestions],
    )


@router.post("/hygiene/actions", response_model=MemoryHygieneActionResponse)
async def apply_memory_hygiene_action(
    action_request: MemoryHygieneActionRequest,
    request: Request,
) -> MemoryHygieneActionResponse:
    try:
        response = await RuntimeMemoryHygieneAdapter(
            request,
            production_action_lifecycle(request),
        ).apply(action_request)
    except MemoryHygieneSuggestionConfirmationRequired as exc:
        raise AppError(
            code="hygiene_confirmation_required",
            message="Applying a memory hygiene suggestion requires confirmation.",
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except MemoryHygieneSuggestionExpired as exc:
        raise AppError(
            code="hygiene_suggestion_expired",
            message="This memory hygiene suggestion is no longer available.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    except (KeyError, MemoryLifecycleTransitionError, ValueError) as exc:
        raise AppError(
            code="hygiene_suggestion_apply_failed",
            message="The memory hygiene suggestion could not be applied.",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc
    except RuntimeError as exc:
        error_code = str(exc).removeprefix("action_lifecycle_")
        raise AppError(
            code=error_code or "hygiene_suggestion_recovery_required",
            message="The memory hygiene effect could not be confirmed; no retry was issued automatically.",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    record_audit(
        request,
        action="memory.hygiene.apply",
        result="success",
        reason=audit_reason(request, suggestion_type=response.type, status=response.status),
    )
    return response


@router.get("/retrospectives", response_model=RetrospectiveResponse)
async def get_retrospectives(
    request: Request,
    service: RetrospectiveService = Depends(retrospective_service_dependency),
) -> RetrospectiveResponse:
    windows = service.build_windows()
    record_audit(
        request,
        action="memory.retrospective.read",
        result="success",
        reason=audit_reason(request, windows="1,7,30,90"),
    )
    return RetrospectiveResponse(generated_at=utc_now_iso(), windows=windows)


@router.post("/retrospectives/report", response_model=RetrospectiveReportResponse)
async def write_retrospective_report(
    report_request: RetrospectiveReportRequest,
    request: Request,
) -> RetrospectiveReportResponse:
    try:
        response = await RuntimeRetrospectiveAdapter(
            request,
            production_action_lifecycle(request),
        ).write_report(report_request)
    except RuntimeError as exc:
        error_code = str(exc).removeprefix("action_lifecycle_")
        if error_code == "retrospective_report_requires_vault":
            raise AppError(
                code="vault_not_configured",
                message="生成 Markdown 回顾报告前需要先配置活动 Vault。",
                status_code=status.HTTP_409_CONFLICT,
            ) from exc
        raise AppError(
            code=error_code or "retrospective_report_failed",
            message="回顾报告无法完成权威写入。",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    record_audit(
        request,
        action="memory.retrospective.report.write",
        result="success",
        target_path=response.page.relative_path,
        reason=audit_reason(
            request,
            days=str(report_request.days),
            period=report_request.period or "days",
            action_id=response.action.action_id,
        ),
    )
    return response


def _memory_hygiene_suggestion_response(item: MemoryHygieneSuggestion) -> MemoryHygieneSuggestionResponse:
    return MemoryHygieneSuggestionResponse(
        id=item.id,
        type=item.type,
        title=item.title,
        summary=item.summary,
        impact=item.impact,
        risk_tier=item.risk_tier,
        destructive=item.destructive,
        requires_confirmation=item.requires_confirmation,
        action_label=item.action_label,
    )
