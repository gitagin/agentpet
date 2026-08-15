from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.memory_entity_graph import (
    EntityAmbiguityError,
    EntityGraphError,
    MemoryEntityGraphStore,
    normalize_entity_name,
)
from app.services.memory_graph import MemoryFactCandidate
from app.utils.time import utc_now_iso


def test_entity_identity_aliases_and_same_name_disambiguation(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        assert normalize_entity_name("  Ada  LOVELACE。 ") == "ada lovelace"
        first = store.create_entity(entity_type="person", canonical_name="Ada Lovelace")
        second = store.create_entity(entity_type="person", canonical_name="Ada Lovelace")
        assert first.id != second.id
        store.add_alias(first.id, "Ada", status="active")
        assert [item.id for item in store.find_candidates(entity_type="person", name="ada")] == [first.id]
        with pytest.raises(EntityAmbiguityError):
            store.add_alias(second.id, "Ada", status="active")
        assert store.ensure_self().entity_key == "entity:self"
        assert store.ensure_self().id == store.ensure_self().id
    finally:
        store.close()


def test_same_name_entities_keep_claims_bound_to_opaque_identity(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        first = store.create_entity(entity_type="person", canonical_name="Ada Lovelace")
        second = store.create_entity(entity_type="person", canonical_name="Ada Lovelace")
        first_claim = store.create_claim(
            subject_entity_id=first.id,
            predicate="knows",
            literal_value="Analytical Engine",
            source_text="The first Ada knows the Analytical Engine.",
            evidence_id="same-name-claim-first",
        )
        with store.conn:
            store.conn.execute(
                "UPDATE memory_graph_facts SET fact_key = ? WHERE id = ?",
                ("legacy-typed-claim-key", first_claim.id),
            )

        repeated = store.create_claim(
            subject_entity_id=first.id,
            predicate="knows",
            literal_value="Analytical Engine",
            source_text="The first Ada was confirmed again.",
            evidence_id="same-name-claim-repeat",
        )
        second_claim = store.create_claim(
            subject_entity_id=second.id,
            predicate="knows",
            literal_value="Analytical Engine",
            source_text="The second Ada knows the Analytical Engine.",
            evidence_id="same-name-claim-second",
        )

        assert repeated.id == first_claim.id
        assert repeated.support_count == 2
        assert second_claim.id != first_claim.id
        assert second_claim.fact_key != first_claim.fact_key
        assert store.get(first_claim.id).subject_entity_id == first.id
        assert store.get(second_claim.id).subject_entity_id == second.id
    finally:
        store.close()


def test_same_name_relation_endpoints_do_not_merge(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        first_person = store.create_entity(entity_type="person", canonical_name="Alex")
        second_person = store.create_entity(entity_type="person", canonical_name="Alex")
        first_project = store.create_entity(entity_type="project", canonical_name="Atlas")
        second_project = store.create_entity(entity_type="project", canonical_name="Atlas")
        first_relation = store.create_relation(
            relation_type="works_on",
            subject_entity_id=first_person.id,
            object_entity_id=first_project.id,
            source_text="The first Alex works on the first Atlas.",
            evidence_id="same-name-relation-first",
        )
        with store.conn:
            store.conn.execute(
                "UPDATE memory_graph_facts SET fact_key = ? WHERE id = ?",
                ("legacy-typed-relation-key", first_relation.id),
            )

        repeated = store.create_relation(
            relation_type="works_on",
            subject_entity_id=first_person.id,
            object_entity_id=first_project.id,
            source_text="The first relation was confirmed again.",
            evidence_id="same-name-relation-repeat",
        )
        second_relation = store.create_relation(
            relation_type="works_on",
            subject_entity_id=second_person.id,
            object_entity_id=second_project.id,
            source_text="The second Alex works on the second Atlas.",
            evidence_id="same-name-relation-second",
        )

        assert repeated.id == first_relation.id
        assert repeated.support_count == 2
        assert second_relation.id != first_relation.id
        assert second_relation.fact_key != first_relation.fact_key
        assert (store.get(first_relation.id).subject_entity_id, store.get(first_relation.id).object_entity_id) == (
            first_person.id,
            first_project.id,
        )
        assert (store.get(second_relation.id).subject_entity_id, store.get(second_relation.id).object_entity_id) == (
            second_person.id,
            second_project.id,
        )
    finally:
        store.close()


def test_evidence_replay_does_not_resurrect_forgotten_relation(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        user = store.ensure_self()
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        relation = store.create_relation(
            relation_type="works_on",
            subject_entity_id=user.id,
            object_entity_id=project.id,
            source_text="I work on Atlas.",
            evidence_id="relation-replay-evidence",
        )
        store.update_status(relation.id, "forgotten", reason="user_forget")

        replayed = store.create_relation(
            relation_type="works_on",
            subject_entity_id=user.id,
            object_entity_id=project.id,
            source_text="I work on Atlas.",
            evidence_id="relation-replay-evidence",
        )

        assert replayed.id == relation.id
        assert replayed.status.value == "forgotten"
        assert replayed.support_count == 1
        assert store.traverse(user.id) == []
    finally:
        store.close()


def test_claim_relation_traversal_and_evidence_gate(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        evidence_id = "evidence-1"
        claim = store.create_claim(
            subject_entity_id=self_entity.id,
            predicate="prefers",
            literal_value="concise answers",
            source_text="I prefer concise answers.",
            evidence_id=evidence_id,
        )
        relation = store.create_relation(
            relation_type="works_on",
            subject_entity_id=self_entity.id,
            object_entity_id=project.id,
            source_text="I work on Atlas.",
            evidence_id="evidence-2",
            confidence=0.9,
        )
        assert claim.statement_kind == "claim"
        assert relation.statement_kind == "relation"
        assert relation.relation_type == "works_on"
        assert len(store.traverse(self_entity.id, max_hops=2)) == 1
        quarantined = store.create_relation(
            relation_type="related_to",
            subject_entity_id=self_entity.id,
            object_entity_id=project.id,
            source_text="Model guessed a relation.",
            confidence=0.8,
        )
        assert quarantined.status.value == "quarantined"
        assert all(item.fact.id != quarantined.id for item in store.traverse(self_entity.id))
        # A legacy/manual row cannot bypass the evidence gate merely by
        # changing its lifecycle status.
        with sqlite3.connect(db) as conn:
            conn.execute("UPDATE memory_graph_facts SET status = 'active' WHERE id = ?", (quarantined.id,))
            conn.commit()
        assert all(item.fact.id != quarantined.id for item in store.traverse(self_entity.id))
        with pytest.raises(EntityGraphError):
            store.create_relation(
                relation_type="works_on",
                subject_entity_id=self_entity.id,
                object_fact_id=claim.id,
                source_text="invalid endpoint",
            )
    finally:
        store.close()


def test_vault_bindings_and_projection_generation_stale_on_revision_change(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        page = store.create_entity(entity_type="wiki_page", canonical_name="Atlas page")
        with sqlite3.connect(db) as conn:
            vault_one = conn.execute("SELECT id FROM vaults ORDER BY id LIMIT 1").fetchone()
            if vault_one is None:
                conn.execute(
                    "INSERT INTO vaults (id, root_path, name, created_at, updated_at) VALUES ('vault-1', ?, 'one', ?, ?)",
                    (str(tmp_path / "one"), utc_now_iso(), utc_now_iso()),
                )
                conn.execute(
                    "INSERT INTO vaults (id, root_path, name, created_at, updated_at) VALUES ('vault-2', ?, 'two', ?, ?)",
                    (str(tmp_path / "two"), utc_now_iso(), utc_now_iso()),
                )
                conn.commit()
                vault_ids = ("vault-1", "vault-2")
            else:
                vault_ids = (str(vault_one[0]), str(vault_one[0]) + "-other")
                conn.execute(
                    "INSERT OR IGNORE INTO vaults (id, root_path, name, created_at, updated_at) VALUES (?, ?, 'two', ?, ?)",
                    (vault_ids[1], str(tmp_path / "two"), utc_now_iso(), utc_now_iso()),
                )
                conn.commit()
        store.bind_wiki_page(vault_id=vault_ids[0], page_entity_id=page.id, wiki_relative_path="Wiki/Atlas.md", content_hash="a")
        other_page = store.create_entity(entity_type="wiki_page", canonical_name="Atlas page copy")
        store.bind_wiki_page(vault_id=vault_ids[1], page_entity_id=other_page.id, wiki_relative_path="Wiki/Atlas.md", content_hash="b")
        with pytest.raises(EntityGraphError):
            store.bind_wiki_page(vault_id=vault_ids[0], page_entity_id=page.id, wiki_relative_path="Notes/Atlas.md", content_hash="x")
        before = store.source_revision()
        generation = store.start_projection_generation()
        assert generation.source_revision == before
        store.add_alias(page.id, "Atlas Wiki")
        finished = store.finish_projection_generation(generation.id, success=True)
        assert finished.status == "stale"
    finally:
        store.close()


def test_relation_endpoint_matrix_rejects_untyped_provenance_edges(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        source = store.create_entity(entity_type="source", canonical_name="Chat source")
        page = store.create_entity(entity_type="wiki_page", canonical_name="Atlas page")
        fact = store.create_claim(
            subject_entity_id=self_entity.id,
            predicate="prefers",
            literal_value="concise answers",
            source_text="I prefer concise answers.",
            evidence_id="evidence-claim",
        )

        with pytest.raises(EntityGraphError, match="relation_endpoint_type_invalid"):
            store.create_relation(
                relation_type="works_on",
                subject_entity_id=self_entity.id,
                object_fact_id=fact.id,
                source_text="invalid entity-to-fact relation",
                evidence_id="evidence-invalid-works-on",
            )
        with pytest.raises(EntityGraphError, match="supports_subject_must_be_source"):
            store.create_relation(
                relation_type="supports",
                subject_entity_id=project.id,
                object_fact_id=fact.id,
                source_text="a project is not a provenance source",
                evidence_id="evidence-invalid-supports",
            )
        with pytest.raises(EntityGraphError, match="documented_in_object_must_be_wiki_page"):
            store.create_relation(
                relation_type="documented_in",
                subject_entity_id=self_entity.id,
                object_entity_id=project.id,
                source_text="project is not a Wiki page",
                evidence_id="evidence-invalid-doc",
            )

        valid_support = store.create_relation(
            relation_type="supports",
            subject_entity_id=source.id,
            object_fact_id=fact.id,
            source_text="The chat source supports the preference.",
            evidence_id="evidence-valid-support",
        )
        valid_documentation = store.create_relation(
            relation_type="documented_in",
            subject_entity_id=project.id,
            object_entity_id=page.id,
            source_text="Atlas is documented in the Wiki page.",
            evidence_id="evidence-valid-doc",
        )
        assert valid_support.status.value == "active"
        assert valid_documentation.status.value == "active"
    finally:
        store.close()


def test_contradiction_orientation_is_deterministic(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        first = store.create_claim(
            subject_entity_id=self_entity.id,
            predicate="prefers",
            literal_value="apple",
            source_text="I prefer apples.",
            evidence_id="evidence-first",
        )
        second = store.create_claim(
            subject_entity_id=self_entity.id,
            predicate="prefers",
            literal_value="banana",
            source_text="I prefer bananas.",
            evidence_id="evidence-second",
        )
        forward = store.create_relation(
            relation_type="contradicts",
            subject_fact_id=second.id,
            object_fact_id=first.id,
            source_text="The two preferences conflict.",
            evidence_id="evidence-conflict-forward",
        )
        reverse = store.create_relation(
            relation_type="contradicts",
            subject_fact_id=first.id,
            object_fact_id=second.id,
            source_text="The same conflict was observed in reverse order.",
            evidence_id="evidence-conflict-reverse",
        )
        assert forward.id == reverse.id
        assert forward.subject_fact_id == min(first.id, second.id)
        assert forward.object_fact_id == max(first.id, second.id)
    finally:
        store.close()


def test_atomic_graph_changes_increment_revision_once_and_rollback_cleanly(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        before = store.source_revision()
        with store.atomic():
            self_entity = store.ensure_self()
            project = store.create_entity(entity_type="project", canonical_name="One transaction")
            relation = store.create_relation(
                relation_type="works_on",
                subject_entity_id=self_entity.id,
                object_entity_id=project.id,
                source_text="I work on One transaction.",
                evidence_id="evidence-atomic",
            )
        assert relation.statement_kind == "relation"
        assert store.source_revision() == before + 1

        committed_ids = {self_entity.id, project.id, relation.id}
        with pytest.raises(RuntimeError, match="abort"):
            with store.atomic():
                transient = store.create_entity(entity_type="concept", canonical_name="Transient")
                raise RuntimeError("abort")

        assert store.source_revision() == before + 1
        rows = store.conn.execute(
            "SELECT id FROM memory_entities WHERE id = ?",
            (transient.id,),
        ).fetchall()
        assert rows == []
        assert committed_ids.issubset(
            {row["id"] for row in store.conn.execute("SELECT id FROM memory_entities").fetchall()}
            | {relation.id}
        )
    finally:
        store.close()


def test_answerable_facts_require_typed_evidence_and_active_lifecycle(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        typed = store.create_claim(
            subject_entity_id=self_entity.id,
            predicate="prefers",
            literal_value="SQLite authority",
            source_text="I prefer SQLite authority.",
            evidence_id="evidence-answerable",
        )
        legacy = store.graph.upsert_candidate(
            MemoryFactCandidate(
                category="preference",
                subject="legacy",
                predicate="is",
                object="untyped",
                source_text="legacy fact",
                confidence=0.95,
            )
        ).fact
        assert [fact.id for fact in store.answerable_facts(query="authority")] == [typed.id]
        assert legacy.id not in {fact.id for fact in store.answerable_facts(query="legacy")}
        store.graph.update_status(typed.id, "forgotten", reason="test_forget")
        assert store.answerable_facts(query="authority") == []
    finally:
        store.close()


def test_answerable_graph_facts_expand_two_hops_from_entity_alias(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        self_entity = store.ensure_self()
        project = store.create_entity(entity_type="project", canonical_name="Atlas")
        concept = store.create_entity(entity_type="concept", canonical_name="Evidence graph")
        first = store.create_relation(
            relation_type="works_on",
            subject_entity_id=self_entity.id,
            object_entity_id=project.id,
            source_text="recorded link one",
            evidence_id="evidence-hop-one",
        )
        second = store.create_relation(
            relation_type="related_to",
            subject_entity_id=project.id,
            object_entity_id=concept.id,
            source_text="recorded link two",
            evidence_id="evidence-hop-two",
        )
        found = store.answerable_graph_facts(query="Atlas", max_hops=2, limit=10)
        assert {fact.id for fact in found} == {first.id, second.id}
    finally:
        store.close()


def test_answerable_graph_facts_do_not_expand_substring_entity_names(tmp_path: Path) -> None:
    db = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db)
    try:
        atlas = store.create_entity(entity_type="project", canonical_name="Atlas")
        atlas_x = store.create_entity(entity_type="project", canonical_name="AtlasX")
        atlas_concept = store.create_entity(entity_type="concept", canonical_name="Atlas evidence")
        atlas_x_concept = store.create_entity(entity_type="concept", canonical_name="AtlasX evidence")
        atlas_relation = store.create_relation(
            relation_type="related_to",
            subject_entity_id=atlas.id,
            object_entity_id=atlas_concept.id,
            source_text="Atlas uses its own evidence model.",
            evidence_id="evidence-atlas",
        )
        atlas_x_relation = store.create_relation(
            relation_type="related_to",
            subject_entity_id=atlas_x.id,
            object_entity_id=atlas_x_concept.id,
            source_text="AtlasX uses a different evidence model.",
            evidence_id="evidence-atlas-x",
        )

        found = store.answerable_graph_facts(query="Atlas", max_hops=2, limit=10)

        assert atlas_relation.id in {fact.id for fact in found}
        assert atlas_x_relation.id not in {fact.id for fact in found}
    finally:
        store.close()
