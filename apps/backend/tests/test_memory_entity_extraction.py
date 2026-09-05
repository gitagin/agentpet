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
        # 自指实体「我」映射到唯一的 self 实体（active，用户本人锚点），
        # 其余实体（Atlas 项目）保持候选态等待确认。
        self_entity = next(entity for entity in result.entities.values() if entity.entity_type == "self")
        assert self_entity.status == "active"
        assert all(
            entity.status == "candidate"
            for entity in result.entities.values()
            if entity.entity_type != "self"
        )
    finally:
        store.close()


def test_self_reference_maps_to_singleton_self_entity_regardless_of_model_type(tmp_path) -> None:
    """模型把「我」误标成 person/concept 时，仍应映射到唯一 self 实体，不产生重复点。"""
    text = "我喜欢喝牛奶"
    payload = {
        "schema_version": EXTRACTION_SCHEMA_VERSION,
        "entities": [
            {
                "entity_ref": "me",
                "entity_type": "person",
                "name": "我",
                "aliases": [],
                "confidence": 0.9,
                "evidence": {"start": 0, "end": 1},
            },
            {
                "entity_ref": "milk",
                "entity_type": "preference",
                "name": "牛奶",
                "aliases": [],
                "confidence": 0.9,
                "evidence": {"start": 4, "end": 6},
            },
        ],
        "claims": [],
        "relations": [
            {
                "subject": {"kind": "entity", "ref": "me"},
                "relation": "prefers",
                "object": {"kind": "entity", "ref": "milk"},
                "confidence": 0.9,
                "evidence": {"start": 0, "end": 6},
            }
        ],
        "sensitive": [],
        "conflicts": [],
        "uncertainties": [],
    }
    batch = parse_extraction_output(payload, text)
    store = MemoryEntityGraphStore(migrate_db(tmp_path / "state.sqlite3"))
    try:
        result = persist_extraction_candidates(
            store,
            batch,
            source_text=text,
            source_type="user_message",
            source_id="message-self",
        )
        me = result.entities["me"]
        assert me.entity_type == "self"
        assert me.status == "active"
        assert me.entity_key == "entity:self"
        # 只有唯一一个 self 实体，没有新建 person「我」重复点
        assert store.conn.execute(
            "SELECT COUNT(*) FROM memory_entities WHERE entity_type = 'self'"
        ).fetchone()[0] == 1
        assert store.conn.execute(
            "SELECT COUNT(*) FROM memory_entities WHERE entity_type = 'person'"
        ).fetchone()[0] == 0
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
        # 用非自指的 Atlas 项目实体验证高风险拦截：自指「我」会映射到低风险 self 实体。
        high_payload["entities"][1] = {
            **high_payload["entities"][1],
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

        self_entity = next(entity for entity in resolved.entities.values() if entity.entity_type == "self")
        assert self_entity.status == "active"
        assert all(
            entity.status == "candidate"
            for entity in resolved.entities.values()
            if entity.entity_type != "self"
        )
        assert all(
            store.get(fact_id).status.value == "candidate"
            for fact_id in resolved.claim_ids.values()
        )
    finally:
        store.close()
