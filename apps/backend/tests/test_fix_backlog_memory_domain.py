from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.models.api import MemorySearchResult
from app.models.enums import MemoryFactStatus
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_read import (
    GraphMemorySourceAdapter,
    MemoryItem,
    MemorySourceRead,
    UnifiedMemorySearchService,
    memory_item_from_search_result,
)
from app.utils.public_references import public_memory_reference
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
        subject = lifecycle.entity_graph.ensure_self()
        return lifecycle.entity_graph.create_claim(
            subject_entity_id=subject.id,
            predicate="is",
            literal_value="active",
            category="preference",
            source_text="fusiontoken graph memory is active",
            confidence=0.95,
            evidence_id="fusiontoken-evidence",
        ).id
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


def test_graph_memory_read_exposes_real_source_and_opaque_references(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        vault_id = bind_vault(client, tmp_path)
        db_path = client.app.state.database.path
        store = MemoryEntityGraphStore(db_path)
        try:
            subject = store.ensure_self()
            evidence_id = "atlas-source-evidence"
            fact = store.create_claim(
                subject_entity_id=subject.id,
                predicate="works_on",
                literal_value="Atlas",
                category="project_context",
                source_text="I work on project Atlas.",
                confidence=0.95,
                evidence_id=evidence_id,
            )
            unbound_fact = store.create_claim(
                subject_entity_id=subject.id,
                predicate="knows",
                literal_value="Orchid",
                category="project_context",
                source_text="I know project Orchid.",
                confidence=0.95,
                evidence_id="unbound-orchid-evidence",
            )
            store.bind_artifact(
                fact_id=fact.id,
                vault_id=vault_id,
                artifact_type="wiki_page",
                artifact_ref="Wiki/Projects/Atlas.md",
            )
        finally:
            store.close()

        source = GraphMemorySourceAdapter(
            lambda: MemoryEntityGraphStore(db_path),
            answerable_only=True,
            vault_id=vault_id,
        )
        read = source.search(
            query="What is the status of project Atlas?",
            top_k=5,
            mode="fts",
            source_scope="personal_memory",
        )

        item = next(candidate for candidate in read.items if candidate.result.fact_id == fact.id)
        result = item.result
        assert result.relative_path == "Wiki/Projects/Atlas.md"
        assert result.entity_refs == [public_memory_reference("entity", subject.id)]
        assert result.evidence_refs == [public_memory_reference("evidence", evidence_id)]
        assert result.citation_refs == [
            public_memory_reference("citation", "Wiki/Projects/Atlas.md")
        ]
        assert item.entity_refs == tuple(result.entity_refs)
        assert item.evidence_refs == tuple(result.evidence_refs)
        assert item.citation_refs == tuple(result.citation_refs)
        assert fact.id not in " ".join((*item.entity_refs, *item.evidence_refs, *item.citation_refs))

        unbound_read = source.search(
            query="What is project Orchid?",
            top_k=5,
            mode="fts",
            source_scope="personal_memory",
        )
        unbound_item = next(candidate for candidate in unbound_read.items if candidate.result.fact_id == unbound_fact.id)
        assert unbound_item.result.relative_path == ""
        assert unbound_item.result.evidence_refs == [
            public_memory_reference("evidence", "unbound-orchid-evidence")
        ]
        assert unbound_item.result.citation_refs == unbound_item.result.evidence_refs


def test_removed_parameterized_graph_actions_are_not_exposed(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = insert_graph_fact(client.app.state.database.path)

        removed_parameterized = client.post(
            f"/api/memory/graph/facts/{fact_id}/actions/wrong",
            headers=auth(),
        )
        removed_legacy = client.post(
            f"/api/memory/graph/facts/{fact_id}/wrong",
            headers=auth(),
        )
        assert removed_parameterized.status_code == 404
        assert removed_legacy.status_code == 404

        with sqlite3.connect(client.app.state.database.path) as conn:
            stored_status = conn.execute(
                "SELECT status FROM memory_graph_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()[0]
        assert stored_status == "active"

        schema = client.get("/openapi.json").json()
        assert "/api/memory/graph/facts/{fact_id}/actions/{action}" not in schema["paths"]
        assert "/api/memory/graph/facts/{fact_id}/wrong" not in schema["paths"]
