from __future__ import annotations

import hashlib
import re
import sqlite3
from pathlib import PurePath
from typing import Any

from app.config import Settings
from app.models.api import (
    DiagnosticsAuditLogSummary,
    DiagnosticsDatabaseStatus,
    DiagnosticsExportResponse,
    DiagnosticsIndexJobSummary,
    DiagnosticsVaultStatus,
)
from app.services.settings import SettingsStore
from app.services.tasks import utc_now_iso
from app.storage.database import Database


SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)\bauthorization\s*[:=]\s*(?:bearer\s+)?[^\s,;]+"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/\-=]+"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"\bsk-[A-Za-z0-9._\-]{8,}\b"),
]
WINDOWS_ABSOLUTE_PATH_RE = re.compile(
    r"\b[A-Za-z]:\\.*?(?=(?:\s+(?:with|and|api[_-]?key|token|authorization|bearer)\b)|[,;]|$)",
    re.IGNORECASE,
)
POSIX_ABSOLUTE_PATH_RE = re.compile(
    r"(?<!\w)/(?:[^,;]+/)+.*?(?=(?:\s+(?:with|and|api[_-]?key|token|authorization|bearer)\b)|[,;]|$)",
    re.IGNORECASE,
)
UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class DiagnosticsExporter:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def export(self, active_vault_id: str | None = None) -> DiagnosticsExportResponse:
        with self.database.connect() as conn:
            database_status = self._database_status(conn)
            vault_status = self._vault_status(conn, active_vault_id)
            recent_index_jobs = self._recent_index_jobs(conn)
            recent_audit_logs = self._recent_audit_logs(conn)
        settings_store = SettingsStore(self.database.path)
        try:
            model_configured = settings_store.get_model_key_status().configured
        finally:
            settings_store.close()

        return DiagnosticsExportResponse(
            generated_at=utc_now_iso(),
            app={
                "name": self.settings.app_name,
                "version": self.settings.app_version,
                "environment": self.settings.environment,
            },
            database=database_status,
            vault=vault_status,
            model_configured=model_configured,
            recent_index_jobs=recent_index_jobs,
            recent_audit_logs=recent_audit_logs,
        )

    def _database_status(self, conn: sqlite3.Connection) -> DiagnosticsDatabaseStatus:
        quick_check = _redact_text(str(conn.execute("PRAGMA quick_check").fetchone()[0]))
        migration_versions = [
            _redact_text(str(row["version"]))
            for row in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        table_counts = {
            table: _safe_count(conn, table)
            for table in ("vaults", "notes", "note_chunks", "index_jobs", "audit_logs", "tasks")
        }
        return DiagnosticsDatabaseStatus(
            path_configured=self.settings.database_path is not None,
            reachable=True,
            quick_check=quick_check,
            migration_versions=migration_versions,
            table_counts=table_counts,
        )

    def _vault_status(
        self,
        conn: sqlite3.Connection,
        active_vault_id: str | None,
    ) -> DiagnosticsVaultStatus:
        rows = conn.execute(
            "SELECT id, name FROM vaults ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
        return DiagnosticsVaultStatus(
            configured=bool(rows),
            active_vault_id=_diagnostic_id(active_vault_id) if active_vault_id in {row["id"] for row in rows} else None,
            vault_count=len(rows),
            names=[_redact_text(str(row["name"])) for row in rows[:5]],
        )

    def _recent_index_jobs(self, conn: sqlite3.Connection) -> list[DiagnosticsIndexJobSummary]:
        rows = conn.execute(
            """
            SELECT id, vault_id, type, status, files_seen, files_indexed, error, created_at, updated_at
            FROM index_jobs
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()
        return [
            DiagnosticsIndexJobSummary(
                id=str(row["id"]),
                vault_id=_diagnostic_id(str(row["vault_id"])),
                type=_redact_text(str(row["type"])),
                status=_redact_text(str(row["status"])),
                files_seen=int(row["files_seen"]),
                files_indexed=int(row["files_indexed"]),
                error=_redact_optional(row["error"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def _recent_audit_logs(self, conn: sqlite3.Connection) -> list[DiagnosticsAuditLogSummary]:
        rows = conn.execute(
            """
            SELECT id, actor, action, target_path, result, reason, created_at
            FROM audit_logs
            ORDER BY created_at DESC
            LIMIT 10
            """
        ).fetchall()
        return [
            DiagnosticsAuditLogSummary(
                id=str(row["id"]),
                actor=_redact_text(str(row["actor"])),
                action=_redact_text(str(row["action"])),
                target_path_present=row["target_path"] is not None,
                target_name=_target_name(row["target_path"]),
                result=_redact_text(str(row["result"])),
                reason=_redact_optional(row["reason"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]


def _safe_count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    except sqlite3.Error:
        return 0


def _target_name(target_path: Any) -> str | None:
    if target_path is None:
        return None
    text = _redact_text(str(target_path))
    if text == "[REDACTED_PATH]":
        return "[REDACTED_PATH]"
    name = PurePath(text.replace("\\", "/")).name
    return _redact_text(name) if name else None


def _redact_optional(value: Any) -> str | None:
    if value is None:
        return None
    return _redact_text(str(value))


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub(lambda match: _redact_match(match.group(0)), redacted)
    redacted = WINDOWS_ABSOLUTE_PATH_RE.sub("[REDACTED_PATH]", redacted)
    redacted = POSIX_ABSOLUTE_PATH_RE.sub("[REDACTED_PATH]", redacted)
    redacted = UUID_RE.sub("[REDACTED_ID]", redacted)
    return redacted


def _redact_match(value: str) -> str:
    head, separator, _tail = value.partition(":")
    if separator and head.strip().lower() == "authorization":
        return f"{head}{separator} [REDACTED]"
    key_match = re.match(r"(?i)^(\s*(?:api[_-]?key|token|secret|password)\s*[:=])", value)
    if key_match:
        return f"{key_match.group(1)}[REDACTED]"
    if value.lower().startswith("bearer "):
        return "Bearer [REDACTED]"
    return "[REDACTED]"


def _diagnostic_id(value: str | None) -> str | None:
    if not value:
        return None
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"id:{digest}"
