from time import perf_counter

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from ..config import get_settings
from ..models.api import (
    AutomationSettingsRequest,
    AutomationSettingsResponse,
    AgentModelConfigRequest,
    AgentModelConfigResponse,
    AgentModelKeyRequest,
    AgentModelsRequest,
    AgentModelsResponse,
    AgentModelHealth,
    EmbeddingConfigRequest,
    EmbeddingConfigResponse,
    EmbeddingKeyRequest,
    EmbeddingTestResponse,
    ModelConfigRequest,
    ModelConfigResponse,
    ModelHealthResponse,
    SettingsPatchRequest,
    ModelKeyRequest,
    ModelKeyResponse,
    ModelTestRequest,
    ModelTestResponse,
    SettingsStatusResponse,
    SettingsUpdateResponse,
    TtsKeyRequest,
    TtsKeyResponse,
    TtsSettingsRequest,
    TtsSettingsResponse,
)
from ..services.embeddings import LangChainEmbeddingClient
from ..services.chat_model import ChatModelError, LangChainGraphChatClient
from ..services.settings import (
    AGENT_MODEL_IDS,
    ConfigurationError,
    CredentialStoreError,
    ModelConfig,
    ModelKeyStatus,
    SettingsStore,
    is_supported_model_provider,
)
from .wiring import database, settings_store_dependency
from .wiring import refresh_retrieval_vector_index

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsStatusResponse)
async def get_settings_status(
    request: Request,
    store: SettingsStore = Depends(settings_store_dependency),
) -> SettingsStatusResponse:
    defaults = get_settings()
    model_status = store.get_model_key_status()
    embedding_status = store.get_embedding_key_status()
    automation = store.get_automation_settings()
    tts_settings = store.get_tts_settings()
    model_config = store.get_model_config(
        default_provider=model_status.provider or "openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    embedding_config = store.get_embedding_config(
        default_provider=embedding_status.provider or "openai-compatible",
        default_base_url=defaults.embedding_base_url,
        default_model=defaults.embedding_model,
        default_dimensions=defaults.embedding_dimensions,
    )
    with database(request).connect() as conn:
        vault_configured = conn.execute("SELECT 1 FROM vaults LIMIT 1").fetchone() is not None
    return SettingsStatusResponse(
        model_provider=model_config.provider,
        model_base_url=model_config.base_url,
        chat_model=model_config.model,
        model_configured=model_status.configured,
        embedding_provider=embedding_config.provider,
        embedding_base_url=embedding_config.base_url,
        embedding_model=embedding_config.model,
        embedding_dimensions=embedding_config.dimensions,
        embedding_configured=embedding_status.configured,
        vault_configured=vault_configured,
        agent_models=_agent_model_responses(store),
        automation=automation,
        tts_settings=tts_settings,
    )


@router.get("/automation", response_model=AutomationSettingsResponse)
async def get_automation_settings(
    store: SettingsStore = Depends(settings_store_dependency),
) -> AutomationSettingsResponse:
    return store.get_automation_settings()


