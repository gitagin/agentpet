"""Internal publication storage; snapshots never confer evidence authority."""

from __future__ import annotations

import sqlite3
import inspect
import json
from collections.abc import Callable, Mapping
from types import MappingProxyType
from uuid import uuid4

from app.services.memory import SafeMarkdownWriter
from app.storage.database import Database
from app.utils.hash import sha256_bytes_hex


class WikiGenerationError(ValueError):
    pass


# The publisher must supply a synchronous, deterministic authority check.
# No model calls, commits, or external writes belong inside this transaction.
PublicationValidator = Callable[[sqlite3.Connection, str, str, Mapping[str, str]], None]


class WikiGenerationStore:
    """Version manifests and shared bodies in the existing application database.

    This storage boundary is not a query API. Callers must validate live access
    before sending snapshot contents to a user or model. History is retained;
    cleanup and forgetting require the later dependency/lease integration.
    """

    def __init__(self, database: Database):
        self.database = database

    def active(self, vault_id: str) -> str | None:
        with self.database.session(read_only=True) as conn:
            return self._active(conn, vault_id)

    def stage(
        self, vault_id: str, *, base_generation: str | None,
        changes: Mapping[str, bytes | None],
        dependencies: Mapping[str, dict] | None = None,
        workflow_run_id: str | None = None,
    ) -> str:
        with self.database.session(read_only=True) as conn:
            vault = conn.execute("SELECT root_path FROM vaults WHERE id = ?", (vault_id,)).fetchone()
            if vault is None:
                raise WikiGenerationError("wiki_generation_unknown_vault")
        writer = SafeMarkdownWriter(vault["root_path"])
        prepared: dict[str, tuple[str, bytes] | None] = {}
        for path, body in changes.items():
            if (
                not path.startswith("Wiki/") or "\\" in path or "//" in path
                or any(part.startswith(".") for part in path.split("/"))
            ):
                raise WikiGenerationError("wiki_generation_invalid_path")
            writer.resolve_markdown_path(path)
            if body is None:
                prepared[path] = None
            else:
                body.decode("utf-8-sig")
                prepared[path] = (sha256_bytes_hex(body), body)
        generation = str(uuid4())
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if self._active(conn, vault_id) != base_generation:
                raise WikiGenerationError("wiki_generation_base_conflict")
            conn.execute(
                "INSERT OR IGNORE INTO wiki_generation_heads(vault_id) VALUES (?)", (vault_id,),
            )
            conn.execute(
                """INSERT INTO wiki_generations(id, vault_id, base_generation, status, workflow_run_id)
                   VALUES (?, ?, ?, 'staged', ?)""",
                (generation, vault_id, base_generation, workflow_run_id),
            )
            if base_generation is not None:
                conn.execute(
                    """INSERT INTO wiki_generation_pages(vault_id, generation, relative_path, content_hash)
                       SELECT vault_id, ?, relative_path, content_hash FROM wiki_generation_pages
                       WHERE vault_id = ? AND generation = ?""",
                    (generation, vault_id, base_generation),
                )
                conn.execute(
                    """INSERT INTO wiki_generation_dependencies
                       SELECT vault_id, ?, relative_path, dependency_json FROM wiki_generation_dependencies
                       WHERE vault_id = ? AND generation = ?""",
                    (generation, vault_id, base_generation),
                )
            for path, entry in prepared.items():
                conn.execute(
                    "DELETE FROM wiki_generation_pages WHERE vault_id = ? AND generation = ? AND relative_path = ?",
                    (vault_id, generation, path),
                )
                if entry is None:
                    continue
                digest, body = entry
                conn.execute(
                    "INSERT OR IGNORE INTO wiki_page_bodies(vault_id, content_hash, body) VALUES (?, ?, ?)",
                    (vault_id, digest, body),
                )
                stored = conn.execute(
                    "SELECT body FROM wiki_page_bodies WHERE vault_id = ? AND content_hash = ?",
                    (vault_id, digest),
                ).fetchone()
                if bytes(stored["body"]) != body:
                    raise WikiGenerationError("wiki_generation_body_integrity")
                conn.execute(
                    "INSERT INTO wiki_generation_pages VALUES (?, ?, ?, ?)",
                    (vault_id, generation, path, digest),
                )
                if dependencies is not None and path in dependencies:
                    conn.execute(
                        "INSERT INTO wiki_generation_dependencies VALUES (?, ?, ?, ?)",
                        (vault_id, generation, path, json.dumps(dependencies[path], sort_keys=True)),
                    )
            from .projections import build_generation_projection

            build_generation_projection(conn, vault_id, generation)
        return generation

    def promote(
        self, vault_id: str, generation: str, *, validate: PublicationValidator,
    ) -> None:
        if inspect.iscoroutinefunction(validate):
            raise WikiGenerationError("wiki_generation_async_validator")
        with self.database.session() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM wiki_generations WHERE vault_id = ? AND id = ?",
                (vault_id, generation),
            ).fetchone()
            if row is None or row["status"] != "staged":
                raise WikiGenerationError("wiki_generation_not_staged")
            if self._active(conn, vault_id) != row["base_generation"]:
                raise WikiGenerationError("wiki_generation_base_conflict")
            from .projections import require_generation_projection

            require_generation_projection(conn, vault_id, generation)
            manifest = dict(conn.execute(
                "SELECT relative_path, content_hash FROM wiki_generation_pages WHERE vault_id = ? AND generation = ?",
                (vault_id, generation),
            ).fetchall())
            for body in conn.execute(
                """SELECT b.body, b.content_hash FROM wiki_page_bodies b
                   WHERE b.vault_id = ? AND b.content_hash IN (
                     SELECT content_hash FROM wiki_generation_pages WHERE vault_id = ? AND generation = ?)""",
                (vault_id, vault_id, generation),
            ):
                if sha256_bytes_hex(bytes(body["body"])) != body["content_hash"]:
                    raise WikiGenerationError("wiki_generation_body_integrity")
            result = validate(conn, vault_id, generation, MappingProxyType(manifest))
            if inspect.iscoroutine(result):
                result.close()
            if result is not None:
                raise WikiGenerationError("wiki_generation_invalid_validation_result")
            updated = conn.execute(
                """UPDATE wiki_generation_heads SET active_generation = ?
                   WHERE vault_id = ? AND active_generation IS ?""",
                (generation, vault_id, row["base_generation"]),
            )
            if updated.rowcount != 1:
                raise WikiGenerationError("wiki_generation_base_conflict")
            conn.execute(
                "UPDATE wiki_generations SET status = 'published', published_at = datetime('now') WHERE id = ?",
                (generation,),
            )
            if row["workflow_run_id"] is not None:
                receipt = conn.execute(
                    """UPDATE wiki_workflow_runs
                       SET result_json = json_set(result_json, '$.publication', json(?)),
                           updated_at = datetime('now')
                       WHERE id = ? AND workflow_type = 'ingest' AND status = 'applied'""",
                    (json.dumps({"status": "published", "generation": generation}), row["workflow_run_id"]),
                )
                if receipt.rowcount != 1:
                    raise WikiGenerationError("wiki_publication_run_not_applied")

    def read_body(self, vault_id: str, generation: str, relative_path: str) -> bytes:
        """Internal published snapshot read, always scoped to an explicit version."""
        with self.database.session(read_only=True) as conn:
            row = conn.execute(
                """SELECT b.body, p.content_hash FROM wiki_generation_pages p
                   JOIN wiki_generations g ON g.id = p.generation AND g.vault_id = p.vault_id
                   JOIN wiki_page_bodies b ON b.vault_id = p.vault_id AND b.content_hash = p.content_hash
                   WHERE p.vault_id = ? AND p.generation = ? AND p.relative_path = ?
                     AND g.status = 'published'""",
                (vault_id, generation, relative_path),
            ).fetchone()
            if row is None:
                raise WikiGenerationError("wiki_generation_page_unavailable")
            body = bytes(row["body"])
            if sha256_bytes_hex(body) != row["content_hash"]:
                raise WikiGenerationError("wiki_generation_body_integrity")
            return body

    @staticmethod
    def _active(conn: sqlite3.Connection, vault_id: str) -> str | None:
        row = conn.execute(
            "SELECT active_generation FROM wiki_generation_heads WHERE vault_id = ?", (vault_id,),
        ).fetchone()
        return row["active_generation"] if row is not None else None
