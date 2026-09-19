"""Version-pinned internal reading primitives for the Wiki query pipeline."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.repositories.storage import _make_like_snippet, _to_fts_queries, _to_like_pattern
from app.services.wiki import WikiService
from app.storage.database import Database
from app.storage.markdown import HEADING_RE, parse_markdown
from app.utils.hash import sha256_bytes_hex

from .compiler import check_material
from .generations import WikiGenerationError
from .projections import require_generation_projection, snapshot_text
from .publication import _normalized_hash, validate_snapshot_dependency


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


class WikiSnapshotReader:
    """Caller supplies live access policy; generation membership is not permission.

    No API or chat route is enabled by this class. Lines refer to the normalized
    Markdown body, excluding frontmatter. Each operation rechecks live authority;
    a later prompt/send boundary must revalidate again.
    """

    def __init__(
        self, database: Database, wiki: WikiService, *,
        authorize: Callable[[str, str], bool],
    ):
        self.database = database
        self.wiki = wiki
        self.authorize = authorize

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
                rank = "bm25(wiki_body_fts)" if "MATCH" in clause else "p.relative_path"
                rows = conn.execute(
                    f"""SELECT p.relative_path, p.content_hash, wiki_body_fts.chunk_index
                        FROM wiki_body_fts JOIN wiki_generation_pages p
                          ON p.vault_id = wiki_body_fts.vault_id AND p.content_hash = wiki_body_fts.content_hash
                        WHERE p.vault_id = ? AND p.generation = ? AND {clause}
                        ORDER BY {rank} LIMIT ?""",
                    (pin.vault_id, pin.generation, *params, max(32, limit * 8)),
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
                    )
                    if len(collected) >= limit:
                        break
                if len(collected) >= limit:
                    break
        results = []
        for candidate in collected.values():
            try:
                self._load(pin, candidate.relative_path, candidate.content_hash)
            except WikiGenerationError:
                continue
            results.append(candidate)
        return results

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
               WHERE g.id = ? AND g.vault_id = ? AND g.status = 'published' AND v.root_path = ?""",
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
