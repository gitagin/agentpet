from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from app.models.api import TtsSettingsResponse, TtsSynthesisRequest, TtsSynthesisResponse
from app.services.settings import SettingsStore, normalize_tts_provider
from app.services.tts_cache import TtsAudioCache, TtsCachedAudio


SUPPORTED_RESPONSE_FORMATS = {"mp3", "wav", "ogg", "webm", "m4a", "aac", "flac"}
SUPPORTED_AUDIO_ENCODINGS = {"base64", "data-url"}
MIME_BY_FORMAT = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "ogg": "audio/ogg",
    "webm": "audio/webm",
    "m4a": "audio/mp4",
    "aac": "audio/aac",
    "flac": "audio/flac",
}
LOCAL_TTS_PROVIDERS = {"system", "mock"}
TTS_PRESET_PROVIDERS = {"xiaomi-mimo"}
XIAOMI_MIMO_MODEL = "mimo-v2.5-tts"
XIAOMI_MIMO_RESPONSE_FORMAT = "wav"
XIAOMI_MIMO_DEFAULT_VOICE = "Chloe"
XIAOMI_MIMO_BUILTIN_VOICES = {
    "Mia",
    "Chloe",
    "mimo_default",
    "Milo",
    "Dean",
    "冰糖",
    "茉莉",
    "苏打",
    "白桦",
}
_SECRET_RE = re.compile(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{8,}|(?:sk|pk|rk)-[a-z0-9._~+/=-]{8,}")
_SENSITIVE_CACHE_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]|"
    r"(?:sk|pk|rk)-[a-z0-9._~+/=-]{8,}|github_pat_[a-z0-9_]+|gh[pousr]_[a-z0-9_]+"
)


class TtsServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        detail: str | None = None,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail
        self.status_code = status_code


@dataclass(slots=True)
class TtsService:
    store: SettingsStore
    timeout_seconds: float = 30.0
    opener: Any | None = None
    cache: TtsAudioCache | None = None

    async def synthesize(self, request: TtsSynthesisRequest) -> TtsSynthesisResponse:
        settings = self.store.get_tts_settings()
        provider = normalize_tts_provider(request.provider or settings.provider)
        if not settings.enabled:
            raise TtsServiceError("TTS playback is disabled.", code="disabled", status_code=422)
        if provider in LOCAL_TTS_PROVIDERS:
            raise TtsServiceError(
                "本地语音 provider 不需要后端合成。",
                code="local_provider",
                status_code=422,
            )
        if provider != normalize_tts_provider(settings.provider):
            raise TtsServiceError(
                "请求的语音 provider 与当前设置不一致。",
                code="provider_mismatch",
                detail=f"requested={provider}, configured={settings.provider}",
                status_code=422,
            )
        _ensure_ready(settings)

        api_key = self.store.get_tts_key(provider) if settings.requires_api_key else None
        if settings.requires_api_key and not api_key:
            raise TtsServiceError(
                "尚未保存语音 API Key。",
                code="credential_missing",
                status_code=401,
            )

        cache_key = _cache_key_for_request(self.cache, request, settings, provider)
        if cache_key:
            cached = await asyncio.to_thread(self.cache.get, cache_key)
            if cached:
                return _cached_audio_response(provider, cached)

        response = await asyncio.to_thread(
            self.synthesize_with_settings,
            request,
            settings,
            provider,
            api_key,
        )
        if cache_key:
            await asyncio.to_thread(_store_audio_response, self.cache, cache_key, provider, response)
        return response

    def synthesize_blocking(self, request: TtsSynthesisRequest) -> TtsSynthesisResponse:
        settings = self.store.get_tts_settings()
        provider = normalize_tts_provider(request.provider or settings.provider)
        if not settings.enabled:
            raise TtsServiceError("TTS playback is disabled.", code="disabled", status_code=422)
        if settings.requires_api_key:
            api_key = self.store.get_tts_key(provider)
        else:
            api_key = None
        cache_key = _cache_key_for_request(self.cache, request, settings, provider)
        if cache_key:
            cached = self.cache.get(cache_key)
            if cached:
                return _cached_audio_response(provider, cached)
        response = self.synthesize_with_settings(request, settings, provider, api_key)
        if cache_key:
            _store_audio_response(self.cache, cache_key, provider, response)
        return response

    def synthesize_with_settings(
        self,
        request: TtsSynthesisRequest,
        settings: TtsSettingsResponse,
        provider: str,
        api_key: str | None,
    ) -> TtsSynthesisResponse:
        response_format = XIAOMI_MIMO_RESPONSE_FORMAT if provider == "xiaomi-mimo" else _normalize_response_format(settings.response_format)
        payload = _build_request_payload(request, settings, response_format)
        headers = {
            "Accept": ",".join(sorted(set(MIME_BY_FORMAT.values()))) + ",application/json",
            "Content-Type": "application/json",
        }
        if api_key:
            auth_header_name = (settings.auth_header_name or "").strip() or (
                "api-key" if provider in TTS_PRESET_PROVIDERS else "Authorization"
            )
            headers[auth_header_name] = api_key if auth_header_name.lower() == "api-key" else f"Bearer {api_key}"

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            str(settings.base_url),
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with self._open(http_request) as response:
                status_code = int(getattr(response, "status", getattr(response, "code", 200)))
                content_type = response.headers.get("content-type", "")
                data = response.read()
        except TimeoutError as exc:
            raise TtsServiceError(
                "语音服务请求超时，请检查服务地址或稍后重试。",
                code="provider_timeout",
                detail=_safe_detail(str(exc)),
                status_code=504,
            ) from exc
        except urllib.error.HTTPError as exc:
            detail = _safe_detail(exc.read().decode("utf-8", errors="replace"))
            _raise_http_status(exc.code, detail)
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise TtsServiceError(
                "无法连接语音服务，请检查服务地址和网络。",
                code="provider_unreachable",
                detail=_safe_detail(str(reason)),
                status_code=502,
            ) from exc

        if status_code < 200 or status_code >= 300:
            _raise_http_status(status_code, _safe_detail(data.decode("utf-8", errors="replace")))

        return _response_to_audio(
            data,
            content_type=content_type,
            provider=provider,
            fallback_format=response_format,
            audio_json_path=settings.audio_json_path or ("choices.0.message.audio.data" if provider == "xiaomi-mimo" else None),
            audio_encoding=settings.audio_encoding,
            configured_mime_type=MIME_BY_FORMAT[response_format] if provider == "xiaomi-mimo" else settings.mime_type,
        )

    def _open(self, request: urllib.request.Request):
        opener = self.opener or urllib.request.urlopen
        return opener(request, timeout=max(self.timeout_seconds, 0.001))


