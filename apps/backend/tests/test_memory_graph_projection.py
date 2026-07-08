from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.models.enums import MemoryFactStatus
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_candidates import MemoryCandidateCreate, MemoryEvidenceCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from tests.conftest import auth_headers


def auth() -> dict[str, str]:
    return auth_headers()


def create_candidate(
    client: TestClient,
    *,
    summary: str,
    source_text: str | None = None,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    risk: RiskTier = RiskTier.LOW,
    confidence: float = 0.9,
    importance: float = 0.8,
    expires_at: str | None = None,
) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        return service.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=kind,
                memory_scope=scope,
                summary=summary,
                normalized_value=summary.casefold(),
                source_text=source_text or summary,
                source_track=SourceTrack.EXPLICIT_USER,
                risk_tier=risk,
                confidence=confidence,
                importance=importance,
                status=status,
                expires_at=expires_at,
            )
        ).id
    finally:
        service.close()


def create_preference_fact(client: TestClient, *, object_value: str = "简洁回答") -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="回答风格",
                predicate="偏好",
                object=object_value,
                source_text="RAW_GRAPH_SOURCE_TEXT_SHOULD_NOT_LEAK",
                source_type="user_message",
                confidence=0.92,
                importance=0.85,
            )
        ).fact
        return fact.id
    finally:
        service.close()


def create_diary_object(
    client: TestClient,
    *,
    summary: str,
    type: str,
    topic: str = "Project Atlas",
    emotion: str = "focused",
    source_id: str = "run-raw-diary-source",
    status: MemoryFactStatus = MemoryFactStatus.ACTIVE,
) -> str:
    db_path = Path(client.app.state.database.path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vaults(id, root_path, name) VALUES (?, ?, ?)",
            ("vault-graph", str(db_path.parent / "Vault"), "Vault"),
        )
    store = DiaryMemoryStore(db_path)
    try:
        record = store.insert_object(
            vault_id="vault-graph",
            extracted=DiaryMemoryObject(
                summary=summary,
                topic=topic,
                emotion=emotion,
                people=("Alice",),
                keywords=("atlas", type),
                source_text="RAW_DIARY_SOURCE_TEXT_SHOULD_NOT_LEAK",
                importance=0.82,
                confidence=0.88,
                status=status,
                type=type,
            ),
            occurred_at="2026-07-08T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=DiaryMemoryObjectSource(
                object_id="",
                source_type="chat_exchange",
                source_id=source_id,
                conversation_id="conv-raw-diary",
                user_message_id="msg-raw-user",
                assistant_message_id="msg-raw-assistant",
                agent_run_id="run-raw-agent",
                markdown_path="Memories/Daily/raw.md",
            ),
            extraction_model="reflection_agent",
        )
        assert record is not None
        return record.id
    finally:
        store.close()


def set_candidate_updated_at(client: TestClient, candidate_id: str, updated_at: str) -> None:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute("UPDATE memory_candidates SET updated_at = ? WHERE id = ?", (updated_at, candidate_id))


def add_raw_evidence(client: TestClient, candidate_id: str) -> None:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        service.candidates.add_evidence(
            MemoryEvidenceCreate(
                candidate_id=candidate_id,
                source_text="PENDING_RAW_EVIDENCE_SHOULD_NOT_LEAK",
                source_excerpt="PENDING_RAW_EXCERPT_SHOULD_NOT_LEAK",
                confidence=0.4,
            )
        )
    finally:
        service.close()


def get_projection(client: TestClient, *, max_nodes: int | None = None) -> dict[str, Any]:
    query = "" if max_nodes is None else f"?max_nodes={max_nodes}"
    response = client.get(f"/api/memory/graph-projection{query}", headers=auth())
    assert response.status_code == 200
    return response.json()


def string_values(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from string_values(nested)


def assert_safe_projection(payload: dict[str, Any], *raw_values: str) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    forbidden = (
        "candidate_id",
        "fact_id",
        "diary_object_id",
        "source_id",
        "evidence_id",
        "agent_run_id",
        "message_id",
        "conversation_id",
        "source_text",
        "source_excerpt",
        "raw evidence",
        "raw_evidence",
        "markdown_path",
        "authorization",
        "bearer",
        "token",
        "lifecycle_status",
        "memory_candidates",
        "fts",
        "vector",
        "c:\\",
        "/users/",
        *[value.lower() for value in raw_values],
    )
    for value in forbidden:
        assert value not in serialized


def table_counts(client: TestClient) -> dict[str, int]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        return {
            "candidates": conn.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0],
            "facts": conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0],
            "diary": conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0],
            "lifecycle": conn.execute("SELECT COUNT(*) FROM memory_lifecycle_events").fetchone()[0],
            "actions": conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0],
        }


