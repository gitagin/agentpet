from __future__ import annotations

import sqlite3
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from app.models.common import new_id
from app.services.memory import SafeMarkdownWriter
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


DEFAULT_CHAT_MEMORY_TIMEZONE = "Asia/Shanghai"
WEEKDAY_NAMES = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


@dataclass(frozen=True)
class ChatAutoMemoryEntry:
    id: str
    conversation_id: str
    user_message_id: str
    assistant_message_id: str
    agent_run_id: str
    entry_hash: str
    memory_date: str
    memory_time: str
    timezone: str
    markdown_path: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChatAutoMemoryWriteResult:
    entry: ChatAutoMemoryEntry
    written: bool
    index_job_id: str | None = None


class ChatAutoMemoryStore:
    def __init__(self, db: str | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def get_by_agent_run_id(self, agent_run_id: str) -> ChatAutoMemoryEntry | None:
        row = self.conn.execute(
            "SELECT * FROM daily_chat_memory_entries WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()
        return self._map(row) if row else None

    def insert(self, entry: ChatAutoMemoryEntry) -> ChatAutoMemoryEntry:
        self.conn.execute(
            """
            INSERT INTO daily_chat_memory_entries (
                id, conversation_id, user_message_id, assistant_message_id,
                agent_run_id, entry_hash, memory_date, memory_time, timezone,
                markdown_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.conversation_id,
                entry.user_message_id,
                entry.assistant_message_id,
                entry.agent_run_id,
                entry.entry_hash,
                entry.memory_date,
                entry.memory_time,
                entry.timezone,
                entry.markdown_path,
                entry.created_at,
                entry.updated_at,
            ),
        )
        self.conn.commit()
        return entry

    def _map(self, row: sqlite3.Row) -> ChatAutoMemoryEntry:
        return ChatAutoMemoryEntry(
            id=row["id"],
            conversation_id=row["conversation_id"],
            user_message_id=row["user_message_id"],
            assistant_message_id=row["assistant_message_id"],
            agent_run_id=row["agent_run_id"],
            entry_hash=row["entry_hash"],
            memory_date=row["memory_date"],
            memory_time=row["memory_time"],
            timezone=row["timezone"],
            markdown_path=row["markdown_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ChatAutoMemoryService:
    def __init__(
        self,
        store: ChatAutoMemoryStore,
        writer: SafeMarkdownWriter,
        *,
        timezone_name: str = DEFAULT_CHAT_MEMORY_TIMEZONE,
        now_provider: Callable[[], datetime] | None = None,
        index_refresh: Callable[[str], str | None] | None = None,
    ):
        self.store = store
        self.writer = writer
        self.timezone_name = timezone_name
        self.timezone = ZoneInfo(timezone_name)
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))
        self.index_refresh = index_refresh

    def close(self) -> None:
        self.store.close()

    def append_chat_exchange(
        self,
        *,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        agent_run_id: str,
        user_question: str,
        assistant_answer: str,
    ) -> ChatAutoMemoryWriteResult:
        existing = self.store.get_by_agent_run_id(agent_run_id)
        if existing is not None:
            return ChatAutoMemoryWriteResult(entry=existing, written=False)

        local_now = self._local_now()
        memory_date = local_now.date().isoformat()
        memory_time = local_now.strftime("%H:%M:%S")
        markdown_path = self.daily_path(local_now)
        entry_hash = self.entry_hash(
            agent_run_id=agent_run_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            user_question=user_question,
            assistant_answer=assistant_answer,
        )
        now = utc_now_iso()
        entry = ChatAutoMemoryEntry(
            id=new_id(),
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=agent_run_id,
            entry_hash=entry_hash,
            memory_date=memory_date,
            memory_time=memory_time,
            timezone=self.timezone_name,
            markdown_path=markdown_path,
            created_at=now,
            updated_at=now,
        )
        markdown = self._entry_markdown(
            entry=entry,
            user_question=user_question,
            assistant_answer=assistant_answer,
        )
        if self.writer.current_hash(markdown_path) is None:
            markdown = f"# {memory_date} 聊天记忆\n\n{markdown}"
        self.writer.append(markdown_path, markdown)
        stored = self.store.insert(entry)
        index_job_id = self.index_refresh(markdown_path) if self.index_refresh else None
        return ChatAutoMemoryWriteResult(entry=stored, written=True, index_job_id=index_job_id)

    def daily_path(self, local_time: datetime) -> str:
        week_number, week_start, week_end = self._month_week_segment(local_time.date())
        weekday_name = WEEKDAY_NAMES[local_time.weekday()]
        return (
            "Memories/Daily/"
            f"{local_time.year:04d}/"
            f"{local_time.month:02d}/"
            f"第{week_number}周_{week_start:%m-%d}至{week_end:%m-%d}/"
            f"{weekday_name}/"
            f"{local_time.date().isoformat()}.md"
        )

    def _month_week_segment(self, current_date: date) -> tuple[int, date, date]:
        month_end = current_date.replace(day=monthrange(current_date.year, current_date.month)[1])
        week_number = ((current_date.day - 1) // 7) + 1
        week_start_day = ((week_number - 1) * 7) + 1
        week_end_day = min(week_start_day + 6, month_end.day)
        week_start = current_date.replace(day=week_start_day)
        week_end = current_date.replace(day=week_end_day)
        return week_number, week_start, week_end

    def entry_hash(
        self,
        *,
        agent_run_id: str,
        user_message_id: str,
        assistant_message_id: str,
        user_question: str,
        assistant_answer: str,
    ) -> str:
        normalized = "\n".join(
            [
                agent_run_id.strip(),
                user_message_id.strip(),
                assistant_message_id.strip(),
                user_question.strip(),
                assistant_answer.strip(),
            ]
        )
        return sha256_hex(normalized)

    def _local_now(self) -> datetime:
        current = self.now_provider()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(self.timezone)

    def _entry_markdown(
        self,
        *,
        entry: ChatAutoMemoryEntry,
        user_question: str,
        assistant_answer: str,
    ) -> str:
        return "\n".join(
            [
                f"## {entry.memory_time}",
                "",
                f"- 用户问题：{self._single_line(user_question)}",
                f"- 桌宠回答：{self._single_line(assistant_answer)}",
                f"- conversation_id：`{entry.conversation_id}`",
                f"- user_message_id：`{entry.user_message_id}`",
                f"- assistant_message_id：`{entry.assistant_message_id}`",
                f"- agent_run_id：`{entry.agent_run_id}`",
                "",
            ]
        )

    def _single_line(self, value: str) -> str:
        return " ".join(value.strip().split())
