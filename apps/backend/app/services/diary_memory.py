from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from app.models.common import new_id
from app.models.enums import MemoryFactStatus
from app.services.diary_memory_extractor import ALLOWED_DIARY_MEMORY_TYPES, DiaryMemoryExtractor, DiaryMemoryObject
from app.storage.database import open_database_connection
from app.utils.hash import sha256_hex
from app.utils.time import local_timezone_name
from app.utils.time import utc_now_iso


DEFAULT_DIARY_MEMORY_TYPE = "event"


def chat_exchange_diary_text(user_question: str, assistant_answer: str) -> str:
    """The one text both the archiver and the pre-check extract from.

    They used to build their own strings -- English labels in the pre-check,
    Chinese ones in the archiver -- so the "is there anything worth archiving?"
    question was asked about a *different* input than the archiving itself, and
    the two object counts diverged far more easily than model noise alone would
    explain.  One builder removes that whole class of disagreement.
    """
    return "\n".join(
        [
            f"用户问题：{user_question}",
            f"桌宠回答：{assistant_answer}",
        ]
    )


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
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run a whole extracted set as one all-or-nothing unit of work.

        Effect verification for structured diary memory asks a single question
        the database can answer on its own: does this agent run own any diary
        object?  That is only equivalent to "the effect is complete" when a
        partial set cannot exist.  Previously the set was written object by
        object, so completeness had to be checked against a count agreed before
        the write -- and that count came from a second, independent model call,
        which is exactly how production ended up with
        ``structured_diary_effect_count_mismatch`` on perfectly good exchanges.
        Committing the set atomically removes the need for that count.

        Implemented so the caller may already hold a transaction on this
        connection (a batch job, a compound write, a test that wraps writes):
        inside a caller's transaction a SAVEPOINT simply joins it and lets the
        caller decide.  With no caller transaction the batch opens with
        ``BEGIN IMMEDIATE`` rather than a savepoint, because the batch reads
        before it writes (dedupe by content hash, then insert) and a deferred
        transaction's read snapshot goes stale the moment another connection
        commits -- WAL then fails the insert immediately with "database is
        locked" and ``busy_timeout`` is never consulted.
        """
        if not self.conn.in_transaction:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()
            return

        savepoint = f"diary_memory_batch_{new_id().replace('-', '')[:12]}"
        self.conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except BaseException:
            self.conn.execute(f"ROLLBACK TO {savepoint}")
            self.conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            self.conn.execute(f"RELEASE {savepoint}")

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
        commit: bool = True,
    ) -> DiaryMemoryObjectRecord | None:
        """Store one extracted object, its FTS row and its source link.

        One object is always all-or-nothing.  Pass ``commit=False`` to join a
        caller-owned transaction (see :meth:`transaction`) so a whole extracted
        set becomes all-or-nothing too.
        """
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
        people_json = _dumps_list(extracted.people)
        keywords_json = _dumps_list(extracted.keywords)
        pending = nullcontext() if commit is False else self.conn
        with pending:
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
            from app.repositories.storage import _bigram_cjk

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
                    _bigram_cjk(extracted.summary),
                    _bigram_cjk(extracted.topic or ""),
                    _bigram_cjk(extracted.emotion or ""),
                    _bigram_cjk(" ".join(extracted.people)),
                    _bigram_cjk(" ".join(extracted.keywords)),
                ),
            )
            self._insert_source(object_id, source)
        return self.get(object_id)

    def search(self, filters: DiaryMemorySearch, *, vault_id: str) -> list[DiaryMemoryObjectRecord]:
        from app.repositories.storage import _expanded_query_terms, _to_fts_queries

        query_text = filters.query.strip()
        clauses = ["o.vault_id = ?"]
        params: list[object] = [vault_id]
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
        limit_value = max(1, min(filters.top_k, 50))

        def run(
            *,
            extra_join: str,
            extra_clause: str,
            extra_params: list[object],
            rank_expr: str,
        ) -> list[DiaryMemoryObjectRecord]:
            where = " AND ".join([*clauses, extra_clause] if extra_clause else clauses)
            rows = self.conn.execute(
                f"""
                SELECT o.*, {rank_expr} AS rank
                FROM diary_memory_objects o
                {extra_join}
                WHERE {where}
                ORDER BY
                    CASE o.status WHEN 'active' THEN 0 WHEN 'candidate' THEN 1 WHEN 'quarantined' THEN 2 ELSE 3 END,
                    o.importance DESC,
                    o.confidence DESC,
                    rank,
                    o.occurred_at DESC
                LIMIT ?
                """,
                (*params, *extra_params, limit_value),
            ).fetchall()
            return [self._map(row, include_sources=False) for row in rows]

        if not query_text:
            return run(extra_join="", extra_clause="", extra_params=[], rank_expr="0")

        # FTS 阶梯：与笔记通道共用同一查询构造器（bigram + 引号转义 + AND→OR 松弛），
        # 消除两通道分词不一致导致的召回不对称。
        for fts_query in _to_fts_queries(query_text):
            results = run(
                extra_join="JOIN diary_memory_object_fts ON diary_memory_object_fts.object_id = o.id",
                # FTS5 的 MATCH 左操作数必须是表的真实名称（不能是 JOIN 别名）。
                extra_clause="diary_memory_object_fts MATCH ?",
                extra_params=[fts_query],
                rank_expr="bm25(diary_memory_object_fts)",
            )
            if results:
                return results

        # LIKE 兜底：单字 CJK 查询、混合脚本子串（"python教程"中的"教程"）等
        # 不进 FTS 索引的情况，与笔记通道的 LIKE 兜底对齐，保证召回对称。
        like_terms: list[str] = []
        for term in (query_text, *_expanded_query_terms(query_text)):
            if term and term not in like_terms:
                like_terms.append(term)
        for term in like_terms:
            results = run(
                extra_join="",
                extra_clause=(
                    "(COALESCE(o.summary, '') || ' ' || COALESCE(o.topic, '') || ' ' || "
                    "COALESCE(o.emotion, '') || ' ' || COALESCE(o.people_json, '') || ' ' || "
                    "COALESCE(o.keywords_json, '')) LIKE ? ESCAPE '~'"
                ),
                extra_params=[_like_pattern(term)],
                rank_expr="0",
            )
            if results:
                return results
        return []

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
        timezone_name: str = local_timezone_name(),
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
        diary_text = chat_exchange_diary_text(user_question, assistant_answer)
        extracted = await self.extractor.extract(
            diary_text,
            memory_date=_date_part(occurred_at),
            source_path=markdown_path,
        )
        object_ids: list[str] = []
        # 整批一个事务:中途失败要么全落库、要么全不落库。部分落库会让"效果是否
        # 完整"无法只靠数据库判断,只能去比对一个更不可靠的模型预估条数。
        with self.store.transaction():
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
                    commit=False,
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
            content_hash=record.object_hash,
            source_scope="diary_objects",
            retrieval_mode="diary_object",
            retrieval_channels=["diary"],
            lifecycle_status=record.status.value,
        )
        for record in records
        if record.status == MemoryFactStatus.ACTIVE
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
            # insert_object 对 topic/emotion 采用 or None 的容忍路径（写入 NULL），
            # 哈希必须同样容忍 None，否则 topic=None 的对象会让整个归档崩溃。
            (topic or "").casefold().strip(),
            (emotion or "").casefold().strip(),
            ",".join(item.casefold().strip() for item in people),
            ",".join(item.casefold().strip() for item in keywords),
            source_id.strip(),
        ]
    )
    return sha256_hex(normalized)


def _dumps_list(values: tuple[str, ...]) -> str:
    return json.dumps(list(values), ensure_ascii=False, separators=(",", ":"))


def _json_list_value(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


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
