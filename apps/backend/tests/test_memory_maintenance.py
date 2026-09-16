from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apps.backend.tests._schema import migrate_db
from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateCreate
from app.services.memory_maintenance import run_memory_maintenance
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack


def _seed_candidate(
    db_path: Path,
    *,
    kind: MemoryKind,
    status: LifecycleStatus,
    value: str,
    confidence: float = 0.8,
    expires_at: str | None = None,
) -> str:
    from app.services.memory_candidates import MemoryCandidateStore

    store = MemoryCandidateStore(db_path)
    try:
        return store.create_candidate(
            MemoryCandidateCreate(
                memory_kind=kind,
                memory_scope=MemoryScope.GLOBAL,
                summary=value,
                normalized_value=value,
                source_text=f"source: {value}",
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                risk_tier=RiskTier.LOW,
                confidence=confidence,
                importance=0.6,
                status=status,
                expires_at=expires_at,
            )
        ).id
    finally:
        store.close()


def _bump_updated_at(db_path: Path, candidate_id: str, updated_at: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE memory_candidates SET updated_at = ? WHERE id = ?", (updated_at, candidate_id))


def _status(db_path: Path, candidate_id: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
    return str(row[0]) if row else ""


def test_run_memory_maintenance_stales_old_project_candidates_and_runs_hygiene(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    old_stamp = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
    fresh_stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    stale_project = _seed_candidate(
        db_path,
        kind=MemoryKind.PROJECT_CONTEXT,
        status=LifecycleStatus.ACTIVE,
        value="project alpha notes",
    )
    fresh_project = _seed_candidate(
        db_path,
        kind=MemoryKind.PROJECT_CONTEXT,
        status=LifecycleStatus.ACTIVE,
        value="project beta notes",
    )
    expired_recent_state = _seed_candidate(
        db_path,
        kind=MemoryKind.RECENT_STATE,
        status=LifecycleStatus.ACTIVE,
        value="temporary focus mode",
        expires_at=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
    )
    _bump_updated_at(db_path, stale_project, old_stamp)

    payload = run_memory_maintenance(db_path)

    assert payload["stale_project_candidates"] == 1
    assert payload["hygiene_actions"] >= 1
    assert _status(db_path, stale_project) == LifecycleStatus.STALE.value
    assert _status(db_path, fresh_project) == LifecycleStatus.ACTIVE.value
    assert _status(db_path, expired_recent_state) == MemoryFactStatus.ARCHIVED.value or _status(
        db_path, expired_recent_state
    ) == LifecycleStatus.ARCHIVED.value


def test_run_memory_maintenance_is_idempotent_on_second_run(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    old_stamp = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat().replace("+00:00", "Z")
    candidate_id = _seed_candidate(
        db_path,
        kind=MemoryKind.PROJECT_CONTEXT,
        status=LifecycleStatus.ACTIVE,
        value="project gamma notes",
    )
    _bump_updated_at(db_path, candidate_id, old_stamp)

    first = run_memory_maintenance(db_path)
    second = run_memory_maintenance(db_path)

    assert first["stale_project_candidates"] == 1
    assert second["stale_project_candidates"] == 0
    assert _status(db_path, candidate_id) == LifecycleStatus.STALE.value


def test_schedule_memory_maintenance_skips_fake_schedulers() -> None:
    import app.main as main_module

    class FakeScheduler:
        pass

    # 无底层 APScheduler 的测试替身应安全跳过，不抛异常。
    main_module._schedule_memory_maintenance(FakeScheduler(), Path("unused.db"))
