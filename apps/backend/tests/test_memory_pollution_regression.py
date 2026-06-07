from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.backend.tests._schema import migrate_db
from app.models.enums import MemoryFactStatus
from app.services.memory_activation import (
    MemoryActivationContext,
    MemoryActivationService,
    activation_item_from_graph_fact,
)
from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_consolidation import MemoryConsolidationService, REDACTED_EVIDENCE
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, SourceTrack
from tests.conftest import auth_headers, parse_sse_events


NOW = datetime(2026, 6, 7, 12, 0, 0, tzinfo=timezone.utc)


def auth() -> dict[str, str]:
    return auth_headers()


def build_consolidation_service(tmp_path: Path) -> tuple[MemoryConsolidationService, Path]:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    service = MemoryConsolidationService(
        MemoryCandidateStore(db_path),
        now_provider=lambda: NOW,
    )
    return service, db_path


def bind_vault(client: TestClient, tmp_path: Path) -> Path:
    vault = tmp_path / "Vault"
    vault.mkdir(exist_ok=True)
    response = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert response.status_code == 200
    return vault


def enable_automation(
    client: TestClient,
    *,
    chat_diary: bool = False,
    structured_memory: bool = False,
    long_term_memory: bool = False,
    wiki_organize: bool = False,
) -> None:
    response = client.put(
        "/api/settings/automation",
        headers=auth(),
        json={
            "auto_chat_diary": chat_diary,
            "auto_structured_memory": structured_memory,
            "auto_long_term_memory": long_term_memory,
            "auto_wiki_organize": wiki_organize,
        },
    )
    assert response.status_code == 200


def stream_chat(client: TestClient, message: str) -> tuple[dict[str, str], list[dict[str, str]]]:
    chat = client.post("/api/chat", headers=auth(), json={"message": message})
    assert chat.status_code == 200
    payload = chat.json()
    with client.stream("GET", payload["stream_url"], headers=auth()) as stream:
        body = "".join(stream.iter_text())
    return payload, parse_sse_events(body)


def create_fact(
    client: TestClient,
    *,
    subject: str,
    object_value: str,
    memory_type: str = "preference",
    confidence: float = 0.9,
) -> str:
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
                confidence=confidence,
                importance=0.8,
            )
        ).fact
        assert fact.status is MemoryFactStatus.ACTIVE
        return fact.id
    finally:
        service.close()


def search_personal_memory(client: TestClient, query: str) -> list[dict[str, object]]:
    response = client.post(
        "/api/memory/search",
        headers=auth(),
        json={"query": query, "top_k": 5, "source_scope": "personal_memory"},
    )
    assert response.status_code == 200
    return response.json()["results"]


def rows(db_path: Path | str, sql: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(sql, params).fetchall()


def test_one_off_emotion_does_not_become_durable_personality_memory(tmp_path: Path) -> None:
    service, db_path = build_consolidation_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="I feel anxious today because the release deadline is close.",
            assistant_answer="Let's keep the next step small.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    candidate = result.items[0].candidate
    assert candidate.memory_kind is MemoryKind.RECENT_STATE
    assert candidate.memory_scope is MemoryScope.TEMPORARY
    assert candidate.status is LifecycleStatus.CANDIDATE
    assert candidate.expires_at == "2026-06-14T12:00:00Z"
    assert candidate.metadata["recall_permissions"]["can_persist"] is False
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_graph_facts")[0]["count"] == 0


def test_jokes_do_not_become_memory_facts(tmp_path: Path) -> None:
    service, db_path = build_consolidation_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="Joking only: I am the mayor of Mars in this silly bit.",
            assistant_answer="I will treat that as a joke, not a fact.",
        )
    finally:
        service.close()

    assert result.candidate_count == 0
    assert result.skipped_reason == "no_signal"
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_candidates")[0]["count"] == 0
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_graph_facts")[0]["count"] == 0


def test_model_summary_does_not_directly_become_long_term_memory(tmp_path: Path) -> None:
    service, db_path = build_consolidation_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="The deploy checklist slipped today.",
            assistant_answer="Summary: the user is an anxious perfectionist person.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    candidate = result.items[0].candidate
    assert candidate.memory_kind is MemoryKind.INFERENCE
    assert candidate.source_track is SourceTrack.MODEL_EXTRACTED
    assert candidate.status is LifecycleStatus.CANDIDATE
    assert candidate.metadata["recall_permissions"]["can_persist"] is False
    assert candidate.metadata["requires_confirmation"] is True
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_graph_facts")[0]["count"] == 0


def test_frequent_complaining_does_not_create_durable_personality_label(tmp_path: Path) -> None:
    service, db_path = build_consolidation_service(tmp_path)
    try:
        for message in (
            "I'm stressed today because the review queue is long.",
            "I'm tired today after context switching.",
            "I'm frustrated today by flaky tests.",
        ):
            service.consolidate(user_message=message, assistant_answer="Small steps.")
    finally:
        service.close()

    candidates = rows(db_path, "SELECT memory_kind, memory_scope, status, expires_at FROM memory_candidates")
    assert candidates
    assert {row["memory_kind"] for row in candidates} == {MemoryKind.RECENT_STATE.value}
    assert {row["memory_scope"] for row in candidates} == {MemoryScope.TEMPORARY.value}
    assert all(row["expires_at"] for row in candidates)
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_graph_facts")[0]["count"] == 0


