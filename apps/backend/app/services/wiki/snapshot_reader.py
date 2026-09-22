"""Version-pinned internal reading primitives for the Wiki query pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable
from array import array
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import get_settings
from app.repositories.storage import _make_like_snippet, _to_fts_queries, _to_like_pattern
from app.services.retrieval_fusion import FusionCandidate, reciprocal_rank_fusion
from app.services.wiki import WikiService
from app.storage.database import Database
from app.storage.markdown import HEADING_RE, parse_markdown
from app.utils.hash import sha256_bytes_hex

from .compiler import check_material
from .generations import WikiGenerationError
from .projections import _embedding_model_name, require_generation_projection, snapshot_text
from .publication import _normalized_hash, validate_snapshot_dependency


# 双路融合的候选池下限:与工具层 top_k 上限一致,保证融合有足够材料重排。
_SEMANTIC_POOL_MIN = 24
_LEXICAL_CHANNEL = "wiki_bm25"
_SEMANTIC_CHANNEL = "wiki_vector"


def _cosine(left, right) -> float:
    """嵌入向量已 L2 归一化,点积即余弦相似度。"""
    return float(sum(a * b for a, b in zip(left, right)))


def _wiki_fusion_candidate(path: str, content_hash: str, vault_id: str) -> FusionCandidate:
    """快照页在融合里的身份 = 页路径;内容哈希来自 wiki_generation_pages,两路必然一致。"""
    return FusionCandidate(
        stable_id=path, content_hash=content_hash, source_scope="wiki", payload=path,
        stable_order_key=path, permission_allowed=True, lifecycle_status="active",
        metadata_filter_passed=True, vault_id=vault_id, generation_valid=True,
    )


@dataclass(frozen=True)
class WikiReadPin:
    vault_id: str
    generation: str


@dataclass(frozen=True)
class WikiSnapshotPage:
    generation: str
    relative_path: str
    content_hash: str
    title: str
    content: str
    start_line: int
    end_line: int
    links: tuple[str, ...]
    backlinks: tuple[str, ...]


@dataclass(frozen=True)
class WikiPageCandidate:
    generation: str
    relative_path: str
    content_hash: str
    title: str
    heading: str | None
    snippet: str
    start_line: int
    end_line: int
    # 相关性分数:供查询节点的价值函数(V = relevance × freshness × coverage)使用。
    # bm25 在 SQLite 中越小越相关,这里取负值使「越大越相关」与既有 score 语义一致;
    # LIKE 命中没有 bm25,给一个低于任何真实 bm25 命中的中性分。
    score: float = 0.0


class WikiSnapshotReader:
    """Caller supplies live access policy; generation membership is not permission.

    No API or chat route is enabled by this class. Lines refer to the normalized
    Markdown body, excluding frontmatter. Each operation rechecks live authority;
    a later prompt/send boundary must revalidate again.
    """

    def __init__(
        self, database: Database, wiki: WikiService, *,
        authorize: Callable[[str, str], bool],
        semantic_embedder: object | None = None,
    ):
        self.database = database
        self.wiki = wiki
        self.authorize = authorize
        # 语义腿是**可注入**能力:None = 纯词法单路(与历史行为逐行一致)。
        # 无嵌入器(未配置/无本地 ONNX 模型)即天然降级,不改变既有保证。
        self.semantic_embedder = semantic_embedder
        # 最近一次 search 实际使用的通道,供调用方与评测观测降级原因。
        self.last_search_mode = "bm25"

    def pin(self, generation: str | None = None) -> WikiReadPin:
        with self.database.session(read_only=True) as conn:
            vault = conn.execute(
                "SELECT id FROM vaults WHERE root_path = ?", (str(self.wiki.writer.vault_root.resolve()),),
            ).fetchone()
            if vault is None:
                raise WikiGenerationError("wiki_snapshot_unavailable")
            if generation is None:
                head = conn.execute(
                    "SELECT active_generation FROM wiki_generation_heads WHERE vault_id = ?", (vault["id"],),
                ).fetchone()
                generation = head["active_generation"] if head else None
            pin = WikiReadPin(vault["id"], generation or "")
            self._scope(conn, pin)
            return pin

    def read(
        self, pin: WikiReadPin, path: str, *, expected_version: str | None = None,
        section: str | None = None, max_chars: int = 12000,
    ) -> WikiSnapshotPage:
        if not 1 <= max_chars <= 180000:
            raise WikiGenerationError("wiki_snapshot_invalid_budget")
        digest, parsed = self._load(pin, path, expected_version)
        lines = parsed.body.splitlines(keepends=True)
        start, end = 0, len(lines)
        if section is not None:
            matches = [(i, match) for i, line in enumerate(lines)
                       if (match := HEADING_RE.match(line.strip())) and match.group(2) == section]
            if len(matches) != 1:
                raise WikiGenerationError("wiki_snapshot_section_missing_or_ambiguous")
            start, heading = matches[0]
            level = len(heading.group(1))
            end = next(
                (i for i in range(start + 1, len(lines))
                 if (match := HEADING_RE.match(lines[i].strip())) and len(match.group(1)) <= level),
                len(lines),
            )
        content = "".join(lines[start:end])
        if len(content) > max_chars:
            raise WikiGenerationError("wiki_snapshot_read_budget_exhausted")
        links, backlinks = self._neighbors(pin, path)
        self._load(pin, path, digest)
        return WikiSnapshotPage(
            pin.generation, path, digest, parsed.title, content, start + 1, end, links, backlinks,
        )

    def search(self, pin: WikiReadPin, query: str, *, limit: int = 8) -> list[WikiPageCandidate]:
        if not 1 <= limit <= 24 or len(query) > 2000:
            raise WikiGenerationError("wiki_snapshot_invalid_search_budget")
        if not query.strip():
            return []
        queries = _to_fts_queries(query)
        collected: dict[str, WikiPageCandidate] = {}
        scanned: set[tuple[str, int]] = set()
        # 融合需要比最终条数更宽的词法候选池;无嵌入器时 pool == limit,
        # 逐行行为与历史单路实现完全一致(既有排序/score 语义不得改变)。
        pool = limit if self.semantic_embedder is None else max(limit, _SEMANTIC_POOL_MIN)
        with self.database.session(read_only=True) as conn:
            self._scope(conn, pin)
            require_generation_projection(conn, pin.vault_id, pin.generation)
            clauses = [("wiki_body_fts MATCH ?", (fts_query,)) for fts_query in queries]
            clauses.append(
                ("(wiki_body_fts.content LIKE ? ESCAPE '~' OR wiki_body_fts.title LIKE ? ESCAPE '~')",
                 (_to_like_pattern(query), _to_like_pattern(query))),
            )
            for clause, params in clauses:
                # Only constant SQL fragments are interpolated; query text is bound.
                matched = "MATCH" in clause
                rank = "bm25(wiki_body_fts)" if matched else "p.relative_path"
                rank_expr = "bm25(wiki_body_fts)" if matched else "0.0"
                rows = conn.execute(
                    f"""SELECT p.relative_path, p.content_hash, wiki_body_fts.chunk_index,
                               {rank_expr} AS rank
                        FROM wiki_body_fts JOIN wiki_generation_pages p
                          ON p.vault_id = wiki_body_fts.vault_id AND p.content_hash = wiki_body_fts.content_hash
                        WHERE p.vault_id = ? AND p.generation = ? AND {clause}
                        ORDER BY {rank} LIMIT ?""",
                    (pin.vault_id, pin.generation, *params, max(32, pool * 8)),
                ).fetchall()
                for row in rows:
                    path, chunk_index = row["relative_path"], int(row["chunk_index"])
                    if path in collected or (path, chunk_index) in scanned:
                        continue
                    scanned.add((path, chunk_index))
                    try:
                        digest, parsed = self._load(pin, path, row["content_hash"])
                    except WikiGenerationError:
                        continue
                    if not 0 <= chunk_index < len(parsed.chunks):
                        raise WikiGenerationError("wiki_generation_projection_incomplete")
                    chunk = parsed.chunks[chunk_index]
                    collected[path] = WikiPageCandidate(
                        pin.generation, path, digest, parsed.title, chunk.heading,
                        _make_like_snippet(content=chunk.content, query=query, title=parsed.title, heading=chunk.heading),
                        chunk.start_line, chunk.end_line,
                        score=-float(row["rank"]),
                    )
                    if len(collected) >= pool:
                        break
                if len(collected) >= pool:
                    break
            self.last_search_mode = "bm25"
            if self.semantic_embedder is not None:
                collected = self._fuse_semantic_channel(conn, pin, query, collected, limit)
        results = []
        for candidate in collected.values():
            try:
                self._load(pin, candidate.relative_path, candidate.content_hash)
            except WikiGenerationError:
                continue
            results.append(candidate)
        return results

    def _fuse_semantic_channel(self, conn, pin, query, collected, limit):
        """快照检索内部的「词法(bm25) + 语义」双路召回,以 RRF 融合为页级排名。

        语义腿 = 用注入的嵌入器对本代全部页块做稠密召回;嵌入器不可用或调用失败
        一律**降级为纯词法**(与历史行为一致),绝不因语义腿异常而改变词法结果。
        score 字段语义不变:bm25 命中仍是 `-bm25`(越大越相关),语义独有命中沿用
        LIKE 命中的中性 0.0 约定。
        """
        semantic = self._semantic_page_ranking(conn, pin, query)
        if not semantic:
            self.last_search_mode = "bm25_semantic_degraded"
            return collected
        lexical_paths = list(collected)
        channels: dict[str, list[FusionCandidate]] = {}
        if lexical_paths:
            channels[_LEXICAL_CHANNEL] = [
                _wiki_fusion_candidate(path, collected[path].content_hash, pin.vault_id)
                for path in lexical_paths
            ]
        channels[_SEMANTIC_CHANNEL] = [
            _wiki_fusion_candidate(path, digest, pin.vault_id) for path, digest, _chunk in semantic
        ]
        fused = reciprocal_rank_fusion(
            channels,
            approved_scopes=("wiki",),
            top_k=min(40, max(limit, len(lexical_paths))),
            required_vault_id=pin.vault_id,
            rrf_k=max(1, min(get_settings().tuning_rrf_k, 1000)),
        )
        best_chunk = {path: chunk for path, _digest, chunk in semantic}
        ordered: dict[str, WikiPageCandidate] = {}
        for candidate in fused.candidates:
            path = candidate.stable_id
            page = collected.get(path) or self._candidate_for_path(
                pin, path, best_chunk.get(path, 0), query,
            )
            if page is None:
                continue
            ordered[path] = page
            if len(ordered) >= limit:
                break
        self.last_search_mode = "fusion"
        return ordered

    def _semantic_page_ranking(self, conn, pin, query) -> list[tuple[str, str, int]]:
        """稠密召回:对本代全部页块算余弦相似度,按「页内最佳块」聚合成页级排名。

        整体尽力而为:读库/解析/嵌入任一环节异常都返回空,调用方随即降级为纯词法。
        """
        try:
            return self._semantic_page_ranking_inner(conn, pin, query)
        except Exception:
            return []

    def _semantic_page_ranking_inner(self, conn, pin, query) -> list[tuple[str, str, int]]:
        # 阶段1(t31):优先用**发布期向量投影**;索引不可用则回退现算(补算通道)。
        indexed = self._indexed_page_ranking(conn, pin, query)
        if indexed is not None:
            return indexed
        embed_query = getattr(self.semantic_embedder, "embed_query", None)
        embed_documents = getattr(self.semantic_embedder, "embed_documents", None)
        if not callable(embed_query) or not callable(embed_documents):
            return []
        rows = conn.execute(
            """SELECT p.relative_path, p.content_hash, b.body
               FROM wiki_generation_pages p
               JOIN wiki_page_bodies b ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
               WHERE p.vault_id = ? AND p.generation = ? ORDER BY p.relative_path""",
            (pin.vault_id, pin.generation),
        ).fetchall()
        prepared = []
        for row in rows:
            path = str(row["relative_path"])
            # 与词法腿同一道权限闸:未授权的页不得进入语义候选。
            if self.authorize(pin.vault_id, path) is not True:
                continue
            parsed = parse_markdown(
                snapshot_text(bytes(row["body"])), fallback_title=PurePosixPath(path).stem,
            )
            texts = [
                " ".join(part for part in (parsed.title, chunk.heading or "", chunk.content) if part)
                for chunk in parsed.chunks
            ]
            if texts:
                prepared.append((path, str(row["content_hash"]), texts))
        if not prepared:
            return []
        flat = [text for _path, _digest, texts in prepared for text in texts]
        try:
            query_vector = embed_query(query)
            vectors = embed_documents(flat)
        except Exception:
            # 语义腿是**尽力而为**:任何异常都不得影响词法结果。
            return []
        if not isinstance(vectors, list) or len(vectors) != len(flat):
            return []
        ranked = []
        cursor = 0
        for path, digest, texts in prepared:
            best_similarity, best_chunk = None, 0
            for offset in range(len(texts)):
                similarity = _cosine(query_vector, vectors[cursor + offset])
                if best_similarity is None or similarity > best_similarity:
                    best_similarity, best_chunk = similarity, offset
            cursor += len(texts)
            ranked.append((path, digest, best_chunk, best_similarity))
        ranked.sort(key=lambda item: (-item[3], item[0]))
        return [(path, digest, chunk) for path, digest, chunk, _similarity in ranked]

    def _indexed_page_ranking(self, conn, pin, query):
        """从**发布期向量投影**取页级排名;索引不可用时返回 None(调用方回退现算)。

        覆盖偏斜处置 = **补算通道**:索引不完整/不存在/模型不符 ⇒ 返回 None
        ⇒ 整代走查询期现算 ⇒ 行为与今天一致,且**不会出现「部分页有向量、部分没有」**。

        **授权闸在读向量之前**(显式检查,不靠调用顺序隐含):
        先按 authorize 过滤页路径,再只取这些路径的向量;取回后再校验一次。
        语义召回不得绕过权限 —— 撤销页不得因缓存而被复活。
        """
        embed_query = getattr(self.semantic_embedder, "embed_query", None)
        if not callable(embed_query):
            return None
        model = _embedding_model_name()
        coverage = conn.execute(
            "SELECT status FROM wiki_generation_semantic_coverage"
            " WHERE vault_id = ? AND generation = ? AND embedding_model = ?",
            (pin.vault_id, pin.generation, model),
        ).fetchone()
        if coverage is None or str(coverage["status"]) != "complete":
            return None

        pages = conn.execute(
            "SELECT relative_path, content_hash FROM wiki_generation_pages"
            " WHERE vault_id = ? AND generation = ? ORDER BY relative_path",
            (pin.vault_id, pin.generation),
        ).fetchall()
        # ---- 授权闸:读向量之前 ----
        authorized: dict[str, str] = {}
        for row in pages:
            path = str(row["relative_path"])
            if self.authorize(pin.vault_id, path) is True:
                authorized[path] = str(row["content_hash"])
        if not authorized:
            return None
        for path in authorized:
            if self.authorize(pin.vault_id, path) is not True:
                raise WikiGenerationError("wiki_snapshot_access_denied")

        digests = tuple(authorized.values())
        placeholders = ",".join("?" for _ in digests)
        rows = conn.execute(
            f"""SELECT content_hash, chunk_index, dimensions, vector FROM wiki_body_vectors
                WHERE vault_id = ? AND embedding_model = ?
                  AND content_hash IN ({placeholders})
                ORDER BY content_hash, chunk_index""",
            (pin.vault_id, model, *digests),
        ).fetchall()
        # ---- 取回后复核:不得出现授权集之外的向量 ----
        allowed = set(digests)
        for row in rows:
            if str(row["content_hash"]) not in allowed:
                raise WikiGenerationError("wiki_snapshot_access_denied")
        if not rows:
            return None
        try:
            query_vector = embed_query(query)
        except Exception:
            return None
        # 维度必须一致:否则 _cosine 会被 zip 静默截断,产出**无意义**的相似度。
        stored_dimensions = {int(row["dimensions"]) for row in rows}
        if len(stored_dimensions) != 1 or len(query_vector) != next(iter(stored_dimensions)):
            return None

        best: dict[str, tuple[float, int]] = {}
        digest_to_path = {digest: path for path, digest in authorized.items()}
        for row in rows:
            path = digest_to_path[str(row["content_hash"])]
            similarity = _cosine(query_vector, array("f", bytes(row["vector"])).tolist())
            current = best.get(path)
            if current is None or similarity > current[0]:
                best[path] = (similarity, int(row["chunk_index"]))
        ranked = sorted(
            ((path, authorized[path], chunk, similarity)
             for path, (similarity, chunk) in best.items()),
            key=lambda item: (-item[3], item[0]),
        )
        return [(path, digest, chunk) for path, digest, chunk, _similarity in ranked]

    def _candidate_for_path(self, pin, path, chunk_index, query):
        """为语义独有命中构造页级候选;页不可读(权限/版本/完整性/内容策略)一律丢弃。

        这里是**尽力而为**的富集路径:语义腿不得为调用方引入词法路没有的失败模式,
        故任何异常都收敛为「该页不出现」——权威闸仍由下方 search() 末尾的逐条 `_load` 复核。
        """
        try:
            digest, parsed = self._load(pin, path)
        except Exception:
            return None
        if not 0 <= chunk_index < len(parsed.chunks):
            return None
        chunk = parsed.chunks[chunk_index]
        return WikiPageCandidate(
            pin.generation, path, digest, parsed.title, chunk.heading,
            _make_like_snippet(content=chunk.content, query=query, title=parsed.title, heading=chunk.heading),
            chunk.start_line, chunk.end_line, score=0.0,
        )

    def source_observation(self, pin, paths):
        from .source_watermark import source_watermark

        paths = tuple(dict.fromkeys(paths))
        for path in paths:
            self._load(pin, path)
        with self.database.session(read_only=True) as conn:
            conn.execute("BEGIN")
            self._scope(conn, pin)
            current = source_watermark(conn, pin.vault_id)
            baselines = []
            for path in paths:
                row = conn.execute(
                    """SELECT dependency_json FROM wiki_generation_dependencies
                       WHERE vault_id = ? AND generation = ? AND relative_path = ?""",
                    (pin.vault_id, pin.generation, path),
                ).fetchone()
                baselines.append(json.loads(row["dependency_json"]).get("source_watermark") if row else None)
        if not baselines or any(not item or item.get("version") != 1 for item in baselines):
            status = "baseline_unknown"
        elif any(item != current for item in baselines):
            status = "changed_since_capture"
        else:
            status = "unchanged_since_capture"
        return {"generation": pin.generation, "watermark": current, "status": status}

    def _scope(self, conn, pin):
        row = conn.execute(
            """SELECT g.id FROM wiki_generations g JOIN vaults v ON v.id = g.vault_id
               WHERE g.id = ? AND g.vault_id = ? AND g.status = 'published' AND g.revoked_at IS NULL AND v.root_path = ?""",
            (pin.generation, pin.vault_id, str(self.wiki.writer.vault_root.resolve())),
        ).fetchone()
        if row is None:
            raise WikiGenerationError("wiki_snapshot_unavailable")

    def _load(self, pin, path, expected_version=None):
        with self.database.session(read_only=True) as conn:
            self._scope(conn, pin)
            row = conn.execute(
                """SELECT p.content_hash, b.body, d.dependency_json FROM wiki_generation_pages p
                   JOIN wiki_page_bodies b ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
                   JOIN wiki_generation_dependencies d ON d.vault_id = p.vault_id
                     AND d.generation = p.generation AND d.relative_path = p.relative_path
                   WHERE p.vault_id = ? AND p.generation = ? AND p.relative_path = ?""",
                (pin.vault_id, pin.generation, path),
            ).fetchone()
            if row is None:
                raise WikiGenerationError("wiki_snapshot_page_unavailable")
            if expected_version is not None and row["content_hash"] != expected_version:
                raise WikiGenerationError("wiki_snapshot_version_mismatch")
            dependency = json.loads(row["dependency_json"])
            normalized = {}
            for parent in dict.fromkeys([path, *dependency["pages"]]):
                if self.authorize(pin.vault_id, parent) is not True:
                    raise WikiGenerationError("wiki_snapshot_access_denied")
                source = conn.execute(
                    """SELECT p.content_hash, b.body FROM wiki_generation_pages p
                       JOIN wiki_page_bodies b ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
                       WHERE p.vault_id = ? AND p.generation = ? AND p.relative_path = ?""",
                    (pin.vault_id, pin.generation, parent),
                ).fetchone()
                if source is None or sha256_bytes_hex(bytes(source["body"])) != source["content_hash"]:
                    raise WikiGenerationError("wiki_generation_body_integrity")
                normalized[parent] = _normalized_hash(bytes(source["body"]))
            validate_snapshot_dependency(conn, pin.vault_id, path, dependency, normalized)
            text = snapshot_text(bytes(row["body"]))
            check_material(text)
            return row["content_hash"], parse_markdown(text, fallback_title=PurePosixPath(path).stem)

    def _neighbors(self, pin, path):
        with self.database.session(read_only=True) as conn:
            require_generation_projection(conn, pin.vault_id, pin.generation)
            edges = conn.execute(
                """SELECT source_path, target_path FROM wiki_generation_links
                   WHERE vault_id = ? AND generation = ? AND (source_path = ? OR target_path = ?)
                   ORDER BY source_path, target_path""", (pin.vault_id, pin.generation, path, path),
            ).fetchall()
        outgoing, incoming = set(), set()
        for edge in edges:
            neighbor = edge["target_path"] if edge["source_path"] == path else edge["source_path"]
            if neighbor == path:
                continue
            try:
                self._load(pin, neighbor)
            except WikiGenerationError:
                continue
            (outgoing if edge["source_path"] == path else incoming).add(neighbor)
        return tuple(sorted(outgoing)), tuple(sorted(incoming))
