"""Closed-world entity extraction and deterministic disambiguation.

The model may suggest entities, claims and low-risk relations.  This module
validates that suggestion as a complete batch before any SQLite write.  It
never activates a fact: callers must pass the resulting candidates through
the lifecycle service and an explicit policy decision.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.services.memory_entity_graph import (
    ENTITY_RELATION_TYPES,
    EntityAmbiguityError,
    EntityGraphError,
    MemoryEntity,
    MemoryEntityGraphStore,
    normalize_entity_name,
)
from app.services.memory_graph import MemoryGraphFact
from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import LOW_CONFIDENCE_THRESHOLD
from app.utils.hash import sha256_hex


ExtractionSchemaVersion = Literal["llmwiki.entity-extraction.v1"]
EXTRACTION_SCHEMA_VERSION: ExtractionSchemaVersion = "llmwiki.entity-extraction.v1"
MODEL_RELATION_TYPES = frozenset(
    {
        "prefers",
        "avoids",
        "works_on",
        "knows",
        "related_to",
        "occurred_in",
        "supports",
        "contradicts",
    }
)


class ExtractionValidationError(ValueError):
    """A whole extraction batch is unsafe and was not persisted."""


_PROMPT_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "reveal the system",
    "execute tool",
    "call the tool",
    "忽略之前的指令",
    "忽略以上规则",
    "忽略系统提示",
    "执行工具",
    "调用工具",
    "泄露系统提示",
)


def detect_prompt_injection(source_text: str) -> bool:
    normalized = re.sub(r"\s+", " ", str(source_text or "").casefold()).strip()
    return any(marker in normalized for marker in _PROMPT_INJECTION_MARKERS)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceSpan(_StrictModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def end_after_start(self) -> "EvidenceSpan":
        if self.end <= self.start:
            raise ValueError("evidence_span_empty")
        return self


class ExtractedEntity(_StrictModel):
    entity_ref: str = Field(min_length=1, max_length=80)
    entity_type: Literal[
        "self",
        "person",
        "project",
        "preference",
        "boundary",
        "goal",
        "event",
        "concept",
        "source",
        "wiki_page",
        "decision",
    ]
    name: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    risk_tier: Literal["low", "medium", "high"] = "low"
    evidence: EvidenceSpan


class Endpoint(_StrictModel):
    kind: Literal["entity", "claim"]
    ref: str = Field(min_length=1, max_length=80)


class ExtractedClaim(_StrictModel):
    claim_ref: str = Field(min_length=1, max_length=80)
    subject_entity_ref: str = Field(min_length=1, max_length=80)
    predicate: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=1000)
    fact_type: str = Field(min_length=1, max_length=80)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EvidenceSpan


class ExtractedRelation(_StrictModel):
    subject: Endpoint
    relation: str = Field(min_length=1, max_length=40)
    object: Endpoint
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: EvidenceSpan


class ExtractionBatch(_StrictModel):
    schema_version: ExtractionSchemaVersion
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=100)
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=200)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=300)
    sensitive: list[str] = Field(default_factory=list, max_length=50)
    conflicts: list[str] = Field(default_factory=list, max_length=50)
    uncertainties: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_references_and_relations(self) -> "ExtractionBatch":
        entity_refs = {item.entity_ref for item in self.entities}
        claim_refs = {item.claim_ref for item in self.claims}
        if len(entity_refs) != len(self.entities) or len(claim_refs) != len(self.claims):
            raise ValueError("extraction_duplicate_reference")
        for claim in self.claims:
            if claim.subject_entity_ref not in entity_refs:
                raise ValueError("claim_subject_reference_missing")
        for relation in self.relations:
            relation_name = relation.relation.casefold()
            if relation_name not in MODEL_RELATION_TYPES:
                raise ValueError("model_relation_not_allowed")
            _validate_endpoint(relation.subject, entity_refs, claim_refs)
            _validate_endpoint(relation.object, entity_refs, claim_refs)
            if relation_name in ENTITY_RELATION_TYPES and (
                relation.subject.kind != "entity" or relation.object.kind != "entity"
            ):
                raise ValueError("entity_relation_endpoint_invalid")
            if relation_name == "supports" and (
                relation.object.kind != "claim" or relation.subject.kind not in {"entity", "claim"}
            ):
                raise ValueError("supports_endpoint_invalid")
            if relation_name == "contradicts" and (
                relation.subject.kind != "claim" or relation.object.kind != "claim"
            ):
                raise ValueError("contradicts_endpoint_invalid")
        return self


def _validate_endpoint(endpoint: Endpoint, entity_refs: set[str], claim_refs: set[str]) -> None:
    refs = entity_refs if endpoint.kind == "entity" else claim_refs
    if endpoint.ref not in refs:
        raise ValueError("relation_endpoint_reference_missing")


@dataclass(frozen=True, slots=True)
class ResolvedExtraction:
    entities: Mapping[str, MemoryEntity]
    claim_ids: Mapping[str, str]
    relation_ids: tuple[str, ...]
    unresolved_entities: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExtractionActivationResult:
    """Deterministic result of promoting one validated extraction batch."""

    entity_ids: tuple[str, ...] = ()
    fact_ids: tuple[str, ...] = ()
    skipped_fact_ids: tuple[str, ...] = ()
    reason: str | None = None


def parse_extraction_output(raw: object, source_text: str) -> ExtractionBatch:
    """Parse exactly one JSON payload and validate every evidence span."""
    if detect_prompt_injection(source_text):
        raise ExtractionValidationError("extraction_prompt_injection")
    payload: object = raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ExtractionValidationError("extraction_json_invalid") from exc
    if not isinstance(payload, dict):
        raise ExtractionValidationError("extraction_payload_not_object")
    try:
        batch = ExtractionBatch.model_validate(payload)
    except ValidationError as exc:
        raise ExtractionValidationError("extraction_schema_invalid") from exc
    text_length = len(source_text)
    evidence_spans = (
        *(entity.evidence for entity in batch.entities),
        *(claim.evidence for claim in batch.claims),
        *(relation.evidence for relation in batch.relations),
    )
    for evidence in evidence_spans:
        if evidence.end > text_length:
            raise ExtractionValidationError("extraction_evidence_out_of_bounds")
    return batch


def extract_with_policy(source_text: str, invoke_model: Callable[[str], object]) -> ExtractionBatch:
    """Apply the source policy before invoking a remote extraction model."""
    if detect_prompt_injection(source_text):
        raise ExtractionValidationError("extraction_prompt_injection")
    return parse_extraction_output(invoke_model(source_text), source_text)


# 自指实体名：这些名字在任何语境下都指"用户本人"，必须映射到唯一的 self 实体，
# 而不是按模型可能误标的 entity_type（person/concept 等）新建同名重复点。
_SELF_REFERENCE_NAMES = frozenset({"self", "myself", "user", "me", "我", "自己", "本人"})


def _is_self_reference(name: str) -> bool:
    return normalize_entity_name(name) in _SELF_REFERENCE_NAMES


def resolve_entity_candidates(
    store: MemoryEntityGraphStore,
    batch: ExtractionBatch,
) -> tuple[dict[str, MemoryEntity], tuple[str, ...]]:
    """Resolve only exact canonical/active alias matches.

    Fuzzy matches are returned as unresolved refs; callers may ask the user to
    choose rather than silently merging two people with the same name.
    """
    resolved: dict[str, MemoryEntity] = {}
    unresolved: list[str] = []
    for item in batch.entities:
        # 自指（"我/自己/self"）永远指向用户本人：直接复用唯一的 self 实体。
        # 否则模型常把"我"标成 person/concept，会新建一个与中心"我"重复的节点。
        if _is_self_reference(item.name):
            resolved[item.entity_ref] = store.ensure_self()
            continue
        candidates = store.find_candidates(entity_type=item.entity_type, name=item.name)
        if len(candidates) > 1:
            raise EntityAmbiguityError("entity_disambiguation_required")
        if item.risk_tier == "high" or (
            candidates and any(entity.risk_tier not in {"low", "medium"} for entity in candidates)
        ):
            # A high-risk entity can be shown in the review queue, but its
            # name must not silently bind a model claim into answer context.
            unresolved.append(item.entity_ref)
            continue
        if candidates:
            resolved[item.entity_ref] = candidates[0]
            continue
        unresolved.append(item.entity_ref)
    return resolved, tuple(unresolved)


_EVIDENCE_STOP_CHARS = "，。！？；：、,.;:!? \t\n\"'「」『』（）()[]【】<>《》"


def _align_evidence_span(text: str, start: int, end: int) -> str:
    """把模型返回的证据片段对齐到标点/空白边界，避免中文词被截断。

    模型给出的 start/end 常偏窄（如把「今天的日期」截成「今天的日」），
    这里向两侧扩展到最近的标点，最多各扩展 16 个字符。
    """
    if not text:
        return ""
    length = len(text)
    start = max(0, min(start, length))
    end = max(start, min(end, length))
    left_limit = max(0, start - 16)
    while start > left_limit and start > 0 and text[start - 1] not in _EVIDENCE_STOP_CHARS:
        start -= 1
    right_limit = min(length, end + 16)
    while end < right_limit and end < length and text[end] not in _EVIDENCE_STOP_CHARS:
        end += 1
    return text[start:end]


def persist_extraction_candidates(
    store: MemoryEntityGraphStore,
    batch: ExtractionBatch,
    *,
    source_text: str,
    source_type: str,
    source_id: str | None = None,
) -> ResolvedExtraction:
    """Persist a validated batch as non-answerable candidates.

    Existing exact entities may be reused. New entities and all model claims
    remain candidate/quarantined until deterministic lifecycle policy promotes
    them. No partial batch is written after validation succeeds.
    """
    provenance = sha256_hex(source_text)
    resolved, unresolved = resolve_entity_candidates(store, batch)
    unresolved_set = set(unresolved)
    # Replaying the identical source is safe to deduplicate.  A candidate
    # from another source is never merged by name; it remains a separate
    # identity and can be disambiguated by the user later.
    for item in batch.entities:
        if item.entity_ref not in unresolved_set:
            continue
        same_source = store.find_candidate_entities_by_source(
            entity_type=item.entity_type,
            name=item.name,
            source_hash=provenance,
        )
        if len(same_source) > 1:
            raise EntityAmbiguityError("entity_candidate_replay_ambiguous")
        if same_source:
            resolved[item.entity_ref] = same_source[0]
            unresolved_set.remove(item.entity_ref)
    unresolved = tuple(ref for ref in unresolved if ref in unresolved_set)
    claim_ids: dict[str, str] = {}
    relation_ids: list[str] = []
    with store.atomic():
        for item in batch.entities:
            entity = resolved.get(item.entity_ref)
            if entity is None:
                entity = store.create_entity(
                    entity_type=item.entity_type,
                    canonical_name=item.name,
                    status="candidate",
                    risk_tier=item.risk_tier,
                    confidence=item.confidence,
                    metadata={
                        "source_hash": provenance,
                        "source_id": source_id,
                        "extractor": EXTRACTION_SCHEMA_VERSION,
                        "candidate": True,
                    },
                )
                resolved[item.entity_ref] = entity
            for alias in item.aliases:
                if alias.strip():
                    try:
                        store.add_alias(entity.id, alias, status="candidate")
                    except EntityGraphError:
                        # Alias collisions are a disambiguation result, not a
                        # reason to merge entities or abort the safe batch.
                        continue
        # New candidate entities have an opaque identity now.  They are
        # unresolved only before persistence; callers can explicitly confirm
        # them instead of being forced through a second name lookup.
        unresolved = tuple(ref for ref in unresolved if ref not in resolved)
        for claim in batch.claims:
            subject = resolved.get(claim.subject_entity_ref)
            if subject is None:
                raise ExtractionValidationError("claim_subject_unresolved")
            fact = store.create_claim(
                subject_entity_id=subject.id,
                predicate=claim.predicate,
                literal_value=claim.value,
                category=claim.fact_type,
                source_text=_align_evidence_span(source_text, claim.evidence.start, claim.evidence.end),
                source_type=source_type,
                confidence=claim.confidence,
                evidence_id=f"extract-evidence-{sha256_hex(f'{provenance}:{claim.claim_ref}')[:32]}",
                metadata={
                    "source_hash": provenance,
                    "source_id": source_id,
                    "candidate": True,
                    "sensitive": list(batch.sensitive),
                    "conflicts": list(batch.conflicts),
                    "uncertainties": list(batch.uncertainties),
                },
            )
            # 只降级本次新建的 fact（support_count 尚未因命中而累加）。
            # 命中的既有 fact 可能已被用户确认，模型重复抽取不应把它降级。
            if fact.status.value == "active" and fact.support_count <= 1:
                fact = store.update_status(fact.id, "candidate", reason="model_extraction_candidate")
            # The same immutable evidence can explain both the claim and its
            # subject entity.  This keeps entity provenance queryable without
            # creating a second source-of-truth evidence row.
            store.bind_entity_evidence(
                entity_id=subject.id,
                evidence_id=f"extract-evidence-{sha256_hex(f'{provenance}:{claim.claim_ref}')[:32]}",
                role="describes",
            )
            claim_ids[claim.claim_ref] = fact.id
        for relation in batch.relations:
            subject_entity_id, subject_fact_id = _resolved_endpoint(relation.subject, resolved, claim_ids)
            object_entity_id, object_fact_id = _resolved_endpoint(relation.object, resolved, claim_ids)
            fact = store.create_relation(
                relation_type=relation.relation,
                subject_entity_id=subject_entity_id,
                subject_fact_id=subject_fact_id,
                object_entity_id=object_entity_id,
                object_fact_id=object_fact_id,
                source_text=_align_evidence_span(source_text, relation.evidence.start, relation.evidence.end),
                source_type=source_type,
                confidence=relation.confidence,
                evidence_id=f"extract-relation-evidence-{sha256_hex(f'{provenance}:{relation.subject.ref}:{relation.object.ref}:{relation.relation}')[:32]}",
            )
            if fact.status.value == "active" and fact.support_count <= 1:
                fact = store.update_status(fact.id, "candidate", reason="model_extraction_candidate")
            for endpoint_entity_id in (subject_entity_id, object_entity_id):
                if endpoint_entity_id:
                    store.bind_entity_evidence(
                        entity_id=endpoint_entity_id,
                        evidence_id=(
                            f"extract-relation-evidence-"
                            f"{sha256_hex(f'{provenance}:{relation.subject.ref}:{relation.object.ref}:{relation.relation}')[:32]}"
                        ),
                        role="describes",
                    )
            relation_ids.append(fact.id)
    return ResolvedExtraction(
        entities=resolved,
        claim_ids=claim_ids,
        relation_ids=tuple(relation_ids),
        unresolved_entities=unresolved,
        sensitive=tuple(batch.sensitive),
        conflicts=tuple(batch.conflicts),
        uncertainties=tuple(batch.uncertainties),
    )


def activate_extraction_candidates(
    store: MemoryEntityGraphStore,
    resolved: ResolvedExtraction,
    *,
    explicit_user: bool = False,
    reason: str = "user_confirmed_extraction",
) -> ExtractionActivationResult:
    """Promote a batch only after a deterministic confirmation decision.

    Model output is never activated by this function's default path.  The
    caller must explicitly identify a low-risk user declaration; malformed,
    unresolved, sensitive, or conflicting batches remain candidates.
    """
    if not explicit_user:
        return ExtractionActivationResult(reason="model_candidates_require_confirmation")
    if resolved.unresolved_entities:
        raise ExtractionValidationError("entity_disambiguation_required")
    if resolved.sensitive:
        raise ExtractionValidationError("sensitive_extraction_requires_local_review")
    if resolved.conflicts:
        raise ExtractionValidationError("conflicting_extraction_requires_local_review")
    if resolved.uncertainties:
        raise ExtractionValidationError("uncertain_extraction_requires_local_review")

    entity_ids = tuple(dict.fromkeys(entity.id for entity in resolved.entities.values()))
    fact_ids = tuple(dict.fromkeys((*resolved.claim_ids.values(), *resolved.relation_ids)))
    entities = tuple(store.get_entity(entity_id) for entity_id in entity_ids)
    facts = tuple(store.get(fact_id) for fact_id in fact_ids)
    for entity in entities:
        if entity.risk_tier == "high":
            raise ExtractionValidationError("sensitive_entity_requires_local_review")
        if entity.status not in {"candidate", "active"}:
            raise ExtractionValidationError("entity_not_activatable")
    if any(not _fact_source_is_allowed(fact) for fact in facts):
        raise ExtractionValidationError("sensitive_fact_requires_local_review")

    activated_entities: list[str] = []
    activated_facts: list[str] = []
    skipped_facts: list[str] = []
    fact_ids_to_activate: list[str] = []
    for fact in facts:
        if not _fact_has_evidence(store, fact.id) or fact.confidence < LOW_CONFIDENCE_THRESHOLD:
            skipped_facts.append(fact.id)
            continue
        if fact.status.value == "active":
            activated_facts.append(fact.id)
        elif fact.status.value in {"candidate", "quarantined"}:
            fact_ids_to_activate.append(fact.id)
        else:
            skipped_facts.append(fact.id)

    with store.atomic():
        for entity in entities:
            if entity.status == "candidate":
                _activate_entity_without_fact_cascade(store, entity.id)
            activated_entities.append(entity.id)
        for fact_id in fact_ids_to_activate:
            updated = store.update_status(fact_id, "active", reason=reason)
            activated_facts.append(updated.id)
    return ExtractionActivationResult(
        entity_ids=tuple(activated_entities),
        fact_ids=tuple(activated_facts),
        skipped_fact_ids=tuple(skipped_facts),
        reason=reason,
    )


def _activate_entity_without_fact_cascade(store: MemoryEntityGraphStore, entity_id: str) -> None:
    """Activate one entity and its safe aliases without reviving old facts."""
    store.activate_entity_candidate(entity_id)


def _fact_source_is_allowed(fact: MemoryGraphFact) -> bool:
    return evaluate_memory_content(fact.source_text).allowed


def _fact_has_evidence(store: MemoryEntityGraphStore, fact_id: str) -> bool:
    return (
        store.conn.execute(
            "SELECT 1 FROM memory_evidence WHERE fact_id = ? LIMIT 1",
            (fact_id,),
        ).fetchone()
        is not None
    )


def _resolved_endpoint(
    endpoint: Endpoint,
    entities: Mapping[str, MemoryEntity],
    claims: Mapping[str, str],
) -> tuple[str | None, str | None]:
    if endpoint.kind == "entity":
        entity = entities.get(endpoint.ref)
        if entity is None:
            raise ExtractionValidationError("relation_entity_unresolved")
        return entity.id, None
    fact_id = claims.get(endpoint.ref)
    if fact_id is None:
        raise ExtractionValidationError("relation_claim_unresolved")
    return None, fact_id
