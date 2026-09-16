"""Local cross-encoder reranking over ONNX, without torch.

The product contract keeps the deterministic retrieval layer free of
heavy ML dependencies.  This module is therefore import-safe: both
`onnxruntime` and `tokenizers` are imported lazily inside
:func:`build_local_reranker`, so a base install that lacks them simply
falls back to :class:`~app.services.reranking.DisabledReranker` instead
of failing at import time.  The ONNX model and tokenizer live on disk
next to the packaged sidecar and are loaded once per process.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.services.reranking import Reranker, RerankerResponse
from app.services.retrieval_fusion import FusedCandidate

logger = logging.getLogger(__name__)

LOCAL_RERANKER_NAME = "bge-reranker-base-onnx"
LOCAL_RERANKER_MAX_TOKENS = 512


class LocalRerankerUnavailableError(RuntimeError):
    """Raised when the local reranker cannot be initialised.

    Callers convert this into a disabled-reranker fallback; it never
    escapes to the API as an internal error.
    """


@dataclass(frozen=True, slots=True)
class _PairText:
    stable_id: str
    text: str


@dataclass(slots=True)
class LocalCrossEncoderReranker:
    """Cross-encoder reranker backed by an ONNX session."""

    model_dir: Path = field(repr=False)
    name: str = LOCAL_RERANKER_NAME
    enabled: bool = True
    is_remote: bool = False

    _session: Any = field(default=None, init=False, repr=False)
    _tokenizer: Any = field(default=None, init=False, repr=False)
    _input_names: tuple[str, ...] = field(default=(), init=False, repr=False)
    _pair_sep_id: int = field(default=2, init=False, repr=False)
    _lock: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        import onnxruntime
        from tokenizers import Tokenizer

        model_path = self.model_dir / "model.onnx"
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not model_path.is_file() or not tokenizer_path.is_file():
            raise LocalRerankerUnavailableError(
                f"local reranker model files missing under {self.model_dir}"
            )
        try:
            self._session = onnxruntime.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
            # 量化导出模型可能只声明 input_ids/attention_mask（无 token_type_ids），
            # 以会话实际声明的输入为准构造 batch；接口缺失时回退到编码键全集。
            get_inputs = getattr(self._session, "get_inputs", None)
            self._input_names = (
                tuple(item.name for item in get_inputs())
                if callable(get_inputs)
                else ("input_ids", "attention_mask", "token_type_ids")
            )
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_truncation(max_length=LOCAL_RERANKER_MAX_TOKENS)
            self._pair_sep_id = _pair_separator_token_id(self._tokenizer)
        except Exception as exc:
            raise LocalRerankerUnavailableError(
                f"local reranker failed to load under {self.model_dir}: {exc}"
            ) from exc

    def rerank(
        self,
        *,
        query: str,
        candidates: Sequence[FusedCandidate],
        timeout_seconds: float,
    ) -> RerankerResponse:
        pairs = [_candidate_pair(candidate) for candidate in candidates]
        if not pairs:
            return RerankerResponse(ordered_ids=tuple())
        # 本地重排跑在线程池里且不可被 asyncio 取消：内部自行按时限中止，
        # 尽快释放 _lock，避免外层 wait_for 超时后孤儿线程继续占锁。
        deadline: float | None = None
        if timeout_seconds and timeout_seconds > 0:
            deadline = time.monotonic() + timeout_seconds
        encoded: list[dict[str, list[int]]] = []
        for pair in pairs:
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError("local reranker timed out")
            encoded.append(self._encode(query, pair.text))
        scores = self._score(encoded, deadline=deadline)
        ordered = [
            pairs[index].stable_id
            for index in sorted(range(len(pairs)), key=lambda i: scores[i], reverse=True)
        ]
        return RerankerResponse(ordered_ids=tuple(ordered))

    def _encode(self, query: str, text: str) -> dict[str, list[int]]:
        # 共享 tokenizer 与 embeddings 持同一假设：旧版 tokenizers 绑定非线程安全，
        # encode 必须与 session.run 一样纳入锁内串行化。
        with self._lock:
            encoding = self._tokenizer.encode(query, text)
            ids = encoding.ids[:LOCAL_RERANKER_MAX_TOKENS]
        return {
            "input_ids": ids,
            "attention_mask": [1] * len(ids),
            "token_type_ids": _token_type_ids(ids, self._pair_sep_id),
        }

    def _score(
        self,
        encoded: list[dict[str, list[int]]],
        *,
        deadline: float | None = None,
    ) -> list[float]:
        import numpy as np

        # 该量化导出的交叉编码器对 padding 与批大小不敏感：实测给一对文本追加
        # 一个被 mask 的 pad token（或把短样本放进同一批）就会改变 logits，
        # 因此逐对独立推理（batch=1、自然长度、零 padding），保证每个候选的
        # 分数只取决于它自己，批内互不污染排序。
        keys = [key for key in encoded[0] if key in self._input_names]
        output_name = self._session.get_outputs()[0].name
        scores: list[float] = []
        with self._lock:
            for item in encoded:
                if deadline is not None and time.monotonic() > deadline:
                    raise TimeoutError("local reranker timed out")
                batch = {
                    key: np.asarray([item[key]], dtype=np.int64)
                    for key in keys
                }
                logits = self._session.run([output_name], batch)[0]
                scores.append(float(np.asarray(logits).reshape(-1)[0]))
        return [_sigmoid(value) for value in scores]


def build_local_reranker(*, model_dir: Path | None) -> Reranker:
    """Build the local reranker or fall back to a disabled one.

    Every failure mode converges on :class:`DisabledReranker` with a
    logged reason, mirroring the vector index fallback policy.
    """
    from app.services.reranking import DisabledReranker

    if model_dir is None:
        return DisabledReranker()
    try:
        return LocalCrossEncoderReranker(model_dir=model_dir)
    except LocalRerankerUnavailableError:
        logger.warning(
            "Local reranker unavailable under %s; falling back to disabled reranker.",
            model_dir,
            exc_info=True,
        )
        return DisabledReranker()
    except ImportError:
        logger.warning("onnxruntime/tokenizers missing; falling back to disabled reranker.")
        return DisabledReranker()


def _candidate_pair(candidate: FusedCandidate) -> _PairText:
    payload = candidate.payload
    if isinstance(payload, dict):
        title = str(payload.get("title") or "")
        text = str(payload.get("content") or payload.get("text") or payload.get("snippet") or "")
    else:
        title = str(getattr(payload, "title", "") or "")
        text = str(
            getattr(payload, "content", "")
            or getattr(payload, "text", "")
            or getattr(payload, "snippet", "")
            or ""
        )
    combined = " ".join(part for part in (title, text) if part)
    return _PairText(stable_id=candidate.stable_id, text=combined)


def _token_type_ids(ids: list[int], sep_id: int) -> list[int]:
    """Pair encoding: 0 up to the first separator token, 1 after it."""
    marker = ids.index(sep_id) if sep_id in ids else len(ids)
    return [0 if index <= marker else 1 for index in range(len(ids))]


def _pair_separator_token_id(tokenizer: Any) -> int:
    """Resolve the pair separator id from the tokenizer, XLM-R (</s>) first."""
    for candidate in ("</s>", "[SEP]", "[sep]"):
        try:
            token_id = tokenizer.token_to_id(candidate)
        except Exception:
            token_id = None
        if isinstance(token_id, int):
            return token_id
    return 2


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + 2.718281828459045 ** -value)
    raised = 2.718281828459045**value
    return raised / (1.0 + raised)
