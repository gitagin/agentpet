from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.enums import MemoryFactStatus
from app.services.memory_candidates import MemoryCandidateCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from tests.conftest import assert_error_shape, auth_headers


def auth() -> dict[str, str]:
    return auth_headers()


def bind_vault(client: TestClient, tmp_path: Path) -> None:
    vault = tmp_path / "Vault"
    vault.mkdir()
    response = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert response.status_code == 200


def create_fact(client: TestClient, *, subject: str, object_value: str, memory_type: str = "preference") -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=memory_type,
                memory_type=memory_type,
                subject=subject,
                predicate="is",
                object=object_value,
                source_text=f"{subject} is {object_value}.",
                confidence=0.9,
                importance=0.8,
            )
        ).fact
        assert fact.status is MemoryFactStatus.ACTIVE
        return fact.id
    finally:
        service.close()


def create_candidate(
    client: TestClient,
    *,
    summary: str,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.CANDIDATE,
) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        return service.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=kind,
                memory_scope=scope,
                summary=summary,
                normalized_value=summary.casefold(),
                source_text=summary,
                source_track=SourceTrack.EXPLICIT_USER,
                risk_tier=RiskTier.LOW,
                confidence=0.9,
                importance=0.7,
                status=status,
            )
        ).id
    finally:
        service.close()


def post_feedback(client: TestClient, payload: dict[str, object]):
    return client.post("/api/memory/feedback", headers=auth(), json=payload)


def search_personal_memory(client: TestClient, query: str) -> list[dict[str, object]]:
    response = client.post(
        "/api/memory/search",
        headers=auth(),
        json={"query": query, "top_k": 5, "source_scope": "personal_memory"},
    )
    assert response.status_code == 200
    return response.json()["results"]


def db_row(client: TestClient, sql: str, params: tuple[object, ...] = ()) -> sqlite3.Row:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row