def test_low_frequency_explicit_boundary_remains_protected(tmp_path: Path) -> None:
    service, _ = build_consolidation_service(tmp_path)
    try:
        result = service.consolidate(
            user_message="Please do not nag me about unfinished tasks.",
            assistant_answer="Understood.",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    candidate = result.items[0].candidate
    assert candidate.memory_kind is MemoryKind.BOUNDARY
    assert candidate.memory_scope is MemoryScope.GLOBAL
    assert candidate.status is LifecycleStatus.ACTIVE
    assert candidate.source_track is SourceTrack.EXPLICIT_USER
    assert candidate.metadata["recall_permissions"]["can_persist"] is True
    assert candidate.metadata["recall_permissions"]["can_style_response"] is True


def test_completed_projects_are_archived_and_not_current_context(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    service = MemoryLifecycleService(db_path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PROJECT_CONTEXT.value,
                memory_type=MemoryKind.PROJECT_CONTEXT.value,
                subject="current project",
                predicate="is",
                object="Atlas",
                source_text="I am working on Project Atlas.",
                confidence=0.9,
            )
        ).fact

        completed = service.mark_fact_completed(fact.id)
        active_projects = service.graph.search_active("current project", limit=5)
    finally:
        service.close()

    assert completed.status is MemoryFactStatus.ARCHIVED
    assert active_projects == []


def test_related_new_projects_are_not_polluted_by_old_archived_project_context(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    service = MemoryLifecycleService(db_path)
    try:
        old = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PROJECT_CONTEXT.value,
                memory_type=MemoryKind.PROJECT_CONTEXT.value,
                subject="current project",
                predicate="is",
                object="Atlas",
                source_text="I am working on Project Atlas.",
                confidence=0.9,
            )
        ).fact
        service.mark_fact_completed(old.id)
        new = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PROJECT_CONTEXT.value,
                memory_type=MemoryKind.PROJECT_CONTEXT.value,
                subject="current project",
                predicate="is",
                object="Borealis",
                source_text="I am working on Project Borealis.",
                confidence=0.92,
            )
        ).fact
        old_after = service.graph.get(old.id)
    finally:
        service.close()

    activation = MemoryActivationService()
    context = MemoryActivationContext(query="What should we do for project Borealis?", route_scopes=("personal_memory",))
    old_decision = activation.score(activation_item_from_graph_fact(old_after), context)
    new_decision = activation.score(activation_item_from_graph_fact(new), context)

    assert old_decision.allowed is False
    assert old_decision.filtered_reason == "archived_memory_not_current"
    assert new_decision.allowed is True


def test_user_correction_prevents_future_recall(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        bind_vault(client, tmp_path)
        fact_id = create_fact(client, subject="pollution preferred snack", object_value="mango")
        assert any(result.get("fact_id") == fact_id for result in search_personal_memory(client, "mango"))

        response = client.post(
            "/api/memory/feedback",
            headers=auth(),
            json={
                "target_type": "fact",
                "target_id": fact_id,
                "operation": "forget",
                "feedback_text": "That memory is wrong.",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == LifecycleStatus.FORGOTTEN.value
        assert not any(result.get("fact_id") == fact_id for result in search_personal_memory(client, "mango"))


def test_sensitive_content_does_not_write_vault_or_ordinary_memory(tmp_path: Path) -> None:
    service, db_path = build_consolidation_service(tmp_path)
    vault = tmp_path / "Vault"
    vault.mkdir()
    try:
        result = service.consolidate(
            user_message="Please remember this \u5bc6\u7801 for the service account.",
            assistant_answer="I cannot save credentials.",
        )
    finally:
        service.close()

    assert result.rejected_count == 1
    candidate = result.items[0].candidate
    assert candidate.memory_scope is MemoryScope.SENSITIVE
    assert candidate.status is LifecycleStatus.REJECTED
    assert result.items[0].evidence is not None
    assert result.items[0].evidence.source_excerpt == REDACTED_EVIDENCE
    assert rows(db_path, "SELECT COUNT(*) AS count FROM memory_graph_facts")[0]["count"] == 0
    assert not list(vault.rglob("*.md"))


def test_agent_actions_trace_automatic_memory_activity(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        bind_vault(client, tmp_path)
        enable_automation(client, long_term_memory=True)

        chat_payload, events = stream_chat(client, "Remember this: my favorite editor is VS Code.")

        action_payloads = [
            json.loads(event["data"])
            for event in events
            if event["event"] == "agent_action"
        ]
        consolidation_action = next(
            payload
            for payload in action_payloads
            if payload["action_type"] == "memory.consolidation.candidate"
        )
        assert consolidation_action["source_agent_run_id"] == chat_payload["agent_run_id"]
        assert consolidation_action["source_conversation_id"] == chat_payload["conversation_id"]
        assert consolidation_action["source_message_id"] == chat_payload["message_id"]
        assert consolidation_action["metadata"]["candidate_count"] == 1

        action_rows = rows(
            client.app.state.database.path,
            "SELECT * FROM agent_actions WHERE id = ?",
            (consolidation_action["action_id"],),
        )
        candidate_rows = rows(
            client.app.state.database.path,
            "SELECT memory_kind, status FROM memory_candidates",
        )
        evidence_rows = rows(
            client.app.state.database.path,
            "SELECT agent_run_id, conversation_id, message_id FROM memory_evidence",
        )

        assert len(action_rows) == 1
        assert action_rows[0]["action_type"] == "memory.consolidation.candidate"
        assert candidate_rows[0]["memory_kind"] == MemoryKind.PREFERENCE.value
        assert candidate_rows[0]["status"] == LifecycleStatus.ACTIVE.value
        assert evidence_rows[0]["agent_run_id"] == chat_payload["agent_run_id"]
        assert evidence_rows[0]["conversation_id"] == chat_payload["conversation_id"]
        assert evidence_rows[0]["message_id"] == chat_payload["message_id"]
