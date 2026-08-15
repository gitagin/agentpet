import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.product_metrics import MetricPayloadConflict, MetricValidationError, ProductMetricsService
from apps.backend.tests.conftest import auth_headers


def _db(tmp_path):
    from app.storage.database import Database, MigrationRunner

    path = tmp_path / "metrics.sqlite3"
    db = Database(path)
    MigrationRunner(db).apply()
    return path


def test_metric_events_are_anonymous_and_idempotent(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    first = service.record(
        event_type="feedback_recorded",
        idempotency_key="feedback:one",
        subject_id="fact-private-id",
        dimensions={"feedback": "helpful"},
    )
    replay = service.record(
        event_type="feedback_recorded",
        idempotency_key="feedback:one",
        subject_id="fact-private-id",
        dimensions={"feedback": "helpful"},
    )
    assert replay.id == first.id
    assert replay.subject_hash != "fact-private-id"
    with pytest.raises(MetricPayloadConflict):
        service.record(
            event_type="feedback_recorded",
            idempotency_key="feedback:one",
            subject_id="fact-private-id",
            dimensions={"feedback": "incorrect"},
        )
    service.close()


def test_metric_aggregation_reports_insufficient_sample(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    service.record(
        event_type="grounded_answer",
        idempotency_key="answer:one",
        dimensions={"citation_valid": "true"},
    )
    report = service.aggregate(window_days=7)
    assert report["evidence_status"] == "insufficient_sample"
    assert report["metrics"]["source_coverage_rate"]["numerator"] == 1
    assert report["metrics"]["source_coverage_rate"]["denominator"] == 1
    service.close()


def test_operational_events_do_not_inflate_feedback_sample_size(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    try:
        service.record(
            event_type="feedback_recorded",
            idempotency_key="feedback:sample",
            subject_id="answer_public_sample",
            dimensions={"feedback": "helpful"},
        )
        service.record(
            event_type="action_attempted",
            idempotency_key="action:sample",
            subject_id="action_public_sample",
            dimensions={"action_type": "metrics.feedback", "status": "verified"},
        )
        service.record(
            event_type="business_effect_committed",
            idempotency_key="effect:sample",
            subject_id="action_public_sample",
            dimensions={"action_type": "metrics.feedback", "effect_id_hash": "a" * 64},
        )

        report = service.aggregate(window_days=7)
        assert report["sample_size"] == 1
        assert report["evidence_status"] == "insufficient_sample"
        assert report["metrics"]["duplicate_effect_rate"]["denominator"] == 1
    finally:
        service.close()


def test_unknown_metric_dimension_is_rejected(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    with pytest.raises(MetricValidationError):
        service.record(
            event_type="recalled",
            idempotency_key="recall:one",
            dimensions={"raw_text": "must-not-be-stored"},
        )
    service.close()


def test_lookup_and_context_metrics_keep_explicit_samples(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    service.record(
        event_type="lookup_completed",
        idempotency_key="lookup:one",
        subject_id="answer-public-one",
        value=245,
        dimensions={"duration_ms": 245, "has_citation": True},
    )
    service.record(
        event_type="context_repetition_reported",
        idempotency_key="context:one",
        subject_id="answer-public-one",
        value=2,
        dimensions={"signal": "context_repeated", "repetition_count": 2},
    )
    report = service.aggregate(window_days=7)
    assert report["metrics"]["lookup_duration"]["p50_ms"] == 245
    assert report["metrics"]["context_repetition_rate"]["numerator"] == 1
    assert report["metrics"]["context_repetition_rate"]["denominator"] == 1
    service.close()


def test_recall_feedback_uses_lifecycle_and_replays_original_receipt(client_factory, tmp_path):
    data_dir = tmp_path / "data"
    idempotency_key = "c" * 64
    headers = {**auth_headers(), "Idempotency-Key": idempotency_key}
    payload = {
        "signal": "helpful",
        "reference": "answer-public-one",
        "source_scope": "personal_memory",
        "duration_ms": 120,
    }
    with client_factory(data_dir=data_dir) as client:
        missing_key = client.post(
            "/api/metrics/recall-feedback",
            headers=auth_headers(),
            json=payload,
        )
        invalid_key = client.post(
            "/api/metrics/recall-feedback",
            headers={**auth_headers(), "Idempotency-Key": "C" * 64},
            json=payload,
        )
        first = client.post("/api/metrics/recall-feedback", headers=headers, json=payload)
        replay = client.post("/api/metrics/recall-feedback", headers=headers, json=payload)
        conflict = client.post(
            "/api/metrics/recall-feedback",
            headers=headers,
            json={**payload, "signal": "incorrect"},
        )

        assert missing_key.status_code == 422
        assert invalid_key.status_code == 422
        assert first.status_code == 200
        assert first.json()["status"] == "recorded"
        assert first.json()["signal"] == "helpful"
        assert replay.status_code == 200
        assert replay.json() == {**first.json(), "status": "replayed"}
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_payload_conflict"

        impact = client.get("/api/metrics/local-impact", headers=auth_headers()).json()
        assert impact["sample_size"] == 1
        assert impact["metrics"]["memory_recall_success_rate"]["numerator"] == 1
        assert impact["metrics"]["memory_recall_success_rate"]["denominator"] == 1

        with sqlite3.connect(client.app.state.database.path) as conn:
            row = conn.execute(
                "SELECT subject_hash, dimensions_json FROM product_metric_events WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            actions = conn.execute(
                "SELECT status, metadata_json FROM agent_actions WHERE action_type = 'metrics.feedback' ORDER BY created_at"
            ).fetchall()
        assert row is not None
        assert row[0] != "answer-public-one"
        assert "answer-public-one" not in row[1]
        assert len(actions) == 2
        assert actions[0][0] == "completed"
        assert actions[1][0] == "failed_recovery"


def test_installation_secret_persists_across_path_and_connection_instances(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_PET_ALLOW_INSECURE_FILE_CREDENTIALS", "1")
    path = _db(tmp_path)
    first = ProductMetricsService(path)
    try:
        expected = first.subject_token("fact_private_stable_identifier")
    finally:
        first.close()

    conn = sqlite3.connect(path)
    second = ProductMetricsService(conn)
    try:
        assert second.subject_token("fact_private_stable_identifier") == expected
    finally:
        second.close()
        conn.close()


def test_invalid_windows_and_non_public_references_are_rejected(client_factory, tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    try:
        with pytest.raises(MetricValidationError, match="metric_window_days_invalid"):
            service.aggregate(window_days=14)
    finally:
        service.close()

    with client_factory(data_dir=tmp_path / "data") as client:
        default_window = client.get("/api/metrics/local-impact", headers=auth_headers())
        thirty_day_window = client.get("/api/metrics/local-impact?window_days=30", headers=auth_headers())
        invalid_window = client.get("/api/metrics/local-impact?window_days=14", headers=auth_headers())
        unsafe_reference = client.post(
            "/api/metrics/recall-feedback",
            headers={**auth_headers(), "Idempotency-Key": "d" * 64},
            json={"signal": "helpful", "reference": "raw-private-text"},
        )
        assert default_window.status_code == 200
        assert default_window.json()["window_days"] == 7
        assert thirty_day_window.status_code == 200
        assert thirty_day_window.json()["window_days"] == 30
        assert invalid_window.status_code == 422
        assert unsafe_reference.status_code == 422


def test_correction_requires_a_later_authoritative_observation(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    try:
        service.record_correction(
            idempotency_key="correction:first",
            old_subject_id="fact_old_stable_identifier",
            replacement_subject_id="fact_new_stable_identifier",
        )
        pending = service.aggregate(window_days=7)["metrics"]["correction_propagation_rate"]
        assert pending["numerator"] == 0
        assert pending["denominator"] == 0

        assert service.observe_corrections(["fact_old_stable_identifier"]) == 1
        assert service.observe_corrections(["fact_new_stable_identifier"]) == 0

        service.record_correction(
            idempotency_key="correction:second",
            old_subject_id="fact_other_old_identifier",
            replacement_subject_id="fact_other_new_identifier",
        )
        assert service.observe_corrections(["fact_other_new_identifier"]) == 1

        observed = service.aggregate(window_days=7)["metrics"]["correction_propagation_rate"]
        assert observed["numerator"] == 1
        assert observed["denominator"] == 2
        statuses = {
            row["status"]
            for row in service.conn.execute(
                "SELECT status FROM product_metric_correction_observations"
            ).fetchall()
        }
        assert statuses == {"failed", "verified"}
    finally:
        service.close()


def test_duplicate_effect_rate_uses_business_subjects(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    try:
        for suffix in ("one", "two"):
            service.record(
                event_type="action_attempted",
                idempotency_key=f"attempt:{suffix}",
                subject_id="action_business_correlation_identifier",
            )
        service.record(
            event_type="duplicate_effect_detected",
            idempotency_key="duplicate:detected",
            subject_id="action_business_correlation_identifier",
        )
        service.record(
            event_type="duplicate_prevented",
            idempotency_key="duplicate:prevented",
            subject_id="action_other_correlation_identifier",
        )

        metric = service.aggregate(window_days=7)["metrics"]["duplicate_effect_rate"]
        assert metric["numerator"] == 1
        assert metric["denominator"] == 1
        assert metric["value"] == 1.0
    finally:
        service.close()


def test_recovery_time_requires_paired_incident_transitions(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    started_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    try:
        service.record(
            event_type="sidecar_ready",
            idempotency_key="ready:unpaired",
            subject_id="sidecar_unpaired_incident_identifier",
            value=1,
            created_at=started_at.isoformat(),
        )
        assert service.aggregate(window_days=7)["metrics"]["recovery_time_ms"]["sample_size"] == 0

        service.record(
            event_type="sidecar_unhealthy",
            idempotency_key="unhealthy:paired",
            subject_id="sidecar_paired_incident_identifier",
            created_at=started_at.isoformat(),
        )
        service.record(
            event_type="sidecar_ready",
            idempotency_key="ready:paired",
            subject_id="sidecar_paired_incident_identifier",
            value=1,
            created_at=(started_at + timedelta(seconds=12.5)).isoformat(),
        )

        metric = service.aggregate(window_days=7)["metrics"]["recovery_time_ms"]
        assert metric["sample_size"] == 1
        assert metric["p50_ms"] == 12_500
        assert metric["p95_ms"] == 12_500
    finally:
        service.close()


def test_confirmation_burden_exposes_queue_and_revocation_counts(tmp_path):
    service = ProductMetricsService(_db(tmp_path), secret=b"test-secret")
    try:
        service.record(
            event_type="action_attempted",
            idempotency_key="confirmation:one",
            subject_id="action_confirmation_identifier",
            dimensions={
                "confirmation_duration_ms": 250,
                "queue_depth": 4,
                "revoked": True,
            },
        )
        metric = service.aggregate(window_days=7)["metrics"]["confirmation_burden"]
        assert metric["p50_ms"] == 250
        assert metric["queue_peak"] == 4
        assert metric["revocation_count"] == 1
    finally:
        service.close()


def test_fixed_metrics_runner_fails_the_current_threshold_fixture(tmp_path):
    repo_root = Path(__file__).resolve().parents[3]
    completed = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "verify_llmwiki_metrics.py"),
            "--fixture",
            str(repo_root / "apps" / "backend" / "tests" / "evals" / "retrieval" / "retrieval-corpus-v1.json"),
            "--out",
            str(tmp_path / "report"),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    summary = json.loads(completed.stdout)
    assert summary["status"] == "failed"
    assert summary["production_evaluator"] == "app.evals.retrieval_eval"
    assert '"status": "passed"' not in completed.stdout
    report = json.loads((tmp_path / "report" / "report.json").read_text(encoding="utf-8"))
    assert report["exit_code"] == 1
    assert report["results"]["production_evaluator"]["module"] == "app.evals.retrieval_eval"
    assert report["results"]["channels"]["sqlite_fts"]["status"] == "failed"
    assert report["results"]["baseline"]["no_evidence_accuracy"]["status"] == "passed"
    assert report["results"]["baseline"]["citation_coverage"]["status"] == "insufficient_sample"
    assert report["results"]["channels"]["sqlite_graph"]["status"] == "passed"
    assert report["results"]["channels"]["sqlite_graph_fallback"]["status"] == "passed"
    assert report["results"]["channels"]["kuzu_acceleration"]["status"] in {
        "passed",
        "not_run",
    }
    assert report["results"]["lifecycle_metrics"]["correction_propagation"]["numerator"] == 3
    assert report["results"]["lifecycle_metrics"]["correction_propagation"]["denominator"] == 3
    assert (
        report["results"]["lifecycle_metrics"]["correction_propagation"]["status"]
        == "insufficient_sample"
    )
    assert report["results"]["ablation"]["status"] == "partial"
    assert report["results"]["ablation"]["llm_extraction_synthesis"]["status"] == "not_run"
    assert (tmp_path / "report" / "production-fts" / "fts-baseline.json").is_file()
    assert (tmp_path / "report" / "graph-lifecycle" / "graph-report.json").is_file()
