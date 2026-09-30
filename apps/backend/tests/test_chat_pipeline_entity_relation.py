from __future__ import annotations

from app.services.chat_pipeline.entity_relation import _deterministic_preference_batch
from app.services.memory_entity_extraction import parse_extraction_output


def test_preference_fallback_batch_passes_evidence_validation() -> None:
    """The batch the entity stage falls back to must itself be valid.

    A rejected model batch is replaced by this deterministic one, so an
    out-of-bounds span here would lose the preference twice over.
    """
    source = "记住，我喜欢牛奶"

    fallback = _deterministic_preference_batch(source)

    assert fallback is not None
    batch = parse_extraction_output(fallback, source)
    assert [entity.entity_type for entity in batch.entities] == ["self", "preference"]
    assert [relation.relation for relation in batch.relations] == ["prefers"]


def test_preference_fallback_declines_a_message_without_a_preference() -> None:
    assert _deterministic_preference_batch("今天几号") is None
