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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from app.services.reranking import Reranker, RerankerResponse
from app.services.retrieval_fusion import FusedCandidate

logger = logging.getLogger(__name__)

LOCAL_RERANKER_NAME = "bge-reranker-base-onnx"
LOCAL_RERANKER_MAX_TOKENS = 512
_PAIR_SEPARATOR_TOKEN_ID = 102  # [SEP] for the BERT-family rerankers


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

    def __post_init__(self) -> None:
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
            self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
            self._tokenizer.enable_truncation(max_length=LOCAL_RERANKER_MAX_TOKENS)
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
        del timeout_seconds
        pairs = [_candidate_pair(candidate) for candidate in candidates]
        if not pairs:
            return RerankerResponse(ordered_ids=tuple())
        encoded = [self._encode(query, pair.text) for pair in pairs]
        scores = self._score(encoded)
        ordered = [
            pairs[index].stable_id
            for index in sorted(range(len(pairs)), key=lambda i: scores[i], reverse=True)
        ]
        return RerankerResponse(ordered_ids=tuple(ordered))

    def _encode(self, query: str, text: str) -> dict[str, list[int]]:
        encoding = self._tokenizer.encode(query, text)
        ids = encoding.ids[:LOCAL_RERANKER_MAX_TOKENS]
        return {
            "input_ids": ids,
            "attention_mask": [1] * len(ids),
            "token_type_ids": _token_type_ids(ids),
        }

    def _score(self, encoded: list[dict[str, list[int]]]) -> list[float]:
        import numpy as np

        batch = {
            key: np.asarray(
                [item[key] for item in encoded],
                dtype=np.int64,
            )
            for key in encoded[0]
        }
        output_name = self._session.get_outputs()[0].name
        logits = self._session.run([output_name], batch)[0]
        flat = np.asarray(logits).reshape(-1).tolist()
        return [_sigmoid(float(value)) for value in flat]


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
        text = str(payload.get("text") or payload.get("snippet") or payload.get("content") or "")
    else:
        title = str(getattr(payload, "title", "") or "")
        text = str(
            getattr(payload, "snippet", "")
            or getattr(payload, "content", "")
            or getattr(payload, "heading", "")
            or ""
        )
    combined = " ".join(part for part in (title, text) if part)
    return _PairText(stable_id=candidate.stable_id, text=combined)


def _token_type_ids(ids: list[int]) -> list[int]:
    """BERT pair encoding: 0 until the first [SEP], 1 after it."""
    marker = ids.index(_PAIR_SEPARATOR_TOKEN_ID) if _PAIR_SEPARATOR_TOKEN_ID in ids else len(ids)
    return [0 if index <= marker else 1 for index in range(len(ids))]


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + 2.718281828459045 ** -value)
    raised = 2.718281828459045**value
    return raised / (1.0 + raised)
