from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from apps.backend.tests._schema import migrate_db
from app.api.memory import graph as graph_api
from app.models.api import MemoryGraphActionRequest, MemoryGraphResponse
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.utils.time import utc_now_iso
from tests.conftest import auth_headers


def test_filter_projection_summary_matches_the_filtered_limited_view() -> None:
    def node(node_id: str, node_type: str, label: str, status: str, risk: str) -> dict[str, object]:
        return {
            "node_id": node_id,
            "type": node_type,
            "label": label,
            "subtitle": "",
            "status": status,
            "risk": risk,
            "size": 1.0,
            "confidence_label": "高",
            "source_label": "本机",
            "updated_at": "2026-08-10T00:00:00Z",
        }

    response = MemoryGraphResponse.model_validate(
        {
            "generated_at": "2026-08-10T00:00:00Z",
            "nodes": [
                node("n-project", "project", "Atlas", "active", "low"),
                node("n-cleanup-pending", "cleanup", "Pending cleanup", "pending", "low"),
                node("n-cleanup-hidden", "cleanup", "Hidden cleanup", "hidden", "hidden"),
                node("n-preference", "preference", "Concise updates", "pending", "low"),
            ],
            "edges": [
                {"edge_id": "e-project-cleanup", "source_node_id": "n-project", "target_node_id": "n-cleanup-pending", "relation_type": "related_to"},
                {"edge_id": "e-pending", "source_node_id": "n-cleanup-pending", "target_node_id": "n-preference", "relation_type": "related_to"},
                {"edge_id": "e-hidden", "source_node_id": "n-cleanup-hidden", "target_node_id": "n-preference", "relation_type": "related_to"},
            ],
            "clusters": [{"cluster_id": "all", "label": "All", "node_ids": ["n-project", "n-cleanup-pending", "n-cleanup-hidden", "n-preference"]}],
            "summary": {"total_nodes": 4, "pending_count": 2, "cleanup_count": 2, "hidden_count": 1},
            "vault": {"vault_id": "vault-test"},
            "generation": {"backend": "sqlite", "source_revision": 1, "status": "degraded"},
            "degraded_mode": True,
        }
    )

    limited = graph_api._filter_projection(
        response,
        query=None,
        status_filter=None,
        entity_type=None,
        limit=2,
    )
    assert limited.summary.model_dump() == {
        "total_nodes": 2,
        "pending_count": 1,
        "cleanup_count": 1,
        "hidden_count": 0,
    }
    assert [edge.edge_id for edge in limited.edges] == ["e-project-cleanup"]
    assert limited.clusters[0].node_ids == ["n-project", "n-cleanup-pending"]

    pending = graph_api._filter_projection(
        response,
        query=None,
        status_filter="pending",
        entity_type=None,
        limit=80,
    )
    assert pending.summary.model_dump() == {
        "total_nodes": 2,
        "pending_count": 2,
        "cleanup_count": 1,
        "hidden_count": 0,
    }
    assert [edge.edge_id for edge in pending.edges] == ["e-pending"]

    hidden = graph_api._filter_projection(
        response,
        query="hidden",
        status_filter=None,
        entity_type=None,
        limit=80,
    )
    assert hidden.summary.model_dump() == {
        "total_nodes": 1,
        "pending_count": 0,
        "cleanup_count": 1,
        "hidden_count": 1,
    }

    project = graph_api._filter_projection(
        response,
        query=None,
        status_filter=None,
        entity_type="project",
        limit=80,
    )
    assert project.summary.model_dump() == {
        "total_nodes": 1,
        "pending_count": 0,
        "cleanup_count": 0,
        "hidden_count": 0,
    }