def test_forget_fact_removes_it_from_search_and_records_feedback(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        bind_vault(client, tmp_path)
        fact_id = create_fact(client, subject="favorite fruit feedback api", object_value="mango")

        assert any(result.get("fact_id") == fact_id for result in search_personal_memory(client, "mango"))

        response = post_feedback(
            client,
            {
                "target_type": "fact",
                "target_id": fact_id,
                "operation": "forget",
                "feedback_text": "That is not what I meant.",
                "source_conversation_id": "conv-feedback-1",
                "source_message_id": "msg-feedback-1",
                "source_agent_run_id": "run-feedback-1",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "forgotten"
        assert payload["feedback_event_id"]
        assert payload["action_id"]
        assert not any(result.get("fact_id") == fact_id for result in search_personal_memory(client, "mango"))

        feedback = db_row(client, "SELECT * FROM memory_feedback_events WHERE id = ?", (payload["feedback_event_id"],))
        lifecycle = db_row(
            client,
            "SELECT * FROM memory_lifecycle_events WHERE fact_id = ? ORDER BY created_at DESC LIMIT 1",
            (fact_id,),
        )
        action = db_row(client, "SELECT * FROM agent_actions WHERE id = ?", (payload["action_id"],))
        assert feedback["fact_id"] == fact_id
        assert feedback["feedback_type"] == "forget"
        assert feedback["requested_status"] == "forgotten"
        assert feedback["agent_action_id"] == payload["action_id"]
        assert lifecycle["to_status"] == "forgotten"
        assert action["action_type"] == "memory.feedback.apply"


def test_edit_fact_supersedes_old_fact_and_recalls_replacement(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        bind_vault(client, tmp_path)
        old_fact_id = create_fact(client, subject="preferred snack feedback api", object_value="mango")

        response = post_feedback(
            client,
            {
                "target_type": "fact",
                "target_id": old_fact_id,
                "operation": "edit",
                "feedback_text": "I meant pear.",
                "replacement_object": "pear",
            },
        )

        assert response.status_code == 200
        payload = response.json()
        replacement_id = payload["replacement_target_id"]
        assert payload["status"] == "superseded"
        assert replacement_id
        observation = db_row(
            client,
            "SELECT status, query_count FROM product_metric_correction_observations",
        )
        assert observation["status"] == "pending"
        assert observation["query_count"] == 0
        assert not any(result.get("fact_id") == old_fact_id for result in search_personal_memory(client, "mango"))
        assert any(result.get("fact_id") == replacement_id for result in search_personal_memory(client, "pear"))

        observation = db_row(
            client,
            "SELECT status, query_count FROM product_metric_correction_observations",
        )
        assert observation["status"] == "verified"
        assert observation["query_count"] == 1

        old_fact = db_row(client, "SELECT status, metadata_json FROM memory_graph_facts WHERE id = ?", (old_fact_id,))
        replacement = db_row(client, "SELECT status, object FROM memory_graph_facts WHERE id = ?", (replacement_id,))
        feedback = db_row(client, "SELECT metadata_json FROM memory_feedback_events WHERE id = ?", (payload["feedback_event_id"],))
        assert old_fact["status"] == "superseded"
        assert "superseded_by" not in json.loads(old_fact["metadata_json"])
        relation = db_row(
            client,
            """
            SELECT subject_fact_id
            FROM memory_graph_facts
            WHERE statement_kind = 'relation'
              AND relation_type = 'supersedes'
              AND object_fact_id = ?
              AND status = 'active'
            """,
            (old_fact_id,),
        )
        assert relation["subject_fact_id"] == replacement_id
        assert replacement["status"] == "active"
        assert replacement["object"] == "pear"
        assert json.loads(feedback["metadata_json"])["replacement_target_id"] == replacement_id


def test_candidate_feedback_operations_update_state_and_events(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        keep_id = create_candidate(client, summary="Use concise status updates.")
        reject_id = create_candidate(client, summary="Draft low confidence candidate.")
        stale_id = create_candidate(client, summary="Old preference to revisit.", status=LifecycleStatus.ACTIVE)
        temporary_id = create_candidate(client, summary="Only use focused mode today.", status=LifecycleStatus.ACTIVE)
        completed_id = create_candidate(
            client,
            summary="User is working on Feedback API.",
            kind=MemoryKind.PROJECT_CONTEXT,
            scope=MemoryScope.PROJECT,
            status=LifecycleStatus.ACTIVE,
        )

        assert post_feedback(client, {"target_type": "candidate", "target_id": keep_id, "operation": "keep"}).json()["status"] == "active"
        assert post_feedback(
            client,
            {"target_type": "candidate", "target_id": reject_id, "operation": "reject_candidate"},
        ).json()["status"] == "rejected"
        assert post_feedback(
            client,
            {"target_type": "candidate", "target_id": stale_id, "operation": "mark_stale"},
        ).json()["status"] == "stale"
        temporary = post_feedback(
            client,
            {
                "target_type": "candidate",
                "target_id": temporary_id,
                "operation": "make_temporary",
                "expires_at": "2026-06-07T23:59:59+08:00",
            },
        )
        completed = post_feedback(
            client,
            {"target_type": "candidate", "target_id": completed_id, "operation": "mark_completed"},
        )

        assert temporary.status_code == 200
        assert completed.status_code == 200
        assert temporary.json()["status"] == "active"
        assert completed.json()["status"] == "archived"
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.row_factory = sqlite3.Row
            statuses = {
                row["id"]: row
                for row in conn.execute(
                    "SELECT id, status, memory_kind, memory_scope, expires_at FROM memory_candidates"
                ).fetchall()
            }
            feedback_count = conn.execute("SELECT COUNT(*) FROM memory_feedback_events").fetchone()[0]
        assert statuses[keep_id]["status"] == "active"
        assert statuses[reject_id]["status"] == "rejected"
        assert statuses[stale_id]["status"] == "stale"
        assert statuses[temporary_id]["memory_kind"] == "recent_state"
        assert statuses[temporary_id]["memory_scope"] == "temporary"
        assert statuses[temporary_id]["expires_at"] == "2026-06-07T23:59:59+08:00"
        assert statuses[completed_id]["status"] == "archived"
        assert feedback_count == 5


def test_weekly_memory_review_lists_safe_categories_and_applies_actions(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        active_fact_id = create_fact(client, subject="weekly review preference", object_value="brief")
        project_fact_id = create_fact(
            client,
            subject="weekly project alpha",
            object_value="active",
            memory_type="project_context",
        )
        candidate_id = create_candidate(client, summary="Maybe use weekly planning prompts.")
        temporary_id = create_candidate(
            client,
            summary="Use review mode this week.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            status=LifecycleStatus.ACTIVE,
        )

        response = client.get("/api/memory/reviews/weekly?days=7", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        assert payload["window_days"] == 7
        assert payload["summary"]["kept"] >= 2
        assert payload["summary"]["temporary"] >= 1
        assert payload["summary"]["ignored"] >= 1
        items = {item["target_id"]: item for item in payload["items"]}
        assert items[active_fact_id]["category"] == "kept"
        assert items[candidate_id]["category"] == "ignored"
        assert items[temporary_id]["category"] == "temporary"
        assert "mark_completed" in items[project_fact_id]["allowed_actions"]
        assert "only_this_week" in items[active_fact_id]["allowed_actions"]

        only_week = client.post(
            "/api/memory/reviews/weekly/actions",
            headers=auth(),
            json={"target_type": "fact", "target_id": active_fact_id, "action": "only_this_week"},
        )
        completed = client.post(
            "/api/memory/reviews/weekly/actions",
            headers=auth(),
            json={"target_type": "fact", "target_id": project_fact_id, "action": "mark_completed"},
        )

        assert only_week.status_code == 200
        assert only_week.json()["operation"] == "make_temporary"
        assert completed.status_code == 200
        assert completed.json()["status"] == "archived"
        temporary_fact = db_row(client, "SELECT memory_type, expires_at FROM memory_graph_facts WHERE id = ?", (active_fact_id,))
        archived_project = db_row(client, "SELECT status FROM memory_graph_facts WHERE id = ?", (project_fact_id,))
        review_action_count = db_row(
            client,
            "SELECT COUNT(*) AS count FROM audit_logs WHERE action = ?",
            ("memory.review.action",),
        )
        assert temporary_fact["memory_type"] == "recent_state"
        assert temporary_fact["expires_at"]
        assert archived_project["status"] == "archived"
        assert review_action_count["count"] == 2


def test_weekly_memory_review_redacts_sensitive_summary(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="token=sk-review-secret-1234567890")

        response = client.get("/api/memory/reviews/weekly", headers=auth())

        assert response.status_code == 200
        body = response.text
        payload = response.json()
        item = next(item for item in payload["items"] if item["target_id"] == candidate_id)
        assert item["summary"] == "[redacted sensitive content]"
        assert "sk-review-secret" not in body
        assert "token=" not in body


def test_feedback_errors_keep_api_error_shape(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        response = post_feedback(
            client,
            {
                "target_type": "fact",
                "target_id": "missing-fact-id",
                "operation": "forget",
                "feedback_text": "No such memory.",
            },
        )

        assert response.status_code == 404
        assert_error_shape(response.json())
        assert response.json()["error"]["code"] == "memory_feedback_target_not_found"
