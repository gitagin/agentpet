from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.services.embeddings import (
    LOCAL_EMBEDDING_DIMENSIONS,
    LOCAL_EMBEDDING_MODEL_NAME,
    LangChainEmbeddingClient,
    build_local_onnx_embeddings,
)
from app.services.settings import CredentialStoreError, SettingsStore
from app.services.vector_index import LangChainQdrantVectorIndex, VectorIndexConfig


logger = logging.getLogger(__name__)

_SUPPORTED_REMOTE_PROVIDERS = {"openai", "openai-compatible"}
_NORMALIZATION = "l2"
_CHUNKER_VERSION = "markdown-chunker.v1"
_INDEX_VERSION = "vector-index.v1"
_PRIVACY_POLICY_VERSION = "embedding-privacy.v1"
_TRANSPORT_REMOTE = "remote-approved"
_TRANSPORT_LOCAL = "local"


def build_vector_index(db_path: str | Path, settings: Settings) -> LangChainQdrantVectorIndex:
    """Resolve the embedding backend once: local by default, remote on explicit key.

    Precedence (single source of truth for the embedding decision):

    - Local privacy mode: always the bundled ONNX model; a configured remote
      key is ignored because remote transport would leak private text.
    - Explicitly configured remote key: remote provider (user opt-in).
    - Otherwise: bundled ONNX model; if it is missing, vector search stays
      disabled with a stable reason and FTS remains the fallback.
    """
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
        external_provider = _normalize_provider(config.provider)
        external_supported = external_provider in _SUPPORTED_REMOTE_PROVIDERS
        stored_key = None
        if external_supported:
            stored_key = store.get_embedding_key(config.provider)
        external_configured = bool(stored_key)

        local_embeddings = None
        if automation.local_privacy_mode or not external_configured:
            local_embeddings = build_local_onnx_embeddings(settings.local_embedding_dir)

        embeddings = None
        unavailable_reason: str | None = None
        embedding_configured = False
        provider = "openai-compatible"
        transport = _TRANSPORT_REMOTE
        dimensions = None
        legacy_initialization_error_type: str | None = None
        if automation.local_privacy_mode:
            provider = "local-onnx"
            transport = _TRANSPORT_LOCAL
            dimensions = LOCAL_EMBEDDING_DIMENSIONS
            if local_embeddings is not None:
                embeddings = local_embeddings
                embedding_configured = True
            else:
                unavailable_reason = "local_embedding_unavailable"
        elif external_configured and stored_key:
            provider = external_provider
            dimensions = config.dimensions
            try:
                embeddings = LangChainEmbeddingClient(
                    api_key=stored_key,
                    base_url=config.base_url,
                    model=config.model,
                    dimensions=config.dimensions,
                    timeout_seconds=settings.model_timeout_seconds,
                ).create_embeddings()
                embedding_configured = True
            except Exception as exc:
                unavailable_reason = "embedding_initialization_failed"
                legacy_initialization_error_type = exc.__class__.__name__
                logger.warning(
                    "Remote embedding client initialization failed; falling back to disabled vector search"
                )
        else:
            provider = "local-onnx"
            transport = _TRANSPORT_LOCAL
            dimensions = LOCAL_EMBEDDING_DIMENSIONS
            if local_embeddings is not None:
                embeddings = local_embeddings
                embedding_configured = True
            else:
                unavailable_reason = "local_embedding_unavailable"

        vector_index = _vector_index(
            settings=settings,
            enabled=embedding_configured,
            provider=provider,
            model=LOCAL_EMBEDDING_MODEL_NAME if transport == _TRANSPORT_LOCAL else config.model,
            dimensions=dimensions,
            embeddings=embeddings,
            unavailable_reason=unavailable_reason,
            embedding_configured=embedding_configured,
            transport_class=transport,
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
            transport_class=_TRANSPORT_REMOTE,
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
            transport_class=_TRANSPORT_REMOTE,
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
    transport_class: str,
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
            transport_class=transport_class,
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
