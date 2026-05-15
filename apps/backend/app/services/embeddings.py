from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from app.services.chat_model import ChatModelError, classify_chat_model_exception


class EmbeddingClientProtocol(Protocol):
    async def embed_query(self, text: str) -> list[float]:
        pass


EmbeddingFactory = Any


@dataclass(slots=True)
class LangChainEmbeddingClient:
    api_key: str
    base_url: str
    model: str
    dimensions: int | None = None
    timeout_seconds: float = 30.0
    embedding_factory: EmbeddingFactory | None = None

    async def embed_query(self, text: str) -> list[float]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._embed_query_sync, text),
                timeout=max(self.timeout_seconds, 0.001),
            )
        except ImportError as exc:
            raise ChatModelError(
                "LangChain embedding 依赖未安装，请先安装后端依赖。",
                code="dependency_missing",
            ) from exc
        except TimeoutError as exc:
            raise classify_chat_model_exception(exc) from exc
        except Exception as exc:
            raise classify_chat_model_exception(exc) from exc

    def create_embeddings(self) -> Any:
        factory = self.embedding_factory or _default_embedding_factory
        return factory(self)

    def _embed_query_sync(self, text: str) -> list[float]:
        embeddings = self.create_embeddings()
        vector = embeddings.embed_query(text)
        return [float(value) for value in vector]


def _default_embedding_factory(client: LangChainEmbeddingClient) -> Any:
    from langchain_openai import OpenAIEmbeddings

    kwargs: dict[str, Any] = {
        "api_key": client.api_key,
        "base_url": client.base_url.rstrip("/"),
        "model": client.model,
        "timeout": client.timeout_seconds,
    }
    if client.dimensions is not None:
        kwargs["dimensions"] = client.dimensions
    return OpenAIEmbeddings(**kwargs)
