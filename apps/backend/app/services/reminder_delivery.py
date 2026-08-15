from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models.common import new_id
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


class ReminderDeliveryError(Exception):
    """Base error for the local notification delivery ledger."""


class ReminderDeliveryNotFound(ReminderDeliveryError):
    pass


class ReminderDeliveryValidationError(ReminderDeliveryError):
    pass


@dataclass(frozen=True)
class DeliveryAttempt:
    attempt_id: str
    reminder_id: str
    trigger_at: str
    dispatch_kind: str
    idempotency_key: str
    status: str
    reserved_at: str
    display_invoked_at: str | None
    result_code: str | None
    error: str | None
    created_at: str
    updated_at: str

    def as_dict(self, *, duplicate: bool = False) -> dict[str, object]:
        return {
            "attempt_id": self.attempt_id,
            "reminder_id": self.reminder_id,
            "trigger_at": self.trigger_at,
            "dispatch_kind": self.dispatch_kind,
            "idempotency_key": self.idempotency_key,
            "status": self.status,
            "reserved_at": self.reserved_at,
            "display_invoked_at": self.display_invoked_at,
            "result_code": self.result_code,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "duplicate": duplicate,
        }


class ReminderDeliveryService:
    """SQLite authority for the non-transactional OS notification boundary.

    A reservation is committed before Electron invokes the operating-system
    notification API.  A later receipt records only that the display call was
    invoked; it does not claim that the user saw or read the notification.
    """

    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def reserve(
        self,
        reminder_id: str,
        trigger_at: str,
        *,
        idempotency_key: str,
        dispatch_kind: str = "automatic",
    ) -> tuple[DeliveryAttempt, bool]:
        reminder_id = self._required_token(reminder_id, "reminder_id")
        trigger_at = self._required_token(trigger_at, "trigger_at")
        idempotency_key = self._required_token(idempotency_key, "idempotency_key")
        if dispatch_kind not in {"automatic", "manual"}:
            raise ReminderDeliveryValidationError("unsupported dispatch kind")
        if self.conn.execute("SELECT 1 FROM reminders WHERE id = ?", (reminder_id,)).fetchone() is None:
            raise ReminderDeliveryNotFound(reminder_id)

        now = utc_now_iso()
        existing = self._find_existing_reservation(
            reminder_id,
            trigger_at,
            idempotency_key=idempotency_key,
            dispatch_kind=dispatch_kind,
        )
        if existing is not None:
            attempt, _ = existing
            return attempt, True

        attempt_id = new_id()
        try:
            with self.conn:
                self.conn.execute(
                    """
                    INSERT INTO reminder_delivery_attempts (
                        attempt_id, reminder_id, trigger_at, dispatch_kind,
                        idempotency_key, status, reserved_at, display_invoked_at,
                        result_code, error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'reserved', ?, NULL, NULL, NULL, ?, ?)
                    """,
                    (
                        attempt_id,
                        reminder_id,
                        trigger_at,
                        dispatch_kind,
                        idempotency_key,
                        now,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            # Concurrent renderer polls converge on the committed row.  No
            # caller is allowed to issue a second OS dispatch for that key.
            existing = self._find_existing_reservation(
                reminder_id,
                trigger_at,
                idempotency_key=idempotency_key,
                dispatch_kind=dispatch_kind,
            )
            if existing is None:
                raise
            attempt, _ = existing
            return attempt, True

        row = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        assert row is not None
        return self._map(row), False

    def mark_display_invoked(
        self,
        attempt_id: str,
        *,
        result_code: str,
        error: str | None = None,
    ) -> DeliveryAttempt:
        attempt_id = self._required_token(attempt_id, "attempt_id")
        if result_code not in {"shown", "unsupported", "failed"}:
            raise ReminderDeliveryValidationError("unsupported display result")
        now = utc_now_iso()
        status = "display_invoked" if result_code == "shown" else result_code
        with self.conn:
            self.conn.execute(
                """
                UPDATE reminder_delivery_attempts
                SET status = ?, display_invoked_at = ?, result_code = ?, error = ?, updated_at = ?
                WHERE attempt_id = ? AND status = 'reserved'
                """,
                (status, now, result_code, error, now, attempt_id),
            )
        row = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise ReminderDeliveryNotFound(attempt_id)
        return self._map(row)

    def recover_reserved(self, *, reason: str = "process_restart") -> int:
        reason = self._required_token(reason, "reason")[:120]
        now = utc_now_iso()
        with self.conn:
            cursor = self.conn.execute(
                """
                UPDATE reminder_delivery_attempts
                SET status = 'unknown_after_crash', result_code = 'unknown_after_crash',
                    error = ?, updated_at = ?
                WHERE status = 'reserved'
                """,
                (reason, now),
            )
        return int(cursor.rowcount)

    def get(self, attempt_id: str) -> DeliveryAttempt:
        attempt_id = self._required_token(attempt_id, "attempt_id")
        row = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE attempt_id = ?", (attempt_id,)
        ).fetchone()
        if row is None:
            raise ReminderDeliveryNotFound(attempt_id)
        return self._map(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> DeliveryAttempt:
        idempotency_key = self._required_token(idempotency_key, "idempotency_key")
        row = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            raise ReminderDeliveryNotFound(idempotency_key)
        return self._map(row)

    def find_reservation(
        self,
        reminder_id: str,
        trigger_at: str,
        *,
        idempotency_key: str,
        dispatch_kind: str,
    ) -> tuple[DeliveryAttempt, bool] | None:
        reminder_id = self._required_token(reminder_id, "reminder_id")
        trigger_at = self._required_token(trigger_at, "trigger_at")
        idempotency_key = self._required_token(idempotency_key, "idempotency_key")
        if dispatch_kind not in {"automatic", "manual"}:
            raise ReminderDeliveryValidationError("unsupported dispatch kind")

        return self._find_existing_reservation(
            reminder_id,
            trigger_at,
            idempotency_key=idempotency_key,
            dispatch_kind=dispatch_kind,
        )

    def _find_existing_reservation(
        self,
        reminder_id: str,
        trigger_at: str,
        *,
        idempotency_key: str,
        dispatch_kind: str,
    ) -> tuple[DeliveryAttempt, bool] | None:
        keyed = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if keyed is not None:
            attempt = self._map(keyed)
            if (
                attempt.reminder_id != reminder_id
                or attempt.trigger_at != trigger_at
                or attempt.dispatch_kind != dispatch_kind
            ):
                raise ReminderDeliveryValidationError("idempotency key payload conflict")
            return attempt, False
        if dispatch_kind != "automatic":
            return None

        automatic = self.conn.execute(
            """
            SELECT * FROM reminder_delivery_attempts
            WHERE reminder_id = ? AND trigger_at = ? AND dispatch_kind = 'automatic'
            ORDER BY created_at DESC LIMIT 1
            """,
            (reminder_id, trigger_at),
        ).fetchone()
        if automatic is None:
            return None
        return self._map(automatic), True

    def list_reserved(self) -> list[DeliveryAttempt]:
        rows = self.conn.execute(
            "SELECT * FROM reminder_delivery_attempts WHERE status = 'reserved' ORDER BY reserved_at, attempt_id"
        ).fetchall()
        return [self._map(row) for row in rows]

    def list_unknown_by_reason(self, reason: str) -> list[DeliveryAttempt]:
        reason = self._required_token(reason, "reason")[:120]
        rows = self.conn.execute(
            """
            SELECT * FROM reminder_delivery_attempts
            WHERE status = 'unknown_after_crash' AND error = ?
            ORDER BY reserved_at, attempt_id
            """,
            (reason,),
        ).fetchall()
        return [self._map(row) for row in rows]

    @staticmethod
    def _required_token(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 512:
            raise ReminderDeliveryValidationError(f"{field} is required")
        return value.strip()

    @staticmethod
    def _map(row: sqlite3.Row) -> DeliveryAttempt:
        return DeliveryAttempt(
            attempt_id=row["attempt_id"],
            reminder_id=row["reminder_id"],
            trigger_at=row["trigger_at"],
            dispatch_kind=row["dispatch_kind"],
            idempotency_key=row["idempotency_key"],
            status=row["status"],
            reserved_at=row["reserved_at"],
            display_invoked_at=row["display_invoked_at"],
            result_code=row["result_code"],
            error=row["error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
