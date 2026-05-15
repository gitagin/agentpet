from fastapi import APIRouter, Request, status

from ..config import get_settings
from ..errors import AppError
from ..models.api import DiagnosticsExportResponse, LocalStateResetRequest, LocalStateResetResponse
from ..services.diagnostics import DiagnosticsExporter
from ..services.local_state_reset import LocalStateResetService, RESET_CONFIRMATION_TEXT
from .wiring import database
from .wiring import refresh_retrieval_vector_index

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


@router.get("/export", response_model=DiagnosticsExportResponse)
async def export_diagnostics(request: Request) -> DiagnosticsExportResponse:
    active_vault_id = getattr(request.app.state, "active_vault_id", None)
    exporter = DiagnosticsExporter(database(request), get_settings())
    return exporter.export(active_vault_id=str(active_vault_id) if active_vault_id else None)


@router.post("/reset-local-state", response_model=LocalStateResetResponse)
async def reset_local_state(
    request: Request,
    reset_request: LocalStateResetRequest,
) -> LocalStateResetResponse:
    if reset_request.confirmation != RESET_CONFIRMATION_TEXT:
        raise AppError(
            code="reset_confirmation_required",
            message=f"请输入确认词 {RESET_CONFIRMATION_TEXT} 后再重置本地状态。",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    service = LocalStateResetService(database(request), get_settings().data_dir)
    result = service.reset()
    request.app.state.active_vault_id = None
    request.app.state.chat_runs = {}
    scheduler = getattr(request.app.state, "reminder_scheduler", None)
    if hasattr(scheduler, "jobs"):
        scheduler.jobs.clear()
    refresh_retrieval_vector_index(request)
    return LocalStateResetResponse(
        status=result.status,
        cleared_tables=result.cleared_tables,
        removed_paths=result.removed_paths,
    )