def test_graph_projection_returns_center_and_profile_nodes_safely(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = create_preference_fact(client)
        boundary_id = create_candidate(
            client,
            summary="不要在早上主动提醒我任务。",
            kind=MemoryKind.BOUNDARY,
        )

        payload = get_projection(client)

        nodes = payload["nodes"]
        assert any(node["type"] == "user" and node["label"] == "我" for node in nodes)
        assert any(node["type"] == "preference" and "简洁" in node["label"] for node in nodes)
        assert any(node["type"] == "boundary" and "早上" in node["label"] for node in nodes)
        assert all(str(node["id"]).startswith("mg_") for node in nodes)
        assert all(str(edge["id"]).startswith("mge_") for edge in payload["edges"])
        assert any(edge["from"] in {node["id"] for node in nodes} for edge in payload["edges"])
        assert_safe_projection(payload, fact_id, boundary_id, "RAW_GRAPH_SOURCE_TEXT_SHOULD_NOT_LEAK")


def test_graph_projection_adds_diary_episode_qa_mood_and_project_nodes(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        raw_ids = [
            create_diary_object(client, summary="Project Atlas kickoff notes were reviewed.", type="event"),
            create_diary_object(client, summary="User asked how to compare two parser options.", type="qa", topic="parser choice"),
            create_diary_object(client, summary="User felt focused after finishing the draft.", type="mood", emotion="focused"),
            create_diary_object(client, summary="Project Atlas decision moved to next week.", type="project_update"),
        ]

        payload = get_projection(client)
        node_types = {node["type"] for node in payload["nodes"]}

        assert {"episode", "qa", "mood", "project"}.issubset(node_types)
        assert any(node["subtitle"] == "项目进展" for node in payload["nodes"])
        assert_safe_projection(
            payload,
            *raw_ids,
            "RAW_DIARY_SOURCE_TEXT_SHOULD_NOT_LEAK",
            "run-raw-diary-source",
            "run-raw-agent",
            "conv-raw-diary",
            "msg-raw-user",
            "Memories/Daily/raw.md",
        )


def test_graph_projection_counts_cleanup_and_hides_sensitive_content(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        stale_id = create_candidate(
            client,
            summary="Temporary focus expired.",
            kind=MemoryKind.RECENT_STATE,
            scope=MemoryScope.TEMPORARY,
            expires_at="2026-01-01T00:00:00Z",
        )
        low_id = create_candidate(
            client,
            summary="Maybe user likes very long explanations.",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.35,
        )
        set_candidate_updated_at(client, low_id, "2026-01-01T00:00:00Z")
        secret_id = create_candidate(
            client,
            summary="token=sk-graph-secret-12345678901234567890",
            source_text="token=sk-graph-secret-12345678901234567890",
            risk=RiskTier.HIGH,
            status=LifecycleStatus.CANDIDATE,
        )

        payload = get_projection(client)

        assert payload["summary"]["cleanup_count"] >= 2
        assert payload["summary"]["hidden_count"] >= 1
        assert any(node["type"] == "cleanup" for node in payload["nodes"])
        assert any(node["status"] == "hidden" and "隐藏" in node["label"] for node in payload["nodes"])
        assert_safe_projection(payload, stale_id, low_id, secret_id, "sk-graph-secret", "token=")


def test_graph_projection_pending_nodes_do_not_expose_raw_evidence(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        pending_id = create_candidate(
            client,
            summary="也许用户喜欢长篇解释。",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.42,
        )
        add_raw_evidence(client, pending_id)

        payload = get_projection(client)

        assert any(node["type"] == "pending" and node["status"] == "pending" for node in payload["nodes"])
        assert_safe_projection(
            payload,
            pending_id,
            "PENDING_RAW_EVIDENCE_SHOULD_NOT_LEAK",
            "PENDING_RAW_EXCERPT_SHOULD_NOT_LEAK",
            "run-pending-raw",
        )


def test_graph_projection_limits_nodes_clusters_are_valid_and_is_read_only(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        for index in range(12):
            create_candidate(client, summary=f"用户偏好第 {index} 项。", confidence=0.9)
        create_diary_object(client, summary="Project Atlas checkpoint was reviewed.", type="event")
        before = table_counts(client)

        payload = get_projection(client, max_nodes=8)

        after = table_counts(client)
        node_ids = {node["id"] for node in payload["nodes"]}
        assert len(payload["nodes"]) <= 8
        assert payload["summary"]["total_nodes"] == len(payload["nodes"])
        for cluster in payload["clusters"]:
            assert cluster["node_ids"]
            assert set(cluster["node_ids"]).issubset(node_ids)
        for edge in payload["edges"]:
            assert edge["from"] in node_ids
            assert edge["to"] in node_ids
        assert before == after
        assert not (tmp_path / "Vault").exists()
