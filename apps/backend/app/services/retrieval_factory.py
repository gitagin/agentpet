from __future__ import annotations

import logging
from pathlib import Path

from app.config import Settings
from app.services.embeddings import LangChainEmbeddingClient
from app.services.settings import SettingsStore
from app.services.vector_index import LangChainQdrantVectorIndex, VectorIndexConfig


logger = logging.getLogger(__name__)


def build_vector_index(db_path: str | Path, settings: Settings) -> LangChainQdrantVectorIndex:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    store = SettingsStore(db_path)
    try:
        key_status = store.get_embedding_key_status()
        config = store.get_embedding_config(
            default_provider=key_status.provider or "openai-compatible",
            default_base_url=settings.embedding_base_url,
            default_model=settings.embedding_model,
            default_dimensions=settings.embedding_dimensions,
        )
        api_key = store.get_embedding_key(config.provider)
        if not api_key and key_status.provider:
            api_key = store.get_embedding_key(key_status.provider)
        provider = config.provider.strip().lower()
        enabled = bool(api_key and provider in {"openai", "openai-compatible", "openai_compatible"})
        unavailable_reason = None
        if not api_key:
            unavailable_reason = "embedding_api_key_missing"
        elif provider not in {"openai", "openai-compatible", "openai_compatible"}:
            unavailable_reason = "embedding_provider_unsupported"
        embeddings = None
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
                unavailable_reason = exc.__class__.__name__
                embeddings = None
                logger.warning(
                    "Embedding client initialization failed; vector search is disabled",
                    exc_info=True,
                    extra={"provider": config.provider, "model": config.model},
                )
        return LangChainQdrantVectorIndex(
            VectorIndexConfig(
                enabled=enabled,
                root_path=settings.data_dir / "vector-index",
                collection_name=_collection_name(config.model, config.dimensions),
                embedding_model=config.model,
                embeddings=embeddings,
                unavailable_reason=unavailable_reason,
            )
        )
    finally:
        store.close()


def _collection_name(model: str, dimensions: int | None) -> str:
    safe_model = "".join(ch if ch.isalnum() else "_" for ch in model.lower()).strip("_") or "embeddings"
    suffix = f"_{dimensions}" if dimensions else ""
    return f"agent_pet_{safe_model}{suffix}"
