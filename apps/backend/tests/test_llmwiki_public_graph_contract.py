from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.api.memory import graph as graph_api
from app.services.memory_entity_graph import MemoryEntityGraphStore
from tests.conftest import auth_headers


def test_legacy_profile_projection_routes_are_not_public(client_factory, tmp_path: Path) -> None:
    """The graph workspace has one public graph contract, not a second profile API."""
    with client_factory(data_dir=tmp_path / "data") as client:
        for method, path in (
            ("get", "/api/memory/profile-projection"),
            ("get", "/api/memory/profile-projection/items/profile_abc123"),
            ("post", "/api/memory/profile-projection/items/profile_abc123/actions"),
        ):
            response = (
                client.post(path, headers=auth_headers(), json={})
                if method == "post"
                else client.get(path, headers=auth_headers())
            )
            assert response.status_code == 404, (method, path, response.status_code, response.text)


def test_graph_api_reports_wiki_reconcile_failure_as_sqlite_degradation(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.memory import graph as graph_api

    with client_factory(data_dir=tmp_path / "data") as client:
        bound = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={
                "path": str(tmp_path / "Vault"),
                "create_if_missing": True,
                "confirmed": True,
            },
        )
        assert bound.status_code == 200

        def fail_reconcile(*args, **kwargs):
            del args, kwargs
            raise OSError("vault unavailable")

        monkeypatch.setattr(graph_api, "reconcile_wiki_vault", fail_reconcile)
        response = client.get("/api/memory/graph", headers=auth_headers())

        assert response.status_code == 200
        payload = response.json()
        assert payload["generation"]["backend"] == "sqlite"
        assert payload["degraded_mode"] is True
        assert "degraded" not in payload["generation"]
        assert payload["generation"]["fallback_code"] == "wiki_reconcile_failed"


def test_graph_rebuild_uses_runtime_lifecycle_and_replays_receipt(client_factory, tmp_path: Path) -> None:
    key = "a" * 64
    with client_factory(data_dir=tmp_path / "data") as client:
        first = client.post(
            "/api/diagnostics/memory-graph/rebuild",
            headers={**auth_headers(), "Idempotency-Key": key},
            json={},
        )
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["operation_id"]

        second = client.post(
            "/api/diagnostics/memory-graph/rebuild",
            headers={**auth_headers(), "Idempotency-Key": key},
            json={},
        )
        assert second.status_code == 200, second.text
        second_payload = second.json()
        assert second_payload["replayed"] is True
        assert second_payload["operation_id"] == first_payload["operation_id"]


def test_graph_contract_uses_canonical_risk_and_required_idempotency_headers(client_factory, tmp_path: Path) -> None:
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
            store.create_relation(
                relation_type="works_on",
                subject_entity_id=person.id,
                object_entity_id=project.id,
                source_text="Ada works on Atlas.",
                evidence_id="canonical-risk-edge",
            )
        finally:
            store.close()

        response = client.get("/api/memory/graph", headers=auth_headers())
        assert response.status_code == 200
        payload = response.json()
        assert isinstance(payload["degraded_mode"], bool)
        assert payload["nodes"] and all("risk" in item and "risk_tier" not in item for item in payload["nodes"])
        assert payload["edges"] and all("risk" in item and "risk_tier" not in item for item in payload["edges"])
        assert all(item["allowed_actions"] for item in payload["edges"])

        document = client.app.openapi()
        for path in (
            "/api/memory/graph/nodes/{node_id}/actions",
            "/api/memory/graph/edges/{edge_id}/actions",
            "/api/memory/graph/claims/{claim_id}/actions",
            "/api/diagnostics/memory-graph/rebuild",
            "/api/metrics/recall-feedback",
            "/api/tasks/reminder-delivery/reservations",
        ):
            parameters = document["paths"][path]["post"]["parameters"]
            header = next(item for item in parameters if item["name"] == "Idempotency-Key")
            assert header["required"] is True
            assert header["schema"]["minLength"] == 64
            assert header["schema"]["maxLength"] == 64
            assert header["schema"]["pattern"] == "^[0-9a-f]{64}$"


