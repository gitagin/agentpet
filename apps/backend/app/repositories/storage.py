from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models.common import new_id
from app.models.enums import IndexJobStatus, IndexJobType, NoteStatus
from app.storage.markdown import ParsedMarkdown


FTS_TOKEN_RE = re.compile(r"[\w-]+", re.UNICODE)
CJK_RE = re.compile(r"[\u3400-\u9fff]")
QUERY_STOP_WORDS = {
    "a",
    "about",
    "an",
    "and",
    "any",
    "are",
    "base",
    "do",
    "does",
    "for",
    "from",
    "have",
    "in",
    "is",
    "knowledge",
    "know",
    "me",
    "memory",
    "note",
    "notes",
    "of",
    "on",
    "please",
    "say",
    "says",
    "the",
    "to",
    "vault",
    "what",
    "who",
    "with",
}
QUERY_SYNONYMS = {
    "preference": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "preferences": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "prefer": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "prefers": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "like": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "likes": ("preference", "preferences", "prefer", "prefers", "like", "likes"),
    "todo": ("todo", "task", "tasks"),
    "task": ("todo", "task", "tasks"),
    "tasks": ("todo", "task", "tasks"),
    "reminder": ("reminder", "reminders", "remind"),
    "reminders": ("reminder", "reminders", "remind"),
    "偏好": ("偏好", "喜好", "喜欢"),
    "喜好": ("偏好", "喜好", "喜欢"),
    "喜欢": ("偏好", "喜好", "喜欢"),
    "任务": ("任务", "待办", "todo"),
    "待办": ("任务", "待办", "todo"),
    "提醒": ("提醒", "reminder", "remind"),
}


@dataclass(frozen=True)
class SearchResult:
    note_id: str
    chunk_id: str
    relative_path: str
    title: str
    heading: str | None
    snippet: str
    score: float
    content_hash: str | None = None
    vault_id: str | None = None
    generation: str | None = None


class VaultRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert(self, root_path: str | Path, *, name: str | None = None, vault_id: str | None = None) -> str:
        root = str(Path(root_path).resolve(strict=False))
        existing = self.conn.execute("SELECT id FROM vaults WHERE root_path = ?", (root,)).fetchone()
        if existing:
            self.conn.execute(
                """
                UPDATE vaults
                SET name = COALESCE(?, name),
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (name, existing["id"]),
            )
            return str(existing["id"])
        created_id = vault_id or new_id()
        self.conn.execute(
            "INSERT INTO vaults(id, root_path, name) VALUES (?, ?, ?)",
            (created_id, root, name or Path(root).name or "Vault"),
        )
        return created_id

    def get(self, vault_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM vaults WHERE id = ?", (vault_id,)).fetchone()
        if row is None:
            raise KeyError(f"Vault not found: {vault_id}")
        return row

    def set_active(self, vault_id: str) -> None:
        self.get(vault_id)
        self.conn.execute(
            """
            INSERT INTO app_state(key, value, updated_at)
            VALUES ('active_vault_id', ?, datetime('now'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (vault_id,),
        )

    def get_active(self) -> sqlite3.Row | None:
        row = self.conn.execute(
            """
            SELECT vaults.*
            FROM app_state
            JOIN vaults ON vaults.id = app_state.value
            WHERE app_state.key = 'active_vault_id'
            """
        ).fetchone()
        if row is not None:
            return row
        return self.conn.execute(
            "SELECT * FROM vaults ORDER BY updated_at DESC, created_at DESC LIMIT 1"
        ).fetchone()


class NoteRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def replace_note(self, *, vault_id: str, relative_path: str, markdown: ParsedMarkdown, modified_at: float) -> str:
        existing = self.conn.execute(
            "SELECT id FROM notes WHERE vault_id = ? AND relative_path = ?",
            (vault_id, relative_path),
        ).fetchone()
        note_id = str(existing["id"]) if existing else new_id()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO notes(
                    id, vault_id, relative_path, title, content_hash, modified_at, status,
                    frontmatter_json, tags_json, links_json, indexed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(vault_id, relative_path) DO UPDATE SET
                    title = excluded.title,
                    content_hash = excluded.content_hash,
                    modified_at = excluded.modified_at,
                    status = excluded.status,
                    frontmatter_json = excluded.frontmatter_json,
                    tags_json = excluded.tags_json,
                    links_json = excluded.links_json,
                    indexed_at = datetime('now')
                """,
                (
                    note_id,
                    vault_id,
                    relative_path,
                    markdown.title,
                    markdown.content_hash,
                    modified_at,
                    NoteStatus.INDEXED.value,
                    json.dumps(markdown.frontmatter, ensure_ascii=True, sort_keys=True),
                    json.dumps(markdown.tags, ensure_ascii=True),
                    json.dumps(markdown.links, ensure_ascii=True),
                ),
            )
            self.conn.execute("DELETE FROM note_fts WHERE note_id = ?", (note_id,))
            self.conn.execute("DELETE FROM note_chunks WHERE note_id = ?", (note_id,))
            for chunk in markdown.chunks:
                chunk_id = new_id()
                self.conn.execute(
                    """
                    INSERT INTO note_chunks(
                        id, note_id, vault_id, chunk_index, relative_path, title, heading,
                        content, start_line, end_line, content_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        chunk_id,
                        note_id,
                        vault_id,
                        chunk.index,
                        relative_path,
                        markdown.title,
                        chunk.heading,
                        chunk.content,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.content_hash,
                    ),
                )
                self.conn.execute(
                    """
                    INSERT INTO note_fts(chunk_id, note_id, vault_id, relative_path, title, heading, content)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (chunk_id, note_id, vault_id, relative_path, markdown.title, chunk.heading or "", chunk.content),
                )
        return note_id

    def mark_deleted(self, *, vault_id: str, relative_path: str) -> None:
        with self.conn:
            row = self.conn.execute(
                "SELECT id FROM notes WHERE vault_id = ? AND relative_path = ?",
                (vault_id, relative_path),
            ).fetchone()
            if row is None:
                return
            note_id = row["id"]
            self.conn.execute("DELETE FROM note_fts WHERE note_id = ?", (note_id,))
            self.conn.execute("DELETE FROM note_chunks WHERE note_id = ?", (note_id,))
            self.conn.execute(
                "UPDATE notes SET status = ?, indexed_at = datetime('now') WHERE id = ?",
                (NoteStatus.DELETED.value, note_id),
            )

    def list_active_paths(self, *, vault_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT relative_path FROM notes WHERE vault_id = ? AND status != ?",
            (vault_id, NoteStatus.DELETED.value),
        ).fetchall()
        return {str(row["relative_path"]) for row in rows}

    def search(self, *, vault_id: str, query: str, top_k: int = 8) -> list[SearchResult]:
        fts_queries = _to_fts_queries(query)
        if not fts_queries:
            return []
        for fts_query in fts_queries:
            rows = self.conn.execute(
                """
                SELECT
                    chunk_id,
                    note_id,
                    relative_path,
                    title,
                    NULLIF(heading, '') AS heading,
                    snippet(note_fts, 6, '[', ']', '...', 24) AS snippet,
                    bm25(note_fts) AS rank
                FROM note_fts
                WHERE vault_id = ? AND note_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (vault_id, fts_query, top_k),
            ).fetchall()
            if rows:
                return [
                    SearchResult(
                        note_id=str(row["note_id"]),
                        chunk_id=str(row["chunk_id"]),
                        relative_path=str(row["relative_path"]),
                        title=str(row["title"]),
                        heading=row["heading"],
                        snippet=str(row["snippet"]),
                        score=float(-row["rank"]),
                    )
                    for row in rows
                ]

        like_queries = _to_like_queries(query)
        if not like_queries:
            return []
        results: list[SearchResult] = []
        seen_chunks: set[str] = set()
        for like_query in like_queries:
            like_pattern = _to_like_pattern(like_query)
            fallback_rows = self.conn.execute(
                """
                SELECT
                    id AS chunk_id,
                    note_id,
                    relative_path,
                    title,
                    heading,
                    content
                FROM note_chunks
                WHERE vault_id = ?
                  AND (
                    content LIKE ? ESCAPE '~'
                    OR title LIKE ? ESCAPE '~'
                    OR COALESCE(heading, '') LIKE ? ESCAPE '~'
                  )
                ORDER BY relative_path, chunk_index
                LIMIT ?
                """,
                (vault_id, like_pattern, like_pattern, like_pattern, top_k),
            ).fetchall()
            for row in fallback_rows:
                chunk_id = str(row["chunk_id"])
                if chunk_id in seen_chunks:
                    continue
                seen_chunks.add(chunk_id)
                results.append(
                    SearchResult(
                        note_id=str(row["note_id"]),
                        chunk_id=chunk_id,
                        relative_path=str(row["relative_path"]),
                        title=str(row["title"]),
                        heading=row["heading"],
                        snippet=_make_like_snippet(
                            content=str(row["content"]),
                            query=like_query,
                            title=str(row["title"]),
                            heading=row["heading"],
                        ),
                        score=1.0,
                    )
                )
                if len(results) >= top_k:
                    return results
        return results

    def search_daily_chat_by_date(self, *, vault_id: str, query: str, top_k: int = 8) -> list[SearchResult]:
        month_day = _extract_month_day(query)
        if month_day is None:
            return []
        month, day = month_day
        filename_suffix = "-%02d-%02d.md" % (month, day)
        rows = self.conn.execute(
            """
            SELECT
                id AS chunk_id,
                note_id,
                relative_path,
                title,
                heading,
                content
            FROM note_chunks
            WHERE vault_id = ?
              AND relative_path LIKE ? ESCAPE '~'
              AND relative_path LIKE 'Memories/Daily/%'
            ORDER BY
                relative_path,
                CASE
                    WHEN content LIKE '%用户问题%' OR content LIKE '%桌宠回答%' THEN 0
                    ELSE 1
                END,
                chunk_index
            LIMIT ?
            """,
            (vault_id, _to_like_pattern(filename_suffix), top_k),
        ).fetchall()
        return [
            SearchResult(
                note_id=str(row["note_id"]),
                chunk_id=str(row["chunk_id"]),
                relative_path=str(row["relative_path"]),
                title=str(row["title"]),
                heading=row["heading"],
                snippet=_make_daily_date_snippet(str(row["content"])),
                score=1.0,
            )
            for row in rows
        ]


class IndexJobRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, *, vault_id: str, job_type: IndexJobType = IndexJobType.FULL) -> str:
        job_id = new_id()
        self.conn.execute(
            "INSERT INTO index_jobs(id, vault_id, type, status) VALUES (?, ?, ?, ?)",
            (job_id, vault_id, job_type.value, IndexJobStatus.RUNNING.value),
        )
        return job_id

    def finish(self, *, job_id: str, status: IndexJobStatus, files_seen: int, files_indexed: int, error: str | None = None) -> None:
        self.conn.execute(
            """
            UPDATE index_jobs
            SET status = ?, files_seen = ?, files_indexed = ?, error = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (status.value, files_seen, files_indexed, error, job_id),
        )


def _to_fts_query(query: str) -> str:
    tokens = [token.strip("-_") for token in FTS_TOKEN_RE.findall(query)]
    return " ".join(_quote_fts_token(token) for token in tokens if token)


def _to_fts_queries(query: str) -> list[str]:
    exact_query = _to_fts_query(query)
    terms = _expanded_query_terms(query)
    queries = [exact_query] if exact_query else []
    if terms:
        queries.append(" OR ".join(_quote_fts_token(term) for term in terms))
        queries.extend(_quote_fts_token(term) for term in terms)
    return _unique_non_empty(queries)


def _to_like_queries(query: str) -> list[str]:
    return _unique_non_empty([query.strip(), *_expanded_query_terms(query)])


def _expanded_query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in FTS_TOKEN_RE.findall(query):
        normalized = token.strip("-_")
        if not normalized:
            continue
        folded = normalized.casefold()
        if not CJK_RE.search(normalized) and (folded in QUERY_STOP_WORDS or len(folded) <= 1):
            continue
        terms.extend(_expand_query_term(folded if not CJK_RE.search(normalized) else normalized))
    for keyword in QUERY_SYNONYMS:
        if CJK_RE.search(keyword) and keyword in query:
            terms.extend(QUERY_SYNONYMS[keyword])
    return _unique_non_empty(terms)


def _expand_query_term(term: str) -> list[str]:
    if term in QUERY_SYNONYMS:
        return list(QUERY_SYNONYMS[term])
    for keyword, synonyms in QUERY_SYNONYMS.items():
        if CJK_RE.search(keyword) and keyword in term:
            return list(synonyms)
    return [term]


def _quote_fts_token(token: str) -> str:
    return f'"{token.replace(chr(34), chr(34) + chr(34))}"'


def _unique_non_empty(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in seen:
            seen.add(stripped)
            unique.append(stripped)
    return unique


def _to_like_pattern(query: str) -> str:
    escaped = query.replace("~", "~~").replace("%", "~%").replace("_", "~_")
    return f"%{escaped}%"


def _make_like_snippet(*, content: str, query: str, title: str, heading: str | None) -> str:
    sources = [content, heading or "", title]
    for source in sources:
        index = source.casefold().find(query.casefold())
        if index >= 0:
            start = max(0, index - 40)
            end = min(len(source), index + len(query) + 40)
            prefix = "..." if start > 0 else ""
            suffix = "..." if end < len(source) else ""
            return f"{prefix}{source[start:index]}[{source[index:index + len(query)]}]{source[index + len(query):end]}{suffix}"
    return content[:120]


def _extract_month_day(query: str) -> tuple[int, int] | None:
    match = re.search(r"(?:\d{4}\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*(?:号|日)?", query)
    if match is None:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return month, day


def _make_daily_date_snippet(content: str) -> str:
    lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if any(
            marker in stripped
            for marker in (
                "conversation_id",
                "user_message_id",
                "assistant_message_id",
                "agent_run_id",
            )
        ):
            continue
        lines.append(stripped)
    return " ".join(lines)[:600]
