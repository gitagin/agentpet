"""Periodic memory maintenance: hygiene sweeps + project-candidate aging.

MemoryHygieneService and mark_old_project_candidates_stale were fully
implemented but never scheduled in production (only tests called them).
This module is the scheduler entry point: it is registered as an
APScheduler interval job at sidecar startup (app/main.py), so memory
decay/卫生 actually runs instead of being a manual-only illusion.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.memory_hygiene import MemoryHygieneService
from app.services.memory_lifecycle import MemoryLifecycleService

logger = logging.getLogger(__name__)

PROJECT_CANDIDATE_STALE_AFTER_DAYS = 90
HYGIENE_LIMIT = 500
STALE_PROJECT_LIMIT = 200
MAINTENANCE_JOB_ID = "memory-maintenance"
MAINTENANCE_INTERVAL_HOURS = 12


def schedule_memory_maintenance(scheduler: object, db_path: str | Path, *, hours: int = MAINTENANCE_INTERVAL_HOURS) -> bool:
    """Register the periodic job on the shared APScheduler; True when newly added.

    Called at sidecar startup and again after reset-local-state (whose
    scheduler.clear() wipes the jobstore), and skipped for test doubles
    that have no underlying APScheduler.
    """
    underlying = getattr(scheduler, "scheduler", None)
    if underlying is None or not callable(getattr(underlying, "add_job", None)):
        return False
    try:
        existing_ids = {str(job.id) for job in underlying.get_jobs()}
    except Exception:
        existing_ids = set()
    if MAINTENANCE_JOB_ID in existing_ids:
        return False
    underlying.add_job(
        run_memory_maintenance,
        trigger="interval",
        hours=max(1, hours),
        id=MAINTENANCE_JOB_ID,
        kwargs={"db_path": str(db_path)},
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
        replace_existing=True,
    )
    logger.info("Scheduled periodic memory maintenance (hygiene sweep + stale project candidates)")
    return True


def run_memory_maintenance(db_path: str | Path) -> dict[str, int]:
    """One maintenance sweep. Safe to call repeatedly (each step is idempotent)."""
    db_path = Path(db_path)
    hygiene = MemoryHygieneService(db_path)
    try:
        result = hygiene.run(limit=HYGIENE_LIMIT)
        action_count = result.action_count
    finally:
        hygiene.close()

    lifecycle = MemoryLifecycleService(db_path)
    try:
        stale_before = (
            datetime.now(timezone.utc) - timedelta(days=PROJECT_CANDIDATE_STALE_AFTER_DAYS)
        ).isoformat().replace("+00:00", "Z")
        stale_ids = lifecycle.mark_old_project_candidates_stale(
            older_than_updated_at=stale_before,
            limit=STALE_PROJECT_LIMIT,
        )
    finally:
        lifecycle.close()

    payload: dict[str, int] = {
        "hygiene_actions": action_count,
        "stale_project_candidates": len(stale_ids),
    }
    if action_count or stale_ids:
        logger.info("Memory maintenance sweep completed", extra=payload)
    return payload


def maintenance_job_payload(db_path: str | Path) -> dict[str, Any]:
    return {"db_path": str(db_path)}
