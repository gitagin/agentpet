from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.config import (
    DEFAULT_CHAT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
)

from .enums import AgentId


ProactiveTriggerFrequency = Literal["off", "low", "normal", "high"]
PROACTIVE_TRIGGER_FREQUENCY_VALUES = {"off", "low", "normal", "high"}
DEFAULT_PROACTIVE_TRIGGER_FREQUENCY: ProactiveTriggerFrequency = "low"


def normalize_proactive_trigger_frequency(value: object) -> ProactiveTriggerFrequency:
    normalized = str(value or "").strip().lower()
    if normalized in PROACTIVE_TRIGGER_FREQUENCY_VALUES:
        return normalized  # type: ignore[return-value]
    return DEFAULT_PROACTIVE_TRIGGER_FREQUENCY


class ModelKeyRequest(BaseModel):
    provider: str
    api_key: str = Field(min_length=1)


class AgentModelKeyRequest(BaseModel):
    agent_id: AgentId | None = None
    provider: str | None = None
    api_key: str = Field(min_length=1)


class ModelKeyResponse(BaseModel):
    provider: str
    status: str
    masked: str


class ModelConfigRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1)
    base_url: str = Field(default=DEFAULT_CHAT_BASE_URL, min_length=1)
    model: str = Field(default=DEFAULT_CHAT_MODEL, min_length=1)


class AgentModelConfigRequest(ModelConfigRequest):
    agent_id: AgentId | None = None
    enabled: bool = True


class ModelConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    status: str


class EmbeddingConfigRequest(BaseModel):
    provider: str = Field(default="openai-compatible", min_length=1)
    base_url: str = Field(default=DEFAULT_EMBEDDING_BASE_URL, min_length=1)
    model: str = Field(default=DEFAULT_EMBEDDING_MODEL, min_length=1)
    dimensions: int | None = Field(default=None, ge=1)


class EmbeddingConfigResponse(BaseModel):
    provider: str
    base_url: str
    model: str
    dimensions: int | None = None
    status: str
    configured: bool = False
    masked: str | None = None


class EmbeddingKeyRequest(BaseModel):
    provider: str | None = None
    api_key: str = Field(min_length=1)


class EmbeddingTestResponse(BaseModel):
    status: str
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    dimensions: int | None = None
    latency_ms: int | None = None
    message: str
    error_code: str | None = None
    error_detail: str | None = None


class AgentModelConfigResponse(ModelConfigResponse):
    agent_id: AgentId
    enabled: bool = True
    configured: bool = False
    masked: str | None = None


class AgentModelsRequest(BaseModel):
    agents: list[AgentModelConfigRequest] = Field(default_factory=list)


class AgentModelsResponse(BaseModel):
    agents: list[AgentModelConfigResponse] = Field(default_factory=list)


class AgentModelHealth(BaseModel):
    agent_id: AgentId
    source: str
    model: str


class ModelHealthResponse(BaseModel):
    global_configured: bool
    agents_configured: int
    agents_fallback_to_global: int
    agents_fallback_to_default: int
    agent_details: list[AgentModelHealth] = Field(default_factory=list)


class ModelTestRequest(BaseModel):
    agent_id: AgentId | None = None


class ModelTestResponse(BaseModel):
    status: str
    agent_id: AgentId | None = None
    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    message: str
    error_code: str | None = None
    error_detail: str | None = None


class AutomationSettingsRequest(BaseModel):
    auto_chat_diary: bool = False
    auto_structured_memory: bool = False
    auto_long_term_memory: bool = False
    auto_wiki_organize: bool = False
    wiki_shadow_enabled: StrictBool = False
    # 源身份 v2(设计 docs/source-identity-migration-design.md):默认关=保持 legacy
    # hash 复用行为。此前该开关只被读取、没有任何写入路径,导致已实现的源身份语义
    # 在生产中不可达;这里按设计接入既有 settings 机制。
    source_identity_v2: StrictBool = False
    # 草稿先行发布(设计 docs/draft-first-publication-design.md):默认关=保持
    # 现有「先写盘再 capture」路径;开启后 ingest 走 draft→审批→publish_draft。
    wiki_draft_first_publication: StrictBool = False
    local_privacy_mode: bool = False
    proactive_trigger_frequency: ProactiveTriggerFrequency = DEFAULT_PROACTIVE_TRIGGER_FREQUENCY
    use_negotiation: bool = False
    max_rounds: int = Field(default=5, ge=2, le=10)


