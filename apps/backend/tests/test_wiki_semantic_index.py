"""t31:发布期向量投影(仅本地嵌入器)+ 覆盖标记 + 索引版语义腿的行为测试。

设计要点(与 captain 的三项决策对应):
- **决策1**:只解析**本地** ONNX 嵌入器;拿不到 ⇒ 一条向量都不写(绝不复用 retrieval_factory 的远端解析)。
- **决策2**:嵌入不可用时跳过向量、**照常发布**(发布是用户核心操作)。
- **决策3**:只用 (content_hash, embedding_model) 键自然失效。
- **覆盖偏斜 = 补算通道**:索引不完整/不存在 ⇒ 整代走现算 ⇒ 行为与今天一致。
- **授权闸在读向量之前**:撤销页不得因缓存而被复活(显式检查,不靠调用顺序)。
"""

from __future__ import annotations

import asyncio

from app.services import embeddings as embeddings_module
from app.services.embeddings import build_local_onnx_embeddings
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from tests.test_wiki_publication import published

QUERIES = ("supplier", "Product P", "region")


def _reader(service, *, embedder):
    return WikiSnapshotReader(
        service.database, service.wiki, authorize=lambda vault, path: True,
        semantic_embedder=embedder,
    )


def _order(reader, pin, query):
    return [hit.relative_path for hit in reader.search(pin, query, limit=24)]


def _coverage(service):
    with service.database.session(read_only=True) as conn:
        return conn.execute(
            "SELECT status, expected_chunks, stored_chunks FROM wiki_generation_semantic_coverage"
        ).fetchall()


def _vector_count(service):
    with service.database.session(read_only=True) as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM wiki_body_vectors").fetchone()["n"]


def test_publication_writes_vectors_and_marks_coverage_complete(published):
    service, _, _, _ = published
    assert _vector_count(service) > 0
    rows = _coverage(service)
    assert rows
    assert all(row["status"] == "complete" for row in rows)
    assert all(row["stored_chunks"] == row["expected_chunks"] for row in rows)


def test_embedder_unavailable_skips_vectors_and_publication_still_succeeds(tmp_path, monkeypatch):
    """决策2:嵌入不可用 ⇒ 一条向量都不写、**发布照常成功**、覆盖标记为 unavailable。

    注意必须在**首次发布之前**就把嵌入器置为不可用 —— 若向量已存在(同一 content_hash
    在更早的发布里算过),再发布时会**复用**它们,覆盖状态仍为 complete,这是决策3
    (按 content_hash 自然复用)的预期行为,不是缺陷。
    """
    from tests.test_wiki_compilation import CompilerModel, apply_preview, compile_preview, service_for
    from tests.test_wiki_publication import publication_record

    monkeypatch.setattr(embeddings_module, "build_local_onnx_embeddings", lambda _dir: None)
    model = CompilerModel()
    service = service_for(tmp_path, model)
    result = apply_preview(service, compile_preview(service, model.claim, title="Alpha"))
    receipt = publication_record(service, result.run_id)

    assert receipt["status"] == "published"          # 决策2:发布不得因嵌入不可用而失败
    assert _vector_count(service) == 0               # 一条向量都不写
    rows = _coverage(service)
    assert rows and all(row["status"] == "unavailable" for row in rows)


def test_existing_vectors_are_reused_across_publications(published, monkeypatch):
    """决策3:同一 content_hash 的向量跨发布复用 —— 嵌入不可用时旧向量仍算数。"""
    service, _, run_id, generation = published
    from app.services.wiki.publication import WikiPublicationService

    before = _vector_count(service)
    assert before > 0
    monkeypatch.setattr(embeddings_module, "build_local_onnx_embeddings", lambda _dir: None)
    assert WikiPublicationService(service.database, service.wiki).publish_ingest(run_id) == generation
    assert _vector_count(service) == before
    assert all(row["status"] == "complete" for row in _coverage(service))


def test_indexed_and_on_the_fly_rankings_are_identical(published):
    """验收 #2 的核心:索引版 vs 现算版**逐题相同排序**(索引不改变检索语义)。"""
    service, _, _, _ = published
    embedder = build_local_onnx_embeddings(__import__("app.config", fromlist=["get_settings"]).get_settings().local_embedding_dir)
    if embedder is None:
        return  # 环境无本地模型 ⇒ 本用例不适用(降级路径由其它用例覆盖)
    reader = _reader(service, embedder=embedder)
    pin = reader.pin()
    indexed = {q: _order(reader, pin, q) for q in QUERIES}

    # 让索引不可用 ⇒ 回退现算
    with service.database.session() as conn:
        conn.execute("DELETE FROM wiki_generation_semantic_coverage")
        conn.commit()
    on_the_fly = {q: _order(reader, pin, q) for q in QUERIES}

    assert indexed == on_the_fly
    assert any(indexed[q] for q in QUERIES)


def test_incomplete_coverage_falls_back_to_on_the_fly(published):
    """覆盖偏斜 = 补算通道:标记非 complete ⇒ 整代走现算,结果与「无索引」逐题相同。"""
    service, _, _, _ = published
    from app.config import get_settings

    embedder = build_local_onnx_embeddings(get_settings().local_embedding_dir)
    if embedder is None:
        return
    reader = _reader(service, embedder=embedder)
    pin = reader.pin()

    with service.database.session() as conn:
        conn.execute("DELETE FROM wiki_generation_semantic_coverage")
        conn.commit()
    baseline = {q: _order(reader, pin, q) for q in QUERIES}

    with service.database.session() as conn:
        conn.execute(
            "INSERT INTO wiki_generation_semantic_coverage"
            "(vault_id, generation, embedding_model, expected_chunks, stored_chunks, status)"
            " SELECT vault_id, generation, embedding_model, expected_chunks, stored_chunks, 'partial'"
            " FROM wiki_generation_semantic_coverage"
        )
        conn.commit()
    assert _coverage(service) == []  # 先删后插,上面那条 SELECT 无源 ⇒ 空;下面显式构造
    with service.database.session() as conn:
        conn.execute(
            "INSERT INTO wiki_generation_semantic_coverage"
            "(vault_id, generation, embedding_model, expected_chunks, stored_chunks, status)"
            " VALUES ((SELECT id FROM vaults LIMIT 1), ?, ?, 1, 0, 'partial')",
            (pin.generation, "bge-small-zh-v1.5"),
        )
        conn.commit()
    assert {q: _order(reader, pin, q) for q in QUERIES} == baseline


def test_revoked_page_is_not_resurrected_from_the_index(published):
    """验收 #3(扩展版):**向量在场**时,撤销页仍不得出现在语义召回里。"""
    service, _, _, _ = published
    from app.config import get_settings

    embedder = build_local_onnx_embeddings(get_settings().local_embedding_dir)
    if embedder is None:
        return
    reader = _reader(service, embedder=embedder)
    pin = reader.pin()
    assert _order(reader, pin, "supplier")  # 有结果

    with service.database.session() as conn:
        conn.execute(
            "UPDATE memory_candidates SET status = 'forgotten' WHERE summary = 'Wiki source provenance'"
        )
        conn.commit()
    # 向量仍在库里,但授权闸在读向量之前 ⇒ 不得复活
    assert _vector_count(service) > 0
    assert _order(reader, pin, "supplier") == []
