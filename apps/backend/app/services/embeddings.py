from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.chat_model import ChatModelError, classify_chat_model_exception

logger = logging.getLogger(__name__)

# bge-small-zh-v1.5 官方 model card：检索查询需加该指令前缀，文档侧不加。
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："
LOCAL_EMBEDDING_MODEL_NAME = "bge-small-zh-v1.5"
LOCAL_EMBEDDING_DIMENSIONS = 512
_LOCAL_EMBEDDING_MAX_TOKENS = 512


class LocalEmbeddingUnavailableError(RuntimeError):
    """Raised when the local ONNX embedding model cannot be loaded."""


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


class LocalOnnxEmbeddings:
    """bge-small-zh-v1.5 over onnxruntime: CLS pooling + L2 normalization.

    Exposes the synchronous embed_query/embed_documents surface that
    LangChainQdrantVectorIndex expects, so the same vector index works
    with a remote provider or with the bundled local model without any
    other change.  Query text gets the official retrieval instruction;
    document text does not (per the model card).
    """

    def __init__(self, model_dir: Path) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        model_path = model_dir / "model.onnx"
        tokenizer_path = model_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise LocalEmbeddingUnavailableError(
                f"local embedding model files missing under {model_dir}"
            )
        try:
            self._session = onnxruntime.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_truncation(max_length=_LOCAL_EMBEDDING_MAX_TOKENS)
            self._tokenizer.enable_padding(pad_id=0, pad_type_id=0)
            # 共享实例可能被多线程并发使用（线程池检索 + 设置页探测），
            # 串行化 tokenizer/session 调用，兼容旧版 tokenizers 的非线程安全绑定。
            self._lock = threading.Lock()
        except Exception as exc:
            raise LocalEmbeddingUnavailableError(
                f"local embedding model failed to load under {model_dir}: {exc}"
            ) from exc

    def embed_query(self, text: str) -> list[float]:
        return self._embed([BGE_QUERY_INSTRUCTION + str(text)])[0]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._embed([str(text) for text in texts])

    def _embed(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        with self._lock:
            encoded = [self._tokenizer.encode(text) for text in texts]
            length = max(len(item.ids) for item in encoded)
            batch = {
                key: np.asarray(
                    [
                        list(getattr(item, field)) + [0] * (length - len(getattr(item, field)))
                        for item in encoded
                    ],
                    dtype=np.int64,
                )
                for key, field in (
                    ("input_ids", "ids"),
                    ("attention_mask", "attention_mask"),
                    ("token_type_ids", "type_ids"),
                )
            }
            hidden = self._session.run(["last_hidden_state"], batch)[0]
            cls = np.asarray(hidden)[:, 0, :].astype(np.float32)
            norms = np.linalg.norm(cls, axis=1, keepdims=True)
            normalized = cls / np.maximum(norms, 1e-12)
        return [row.tolist() for row in normalized]


def build_local_onnx_embeddings(model_dir: Path | None) -> LocalOnnxEmbeddings | None:
    """Load the bundled model or return None (caller falls back)."""
    if model_dir is None:
        return None
    try:
        return LocalOnnxEmbeddings(model_dir)
    except LocalEmbeddingUnavailableError:
        logger.warning(
            "Local embedding model unavailable under %s; vector search will stay disabled",
            model_dir,
            exc_info=True,
        )
        return None
    except ImportError:
        logger.warning("onnxruntime/tokenizers missing; vector search will stay disabled")
        return None