@router.get("/model-health", response_model=ModelHealthResponse)
async def get_model_health(
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelHealthResponse:
    return store.get_model_health_status()


@router.put("/automation", response_model=AutomationSettingsResponse)
async def set_automation_settings(
    automation: AutomationSettingsRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> AutomationSettingsResponse:
    return store.set_automation_settings(automation)


@router.get("/tts", response_model=TtsSettingsResponse)
async def get_tts_settings(
    store: SettingsStore = Depends(settings_store_dependency),
) -> TtsSettingsResponse:
    return store.get_tts_settings()


@router.put("/tts", response_model=TtsSettingsResponse)
async def set_tts_settings(
    tts_settings: TtsSettingsRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> TtsSettingsResponse:
    return store.set_tts_settings(tts_settings)


@router.put("/tts-key", response_model=TtsKeyResponse)
async def set_tts_key(
    tts_key: TtsKeyRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> TtsKeyResponse:
    try:
        status_value = store.set_tts_key(tts_key.provider, tts_key.api_key)
    except CredentialStoreError as exc:
        _raise_credential_store_error(exc)
    return TtsKeyResponse(
        provider=status_value.provider or tts_key.provider,
        status="configured",
        configured=status_value.configured,
        masked=status_value.masked or "****",
    )


@router.put("/model-key", response_model=ModelKeyResponse)
async def set_model_key(
    model_key: ModelKeyRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelKeyResponse:
    _ensure_supported_provider(model_key.provider)
    try:
        status = store.set_model_key(model_key.provider, model_key.api_key)
    except CredentialStoreError as exc:
        _raise_credential_store_error(exc)
    return ModelKeyResponse(
        provider=status.provider or model_key.provider,
        status="configured",
        masked=status.masked or "****",
    )


@router.patch("", response_model=SettingsUpdateResponse)
async def update_settings(
    request: SettingsPatchRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> SettingsUpdateResponse:
    defaults = get_settings()
    current_status = store.get_model_key_status()
    current_model = store.get_model_config(
        default_provider=current_status.provider or "openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    model_updated = any(value is not None for value in (request.provider, request.base_url, request.model))
    if model_updated:
        provider = request.provider or current_model.provider
        _ensure_supported_provider(provider)
        saved = store.set_model_config(
            provider=provider,
            base_url=request.base_url or current_model.base_url,
            model=request.model or current_model.model,
        )
    else:
        saved = current_model

    current_automation = store.get_automation_settings()
    automation_updated = request.use_negotiation is not None or request.max_rounds is not None
    automation = current_automation
    if automation_updated:
        automation = store.set_automation_settings(
            AutomationSettingsRequest(
                auto_chat_diary=current_automation.auto_chat_diary,
                auto_structured_memory=current_automation.auto_structured_memory,
                auto_long_term_memory=current_automation.auto_long_term_memory,
                auto_wiki_organize=current_automation.auto_wiki_organize,
                use_negotiation=current_automation.use_negotiation if request.use_negotiation is None else request.use_negotiation,
                max_rounds=current_automation.max_rounds if request.max_rounds is None else request.max_rounds,
            )
        )

    health = store.get_model_health_status()
    return SettingsUpdateResponse(
        provider=saved.provider,
        base_url=saved.base_url,
        model=saved.model,
        status="configured" if current_status.configured or model_updated else "missing_key",
        agents_using_global=health.agents_fallback_to_global,
        automation=automation,
    )


@router.put("/model-config", response_model=ModelConfigResponse)
async def set_model_config(
    model_config: ModelConfigRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelConfigResponse:
    _ensure_supported_provider(model_config.provider)
    saved = store.set_model_config(
        provider=model_config.provider,
        base_url=model_config.base_url,
        model=model_config.model,
    )
    return ModelConfigResponse(
        provider=saved.provider,
        base_url=saved.base_url,
        model=saved.model,
        status="configured",
    )


@router.put("/embedding-key", response_model=EmbeddingConfigResponse)
async def set_embedding_key(
    request: Request,
    embedding_key: EmbeddingKeyRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> EmbeddingConfigResponse:
    defaults = get_settings()
    current = store.get_embedding_config(
        default_provider="openai-compatible",
        default_base_url=defaults.embedding_base_url,
        default_model=defaults.embedding_model,
        default_dimensions=defaults.embedding_dimensions,
    )
    provider = embedding_key.provider or current.provider
    _ensure_supported_provider(provider)
    try:
        status_value = store.set_embedding_key(provider, embedding_key.api_key)
    except CredentialStoreError as exc:
        _raise_credential_store_error(exc)
    refresh_retrieval_vector_index(request)
    return EmbeddingConfigResponse(
        provider=status_value.provider or provider,
        base_url=current.base_url,
        model=current.model,
        dimensions=current.dimensions,
        status="configured",
        configured=status_value.configured,
        masked=status_value.masked,
    )


@router.put("/embedding-config", response_model=EmbeddingConfigResponse)
async def set_embedding_config(
    request: Request,
    embedding_config: EmbeddingConfigRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> EmbeddingConfigResponse:
    _ensure_supported_provider(embedding_config.provider)
    saved = store.set_embedding_config(
        provider=embedding_config.provider,
        base_url=embedding_config.base_url,
        model=embedding_config.model,
        dimensions=embedding_config.dimensions,
    )
    key_status = store.get_embedding_key_status()
    refresh_retrieval_vector_index(request)
    return EmbeddingConfigResponse(
        provider=saved.provider,
        base_url=saved.base_url,
        model=saved.model,
        dimensions=saved.dimensions,
        status="configured" if key_status.configured else "missing_key",
        configured=key_status.configured,
        masked=key_status.masked,
    )


@router.post("/embedding-test", response_model=EmbeddingTestResponse)
async def test_embedding_connection(
    store: SettingsStore = Depends(settings_store_dependency),
) -> EmbeddingTestResponse:
    defaults = get_settings()
    key_status = store.get_embedding_key_status()
    config = store.get_embedding_config(
        default_provider=key_status.provider or "openai-compatible",
        default_base_url=defaults.embedding_base_url,
        default_model=defaults.embedding_model,
        default_dimensions=defaults.embedding_dimensions,
    )
    if config.provider.strip().lower() not in {"openai", "openai-compatible", "openai_compatible"}:
        return EmbeddingTestResponse(
            status="failed",
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            dimensions=config.dimensions,
            message="当前 embedding 提供方暂不支持试连，请使用 OpenAI 兼容接口。",
            error_code="unsupported_provider",
        )
    if not key_status.configured:
        return EmbeddingTestResponse(
            status="failed",
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            dimensions=config.dimensions,
            message="尚未保存 embedding API 密钥。",
            error_code="not_configured",
        )
    api_key = store.get_embedding_key(config.provider)
    if not api_key and key_status.provider:
        api_key = store.get_embedding_key(key_status.provider)
    if not api_key:
        return EmbeddingTestResponse(
            status="failed",
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            dimensions=config.dimensions,
            message="本地凭据服务没有找到 embedding API 密钥，请重新保存密钥。",
            error_code="credential_missing",
        )

    started = perf_counter()
    client = LangChainEmbeddingClient(
        api_key=api_key,
        base_url=config.base_url,
        model=config.model,
        dimensions=config.dimensions,
        timeout_seconds=defaults.model_timeout_seconds,
    )
    try:
        vector = await client.embed_query("embedding connection test")
    except ChatModelError as exc:
        return EmbeddingTestResponse(
            status="failed",
            provider=config.provider,
            base_url=config.base_url,
            model=config.model,
            dimensions=config.dimensions,
            latency_ms=_elapsed_ms(started),
            message=str(exc),
            error_code=exc.code,
            error_detail=exc.detail,
        )
    return EmbeddingTestResponse(
        status="ok",
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        dimensions=len(vector),
        latency_ms=_elapsed_ms(started),
        message=f"Embedding 试连成功，向量维度：{len(vector)}",
    )


@router.get("/agent-models", response_model=AgentModelsResponse)
async def get_agent_models(
    store: SettingsStore = Depends(settings_store_dependency),
) -> AgentModelsResponse:
    defaults = get_settings()
    agents = store.list_agent_model_settings(
        default_provider="openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    return AgentModelsResponse(
        agents=[_agent_model_response(agent) for agent in agents]
    )


@router.put("/agent-models", response_model=AgentModelsResponse)
async def set_agent_models(
    request: AgentModelsRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> AgentModelsResponse:
    for agent_config in request.agents:
        agent_id = _require_agent_id(agent_config.agent_id)
        _set_agent_config(store, agent_id, agent_config)
    return await get_agent_models(store)


@router.put("/agent-models/{agent_id}/config", response_model=AgentModelConfigResponse)
@router.put("/agent-models/{agent_id}/model-config", response_model=AgentModelConfigResponse)
async def set_agent_model_config(
    agent_id: str,
    model_config: AgentModelConfigRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> AgentModelConfigResponse:
    _ensure_supported_provider(model_config.provider)
    normalized_agent_id = _resolve_agent_id(agent_id)
    saved = _set_agent_config(store, normalized_agent_id, model_config)
    key_status = store.get_agent_model_key_status(
        normalized_agent_id,
        provider=saved.provider,
    )
    return AgentModelConfigResponse(
        agent_id=normalized_agent_id,
        provider=saved.provider,
        base_url=saved.base_url,
        model=saved.model,
        enabled=model_config.enabled,
        status="configured" if key_status.configured and model_config.enabled else "missing_key",
        configured=key_status.configured,
        masked=key_status.masked,
    )


@router.put("/agent-models/{agent_id}/key", response_model=AgentModelConfigResponse)
@router.put("/agent-models/{agent_id}/model-key", response_model=AgentModelConfigResponse)
async def set_agent_model_key(
    agent_id: str,
    model_key: AgentModelKeyRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> AgentModelConfigResponse:
    normalized_agent_id = _resolve_agent_id(agent_id)
    defaults = get_settings()
    existing_config = store.get_agent_model_config(
        normalized_agent_id,
        default_provider="openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    provider = model_key.provider or (existing_config.provider if existing_config else "openai-compatible")
    _ensure_supported_provider(provider)
    try:
        key_status = store.set_agent_model_key(
            agent_id=normalized_agent_id,
            provider=provider,
            api_key=model_key.api_key,
        )
    except ConfigurationError as exc:
        _raise_configuration_error(exc)
    except CredentialStoreError as exc:
        _raise_credential_store_error(exc)
    config = store.get_agent_model_config(
        normalized_agent_id,
        default_provider=key_status.provider or provider,
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    if config is None:
        config = store.set_agent_model_config(
            agent_id=normalized_agent_id,
            provider=provider,
            base_url="",
            model="",
        )
    return AgentModelConfigResponse(
        agent_id=normalized_agent_id,
        provider=config.provider,
        base_url=config.base_url,
        model=config.model,
        enabled=True,
        status="configured",
        configured=key_status.configured,
        masked=key_status.masked,
    )


@router.put("/agent-model-config", response_model=AgentModelConfigResponse)
async def set_agent_model_config_legacy(
    model_config: AgentModelConfigRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> AgentModelConfigResponse:
    agent_id = _require_agent_id(model_config.agent_id)
    return await set_agent_model_config(agent_id, model_config, store)


@router.put("/agent-model-key", response_model=ModelKeyResponse)
async def set_agent_model_key_legacy(
    model_key: AgentModelKeyRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelKeyResponse:
    agent_id = _require_agent_id(model_key.agent_id)
    defaults = get_settings()
    existing_config = store.get_agent_model_config(
        agent_id,
        default_provider="openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    provider = model_key.provider or (existing_config.provider if existing_config else "openai-compatible")
    _ensure_supported_provider(provider)
    try:
        status_value = store.set_agent_model_key(
            agent_id=agent_id,
            provider=provider,
            api_key=model_key.api_key,
        )
    except ConfigurationError as exc:
        _raise_configuration_error(exc)
    except CredentialStoreError as exc:
        _raise_credential_store_error(exc)
    return ModelKeyResponse(
        provider=status_value.provider or provider,
        status="configured",
        masked=status_value.masked or "****",
    )


@router.post("/agent-model-test", response_model=ModelTestResponse)
async def test_agent_model_connection_legacy(
    request: ModelTestRequest,
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelTestResponse:
    return await test_model_connection(request, store)


@router.post("/model-test", response_model=ModelTestResponse)
async def test_model_connection(
    request: ModelTestRequest | None = Body(default=None),
    store: SettingsStore = Depends(settings_store_dependency),
) -> ModelTestResponse:
    agent_id = _resolve_optional_agent_id(request.agent_id if request else None)
    defaults = get_settings()
    model_status, model_config = _model_settings_for_test(store, agent_id)
    provider = model_config.provider.strip()
    normalized_provider = provider.lower()
    base_url = model_config.base_url
    model = model_config.model

    if normalized_provider not in {"openai", "openai-compatible", "openai_compatible"}:
        return ModelTestResponse(
            status="failed",
            agent_id=agent_id,
            provider=provider,
            base_url=base_url,
            model=model,
            message="当前模型提供方暂不支持试连，请使用 OpenAI 兼容接口。",
            error_code="unsupported_provider",
            error_detail=f"provider={provider}",
        )

    if not model_status.configured:
        return ModelTestResponse(
            status="failed",
            agent_id=agent_id,
            provider=provider,
            base_url=base_url,
            model=model,
            message="尚未保存 API 密钥，请先填写并保存密钥。",
            error_code="not_configured",
        )

    if agent_id is not None and store.is_agent_model_enabled(agent_id):
        api_key = store.get_agent_model_key(agent_id=agent_id, provider=provider)
        if not api_key and model_status.provider:
            api_key = store.get_agent_model_key(
                agent_id=agent_id,
                provider=model_status.provider,
            )
    else:
        api_key = store.get_model_key(provider)
        if not api_key and model_status.provider:
            api_key = store.get_model_key(model_status.provider)
    if not api_key:
        return ModelTestResponse(
            status="failed",
            agent_id=agent_id,
            provider=provider,
            base_url=base_url,
            model=model,
            message="本地凭据服务没有找到 API 密钥，请重新保存密钥。",
            error_code="credential_missing",
        )

    client = LangChainGraphChatClient(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout_seconds=defaults.model_timeout_seconds,
    )
    started = perf_counter()
    try:
        reply = await client.complete(
            user_message="请只回复 OK，用于测试模型连接。",
            system_prompt="你正在执行桌面应用的模型连接测试。只回复 OK。",
        )
    except ChatModelError as exc:
        return ModelTestResponse(
            status="failed",
            agent_id=agent_id,
            provider=provider,
            base_url=base_url,
            model=model,
            latency_ms=_elapsed_ms(started),
            message=str(exc),
            error_code=exc.code,
            error_detail=exc.detail,
        )

    return ModelTestResponse(
        status="ok",
        agent_id=agent_id,
        provider=provider,
        base_url=base_url,
        model=model,
        latency_ms=_elapsed_ms(started),
        message=f"模型试连成功，已收到回复：{reply[:80]}",
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _ensure_supported_provider(provider: str) -> None:
    if not is_supported_model_provider(provider):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="当前模型提供方暂不支持，请使用 openai-compatible。",
        )


def _raise_credential_store_error(exc: CredentialStoreError) -> None:
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
    ) from exc


def _raise_configuration_error(exc: ConfigurationError) -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc


def _set_agent_config(
    store: SettingsStore,
    agent_id: str,
    model_config: AgentModelConfigRequest,
) -> ModelConfig:
    normalized_agent_id = _resolve_agent_id(agent_id)
    return store.set_agent_model_config(
        agent_id=normalized_agent_id,
        provider=model_config.provider,
        base_url=model_config.base_url,
        model=model_config.model,
        enabled=model_config.enabled,
    )


def _model_settings_for_test(
    store: SettingsStore,
    agent_id: str | None,
) -> tuple[ModelKeyStatus, ModelConfig]:
    defaults = get_settings()
    if agent_id is None or not store.is_agent_model_enabled(agent_id):
        model_status = store.get_model_key_status()
        model_config = store.get_model_config(
            default_provider=model_status.provider or "openai-compatible",
            default_base_url=defaults.model_base_url,
            default_model=defaults.chat_model,
        )
        return model_status, model_config

    model_status = store.get_agent_model_key_status(agent_id)
    model_config = store.get_agent_model_config(
        agent_id,
        default_provider=model_status.provider or "openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    if model_config is None:
        return ModelKeyStatus(provider=None, configured=False), ModelConfig(
            provider="",
            base_url="",
            model="",
        )
    provider_status = store.get_agent_model_key_status(
        agent_id,
        provider=model_config.provider,
    )
    if provider_status.configured:
        model_status = provider_status
    return model_status, model_config


def _require_agent_id(agent_id: str | None) -> str:
    if agent_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="缺少 agent_id。",
        )
    return _resolve_agent_id(agent_id)


def _resolve_optional_agent_id(agent_id: str | None) -> str | None:
    if agent_id is None:
        return None
    return _resolve_agent_id(agent_id)


def _resolve_agent_id(agent_id: object) -> str:
    normalized = getattr(agent_id, "value", str(agent_id)).strip()
    if normalized not in AGENT_MODEL_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"unsupported agent_id: {agent_id}（不支持的 agent_id）",
        )
    return normalized


def _agent_model_responses(store: SettingsStore) -> list[AgentModelConfigResponse]:
    defaults = get_settings()
    agents = store.list_agent_model_settings(
        default_provider="openai-compatible",
        default_base_url=defaults.model_base_url,
        default_model=defaults.chat_model,
    )
    return [_agent_model_response(agent) for agent in agents]


def _agent_model_response(agent) -> AgentModelConfigResponse:
    return AgentModelConfigResponse(
        agent_id=agent.agent_id,
        provider=agent.provider or "",
        base_url=agent.base_url or "",
        model=agent.model or "",
        enabled=agent.enabled,
        status="configured" if agent.configured else "missing_key",
        configured=agent.configured,
        masked=agent.masked,
    )