class AutomationSettingsResponse(AutomationSettingsRequest):
    high_risk_confirmation_required: bool = True
    updated_at: str | None = None


class TtsVoiceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="system", min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)
    locale: str | None = Field(default=None, max_length=32)
    gender: str | None = Field(default=None, max_length=16)
    description: str | None = Field(default=None, max_length=256)


class TtsSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = False
    auto_play_assistant_reply: bool = False
    auto_play_reminders: bool = False
    provider: str = Field(default="system", min_length=1, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)
    voice: TtsVoiceConfig | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    response_format: str = Field(default="mp3", min_length=1, max_length=16)
    requires_api_key: bool = False
    api_style: str = Field(default="generic", min_length=1, max_length=64)
    auth_header_name: str | None = Field(default=None, max_length=128)
    request_template: dict[str, Any] | None = None
    audio_json_path: str | None = Field(default=None, max_length=256)
    audio_encoding: str = Field(default="base64", min_length=1, max_length=32)
    mime_type: str | None = Field(default=None, max_length=128)
    cache_enabled: bool = False
    night_quiet_mode: bool = True


class TtsSettingsResponse(TtsSettingsRequest):
    configured: bool = False
    status: str = "disabled"
    key_configured: bool = False
    key_masked: str | None = None
    updated_at: str | None = None


class TtsKeyRequest(BaseModel):
    provider: str = Field(default="custom-http", min_length=1, max_length=64)
    api_key: str = Field(min_length=1, max_length=4096)


class TtsKeyResponse(BaseModel):
    provider: str
    status: str = "configured"
    configured: bool = True
    masked: str


class TtsSynthesisRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    provider: str | None = Field(default=None, max_length=64)
    voice: TtsVoiceConfig | None = None
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    cache_enabled: bool | None = None


class TtsSynthesisResponse(BaseModel):
    provider: str
    mime_type: str
    audio_base64: str
    duration_ms: int | None = None
    cache_hit: bool = False


class TtsCacheClearResponse(BaseModel):
    status: str = "cleared"
    cleared_entries: int = 0
    cleared_bytes: int = 0


class VaultStatusResponse(BaseModel):
    configured: bool = False
    active_vault_id: str | None = None
    root_path: str | None = None
    root_path_label: str | None = None
    name: str | None = None
    latest_indexed_at: str | None = None
    markdown_count: int = 0
    wiki_page_count: int = 0
    diary_page_count: int = 0


class VaultBindRequest(BaseModel):
    path: str = Field(min_length=1)
    create_if_missing: bool = False
    confirmed: bool = False


class VaultBindResponse(BaseModel):
    vault_id: str
    status: str
    root_path: str | None = None
    name: str | None = None


class VaultIndexResponse(BaseModel):
    index_job_id: str
    status: str
    files_seen: int = 0
    files_indexed: int = 0


class WikiShadowSummary(BaseModel):
    available: bool = True
    samples: int = 0
    today_samples: int = 0
    completed: int = 0
    failed: int = 0
    interrupted: int = 0
    unfinished: int = 0
    invalid_records: int = 0
    wiki_hits: int = 0
    note_fallbacks: int = 0
    authority_denied: int = 0
    coverage_complete: int = 0
    disputed: int = 0
    budget_exhausted: int = 0
    assessment_calls: int = 0
    evidence_chars: int = 0
    mean_latency_ms: int | None = None


class SettingsStatusResponse(BaseModel):
    model_provider: str | None = None
    model_base_url: str | None = None
    chat_model: str | None = None
    model_configured: bool = False
    embedding_provider: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_dimensions: int | None = None
    embedding_configured: bool = False
    vault_configured: bool = False
    agent_models: list[AgentModelConfigResponse] = Field(default_factory=list)
    automation: AutomationSettingsResponse = Field(default_factory=AutomationSettingsResponse)
    wiki_shadow_metrics: WikiShadowSummary = Field(default_factory=WikiShadowSummary)
    tts_settings: TtsSettingsResponse = Field(default_factory=TtsSettingsResponse)
