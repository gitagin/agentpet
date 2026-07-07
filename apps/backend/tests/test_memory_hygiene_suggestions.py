from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_hygiene_suggestions import MemoryHygieneSuggestionService
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from tests.conftest import assert_error_shape, auth_headers


NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def auth() -> dict[str, str]:
    return auth_headers()


def create_candidate(
    client: TestClient,
    *,
    summary: str,
    normalized_value: str | None = None,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
    risk_tier: RiskTier = RiskTier.LOW,
    confidence: float = 0.9,
    expires_at: str | None = None,
) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        return service.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=kind,
                memory_scope=scope,
                summary=summary,
                normalized_value=normalized_value or summary.casefold(),
                source_text=summary,
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                risk_tier=risk_tier,
                confidence=confidence,
                importance=0.6,
                status=status,
                expires_at=expires_at,
            )
        ).id
    finally:
        service.close()


def create_recent_state_fact(client: TestClient, *, expires_at: str) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.RECENT_STATE.value,
                memory_type=MemoryKind.RECENT_STATE.value,
                subject="current focus",
                predicate="is",
                object="temporary",
                source_text="Current focus is temporary.",
                confidence=0.9,
                expires_at=expires_at,
            )
        ).fact
        return fact.id
    finally:
        service.close()


def create_conflicting_facts(client: TestClient) -> tuple[str, str]:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        old = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="hygiene conflict snack",
                predicate="is",
                object="mango",
                source_text="Snack is mango.",
                confidence=0.7,
            )
        ).fact
        new = service.graph.insert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="hygiene conflict snack",
                predicate="is",
                object="pear",
                source_text="Snack is pear.",
                confidence=0.95,
            )
        ).fact
        service.graph.update_status(new.id, MemoryFactStatus.ACTIVE, reason="test_active_conflict")
        return old.id, new.id
    finally:
        service.close()


def set_candidate_updated_at(client: TestClient, candidate_id: str, updated_at: str) -> None:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute("UPDATE memory_candidates SET updated_at = ? WHERE id = ?", (updated_at, candidate_id))


def db_counts(client: TestClient) -> dict[str, int]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        return {
            "lifecycle": conn.execute("SELECT COUNT(*) FROM memory_lifecycle_events").fetchone()[0],
            "actions": conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0],
            "audit": conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0],
        }


def candidate_status(client: TestClient, candidate_id: str) -> str:
    with sqlite3.connect(client.app.state.database.path) as conn:
        return str(conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()[0])


def fact_status(client: TestClient, fact_id: str) -> str:
    with sqlite3.connect(client.app.state.database.path) as conn:
        return str(conn.execute("SELECT status FROM memory_graph_facts WHERE id = ?", (fact_id,)).fetchone()[0])


def preview(client: TestClient) -> dict[str, object]:
    response = client.get("/api/memory/hygiene/preview", headers=auth())
    assert response.status_code == 200
    return response.json()


def suggestion_by_type(payload: dict[str, object], suggestion_type: str) -> dict[str, object]:
    suggestions = payload["suggestions"]
    assert isinstance(suggestions, list)
    return next(item for item in suggestions if item["type"] == suggestion_type)


def assert_safe_payload(payload: object, forbidden_values: tuple[str, ...] = ()) -> None:
    text = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = (
        "candidate_id",
        "fact_id",
        "source_text",
        "source_excerpt",
        "raw_evidence",
        "evidence_id",
        "authorization",
        "bearer",
        "agent_run_id",
        "memory_candidates",
        "lifecycle_status",
        "c:\\",
        "/users/",
        "token=",
        *[value.lower() for value in forbidden_values],
    )
    for value in forbidden:
        assert value not in text


