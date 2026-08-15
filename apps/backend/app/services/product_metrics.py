from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
from threading import Lock

from app.models.common import new_id
from app.services.settings_store import LocalCredentialStore
from app.storage.database import open_database_connection
from app.utils.metric_references import (
    PUBLIC_REFERENCE_PATTERN as PUBLIC_REFERENCE_PATTERN,
    is_public_reference as is_public_reference,
)
from app.utils.time import utc_now_iso


METRIC_VERSION = "local-impact.v1"
METRICS_SECRET_REF = "product-metrics:hmac:v1"
ALLOWED_WINDOW_DAYS = frozenset({7, 30})
_SECRET_LOCK = Lock()
EVENT_TYPES = frozenset(
    {
        "candidate_created",
        "activated",
        "recalled",
        "feedback_recorded",
        "corrected",
        "forgotten",
        "grounded_answer",
        "no_evidence",
        "action_attempted",
        "business_effect_committed",
        "duplicate_prevented",
        "duplicate_effect_detected",
        "reminder_triggered",
        "reminder_display_attempted",
        "reminder_display_unknown",
        "sidecar_unhealthy",
        "sidecar_ready",
        "wiki_lint_result",
        "lookup_started",
        "lookup_completed",
        "context_repetition_reported",
        "wiki_reused",
    }
)
ALLOWED_DIMENSIONS = frozenset(
    {
        "channel",
        "source_scope",
        "feedback",
        "status",
        "reason",
        "result",
        "citation_valid",
        "old_absent",
        "new_present",
        "route",
        "failure_code",
        "action_type",
        "duration_ms",
        "repetition_count",
        "signal",
        "reference_type",
        "has_citation",
        "observation_status",
        "replacement_subject_hash",
        "effect_id_hash",
        "confirmation_duration_ms",
        "queue_depth",
        "revoked",
        "active_pages",
        "passed_pages",
        "error_count",
        "warning_count",
        "incident_state",
        "restart_attempt",
    }
)
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SAFE_DIMENSION_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_SIDECAR_INCIDENT_ID = re.compile(r"^[a-f0-9]{32}$")
_SIDECAR_CAUSES = frozenset(
    {"process_exited", "spawn_failed", "startup_failed", "readiness_failed"}
)


class MetricValidationError(ValueError):
    """A caller supplied an event outside the local metric contract."""


class MetricPayloadConflict(MetricValidationError):
    """An idempotency key was reused for a different event payload."""


@dataclass(frozen=True, slots=True)
class MetricEvent:
    id: str
    event_version: str
    event_type: str
    idempotency_key: str
    subject_hash: str | None
    value: float
    dimensions: dict[str, str]
    created_at: str


