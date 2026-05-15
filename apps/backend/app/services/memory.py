from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.models.common import new_id
from app.models.enums import MemoryProposalStatus, MemoryProposalType


class MemoryServiceError(Exception):
    """记忆提案失败的基础异常。"""


class MemoryProposalNotFoundError(MemoryServiceError):
    pass


class MemoryProposalStateError(MemoryServiceError):
    pass


class MemoryConflictError(MemoryServiceError):
    pass


class MarkdownWriteError(MemoryServiceError):
    pass


@dataclass(frozen=True)
class MemoryProposal:
    id: str
    type: MemoryProposalType
    content: str
    target_path: str
    target_content_hash: str | None
    source_message_id: str | None
    status: MemoryProposalStatus
    created_at: str
    updated_at: str
    rejected_reason: str | None = None
    written_path: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class MemoryWriteResult:
    proposal_id: str
    status: MemoryProposalStatus
    written_path: str
    index_job_id: str | None = None


@dataclass(frozen=True)
class MarkdownWriteHooks:
    before_write: Callable[[Path, str], None] | None = None
    after_write: Callable[[Path, str], None] | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def content_hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def content_hash_text(content: str) -> str:
    return content_hash_bytes(content.encode("utf-8"))


class MemoryProposalStore:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._ensure_schema()

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_proposals (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                target_path TEXT NOT NULL,
                target_content_hash TEXT,
                source_message_id TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                rejected_reason TEXT,
                written_path TEXT,
                error TEXT
            )
            """
        )
        self.conn.commit()

    def insert(self, proposal: MemoryProposal) -> MemoryProposal:
        self.conn.execute(
            """
            INSERT INTO memory_proposals (
                id, type, content, target_path, target_content_hash,
                source_message_id, status, created_at, updated_at,
                rejected_reason, written_path, error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.id,
                proposal.type.value,
                proposal.content,
                proposal.target_path,
                proposal.target_content_hash,
                proposal.source_message_id,
                proposal.status.value,
                proposal.created_at,
                proposal.updated_at,
                proposal.rejected_reason,
                proposal.written_path,
                proposal.error,
            ),
        )
        self.conn.commit()
        return proposal

    def get(self, proposal_id: str) -> MemoryProposal:
        row = self.conn.execute(
            "SELECT * FROM memory_proposals WHERE id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            raise MemoryProposalNotFoundError(proposal_id)
        return self._map(row)

    def update_status(
        self,
        proposal_id: str,
        status: MemoryProposalStatus,
        *,
        rejected_reason: str | None = None,
        written_path: str | None = None,
        error: str | None = None,
    ) -> MemoryProposal:
        self.conn.execute(
            """
            UPDATE memory_proposals
            SET status = ?, updated_at = ?, rejected_reason = COALESCE(?, rejected_reason),
                written_path = COALESCE(?, written_path), error = ?
            WHERE id = ?
            """,
            (status.value, utc_now_iso(), rejected_reason, written_path, error, proposal_id),
        )
        self.conn.commit()
        return self.get(proposal_id)

    def list_pending(self) -> list[MemoryProposal]:
        rows = self.conn.execute(
            "SELECT * FROM memory_proposals WHERE status = ? ORDER BY created_at",
            (MemoryProposalStatus.PENDING.value,),
        ).fetchall()
        return [self._map(row) for row in rows]

    def _map(self, row: sqlite3.Row) -> MemoryProposal:
        return MemoryProposal(
            id=row["id"],
            type=MemoryProposalType(row["type"]),
            content=row["content"],
            target_path=row["target_path"],
            target_content_hash=row["target_content_hash"],
            source_message_id=row["source_message_id"],
            status=MemoryProposalStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            rejected_reason=row["rejected_reason"],
            written_path=row["written_path"],
            error=row["error"],
        )


class SafeMarkdownWriter:
    def __init__(self, vault_root: str | Path, hooks: MarkdownWriteHooks | None = None):
        self.vault_root = Path(vault_root).resolve()
        self.hooks = hooks or MarkdownWriteHooks()
        self._locks: dict[Path, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def resolve_markdown_path(self, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise MarkdownWriteError("target_path 必须是知识库根目录内的相对路径")
        target = (self.vault_root / relative_path).resolve()
        try:
            target.relative_to(self.vault_root)
        except ValueError as exc:
            raise MarkdownWriteError("target_path 不能超出知识库根目录") from exc
        if target.suffix.lower() != ".md":
            raise MarkdownWriteError("target_path 必须指向 Markdown 文件")
        hidden_parts = {".obsidian", ".git"}
        if any(part in hidden_parts or part.startswith(".") for part in target.relative_to(self.vault_root).parts):
            raise MarkdownWriteError("不能写入隐藏的知识库路径")
        return target

    def current_hash(self, relative_path: str) -> str | None:
        target = self.resolve_markdown_path(relative_path)
        if not target.exists():
            return None
        return content_hash_bytes(target.read_bytes())

    def append(self, relative_path: str, markdown: str) -> Path:
        target = self.resolve_markdown_path(relative_path)
        with self._lock_for(target):
            existing = target.read_bytes() if target.exists() else b""
            text, newline, final_newline = self._decode_existing(existing)
            separator = "" if not text else (newline if final_newline else newline + newline)
            next_text = f"{text}{separator}{markdown}"
            if not next_text.endswith(newline):
                next_text += newline
            self.write(relative_path, next_text)
            return target

    def write(self, relative_path: str, markdown: str) -> Path:
        target = self.resolve_markdown_path(relative_path)
        with self._lock_for(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            if self.hooks.before_write:
                self.hooks.before_write(target, markdown)
            backup = None
            if target.exists():
                backup = target.with_name(f"{target.name}.bak")
                backup.write_bytes(target.read_bytes())
            fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(markdown)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, target)
            except OSError as exc:
                try:
                    temp_path.unlink(missing_ok=True)
                finally:
                    raise MarkdownWriteError(f"安全写入 Markdown 失败：{exc}") from exc
            if self.hooks.after_write:
                self.hooks.after_write(target, markdown)
            return target

    def _lock_for(self, target: Path) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(target, threading.RLock())

    def _decode_existing(self, data: bytes) -> tuple[str, str, bool]:
        if not data:
            return "", "\n", True
        text = data.decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        return text, newline, text.endswith(("\n", "\r\n"))


class MemoryService:
    def __init__(
        self,
        store: MemoryProposalStore,
        writer: SafeMarkdownWriter,
        *,
        index_refresh: Callable[[str], str | None] | None = None,
    ):
        self.store = store
        self.writer = writer
        self.index_refresh = index_refresh

    def close(self) -> None:
        self.store.close()

    def create_proposal(
        self,
        *,
        type: MemoryProposalType,
        content: str,
        target_path: str,
        source_message_id: str | None = None,
    ) -> MemoryProposal:
        now = utc_now_iso()
        proposal = MemoryProposal(
            id=new_id(),
            type=type,
            content=content,
            target_path=target_path,
            target_content_hash=self.writer.current_hash(target_path),
            source_message_id=source_message_id,
            status=MemoryProposalStatus.PENDING,
            created_at=now,
            updated_at=now,
        )
        return self.store.insert(proposal)

    def confirm_proposal(self, proposal_id: str) -> MemoryWriteResult:
        proposal = self.store.get(proposal_id)
        if proposal.status != MemoryProposalStatus.PENDING:
            raise MemoryProposalStateError(f"记忆提案当前状态为 {proposal.status}")
        current_hash = self.writer.current_hash(proposal.target_path)
        if current_hash != proposal.target_content_hash:
            raise MemoryConflictError("目标文件在提案预览后已发生变化")
        try:
            written_path = self.writer.append(proposal.target_path, proposal.content)
            index_job_id = self.index_refresh(proposal.target_path) if self.index_refresh else None
        except Exception as exc:
            self.store.update_status(proposal_id, MemoryProposalStatus.FAILED, error=str(exc))
            raise
        self.store.update_status(
            proposal_id,
            MemoryProposalStatus.CONFIRMED,
            written_path=str(written_path),
            error=None,
        )
        return MemoryWriteResult(
            proposal_id=proposal_id,
            status=MemoryProposalStatus.CONFIRMED,
            written_path=str(written_path),
            index_job_id=index_job_id,
        )

    def reject_proposal(self, proposal_id: str, reason: str) -> MemoryProposal:
        proposal = self.store.get(proposal_id)
        if proposal.status != MemoryProposalStatus.PENDING:
            raise MemoryProposalStateError(f"记忆提案当前状态为 {proposal.status}")
        return self.store.update_status(
            proposal_id,
            MemoryProposalStatus.REJECTED,
            rejected_reason=reason,
            error=None,
        )

    def list_pending(self) -> list[MemoryProposal]:
        return self.store.list_pending()