def test_claim_and_edge_details_expose_wiki_versions_and_safe_relative_evidence(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        initialized = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(tmp_path / "Vault"), "create_if_missing": True, "confirmed": True},
        )
        assert initialized.status_code == 200
        vault_id = initialized.json()["vault_id"]
        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            person = store.create_entity(entity_type="person", canonical_name="Ada")
            project = store.create_entity(entity_type="project", canonical_name="Atlas")
            page = store.create_entity(entity_type="wiki_page", canonical_name="Atlas record")
            store.bind_wiki_page(
                vault_id=vault_id,
                page_entity_id=page.id,
                wiki_relative_path="Wiki/Projects/Atlas.md",
                content_hash="content-hash",
                revision=2,
            )
            claim = store.create_claim(
                subject_entity_id=person.id,
                predicate="prefers",
                literal_value="short updates",
                source_text="Ada prefers short updates.",
                evidence_id="claim-version-evidence",
            )
            store.bind_artifact(
                fact_id=claim.id,
                vault_id=vault_id,
                artifact_type="wiki_page",
                artifact_ref="Wiki/Projects/Atlas.md",
            )
            old_claim, new_claim = store.correct_claim(claim.id, literal_value="detailed updates")
            relation = store.create_relation(
                relation_type="works_on",
                subject_entity_id=person.id,
                object_entity_id=project.id,
                source_text="Ada works on Atlas.",
                evidence_id="edge-version-evidence",
            )
            store.bind_artifact(
                fact_id=relation.id,
                vault_id=vault_id,
                artifact_type="wiki_page",
                artifact_ref="Wiki/Projects/Atlas.md",
            )
            old_relation, new_relation = store.correct_relation(
                relation.id,
                relation_type="knows",
                subject_entity_id=person.id,
                object_entity_id=project.id,
            )
            old_edge_id = graph_api._relation_edge_id(
                graph_api.EntityRelation(
                    fact=old_relation,
                    relation_type="works_on",
                    subject_entity_id=person.id,
                    subject_fact_id=None,
                    object_entity_id=project.id,
                    object_fact_id=None,
                )
            )
        finally:
            store.close()

        claim_response = client.get(
            f"/api/memory/graph/claims/{graph_api._public_id('claim', old_claim.id)}",
            headers=auth_headers(),
        )
        assert claim_response.status_code == 200
        claim_payload = claim_response.json()
        assert claim_payload["risk"] == "low" and "risk_tier" not in claim_payload
        assert claim_payload["evidence"][0]["relative_path"] == "Wiki/Projects/Atlas.md"
        assert claim_payload["wiki_pages"][0]["relative_path"] == "Wiki/Projects/Atlas.md"
        assert {item["object_id"] for item in claim_payload["version_chain"]} == {
            graph_api._public_id("claim", old_claim.id),
            graph_api._public_id("claim", new_claim.id),
        }

        edge_response = client.get(f"/api/memory/graph/edges/{old_edge_id}", headers=auth_headers())
        assert edge_response.status_code == 200
        edge_payload = edge_response.json()
        assert edge_payload["risk"] == "low" and "risk_tier" not in edge_payload
        assert edge_payload["evidence"][0]["relative_path"] == "Wiki/Projects/Atlas.md"
        assert edge_payload["wiki_pages"][0]["revision"] == 2
        assert len(edge_payload["version_chain"]) == 2
        assert any(item["current"] and item["object_id"] == old_edge_id for item in edge_payload["version_chain"])
        assert new_relation.id != old_relation.id


