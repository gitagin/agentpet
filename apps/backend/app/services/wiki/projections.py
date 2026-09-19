"""SQLite search/link projections of immutable Wiki bodies."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import PurePosixPath

from app.repositories.storage import _bigram_cjk
from app.storage.markdown import parse_markdown
from app.utils.hash import sha256_bytes_hex

from . import _legacy_wiki


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
            title, links = parsed.title, parsed.links
        else:
            title, links = projected["title"], json.loads(projected["links_json"])
        pages.append(_legacy_wiki._GraphPage(
            title=title or PurePosixPath(row["relative_path"]).stem,
            relative_path=row["relative_path"], links=links, frontmatter={},
        ))
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
