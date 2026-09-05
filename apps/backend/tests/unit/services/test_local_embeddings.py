from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

from app.services.embeddings import (
    LocalOnnxEmbeddings,
    build_local_onnx_embeddings,
)


class _FakeTokenizer:
    encoded: list[str] = []

    def enable_truncation(self, *, max_length: int) -> None:
        del max_length

    def enable_padding(self, *, pad_id: int, pad_type_id: int) -> None:
        del pad_id, pad_type_id

    @staticmethod
    def from_file(path: str):
        del path
        _FakeTokenizer.encoded = []
        return _FakeTokenizer()

    def encode(self, text: str) -> object:
        _FakeTokenizer.encoded.append(text)
        return types.SimpleNamespace(ids=[101, 1, 102, 0], attention_mask=[1, 1, 1, 0], type_ids=[0, 0, 0, 0])


class _FakeSession:
    def __init__(self, hidden: np.ndarray) -> None:
        self._hidden = hidden
        self.run_calls: list[tuple] = []

    def run(self, output_names, feeds):
        self.run_calls.append((output_names, feeds))
        return [self._hidden]


def _install_fake_backends(monkeypatch, tmp_path: Path, hidden: np.ndarray) -> None:
    fake_onnx = types.ModuleType("onnxruntime")
    fake_onnx.InferenceSession = lambda path, providers: _FakeSession(hidden)
    fake_tokenizers = types.ModuleType("tokenizers")
    fake_tokenizers.Tokenizer = _FakeTokenizer
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_onnx)
    monkeypatch.setitem(sys.modules, "tokenizers", fake_tokenizers)
    (tmp_path / "model.onnx").write_bytes(b"fake")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")


def test_local_embeddings_apply_query_instruction_and_cls_normalize(tmp_path: Path, monkeypatch) -> None:
    hidden = np.asarray([[[3.0, 4.0, 0.0], [1.0, 1.0, 1.0]]], dtype=np.float32)
    _install_fake_backends(monkeypatch, tmp_path, hidden)

    model = LocalOnnxEmbeddings(tmp_path)
    vector = model.embed_query("我喜欢牛奶")

    assert len(vector) == 3
    assert abs(sum(x * x for x in vector) - 1.0) < 1e-6  # L2 归一化
    assert all(abs(a - b) < 1e-5 for a, b in zip(vector, [0.6, 0.8, 0.0]))  # CLS [3,4,0] 归一化


def test_local_embeddings_embed_documents_skip_query_instruction(tmp_path: Path, monkeypatch) -> None:
    hidden = np.asarray([[[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]], dtype=np.float32)
    _install_fake_backends(monkeypatch, tmp_path, hidden)

    model = LocalOnnxEmbeddings(tmp_path)
    model.embed_documents(["用户喜欢喝牛奶"])

    assert _FakeTokenizer.encoded == ["用户喜欢喝牛奶"]  # 文档侧不加前缀


def test_build_local_onnx_embeddings_returns_none_when_files_missing(tmp_path: Path) -> None:
    assert build_local_onnx_embeddings(tmp_path / "missing") is None