def test_graph_action_idempotency_header_and_payload_conflict_are_enforced(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        initialized = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(tmp_path / "Vault"), "create_if_missing": True, "confirmed": True},
        )
        assert initialized.status_code == 200
        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            entity = store.create_entity(entity_type="person", canonical_name="Ada")
            store.create_claim(
                subject_entity_id=entity.id,
                predicate="works_on",
                literal_value="Atlas",
                source_text="Ada works on Atlas.",
                evidence_id="graph-idempotency-evidence",
            )
        finally:
            store.close()

        action_path = f"/api/memory/graph/nodes/{graph_api._opaque_node_id('entity', entity.id)}/actions"
        payload = {"action": "archive", "confirmed": True}

        missing = client.post(action_path, headers=auth_headers(), json=payload)
        assert missing.status_code == 422

        invalid = client.post(
            action_path,
            headers={**auth_headers(), "Idempotency-Key": "A" * 64},
            json=payload,
        )
        assert invalid.status_code == 422

        key = "f" * 64
        first = client.post(
            action_path,
            headers={**auth_headers(), "Idempotency-Key": key},
            json=payload,
        )
        assert first.status_code == 200, first.text

        conflict = client.post(
            action_path,
            headers={**auth_headers(), "Idempotency-Key": key},
            json={"action": "forget", "confirmed": True},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "idempotency_key_conflict"


def test_claim_correction_returns_and_replays_verified_replacement(client_factory, tmp_path: Path) -> None:
    key = "1" * 64
    with client_factory(data_dir=tmp_path / "data") as client:
        initialized = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(tmp_path / "Vault"), "create_if_missing": True, "confirmed": True},
        )
        assert initialized.status_code == 200
        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            preference = store.create_entity(entity_type="preference", canonical_name="Editor")
            original = store.create_claim(
                subject_entity_id=preference.id,
                predicate="prefers",
                literal_value="VS Code",
                source_text="I prefer VS Code.",
                evidence_id="claim-correction-http-evidence",
            )
            public_claim_id = graph_api._public_id("claim", original.id)
        finally:
            store.close()

        path = f"/api/memory/graph/claims/{public_claim_id}/actions"
        payload = {
            "action": "correct",
            "confirmed": True,
            "replacement": {"value": "JetBrains", "fact_type": "preference"},
        }
        first = client.post(path, headers={**auth_headers(), "Idempotency-Key": key}, json=payload)
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["status"] == "active"
        assert first_payload["replayed"] is False
        assert first_payload["replacement_id"].startswith("claim_")

        replay = client.post(path, headers={**auth_headers(), "Idempotency-Key": key}, json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["operation_id"] == first_payload["operation_id"]
        assert replay.json()["replacement_id"] == first_payload["replacement_id"]

        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            replacement_id = graph_api._resolve_claim_id(first_payload["replacement_id"], store)
            assert replacement_id is not None
            assert store.get(original.id).status is graph_api.MemoryFactStatus.SUPERSEDED
            replacement = store.get(replacement_id)
            assert replacement.status is graph_api.MemoryFactStatus.ACTIVE
            assert replacement.object == "JetBrains"
            supersedes_count = store.conn.execute(
                """
                SELECT COUNT(*) FROM memory_graph_facts
                WHERE statement_kind = 'relation'
                  AND relation_type = 'supersedes'
                  AND subject_fact_id = ?
                  AND object_fact_id = ?
                  AND status = 'active'
                """,
                (replacement_id, original.id),
            ).fetchone()[0]
        finally:
            store.close()
        assert supersedes_count == 1
        _assert_verified_graph_action(client.app.state.database.path, key)


def test_relation_correction_returns_and_replays_verified_replacement(client_factory, tmp_path: Path) -> None:
    key = "2" * 64
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
            old_project = store.create_entity(entity_type="project", canonical_name="Atlas")
            new_project = store.create_entity(entity_type="project", canonical_name="Nova")
            original = store.create_relation(
                relation_type="works_on",
                subject_entity_id=person.id,
                object_entity_id=old_project.id,
                source_text="Ada works on Atlas.",
                evidence_id="relation-correction-http-evidence",
            )
            original_relation = graph_api.EntityRelation(
                fact=original,
                relation_type="works_on",
                subject_entity_id=person.id,
                subject_fact_id=None,
                object_entity_id=old_project.id,
                object_fact_id=None,
            )
            public_edge_id = graph_api._relation_edge_id(original_relation)
            subject_node_id = graph_api._opaque_node_id("entity", person.id)
            object_node_id = graph_api._opaque_node_id("entity", new_project.id)
        finally:
            store.close()

        path = f"/api/memory/graph/edges/{public_edge_id}/actions"
        payload = {
            "action": "correct",
            "confirmed": True,
            "replacement": {
                "relation_type": "works_on",
                "subject_node_id": subject_node_id,
                "object_node_id": object_node_id,
            },
        }
        first = client.post(path, headers={**auth_headers(), "Idempotency-Key": key}, json=payload)
        assert first.status_code == 200, first.text
        first_payload = first.json()
        assert first_payload["status"] == "active"
        assert first_payload["replayed"] is False
        assert first_payload["replacement_id"].startswith("mge_")
        assert first_payload["replacement_id"] != public_edge_id

        replay = client.post(path, headers={**auth_headers(), "Idempotency-Key": key}, json=payload)
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["operation_id"] == first_payload["operation_id"]
        assert replay.json()["replacement_id"] == first_payload["replacement_id"]

        store = MemoryEntityGraphStore(client.app.state.database.path)
        try:
            replacement = graph_api._resolve_relation_any_status(first_payload["replacement_id"], store)
            assert replacement is not None
            assert store.get(original.id).status is graph_api.MemoryFactStatus.SUPERSEDED
            assert replacement.fact.status is graph_api.MemoryFactStatus.ACTIVE
            assert replacement.relation_type == "works_on"
            assert replacement.subject_entity_id == person.id
            assert replacement.object_entity_id == new_project.id
            supersedes_count = store.conn.execute(
                """
                SELECT COUNT(*) FROM memory_graph_facts
                WHERE statement_kind = 'relation'
                  AND relation_type = 'supersedes'
                  AND subject_fact_id = ?
                  AND object_fact_id = ?
                  AND status = 'active'
                """,
                (replacement.fact.id, original.id),
            ).fetchone()[0]
        finally:
            store.close()
        assert supersedes_count == 1
        _assert_verified_graph_action(client.app.state.database.path, key)


def _assert_verified_graph_action(database_path: Path, idempotency_key: str) -> None:
    with sqlite3.connect(database_path) as conn:
        rows = conn.execute(
            "SELECT status, metadata_json FROM agent_actions WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchall()
    assert len(rows) == 1
    status_value, metadata_json = rows[0]
    metadata = json.loads(metadata_json)
    assert status_value == "completed"
    assert metadata["execution_receipt"]["status"] == "verified"
    assert metadata["verification_result"]["status"] == "verified"


def test_pending_profile_candidate_is_confirmable_via_graph_node_action(client_factory, tmp_path: Path) -> None:
    from app.services.memory_candidates import MemoryCandidateCreate, MemoryCandidateStore
    from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack

    with client_factory(data_dir=tmp_path / "data") as client:
        bound = client.post(
            "/api/vaults/init",
            headers=auth_headers(),
            json={"path": str(tmp_path / "Vault"), "create_if_missing": True, "confirmed": True},
        )
        assert bound.status_code == 200

        store = MemoryCandidateStore(client.app.state.database.path)
        try:
            record = store.create_candidate(
                MemoryCandidateCreate(
                    memory_kind=MemoryKind.PREFERENCE,
                    memory_scope=MemoryScope.GLOBAL,
                    summary="User prefers 安静的环境.",
                    normalized_value="preference:安静的环境",
                    source_text="记住:我偏好安静的环境",
                    source_track=SourceTrack.EXPLICIT_USER,
                    risk_tier=RiskTier.LOW,
                    confidence=0.6,
                    importance=0.6,
                    status=LifecycleStatus.CANDIDATE,
                )
            )
        finally:
            store.close()

        graph_response = client.get("/api/memory/graph", headers=auth_headers())
        assert graph_response.status_code == 200
        payload = graph_response.json()
        pending_nodes = [node for node in payload["nodes"] if node["status"] == "pending"]
        assert pending_nodes, "expected a pending profile candidate node in the graph"
        assert "confirm" in pending_nodes[0]["allowed_actions"]
        node_id = pending_nodes[0]["node_id"]

        detail_response = client.get(f"/api/memory/graph/nodes/{node_id}", headers=auth_headers())
        assert detail_response.status_code == 200
        assert "confirm" in detail_response.json()["allowed_actions"]

        key = "b" * 64
        confirm_response = client.post(
            f"/api/memory/graph/nodes/{node_id}/actions",
            headers={**auth_headers(), "Idempotency-Key": key},
            json={"action": "confirm", "confirmed": True},
        )
        assert confirm_response.status_code == 200, confirm_response.text
        assert confirm_response.json()["status"] == "active"

        with sqlite3.connect(client.app.state.database.path) as conn:
            status_value = conn.execute(
                "SELECT status FROM memory_candidates WHERE id = ?", (record.id,)
            ).fetchone()[0]
        assert status_value == "active"


def test_candidate_entity_actions_include_confirm() -> None:
    assert "confirm" in graph_api._entity_actions("candidate", "concept")
    assert "confirm" in graph_api._entity_actions("quarantined", "person")
    assert "confirm" not in graph_api._entity_actions("active", "concept")
    assert graph_api._entity_actions("candidate", "self") == []
