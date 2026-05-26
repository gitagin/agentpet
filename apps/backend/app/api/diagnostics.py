from fastapi import APIRouter, Depends, Request, status

from ..config import get_settings
from ..errors import AppError
from ..models.api import DiagnosticsExportResponse, LocalStateResetRequest, LocalStateResetResponse
from ..scheduler import ReminderSchedulerProtocol
from ..services.diagnostics import DiagnosticsExporter
from ..services.local_state_reset import LocalStateResetService, RESET_CONFIRMATION_TEXT
from .wiring import cached_active_vault_id, clear_cached_active_vault_id, database
from .wiring import refresh_retrieval_vector_index, reminder_scheduler, reset_chat_runs

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/export", response_model=DiagnosticsExportResponse)
async def export_diagnostics(
    request: Request,
    active_vault_id: str | None = Depends(cached_active_vault_id),
) -> DiagnosticsExportResponse:
    exporter = DiagnosticsExporter(database(request), get_settings())
    return exporter.export(active_vault_id=active_vault_id)


@router.post("/reset-local-state", response_model=LocalStateResetResponse)
async def reset_local_state(
    request: Request,
    reset_request: LocalStateResetRequest,
    scheduler=Depends(reminder_scheduler),
) -> LocalStateResetResponse:
    if reset_request.confirmation != RESET_CONFIRMATION_TEXT:
        raise AppError(
            code="reset_confirmation_required",
            message=f"请输入确认词 {RESET_CONFIRMATION_TEXT} 后再重置本地状态。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    scheduler_available = isinstance(scheduler, ReminderSchedulerProtocol)
    if scheduler_available:
        scheduler.pause()
    try:
        service = LocalStateResetService(database(request), get_settings().data_dir)
        result = service.reset()
        clear_cached_active_vault_id(request)
        reset_chat_runs(request)
        if scheduler_available:
            scheduler.clear()
        refresh_retrieval_vector_index(request)
    finally:
        if scheduler_available:
            scheduler.resume()
    return LocalStateResetResponse(
        status=result.status,
        cleared_tables=result.cleared_tables,
        removed_paths=result.removed_paths,
    )