def test_preview_is_read_only_and_returns_safe_suggestions(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        stale_id = create_candidate(
            client,
            summary="Temporary focus for cleanup.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-05-01T00:00:00Z",
        )
        low_id = create_candidate(
            client,
            summary="Maybe the user likes noisy summaries.",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.2,
        )
        set_candidate_updated_at(client, low_id, "2026-04-01T00:00:00Z")
        sensitive_id = create_candidate(
            client,
            summary="Authorization: Bearer token=sk-hygiene-secret from C:\\Users\\Ada\\Vault\\secret.md",
            status=LifecycleStatus.ACTIVE,
            confidence=0.9,
        )
        before = db_counts(client)

        payload = preview(client)

        assert {item["type"] for item in payload["suggestions"]} >= {
            "stale_recent_state",
            "low_confidence_stale",
            "sensitive_candidate",
        }
        assert db_counts(client) == before
        assert candidate_status(client, stale_id) == "active"
        assert candidate_status(client, low_id) == "candidate"
        assert candidate_status(client, sensitive_id) == "active"
        assert_safe_payload(
            payload,
            (
                stale_id,
                low_id,
                sensitive_id,
                "sk-hygiene-secret",
                "secret.md",
                "noisy summaries",
            ),
        )


def test_confirmed_false_rejects_apply_without_writing(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Temporary status without confirmation.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-05-01T00:00:00Z",
        )
        item = suggestion_by_type(preview(client), "stale_recent_state")
        before = db_counts(client)

        response = client.post(
            "/api/memory/hygiene/actions",
            headers=auth(),
            json={"suggestion_id": item["id"], "confirmed": False},
        )

        assert response.status_code == 400
        assert_error_shape(response.json())
        assert response.json()["error"]["code"] == "hygiene_confirmation_required"
        assert db_counts(client) == before
        assert candidate_status(client, candidate_id) == "active"


def test_apply_stale_recent_state_archives_candidate_and_fact(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Temporary state to archive.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-05-01T00:00:00Z",
        )
        fact_id = create_recent_state_fact(client, expires_at="2026-05-01T00:00:00Z")
        payload = preview(client)

        for item in [item for item in payload["suggestions"] if item["type"] == "stale_recent_state"]:
            response = client.post(
                "/api/memory/hygiene/actions",
                headers=auth(),
                json={"suggestion_id": item["id"], "confirmed": True},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "archived"

        assert candidate_status(client, candidate_id) == "archived"
        assert fact_status(client, fact_id) == "archived"


def test_apply_low_confidence_stale_rejects_candidate(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Maybe use old planning prompts.",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.2,
        )
        set_candidate_updated_at(client, candidate_id, "2026-04-01T00:00:00Z")
        item = suggestion_by_type(preview(client), "low_confidence_stale")

        response = client.post(
            "/api/memory/hygiene/actions",
            headers=auth(),
            json={"suggestion_id": item["id"], "confirmed": True},
        )

        assert response.status_code == 200
        assert response.json()["type"] == "low_confidence_stale"
        assert response.json()["status"] == "rejected"
        assert candidate_status(client, candidate_id) == "rejected"


def test_apply_sensitive_candidate_rejects_candidate_and_records_safe_action(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="token=sk-hygiene-sensitive Authorization: Bearer secret from C:\\Users\\Ada\\Vault\\secret.md",
            status=LifecycleStatus.ACTIVE,
            confidence=0.9,
        )
        item = suggestion_by_type(preview(client), "sensitive_candidate")

        response = client.post(
            "/api/memory/hygiene/actions",
            headers=auth(),
            json={"suggestion_id": item["id"], "confirmed": True},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "sensitive_candidate"
        assert body["status"] == "rejected"
        assert candidate_status(client, candidate_id) == "rejected"
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            action = conn.execute("SELECT * FROM agent_actions WHERE id = ?", (body["action_id"],)).fetchone()
        assert action["action_type"] == "memory.hygiene.apply"
        metadata = json.loads(action["metadata_json"])
        assert metadata == {
            "suggestion_type": "sensitive_candidate",
            "suggestion_id": body["suggestion_id"],
            "result_status": "rejected",
            "safe_summary": True,
        }
        assert_safe_payload(
            {"summary": action["summary"], "metadata": metadata},
            (candidate_id, "sk-hygiene-sensitive", "secret.md"),
        )


def test_apply_revalidates_suggestion_and_returns_safe_expired_error(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Temporary state that changes before apply.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-05-01T00:00:00Z",
        )
        item = suggestion_by_type(preview(client), "stale_recent_state")
        service = MemoryLifecycleService(client.app.state.database.path)
        try:
            service.transition_candidate(candidate_id, LifecycleStatus.ARCHIVED, reason="test_changed_before_apply")
        finally:
            service.close()

        response = client.post(
            "/api/memory/hygiene/actions",
            headers=auth(),
            json={"suggestion_id": item["id"], "confirmed": True},
        )

        assert response.status_code == 409
        assert_error_shape(response.json())
        assert response.json()["error"]["code"] == "hygiene_suggestion_expired"
        assert_safe_payload(response.json(), (candidate_id,))


def test_duplicate_and_conflict_are_not_applyable_suggestions(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        create_candidate(
            client,
            summary="User prefers short summaries.",
            normalized_value="reply_style=short",
            status=LifecycleStatus.ACTIVE,
        )
        create_candidate(
            client,
            summary="Use short summaries.",
            normalized_value="reply_style=short",
            status=LifecycleStatus.CANDIDATE,
        )
        create_conflicting_facts(client)

        payload = preview(client)

        types = {item["type"] for item in payload["suggestions"]}
        assert "duplicate_candidate" not in types
        assert "conflicting_fact" not in types
        assert "completed_project_state" not in types


def test_service_preview_is_read_only_without_api_audit(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Temporary service-level status.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
            expires_at="2026-05-01T00:00:00Z",
        )
        service = MemoryHygieneSuggestionService(client.app.state.database.path, now_provider=lambda: NOW)
        try:
            before = db_counts(client)
            suggestions = service.preview()
        finally:
            service.close()

        assert any(item.type == "stale_recent_state" for item in suggestions)
        assert db_counts(client) == before
        assert candidate_status(client, candidate_id) == "active"


def test_no_vault_or_markdown_files_are_created(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(
            client,
            summary="Maybe use old cleanup prompts.",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.2,
        )
        set_candidate_updated_at(client, candidate_id, "2026-04-01T00:00:00Z")
        item = suggestion_by_type(preview(client), "low_confidence_stale")

        response = client.post(
            "/api/memory/hygiene/actions",
            headers=auth(),
            json={"suggestion_id": item["id"], "confirmed": True},
        )

        assert response.status_code == 200
        markdown_files = [
            path
            for path in tmp_path.rglob("*.md")
            if ".pytest_cache" not in path.parts
        ]
        assert markdown_files == []
