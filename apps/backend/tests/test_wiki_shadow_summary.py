import json
from datetime import datetime, timedelta, timezone

from app.services.wiki.shadow import ShadowMetrics, ShadowMetricStore
from tests.conftest import auth_headers
from tests.test_wiki_shadow import metric_store


def test_summary_counts_only_valid_recent_samples_without_writing(tmp_path):
    store = metric_store(tmp_path)
    now = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    completed = store.reserve(now=now - timedelta(minutes=1))
    store.finish(completed, ShadowMetrics(
        status="completed", page_read_count=2, note_read_count=1, authority="denied",
        coverage="partial", conflict="disputed", budget_exhausted=True,
        assessment_calls=2, evidence_chars=200, latency_ms=1000,
    ), now=now)
    store.reserve(now=now)
    failed = store.reserve(now=now)
    store.finish(failed, ShadowMetrics(status="failed"), now=now)
    store.reserve(now=now - timedelta(days=8))
    with store.database.session() as conn:
        before = conn.execute(
            "SELECT value FROM app_state WHERE key = 'wiki_shadow_metrics_v1'"
        ).fetchone()["value"]
    summary = store.summary(now=now)
    assert summary.samples == 3 and summary.today_samples == 3
    assert summary.completed == summary.failed == summary.unfinished == 1
    assert summary.wiki_hits == summary.note_fallbacks == summary.authority_denied == 1
    assert summary.disputed == summary.budget_exhausted == 1
    assert summary.coverage_complete == 0
    assert summary.mean_latency_ms == 1000 and summary.assessment_calls == 2
    with store.database.session() as conn:
        assert conn.execute(
            "SELECT value FROM app_state WHERE key = 'wiki_shadow_metrics_v1'"
        ).fetchone()["value"] == before


def test_settings_summary_is_authenticated_aggregate_and_corruption_safe(client_factory):
    with client_factory() as client:
        database = client.app.state.database
        now = datetime.now(timezone.utc).isoformat()
        records = [
            {"id": "PRIVATE_SAMPLE", "created_at": now,
             "metrics": ShadowMetrics(status="completed").model_dump()},
            {"id": "PRIVATE_SAMPLE_2", "created_at": now,
             "metrics": {"question": "PRIVATE_QUESTION", "relative_path": "PRIVATE_PATH"}},
        ]
        with database.session() as conn:
            conn.execute(
                "UPDATE app_state SET value = ? WHERE key = 'wiki_shadow_metrics_v1'",
                (json.dumps(records),),
            )
        assert client.get("/api/settings").status_code == 401
        response = client.get("/api/settings", headers=auth_headers())
        assert response.status_code == 200
        payload = response.json()["wiki_shadow_metrics"]
        assert payload["samples"] == 1 and payload["invalid_records"] == 1
        assert "PRIVATE_" not in json.dumps(payload)
        assert all(isinstance(value, (bool, int)) or value is None for value in payload.values())
        with database.session() as conn:
            conn.execute(
                "UPDATE app_state SET value = ? WHERE key = 'wiki_shadow_metrics_v1'",
                ("PRIVATE_INVALID_JSON",),
            )
        unavailable = client.get("/api/settings", headers=auth_headers())
        assert unavailable.status_code == 200
        assert unavailable.json()["wiki_shadow_metrics"]["available"] is False
        assert "PRIVATE_INVALID_JSON" not in unavailable.text