def test_entity_detail_exposes_claim_ids_without_relation_ids(tmp_path: Path) -> None:
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        person = store.create_entity(entity_type="person", canonical_name="Ada")
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        claim = store.create_claim(
            subject_entity_id=person.id,
            predicate="prefers",
            literal_value="concise updates",
            source_text="Ada prefers concise updates.",
            evidence_id="entity-detail-claim-evidence",
        )
        relation = store.create_relation(
            relation_type="works_on",
            subject_entity_id=person.id,
            object_entity_id=project.id,
            source_text="Ada works on Atlas.",
            evidence_id="entity-detail-relation-evidence",
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(active_vault_id="vault-test"))
        )
        node = SimpleNamespace(id="mg_" + "1" * 32, subtitle="person")

        detail = graph_api._entity_detail(store, person.id, node, request)

        assert detail.claim_ids == [graph_api._public_id("claim", claim.id)]
        assert graph_api._public_id("claim", relation.id) not in detail.claim_ids
    finally:
        store.close()


def test_evidence_excerpt_without_safe_source_path_has_no_relative_reference(tmp_path: Path) -> None:
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        person = store.create_entity(entity_type="person", canonical_name="Ada")
        claim = store.create_claim(
            subject_entity_id=person.id,
            predicate="prefers",
            literal_value="concise updates",
            source_text="Ada prefers concise updates.",
            evidence_id="citation-boundary-evidence",
        )

        evidence = graph_api._fact_evidence(store, claim.id)

        assert evidence[0].excerpt == "Ada prefers concise updates."
        assert evidence[0].relative_path is None
    finally:
        store.close()


def test_entity_evidence_is_scoped_to_the_active_vault_fact_binding(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        now = utc_now_iso()
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO vaults (id, root_path, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("vault-a", str(tmp_path / "a"), "A", now, now),
                    ("vault-b", str(tmp_path / "b"), "B", now, now),
                ],
            )
            conn.commit()
        entity = store.create_entity(entity_type="person", canonical_name="Private Person")
        fact = store.create_claim(
            subject_entity_id=entity.id,
            predicate="uses",
            literal_value="the blue folder",
            source_text="Private Person uses the blue folder.",
            evidence_id="cross-vault-evidence",
        )
        evidence_id = "cross-vault-evidence"
        store.bind_entity_evidence(entity_id=entity.id, evidence_id=evidence_id, role="supports")
        store.bind_artifact(
            fact_id=fact.id,
            vault_id="vault-a",
            artifact_type="source",
            artifact_ref="Sources/private.txt",
        )

        assert graph_api._entity_evidence(store, entity.id, vault_id="vault-a")[0].excerpt == "Private Person uses the blue folder."
        assert graph_api._entity_evidence(store, entity.id, vault_id="vault-b") == []

        _, replacement = store.correct_claim(fact.id, literal_value="the green folder")
        store.bind_artifact(
            fact_id=replacement.id,
            vault_id="vault-b",
            artifact_type="source",
            artifact_ref="Sources/private-correction.txt",
        )
        vault_b_chain = graph_api._version_chain(store, replacement.id, target_kind="claim", vault_id="vault-b")
        assert [item.object_id for item in vault_b_chain] == [graph_api._public_id("claim", replacement.id)]
    finally:
        store.close()


def test_fact_references_use_authoritative_artifact_binding_for_each_vault(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        now = utc_now_iso()
        with sqlite3.connect(db) as conn:
            conn.executemany(
                "INSERT INTO vaults (id, root_path, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                [
                    ("vault-a", str(tmp_path / "a"), "A", now, now),
                    ("vault-b", str(tmp_path / "b"), "B", now, now),
                ],
            )
            conn.commit()
        entity = store.create_entity(entity_type="project", canonical_name="Atlas")
        evidence_id = "cross-vault-path-evidence"
        fact = store.create_claim(
            subject_entity_id=entity.id,
            predicate="status",
            literal_value="active",
            source_text="Atlas is active.",
            evidence_id=evidence_id,
        )
        with store.atomic():
            store.conn.execute(
                "UPDATE memory_evidence SET metadata_json = ? WHERE id = ?",
                ('{"vault_id":"vault-a","source_path":"Sources/A.md"}', evidence_id),
            )
        store.bind_artifact(
            fact_id=fact.id,
            vault_id="vault-a",
            artifact_type="source",
            artifact_ref="Sources/A.md",
        )
        store.bind_artifact(
            fact_id=fact.id,
            vault_id="vault-b",
            artifact_type="source",
            artifact_ref="Sources/B.md",
        )

        assert store.recall_references(fact.id, vault_id="vault-a").source_refs == ("Sources/A.md",)
        assert store.recall_references(fact.id, vault_id="vault-b").source_refs == ("Sources/B.md",)
        assert graph_api._fact_evidence(store, fact.id, vault_id="vault-a")[0].relative_path == "Sources/A.md"
        assert graph_api._fact_evidence(store, fact.id, vault_id="vault-b")[0].relative_path == "Sources/B.md"
    finally:
        store.close()


