"""Authoritative memory closure for Wiki writes.

The Wiki workflow owns the source and Markdown effect, while the typed memory
graph remains the only authority for entities, facts, relations, and artifact
bindings.  This module deliberately accepts only a versioned extraction
payload supplied in source metadata.  In the absence of that payload, ingest
creates a source entity and a quarantined provenance candidate, never an
answerable placeholder fact.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from app.repositories.storage import VaultRepository
from app.services.memory_candidates import (
    MemoryCandidateCreate,
    MemoryCandidateStore,
)
from app.services.memory_entity_extraction import (
    EXTRACTION_SCHEMA_VERSION,
    ExtractionValidationError,
    ResolvedExtraction,
    activate_extraction_candidates,
    parse_extraction_output,
    persist_extraction_candidates,
)
from app.services.memory_entity_graph import (
    EntityGraphError,
    MemoryEntity,
    MemoryEntityGraphStore,
)
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import MemoryKind, MemoryScope, RiskTier, SourceTrack
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.markdown import read_markdown
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


WIKI_EXTRACTION_METADATA_KEY = "memory_extraction"
WIKI_EXTRACTION_METADATA_VERSION = "llmwiki.wiki-extraction.v1"
EXPLICIT_USER_SOURCE_TYPES = frozenset({"explicit_user", "user_message"})


class WikiMemoryClosureError(ValueError):
    """A supplied extraction envelope failed closed validation."""

    code = "wiki_memory_closure_failed"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class WikiMemoryClosurePreparation:
    vault_id: str
    source_id: str
    source_entity_id: str
    source_evidence_id: str
    source_candidate_id: str
    source_path: str
    source_hash: str
    extraction: ResolvedExtraction | None = None
    extraction_provenance: str = "none"
    extraction_fact_ids: tuple[str, ...] = ()
    extraction_entity_ids: tuple[str, ...] = ()
    extraction_evidence_ids: tuple[str, ...] = ()

    @property
    def all_entity_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.source_entity_id, *self.extraction_entity_ids)))

    @property
    def all_fact_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.extraction_fact_ids))

    @property
    def all_evidence_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.source_evidence_id, *self.extraction_evidence_ids)))

    @property
    def explicit_user(self) -> bool:
        return self.extraction_provenance == "explicit_user"

    def page_metadata(self) -> dict[str, list[str]]:
        """Return only IDs resolved by SQLite, suitable for frontmatter."""
        return {
            "entity_ids": list(self.all_entity_ids),
            "fact_ids": list(self.all_fact_ids),
            "evidence_ids": list(self.all_evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class WikiMemoryClosureFinalization:
    active_fact_ids: tuple[str, ...] = ()
    active_entity_ids: tuple[str, ...] = ()
    wiki_page_binding_ids: tuple[str, ...] = ()
    artifact_binding_ids: tuple[str, ...] = ()
    documented_relation_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WikiSynthesisAuthority:
    vault_id: str
    target_path: str
    page_type: str
    source_paths: tuple[str, ...]
    source_hashes: tuple[str, ...]
    source_entity_ids: tuple[str, ...]
    entity_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    decision_entity_id: str | None = None

    def page_metadata(self) -> dict[str, list[str]]:
        return {
            "entity_ids": list(self.entity_ids),
            "fact_ids": list(self.fact_ids),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True, slots=True)
class _ResolvedWikiSource:
    source_hashes: tuple[str, ...]
    source_entity_ids: tuple[str, ...]
    fact_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]


def prepare_wiki_memory_closure(
    conn: sqlite3.Connection,
    *,
    vault_root: str | Path,
    source_id: str,
    source_hash: str,
    source_title: str,
    source_type: str,
    raw_content: str,
    source_path: str,
    source_metadata: Mapping[str, object] | None,
) -> WikiMemoryClosurePreparation:
    """Persist source identity and validated extraction candidates.

    Preparation is safe to replay.  It intentionally commits no active fact;
    activation and artifact binding happen only after all approved Markdown
    pages have been written and read back successfully.
    """
    actual_hash = sha256_hex(raw_content)
    if actual_hash != source_hash:
        raise WikiMemoryClosureError("source_hash_mismatch")
    vault_id = _ensure_vault(conn, vault_root)
    graph = MemoryEntityGraphStore(conn)
    candidates = MemoryCandidateStore(conn)
    try:
        source_entity = _ensure_source_entity(
            graph,
            source_hash=source_hash,
            source_id=source_id,
            source_title=source_title,
        )
        source_candidate, source_evidence_id = _ensure_source_provenance_candidate(
            candidates,
            graph,
            source_hash=source_hash,
            source_id=source_id,
            source_title=source_title,
            source_type=source_type,
            raw_content=raw_content,
        )
        graph.bind_entity_evidence(
            entity_id=source_entity.id,
            evidence_id=source_evidence_id,
            role="describes",
        )

        envelope = _read_extraction_envelope(source_metadata, raw_content)
        resolved: ResolvedExtraction | None = None
        provenance = "none"
        if envelope is not None:
            batch, provenance = envelope
            _validate_extraction_source(provenance=provenance, source_type=source_type)
            try:
                resolved = persist_extraction_candidates(
                    graph,
                    batch,
                    source_text=raw_content,
                    source_type=source_type,
                    source_id=source_id,
                )
            except (ExtractionValidationError, EntityGraphError, ValueError) as exc:
                raise WikiMemoryClosureError(f"extraction_persist_failed:{_safe_reason(exc)}") from exc
            _annotate_fact_provenance(
                graph,
                (*resolved.claim_ids.values(), *resolved.relation_ids),
                source_hash=source_hash,
                source_id=source_id,
                provenance=provenance,
            )
            _bind_source_provenance_edges(
                graph,
                resolved,
                source_entity=source_entity,
                source_hash=source_hash,
                raw_content=raw_content,
                source_type=source_type,
            )

        extraction_fact_ids = (
            tuple(dict.fromkeys((*resolved.claim_ids.values(), *resolved.relation_ids)))
            if resolved is not None
            else ()
        )
        extraction_entity_ids = (
            tuple(dict.fromkeys(entity.id for entity in resolved.entities.values()))
            if resolved is not None
            else ()
        )
        extraction_evidence_ids = _fact_evidence_ids(graph.conn, extraction_fact_ids)
        return WikiMemoryClosurePreparation(
            vault_id=vault_id,
            source_id=source_id,
            source_entity_id=source_entity.id,
            source_evidence_id=source_evidence_id,
            source_candidate_id=source_candidate.id,
            source_path=source_path,
            source_hash=source_hash,
            extraction=resolved,
            extraction_provenance=provenance,
            extraction_fact_ids=extraction_fact_ids,
            extraction_entity_ids=extraction_entity_ids,
            extraction_evidence_ids=extraction_evidence_ids,
        )
    finally:
        candidates.close()
        graph.close()


def finalize_wiki_memory_closure(
    conn: sqlite3.Connection,
    *,
    preparation: WikiMemoryClosurePreparation,
    vault_root: str | Path,
    source_type: str,
    written_paths: tuple[str, ...],
) -> WikiMemoryClosureFinalization:
    """Activate eligible facts and bind them to authoritative Wiki artifacts."""
    if not written_paths:
        return WikiMemoryClosureFinalization()
    if sha256_hex(_read_source_content(conn, preparation.source_id)) != preparation.source_hash:
        raise WikiMemoryClosureError("source_hash_changed_before_finalize")
    vault_id = _ensure_vault(conn, vault_root)
    if vault_id != preparation.vault_id:
        raise WikiMemoryClosureError("vault_identity_changed_before_finalize")

    lifecycle = MemoryLifecycleService(conn)
    graph = lifecycle.entity_graph
    active_entities: list[str] = []
    active_facts: list[str] = []
    page_bindings: list[str] = []
    artifact_bindings: list[str] = []
    documented_relations: list[str] = []
    try:
        with graph.atomic():
            source_entity = graph.get_entity(preparation.source_entity_id)
            if source_entity.status == "candidate":
                source_entity = graph.activate_entity_candidate(
                    source_entity.id,
                    reason="wiki_source_written",
                )
            elif source_entity.status != "active":
                raise WikiMemoryClosureError("source_entity_not_activatable")
            active_entities.append(source_entity.id)

            activation = None
            if preparation.extraction is not None and preparation.explicit_user:
                _validate_extraction_source(
                    provenance=preparation.extraction_provenance,
                    source_type=source_type,
                )
                try:
                    activation = activate_extraction_candidates(
                        graph,
                        preparation.extraction,
                        explicit_user=True,
                        reason="wiki_explicit_user_confirmed",
                    )
                except (ExtractionValidationError, EntityGraphError, ValueError) as exc:
                    raise WikiMemoryClosureError(f"extraction_activation_failed:{_safe_reason(exc)}") from exc
                active_entities.extend(activation.entity_ids)
                active_facts.extend(activation.fact_ids)
            elif preparation.extraction is not None:
                # A model envelope is persisted for review, never activated by
                # the Wiki confirmation gate.
                active_entities.extend(
                    entity.id
                    for entity in preparation.extraction.entities.values()
                    if entity.status == "active"
                )

            active_entities = list(dict.fromkeys(active_entities))
            active_facts = list(
                dict.fromkeys(
                    fact_id
                    for fact_id in active_facts
                    if _fact_is_active_and_grounded(graph.conn, fact_id, preparation.source_hash)
                )
            )

            for relative_path in written_paths:
                page_path = Path(vault_root) / Path(*relative_path.split("/"))
                if not page_path.is_file():
                    raise WikiMemoryClosureError("wiki_page_readback_missing")
                parsed = read_markdown(page_path)
                title = parsed.title or page_path.stem
                page_entity = _ensure_wiki_page_entity(
                    graph,
                    vault_id=vault_id,
                    relative_path=relative_path,
                    title=title,
                )
                page_binding_id = graph.bind_wiki_page(
                    vault_id=vault_id,
                    page_entity_id=page_entity.id,
                    wiki_relative_path=relative_path,
                    content_hash=parsed.content_hash,
                    revision=_frontmatter_revision(parsed.frontmatter),
                    status="active",
                )
                page_bindings.append(page_binding_id)

                page_evidence_id = _page_evidence_id(
                    source_hash=preparation.source_hash,
                    relative_path=relative_path,
                )
                source_doc = graph.create_relation(
                    relation_type="documented_in",
                    subject_entity_id=source_entity.id,
                    object_entity_id=page_entity.id,
                    source_text=f"{preparation.source_hash}:{relative_path}",
                    source_type="wiki_binding",
                    confidence=1.0,
                    evidence_id=page_evidence_id,
                )
                documented_relations.append(source_doc.id)
                _annotate_fact_provenance(
                    graph,
                    (source_doc.id,),
                    source_hash=preparation.source_hash,
                    source_id=preparation.source_id,
                    provenance="wiki_binding",
                )

                for entity_id in preparation.extraction_entity_ids if preparation.extraction else ():
                    entity = graph.get_entity(entity_id)
                    relation = graph.create_relation(
                        relation_type="documented_in",
                        subject_entity_id=entity.id,
                        object_entity_id=page_entity.id,
                        source_text=f"{preparation.source_hash}:{relative_path}",
                        source_type="wiki_binding",
                        confidence=1.0,
                        evidence_id=_entity_page_evidence_id(
                            preparation.source_hash,
                            entity.id,
                            relative_path,
                        ),
                    )
                    if entity.status != "active" and relation.status.value == "active":
                        relation = graph.update_status(
                            relation.id,
                            "candidate",
                            reason="wiki_entity_candidate",
                        )
                    documented_relations.append(relation.id)
                    _annotate_fact_provenance(
                        graph,
                        (relation.id,),
                        source_hash=preparation.source_hash,
                        source_id=preparation.source_id,
                        provenance="wiki_binding",
                    )

                for fact_id in active_facts:
                    graph.get(fact_id)
                    artifact_bindings.append(
                        graph.bind_artifact(
                            fact_id=fact_id,
                            vault_id=vault_id,
                            artifact_type="source",
                            artifact_ref=preparation.source_path,
                        )
                    )
                    artifact_bindings.append(
                        graph.bind_artifact(
                            fact_id=fact_id,
                            vault_id=vault_id,
                            artifact_type="wiki_page",
                            artifact_ref=relative_path,
                        )
                    )
                    relation = graph.create_relation(
                        relation_type="documented_in",
                        subject_fact_id=fact_id,
                        object_entity_id=page_entity.id,
                        source_text=f"{preparation.source_hash}:{relative_path}",
                        source_type="wiki_binding",
                        confidence=1.0,
                        evidence_id=_fact_page_evidence_id(
                            preparation.source_hash,
                            fact_id,
                            relative_path,
                        ),
                    )
                    documented_relations.append(relation.id)
                    _annotate_fact_provenance(
                        graph,
                        (relation.id,),
                        source_hash=preparation.source_hash,
                        source_id=preparation.source_id,
                        provenance="wiki_binding",
                    )

            return WikiMemoryClosureFinalization(
                active_fact_ids=tuple(dict.fromkeys(active_facts)),
                active_entity_ids=tuple(dict.fromkeys(active_entities)),
                wiki_page_binding_ids=tuple(dict.fromkeys(page_bindings)),
                artifact_binding_ids=tuple(dict.fromkeys(artifact_bindings)),
                documented_relation_ids=tuple(dict.fromkeys(documented_relations)),
            )
    finally:
        lifecycle.close()


def prepare_wiki_synthesis_authority(
    conn: sqlite3.Connection,
    *,
    vault_root: str | Path,
    target_path: str,
    page_type: str,
    title: str,
    source_paths: tuple[str, ...] | list[str],
    requested_entity_ids: tuple[str, ...] | list[str] = (),
    requested_fact_ids: tuple[str, ...] | list[str] = (),
    requested_evidence_ids: tuple[str, ...] | list[str] = (),
) -> WikiSynthesisAuthority:
    """Resolve a derived page only from active, hash-verified authority rows."""
    vault_id = _ensure_vault(conn, vault_root)
    graph = MemoryEntityGraphStore(conn)
    try:
        normalized_sources = tuple(dict.fromkeys(_safe_wiki_source_path(path) for path in source_paths))
        if not normalized_sources:
            raise WikiMemoryClosureError(f"{page_type}_requires_source_reference")

        resolved_cache: dict[str, _ResolvedWikiSource] = {}
        resolved_sources: list[_ResolvedWikiSource] = []
        for source_path in normalized_sources:
            resolved_sources.append(
                _resolve_authoritative_wiki_source(
                    conn,
                    graph,
                    vault_root=Path(vault_root),
                    vault_id=vault_id,
                    source_path=source_path,
                    resolving=(),
                    cache=resolved_cache,
                )
            )

        source_hashes = tuple(
            dict.fromkeys(
                source_hash
                for resolved in resolved_sources
                for source_hash in resolved.source_hashes
            )
        )
        if page_type in {"synthesis", "comparison"} and len(source_hashes) < 2:
            raise WikiMemoryClosureError("synthesis_sources_not_independent")
        source_entity_ids = tuple(
            dict.fromkeys(
                entity_id
                for resolved in resolved_sources
                for entity_id in resolved.source_entity_ids
            )
        )
        fact_ids = tuple(
            dict.fromkeys(
                fact_id
                for resolved in resolved_sources
                for fact_id in resolved.fact_ids
            )
        )
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id
                for resolved in resolved_sources
                for evidence_id in resolved.evidence_ids
            )
        )

        derived_fact_ids = fact_ids
        derived_entity_ids = tuple(dict.fromkeys(_entity_ids_for_facts(conn, derived_fact_ids)))
        _validate_requested_ids(
            graph,
            vault_id=vault_id,
            requested_entity_ids=requested_entity_ids,
            requested_fact_ids=requested_fact_ids,
            requested_evidence_ids=requested_evidence_ids,
            allowed_entity_ids=(*source_entity_ids, *derived_entity_ids),
            allowed_fact_ids=derived_fact_ids,
            allowed_evidence_ids=evidence_ids,
        )

        decision_entity_id: str | None = None
        if page_type == "decision":
            decision_entity = _ensure_decision_entity_candidate(
                graph,
                vault_id=vault_id,
                target_path=target_path,
                title=title,
            )
            decision_entity_id = decision_entity.id

        entity_ids = tuple(
            dict.fromkeys(
                (
                    *source_entity_ids,
                    *derived_entity_ids,
                    *requested_entity_ids,
                    *((decision_entity_id,) if decision_entity_id else ()),
                )
            )
        )
        return WikiSynthesisAuthority(
            vault_id=vault_id,
            target_path=target_path,
            page_type=page_type,
            source_paths=normalized_sources,
            source_hashes=source_hashes,
            source_entity_ids=source_entity_ids,
            entity_ids=entity_ids,
            fact_ids=tuple(dict.fromkeys((*derived_fact_ids, *requested_fact_ids))),
            evidence_ids=tuple(dict.fromkeys((*evidence_ids, *requested_evidence_ids))),
            decision_entity_id=decision_entity_id,
        )
    finally:
        graph.close()


def finalize_wiki_synthesis_authority(
    conn: sqlite3.Connection,
    *,
    authority: WikiSynthesisAuthority,
    vault_root: str | Path,
) -> WikiMemoryClosureFinalization:
    """Bind a derived page after its Markdown bytes have been read back."""
    page_path = Path(vault_root) / Path(*authority.target_path.split("/"))
    if not page_path.is_file():
        raise WikiMemoryClosureError("wiki_page_readback_missing")
    parsed = read_markdown(page_path)
    if tuple(_frontmatter_list(parsed.frontmatter, "sources")) != authority.source_paths:
        raise WikiMemoryClosureError("synthesis_source_frontmatter_mismatch")
    if tuple(_frontmatter_list(parsed.frontmatter, "entity_ids")) != authority.entity_ids:
        raise WikiMemoryClosureError("synthesis_entity_frontmatter_mismatch")
    if tuple(_frontmatter_list(parsed.frontmatter, "fact_ids")) != authority.fact_ids:
        raise WikiMemoryClosureError("synthesis_fact_frontmatter_mismatch")
    if tuple(_frontmatter_list(parsed.frontmatter, "evidence_ids")) != authority.evidence_ids:
        raise WikiMemoryClosureError("synthesis_evidence_frontmatter_mismatch")

    graph = MemoryEntityGraphStore(conn)
    page_bindings: list[str] = []
    artifact_bindings: list[str] = []
    documented_relations: list[str] = []
    try:
        with graph.atomic():
            page_bindings.append(
                bind_authoritative_wiki_page(
                    graph,
                    vault_id=authority.vault_id,
                    relative_path=authority.target_path,
                    parsed=parsed,
                    status="active",
                )
            )
            page_binding = graph.get_wiki_binding(
                vault_id=authority.vault_id,
                wiki_relative_path=authority.target_path,
            )
            if page_binding is None:
                raise WikiMemoryClosureError("wiki_page_binding_readback_missing")
            page_entity = graph.get_entity(str(page_binding["page_entity_id"]))
            for source_entity_id in authority.source_entity_ids:
                source_entity = graph.get_entity(source_entity_id)
                if source_entity.status != "active" or source_entity.entity_type != "source":
                    raise WikiMemoryClosureError("synthesis_source_entity_not_active")
                documented_relations.append(
                    graph.create_relation(
                        relation_type="documented_in",
                        subject_entity_id=source_entity.id,
                        object_entity_id=page_entity.id,
                        source_text=f"{':'.join(authority.source_hashes)}:{authority.target_path}",
                        source_type="wiki_binding",
                        confidence=1.0,
                        evidence_id=_stable_id(
                            "wiki-synthesis-source-page-evidence",
                            source_entity.id,
                            authority.target_path,
                        ),
                    ).id
                )
            for fact_id in authority.fact_ids:
                if not graph.statement_recallable(fact_id, vault_id=authority.vault_id):
                    raise WikiMemoryClosureError("synthesis_fact_not_recallable")
                artifact_bindings.append(
                    graph.bind_artifact(
                        fact_id=fact_id,
                        vault_id=authority.vault_id,
                        artifact_type="wiki_page",
                        artifact_ref=authority.target_path,
                    )
                )
                documented_relations.append(
                    graph.create_relation(
                        relation_type="documented_in",
                        subject_fact_id=fact_id,
                        object_entity_id=page_entity.id,
                        source_text=f"{':'.join(authority.source_hashes)}:{authority.target_path}",
                        source_type="wiki_binding",
                        confidence=1.0,
                        evidence_id=_stable_id("wiki-synthesis-page-evidence", fact_id, authority.target_path),
                    ).id
                )
            if authority.decision_entity_id is not None:
                decision_entity = graph.get_entity(authority.decision_entity_id)
                if decision_entity.status == "candidate":
                    decision_entity = graph.activate_entity_candidate(
                        decision_entity.id,
                        reason="wiki_decision_written",
                    )
                elif decision_entity.status != "active":
                    raise WikiMemoryClosureError("decision_entity_not_activatable")
                documented_relations.append(
                    graph.create_relation(
                        relation_type="documented_in",
                        subject_entity_id=decision_entity.id,
                        object_entity_id=page_entity.id,
                        source_text=f"{':'.join(authority.source_hashes)}:{authority.target_path}",
                        source_type="wiki_binding",
                        confidence=1.0,
                        evidence_id=_stable_id(
                            "wiki-decision-page-evidence",
                            authority.decision_entity_id,
                            authority.target_path,
                        ),
                    ).id
                )
        return WikiMemoryClosureFinalization(
            active_fact_ids=authority.fact_ids,
            active_entity_ids=authority.entity_ids,
            wiki_page_binding_ids=tuple(page_bindings),
            artifact_binding_ids=tuple(artifact_bindings),
            documented_relation_ids=tuple(documented_relations),
        )
    finally:
        graph.close()


def _read_extraction_envelope(
    source_metadata: Mapping[str, object] | None,
    source_text: str,
) -> tuple[Any, str] | None:
    if not source_metadata or WIKI_EXTRACTION_METADATA_KEY not in source_metadata:
        return None
    raw = source_metadata.get(WIKI_EXTRACTION_METADATA_KEY)
    if not isinstance(raw, Mapping):
        raise WikiMemoryClosureError("extraction_envelope_invalid")

    provenance = str(raw.get("provenance") or "").strip().casefold()
    if provenance not in {"model", "explicit_user"}:
        raise WikiMemoryClosureError("extraction_provenance_invalid")
    if str(raw.get("wrapper_version") or "") != WIKI_EXTRACTION_METADATA_VERSION:
        raise WikiMemoryClosureError("extraction_wrapper_version_invalid")

    payload = raw.get("payload")
    if not isinstance(payload, Mapping) or str(payload.get("schema_version") or "") != EXTRACTION_SCHEMA_VERSION:
        raise WikiMemoryClosureError("extraction_schema_version_invalid")
    try:
        return parse_extraction_output(payload, source_text), provenance
    except (ExtractionValidationError, ValueError) as exc:
        raise WikiMemoryClosureError(f"extraction_payload_invalid:{_safe_reason(exc)}") from exc


def _safe_wiki_source_path(value: object) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    if (
        not normalized.startswith("Wiki/")
        or normalized.startswith("Wiki/../")
        or "/../" in normalized
        or not normalized.endswith(".md")
    ):
        raise WikiMemoryClosureError("synthesis_source_path_invalid")
    return normalized


def _direct_source_hash_for_page(
    conn: sqlite3.Connection,
    parsed,
    source_path: str,
) -> str | None:
    page_type = str(parsed.frontmatter.get("page_type") or parsed.frontmatter.get("type") or "").strip()
    if page_type != "source" or not source_path.startswith("Wiki/Sources/"):
        return None
    raw_hashes = re.findall(r"(?m)^- 来源哈希：`([0-9a-f]{64})`\s*$", parsed.body)
    hashes = tuple(dict.fromkeys(raw_hashes))
    if len(hashes) > 1:
        raise WikiMemoryClosureError("synthesis_source_hash_ambiguous")
    if hashes:
        row = conn.execute(
            "SELECT raw_content, content_preview FROM wiki_sources WHERE source_hash = ?",
            (hashes[0],),
        ).fetchone()
        if row is None or sha256_hex(str(row["raw_content"] or row["content_preview"] or "")) != hashes[0]:
            raise WikiMemoryClosureError("synthesis_source_hash_not_authoritative")
        return hashes[0]
    return None


def _resolve_authoritative_wiki_source(
    conn: sqlite3.Connection,
    graph: MemoryEntityGraphStore,
    *,
    vault_root: Path,
    vault_id: str,
    source_path: str,
    resolving: tuple[str, ...],
    cache: dict[str, _ResolvedWikiSource],
) -> _ResolvedWikiSource:
    cached = cache.get(source_path)
    if cached is not None:
        return cached
    if source_path in resolving:
        raise WikiMemoryClosureError("synthesis_source_cycle")

    page_path = vault_root / Path(*source_path.split("/"))
    if not page_path.is_file():
        raise WikiMemoryClosureError("synthesis_source_page_missing")
    parsed = read_markdown(page_path)
    binding = graph.get_wiki_binding(vault_id=vault_id, wiki_relative_path=source_path)
    if binding is None:
        raise WikiMemoryClosureError("synthesis_source_binding_missing")
    if str(binding["status"] or "") != "active":
        raise WikiMemoryClosureError("synthesis_source_binding_not_active")
    if str(binding["content_hash"] or "") != parsed.content_hash:
        raise WikiMemoryClosureError("synthesis_source_binding_hash_mismatch")

    page_entity_id = str(binding["page_entity_id"])
    page_fact_ids = _active_facts_for_page(conn, page_entity_id, vault_id=vault_id)
    direct_hash = _direct_source_hash_for_page(conn, parsed, source_path)
    if direct_hash is not None:
        resolved = _ResolvedWikiSource(
            source_hashes=(direct_hash,),
            source_entity_ids=_source_entities_for_page(conn, page_entity_id, direct_hash),
            fact_ids=page_fact_ids,
            evidence_ids=_evidence_ids_for_hash(conn, direct_hash),
        )
        cache[source_path] = resolved
        return resolved

    parent_paths = tuple(
        dict.fromkeys(
            _safe_wiki_source_path(path)
            for path in _frontmatter_list(parsed.frontmatter, "sources")
        )
    )
    if not parent_paths:
        raise WikiMemoryClosureError("synthesis_source_provenance_missing")
    parents = tuple(
        _resolve_authoritative_wiki_source(
            conn,
            graph,
            vault_root=vault_root,
            vault_id=vault_id,
            source_path=parent_path,
            resolving=(*resolving, source_path),
            cache=cache,
        )
        for parent_path in parent_paths
    )
    resolved = _ResolvedWikiSource(
        source_hashes=tuple(
            dict.fromkeys(source_hash for parent in parents for source_hash in parent.source_hashes)
        ),
        source_entity_ids=tuple(
            dict.fromkeys(entity_id for parent in parents for entity_id in parent.source_entity_ids)
        ),
        fact_ids=tuple(
            dict.fromkeys(
                (*page_fact_ids, *(fact_id for parent in parents for fact_id in parent.fact_ids))
            )
        ),
        evidence_ids=tuple(
            dict.fromkeys(evidence_id for parent in parents for evidence_id in parent.evidence_ids)
        ),
    )
    cache[source_path] = resolved
    return resolved


def _source_entities_for_page(
    conn: sqlite3.Connection,
    page_entity_id: str,
    source_hash: str,
) -> tuple[str, ...]:
    params: list[object] = [page_entity_id]
    hash_clause = ""
    if not source_hash.startswith("page:"):
        hash_clause = "AND json_extract(source.metadata_json, '$.source_hash') = ?"
        params.append(source_hash)
    rows = conn.execute(
        f"""
        SELECT DISTINCT source.id
        FROM memory_graph_facts relation
        JOIN memory_entities source ON source.id = relation.subject_entity_id
        WHERE relation.statement_kind = 'relation'
          AND relation.relation_type = 'documented_in'
          AND relation.object_entity_id = ?
          AND relation.status = 'active'
          AND source.entity_type = 'source'
          AND source.status = 'active'
          {hash_clause}
        ORDER BY source.id
        """,
        tuple(params),
    ).fetchall()
    if not rows:
        raise WikiMemoryClosureError("synthesis_source_entity_missing")
    return tuple(str(row["id"]) for row in rows)


def _active_facts_for_page(
    conn: sqlite3.Connection,
    page_entity_id: str,
    *,
    vault_id: str,
) -> tuple[str, ...]:
    graph = MemoryEntityGraphStore(conn)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT relation.subject_fact_id
            FROM memory_graph_facts relation
            WHERE relation.statement_kind = 'relation'
              AND relation.relation_type = 'documented_in'
              AND relation.object_entity_id = ?
              AND relation.subject_fact_id IS NOT NULL
              AND relation.status = 'active'
            ORDER BY relation.subject_fact_id
            """,
            (page_entity_id,),
        ).fetchall()
        return tuple(
            fact_id
            for row in rows
            if (fact_id := str(row["subject_fact_id"]))
            and graph.statement_recallable(fact_id, vault_id=vault_id)
        )
    finally:
        graph.close()


