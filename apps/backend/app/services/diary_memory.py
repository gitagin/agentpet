from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.services.diary_memory_extractor import ALLOWED_DIARY_MEMORY_TYPES, DiaryMemoryExtractor, DiaryMemoryObject
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


DEFAULT_DIARY_MEMORY_TYPE = "event"


@dataclass(frozen=True, slots=True)
class DiaryMemoryObjectSource:
    object_id: str
    source_type: str
    source_id: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    agent_run_id: str | None = None
    markdown_path: str | None = None
    note_id: str | None = None
    chunk_id: str | None = None


@dataclass(frozen=True, slots=True)
class DiaryMemoryObjectRecord:
    id: str
    vault_id: str
    type: str
    summary: str
    topic: str | None
    emotion: str | None
    people: tuple[str, ...]
    keywords: tuple[str, ...]
    importance: float
    confidence: float
    occurred_at: str
    timezone: str
    status: MemoryFactStatus
    object_hash: str
    extraction_model: str | None
    created_at: str
    updated_at: str
    sources: tuple[DiaryMemoryObjectSource, ...] = ()


@dataclass(frozen=True, slots=True)
class DiaryMemorySearch:
    query: str = ""
    type: str | None = None
    topic: str | None = None
    emotion: str | None = None
    people: tuple[str, ...] = ()
    min_importance: float | None = None
    from_: str | None = None
    to: str | None = None
    top_k: int = 8


@dataclass(frozen=True, slots=True)
class DiaryMemoryArchiveResult:
    objects_seen: int
    objects_written: int
    object_ids: tuple[str, ...]


class DiaryMemoryNotFoundError(KeyError):
    pass