def test_claim_correction_preserves_predicate_when_fact_type_is_supplied(tmp_path: Path) -> None:
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        preference = store.create_entity(entity_type="preference", canonical_name="Fruit")
        claim = store.create_claim(
            subject_entity_id=preference.id,
            predicate="likes",
            literal_value="apple",
            category="preference",
            source_text="I like apples.",
            evidence_id="predicate-boundary-evidence",
        )
        request = MemoryGraphActionRequest(
            action="correct",
            confirmed=True,
            replacement={"value": "banana", "fact_type": "preference"},
        )

        lifecycle = graph_api.MemoryLifecycleService(store.conn)
        result = graph_api._apply_fact_action(lifecycle, claim.id, request)
        replacement_id = graph_api._resolve_claim_id(str(result["claim_id"]), store)
        assert replacement_id is not None
        replacement = store.get(replacement_id)

        assert replacement.predicate == "likes"
        assert replacement.object == "banana"
        assert store.get(claim.id).superseded_by == replacement.id
    finally:
        store.close()


def test_archived_edge_replays_original_receipt_without_repeating_side_effects(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        initialized = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(tmp_path / "Vault"), "create_if_missing": True, "confirmed": True},
        )
        assert initialized.status_code == 200
        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            person = store.create_entity(entity_type="person", canonical_name="Ada")
            project = store.create_entity(entity_type="project", canonical_name="Atlas")
            relation = store.create_relation(
                relation_type="works_on",
                subject_entity_id=person.id,
                object_entity_id=project.id,
                source_text="Ada works on Atlas.",
                evidence_id="edge-replay-evidence",
            )
        finally:
            store.close()

        graph = client.get("/api/memory/graph", headers=auth_headers())
        assert graph.status_code == 200
        edge = next(item for item in graph.json()["edges"] if item["relation_type"] == "works_on")
        first_key = "d" * 64
        archived = client.post(
            f"/api/memory/graph/edges/{edge['edge_id']}/actions",
            headers={**auth_headers(), "Idempotency-Key": first_key},
            json={"action": "archive", "confirmed": True},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["status"] == "archived"
        assert archived.json()["replayed"] is False

        def authority_counts() -> tuple[int, int, int, int]:
            with sqlite3.connect(client.app.state.database.path) as conn:
                return (
                    int(conn.execute("SELECT COUNT(*) FROM memory_graph_facts").fetchone()[0]),
                    int(conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0]),
                    int(conn.execute("SELECT COUNT(*) FROM memory_lifecycle_events WHERE fact_id = ?", (relation.id,)).fetchone()[0]),
                    int(conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]),
                )

        counts_after_archive = authority_counts()
        hidden = client.get("/api/memory/graph", headers=auth_headers())
        assert all(item["edge_id"] != edge["edge_id"] for item in hidden.json()["edges"])

        replay = client.post(
            f"/api/memory/graph/edges/{edge['edge_id']}/actions",
            headers={**auth_headers(), "Idempotency-Key": first_key},
            json={"action": "archive", "confirmed": True},
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True
        assert replay.json()["operation_id"] == archived.json()["operation_id"]
        assert authority_counts() == counts_after_archive

        new_operation = client.post(
            f"/api/memory/graph/edges/{edge['edge_id']}/actions",
            headers={**auth_headers(), "Idempotency-Key": "e" * 64},
            json={"action": "archive", "confirmed": True},
        )
        assert new_operation.status_code == 409
        assert new_operation.json()["error"]["code"] == "memory_graph_edge_not_active"
        assert authority_counts() == counts_after_archive
