from fastapi import APIRouter, Request

from app.models.visible_continuity import VisibleContinuitySnapshotResponse
from app.services.visible_continuity import VisibleContinuityService

from .wiring import audit_reason, cached_active_vault_id, database, record_audit

router = APIRouter(prefix="/today", tags=["today"])


@router.get("/snapshot", response_model=VisibleContinuitySnapshotResponse)
async def get_today_snapshot(request: Request) -> VisibleContinuitySnapshotResponse:
    vault_id = cached_active_vault_id(request)
    service = VisibleContinuityService(database(request).path, vault_id=vault_id)
    try:
        snapshot = service.snapshot()
    finally:
        service.close()
    record_audit(
        request,
        action="today.snapshot.read",
        result="success",
        reason=audit_reason(
            request,
            vault_configured="true" if vault_id else "false",
            source_count=str(snapshot.today_card.source_count),
        ),
    )
    return snapshot