class DiaryMemoryStore:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def insert_object(
        self,
        *,
        vault_id: str,
        extracted: DiaryMemoryObject,
        occurred_at: str,
        timezone: str,
        source: DiaryMemoryObjectSource,
        extraction_model: str | None = None,
        memory_type: str | None = None,
    ) -> DiaryMemoryObjectRecord | None:
        memory_type = _safe_memory_type(memory_type or extracted.type)
        if memory_type is None:
            return None
        object_hash = _object_hash(
            vault_id=vault_id,
            memory_type=memory_type,
            summary=extracted.summary,
            topic=extracted.topic,
            emotion=extracted.emotion,
            people=extracted.people,
            keywords=extracted.keywords,
            source_id=source.source_id,
        )
        existing = self._get_by_hash(object_hash)
        if existing is not None:
            self._insert_source(existing.id, source)
            return None

        now = utc_now_iso()
        object_id = new_id()
        people_json = _json_list(extracted.people)
        keywords_json = _json_list(extracted.keywords)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO diary_memory_objects (
                    id, vault_id, type, summary, topic, emotion, people_json,
                    keywords_json, importance, confidence, occurred_at, timezone,
                    status, object_hash, extraction_model, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    object_id,
                    vault_id,
                    memory_type,
                    extracted.summary,
                    extracted.topic or None,
                    extracted.emotion or None,
                    people_json,
                    keywords_json,
                    extracted.importance,
                    extracted.confidence,
                    occurred_at,
                    timezone,
                    extracted.status.value,
                    object_hash,
                    extraction_model,
                    now,
                    now,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO diary_memory_object_fts(
                    object_id, type, summary, topic, emotion, people, keywords
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    object_id,
                    memory_type,
                    extracted.summary,
                    extracted.topic,
                    extracted.emotion,
                    " ".join(extracted.people),
                    " ".join(extracted.keywords),
                ),
            )
            self._insert_source(object_id, source)
        return self.get(object_id)

    def search(self, filters: DiaryMemorySearch, *, vault_id: str) -> list[DiaryMemoryObjectRecord]:
        clauses = ["o.vault_id = ?"]
        params: list[object] = [vault_id]
        joins = ""
        if filters.query.strip():
            joins = "JOIN diary_memory_object_fts fts ON fts.object_id = o.id"
            clauses.append("diary_memory_object_fts MATCH ?")
            params.append(_to_fts_query(filters.query.strip()))
        if filters.type:
            clauses.append("o.type = ?")
            params.append(filters.type)
        if filters.topic:
            clauses.append("o.topic LIKE ? ESCAPE '~'")
            params.append(_like_pattern(filters.topic))
        if filters.emotion:
            clauses.append("o.emotion LIKE ? ESCAPE '~'")
            params.append(_like_pattern(filters.emotion))
        if filters.people:
            for person in filters.people:
                clauses.append("o.people_json LIKE ? ESCAPE '~'")
                params.append(_like_pattern(person))
        if filters.min_importance is not None:
            clauses.append("o.importance >= ?")
            params.append(max(0.0, min(1.0, filters.min_importance)))
        if filters.from_:
            clauses.append("o.occurred_at >= ?")
            params.append(filters.from_)
        if filters.to:
            clauses.append("o.occurred_at <= ?")
            params.append(filters.to)

        rank_expr = "bm25(diary_memory_object_fts)" if filters.query.strip() else "0"
        rows = self.conn.execute(
            f"""
            SELECT o.*, {rank_expr} AS rank
            FROM diary_memory_objects o
            {joins}
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE o.status WHEN 'active' THEN 0 WHEN 'candidate' THEN 1 WHEN 'quarantined' THEN 2 ELSE 3 END,
                o.importance DESC,
                o.confidence DESC,
                rank,
                o.occurred_at DESC
            LIMIT ?
            """,
            (*params, max(1, min(filters.top_k, 50))),
        ).fetchall()
        return [self._map(row, include_sources=False) for row in rows]

    def get(self, object_id: str) -> DiaryMemoryObjectRecord:
        row = self.conn.execute(
            "SELECT * FROM diary_memory_objects WHERE id = ?",
            (object_id,),
        ).fetchone()
        if row is None:
            raise DiaryMemoryNotFoundError(object_id)
        return self._map(row, include_sources=True)

    def _get_by_hash(self, object_hash: str) -> DiaryMemoryObjectRecord | None:
        row = self.conn.execute(
            "SELECT * FROM diary_memory_objects WHERE object_hash = ?",
            (object_hash,),
        ).fetchone()
        return self._map(row, include_sources=False) if row else None

    def _insert_source(self, object_id: str, source: DiaryMemoryObjectSource) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO diary_memory_object_sources (
                object_id, source_type, source_id, conversation_id, user_message_id,
                assistant_message_id, agent_run_id, markdown_path, note_id, chunk_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                object_id,
                source.source_type,
                source.source_id,
                source.conversation_id,
                source.user_message_id,
                source.assistant_message_id,
                source.agent_run_id,
                source.markdown_path,
                source.note_id,
                source.chunk_id,
            ),
        )

    def _sources(self, object_id: str) -> tuple[DiaryMemoryObjectSource, ...]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM diary_memory_object_sources
            WHERE object_id = ?
            ORDER BY source_type, source_id
            """,
            (object_id,),
        ).fetchall()
        return tuple(
            DiaryMemoryObjectSource(
                object_id=row["object_id"],
                source_type=row["source_type"],
                source_id=row["source_id"],
                conversation_id=row["conversation_id"],
                user_message_id=row["user_message_id"],
                assistant_message_id=row["assistant_message_id"],
                agent_run_id=row["agent_run_id"],
                markdown_path=row["markdown_path"],
                note_id=row["note_id"],
                chunk_id=row["chunk_id"],
            )
            for row in rows
        )

    def _map(self, row: sqlite3.Row, *, include_sources: bool) -> DiaryMemoryObjectRecord:
        object_id = row["id"]
        return DiaryMemoryObjectRecord(
            id=object_id,
            vault_id=row["vault_id"],
            type=row["type"],
            summary=row["summary"],
            topic=row["topic"],
            emotion=row["emotion"],
            people=tuple(_json_list_value(row["people_json"])),
            keywords=tuple(_json_list_value(row["keywords_json"])),
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            occurred_at=row["occurred_at"],
            timezone=row["timezone"],
            status=MemoryFactStatus(row["status"]),
            object_hash=row["object_hash"],
            extraction_model=row["extraction_model"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            sources=self._sources(object_id) if include_sources else (),
        )


class DiaryMemoryService:
    def __init__(
        self,
        store: DiaryMemoryStore,
        *,
        vault_id: str,
        extractor: DiaryMemoryExtractor,
        timezone_name: str = "Asia/Shanghai",
        extraction_model: str | None = None,
    ) -> None:
        self.store = store
        self.vault_id = vault_id
        self.extractor = extractor
        self.timezone_name = timezone_name
        self.extraction_model = extraction_model

    def close(self) -> None:
        self.store.close()

    async def archive_chat_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        agent_run_id: str,
        user_question: str,
        assistant_answer: str,
        occurred_at: str,
        markdown_path: str | None,
    ) -> DiaryMemoryArchiveResult:
        diary_text = "\n".join(
            [
                f"用户问题：{user_question}",
                f"桌宠回答：{assistant_answer}",
            ]
        )
        extracted = await self.extractor.extract(
            diary_text,
            memory_date=_date_part(occurred_at),
            source_path=markdown_path,
        )
        object_ids: list[str] = []
        for item in extracted:
            source = DiaryMemoryObjectSource(
                object_id="",
                source_type="chat_exchange",
                source_id=agent_run_id,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                agent_run_id=agent_run_id,
                markdown_path=markdown_path,
            )
            record = self.store.insert_object(
                vault_id=self.vault_id,
                extracted=item,
                occurred_at=occurred_at,
                timezone=self.timezone_name,
                source=source,
                extraction_model=self.extraction_model,
                memory_type=item.type,
            )
            if record is not None:
                object_ids.append(record.id)
        return DiaryMemoryArchiveResult(
            objects_seen=len(extracted),
            objects_written=len(object_ids),
            object_ids=tuple(object_ids),
        )

    def search(self, filters: DiaryMemorySearch) -> list[DiaryMemoryObjectRecord]:
        return self.store.search(filters, vault_id=self.vault_id)

    def get(self, object_id: str) -> DiaryMemoryObjectRecord:
        return self.store.get(object_id)


def diary_records_to_search_results(records: Iterable[DiaryMemoryObjectRecord]):
    from app.models.api import MemorySearchResult

    return [
        MemorySearchResult(
            note_id=record.id,
            chunk_id=record.id,
            relative_path=f"DiaryMemory/{record.id}",
            title="结构化日记记忆",
            heading=record.topic or record.type,
            snippet=_record_snippet(record),
            score=record.importance + record.confidence,
            source_scope="diary_objects",
            retrieval_mode="diary_object",
        )
        for record in records
    ]


def _record_snippet(record: DiaryMemoryObjectRecord) -> str:
    details = []
    if record.emotion:
        details.append(f"emotion={record.emotion}")
    if record.people:
        details.append(f"people={', '.join(record.people)}")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"{record.summary}{suffix}"


def _object_hash(
    *,
    vault_id: str,
    memory_type: str,
    summary: str,
    topic: str,
    emotion: str,
    people: tuple[str, ...],
    keywords: tuple[str, ...],
    source_id: str,
) -> str:
    normalized = "\n".join(
        [
            vault_id.strip(),
            memory_type.casefold().strip(),
            summary.casefold().strip(),
            topic.casefold().strip(),
            emotion.casefold().strip(),
            ",".join(item.casefold().strip() for item in people),
            ",".join(item.casefold().strip() for item in keywords),
            source_id.strip(),
        ]
    )
    return sha256_hex(normalized)


def _json_list(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _json_list_value(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _to_fts_query(query: str) -> str:
    terms = [term.strip('"') for term in query.split() if term.strip()]
    return " OR ".join(f'"{term.replace(chr(34), chr(34) + chr(34))}"' for term in terms) or '""'


def _like_pattern(query: str) -> str:
    escaped = query.replace("~", "~~").replace("%", "~%").replace("_", "~_")
    return f"%{escaped}%"


def _date_part(value: str) -> str | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


def _safe_memory_type(value: str | None) -> str | None:
    normalized = (value or DEFAULT_DIARY_MEMORY_TYPE).strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in ALLOWED_DIARY_MEMORY_TYPES:
        return normalized
    return None
