from __future__ import annotations

import sqlite3
from pathlib import Path

from app.storage.database import Database, MigrationRunner


DUAL_TRACK_TABLES = {
    "memory_candidates",
    "memory_evidence",
    "memory_lifecycle_events",
    "memory_activation_events",
    "memory_feedback_events",
}


def test_dual_track_memory_migration_creates_tables_indexes_and_defaults(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    applied = MigrationRunner(Database(db_path)).apply()

    assert "017_dual_track_memory" in applied

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        }
        assert DUAL_TRACK_TABLES.issubset(tables)

        candidate_columns = _columns(conn, "memory_candidates")
        assert candidate_columns["status"]["dflt_value"] == "'candidate'"
        assert candidate_columns["normalized_value"]["dflt_value"] == "''"
        assert candidate_columns["evidence_count"]["dflt_value"] == "1"
        assert candidate_columns["metadata_json"]["dflt_value"] == "'{}'"
        assert candidate_columns["fact_id"]["notnull"] == 0
        assert candidate_columns["superseded_by"]["notnull"] == 0

        evidence_columns = _columns(conn, "memory_evidence")
        assert evidence_columns["source_excerpt"]["dflt_value"] == "''"
        assert evidence_columns["metadata_json"]["dflt_value"] == "'{}'"

        activation_columns = _columns(conn, "memory_activation_events")
        assert activation_columns["permissions_json"]["dflt_value"] == "'{}'"
        assert activation_columns["score_breakdown_json"]["dflt_value"] == "'{}'"
        assert activation_columns["used_for_style"]["dflt_value"] == "0"
        assert activation_columns["used_for_answer_context"]["dflt_value"] == "0"

        feedback_columns = _columns(conn, "memory_feedback_events")
        assert feedback_columns["feedback_text"]["dflt_value"] == "''"
        assert feedback_columns["metadata_json"]["dflt_value"] == "'{}'"

        indexes = _indexes(conn)
        assert {
            "idx_memory_candidates_status_kind",
            "idx_memory_candidates_scope_risk",
            "idx_memory_candidates_fact",
            "idx_memory_candidates_expires",
            "idx_memory_evidence_candidate",
            "idx_memory_evidence_fact",
            "idx_memory_evidence_agent_run",
            "idx_memory_evidence_diary_object",
            "idx_memory_lifecycle_events_candidate",
            "idx_memory_lifecycle_events_fact",
            "idx_memory_lifecycle_events_action",
            "idx_memory_activation_events_run",
            "idx_memory_activation_events_candidate",
            "idx_memory_activation_events_fact",
            "idx_memory_feedback_events_candidate",
            "idx_memory_feedback_events_fact",
            "idx_memory_feedback_events_type",
        }.issubset(indexes)


def test_dual_track_memory_foreign_keys_and_constraints(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    MigrationRunner(Database(db_path)).apply()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        assert _foreign_key_targets(conn, "memory_candidates") >= {
            ("fact_id", "memory_graph_facts"),
            ("superseded_by", "memory_candidates"),
        }
        assert _foreign_key_targets(conn, "memory_evidence") >= {
            ("candidate_id", "memory_candidates"),
            ("fact_id", "memory_graph_facts"),
            ("conversation_id", "conversations"),
            ("message_id", "messages"),
            ("agent_run_id", "agent_runs"),
            ("diary_object_id", "diary_memory_objects"),
        }
        assert _foreign_key_targets(conn, "memory_lifecycle_events") >= {
            ("candidate_id", "memory_candidates"),
            ("fact_id", "memory_graph_facts"),
            ("agent_action_id", "agent_actions"),
        }
        assert _foreign_key_targets(conn, "memory_activation_events") >= {
            ("candidate_id", "memory_candidates"),
            ("fact_id", "memory_graph_facts"),
        }
        assert _foreign_key_targets(conn, "memory_feedback_events") >= {
            ("candidate_id", "memory_candidates"),
            ("fact_id", "memory_graph_facts"),
            ("replacement_candidate_id", "memory_candidates"),
            ("agent_action_id", "agent_actions"),
        }

        conn.execute(
            """
            INSERT INTO memory_candidates (
                id, candidate_hash, memory_kind, memory_scope, summary,
                source_text, source_text_hash, source_track, risk_tier,
                confidence, importance, created_at, updated_at
            )
            VALUES (
                'candidate-1', 'hash-1', 'preference', 'global', 'Likes concise replies.',
                'source', 'source-hash', 'explicit_user', 'low',
                0.9, 0.8, '2026-06-06T00:00:00Z', '2026-06-06T00:00:00Z'
            )
            """
        )
        row = conn.execute("SELECT status, evidence_count, metadata_json FROM memory_candidates").fetchone()
        assert row["status"] == "candidate"
        assert row["evidence_count"] == 1
        assert row["metadata_json"] == "{}"

        conn.execute(
            """
            INSERT INTO memory_evidence (
                id, candidate_id, source_type, source_text_hash, confidence, created_at
            )
            VALUES (
                'evidence-1', 'candidate-1', 'chat_message', 'source-hash',
                0.8, '2026-06-06T00:00:00Z'
            )
            """
        )

        try:
            conn.execute(
                """
                INSERT INTO memory_candidates (
                    id, candidate_hash, memory_kind, memory_scope, summary,
                    source_text, source_text_hash, source_track, risk_tier,
                    confidence, importance, created_at, updated_at
                )
                VALUES (
                    'candidate-bad', 'hash-bad', 'personality_label', 'global', 'Bad kind.',
                    'source', 'source-hash', 'explicit_user', 'low',
                    0.9, 0.8, '2026-06-06T00:00:00Z', '2026-06-06T00:00:00Z'
                )
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("invalid memory_kind should violate CHECK constraint")

        try:
            conn.execute(
                """
                INSERT INTO memory_evidence (
                    id, source_type, source_text_hash, confidence, created_at
                )
                VALUES (
                    'evidence-bad', 'chat_message', 'source-hash',
                    0.8, '2026-06-06T00:00:00Z'
                )
                """
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("evidence without candidate_id or fact_id should violate CHECK constraint")


def test_dual_track_memory_migration_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite3"
    runner = MigrationRunner(Database(db_path))
    first = runner.apply()
    second = runner.apply()

    assert "017_dual_track_memory" in first
    assert second == []

    with sqlite3.connect(db_path) as conn:
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version FROM schema_migrations WHERE version = '017_dual_track_memory'"
            ).fetchall()
        ]
    assert versions == ["017_dual_track_memory"]


def _columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    }


def _foreign_key_targets(conn: sqlite3.Connection, table: str) -> set[tuple[str, str]]:
    return {
        (row["from"], row["table"])
        for row in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    }

