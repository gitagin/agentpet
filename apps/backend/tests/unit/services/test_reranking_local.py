from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

from app.services.retrieval_fusion import FusedCandidate
from app.services.reranking import DisabledReranker, RerankerResponse
from app.services.reranking_local import (
    LocalCrossEncoderReranker,
    build_local_reranker,
    _candidate_pair,
    _token_type_ids,
)


def _candidate(stable_id: str, payload: object) -> FusedCandidate:
    return FusedCandidate(
        stable_id=stable_id,
        content_hash=f"hash-{stable_id}",
        source_scope="knowledge_base",
        payload=payload,
        score=0.0,
        best_rank=1,
        contributions=(),
    )


class _FakeTokenizer:
    """XLM-RoBERTa 形态的假分词器：pad=1、分隔符 </s>=2（无 BERT [SEP]=102）。"""

    def __init__(self) -> None:
        self.encode_calls: list[tuple[str, str]] = []

    def enable_truncation(self, *, max_length: int) -> None:
        del max_length

    @staticmethod
    def from_file(path: str):
        del path
        return _FakeTokenizer()

    def token_to_id(self, token: str):
        return {"</s>": 2}.get(token)

    def encode(self, query: str, text: str) -> object:
        self.encode_calls.append((query, text))
        ids = [0, 5, 6, 2, 2, 7, 8, 2]
        if text:
            ids.extend([7] * len(text))
        return types.SimpleNamespace(ids=ids)


class _FakeSession:
    """量化导出只声明 input_ids / attention_mask 两个输入；每次 run 消费一个 logits。"""

    def __init__(self, logits_per_call: list[np.ndarray]) -> None:
        self._queue = list(logits_per_call)
        self.run_calls: list[tuple] = []

    def get_inputs(self):
        return [
            types.SimpleNamespace(name="input_ids"),
            types.SimpleNamespace(name="attention_mask"),
        ]

    def get_outputs(self):
        return [types.SimpleNamespace(name="logits")]

    def run(self, output_names, feeds):
        self.run_calls.append((output_names, feeds))
        return [self._queue.pop(0)]


def _install_fake_backends(
    monkeypatch,
    tmp_path: Path,
    logits_per_call: list[np.ndarray],
) -> _FakeSession:
    session = _FakeSession(logits_per_call)
    fake_onnx = types.ModuleType("onnxruntime")
    fake_onnx.InferenceSession = lambda path, providers: session
    fake_tokenizers = types.ModuleType("tokenizers")
    fake_tokenizers.Tokenizer = _FakeTokenizer
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_onnx)
    monkeypatch.setitem(sys.modules, "tokenizers", fake_tokenizers)
    (tmp_path / "model.onnx").write_bytes(b"fake")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    return session


def test_build_local_reranker_disabled_when_model_dir_is_none() -> None:
    reranker = build_local_reranker(model_dir=None)

    assert isinstance(reranker, DisabledReranker)


def test_build_local_reranker_disabled_when_model_files_missing(tmp_path: Path) -> None:
    reranker = build_local_reranker(model_dir=tmp_path / "missing")

    assert isinstance(reranker, DisabledReranker)


def test_local_reranker_orders_by_sigmoid_score_desc(tmp_path: Path, monkeypatch) -> None:
    session = _install_fake_backends(
        monkeypatch,
        tmp_path,
        [np.asarray([[-2.2]], dtype=np.float32), np.asarray([[2.2]], dtype=np.float32)],
    )
    reranker = LocalCrossEncoderReranker(model_dir=tmp_path)
    candidates = [
        _candidate("low", {"title": "t", "text": "irrelevant"}),
        _candidate("high", {"title": "t", "text": "relevant"}),
    ]

    response = reranker.rerank(query="q", candidates=candidates, timeout_seconds=1.0)

    assert response == RerankerResponse(ordered_ids=("high", "low"))
    assert response.external_request_count == 0
    assert response.transmitted_bytes == 0
    assert len(session.run_calls) == 2


def test_local_reranker_returns_empty_for_no_candidates(tmp_path: Path, monkeypatch) -> None:
    _install_fake_backends(
        monkeypatch,
        tmp_path,
        [np.asarray([[]], dtype=np.float32).reshape(0, 1)],
    )
    reranker = LocalCrossEncoderReranker(model_dir=tmp_path)

    response = reranker.rerank(query="q", candidates=(), timeout_seconds=1.0)

    assert response.ordered_ids == ()


def test_local_reranker_scores_each_pair_in_its_own_unpadded_batch(
    tmp_path: Path, monkeypatch
) -> None:
    session = _install_fake_backends(
        monkeypatch,
        tmp_path,
        [
            np.asarray([[-1.0]], dtype=np.float32),
            np.asarray([[-0.5]], dtype=np.float32),
        ],
    )
    reranker = LocalCrossEncoderReranker(model_dir=tmp_path)
    candidates = [
        _candidate("short", {"title": "t", "text": "短"}),
        _candidate("long", {"title": "t", "text": "长" * 40}),
    ]

    reranker.rerank(query="q", candidates=candidates, timeout_seconds=1.0)

    # 量化模型对 padding/批大小不敏感，因此必须逐对 batch=1 推理：
    # 两次 run、每次只含 input_ids/attention_mask、长度互不补齐。
    assert len(session.run_calls) == 2
    lengths = set()
    for output_names, feeds in session.run_calls:
        assert output_names == ["logits"]
        assert set(feeds.keys()) == {"input_ids", "attention_mask"}
        for value in feeds.values():
            assert value.shape[0] == 1
        lengths.add(feeds["input_ids"].shape[1])
    assert len(lengths) == 2


def test_candidate_pair_extracts_text_from_dict_payload() -> None:
    pair = _candidate_pair(_candidate("id", {"title": "标题", "text": "正文"}))

    assert pair.stable_id == "id"
    assert pair.text == "标题 正文"


def test_candidate_pair_prefers_full_content_over_snippet() -> None:
    pair = _candidate_pair(
        _candidate(
            "id",
            {"title": "标题", "snippet": "截断摘要", "content": "完整正文内容"},
        )
    )

    assert pair.text == "标题 完整正文内容"


def test_token_type_ids_split_at_sep() -> None:
    assert _token_type_ids([0, 5, 6, 2, 2, 7, 8, 2], 2) == [0, 0, 0, 0, 1, 1, 1, 1]
    assert _token_type_ids([101, 1, 102, 3, 4], 102) == [0, 0, 0, 1, 1]
    assert _token_type_ids([101, 1, 2], 102) == [0, 0, 0]
