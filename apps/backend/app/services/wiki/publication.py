"""Publish verified ingest artifacts without granting snapshot read permission."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence

from app.services.wiki import WikiService
from app.storage.database import Database
from app.utils.hash import sha256_bytes_hex, sha256_hex

from .compiler import read_evidence_snapshot
from .generations import WikiGenerationError, WikiGenerationStore
from .memory_closure import validate_wiki_page_roots


def _normalized_hash(body: bytes) -> str:
    return sha256_hex(body.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"))


def _dependency_stamp(conn, vault_id: str, pages: Mapping[str, str], entities: list[str]) -> str:
    state: dict[str, list] = {"pages": [], "roots": [], "candidates": [], "relations": []}
    for path, expected in sorted(pages.items()):
        binding = conn.execute(
            "SELECT * FROM wiki_page_bindings WHERE vault_id = ? AND wiki_relative_path = ?",
            (vault_id, path),
        ).fetchone()
        if binding is None or binding["status"] != "active" or binding["content_hash"] != expected:
            raise WikiGenerationError("wiki_publication_dependency_changed")
        state["pages"].append(dict(binding))
        state["relations"].extend(dict(row) for row in conn.execute(
            """SELECT relation.* FROM memory_graph_facts relation
               JOIN memory_entities entity ON entity.id = relation.subject_entity_id
               WHERE relation.object_entity_id = ? AND relation.relation_type = 'documented_in'
                 AND entity.entity_type = 'source' ORDER BY relation.id""",
            (binding["page_entity_id"],),
        ))
    for entity_id in sorted(entities):
        entity = conn.execute("SELECT * FROM memory_entities WHERE id = ?", (entity_id,)).fetchone()
        if entity is None or entity["status"] != "active":
            raise WikiGenerationError("wiki_publication_root_inactive")
        source_id = json.loads(entity["metadata_json"]).get("source_id")
        source = conn.execute(
            "SELECT * FROM wiki_sources WHERE id = ? AND vault_id = ?", (source_id, vault_id),
        ).fetchone()
        if source is None:
            raise WikiGenerationError("wiki_publication_root_missing")
        source_state = dict(source)
        source_state["raw_content"] = sha256_hex(source_state["raw_content"] or "")
        # 依赖戳承载**内容完整性**语义,故剔除下面三类非内容字段。剔除理由**各不相同**:
        #   verification_status / verified_at —— 查询期惰性核验会写它们;若纳入戳,
        #     核验动作本身就会让本轮引用校验失败(自相矛盾),**必须**剔除。
        #   expires_at —— 是**有效性**字段而非「何时检查过」。查询期 derive_source_freshness
        #     会读它并判 stale,故完整性不因剔除而削弱;反之若纳入戳,「设置一个未来的
        #     过期时间」会立刻让已发布页失效,属误伤。
        # 注:revoked_at **保留**在戳内——撤销是**权威**变更,本就应当使已发布页失效。
        for _meta_key in ("verification_status", "verified_at", "expires_at"):
            source_state.pop(_meta_key, None)
        if source_state["raw_content"] != source_state["source_hash"]:
            raise WikiGenerationError("wiki_publication_root_changed")
        state["roots"].append({"entity": dict(entity), "source": source_state})
        candidates = conn.execute(
            """SELECT * FROM memory_candidates
               WHERE json_extract(metadata_json, '$.source_id') = ?
                 AND json_extract(metadata_json, '$.candidate_role') = 'wiki_source_provenance'
               ORDER BY id""",
            (source_id,),
        ).fetchall()
        if len(candidates) != 1 or candidates[0]["status"] not in {"candidate", "active"}:
            raise WikiGenerationError("wiki_publication_root_inactive")
        candidate = dict(candidates[0])
        candidate["source_text"] = sha256_hex(candidate["source_text"] or "")
        state["candidates"].append(candidate)
    return sha256_hex(json.dumps(state, sort_keys=True, ensure_ascii=True))


def validate_snapshot_dependency(conn, vault_id, path, dependency, normalized):
    pages = dependency["pages"]
    if path not in pages or any(normalized.get(parent) != digest for parent, digest in pages.items()):
        raise WikiGenerationError("wiki_publication_dependency_version_mismatch")
    current = _dependency_stamp(conn, vault_id, pages, dependency["root_entities"])
    if current != dependency["stamp"]:
        raise WikiGenerationError("wiki_publication_dependency_changed")


DRAFT_FIRST_PUBLICATION_KEY = "wiki_draft_first_publication"


def draft_first_publication_enabled(conn: sqlite3.Connection) -> bool:
    """读取「草稿先行发布」开关。

    与 settings 层写入的是同一个 app_state 键(services/settings_types.py 的
    WIKI_DRAFT_FIRST_PUBLICATION_STATE_KEY);这里直接读库,避免 wiki 服务层
    反向依赖 settings 层——与 ingest_identity.source_identity_v2_enabled 同构。
    默认 False = 完全保持现有「先写盘再 capture」路径。
    """
    row = conn.execute(
        "SELECT value FROM app_state WHERE key = ?", (DRAFT_FIRST_PUBLICATION_KEY,)
    ).fetchone()
    if row is None:
        return False
    try:
        return json.loads(row["value"]) is True
    except (TypeError, ValueError):
        return False


class WikiPublicationService:
    def __init__(self, database: Database, wiki: WikiService):
        self.database = database
        self.wiki = wiki
        self.store = WikiGenerationStore(database)

    def publish_ingest(self, run_id: str) -> str:
        with self.database.session(read_only=True) as conn:
            run = conn.execute(
                """SELECT r.status, s.vault_id, v.root_path FROM wiki_workflow_runs r
                   JOIN wiki_sources s ON s.id = r.source_id JOIN vaults v ON v.id = s.vault_id
                   WHERE r.id = ? AND r.workflow_type = 'ingest'""", (run_id,),
            ).fetchone()
            if run is None or run["root_path"] != str(self.wiki.writer.vault_root.resolve()):
                raise WikiGenerationError("wiki_publication_run_scope")
            if run["status"] != "applied":
                raise WikiGenerationError("wiki_publication_run_not_applied")
            vault_id = run["vault_id"]
            previous = conn.execute(
                "SELECT id, status FROM wiki_generations WHERE vault_id = ? AND workflow_run_id = ?",
                (vault_id, run_id),
            ).fetchone()
            paths = dict(conn.execute(
                """SELECT target_path, target_content_hash FROM wiki_workflow_page_updates
                   WHERE run_id = ? AND status = 'written' ORDER BY target_path""",
                (run_id,),
            ).fetchall())
        if previous is not None:
            generation = previous["id"]
            if previous["status"] == "published":
                with self.database.session(read_only=True) as conn:
                    manifest = self._manifest(conn, vault_id, generation)
                    self._validate(conn, vault_id, generation, manifest)
                return generation
        else:
            if not paths:
                raise WikiGenerationError("wiki_publication_no_pages")
            base = self.store.active(vault_id)
            bodies, dependencies = self._capture(vault_id, paths)
            generation = self.store.stage(
                vault_id, base_generation=base, changes=bodies,
                dependencies=dependencies, workflow_run_id=run_id,
            )
        self.store.promote(vault_id, generation, validate=self._validate)
        return generation

    def stage_draft(self, run_id: str, approved_targets: Sequence[str] | None = None) -> str:
        """方案 A 阶段 1:把运行的规划页面作为 draft 入库(不写盘、不建 binding)。

        changes 直接取 wiki_workflow_page_updates 的规划内容;依赖在 publish_draft
        写盘后以捕获结果重建(re-capture),draft 阶段不跑权威校验(设计 §3.2)。
        """
        from app.repositories.storage import VaultRepository as _VaultRepository

        with self.database.session(read_only=True) as conn:
            run = conn.execute(
                """SELECT r.status AS run_status, s.vault_id, v.root_path
                   FROM wiki_workflow_runs r
                   JOIN wiki_sources s ON s.id = r.source_id JOIN vaults v ON v.id = s.vault_id
                   WHERE r.id = ? AND r.workflow_type = 'ingest'""", (run_id,),
            ).fetchone()
            if run is None or run["root_path"] != str(self.wiki.writer.vault_root.resolve()):
                raise WikiGenerationError("wiki_publication_run_scope")
            if run["run_status"] != "planned":
                raise WikiGenerationError("wiki_publication_run_not_planned")
            vault_id = run["vault_id"]
            rows = conn.execute(
                """SELECT * FROM wiki_workflow_page_updates
                   WHERE run_id = ? AND status = 'planned' ORDER BY created_at, target_path""", (run_id,),
            ).fetchall()
        if approved_targets is not None:
            allowed = set(approved_targets)
            rows = [row for row in rows if str(row["target_path"]) in allowed]
        if not rows:
            raise WikiGenerationError("wiki_publication_no_pages")
        base = self.store.active(vault_id)
        changes = {
            str(row["target_path"]): str(row["content"]).encode("utf-8")
            for row in rows
        }
        return self.store.stage(
            vault_id, base_generation=base, changes=changes, dependencies={},
            workflow_run_id=run_id,
        )

    def publish_draft(self, run_id: str) -> str:
        """方案 A(设计 §3.4):draft_approved 后执行 写盘→bind→index→written/applied→re-capture→promote。

        写盘走 write_page 的 target_content_hash 门禁;外部编辑冲突 →
        wiki_publication_working_copy_changed,人工修改保留、同一 run 的 staged draft 保留待重试。
        """
        from app.models.wiki import WikiPageWriteRequest
        from app.repositories.storage import VaultRepository as _VaultRepository
        from app.services.memory_entity_graph import MemoryEntityGraphStore
        from app.services.wiki import WIKI_TARGET_ABSENT_HASH, WikiConflictError
        from app.services.wiki.contracts import page_type_for_path
        from app.services.wiki_reconciler import bind_authoritative_wiki_page
        from app.storage.markdown import read_markdown as _read_markdown

        with self.database.session(read_only=True) as conn:
            run = conn.execute(
                """SELECT r.status AS run_status, r.source_id, r.request_json,
                          s.vault_id, v.root_path, r.result_json
                   FROM wiki_workflow_runs r
                   JOIN wiki_sources s ON s.id = r.source_id JOIN vaults v ON v.id = s.vault_id
                   WHERE r.id = ? AND r.workflow_type = 'ingest'""", (run_id,),
            ).fetchone()
            if run is None or run["root_path"] != str(self.wiki.writer.vault_root.resolve()):
                raise WikiGenerationError("wiki_publication_run_scope")
            if run["run_status"] != "planned":
                raise WikiGenerationError("wiki_publication_run_not_planned")
            publication = json.loads(str(run["result_json"] or "{}")).get("publication") or {}
            if str(publication.get("status") or "") != "draft_approved":
                raise WikiGenerationError("wiki_publication_draft_not_approved")
            vault_id = run["vault_id"]
            generation = conn.execute(
                """SELECT id FROM wiki_generations
                   WHERE vault_id = ? AND workflow_run_id = ? AND status = 'staged'""",
                (vault_id, run_id),
            ).fetchone()
            if generation is None:
                raise WikiGenerationError("wiki_publication_draft_missing")
            rows = conn.execute(
                """SELECT * FROM wiki_workflow_page_updates
                   WHERE run_id = ? AND status = 'planned' ORDER BY created_at, target_path""", (run_id,),
            ).fetchall()
        if not rows:
            raise WikiGenerationError("wiki_publication_no_pages")
        written_paths = [str(row["target_path"]) for row in rows]

        # 0) 内存闭包准备(写盘前持久化来源身份与候选,与 apply_ingest 的语义一致),
        #    闭包定案在写盘后执行以创建 page entity/binding/documented_in 关系
        from app.models.wiki import WikiIngestPreviewRequest as _PreviewRequest
        from .memory_closure import (
            finalize_wiki_memory_closure as _finalize_closure,
            prepare_wiki_memory_closure as _prepare_closure,
        )

        with self.database.session() as conn:
            source_row = conn.execute(
                "SELECT * FROM wiki_sources WHERE id = ? AND vault_id = ?",
                (run["source_id"], vault_id),
            ).fetchone()
        request = _PreviewRequest.model_validate(json.loads(str(run["request_json"])))
        source_path = next(
            (path for path in written_paths if path.startswith("Wiki/Sources/")),
            written_paths[0],
        )
        with self.database.session() as conn:
            closure = _prepare_closure(
                conn,
                vault_root=self.wiki.writer.vault_root,
                source_id=str(run["source_id"]),
                source_hash=str(source_row["source_hash"]),
                source_title=request.title,
                source_type=request.source_type,
                raw_content=request.content,
                source_path=source_path,
                source_metadata=request.source_metadata,
            )

        # 1) 写盘:write_page 的 target_content_hash 门禁拒绝外部修改,人工修改保留
        for row in rows:
            path = str(row["target_path"])
            try:
                self.wiki.write_page(
                    WikiPageWriteRequest(
                        title=str(row["title"]),
                        content=str(row["content"]),
                        operation=str(row["operation"]),  # type: ignore[arg-type]
                        target_path=path,
                        section=row["section"],
                        tags=json.loads(row["tags_json"] or "[]"),
                        links=json.loads(row["links_json"] or "[]"),
                        page_type=page_type_for_path(path),
                        confidence="medium",
                        sources=[source_path],
                        target_content_hash=row["target_content_hash"] or WIKI_TARGET_ABSENT_HASH,
                    )
                )
            except WikiConflictError as exc:
                raise WikiGenerationError("wiki_publication_working_copy_changed") from exc
        # 2) 闭包定案:page entity/binding/documented_in 关系(读路径解析依赖)
        with self.database.session() as conn:
            _finalize_closure(
                conn, preparation=closure, vault_root=self.wiki.writer.vault_root,
                source_type=request.source_type, written_paths=tuple(written_paths),
            )

        # 3) bind(active)+ index_refresh
        with self.database.session() as conn:
            vault_binding_id = _VaultRepository(conn).upsert(
                self.wiki.writer.vault_root, name=self.wiki.writer.vault_root.name or "Vault",
            )
            conn.commit()
            graph = MemoryEntityGraphStore(conn)
            try:
                for path in written_paths:
                    page_path = self.wiki.writer.vault_root.joinpath(*path.split("/"))
                    bind_authoritative_wiki_page(
                        graph, vault_id=vault_binding_id, relative_path=path,
                        parsed=_read_markdown(page_path), status="active",
                    )
            finally:
                graph.close()
        if self.wiki.index_refresh is not None:
            for path in written_paths:
                self.wiki.index_refresh(path)

        # 4) page_updates → written,run → applied(现有语义,触发点移到方案 A 写盘后)
        with self.database.session() as conn:
            for path in written_paths:
                conn.execute(
                    "UPDATE wiki_workflow_page_updates SET status = 'written', updated_at = datetime('now') WHERE run_id = ? AND target_path = ?",
                    (run_id, path),
                )
            conn.execute(
                "UPDATE wiki_workflow_runs SET status = 'applied', updated_at = datetime('now') WHERE id = ?",
                (run_id,),
            )

        # 5) re-capture(双 hash)+ 以磁盘真相重建 draft 清单(正文含写盘 frontmatter,
        #    依赖以捕获为准替换规划期存根);冲突由写盘门禁与 capture 双 hash 共同拦截
        from .projections import build_generation_projection

        bodies, dependencies = self._capture(vault_id, {path: None for path in written_paths})
        written_set = set(written_paths)
        bodies = {path: body for path, body in bodies.items() if path in written_set}
        dependencies = {path: dep for path, dep in dependencies.items() if path in written_set}
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM wiki_generation_pages WHERE vault_id = ? AND generation = ?",
                (vault_id, str(generation["id"])),
            )
            conn.execute(
                "DELETE FROM wiki_generation_dependencies WHERE vault_id = ? AND generation = ?",
                (vault_id, str(generation["id"])),
            )
            for path, body in bodies.items():
                digest = sha256_bytes_hex(body)
                conn.execute(
                    "INSERT OR IGNORE INTO wiki_page_bodies(vault_id, content_hash, body) VALUES (?, ?, ?)",
                    (vault_id, digest, body),
                )
                conn.execute(
                    "INSERT INTO wiki_generation_pages VALUES (?, ?, ?, ?)",
                    (vault_id, str(generation["id"]), path, digest),
                )
            for path, dependency in dependencies.items():
                conn.execute(
                    "INSERT INTO wiki_generation_dependencies VALUES (?, ?, ?, ?)",
                    (vault_id, str(generation["id"]), path, json.dumps(dependency, sort_keys=True)),
                )
            # 重建投影(清旧行避免 UNIQUE 冲突;links 随 pages 删除级联清理)
            conn.execute(
                "DELETE FROM wiki_generation_projection WHERE vault_id = ? AND generation = ?",
                (vault_id, str(generation["id"])),
            )
            build_generation_projection(conn, vault_id, str(generation["id"]))

        # 6) promote(validator 复用既有权威校验)
        self.store.promote(vault_id, str(generation["id"]), validate=self._validate)
        return str(generation["id"])

    def _capture(self, vault_id, paths):
        from .source_watermark import source_watermark

        with self.database.session(read_only=True) as conn:
            conn.execute("BEGIN")
            watermark = source_watermark(conn, vault_id)
        bodies: dict[str, bytes] = {}
        dependencies: dict[str, dict] = {}
        pending = dict(paths)
        while pending:
            path, expected_bytes_hash = pending.popitem()
            if path in bodies:
                continue
            snapshot = read_evidence_snapshot(self.wiki, path, database=self.database)
            if expected_bytes_hash is not None and snapshot.content_hash != expected_bytes_hash:
                raise WikiGenerationError("wiki_publication_working_copy_changed")
            raw = self.wiki.writer.resolve_markdown_path(path).read_bytes()
            if sha256_bytes_hex(raw) != snapshot.content_hash:
                raise WikiGenerationError("wiki_publication_working_copy_changed")
            with self.database.session(read_only=True) as conn:
                conn.execute("BEGIN")
                roots = validate_wiki_page_roots(
                    conn, vault_root=self.wiki.writer.vault_root, vault_id=vault_id,
                    source_path=path, expected_content_hash=_normalized_hash(raw),
                )
                page_hashes = dict(roots.page_hashes)
                entity_ids = list(roots.source_entity_ids)
                stamp = _dependency_stamp(conn, vault_id, page_hashes, entity_ids)
            dependencies[path] = {
                "pages": page_hashes, "root_entities": entity_ids, "stamp": stamp,
                "source_watermark": watermark,
            }
            bodies[path] = raw
            for parent in page_hashes:
                if parent not in bodies:
                    pending.setdefault(parent, None)
        return bodies, dependencies

    @staticmethod
    def _manifest(conn, vault_id, generation):
        return dict(conn.execute(
            "SELECT relative_path, content_hash FROM wiki_generation_pages WHERE vault_id = ? AND generation = ?",
            (vault_id, generation),
        ).fetchall())

    def _validate(self, conn: sqlite3.Connection, vault_id: str, generation: str, manifest: Mapping[str, str]):
        dependencies = {
            row["relative_path"]: json.loads(row["dependency_json"])
            for row in conn.execute(
                "SELECT * FROM wiki_generation_dependencies WHERE vault_id = ? AND generation = ?",
                (vault_id, generation),
            )
        }
        if not manifest or set(dependencies) != set(manifest):
            raise WikiGenerationError("wiki_publication_dependencies_missing")
        normalized = {}
        for path, digest in manifest.items():
            body = conn.execute(
                "SELECT body FROM wiki_page_bodies WHERE vault_id = ? AND content_hash = ?",
                (vault_id, digest),
            ).fetchone()
            if body is None or sha256_bytes_hex(bytes(body["body"])) != digest:
                raise WikiGenerationError("wiki_generation_body_integrity")
            normalized[path] = _normalized_hash(bytes(body["body"]))
        for path, dependency in dependencies.items():
            validate_snapshot_dependency(conn, vault_id, path, dependency, normalized)
