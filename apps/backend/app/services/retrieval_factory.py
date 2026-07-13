from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.services.embeddings import LangChainEmbeddingClient
from app.services.settings import CredentialStoreError, SettingsStore
from app.services.vector_index import LangChainQdrantVectorIndex, VectorIndexConfig


logger = logging.getLogger(__name__)

_SUPPORTED_REMOTE_PROVIDERS = {"openai", "openai-compatible"}
_NORMALIZATION = "l2"
_CHUNKER_VERSION = "markdown-chunker.v1"
_INDEX_VERSION = "vector-index.v1"
_PRIVACY_POLICY_VERSION = "embedding-privacy.v1"
_TRANSPORT_CLASS = "remote-approved"


def build_vector_index(db_path: str | Path, settings: Settings) -> LangChainQdrantVectorIndex:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store: SettingsStore | None = None
    try:
        store = SettingsStore(db_path)
        automation = store.get_automation_settings()
        key_status = store.get_embedding_key_status()
        config = store.get_embedding_config(
            default_provider=key_status.provider or "openai-compatible",
            default_base_url=settings.embedding_base_url,
            default_model=settings.embedding_model,
            default_dimensions=settings.embedding_dimensions,
        )
        provider = _normalize_provider(config.provider)
        supported_provider = provider in _SUPPORTED_REMOTE_PROVIDERS
        configured_provider = _normalize_provider(key_status.provider or "")
        embedding_configured = bool(key_status.configured and configured_provider == provider)
        api_key: str | None = None
        unavailable_reason: str | None = None
        if supported_provider:
            stored_key = store.get_embedding_key(config.provider)
            embedding_configured = bool(stored_key)
            if not automation.local_privacy_mode:
                api_key = stored_key
        if automation.local_privacy_mode:
            unavailable_reason = "local_privacy_mode"
        elif not supported_provider:
            unavailable_reason = "embedding_provider_unsupported"
        elif not embedding_configured:
            unavailable_reason = "embedding_api_key_missing"

        enabled = bool(
            not automation.local_privacy_mode
            and supported_provider
            and embedding_configured
            and api_key
        )
        embeddings = None
        legacy_initialization_error_type: str | None = None
        if enabled:
            try:
                embeddings = LangChainEmbeddingClient(
                    api_key=api_key or "",
                    base_url=config.base_url,
                    model=config.model,
                    dimensions=config.dimensions,
                    timeout_seconds=settings.model_timeout_seconds,
                ).create_embeddings()
            except Exception as exc:
                enabled = False
                unavailable_reason = "embedding_initialization_failed"
                embeddings = None
                legacy_initialization_error_type = exc.__class__.__name__
                logger.warning(
                    "Embedding client initialization failed; optional vector search is disabled"
                )
        vector_index = _vector_index(
            settings=settings,
            enabled=enabled,
            provider=provider,
            model=config.model,
            dimensions=config.dimensions,
            embeddings=embeddings,
            unavailable_reason=unavailable_reason,
            embedding_configured=embedding_configured,
        )
        if legacy_initialization_error_type is not None:
            vector_index._legacy_initialization_error_type = legacy_initialization_error_type
        return vector_index
    except CredentialStoreError:
        logger.warning("Embedding credential store is unavailable; optional vector search is disabled")
        return _vector_index(
            settings=settings,
            enabled=False,
            provider="openai-compatible",
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            embeddings=None,
            unavailable_reason="credential_store_unavailable",
            embedding_configured=False,
        )
    except Exception:
        logger.warning("Embedding configuration is unavailable; optional vector search is disabled")
        return _vector_index(
            settings=settings,
            enabled=False,
            provider="openai-compatible",
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            embeddings=None,
            unavailable_reason="embedding_configuration_unavailable",
            embedding_configured=False,
        )
    finally:
        if store is not None:
            try:
                store.close()
            except Exception:
                logger.warning("Embedding settings store close failed")


def _vector_index(
    *,
    settings: Settings,
    enabled: bool,
    provider: str,
    model: str,
    dimensions: int | None,
    embeddings,
    unavailable_reason: str | None,
    embedding_configured: bool,
) -> LangChainQdrantVectorIndex:
    return LangChainQdrantVectorIndex(
        VectorIndexConfig(
            enabled=enabled,
            root_path=settings.data_dir / "vector-index",
            collection_name=_collection_name(model, dimensions),
            embedding_model=model,
            embeddings=embeddings,
            unavailable_reason=unavailable_reason,
            embedding_provider=provider,
            embedding_dimensions=dimensions,
            normalization=_NORMALIZATION,
            chunker_version=_CHUNKER_VERSION,
            index_version=_INDEX_VERSION,
            privacy_policy_version=_PRIVACY_POLICY_VERSION,
            transport_class=_TRANSPORT_CLASS,
            embedding_configured=embedding_configured,
            qdrant_client=None,
        )
    )


def _collection_name(model: str, dimensions: int | None) -> str:
    safe_model = "".join(ch if ch.isalnum() else "_" for ch in model.lower()).strip("_") or "embeddings"
    suffix = f"_{dimensions}" if dimensions else ""
    return f"agent_pet_{safe_model}{suffix}"


def _normalize_provider(provider: str) -> str:
    return provider.strip().casefold().replace("_", "-")
