"""Wiki 快照检索「词法 + 语义」双路 RRF 融合的行为测试。

设计约束(与既有保证一致):
- 不注入嵌入器 = 纯词法单路,行为与历史完全一致;
- 嵌入器不可用/抛错 = 降级为纯词法,结果与不注入**逐条相同**;
- 语义腿不得绕过权限、版本钉扎与完整性校验;
- 既有 `score` 语义(bm25 取负,越大越相关)不得被破坏。

嵌入器用确定性桩,不依赖 onnxruntime/tokenizers,任何环境都可运行。
"""

from __future__ import annotations

from app.services.wiki.generations import WikiGenerationStore
from app.services.wiki.publication import WikiPublicationService
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from tests.test_wiki_publication import published

# 词法上完全查不到的查询:确保「语义腿单独把页捞回来」这件事可被观测。
LEXICAL_GAP_QUERY = "完全无关的查询字符串"


class MappingEmbedder:
    """确定性桩嵌入器:命中 needle 的文本映射到同一向量,其余给正交向量。"""

    def __init__(self, mapping, default=(0.0, 1.0)):
        self.mapping = tuple(mapping)
        self.default = tuple(default)

    def _vector(self, text):
        haystack = str(text).casefold()
        for needle, vector in self.mapping:
            if needle.casefold() in haystack:
                return list(vector)
        return list(self.default)

    def embed_query(self, text):
        return self._vector(text)

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]


class BrokenEmbedder:
    def embed_query(self, text):
        raise RuntimeError("embedding endpoint unavailable")

    def embed_documents(self, texts):
        raise RuntimeError("embedding endpoint unavailable")


class IncompleteEmbedder:
    """只有 embed_query、没有 embed_documents 的半成品实现。"""

    def embed_query(self, text):
        return [1.0, 0.0]


def _reader(service, embedder=None, authorize=None):
    return WikiSnapshotReader(
        service.database, service.wiki,
        authorize=authorize or (lambda vault, path: True),
        semantic_embedder=embedder,
    )


def _paths(candidates):
    return [candidate.relative_path for candidate in candidates]


def test_search_without_an_embedder_stays_lexical_only(published):
    service, _, _, _ = published
    reader = _reader(service)
    pin = reader.pin()
    hits = reader.search(pin, "supplier")
    assert hits
    assert reader.last_search_mode == "bm25"
    # 词法命中保留 bm25 取负后的正分(score 语义不变)。
    assert all(hit.score > 0 for hit in hits)


def test_semantic_channel_recovers_a_page_the_lexical_channel_misses(published):
    service, _, _, _ = published
    lexical = _reader(service)
    pin = lexical.pin()
    assert lexical.search(pin, LEXICAL_GAP_QUERY) == []

    fused = _reader(service, MappingEmbedder([("supplier", (1.0, 0.0)), (LEXICAL_GAP_QUERY, (1.0, 0.0))]))
    hits = fused.search(pin, LEXICAL_GAP_QUERY, limit=8)
    assert fused.last_search_mode == "fusion"
    assert "Wiki/Concepts/Product-P.md" in _paths(hits)
    # 语义独有命中没有 bm25 分,沿用 LIKE 命中的中性 0.0 约定。
    assert all(hit.score == 0.0 for hit in hits)


def test_fusion_keeps_lexical_candidates_and_their_scores(published):
    service, _, _, _ = published
    lexical = _reader(service)
    pin = lexical.pin()
    baseline = {hit.relative_path: hit.score for hit in lexical.search(pin, "supplier")}

    fused = _reader(service, MappingEmbedder([("supplier", (1.0, 0.0))]))
    fused_hits = fused.search(pin, "supplier", limit=8)
    assert fused.last_search_mode == "fusion"
    scores = {hit.relative_path: hit.score for hit in fused_hits}
    for path, score in baseline.items():
        assert path in scores, f"融合丢了词法候选 {path}"
        assert scores[path] == score


def test_embedding_failure_degrades_to_lexical_only(published):
    service, _, _, _ = published
    lexical = _reader(service)
    pin = lexical.pin()
    expected = _paths(lexical.search(pin, "supplier"))

    for embedder in (BrokenEmbedder(), IncompleteEmbedder()):
        degraded = _reader(service, embedder)
        hits = degraded.search(pin, "supplier")
        assert degraded.last_search_mode == "bm25_semantic_degraded"
        assert _paths(hits) == expected


def test_semantic_channel_cannot_resurrect_a_revoked_page(published):
    service, _, _, _ = published
    embedder = MappingEmbedder([("supplier", (1.0, 0.0)), (LEXICAL_GAP_QUERY, (1.0, 0.0))])
    reader = _reader(service, embedder)
    pin = reader.pin()
    assert reader.search(pin, LEXICAL_GAP_QUERY)

    with service.database.session() as conn:
        conn.execute(
            "UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'"
        )
        conn.commit()
    # 语义腿不得绕过权限闸:被撤销的来源页即使排在语义第一名也不得出现。
    assert reader.search(pin, LEXICAL_GAP_QUERY) == []


def test_semantic_channel_is_pinned_to_the_searched_generation(published):
    service, vault, _, previous = published
    embedder = MappingEmbedder([("supplier", (1.0, 0.0)), (LEXICAL_GAP_QUERY, (1.0, 0.0))])
    reader = _reader(service, embedder)
    pin = reader.pin()
    store = WikiGenerationStore(service.database)
    newer = store.stage(vault, base_generation=previous, changes={})
    store.promote(vault, newer, validate=WikiPublicationService(service.database, service.wiki)._validate)
    assert reader.pin().generation == newer
    assert all(hit.generation == previous for hit in reader.search(pin, LEXICAL_GAP_QUERY))
