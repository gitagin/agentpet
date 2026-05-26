from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models.common import new_id
from app.utils.time import utc_now_iso


@dataclass(frozen=True)
class AuditLogEntry:
    id: str
    actor: str
    action: str
    target_path: str | None
    result: str
    reason: str | None
    created_at: str


class AuditLogService:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def record(
        self,
        *,
        actor: str,
        action: str,
        result: str,
        target_path: str | None = None,
        reason: str | None = None,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            id=new_id(),
            actor=actor,
            action=action,
            target_path=target_path,
            result=result,
            reason=reason,
            created_at=utc_now_iso(),
        )
        self.conn.execute(
            """
            INSERT INTO audit_logs(id, actor, action, target_path, result, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.id,
                entry.actor,
                entry.action,
                entry.target_path,
                entry.result,
                entry.reason,
                entry.created_at,
            ),
        )
        self.conn.commit()
        return entry

    def list_recent(self, limit: int = 10) -> list[AuditLogEntry]:
        rows = self.conn.execute(
            """
            SELECT id, actor, action, target_path, result, reason, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._map(row) for row in rows]

    @staticmethod
    def _map(row: sqlite3.Row) -> AuditLogEntry:
        return AuditLogEntry(
            id=str(row["id"]),
            actor=str(row["actor"]),
            action=str(row["action"]),
            target_path=str(row["target_path"]) if row["target_path"] is not None else None,
            result=str(row["result"]),
            reason=str(row["reason"]) if row["reason"] is not None else None,
            created_at=str(row["created_at"]),
        )