def _cache_key_for_request(
    cache: TtsAudioCache | None,
    request: TtsSynthesisRequest,
    settings: TtsSettingsResponse,
    provider: str,
) -> str | None:
    if cache is None or not settings.cache_enabled or request.cache_enabled is False:
        return None
    if _SENSITIVE_CACHE_RE.search(request.text):
        return None
    voice = request.voice or settings.voice
    return cache.key_for(
        provider=provider,
        voice_id=voice.id if voice else None,
        speed=request.speed,
        text=request.text,
    )


def _cached_audio_response(provider: str, cached: TtsCachedAudio) -> TtsSynthesisResponse:
    return TtsSynthesisResponse(
        provider=provider,
        mime_type=cached.mime_type,
        audio_base64=base64.b64encode(cached.audio).decode("ascii"),
        duration_ms=cached.duration_ms,
        cache_hit=True,
    )


def _store_audio_response(
    cache: TtsAudioCache | None,
    cache_key: str,
    provider: str,
    response: TtsSynthesisResponse,
) -> None:
    if cache is None:
        return
    try:
        audio = base64.b64decode(response.audio_base64, validate=True)
    except binascii.Error:
        return
    try:
        cache.put(
            cache_key,
            provider=provider,
            mime_type=response.mime_type,
            audio=audio,
            duration_ms=response.duration_ms,
        )
    except (OSError, ValueError):
        return


def _ensure_ready(settings: TtsSettingsResponse) -> None:
    if not settings.enabled:
        raise TtsServiceError("语音朗读尚未启用。", code="disabled", status_code=422)
    if settings.status != "ready" or not settings.configured:
        raise TtsServiceError(
            "语音服务尚未配置完成。",
            code=settings.status or "provider_not_configured",
            status_code=422,
        )
    if not settings.base_url:
        raise TtsServiceError("请先配置语音 API 地址。", code="provider_not_configured", status_code=422)


def _build_request_payload(
    request: TtsSynthesisRequest,
    settings: TtsSettingsResponse,
    response_format: str,
) -> dict[str, Any]:
    provider = normalize_tts_provider(settings.provider)
    voice = request.voice or settings.voice
    voice_id = voice.id if voice else ""
    if provider == "xiaomi-mimo":
        voice_id = voice_id if voice_id in XIAOMI_MIMO_BUILTIN_VOICES else XIAOMI_MIMO_DEFAULT_VOICE
    context = {
        "text": request.text,
        "model": XIAOMI_MIMO_MODEL if provider == "xiaomi-mimo" else settings.model or "",
        "voice": voice_id,
        "voice_label": voice.label if voice else "",
        "speed": request.speed,
        "volume": request.volume,
        "format": response_format,
        "response_format": response_format,
    }
    if settings.request_template:
        rendered = _render_template(settings.request_template, context)
        if not isinstance(rendered, dict):
            raise TtsServiceError(
                "TTS request template must render to a JSON object.",
                code="provider_not_configured",
                status_code=422,
            )
        return rendered
    if provider == "xiaomi-mimo":
        return {
            "model": XIAOMI_MIMO_MODEL,
            "messages": [
                {"role": "user", "content": "请自然朗读助手文本。"},
                {"role": "assistant", "content": request.text},
            ],
            "audio": {
                "voice": voice_id,
                "format": response_format,
            },
        }
    return {
        "text": request.text,
        "model": settings.model,
        "voice": voice.id if voice else None,
        "voice_label": voice.label if voice else None,
        "speed": request.speed,
        "volume": request.volume,
        "response_format": response_format,
    }


