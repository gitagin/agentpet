import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.services.product_metrics import MetricPayloadConflict, ProductMetricsService
from app.storage.database import Database, MigrationRunner
from apps.backend.tests.conftest import auth_headers


def _db(tmp_path):
    path = tmp_path / "sidecar-metrics.sqlite3"
    db = Database(path)
    MigrationRunner(db).apply()
    return path


def test_sidecar_recovery_records_one_paired_incident_and_replays(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    unhealthy_at = datetime(2026, 8, 11, 8, 0, tzinfo=timezone.utc).isoformat()
    ready_at = (datetime.fromisoformat(unhealthy_at) + timedelta(seconds=12.5)).isoformat()
    try:
        first = service.record_sidecar_recovery(
            incident_id="a" * 32,
            unhealthy_at=unhealthy_at,
            ready_at=ready_at,
            cause="process_exited",
        )
        replay = service.record_sidecar_recovery(
            incident_id="a" * 32,
            unhealthy_at=unhealthy_at,
            ready_at=ready_at,
            cause="process_exited",
        )

        assert first[2] is False
        assert replay[2] is True
        assert replay[0].id == first[0].id
        assert replay[1].id == first[1].id
        observed = service.read_sidecar_recovery(
            incident_id="a" * 32,
            unhealthy_at=unhealthy_at,
            ready_at=ready_at,
            cause="process_exited",
        )
        assert observed is not None
        assert observed["unhealthy_event_id"] == first[0].id
        assert observed["ready_event_id"] == first[1].id
        assert service.aggregate(window_days=7)["metrics"]["recovery_time_ms"]["sample_size"] == 1
    finally:
        service.close()


def test_sidecar_recovery_rejects_payload_conflict_and_unpaired_ready_is_ignored(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    ready_at = datetime.now(timezone.utc).isoformat()
    try:
        service.record(
            event_type="sidecar_ready",
            idempotency_key="sidecar-recovery:unpaired:ready",
            subject_id="sidecar-incident:unpaired",
            dimensions={"incident_state": "ready"},
            created_at=ready_at,
        )
        assert service.aggregate(window_days=7)["metrics"]["recovery_time_ms"]["sample_size"] == 0

        incident_id = "b" * 32
        service.record_sidecar_recovery(
            incident_id=incident_id,
            unhealthy_at=ready_at,
            ready_at=ready_at,
            cause="spawn_failed",
        )
        with pytest.raises(MetricPayloadConflict):
            service.record_sidecar_recovery(
                incident_id=incident_id,
                unhealthy_at=ready_at,
                ready_at=ready_at,
                cause="startup_failed",
            )
    finally:
        service.close()


def test_authenticated_sidecar_recovery_api_persists_and_reads_back_the_pair(client_factory):
    incident_id = "c" * 32
    payload = {
        "incident_id": incident_id,
        "unhealthy_at": "2026-08-11T08:00:00Z",
        "ready_at": "2026-08-11T08:00:12.500Z",
        "cause": "process_exited",
        "restart_attempt": 2,
    }
    idempotency_key = hashlib.sha256(
        f"sidecar-recovery:{incident_id}".encode("utf-8")
    ).hexdigest()
    headers = {**auth_headers(), "Idempotency-Key": idempotency_key}

    with client_factory() as client:
        unauthorized = client.post(
            "/api/metrics/sidecar-recovery",
            headers={"Idempotency-Key": idempotency_key},
            json=payload,
        )
        first = client.post("/api/metrics/sidecar-recovery", headers=headers, json=payload)
        replay = client.post("/api/metrics/sidecar-recovery", headers=headers, json=payload)
        conflict = client.post(
            "/api/metrics/sidecar-recovery",
            headers=headers,
            json={**payload, "restart_attempt": 3},
        )

        assert unauthorized.status_code == 401
        assert first.status_code == 200
        assert first.json() == {
            "status": "recorded",
            "incident_id": incident_id,
            "unhealthy_event_id": first.json()["unhealthy_event_id"],
            "ready_event_id": first.json()["ready_event_id"],
            "recovery_time_ms": 12_500,
        }
        assert replay.status_code == 200
        assert replay.json() == {**first.json(), "status": "replayed"}
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_payload_conflict"

        impact = client.get("/api/metrics/local-impact", headers=auth_headers()).json()
        assert impact["metrics"]["recovery_time_ms"]["sample_size"] == 1
        with sqlite3.connect(client.app.state.database.path) as conn:
            rows = conn.execute(
                """
                SELECT event_type, subject_hash, dimensions_json
                FROM product_metric_events
                WHERE event_type IN ('sidecar_unhealthy', 'sidecar_ready')
                ORDER BY created_at
                """
            ).fetchall()
        assert [row[0] for row in rows] == ["sidecar_unhealthy", "sidecar_ready"]
        assert rows[0][1] == rows[1][1]
        assert rows[0][1] != incident_id
        assert json.loads(rows[0][2]) == {
            "failure_code": "process_exited",
            "incident_state": "unhealthy",
            "restart_attempt": "2",
        }
