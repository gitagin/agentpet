from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.api import MemorySearchResult
from app.models.enums import MemoryFactStatus
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_read import (
    MemoryItem,
    MemorySourceRead,
    UnifiedMemorySearchService,
    memory_item_from_search_result,
)
from tests.conftest import auth_headers


def auth() -> dict[str, str]:
    return auth_headers()


class StaticMemorySource:
    def __init__(self, channel: str, results: list[MemorySearchResult]) -> None:
        self.channel = channel
        self._results = results

    def supports(self, source_scope: str) -> bool:
        return source_scope == "all"

    def search(self, **kwargs) -> MemorySourceRead:
        del kwargs
        return MemorySourceRead(
            items=tuple(
                memory_item_from_search_result(result, source=self.channel)
                for result in self._results
            )
        )


def search_result(identifier: str, *, scope: str, score: float) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=identifier,
        chunk_id=identifier,
        relative_path=f"Memory/{identifier}",
        title=identifier,
        snippet=f"memory item {identifier}",
        score=score,
        content_hash=f"hash-{identifier}",
        source_scope=scope,
        retrieval_mode="test",
    )


def test_unified_memory_item_and_rrf_interleave_registered_sources() -> None:
    adapters = (
        StaticMemorySource(
            "retrieval",
            [
                search_result("retrieval-1", scope="knowledge_base", score=100.0),
                search_result("retrieval-2", scope="knowledge_base", score=90.0),
            ],
        ),
        StaticMemorySource(
            "graph",
            [
                search_result("graph-1", scope="personal_memory", score=0.9),
                search_result("graph-2", scope="personal_memory", score=0.8),
            ],
        ),
        StaticMemorySource(
            "diary",
            [
                search_result("diary-1", scope="diary_objects", score=2.0),
                search_result("diary-2", scope="diary_objects", score=1.9),
            ],
        ),
    )

    first_item: MemoryItem = adapters[0].search().items[0]
    assert first_item.id == "retrieval-1:retrieval-1"
    assert first_item.kind == "note"
    assert first_item.status == "active"
    assert first_item.score == 100.0
    assert first_item.provenance.source == "retrieval"

    response = UnifiedMemorySearchService(adapters).search(
        query="memory",
        top_k=5,
        mode="fts",
        source_scope="all",
    )

    assert [result.note_id for result in response.results] == [
        "retrieval-1",
        "graph-1",
        "diary-1",
        "retrieval-2",
        "graph-2",
    ]
    assert response.metadata["memory_fusion"]["algorithm"] == "reciprocal_rank_fusion"
    assert response.results[0].score_breakdown["source_score"] == 100.0
    assert response.results[0].score != 100.0


def bind_vault(client: TestClient, tmp_path: Path) -> str:
    vault = tmp_path / "Vault"
    vault.mkdir()
    response = client.post(
        "/api/vaults/init",
        headers=auth(),
        json={"path": str(vault), "create_if_missing": False, "confirmed": True},
    )
    assert response.status_code == 200
    return str(client.app.state.active_vault_id)


def insert_diary_memory(db_path: Path, *, vault_id: str, index: int) -> None:
    store = DiaryMemoryStore(db_path)
    try:
        inserted = store.insert_object(
            vault_id=vault_id,
            extracted=DiaryMemoryObject(
                summary=f"fusiontoken diary memory {index}",
                topic="fusiontoken",
                emotion="",
                people=(),
                keywords=("fusiontoken",),
                source_text=f"fusiontoken diary memory {index}",
                importance=0.9 - (index * 0.01),
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
                type="event",
            ),
            occurred_at=f"2026-08-0{index + 1}T10:00:00+08:00",
            timezone="Asia/Shanghai",
            source=DiaryMemoryObjectSource(
                object_id="",
                source_type="test",
                source_id=f"diary-source-{index}",
            ),
            extraction_model="test",
        )
        assert inserted is not None
    finally:
        store.close()


def insert_graph_fact(db_path: Path) -> str:
    lifecycle = MemoryLifecycleService(db_path)
    try:
        return lifecycle.graph.upsert_candidate(
            MemoryFactCandidate(
                category="preference",
                memory_type="preference",
                subject="fusiontoken graph memory",
                predicate="is",
                object="active",
                source_text="fusiontoken graph memory is active",
                confidence=0.95,
                importance=0.9,
            )
        ).fact.id
    finally:
        lifecycle.close()


def test_memory_search_all_does_not_let_diary_consume_top_k(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        vault_id = bind_vault(client, tmp_path)
        db_path = client.app.state.database.path
        fact_id = insert_graph_fact(db_path)
        for index in range(3):
            insert_diary_memory(db_path, vault_id=vault_id, index=index)

        response = client.post(
            "/api/memory/search",
            headers=auth(),
            json={"query": "fusiontoken", "top_k": 2, "source_scope": "all"},
        )

        assert response.status_code == 200
        payload = response.json()
        assert {result["source_scope"] for result in payload["results"]} == {
            "personal_memory",
            "diary_objects",
        }
        assert any(result["fact_id"] == fact_id for result in payload["results"])
        assert payload["metadata"]["memory_fusion"]["algorithm"] == "reciprocal_rank_fusion"


def test_parameterized_graph_action_preserves_fact_status_and_audits_once(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = insert_graph_fact(client.app.state.database.path)

        wrong = client.post(
            f"/api/memory/graph/facts/{fact_id}/actions/wrong",
            headers=auth(),
        )
        assert wrong.status_code == 200
        assert wrong.json() == {"fact_id": fact_id, "status": "wrong"}

        unknown = client.post(
            f"/api/memory/graph/facts/{fact_id}/actions/not-an-action",
            headers=auth(),
        )
        assert unknown.status_code == 422

        restored = client.post(
            f"/api/memory/graph/facts/{fact_id}/actions/confirm",
            headers=auth(),
        )
        assert restored.status_code == 200
        assert restored.json()["status"] == "active"

        with sqlite3.connect(client.app.state.database.path) as conn:
            wrong_audits = conn.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action = 'memory.graph.wrong'"
            ).fetchone()[0]
            stored_status = conn.execute(
                "SELECT status FROM memory_graph_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()[0]
        assert wrong_audits == 1
        assert stored_status == "active"

        schema = client.get("/openapi.json").json()
        canonical = schema["paths"]["/api/memory/graph/facts/{fact_id}/actions/{action}"]["post"]
        legacy = schema["paths"]["/api/memory/graph/facts/{fact_id}/wrong"]["post"]
        assert canonical.get("deprecated") is not True
        assert legacy["deprecated"] is True
