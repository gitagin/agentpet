"""Run the non-destructive LLM Wiki migration smoke matrix."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.services.memory_graph_migration import apply_llmwiki_migrations
from app.storage.database import Database, MigrationRunner


def _snapshot_dict(snapshot: Any) -> dict[str, Any]:
    data = asdict(snapshot)
    data["tables"] = sorted(data["tables"])
    data["columns"] = {key: sorted(value) for key, value in data["columns"].items()}
    data["row_counts"] = dict(data["row_counts"])
    data["foreign_key_violations"] = [list(item) for item in data["foreign_key_violations"]]
    return data


def _run_full(path: Path, backup: Path) -> dict[str, Any]:
    report = apply_llmwiki_migrations(path, backup_path=backup)
    preserved_row_counts = all(
        report.after.row_counts.get(table, before_count) >= before_count
        for table, before_count in report.before.row_counts.items()
    )
    return {
        "backup_path_present": Path(report.backup_path).exists(),
        "applied_versions": list(report.applied_versions),
        "repeated_apply_versions": list(report.repeated_apply_versions),
        "before": _snapshot_dict(report.before),
        "after": _snapshot_dict(report.after),
        "repeat": _snapshot_dict(report.repeat_snapshot),
        "preserved_row_counts": preserved_row_counts,
        "foreign_key_errors": len(report.after.foreign_key_violations),
    }


def _create_empty(path: Path) -> None:
    with Database(path).session() as conn:
        conn.execute("SELECT 1")


def _create_legacy(path: Path, migration_source: Path, temporary: Path) -> None:
    partial_dir = temporary / "legacy-migrations"
    partial_dir.mkdir(parents=True, exist_ok=True)
    for migration in sorted(migration_source.glob("*.sql")):
        if migration.stem > "019_credential_metadata_without_masks":
            continue
        shutil.copy2(migration, partial_dir / migration.name)
    MigrationRunner(Database(path), migrations_dir=partial_dir).apply()
    with Database(path).session() as conn:
        conn.execute(
            """
            INSERT INTO memory_graph_facts (
                id, fact_key, conflict_key, category, subject, predicate, object,
                status, confidence, source_text, source_type, support_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration-smoke-fact",
                "migration-smoke-key",
                "migration-smoke-conflict",
                "preference",
                "self",
                "prefers",
                "preserved legacy data",
                "active",
                0.95,
                "legacy migration fixture",
                "user_message",
                1,
                "2026-08-10T00:00:00Z",
                "2026-08-10T00:00:00Z",
            ),
        )
        conn.execute(
            """
            INSERT INTO memory_candidates (
                id, candidate_hash, memory_kind, memory_scope, summary,
                normalized_value, source_text, source_text_hash, source_track,
                risk_tier, confidence, importance, evidence_count, status,
                fact_id, metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "migration-smoke-candidate",
                "migration-smoke-candidate-hash",
                "preference",
                "global",
                "Preserve this legacy candidate",
                "preserved legacy data",
                "legacy migration fixture",
                "migration-smoke-source-hash",
                "explicit_user",
                "low",
                0.95,
                0.8,
                1,
                "active",
                "migration-smoke-fact",
                '{"fixture":"legacy-019"}',
                "2026-08-10T00:00:00Z",
                "2026-08-10T00:00:00Z",
            ),
        )


def run(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    migration_source = Path(__file__).resolve().parents[2] / "migrations"
    with tempfile.TemporaryDirectory(prefix="llmwiki-migration-smoke-") as temporary_name:
        temporary = Path(temporary_name)
        empty = temporary / "empty.sqlite3"
        legacy = temporary / "legacy.sqlite3"
        _create_empty(empty)
        _create_legacy(legacy, migration_source, temporary)
        result = {
            "schema_version": "llmwiki-migration-smoke.v1",
            "modes": {
                "empty_database": _run_full(empty, temporary / "empty.sqlite3.bak"),
                "legacy_database": _run_full(legacy, temporary / "legacy.sqlite3.bak"),
            },
        }
    (output_dir / "migration-report.json").write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.output_dir)
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(json.dumps({"status": "failed", "error": type(exc).__name__}, ensure_ascii=True))
        return 1
    failed = [
        mode
        for mode, report in result["modes"].items()
        if report["foreign_key_errors"] != 0
        or report["repeated_apply_versions"]
        or not report["preserved_row_counts"]
    ]
    legacy_before = result["modes"]["legacy_database"]["before"]["row_counts"]
    if legacy_before.get("memory_graph_facts") != 1 or legacy_before.get("memory_candidates") != 1:
        failed.append("legacy_fixture_missing")
    print(json.dumps({"status": "passed" if not failed else "failed", "failed_modes": failed}, ensure_ascii=True))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
