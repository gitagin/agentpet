from __future__ import annotations

import hashlib
from datetime import timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BeforeValidator

from ..errors import AppError
from ..models.metrics import (
    LocalImpactResponse,
    RecallFeedbackRequest,
    RecallFeedbackResponse,
    SidecarRecoveryRequest,
    SidecarRecoveryResponse,
)
from ..services.product_metrics import (
    MetricPayloadConflict,
    MetricValidationError,
    ProductMetricsService,
)
from .idempotency import IdempotencyKeyHeader
from .services.adapters import execute_metrics_feedback


router = APIRouter(prefix="/metrics", tags=["metrics"])


def _coerce_window_days(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("metric_window_days_invalid") from exc


MetricWindowDays = Annotated[Literal[7, 30], BeforeValidator(_coerce_window_days)]


async def metrics_service_dependency(request: Request):
    service = ProductMetricsService(request.app.state.database.path)
    try:
        yield service
    finally:
        service.close()


@router.get("/local-impact", response_model=LocalImpactResponse)
async def get_local_impact(
    window_days: MetricWindowDays = 7,
    service: ProductMetricsService = Depends(metrics_service_dependency),
) -> LocalImpactResponse:
    return LocalImpactResponse.model_validate(service.aggregate(window_days=window_days))


@router.post("/sidecar-recovery", response_model=SidecarRecoveryResponse)
async def record_sidecar_recovery(
    recovery: SidecarRecoveryRequest,
    idempotency_key: IdempotencyKeyHeader,
    service: ProductMetricsService = Depends(metrics_service_dependency),
) -> SidecarRecoveryResponse:
    expected_key = hashlib.sha256(
        f"sidecar-recovery:{recovery.incident_id}".encode("utf-8")
    ).hexdigest()
    if idempotency_key != expected_key:
        raise AppError(
            "sidecar_recovery_key_mismatch",
            "Sidecar 恢复回执的幂等键与 incident 不匹配。",
            status.HTTP_409_CONFLICT,
        )

    unhealthy_at = recovery.unhealthy_at.astimezone(timezone.utc).isoformat()
    ready_at = recovery.ready_at.astimezone(timezone.utc).isoformat()
    try:
        unhealthy, ready, was_complete = service.record_sidecar_recovery(
            incident_id=recovery.incident_id,
            unhealthy_at=unhealthy_at,
            ready_at=ready_at,
            cause=recovery.cause,
            restart_attempt=recovery.restart_attempt,
        )
        observed = service.read_sidecar_recovery(
            incident_id=recovery.incident_id,
            unhealthy_at=unhealthy_at,
            ready_at=ready_at,
            cause=recovery.cause,
            restart_attempt=recovery.restart_attempt,
        )
    except MetricPayloadConflict as exc:
        raise AppError(
            "idempotency_payload_conflict",
            "同一个 sidecar incident 已经使用了不同的恢复回执。",
            status.HTTP_409_CONFLICT,
        ) from exc
    except MetricValidationError as exc:
        raise AppError(
            "invalid_sidecar_recovery",
            "Sidecar 恢复回执不符合本地指标契约。",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc

    if observed is None:
        raise AppError(
            "sidecar_recovery_receipt_invalid",
            "Sidecar 恢复事件写入后未能通过权威读回校验。",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    recovery_time_ms = int(
        (recovery.ready_at.astimezone(timezone.utc) - recovery.unhealthy_at.astimezone(timezone.utc)).total_seconds()
        * 1000
    )
    return SidecarRecoveryResponse(
        status="replayed" if was_complete else "recorded",
        incident_id=recovery.incident_id,
        unhealthy_event_id=unhealthy.id,
        ready_event_id=ready.id,
        recovery_time_ms=recovery_time_ms,
    )


@router.post("/recall-feedback", response_model=RecallFeedbackResponse)
async def record_recall_feedback(
    feedback: RecallFeedbackRequest,
    request: Request,
    idempotency_key: IdempotencyKeyHeader,
) -> RecallFeedbackResponse:
    try:
        outcome = await execute_metrics_feedback(
            request,
            idempotency_key=idempotency_key,
            payload=feedback.model_dump(exclude_none=True),
        )
    except MetricValidationError as exc:
        raise AppError(
            "invalid_metric_event",
            "反馈不符合本地指标契约。",
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc
    receipt = outcome.receipt
    if receipt.status != "verified":
        code = receipt.safe_error_code or "metric_feedback_failed"
        if code == "metric_payload_conflict":
            raise AppError(
                "idempotency_payload_conflict",
                "相同 Idempotency-Key 已用于不同反馈。",
                status.HTTP_409_CONFLICT,
            )
        if code in {"invalid_metric_signal", "invalid_metric_feedback", "invalid_metric_reference"}:
            raise AppError(
                code,
                "反馈不符合本地指标契约。",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
        raise AppError(
            code,
            "本地反馈未能确认写入，请稍后查看恢复记录。",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    result = receipt.result
    event_id = str(result.get("event_id") or "")
    if not event_id:
        raise AppError(
            "metric_feedback_receipt_invalid",
            "反馈回执缺少事件标识。",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return RecallFeedbackResponse(
        status="replayed" if outcome.duplicate else "recorded",
        event_id=event_id,
        signal=feedback.signal,
    )
