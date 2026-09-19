"""Publish verified ingest artifacts without granting snapshot read permission."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping

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
