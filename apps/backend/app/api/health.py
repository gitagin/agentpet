import logging

from fastapi import APIRouter, Request

from ..config import get_settings
from ..models.api import HealthResponse
from .wiring import database

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    settings = get_settings()
    database_status = "error"
    try:
        with database(request).connect() as conn:
            conn.execute("SELECT 1").fetchone()
        database_status = "ok"
    except Exception as exc:
        logger.warning("health_check: db unreachable: %s", exc)

    components = {
        name: {"status": health.status, "reason": health.reason}
        for name, health in getattr(request.app.state, "component_health", {}).items()
    }
    components_ok = all(component["status"] == "ok" for component in components.values())

    return HealthResponse(
        status="ok" if database_status == "ok" and components_ok else "degraded",
        version=settings.app_version,
        database=database_status,
        components=components,
    )
