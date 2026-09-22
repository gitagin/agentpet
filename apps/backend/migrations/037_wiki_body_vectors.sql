-- 阶段1(t31): wiki 快照页的**发布期**向量投影 + 逐代覆盖标记。
-- 设计依据: docs/wiki-staged-vector-index-design.md 与 captain 的三项决策:
--   决策1 仅本地 ONNX 嵌入器(绝不复用 retrieval_factory 的解析结果,那可能是远端);
--   决策2 嵌入不可用时跳过向量、照常发布(发布是用户核心操作);
--   决策3 只靠 (content_hash, embedding_model) 键自然失效,不加显式重建入口。
-- 覆盖偏斜处置:**补算通道** —— 索引不完整/不存在时整代走查询期现算(行为与今天一致)。

CREATE TABLE wiki_body_vectors (
    vault_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding_model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector BLOB NOT NULL,               -- float32 小端(array('f').tobytes())
    PRIMARY KEY(vault_id, content_hash, chunk_index, embedding_model),
    FOREIGN KEY(vault_id, content_hash) REFERENCES wiki_page_bodies(vault_id, content_hash)
);

-- 键不含 generation: wiki_page_bodies 主键是 (vault_id, content_hash) ⇒ 正文跨代共享
-- ⇒ 嵌入跨代复用(与既有 FTS 投影的 if projected is None 语义一致)。

CREATE TABLE wiki_generation_semantic_coverage (
    vault_id TEXT NOT NULL,
    generation TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    expected_chunks INTEGER NOT NULL,
    stored_chunks INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('complete', 'partial', 'unavailable')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY(vault_id, generation, embedding_model),
    FOREIGN KEY(vault_id, generation) REFERENCES wiki_generations(vault_id, id)
);

-- 这张表**刻意不参与** require_generation_projection 的完整性断言:
-- 嵌入不可用是允许的,不得因此被误判为「投影不完整」而阻止发布。
