from fastapi import APIRouter, Depends

from ..config import get_settings
from ..errors import AppError
from ..models.api import TtsCacheClearResponse, TtsSynthesisRequest, TtsSynthesisResponse
from ..services.settings import SettingsStore
from ..services.tts import TtsService, TtsServiceError
from ..services.tts_cache import TtsAudioCache
from .wiring import settings_store_dependency

router = APIRouter(prefix="/tts", tags=["tts"])


@router.post("/synthesize", response_model=TtsSynthesisResponse)
async def synthesize_tts(
    request: TtsSynthesisRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> TtsSynthesisResponse:
    settings = get_settings()
    cache = TtsAudioCache(settings.data_dir / "cache" / "tts")
    service = TtsService(store, timeout_seconds=settings.model_timeout_seconds, cache=cache)
    try:
        return await service.synthesize(request)
    except TtsServiceError as exc:
        raise AppError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details={"detail": exc.detail} if exc.detail else {},
        ) from exc


@router.delete("/cache", response_model=TtsCacheClearResponse)
async def clear_tts_cache() -> TtsCacheClearResponse:
    settings = get_settings()
    result = TtsAudioCache(settings.data_dir / "cache" / "tts").clear()
    return TtsCacheClearResponse(
        status="cleared",
        cleared_entries=result.cleared_entries,
        cleared_bytes=result.cleared_bytes,
    )
