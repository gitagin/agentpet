from __future__ import annotations

from fastapi import APIRouter, Request

from ..errors import AppError
from ..models.api import GrowthSnapshotResponse
from ..services.growth import GrowthSnapshotService
from .wiring import active_vault_id, active_vault_root, database

router = APIRouter(prefix="/growth", tags=["growth"])


@router.get("/snapshot", response_model=GrowthSnapshotResponse)
async def get_growth_snapshot(request: Request) -> GrowthSnapshotResponse:
    try:
        vault_id = active_vault_id(request)
        vault_root = active_vault_root(request)
    except AppError as exc:
        if exc.code != "vault_not_configured":
            raise
        vault_id = None
        vault_root = None

    with database(request).session() as conn:
        return GrowthSnapshotService(conn, vault_id=vault_id, vault_root=vault_root).snapshot()

