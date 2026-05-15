from fastapi import APIRouter

from ..config import get_settings
from ..models.api import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=settings.app_version,
        database="not_configured",
    )
