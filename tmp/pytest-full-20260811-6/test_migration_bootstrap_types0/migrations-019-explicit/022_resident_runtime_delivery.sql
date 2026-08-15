PRAGMA foreign_keys = ON;

-- The operating system notification API is outside the SQLite transaction.
-- This table records the local dispatch decision and its best-effort receipt
-- so a restart can distinguish an unattempted reminder from an unknown result.
CREATE TABLE IF NOT EXISTS reminder_delivery_attempts (
    attempt_id TEXT PRIMARY KEY,
    reminder_id TEXT NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    trigger_at TEXT NOT NULL,
    dispatch_kind TEXT NOT NULL CHECK (dispatch_kind IN ('automatic', 'manual')),
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN ('reserved', 'display_invoked', 'unknown_after_crash', 'unsupported', 'failed')
    ),
    reserved_at TEXT NOT NULL,
    display_invoked_at TEXT,
    result_code TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_reminder_delivery_automatic_trigger
ON reminder_delivery_attempts(reminder_id, trigger_at)
WHERE dispatch_kind = 'automatic';

CREATE INDEX IF NOT EXISTS idx_reminder_delivery_status
ON reminder_delivery_attempts(status, reserved_at);

CREATE INDEX IF NOT EXISTS idx_reminder_delivery_reminder
ON reminder_delivery_attempts(reminder_id, trigger_at, created_at);
