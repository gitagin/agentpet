from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.storage.database import Database
from app.evals.soak_snapshot import collect_soak_snapshot


def test_empty_database_snapshot_reports_explicit_sqlite_fallback(tmp_path: Path) -> None:
    database = migrate_db(tmp_path / "state.sqlite3")
    snapshot = collect_soak_snapshot(database, since="2026-08-10T00:00:00+00:00")
    assert snapshot["unexplained_action_count"] == 0
    assert snapshot["post_reply_backlog_count"] == 0
    assert snapshot["graph_projection_mode"] in {"sqlite_fallback", "sqlite_only", "kuzu"}
    assert "recovery_durations_ms" in snapshot


def test_snapshot_connection_is_read_only(tmp_path: Path) -> None:
    database = migrate_db(tmp_path / "state.sqlite3")
    with Database(database).session(read_only=True) as conn:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE should_not_exist (id INTEGER)")


def test_snapshot_counts_metric_failures_and_recovery_durations(tmp_path: Path) -> None:
    database = migrate_db(tmp_path / "state.sqlite3")
    with Database(database).connect() as conn:
        conn.execute(
            """
            INSERT INTO product_metric_events(
                id, event_version, event_type, idempotency_key, payload_hash,
                subject_hash, value, dimensions_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "metric-1",
                "local-impact.v1",
                "sidecar_ready",
                "metric-key-1",
                "hash-1",
                None,
                1250,
                "{}",
                "2026-08-10T01:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO product_metric_events(
                id, event_version, event_type, idempotency_key, payload_hash,
                subject_hash, value, dimensions_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "metric-2",
                "local-impact.v1",
                "wiki_lint_result",
                "metric-key-2",
                "hash-2",
                None,
                1,
                json.dumps({"status": "failed"}),
                "2026-08-10T01:01:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO product_metric_events(
                id, event_version, event_type, idempotency_key, payload_hash,
                subject_hash, value, dimensions_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "metric-3",
                "local-impact.v1",
                "duplicate_effect_detected",
                "metric-key-3",
                "hash-3",
                "subject-hash-3",
                1,
                "{}",
                "2026-08-10T01:02:00+00:00",
            ),
        )
        conn.commit()
    snapshot = collect_soak_snapshot(database, since="2026-08-10T00:00:00+00:00")
    assert snapshot["recovery_durations_ms"] == [1250.0]
    assert snapshot["metric_event_counts"]["wiki_lint_failed"] == 1
    assert snapshot["duplicate_business_effect_count"] == 1
