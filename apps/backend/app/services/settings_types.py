from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from app.models.config import TtsSettingsRequest, TtsSettingsResponse
from app.utils.hash import sha256_hex


AGENT_MODEL_IDS = (
    "chat_agent",
    "semantic_analysis_agent",
    "retrieval_agent",
    "action_agent",
    "reflection_agent",
)
AGENT_MODEL_ALIASES = {
    "memory_retrieval_agent": "retrieval_agent",
    "knowledge_retrieval_agent": "retrieval_agent",
    "context_retrieval_agent": "retrieval_agent",
    "knowledge_agent": "retrieval_agent",
    "wiki_manager_agent": "action_agent",
    "memory_proposal_agent": "action_agent",
    "task_agent": "action_agent",
    "diary_memory_extractor_agent": "reflection_agent",
    "continuity_agent": "reflection_agent",
}
LEGACY_AGENT_MODEL_MIGRATIONS = (
    ("memory_retrieval_agent", ("retrieval_agent",)),
    ("knowledge_retrieval_agent", ("retrieval_agent",)),
    ("context_retrieval_agent", ("retrieval_agent",)),
    ("knowledge_agent", ("retrieval_agent",)),
    ("wiki_manager_agent", ("action_agent",)),
    ("memory_proposal_agent", ("action_agent",)),
    ("task_agent", ("action_agent",)),
    ("diary_memory_extractor_agent", ("reflection_agent",)),
    ("continuity_agent", ("reflection_agent",)),
)
LEGACY_AGENT_MODEL_IDS = tuple(
    legacy_agent_id for legacy_agent_id, _target_agent_ids in LEGACY_AGENT_MODEL_MIGRATIONS
)
OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai compatible",
    "openai-compatible",
    "openai_compatible",
    "openai兼容",
    "openai 兼容",
    "openai兼容接口",
    "openai 兼容接口",
    "openai兼容协议",
    "openai 兼容协议",
}
SUPPORTED_MODEL_PROVIDERS = {"openai", "openai-compatible"}
TTS_SETTINGS_STATE_KEY = "tts_settings"
LOCAL_PRIVACY_MODE_STATE_KEY = "local_privacy_mode"
PROACTIVE_TRIGGER_FREQUENCY_STATE_KEY = "proactive_trigger_frequency"
TTS_KEY_STATE_PREFIX = "tts_key:"
XIAOMI_MIMO_TTS_PROVIDER = "xiaomi-mimo"
XIAOMI_MIMO_TTS_URL = "https://api.xiaomimimo.com/v1/chat/completions"
XIAOMI_MIMO_TTS_MODEL = "mimo-v2.5-tts"
XIAOMI_MIMO_TTS_FORMAT = "wav"
XIAOMI_MIMO_TTS_DEFAULT_VOICE = "Chloe"
XIAOMI_MIMO_TTS_VOICES = {
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
LOCAL_TTS_PROVIDERS = {"system", "mock"}


class CredentialStoreError(RuntimeError):
    pass


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelKeyStatus:
    provider: str | None
    configured: bool
    masked: str | None = None


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    base_url: str
    model: str


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    base_url: str
    model: str
    dimensions: int | None = None


@dataclass(frozen=True)
class AgentModelSettings:
    agent_id: str
    provider: str | None
    base_url: str | None
    model: str | None
    enabled: bool
    configured: bool
    masked: str | None = None


class CredentialStore(Protocol):
    def put(self, ref: str, secret: str) -> None: ...

    def get(self, ref: str) -> str | None: ...

    def exists(self, ref: str) -> bool: ...


def normalize_model_provider(provider: str) -> str:
    value = provider.strip()
    normalized = value.lower().replace("－", "-").replace("—", "-").replace("–", "-")
    normalized = " ".join(normalized.split())
    if normalized in OPENAI_COMPATIBLE_PROVIDER_ALIASES:
        return "openai-compatible"
    return value


def is_supported_model_provider(provider: str) -> bool:
    return normalize_model_provider(provider).strip().lower() in SUPPORTED_MODEL_PROVIDERS


def normalize_tts_provider(provider: str) -> str:
    return provider.strip().lower() or "system"


def normalize_agent_id(agent_id: str) -> str:
    normalized = getattr(agent_id, "value", str(agent_id)).strip()
    normalized = AGENT_MODEL_ALIASES.get(normalized, normalized)
    if normalized not in AGENT_MODEL_IDS:
        raise ValueError(f"unsupported agent_id: {agent_id}")
    return normalized


def _normalize_provider_identifier(provider: str) -> str:
    return normalize_model_provider(provider).strip().lower()


@dataclass(frozen=True, slots=True)
class CredentialSlot:
    """Relational metadata and vault naming for one credential domain."""

    table: str
    key_column: str
    ref_builder: Callable[[str], str]
    normalizer: Callable[[str], str]

    def normalize(self, identifier: str) -> str:
        return self.normalizer(identifier)

    def ref(self, identifier: str) -> str:
        return self.ref_builder(self.normalize(identifier))


MODEL_CREDENTIAL_SLOT = CredentialSlot(
    "model_keys",
    "provider",
    lambda provider: f"model-key:{sha256_hex(provider)}",
    _normalize_provider_identifier,
)
EMBEDDING_CREDENTIAL_SLOT = CredentialSlot(
    "embedding_keys",
    "provider",
    lambda provider: f"embedding-key:{sha256_hex(provider)}",
    _normalize_provider_identifier,
)
TTS_CREDENTIAL_SLOT = CredentialSlot(
    "app_state",
    "key",
    lambda provider: f"tts-key:{sha256_hex(provider)}",
    normalize_tts_provider,
)
AGENT_CREDENTIAL_SLOT = CredentialSlot(
    "agent_model_configs",
    "agent_id",
    lambda agent_id: f"model-key:agent:{agent_id}",
    normalize_agent_id,
)


def mask_secret(secret: str) -> str:
    if len(secret) <= 8:
        return "****"
    return f"****{secret[-4:]}"


def write_credential(
    store: CredentialStore,
    slot: CredentialSlot,
    identifier: str,
    secret: str,
) -> tuple[str, str, ModelKeyStatus]:
    """Write secret material once; domain stores persist only the returned ref."""
    normalized = slot.normalize(identifier)
    credential_ref = slot.ref(normalized)
    store.put(credential_ref, secret)
    return (
        normalized,
        credential_ref,
        ModelKeyStatus(provider=normalized, configured=True, masked=mask_secret(secret)),
    )


def credential_status(
    store: CredentialStore,
    slot: CredentialSlot,
    identifier: str,
    credential_ref: str | None,
    *,
    provider: str | None = None,
) -> ModelKeyStatus:
    normalized = slot.normalize(identifier)
    ref = credential_ref or slot.ref(normalized)
    configured = store.exists(ref)
    secret = store.get(ref) if configured else None
    return ModelKeyStatus(
        provider=provider or normalized,
        configured=configured,
        masked=mask_secret(secret) if secret else None,
    )


def read_credential(
    store: CredentialStore,
    slot: CredentialSlot,
    identifier: str,
    credential_ref: str | None,
) -> str | None:
    ref = credential_ref or slot.ref(identifier)
    return store.get(ref)


def tts_key_state_key(provider: str) -> str:
    return f"{TTS_KEY_STATE_PREFIX}{sha256_hex(normalize_tts_provider(provider))}"


def model_config_matches(left: ModelConfig, right: ModelConfig) -> bool:
    return (
        normalize_model_provider(left.provider).strip().lower()
        == normalize_model_provider(right.provider).strip().lower()
        and left.base_url.strip().rstrip("/") == right.base_url.strip().rstrip("/")
        and left.model.strip() == right.model.strip()
    )


def normalize_tts_preset_settings(raw_settings: dict) -> dict:
    provider = normalize_tts_provider(str(raw_settings.get("provider") or "system"))
    if provider != XIAOMI_MIMO_TTS_PROVIDER:
        return raw_settings
    raw_voice = raw_settings.get("voice")
    voice_id = XIAOMI_MIMO_TTS_DEFAULT_VOICE
    if isinstance(raw_voice, dict):
        candidate = str(raw_voice.get("id") or "").strip()
        if candidate in XIAOMI_MIMO_TTS_VOICES:
            voice_id = candidate
    return {
        **raw_settings,
        "provider": XIAOMI_MIMO_TTS_PROVIDER,
        "base_url": XIAOMI_MIMO_TTS_URL,
        "model": XIAOMI_MIMO_TTS_MODEL,
        "response_format": XIAOMI_MIMO_TTS_FORMAT,
        "requires_api_key": True,
        "api_style": "chat-completions-audio",
        "auth_header_name": "api-key",
        "audio_json_path": "choices.0.message.audio.data",
        "audio_encoding": "base64",
        "mime_type": "audio/wav",
        "voice": {
            "id": voice_id,
            "provider": XIAOMI_MIMO_TTS_PROVIDER,
            "label": voice_id,
            "locale": raw_voice.get("locale") if isinstance(raw_voice, dict) else None,
            "gender": raw_voice.get("gender") if isinstance(raw_voice, dict) else None,
            "description": "MiMo 内置声音",
        },
    }


def tts_settings_response(
    settings: TtsSettingsRequest,
    *,
    updated_at: str | None,
    key_status: ModelKeyStatus,
) -> TtsSettingsResponse:
    settings = TtsSettingsRequest.model_validate(
        normalize_tts_preset_settings(settings.model_dump(mode="json"))
    )
    provider = normalize_tts_provider(settings.provider)
    has_custom_endpoint = bool((settings.base_url or "").strip())
    if not settings.enabled:
        status, configured = "disabled", False
    elif provider in LOCAL_TTS_PROVIDERS:
        status, configured = "ready", True
    elif not has_custom_endpoint:
        status, configured = "provider_not_configured", False
    elif settings.requires_api_key and not key_status.configured:
        status, configured = "credential_missing", False
    else:
        status, configured = "ready", True
    return TtsSettingsResponse(
        **{**settings.model_dump(), "provider": provider},
        configured=configured,
        status=status,
        key_configured=key_status.configured,
        key_masked=key_status.masked,
        updated_at=updated_at,
    )