def _evidence_ids_for_hash(conn: sqlite3.Connection, source_hash: str) -> tuple[str, ...]:
    if source_hash.startswith("page:"):
        return ()
    rows = conn.execute(
        """
        SELECT id
        FROM memory_evidence
        WHERE source_text_hash = ?
           OR json_extract(metadata_json, '$.source_hash') = ?
        ORDER BY created_at, id
        """,
        (source_hash, source_hash),
    ).fetchall()
    return tuple(str(row["id"]) for row in rows)


def _entity_ids_for_facts(
    conn: sqlite3.Connection,
    fact_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if not fact_ids:
        return ()
    placeholders = ", ".join("?" for _ in fact_ids)
    rows = conn.execute(
        f"""
        SELECT subject_entity_id, object_entity_id
        FROM memory_graph_facts
        WHERE id IN ({placeholders})
        ORDER BY id
        """,
        fact_ids,
    ).fetchall()
    return tuple(
        dict.fromkeys(
            str(entity_id)
            for row in rows
            for entity_id in (row["subject_entity_id"], row["object_entity_id"])
            if entity_id
        )
    )


def _validate_requested_ids(
    graph: MemoryEntityGraphStore,
    *,
    vault_id: str,
    requested_entity_ids: tuple[str, ...] | list[str],
    requested_fact_ids: tuple[str, ...] | list[str],
    requested_evidence_ids: tuple[str, ...] | list[str],
    allowed_entity_ids: tuple[str, ...] | list[str],
    allowed_fact_ids: tuple[str, ...] | list[str],
    allowed_evidence_ids: tuple[str, ...] | list[str],
) -> None:
    allowed_entities = set(allowed_entity_ids)
    allowed_facts = set(allowed_fact_ids)
    allowed_evidence = set(allowed_evidence_ids)
    for entity_id in dict.fromkeys(requested_entity_ids):
        if entity_id not in allowed_entities:
            raise WikiMemoryClosureError("synthesis_entity_not_grounded")
        entity = graph.get_entity(entity_id)
        if entity.status != "active":
            raise WikiMemoryClosureError("synthesis_entity_not_grounded")
    for fact_id in dict.fromkeys(requested_fact_ids):
        if fact_id not in allowed_facts or not graph.statement_recallable(fact_id, vault_id=vault_id):
            raise WikiMemoryClosureError("synthesis_fact_not_grounded")
    for evidence_id in dict.fromkeys(requested_evidence_ids):
        if evidence_id not in allowed_evidence:
            raise WikiMemoryClosureError("synthesis_evidence_not_grounded")


def _ensure_decision_entity_candidate(
    graph: MemoryEntityGraphStore,
    *,
    vault_id: str,
    target_path: str,
    title: str,
) -> MemoryEntity:
    entity_key = f"wiki-decision:{vault_id}:{target_path}"
    row = graph.conn.execute(
        "SELECT id FROM memory_entities WHERE entity_key = ?",
        (entity_key,),
    ).fetchone()
    if row is not None:
        entity = graph.get_entity(str(row["id"]))
        if entity.status not in {"active", "candidate"}:
            raise WikiMemoryClosureError("decision_entity_not_activatable")
        return entity
    return graph.create_entity(
        entity_type="decision",
        canonical_name=title,
        entity_key=entity_key,
        status="candidate",
        risk_tier="low",
        confidence=1.0,
        metadata={"vault_id": vault_id, "wiki_relative_path": target_path},
    )


def _frontmatter_list(frontmatter: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = frontmatter.get(key)
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _validate_extraction_source(*, provenance: str, source_type: str) -> None:
    if provenance == "explicit_user" and source_type.casefold().strip() not in EXPLICIT_USER_SOURCE_TYPES:
        raise WikiMemoryClosureError("explicit_user_source_type_required")


def _ensure_vault(conn: sqlite3.Connection, vault_root: str | Path) -> str:
    vault_id = VaultRepository(conn).upsert(vault_root, name=Path(vault_root).name or "Vault")
    conn.commit()
    return vault_id


def _ensure_source_entity(
    graph: MemoryEntityGraphStore,
    *,
    source_hash: str,
    source_id: str,
    source_title: str,
) -> MemoryEntity:
    entity_key = f"wiki-source:{source_hash}"
    row = graph.conn.execute(
        "SELECT id FROM memory_entities WHERE entity_key = ?",
        (entity_key,),
    ).fetchone()
    if row is not None:
        return graph.get_entity(str(row["id"]))
    return graph.create_entity(
        entity_type="source",
        canonical_name=source_title,
        entity_key=entity_key,
        status="candidate",
        risk_tier="low",
        confidence=1.0,
        metadata={
            "source_hash": source_hash,
            "source_id": source_id,
            "source_type": "wiki",
        },
    )


def _ensure_source_provenance_candidate(
    candidates: MemoryCandidateStore,
    graph: MemoryEntityGraphStore,
    *,
    source_hash: str,
    source_id: str,
    source_title: str,
    source_type: str,
    raw_content: str,
):
    candidate = candidates.create_candidate(
        MemoryCandidateCreate(
            memory_kind=MemoryKind.FACT,
            memory_scope=MemoryScope.TOPIC,
            summary="Wiki source provenance",
            normalized_value=source_hash,
            source_text=raw_content,
            source_track=SourceTrack.MODEL_EXTRACTED,
            risk_tier=RiskTier.LOW,
            confidence=1.0,
            metadata={
                "source_hash": source_hash,
                "source_id": source_id,
                "source_type": source_type,
                "source_title": source_title,
                "candidate_role": "wiki_source_provenance",
            },
        )
    )
    row = graph.conn.execute(
        "SELECT id FROM memory_evidence WHERE candidate_id = ? ORDER BY created_at, id LIMIT 1",
        (candidate.id,),
    ).fetchone()
    if row is None:
        raise WikiMemoryClosureError("source_evidence_missing")
    return candidate, str(row["id"])


def _bind_source_provenance_edges(
    graph: MemoryEntityGraphStore,
    resolved: ResolvedExtraction,
    *,
    source_entity: MemoryEntity,
    source_hash: str,
    raw_content: str,
    source_type: str,
) -> None:
    for entity in resolved.entities.values():
        relation = graph.create_relation(
            relation_type="derived_from",
            subject_entity_id=entity.id,
            object_entity_id=source_entity.id,
            source_text=raw_content,
            source_type=source_type,
            confidence=1.0,
            evidence_id=_entity_source_evidence_id(source_hash, entity.id),
        )
        if relation.status.value == "active":
            graph.update_status(relation.id, "candidate", reason="wiki_extraction_candidate")
    for fact_id in (*resolved.claim_ids.values(), *resolved.relation_ids):
        relation = graph.create_relation(
            relation_type="supports",
            subject_entity_id=source_entity.id,
            object_fact_id=fact_id,
            source_text=raw_content,
            source_type=source_type,
            confidence=1.0,
            evidence_id=_fact_source_evidence_id(source_hash, fact_id),
        )
        if relation.status.value == "active":
            graph.update_status(relation.id, "candidate", reason="wiki_extraction_candidate")


def _annotate_fact_provenance(
    graph: MemoryEntityGraphStore,
    fact_ids: tuple[str, ...] | list[str],
    *,
    source_hash: str,
    source_id: str,
    provenance: str,
) -> None:
    with graph.atomic():
        with graph._write_scope():
            conn = graph.conn
            for fact_id in dict.fromkeys(fact_ids):
                row = conn.execute(
                    "SELECT metadata_json FROM memory_graph_facts WHERE id = ?",
                    (fact_id,),
                ).fetchone()
                if row is None:
                    continue
                try:
                    metadata = json.loads(str(row["metadata_json"] or "{}"))
                except json.JSONDecodeError:
                    metadata = {}
                if not isinstance(metadata, dict):
                    metadata = {}
                metadata.update(
                    {
                        "source_hash": source_hash,
                        "source_id": source_id,
                        "wiki_extraction_provenance": provenance,
                    }
                )
                serialized = json.dumps(metadata, ensure_ascii=True, sort_keys=True)
                conn.execute(
                    "UPDATE memory_graph_facts SET metadata_json = ?, updated_at = ? WHERE id = ?",
                    (serialized, utc_now_iso(), fact_id),
                )
                conn.execute(
                    "UPDATE memory_evidence SET metadata_json = ? WHERE fact_id = ?",
                    (serialized, fact_id),
                )


def _ensure_wiki_page_entity(
    graph: MemoryEntityGraphStore,
    *,
    vault_id: str,
    relative_path: str,
    title: str,
) -> MemoryEntity:
    normalized_path = relative_path.replace("\\", "/")
    entity_key = f"wiki-page:{vault_id}:{normalized_path}"
    row = graph.conn.execute(
        "SELECT id FROM memory_entities WHERE entity_key = ?",
        (entity_key,),
    ).fetchone()
    if row is not None:
        return graph.get_entity(str(row["id"]))
    return graph.create_entity(
        entity_type="wiki_page",
        canonical_name=title,
        entity_key=entity_key,
        status="active",
        risk_tier="low",
        confidence=1.0,
        metadata={"vault_id": vault_id, "wiki_relative_path": relative_path},
    )


def _fact_evidence_ids(conn: sqlite3.Connection, fact_ids: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for fact_id in fact_ids:
        rows = conn.execute(
            "SELECT id FROM memory_evidence WHERE fact_id = ? ORDER BY created_at, id",
            (fact_id,),
        ).fetchall()
        result.extend(str(row["id"]) for row in rows)
    return tuple(dict.fromkeys(result))


def _fact_is_active_and_grounded(conn: sqlite3.Connection, fact_id: str, source_hash: str) -> bool:
    row = conn.execute(
        "SELECT status, metadata_json FROM memory_graph_facts WHERE id = ?",
        (fact_id,),
    ).fetchone()
    if row is None or str(row["status"] or "") != "active":
        return False
    try:
        metadata = json.loads(str(row["metadata_json"] or "{}"))
    except json.JSONDecodeError:
        metadata = {}
    if isinstance(metadata, dict) and str(metadata.get("source_hash") or "") == source_hash:
        return True
    return conn.execute(
        "SELECT 1 FROM memory_evidence WHERE fact_id = ? AND source_text_hash = ? LIMIT 1",
        (fact_id, source_hash),
    ).fetchone() is not None


def _read_source_content(conn: sqlite3.Connection, source_id: str) -> str:
    row = conn.execute("SELECT raw_content, content_preview FROM wiki_sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise WikiMemoryClosureError("source_not_found_before_finalize")
    return str(row["raw_content"] or row["content_preview"] or "")


def _frontmatter_revision(frontmatter: Mapping[str, object]) -> int:
    try:
        return max(1, int(str(frontmatter.get("revision") or "1")))
    except (TypeError, ValueError):
        return 1


def _safe_reason(exc: BaseException) -> str:
    return re.sub(r"[^a-zA-Z0-9_.:-]+", "_", str(exc))[:120] or exc.__class__.__name__


def _stable_id(prefix: str, *parts: str) -> str:
    payload = "\x1f".join(parts)
    return f"{prefix}-{sha256_hex(payload)[:40]}"


def _entity_source_evidence_id(source_hash: str, entity_id: str) -> str:
    return _stable_id("wiki-entity-source-evidence", source_hash, entity_id)


def _fact_source_evidence_id(source_hash: str, fact_id: str) -> str:
    return _stable_id("wiki-fact-source-evidence", source_hash, fact_id)


def _page_evidence_id(*, source_hash: str, relative_path: str) -> str:
    return _stable_id("wiki-page-evidence", source_hash, relative_path)


def _entity_page_evidence_id(source_hash: str, entity_id: str, relative_path: str) -> str:
    return _stable_id("wiki-entity-page-evidence", source_hash, entity_id, relative_path)


def _fact_page_evidence_id(source_hash: str, fact_id: str, relative_path: str) -> str:
    return _stable_id("wiki-fact-page-evidence", source_hash, fact_id, relative_path)