class ProductMetricsService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        secret: bytes | None = None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self._secret = secret or _installation_secret(db)

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def subject_token(self, stable_id: str) -> str:
        value = str(stable_id).strip()
        if (
            not value
            or len(value) > 256
            or any(char.isspace() or ord(char) < 32 for char in value)
            or "/" in value
            or "\\" in value
        ):
            raise MetricValidationError("metric_subject_invalid")
        return hmac.new(self._secret, value.encode("utf-8"), hashlib.sha256).hexdigest()

    def record_correction(
        self,
        *,
        idempotency_key: str,
        old_subject_id: str,
        replacement_subject_id: str | None,
    ) -> MetricEvent:
        replacement_hash = (
            self.subject_token(replacement_subject_id)
            if replacement_subject_id
            else None
        )
        dimensions: dict[str, object] = {"observation_status": "pending"}
        if replacement_hash:
            dimensions["replacement_subject_hash"] = replacement_hash
        event = self.record(
            event_type="corrected",
            idempotency_key=idempotency_key,
            subject_id=old_subject_id,
            dimensions=dimensions,
        )
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO product_metric_correction_observations (
                    correction_event_id, old_subject_hash, replacement_subject_hash,
                    status, query_count, observed_at, updated_at
                ) VALUES (?, ?, ?, 'pending', 0, NULL, ?)
                """,
                (event.id, event.subject_hash, replacement_hash, now),
            )
        return event

    def observe_corrections(self, observed_subject_ids: Iterable[str]) -> int:
        observed_hashes = {
            self.subject_token(subject_id)
            for subject_id in observed_subject_ids
            if str(subject_id).strip()
        }
        if not observed_hashes:
            return 0
        rows = self.conn.execute(
            """
            SELECT correction_event_id, old_subject_hash, replacement_subject_hash, status
            FROM product_metric_correction_observations
            WHERE status = 'pending' AND replacement_subject_hash IS NOT NULL
            """
        ).fetchall()
        now = utc_now_iso()
        updated = 0
        with self.conn:
            for row in rows:
                old_hash = str(row["old_subject_hash"])
                replacement_hash = str(row["replacement_subject_hash"])
                old_present = old_hash in observed_hashes
                replacement_present = replacement_hash in observed_hashes
                if not old_present and not replacement_present:
                    continue
                status = "verified" if not old_present and replacement_present else "failed"
                self.conn.execute(
                    """
                    UPDATE product_metric_correction_observations
                    SET status = ?, query_count = query_count + 1,
                        observed_at = ?, updated_at = ?
                    WHERE correction_event_id = ?
                    """,
                    (status, now, now, str(row["correction_event_id"])),
                )
                updated += 1
        return updated

    def record(
        self,
        *,
        event_type: str,
        idempotency_key: str,
        subject_id: str | None = None,
        value: float = 1.0,
        dimensions: Mapping[str, object] | None = None,
        created_at: str | None = None,
    ) -> MetricEvent:
        event = _validate_event(
            event_type=event_type,
            idempotency_key=idempotency_key,
            subject_hash=self.subject_token(subject_id) if subject_id else None,
            value=value,
            dimensions=dimensions or {},
            created_at=created_at or utc_now_iso(),
        )
        payload_hash = _payload_hash(event)
        existing = self.conn.execute(
            "SELECT * FROM product_metric_events WHERE idempotency_key = ?",
            (event.idempotency_key,),
        ).fetchone()
        if existing is not None:
            if str(existing["payload_hash"]) != payload_hash:
                raise MetricPayloadConflict("metric_idempotency_payload_conflict")
            return _map_event(existing)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO product_metric_events (
                    id, event_version, event_type, idempotency_key, payload_hash,
                    subject_hash, value, dimensions_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    event.event_version,
                    event.event_type,
                    event.idempotency_key,
                    payload_hash,
                    event.subject_hash,
                    event.value,
                    json.dumps(event.dimensions, ensure_ascii=True, sort_keys=True, separators=(",", ":")),
                    event.created_at,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM product_metric_events WHERE idempotency_key = ?",
            (event.idempotency_key,),
        ).fetchone()
        assert row is not None
        return _map_event(row)

    def record_sidecar_recovery(
        self,
        *,
        incident_id: str,
        unhealthy_at: str,
        ready_at: str,
        cause: str,
        restart_attempt: int = 1,
    ) -> tuple[MetricEvent, MetricEvent, bool]:
        """Record one paired sidecar incident using stable event identities.

        The sidecar can only reach the API after it has recovered, so the
        unhealthy and ready transitions are submitted together. Each event
        remains independently idempotent, allowing a retry to complete a
        write interrupted between the two inserts.
        """
        normalized_incident = _normalize_sidecar_incident_id(incident_id)
        normalized_cause = _normalize_sidecar_cause(cause)
        normalized_attempt = _normalize_sidecar_restart_attempt(restart_attempt)
        subject_id = f"sidecar-incident:{normalized_incident}"
        unhealthy_key = f"sidecar-recovery:{normalized_incident}:unhealthy"
        ready_key = f"sidecar-recovery:{normalized_incident}:ready"
        unhealthy_dimensions = {
            "failure_code": normalized_cause,
            "incident_state": "unhealthy",
            "restart_attempt": normalized_attempt,
        }
        ready_dimensions = {"incident_state": "ready"}
        was_complete = (
            self.event_by_idempotency_key(unhealthy_key) is not None
            and self.event_by_idempotency_key(ready_key) is not None
        )
        unhealthy = self.record(
            event_type="sidecar_unhealthy",
            idempotency_key=unhealthy_key,
            subject_id=subject_id,
            dimensions=unhealthy_dimensions,
            created_at=unhealthy_at,
        )
        ready = self.record(
            event_type="sidecar_ready",
            idempotency_key=ready_key,
            subject_id=subject_id,
            dimensions=ready_dimensions,
            created_at=ready_at,
        )
        return unhealthy, ready, was_complete

    def read_sidecar_recovery(
        self,
        *,
        incident_id: str,
        unhealthy_at: str,
        ready_at: str,
        cause: str,
        restart_attempt: int = 1,
    ) -> dict[str, object] | None:
        """Return the paired events only when their hashes match the request."""
        normalized_incident = _normalize_sidecar_incident_id(incident_id)
        normalized_cause = _normalize_sidecar_cause(cause)
        normalized_attempt = _normalize_sidecar_restart_attempt(restart_attempt)
        subject_id = f"sidecar-incident:{normalized_incident}"
        unhealthy_key = f"sidecar-recovery:{normalized_incident}:unhealthy"
        ready_key = f"sidecar-recovery:{normalized_incident}:ready"
        expected = (
            (
                unhealthy_key,
                "sidecar_unhealthy",
                unhealthy_at,
                {
                    "failure_code": normalized_cause,
                    "incident_state": "unhealthy",
                    "restart_attempt": normalized_attempt,
                },
            ),
            (ready_key, "sidecar_ready", ready_at, {"incident_state": "ready"}),
        )
        rows: list[sqlite3.Row] = []
        for key, event_type, created_at, dimensions in expected:
            row = self.event_by_idempotency_key(key)
            if row is None or str(row["event_type"]) != event_type:
                return None
            if str(row["created_at"]) != str(created_at):
                return None
            if str(row["subject_hash"] or "") != self.subject_token(subject_id):
                return None
            payload_hash = self.payload_hash_for(
                event_type=event_type,
                idempotency_key=key,
                subject_id=subject_id,
                dimensions=dimensions,
            )
            if str(row["payload_hash"]) != payload_hash:
                return None
            rows.append(row)
        return {
            "unhealthy_event_id": str(rows[0]["id"]),
            "ready_event_id": str(rows[1]["id"]),
            "incident_id": normalized_incident,
            "state_ref": f"sidecar-incident:{normalized_incident}",
        }

    def has_idempotency_key(self, idempotency_key: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM product_metric_events WHERE idempotency_key = ? LIMIT 1",
            (str(idempotency_key).strip(),),
        ).fetchone()
        return row is not None

    def existing_payload_hash(self, idempotency_key: str) -> str | None:
        """Return the stored event payload hash without exposing event data."""
        row = self.conn.execute(
            "SELECT payload_hash FROM product_metric_events WHERE idempotency_key = ? LIMIT 1",
            (str(idempotency_key).strip(),),
        ).fetchone()
        return str(row["payload_hash"]) if row is not None else None

    def event_by_idempotency_key(self, idempotency_key: str) -> sqlite3.Row | None:
        """Read one event for lifecycle verification without returning content."""
        return self.conn.execute(
            "SELECT id, event_type, payload_hash, subject_hash, value, created_at FROM product_metric_events WHERE idempotency_key = ? LIMIT 1",
            (str(idempotency_key).strip(),),
        ).fetchone()

    def effect_hashes_for_action(self, action_id: str) -> set[str]:
        subject_hash = self.subject_token(action_id)
        rows = self.conn.execute(
            """
            SELECT dimensions_json
            FROM product_metric_events
            WHERE event_type = 'business_effect_committed' AND subject_hash = ?
            """,
            (subject_hash,),
        ).fetchall()
        effect_hashes: set[str] = set()
        for row in rows:
            try:
                dimensions = json.loads(str(row["dimensions_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(dimensions, dict) and dimensions.get("effect_id_hash"):
                effect_hashes.add(str(dimensions["effect_id_hash"]))
        return effect_hashes

    def payload_hash_for(
        self,
        *,
        event_type: str,
        idempotency_key: str,
        subject_id: str | None = None,
        value: float = 1.0,
        dimensions: Mapping[str, object] | None = None,
    ) -> str:
        event = _validate_event(
            event_type=event_type,
            idempotency_key=idempotency_key,
            subject_hash=self.subject_token(subject_id) if subject_id else None,
            value=value,
            dimensions=dimensions or {},
            created_at="",
        )
        return _payload_hash(event)

    def aggregate(self, *, window_days: int = 7) -> dict[str, object]:
        days = _normalize_window_days(window_days)
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM product_metric_events WHERE created_at >= ? ORDER BY created_at, id",
            (since,),
        ).fetchall()
        events = [_map_event(row) for row in rows]
        metrics = {
            "memory_recall_success_rate": _ratio_metric(
                _count_feedback(events, "helpful"),
                _count_feedback(events, "helpful", "incorrect", "missing"),
                days,
            ),
            "memory_error_rate": _ratio_metric(
                _count_feedback(events, "incorrect"),
                _count_feedback(events, "helpful", "incorrect", "missing"),
                days,
            ),
            "context_repetition_rate": _ratio_metric(
                _count_feedback(events, "context_repeated"),
                _count_feedback(events, "context_repeated", "context_not_repeated"),
                days,
            ),
            "wiki_reuse_rate": _ratio_metric(
                _count_feedback(events, "wiki_reused"),
                _count_feedback(events, "wiki_reused", "context_not_repeated", "context_repeated"),
                days,
            ),
            "correction_propagation_rate": _ratio_metric(
                self._correction_observation_count(since, status="verified"),
                self._correction_observation_count(since, statuses={"verified", "failed"}),
                days,
            ),
            "source_coverage_rate": _ratio_metric(
                sum(1 for event in events if event.event_type == "grounded_answer" and event.dimensions.get("citation_valid") == "true"),
                sum(1 for event in events if event.event_type == "grounded_answer"),
                days,
            ),
            "duplicate_effect_rate": _ratio_metric(
                len({
                    event.subject_hash
                    for event in events
                    if event.event_type == "duplicate_effect_detected" and event.subject_hash
                }),
                len({
                    event.subject_hash
                    for event in events
                    if event.event_type == "action_attempted" and event.subject_hash
                }),
                days,
            ),
            "reminder_display_attempt_rate": _ratio_metric(
                len({event.subject_hash for event in events if event.event_type == "reminder_display_attempted" and event.subject_hash}),
                len({event.subject_hash for event in events if event.event_type == "reminder_triggered" and event.subject_hash}),
                days,
            ),
            "recovery_time_ms": _recovery_metric(events, days),
            "lookup_duration": _latency_metric(events, days, event_types={"lookup_completed"}),
            "wiki_health_rate": _wiki_health_metric(events, days),
            "confirmation_burden": _confirmation_metric(events, days),
        }
        failure_counts: dict[str, int] = {}
        for event in events:
            if event.event_type in {"no_evidence", "sidecar_unhealthy", "reminder_display_unknown"}:
                failure_counts[event.event_type] = failure_counts.get(event.event_type, 0) + 1
        return {
            "metric_version": METRIC_VERSION,
            "window_days": days,
            "generated_at": utc_now_iso(),
            "sample_size": (feedback_sample_size := _feedback_sample_count(events)),
            "evidence_status": "sufficient" if feedback_sample_size >= 20 else "insufficient_sample",
            "failure_counts": failure_counts,
            "metrics": metrics,
        }

    def _correction_observation_count(
        self,
        since: str,
        *,
        status: str | None = None,
        statuses: set[str] | None = None,
    ) -> int:
        clauses = ["observed_at IS NOT NULL", "observed_at >= ?"]
        params: list[object] = [since]
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        elif statuses:
            placeholders = ",".join("?" for _ in statuses)
            clauses.append(f"status IN ({placeholders})")
            params.extend(sorted(statuses))
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM product_metric_correction_observations WHERE {' AND '.join(clauses)}",
            params,
        ).fetchone()
        return int(row[0] or 0) if row is not None else 0

    def reset(self) -> int:
        with self.conn:
            self.conn.execute("DELETE FROM product_metric_correction_observations")
            result = self.conn.execute("DELETE FROM product_metric_events")
        return int(result.rowcount)


def _installation_secret(db: str | Path | sqlite3.Connection) -> bytes:
    env_secret = os.environ.get("AGENT_PET_METRICS_SECRET", "").strip()
    if env_secret:
        return hashlib.sha256(env_secret.encode("utf-8")).digest()
    database_path = _database_path(db)
    if database_path is None:
        raise MetricValidationError("metric_secret_persistence_unavailable")
    with _SECRET_LOCK:
        store = LocalCredentialStore.for_database(database_path)
        existing = store.get(METRICS_SECRET_REF)
        if existing:
            return hashlib.sha256(existing.encode("utf-8")).digest()
        value = secrets.token_urlsafe(48)
        store.put(METRICS_SECRET_REF, value)
        return hashlib.sha256(value.encode("utf-8")).digest()


def _database_path(db: str | Path | sqlite3.Connection) -> Path | None:
    if not isinstance(db, sqlite3.Connection):
        if str(db) == ":memory:":
            return None
        return Path(db).resolve()
    row = db.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    try:
        path_value = row[2]
    except (IndexError, KeyError):
        path_value = None
    if not path_value:
        return None
    return Path(str(path_value)).resolve()


def _validate_event(
    *,
    event_type: str,
    idempotency_key: str,
    subject_hash: str | None,
    value: float,
    dimensions: Mapping[str, object],
    created_at: str,
) -> MetricEvent:
    normalized_type = str(event_type).strip()
    key = str(idempotency_key).strip()
    if normalized_type not in EVENT_TYPES:
        raise MetricValidationError("metric_event_type_not_allowed")
    if not _SAFE_KEY.fullmatch(key):
        raise MetricValidationError("metric_idempotency_key_invalid")
    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise MetricValidationError("metric_value_invalid") from exc
    if numeric_value < 0:
        raise MetricValidationError("metric_value_invalid")
    normalized_dimensions: dict[str, str] = {}
    for raw_name, raw_value in dimensions.items():
        name = str(raw_name).strip()
        if name not in ALLOWED_DIMENSIONS:
            raise MetricValidationError("metric_dimension_not_allowed")
        if isinstance(raw_value, bool):
            value_text = "true" if raw_value else "false"
        elif isinstance(raw_value, (str, int, float)):
            value_text = str(raw_value).strip()
        else:
            raise MetricValidationError("metric_dimension_value_invalid")
        if not _SAFE_DIMENSION_VALUE.fullmatch(value_text):
            raise MetricValidationError("metric_dimension_value_invalid")
        normalized_dimensions[name] = value_text
    return MetricEvent(
        id="",
        event_version=METRIC_VERSION,
        event_type=normalized_type,
        idempotency_key=key,
        subject_hash=subject_hash,
        value=numeric_value,
        dimensions=normalized_dimensions,
        created_at=str(created_at),
    )


def _normalize_sidecar_incident_id(value: str) -> str:
    normalized = str(value).strip().lower()
    if not _SIDECAR_INCIDENT_ID.fullmatch(normalized):
        raise MetricValidationError("sidecar_incident_id_invalid")
    return normalized


def _normalize_sidecar_cause(value: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in _SIDECAR_CAUSES:
        raise MetricValidationError("sidecar_incident_cause_invalid")
    return normalized


def _normalize_sidecar_restart_attempt(value: int) -> str:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MetricValidationError("sidecar_restart_attempt_invalid") from exc
    if normalized < 1 or normalized > 5:
        raise MetricValidationError("sidecar_restart_attempt_invalid")
    return str(normalized)


def _payload_hash(event: MetricEvent) -> str:
    payload = {
        "event_version": event.event_version,
        "event_type": event.event_type,
        "idempotency_key": event.idempotency_key,
        "subject_hash": event.subject_hash,
        "value": event.value,
        "dimensions": event.dimensions,
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _map_event(row: sqlite3.Row) -> MetricEvent:
    return MetricEvent(
        id=str(row["id"]),
        event_version=str(row["event_version"]),
        event_type=str(row["event_type"]),
        idempotency_key=str(row["idempotency_key"]),
        subject_hash=row["subject_hash"],
        value=float(row["value"]),
        dimensions=json.loads(str(row["dimensions_json"] or "{}")),
        created_at=str(row["created_at"]),
    )


def _count_feedback(events: Sequence[MetricEvent], *values: str) -> int:
    allowed = set(values)
    return sum(
        1
        for event in events
        if event.event_type in {"feedback_recorded", "context_repetition_reported", "wiki_reused"}
        and (event.dimensions.get("feedback") or event.dimensions.get("signal")) in allowed
    )


def _feedback_sample_count(events: Sequence[MetricEvent]) -> int:
    return sum(
        1
        for event in events
        if event.event_type in {"feedback_recorded", "context_repetition_reported", "wiki_reused"}
    )


def _normalize_window_days(value: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise MetricValidationError("metric_window_days_invalid") from exc
    if normalized not in ALLOWED_WINDOW_DAYS:
        raise MetricValidationError("metric_window_days_invalid")
    return normalized


def _ratio_metric(numerator: int, denominator: int, window_days: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "sample_size": denominator,
        "window_days": window_days,
        "value": (numerator / denominator) if denominator else None,
        "evidence_status": "sufficient" if denominator >= 20 else "insufficient_sample",
    }


def _wiki_health_metric(events: Sequence[MetricEvent], window_days: int) -> dict[str, object]:
    lint_events = [event for event in events if event.event_type == "wiki_lint_result"]
    if not lint_events:
        return _ratio_metric(0, 0, window_days)
    has_page_counts = any("active_pages" in event.dimensions for event in lint_events)
    if not has_page_counts:
        return _ratio_metric(
            sum(1 for event in lint_events if event.dimensions.get("status") == "passed"),
            len(lint_events),
            window_days,
        )
    numerator = 0
    denominator = 0
    for event in lint_events:
        try:
            active_pages = max(0, int(event.dimensions.get("active_pages", "0")))
            passed_pages = max(0, int(event.dimensions.get("passed_pages", str(event.value))))
        except (TypeError, ValueError):
            continue
        denominator += active_pages
        numerator += min(active_pages, passed_pages)
    return _ratio_metric(numerator, denominator, window_days)


def _latency_metric(
    events: Sequence[MetricEvent],
    window_days: int,
    *,
    event_types: set[str] | None = None,
) -> dict[str, object]:
    allowed_types = event_types or {"sidecar_ready"}
    return _latency_values(
        [event.value for event in events if event.event_type in allowed_types],
        window_days,
    )


def _recovery_metric(events: Sequence[MetricEvent], window_days: int) -> dict[str, object]:
    pending: dict[str, datetime] = {}
    values: list[float] = []
    transitions = sorted(
        (
            (observed_at, event)
            for event in events
            if event.event_type in {"sidecar_unhealthy", "sidecar_ready"}
            if (observed_at := _parse_metric_timestamp(event.created_at)) is not None
        ),
        key=lambda item: item[0],
    )
    for observed_at, event in transitions:
        subject_hash = event.subject_hash
        if not subject_hash:
            continue
        if event.event_type == "sidecar_unhealthy":
            pending.setdefault(subject_hash, observed_at)
            continue
        unhealthy_at = pending.pop(subject_hash, None)
        if unhealthy_at is None or observed_at < unhealthy_at:
            continue
        values.append((observed_at - unhealthy_at).total_seconds() * 1000)
    return _latency_values(values, window_days)


def _parse_metric_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latency_values(values: Sequence[float], window_days: int) -> dict[str, object]:
    ordered = sorted(value for value in values if value >= 0)
    if not ordered:
        return {
            "p50_ms": None,
            "p95_ms": None,
            "numerator": 0,
            "denominator": 0,
            "sample_size": 0,
            "window_days": window_days,
            "evidence_status": "insufficient_sample",
        }
    return {
        "p50_ms": ordered[(len(ordered) - 1) // 2],
        "p95_ms": ordered[max(0, min(len(ordered) - 1, int((len(ordered) - 1) * 0.95)))],
        "numerator": len(ordered),
        "denominator": len(ordered),
        "sample_size": len(ordered),
        "window_days": window_days,
        "evidence_status": "sufficient" if len(ordered) >= 20 else "insufficient_sample",
    }


def _confirmation_metric(events: Sequence[MetricEvent], window_days: int) -> dict[str, object]:
    durations: list[float] = []
    queue_depths: list[int] = []
    revoked = 0
    for event in events:
        if event.event_type != "action_attempted":
            continue
        raw_duration = event.dimensions.get("confirmation_duration_ms")
        if raw_duration is None:
            continue
        try:
            duration = float(raw_duration)
            queue_depth = int(event.dimensions.get("queue_depth", "0"))
        except (TypeError, ValueError):
            continue
        if duration < 0 or queue_depth < 0:
            continue
        durations.append(duration)
        queue_depths.append(queue_depth)
        revoked += int(event.dimensions.get("revoked") == "true")
    if not durations:
        return {
            "p50_ms": None,
            "p95_ms": None,
            "queue_peak": None,
            "revocation_count": 0,
            "numerator": 0,
            "denominator": 0,
            "sample_size": 0,
            "window_days": window_days,
            "evidence_status": "insufficient_sample",
        }
    values = sorted(durations)
    return {
        "p50_ms": values[(len(values) - 1) // 2],
        "p95_ms": values[max(0, min(len(values) - 1, int((len(values) - 1) * 0.95)))],
        "queue_peak": max(queue_depths, default=0),
        "revocation_count": revoked,
        "numerator": len(values),
        "denominator": len(values),
        "sample_size": len(values),
        "window_days": window_days,
        "evidence_status": "sufficient" if len(values) >= 20 else "insufficient_sample",
    }
