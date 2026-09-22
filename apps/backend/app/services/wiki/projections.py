"""SQLite search/link projections of immutable Wiki bodies."""

from __future__ import annotations

import json
import threading
from array import array
from collections import defaultdict
from pathlib import PurePosixPath

from app.repositories.storage import _bigram_cjk
from app.storage.markdown import parse_markdown
from app.utils.hash import sha256_bytes_hex

from . import _legacy_wiki


# ---------------------------------------------------------------------------
# 阶段1(t31):发布期向量投影(仅本地嵌入器) + 逐代覆盖标记
# ---------------------------------------------------------------------------
_EMBEDDER_LOCK = threading.Lock()
_EMBEDDER_CACHE: dict = {}


def _local_embedder():
    """**仅本地** ONNX 嵌入器(决策 1)。

    **绝不复用 retrieval_factory 解析出的嵌入器** —— 检索用的向量索引可以是远端的
    (用户 opt-in),复用会把 wiki 正文发往远端,削弱隐私保证。
    拿不到 ⇒ 返回 None ⇒ 调用方**一条向量都不写**(决策 2:跳过向量、照常发布)。
    """
    from app.config import get_settings
    from app.services import embeddings

    model_dir = get_settings().local_embedding_dir
    # 构造函数进缓存键:测试 monkeypatch 了它也能得到新解析,不吃旧缓存。
    key = (str(model_dir), embeddings.build_local_onnx_embeddings)
    with _EMBEDDER_LOCK:
        if key not in _EMBEDDER_CACHE:
            _EMBEDDER_CACHE[key] = embeddings.build_local_onnx_embeddings(model_dir)
        return _EMBEDDER_CACHE[key]


def _embedding_model_name() -> str:
    from app.services.embeddings import LOCAL_EMBEDDING_MODEL_NAME

    return LOCAL_EMBEDDING_MODEL_NAME


def _chunk_texts(title: str, parsed) -> list:
    return [
        " ".join(part for part in (title, chunk.heading or "", chunk.content) if part)
        for chunk in parsed.chunks
    ]


def _project_page_vectors(conn, vault_id: str, digest: str, title: str, parsed) -> bool:
    """把该正文的块向量写入投影(按 content_hash 复用;已存在则跳过)。

    返回是否写入。**任何异常都不得逃逸** —— 嵌入失败只意味着「跳过向量」。
    """
    embedder = _local_embedder()
    if embedder is None:
        return False
    texts = _chunk_texts(title, parsed)
    if not texts:
        return False
    existing = conn.execute(
        "SELECT COUNT(*) AS n FROM wiki_body_vectors WHERE vault_id = ? AND content_hash = ?",
        (vault_id, digest),
    ).fetchone()["n"]
    if existing >= len(texts):
        return False
    try:
        vectors = embedder.embed_documents(texts)
    except Exception:
        return False
    if not isinstance(vectors, list) or len(vectors) != len(texts):
        return False
    model = _embedding_model_name()
    for index, vector in enumerate(vectors):
        payload = array("f", [float(value) for value in vector])
        conn.execute(
            "INSERT OR REPLACE INTO wiki_body_vectors"
            "(vault_id, content_hash, chunk_index, embedding_model, dimensions, vector)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (vault_id, digest, index, model, len(vector), payload.tobytes()),
        )
    return True


