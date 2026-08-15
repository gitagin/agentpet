from __future__ import annotations

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.memory_entity_extraction import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractionValidationError,
    activate_extraction_candidates,
    parse_extraction_output,
    persist_extraction_candidates,
    resolve_entity_candidates,
)
from app.services.memory_entity_graph import MemoryEntityGraphStore


def _payload() -> dict[str, object]:
    return {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "entities": [
            {
                "entity_ref": "self",
                "entity_type": "self",
                "name": "我",
                "aliases": ["用户"],
                "confidence": 1.0,
                "evidence": {"start": 0, "end": 19},
            },
            {
                "entity_ref": "project-atlas",
                "entity_type": "project",
                "name": "Atlas",
                "aliases": [],
                "confidence": 0.9,
                "evidence": {"start": 10, "end": 15},
            },
        ],
        "claims": [
            {
                "claim_ref": "claim-editor",
                "subject_entity_ref": "self",
                "predicate": "prefers",
                "value": "VS Code",
                "fact_type": "preference",
                "confidence": 0.88,
                "evidence": {"start": 0, "end": 19},
            }
        ],
        "relations": [
            {
                "subject": {"kind": "entity", "ref": "self"},
                "relation": "works_on",
                "object": {"kind": "entity", "ref": "project-atlas"},
                "confidence": 0.9,
                "evidence": {"start": 10, "end": 19},
            }
        ],
        "sensitive": [],
        "conflicts": [],
        "uncertainties": [],
    }


def test_invalid_relation_and_unknown_fields_reject_the_whole_batch() -> None:
    payload = _payload()
    payload["extra"] = True
    with pytest.raises(ExtractionValidationError, match="schema_invalid"):
        parse_extraction_output(payload, "我在做 Atlas 项目，偏好 VS Code")

    payload = _payload()
    payload["relations"] = [
        {
            "subject": {"kind": "entity", "ref": "self"},
            "relation": "supersedes",
            "object": {"kind": "claim", "ref": "claim-editor"},
            "confidence": 1.0,
            "evidence": {"start": 0, "end": 19},
        }
    ]
    with pytest.raises(ExtractionValidationError, match="schema_invalid"):
        parse_extraction_output(payload, "我在做 Atlas 项目，偏好 VS Code")


def test_evidence_bounds_are_checked_before_writes(tmp_path) -> None:
    payload = _payload()
    payload["claims"] = [
        {
            **payload["claims"][0],
            "evidence": {"start": 0, "end": 1000},
        }
    ]
    with pytest.raises(ExtractionValidationError, match="out_of_bounds"):
        parse_extraction_output(payload, "短文本")


def test_model_batch_persists_candidates_only(tmp_path) -> None:
    text = "我在做 Atlas 项目，偏好 VS Code"
    batch = parse_extraction_output(_payload(), text)
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        result = persist_extraction_candidates(
            store,
            batch,
            source_text=text,
            source_type="user_message",
            source_id="message-1",
        )
        assert result.claim_ids
        claim = store.get(next(iter(result.claim_ids.values())))
        assert claim.status.value == "candidate"
        assert all(entity.status == "candidate" for entity in result.entities.values())
    finally:
        store.close()


def test_replaying_model_batch_does_not_inflate_relation_support(tmp_path) -> None:
    text = "我在做 Atlas 项目，偏好 VS Code"
    batch = parse_extraction_output(_payload(), text)
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        first = persist_extraction_candidates(
            store,
            batch,
            source_text=text,
            source_type="user_message",
            source_id="message-replay",
        )
        first_revision = store.source_revision()
        second = persist_extraction_candidates(
            store,
            batch,
            source_text=text,
            source_type="user_message",
            source_id="message-replay",
        )

        fact_ids = (*first.claim_ids.values(), *first.relation_ids)
        assert first.claim_ids == second.claim_ids
        assert first.relation_ids == second.relation_ids
        assert all(store.get(fact_id).support_count == 1 for fact_id in fact_ids)
        assert store.source_revision() == first_revision
    finally:
        store.close()


def test_existing_high_risk_entity_is_not_silently_bound(tmp_path) -> None:
    text = "Alex is a person I know."
    payload = _payload()
    payload["entities"] = [
        {
            "entity_ref": "alex",
            "entity_type": "person",
            "name": "Alex",
            "aliases": [],
            "confidence": 0.9,
            "evidence": {"start": 0, "end": 4},
        }
    ]
    payload["claims"] = []
    payload["relations"] = []
    batch = parse_extraction_output(payload, text)
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        hidden = store.create_entity(entity_type="person", canonical_name="Alex", risk_tier="high")
        resolved, unresolved = resolve_entity_candidates(store, batch)
        assert hidden.id not in {entity.id for entity in resolved.values()}
        assert unresolved == ("alex",)
        persisted = persist_extraction_candidates(
            store,
            batch,
            source_text=text,
            source_type="user_message",
            source_id="high-risk-source",
        )
        assert persisted.entities["alex"].id != hidden.id
        assert persisted.entities["alex"].status == "candidate"
    finally:
        store.close()


def test_high_risk_and_flagged_batches_cannot_be_activated(tmp_path) -> None:
    text = "我在做 Atlas 项目，偏好 VS Code"
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        high_payload = _payload()
        high_payload["entities"][0] = {
            **high_payload["entities"][0],
            "risk_tier": "high",
        }
        high_batch = parse_extraction_output(high_payload, text)
        high_resolved = persist_extraction_candidates(
            store,
            high_batch,
            source_text=text,
            source_type="user_message",
            source_id="high-batch",
        )
        with pytest.raises(ExtractionValidationError, match="sensitive_entity"):
            activate_extraction_candidates(store, high_resolved, explicit_user=True)

        flagged_payload = _payload()
        flagged_payload["sensitive"] = ["health"]
        flagged_batch = parse_extraction_output(flagged_payload, text)
        flagged_resolved = persist_extraction_candidates(
            store,
            flagged_batch,
            source_text=text,
            source_type="user_message",
            source_id="sensitive-batch",
        )
        with pytest.raises(ExtractionValidationError, match="sensitive_extraction"):
            activate_extraction_candidates(store, flagged_resolved, explicit_user=True)
        assert all(
            store.get(fact_id).status.value == "candidate"
            for fact_id in flagged_resolved.claim_ids.values()
        )
    finally:
        store.close()


def test_sensitive_fact_source_fails_before_entity_activation(tmp_path) -> None:
    source = "password: super-secret-value Atlas"
    batch = parse_extraction_output(_payload(), source)
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        resolved = persist_extraction_candidates(
            store,
            batch,
            source_text=source,
            source_type="user_message",
            source_id="sensitive-source",
        )

        with pytest.raises(ExtractionValidationError, match="sensitive_fact"):
            activate_extraction_candidates(store, resolved, explicit_user=True)

        assert all(
            store.get_entity(entity.id).status == "candidate"
            for entity in resolved.entities.values()
        )
        assert all(
            store.get(fact_id).status.value == "candidate"
            for fact_id in resolved.claim_ids.values()
        )
    finally:
        store.close()