def _render_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        rendered = value
        for key, replacement in context.items():
            rendered = rendered.replace("{{" + key + "}}", str(replacement))
        return rendered
    if isinstance(value, list):
        return [_render_template(item, context) for item in value]
    if isinstance(value, dict):
        return {str(key): _render_template(item, context) for key, item in value.items()}
    return value


def _response_to_audio(
    data: bytes,
    *,
    content_type: str,
    provider: str,
    fallback_format: str,
    audio_json_path: str | None = None,
    audio_encoding: str = "base64",
    configured_mime_type: str | None = None,
) -> TtsSynthesisResponse:
    response_mime_type = content_type.split(";", 1)[0].strip().lower()
    mime_type = (configured_mime_type or response_mime_type).strip().lower()
    if response_mime_type.startswith("audio/"):
        audio = data
    else:
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TtsServiceError(
                "语音服务没有返回可播放音频。",
                code="invalid_audio",
                status_code=502,
            ) from exc
        audio, mime_type = _extract_audio_from_json(
            payload,
            fallback_format=fallback_format,
            audio_json_path=audio_json_path,
            audio_encoding=audio_encoding,
            configured_mime_type=configured_mime_type,
        )

    if not audio:
        raise TtsServiceError("语音服务返回了空音频。", code="invalid_audio", status_code=502)
    return TtsSynthesisResponse(
        provider=provider,
        mime_type=mime_type,
        audio_base64=base64.b64encode(audio).decode("ascii"),
        duration_ms=None,
        cache_hit=False,
    )


def _extract_audio_from_json(
    payload: Any,
    *,
    fallback_format: str,
    audio_json_path: str | None = None,
    audio_encoding: str = "base64",
    configured_mime_type: str | None = None,
) -> tuple[bytes, str]:
    if not isinstance(payload, dict):
        raise TtsServiceError("语音服务 JSON 响应格式无效。", code="invalid_audio", status_code=502)
    mime_type = str(configured_mime_type or payload.get("mime_type") or payload.get("mimeType") or MIME_BY_FORMAT[fallback_format])
    normalized_encoding = audio_encoding.strip().lower()
    if normalized_encoding not in SUPPORTED_AUDIO_ENCODINGS:
        raise TtsServiceError("不支持的 TTS 音频编码。", code="unsupported_format", status_code=422)
    if audio_json_path:
        candidate = _get_json_path(payload, audio_json_path)
        if isinstance(candidate, str) and candidate.strip():
            return _decode_audio_string(candidate, mime_type=mime_type)
        raise TtsServiceError("TTS JSON 路径未解析到音频内容。", code="invalid_audio", status_code=502)
    candidates = (
        payload.get("audio_base64"),
        payload.get("audioBase64"),
        payload.get("audio"),
        payload.get("data"),
    )
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return _decode_audio_string(candidate, mime_type=mime_type)
    raise TtsServiceError("语音服务 JSON 响应缺少音频内容。", code="invalid_audio", status_code=502)


def _decode_audio_string(value: str, *, mime_type: str) -> tuple[bytes, str]:
    text = value.strip()
    if text.startswith("data:"):
        header, _, encoded = text.partition(",")
        if ";base64" not in header or not encoded:
            raise TtsServiceError("语音服务 data URL 格式无效。", code="invalid_audio", status_code=502)
        mime = header[5:].split(";", 1)[0] or mime_type
        text = encoded
        mime_type = mime
    try:
        return base64.b64decode(text, validate=True), mime_type
    except binascii.Error as exc:
        raise TtsServiceError("语音服务返回的音频不是有效 base64。", code="invalid_audio", status_code=502) from exc


def _get_json_path(payload: Any, path: str) -> Any:
    current = payload
    for raw_part in path.split("."):
        part = raw_part.strip()
        if not part:
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (IndexError, ValueError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _normalize_response_format(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in SUPPORTED_RESPONSE_FORMATS:
        raise TtsServiceError(
            "语音格式不受支持。",
            code="unsupported_format",
            detail=f"response_format={normalized}",
            status_code=422,
        )
    return normalized


def _raise_http_status(status_code: int, detail: str) -> None:
    if status_code in {401, 403}:
        raise TtsServiceError("语音服务鉴权失败，请检查 API Key。", code="authentication_failed", detail=detail, status_code=502)
    if status_code == 429:
        raise TtsServiceError("语音服务限流，请稍后重试。", code="rate_limited", detail=detail, status_code=502)
    raise TtsServiceError("语音服务返回错误，请检查接口地址和参数。", code="provider_failed", detail=detail, status_code=502)


def _safe_detail(text: str) -> str:
    compact = " ".join(text.split())
    compact = _SECRET_RE.sub("[REDACTED]", compact)
    return compact[:400]