def _record_semantic_coverage(conn, vault_id: str, generation: str) -> None:
    """记录该代的语义覆盖状态(complete / partial / unavailable)。

    **刻意不参与 require_generation_projection 的完整性断言** ——
    嵌入不可用是允许的,不得因此被误判为「投影不完整」而阻止发布。
    """
    model = _embedding_model_name()
    expected = conn.execute(
        """SELECT COALESCE(SUM(b.chunk_count), 0) AS n
           FROM wiki_generation_pages p
           JOIN wiki_body_projection b
             ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
           WHERE p.vault_id = ? AND p.generation = ?""",
        (vault_id, generation),
    ).fetchone()["n"]
    stored = conn.execute(
        """SELECT COUNT(*) AS n FROM wiki_body_vectors
           WHERE vault_id = ? AND embedding_model = ?
             AND content_hash IN (
               SELECT content_hash FROM wiki_generation_pages
               WHERE vault_id = ? AND generation = ?)""",
        (vault_id, model, vault_id, generation),
    ).fetchone()["n"]
    if expected <= 0 or stored <= 0:
        status = "unavailable"
    elif stored >= expected:
        status = "complete"
    else:
        status = "partial"
    conn.execute(
        """INSERT OR REPLACE INTO wiki_generation_semantic_coverage
           (vault_id, generation, embedding_model, expected_chunks, stored_chunks, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
        (vault_id, generation, model, expected, stored, status),
    )



def snapshot_text(body: bytes) -> str:
    return body.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def build_generation_projection(conn, vault_id: str, generation: str) -> None:
    from .generations import WikiGenerationError

    rows = conn.execute(
        """SELECT p.relative_path, p.content_hash, b.body FROM wiki_generation_pages p
           JOIN wiki_page_bodies b ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
           WHERE p.vault_id = ? AND p.generation = ? ORDER BY p.relative_path""",
        (vault_id, generation),
    ).fetchall()
    pages = []
    for row in rows:
        digest = row["content_hash"]
        projected = conn.execute(
            "SELECT * FROM wiki_body_projection WHERE vault_id = ? AND content_hash = ?", (vault_id, digest),
        ).fetchone()
        if projected is None:
            body = bytes(row["body"])
            if sha256_bytes_hex(body) != digest:
                raise WikiGenerationError("wiki_generation_body_integrity")
            parsed = parse_markdown(snapshot_text(body), fallback_title="")
            for chunk in parsed.chunks:
                conn.execute(
                    "INSERT INTO wiki_body_fts VALUES (?, ?, ?, ?, ?, ?)",
                    (vault_id, digest, chunk.index, _bigram_cjk(parsed.title),
                     _bigram_cjk(chunk.heading or ""), _bigram_cjk(chunk.content)),
                )
            conn.execute(
                "INSERT INTO wiki_body_projection VALUES (?, ?, ?, ?, ?)",
                (vault_id, digest, parsed.title, json.dumps(parsed.links), len(parsed.chunks)),
            )
            _project_page_vectors(conn, vault_id, digest, parsed.title, parsed)
            title, links = parsed.title, parsed.links
        else:
            title, links = projected["title"], json.loads(projected["links_json"])
        pages.append(_legacy_wiki._GraphPage(
            title=title or PurePosixPath(row["relative_path"]).stem,
            relative_path=row["relative_path"], links=links, frontmatter={},
        ))
    _record_semantic_coverage(conn, vault_id, generation)
    by_title, by_slug, by_path = defaultdict(list), defaultdict(list), defaultdict(list)
    for page in pages:
        by_title[page.title.casefold()].append(page)
        by_slug[PurePosixPath(page.relative_path).stem.casefold()].append(page)
        by_path[page.relative_path.casefold()].append(page)
    # Ambiguous aliases must not become an arbitrary cross-page edge.
    indexes = [{key: values[0] for key, values in index.items() if len(values) == 1}
               for index in (by_title, by_slug, by_path)]
    links = set()
    for page in pages:
        for link in page.links:
            target = _legacy_wiki._resolve_graph_link(
                link, by_title=indexes[0], by_slug=indexes[1], by_relative_path=indexes[2],
            )
            if target is not None:
                links.add((vault_id, generation, page.relative_path, target.relative_path))
    conn.executemany("INSERT INTO wiki_generation_links VALUES (?, ?, ?, ?)", sorted(links))
    conn.execute(
        "INSERT INTO wiki_generation_projection VALUES (?, ?, ?, ?)",
        (vault_id, generation, len(pages), len(links)),
    )


def require_generation_projection(conn, vault_id: str, generation: str) -> None:
    from .generations import WikiGenerationError

    marker = conn.execute(
        "SELECT * FROM wiki_generation_projection WHERE vault_id = ? AND generation = ?",
        (vault_id, generation),
    ).fetchone()
    if marker is None:
        raise WikiGenerationError("wiki_generation_projection_unavailable")
    counts = conn.execute(
        """SELECT COUNT(*) AS pages, COUNT(b.content_hash) AS projected
           FROM wiki_generation_pages p LEFT JOIN wiki_body_projection b
             ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
           WHERE p.vault_id = ? AND p.generation = ?""", (vault_id, generation),
    ).fetchone()
    links = conn.execute(
        "SELECT COUNT(*) FROM wiki_generation_links WHERE vault_id = ? AND generation = ?",
        (vault_id, generation),
    ).fetchone()[0]
    if counts["pages"] != marker["page_count"] or counts["projected"] != counts["pages"] or links != marker["link_count"]:
        raise WikiGenerationError("wiki_generation_projection_incomplete")
    incomplete = conn.execute(
        """SELECT 1 FROM wiki_body_projection b
           WHERE b.vault_id = ? AND b.content_hash IN (
             SELECT content_hash FROM wiki_generation_pages WHERE vault_id = ? AND generation = ?)
           AND b.chunk_count != (
             SELECT COUNT(*) FROM wiki_body_fts f WHERE f.vault_id = b.vault_id AND f.content_hash = b.content_hash)
           LIMIT 1""", (vault_id, vault_id, generation),
    ).fetchone()
    if incomplete is not None:
        raise WikiGenerationError("wiki_generation_projection_incomplete")