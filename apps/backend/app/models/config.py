from __future__ import annotations

from pydantic import BaseModel, Field

from app.config import (
    DEFAULT_CHAT_BASE_URL,
    DEFAULT_CHAT_MODEL,
    DEFAULT_EMBEDDING_BASE_URL,
    DEFAULT_EMBEDDING_MODEL,
)

from .enums import AgentId


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


class SettingsPatchRequest(BaseModel):
    provider: str | None = Field(default=None, min_length=1)
    base_url: str | None = Field(default=None, min_length=1)
    model: str | None = Field(default=None, min_length=1)
    use_negotiation: bool | None = None
    max_rounds: int | None = Field(default=None, ge=2, le=10)


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
    use_negotiation: bool = True
    max_rounds: int = Field(default=5, ge=2, le=10)


class AutomationSettingsResponse(AutomationSettingsRequest):
    high_risk_confirmation_required: bool = True
    updated_at: str | None = None


class SettingsUpdateResponse(ModelConfigResponse):
    agents_using_global: int
    automation: AutomationSettingsResponse | None = None


class VaultStatusResponse(BaseModel):
    configured: bool = False
    active_vault_id: str | None = None
    root_path: str | None = None
    name: str | None = None


class VaultBindRequest(BaseModel):
    path: str = Field(min_length=1)
    create_if_missing: bool = False


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
