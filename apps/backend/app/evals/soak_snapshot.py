from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from app.storage.database import Database


UNEXPLAINED_ACTION_STATUSES = ("claimed", "executing", "verifying")
BACKLOG_STATUSES = ("pending", "running")


def collect_soak_snapshot(
    database_path: str | Path,
    *,
    since: str,
    now: datetime | None = None,
) -> dict[str, object]:
    observed_at = now or datetime.now(timezone.utc)
    with Database(database_path).session(read_only=True) as conn:
        action_counts = _group_counts(conn, "agent_actions", "status")
        post_reply_counts = _group_counts(conn, "post_reply_memory_jobs", "status")
        index_counts = _group_counts(conn, "index_jobs", "status")
        reminder_counts = _group_counts(conn, "reminders", "status")
        delivery_counts = _group_counts(conn, "reminder_delivery_attempts", "status")
        metric_counts, recovery_durations_ms = _metric_counts(conn, since=since)
        generation = _generation_snapshot(conn, observed_at=observed_at)
        automatic_duplicate_dispatches = _scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM (
                SELECT reminder_id, trigger_at
                FROM reminder_delivery_attempts
                WHERE dispatch_kind = 'automatic'
                GROUP BY reminder_id, trigger_at
                HAVING COUNT(*) > 1
            )
            """,
            table="reminder_delivery_attempts",
        )
        duplicate_effects = metric_counts.get("duplicate_effect_detected", 0)
        sqlite_errors = metric_counts.get("sqlite_locked", 0) + metric_counts.get("sqlite_error", 0)
        return {
            "observed_at": observed_at.isoformat(),
            "action_counts": action_counts,
            "unexplained_action_count": sum(action_counts.get(status, 0) for status in UNEXPLAINED_ACTION_STATUSES),
            "failed_recovery_count": action_counts.get("failed_recovery", 0),
            "post_reply_job_counts": post_reply_counts,
            "post_reply_backlog_count": sum(post_reply_counts.get(status, 0) for status in BACKLOG_STATUSES),
            "post_reply_failed_count": post_reply_counts.get("failed", 0),
            "index_job_counts": index_counts,
            "index_backlog_count": sum(index_counts.get(status, 0) for status in BACKLOG_STATUSES),
            "reminder_counts": reminder_counts,
            "reminder_delivery_counts": delivery_counts,
            "automatic_duplicate_dispatch_count": automatic_duplicate_dispatches,
            "duplicate_business_effect_count": duplicate_effects,
            "sqlite_error_count": sqlite_errors,
            "wiki_lint_failed_count": metric_counts.get("wiki_lint_failed", 0),
            "metric_event_counts": metric_counts,
            "recovery_durations_ms": recovery_durations_ms,
            **generation,
        }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _group_counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    if not _table_exists(conn, table):
        return {}
    rows = conn.execute(
        f'SELECT "{column}" AS value, COUNT(*) AS count FROM "{table}" GROUP BY "{column}"'
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def _scalar(
    conn: sqlite3.Connection,
    query: str,
    params: Sequence[object] = (),
    *,
    table: str,
) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(query, tuple(params)).fetchone()
    return int(row[0] or 0) if row is not None else 0


def _metric_counts(conn: sqlite3.Connection, *, since: str) -> tuple[dict[str, int], list[float]]:
    if not _table_exists(conn, "product_metric_events"):
        return {}, []
    rows = conn.execute(
        """
        SELECT event_type, dimensions_json, COUNT(*) AS count
        FROM product_metric_events
        WHERE created_at >= ?
        GROUP BY event_type, dimensions_json
        """,
        (since,),
    ).fetchall()
    counts: dict[str, int] = {}
    recovery_durations_ms: list[float] = []
    for row in rows:
        event_type = str(row["event_type"])
        count = int(row["count"])
        counts[event_type] = counts.get(event_type, 0) + count
        if event_type == "wiki_lint_result":
            try:
                dimensions = json.loads(str(row["dimensions_json"] or "{}"))
            except json.JSONDecodeError:
                dimensions = {}
            if isinstance(dimensions, dict) and dimensions.get("status") != "passed":
                counts["wiki_lint_failed"] = counts.get("wiki_lint_failed", 0) + count
    duration_rows = conn.execute(
        """
        SELECT value, dimensions_json
        FROM product_metric_events
        WHERE created_at >= ? AND event_type = 'sidecar_ready'
        ORDER BY created_at, id
        """,
        (since,),
    ).fetchall()
    for row in duration_rows:
        raw_value = row["value"]
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = -1.0
        if value < 0:
            try:
                dimensions = json.loads(str(row["dimensions_json"] or "{}"))
                value = float(dimensions.get("duration_ms", -1)) if isinstance(dimensions, dict) else -1.0
            except (TypeError, ValueError, json.JSONDecodeError):
                value = -1.0
        if value >= 0:
            recovery_durations_ms.append(value)
    return counts, recovery_durations_ms


def _generation_snapshot(conn: sqlite3.Connection, *, observed_at: datetime) -> dict[str, object]:
    if not _table_exists(conn, "graph_source_state"):
        return {
            "graph_source_revision": None,
            "graph_projection_revision": None,
            "graph_generation_lag_seconds": None,
            "graph_projection_mode": "sqlite_only",
        }
    source = conn.execute("SELECT revision, updated_at FROM graph_source_state WHERE id = 1").fetchone()
    source_revision = int(source["revision"] or 0) if source is not None else 0
    source_updated_at = _parse_time(source["updated_at"] if source is not None else None)
    if not _table_exists(conn, "graph_projection_generations"):
        return {
            "graph_source_revision": source_revision,
            "graph_projection_revision": None,
            "graph_generation_lag_seconds": None,
            "graph_projection_mode": "sqlite_fallback",
        }
    projection = conn.execute(
        """
        SELECT source_revision, status, built_at, error_code
        FROM graph_projection_generations
        ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'building' THEN 1 ELSE 2 END,
                 COALESCE(built_at, '') DESC,
                 id DESC
        LIMIT 1
        """
    ).fetchone()
    if projection is None or str(projection["status"]) != "active":
        return {
            "graph_source_revision": source_revision,
            "graph_projection_revision": int(projection["source_revision"]) if projection is not None else None,
            "graph_generation_lag_seconds": None,
            "graph_projection_mode": "sqlite_fallback",
            "graph_projection_error_code": str(projection["error_code"]) if projection is not None and projection["error_code"] else None,
        }
    projection_revision = int(projection["source_revision"] or 0)
    lag = 0.0
    if projection_revision != source_revision and source_updated_at is not None:
        lag = max(0.0, (observed_at - source_updated_at).total_seconds())
    return {
        "graph_source_revision": source_revision,
        "graph_projection_revision": projection_revision,
        "graph_generation_lag_seconds": round(lag, 3),
        "graph_projection_mode": "kuzu" if projection_revision == source_revision else "sqlite_fallback",
    }


def _parse_time(value: object) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect one privacy-safe Agent Pet soak snapshot")
    parser.add_argument("--database", required=True)
    parser.add_argument("--since", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(json.dumps(collect_soak_snapshot(args.database, since=args.since), separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
