"""Reconcile user-editable Wiki Markdown with SQLite authority metadata."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.storage.database import open_database_connection
from app.storage.markdown import ParsedMarkdown, read_markdown


@dataclass(frozen=True, slots=True)
class WikiReconcileReport:
    vault_id: str
    scanned: int
    created: int
    changed: int
    deleted: int
    quarantined: int
    revision_before: int
    revision_after: int


def bind_authoritative_wiki_page(
    graph: MemoryEntityGraphStore,
    *,
    vault_id: str,
    relative_path: str,
    parsed: ParsedMarkdown,
    status: str = "active",
) -> str:
    normalized_path = relative_path.replace("\\", "/")
    entity_key = f"wiki-page:{vault_id}:{normalized_path}"
    with graph.atomic():
        row = graph.conn.execute(
            "SELECT id FROM memory_entities WHERE entity_key = ?",
            (entity_key,),
        ).fetchone()
        if row is None:
            entity = graph.create_entity(
                entity_type="wiki_page",
                canonical_name=parsed.title or Path(normalized_path).stem,
                entity_key=entity_key,
                confidence=1.0,
                metadata={"wiki_relative_path": normalized_path, "vault_id": vault_id},
            )
        else:
            entity = graph.get_entity(str(row["id"]))
        return graph.bind_wiki_page(
            vault_id=vault_id,
            page_entity_id=entity.id,
            wiki_relative_path=normalized_path,
            content_hash=parsed.content_hash,
            revision=_frontmatter_revision(parsed),
            status=status,
        )


def reconcile_wiki_vault(
    db: str | Path | sqlite3.Connection,
    *,
    vault_id: str,
    vault_root: str | Path,
) -> WikiReconcileReport:
    """Make binding hashes trustworthy before any derived read is used.

    External edits never silently become verified facts.  A changed active
    page is marked stale; a later reviewed write can promote it again.
    """
    owns = not isinstance(db, sqlite3.Connection)
    conn = open_database_connection(db)
    try:
        graph = MemoryEntityGraphStore(conn)
        before = graph.source_revision()
        root = Path(vault_root).resolve(strict=False) / "Wiki"
        if not root.exists():
            graph.close()
            return WikiReconcileReport(
                vault_id=vault_id,
                scanned=0,
                created=0,
                changed=0,
                deleted=0,
                quarantined=0,
                revision_before=before,
                revision_after=before,
            )
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        files: dict[str, tuple[Path, ParsedMarkdown]] = {}
        for path in sorted(root.rglob("*.md")):
            relative = path.relative_to(Path(vault_root).resolve(strict=False)).as_posix()
            if relative in {"Wiki/AGENTS.md", "Wiki/index.md", "Wiki/log.md"}:
                continue
            try:
                parsed = read_markdown(path)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            files[relative] = (path, parsed)

        existing = {
            str(row["wiki_relative_path"]): row
            for row in graph.list_wiki_bindings(vault_id=vault_id)
        }
        created = changed = deleted = quarantined = 0
        for relative, (_path, parsed) in files.items():
            current_hash = str(getattr(parsed, "content_hash", "") or "")
            frontmatter = getattr(parsed, "frontmatter", {}) or {}
            sources = frontmatter.get("sources")
            has_sources = bool(sources) and (not isinstance(sources, list) or any(str(item).strip() for item in sources))
            status = "active" if has_sources else "quarantined"
            row = existing.get(relative)
            if row is None:
                bind_authoritative_wiki_page(
                    graph,
                    vault_id=vault_id,
                    relative_path=relative,
                    parsed=parsed,
                    status=status,
                )
                created += 1
                quarantined += int(status == "quarantined")
                continue
            old_hash = str(row["content_hash"] or "")
            old_status = str(row["status"] or "")
            if old_hash != current_hash:
                graph.update_wiki_binding(
                    str(row["id"]),
                    content_hash=current_hash,
                    status="stale" if old_status == "active" else status,
                    revision=int(row["revision"] or 0) + 1,
                )
                changed += 1
        for relative, row in existing.items():
            if relative in files or str(row["status"]) in {"forgotten", "stale"}:
                continue
            graph.update_wiki_binding(
                str(row["id"]),
                content_hash=str(row["content_hash"] or "") or None,
                status="stale",
                revision=int(row["revision"] or 0) + 1,
            )
            deleted += 1
        after = graph.source_revision()
        graph.close()
        return WikiReconcileReport(
            vault_id=vault_id,
            scanned=len(files),
            created=created,
            changed=changed,
            deleted=deleted,
            quarantined=quarantined,
            revision_before=before,
            revision_after=after,
        )
    finally:
        if owns:
            conn.close()


def _frontmatter_revision(parsed: ParsedMarkdown) -> int:
    try:
        return max(1, int(str(parsed.frontmatter.get("revision") or "1")))
    except (TypeError, ValueError):
        return 1


def reconcile_all_vaults(db: str | Path | sqlite3.Connection) -> tuple[WikiReconcileReport, ...]:
    owns = not isinstance(db, sqlite3.Connection)
    conn = open_database_connection(db)
    try:
        rows = conn.execute("SELECT id, root_path FROM vaults ORDER BY id").fetchall()
        return tuple(
            reconcile_wiki_vault(conn, vault_id=str(row["id"]), vault_root=str(row["root_path"]))
            for row in rows
        )
    finally:
        if owns:
            conn.close()
