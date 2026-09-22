from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import Protocol

from app.models.memory import MemorySearchResponse, MemorySearchResult
from app.models.memory import RetrievalContribution
from app.models.enums import MemoryFactStatus
from app.services.diary_memory import (
    DiaryMemorySearch,
    DiaryMemoryService,
    diary_records_to_search_results,
)
from app.services.memory_activation import (
    MemoryActivationContext,
    MemoryActivationService,
    activation_item_from_graph_fact,
    rank_activation_decisions,
)
from app.services.memory_graph import MemoryGraphFact, MemoryGraphStore
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_permissions import result_with_activation_permissions
from app.services.memory_taxonomy import graph_fact_content_category
from app.services.retrieval_fusion import (
    FusionCandidate,
    FUSION_POLICY_VERSION,
    reciprocal_rank_fusion,
)
from app.utils.hash import sha256_hex
from app.utils.public_references import public_memory_reference


@dataclass(frozen=True, slots=True)
class MemoryItemProvenance:
    source: str
    source_scope: str
    retrieval_mode: str
    channels: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryItem:
    """Common read model shared by every memory retrieval source."""

    id: str
    kind: str
    status: str
    score: float
    provenance: MemoryItemProvenance
    result: MemorySearchResult
    entity_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    citation_refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemorySourceRead:
    items: tuple[MemoryItem, ...]
    metadata: Mapping[str, object] = field(default_factory=dict)
    excluded_long_term_signatures: frozenset[tuple[str, str]] = frozenset()


class MemorySourceAdapter(Protocol):
    channel: str

    def supports(self, source_scope: str) -> bool: ...

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySourceRead: ...


class SearchResultMemorySourceAdapter:
    """Adapts an existing response into the unified source contract."""

    def __init__(
        self,
        channel: str,
        response: MemorySearchResponse,
        *,
        supported_scopes: Sequence[str] = ("all",),
    ) -> None:
        self.channel = channel
        self._response = response
        self._supported_scopes = frozenset(supported_scopes)

    def supports(self, source_scope: str) -> bool:
        return source_scope in self._supported_scopes

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySourceRead:
        del query, mode, source_scope
        return MemorySourceRead(
            items=tuple(
                memory_item_from_search_result(result, source=self.channel)
                for result in self._response.results[:top_k]
            ),
            metadata=self._response.metadata,
        )


class RetrievalMemorySourceAdapter:
    channel = "retrieval"

    def __init__(self, retrieval_service, *, vault_id: str) -> None:
        self._retrieval_service = retrieval_service
        self._vault_id = vault_id

    def supports(self, source_scope: str) -> bool:
        return source_scope != "diary_objects"

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySourceRead:
        response = self._retrieval_service.search(
            vault_id=self._vault_id,
            query=query,
            top_k=top_k,
            source_scope=source_scope,
            mode=mode,
        )
        return MemorySourceRead(
            items=tuple(memory_item_from_search_result(item, source=self.channel) for item in response.results),
            metadata=response.metadata,
        )


class DiaryMemorySourceAdapter:
    channel = "diary"

    def __init__(self, service_factory: Callable[[], DiaryMemoryService]) -> None:
        self._service_factory = service_factory

    def supports(self, source_scope: str) -> bool:
        return source_scope in {"all", "diary_objects"}

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySourceRead:
        del mode, source_scope
        service = self._service_factory()
        try:
            results = diary_records_to_search_results(
                service.search(DiaryMemorySearch(query=query, top_k=top_k))
            )
        finally:
            service.close()
        return MemorySourceRead(
            items=tuple(memory_item_from_search_result(item, source=self.channel) for item in results),
            metadata={"semantic_available": False, "retrieval_mode": "diary_object"},
        )


class GraphMemorySourceAdapter:
    channel = "graph"

    def __init__(
        self,
        store_factory: Callable[[], MemoryGraphStore | MemoryEntityGraphStore],
        *,
        answerable_only: bool = False,
        vault_id: str | None = None,
    ) -> None:
        self._store_factory = store_factory
        self._answerable_only = answerable_only
        self._vault_id = vault_id

    def supports(self, source_scope: str) -> bool:
        return source_scope in {"all", "personal_memory"}

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySourceRead:
        del mode, source_scope
        store = self._store_factory()
        references_by_fact_id = {}
        try:
            if self._answerable_only and isinstance(store, MemoryEntityGraphStore):
                facts = store.answerable_graph_facts(query=query, vault_id=self._vault_id, max_hops=2, limit=200)
            else:
                graph_store = store.graph if isinstance(store, MemoryEntityGraphStore) else store
                facts = graph_fact_candidates(graph_store, query=query, limit=200)
            if isinstance(store, MemoryEntityGraphStore):
                references_by_fact_id = {
                    fact.id: store.recall_references(fact.id, vault_id=self._vault_id)
                    for fact in facts
                }
            decisions = rank_activation_decisions(
                (
                    MemoryActivationService().score(
                        activation_item_from_graph_fact(fact),
                        MemoryActivationContext(
                            query=query,
                            route_scopes=("graph_facts", "personal_memory"),
                        ),
                    )
                    for fact in facts
                ),
                limit=top_k,
                require_answer_context=False,
            )
        finally:
            store.close()

        facts_by_id = {fact.id: fact for fact in facts}
        items: list[MemoryItem] = []
        for decision in decisions:
            fact = facts_by_id.get(decision.item.memory_id)
            if fact is None:
                continue
            references = references_by_fact_id.get(fact.id)
            source_refs = references.source_refs if references is not None else ()
            relative_path = source_refs[0] if source_refs else ""
            entity_refs = [
                public_memory_reference("entity", entity_id)
                for entity_id in (references.entity_ids if references is not None else ())
            ]
            evidence_refs = [
                public_memory_reference("evidence", evidence_id)
                for evidence_id in (references.evidence_ids if references is not None else ())
            ]
            citation_refs = (
                [public_memory_reference("citation", source_ref) for source_ref in source_refs]
                if source_refs
                else list(evidence_refs)
            )
            result = result_with_activation_permissions(
                MemorySearchResult(
                    note_id=fact.id,
                    chunk_id=fact.id,
                    relative_path=relative_path,
                    title=_graph_result_title(relative_path),
                    heading=fact.subject,
                    snippet=graph_result_snippet(fact),
                    score=decision.activation_score,
                    source_scope="personal_memory",
                    retrieval_mode="graph_activation",
                    retrieval_channels=[self.channel],
                    entity_refs=entity_refs,
                    evidence_refs=evidence_refs,
                    citation_refs=citation_refs,
                ),
                decision,
                query=query,
                fact_id=fact.id,
                # metadata 优先,沉默时才由 relation_type 无歧义重建 —— 旧库里
                # 修复前落库的偏好关系边 metadata 恒为 "{}",只认 metadata 会让它们永远失明。
                content_category=graph_fact_content_category(fact),
                # 来源性质是两轴的另一个输入:偏好类用户陈述在此记的是 explicit_user,
                # 消费点据此把权威判为 user;缺了它,权威轴只剩范畴、无法区分谁说的。
                source_type=fact.source_type,
            )
            items.append(memory_item_from_search_result(result, source=self.channel))

        return MemorySourceRead(
            items=tuple(items),
            excluded_long_term_signatures=inactive_long_term_signatures(facts),
        )


class UnifiedMemorySearchService:
    """Runs registered sources and fuses their common read models with RRF."""

    def __init__(self, adapters: Sequence[MemorySourceAdapter]) -> None:
        self._adapters = tuple(adapters)

    def search(
        self,
        *,
        query: str,
        top_k: int,
        mode: str,
        source_scope: str,
    ) -> MemorySearchResponse:
        reads: list[tuple[MemorySourceAdapter, MemorySourceRead]] = []
        metadata: dict[str, object] = {}
        for adapter in self._adapters:
            if not adapter.supports(source_scope):
                continue
            source_read = adapter.search(
                query=query,
                top_k=top_k,
                mode=mode,
                source_scope=source_scope,
            )
            reads.append((adapter, source_read))
            metadata.update(source_read.metadata)

        excluded_signatures = frozenset(
            signature
            for _, source_read in reads
            for signature in source_read.excluded_long_term_signatures
        )
        channels: dict[str, list[FusionCandidate]] = {}
        approved_scopes: list[str] = []
        for priority, (adapter, source_read) in enumerate(reads):
            channel_items: list[FusionCandidate] = []
            for item in source_read.items:
                if adapter.channel == "retrieval" and matches_inactive_long_term_fact(
                    item.result, excluded_signatures
                ):
                    continue
                if item.provenance.source_scope not in approved_scopes:
                    approved_scopes.append(item.provenance.source_scope)
                channel_items.append(
                    FusionCandidate(
                        stable_id=item.id,
                        content_hash=item.result.content_hash or memory_item_content_hash(item),
                        source_scope=item.provenance.source_scope,
                        payload=item,
                        stable_order_key=f"{priority:02d}:{item.id}",
                        lifecycle_status=normalized_fusion_status(item.status),
                    )
                )
            channels[adapter.channel] = channel_items

        if not approved_scopes:
            return MemorySearchResponse(
                results=[],
                metadata={
                    **metadata,
                    "memory_fusion": {
                        "algorithm": "reciprocal_rank_fusion",
                        "policy_version": FUSION_POLICY_VERSION,
                        "input_counts": {channel: 0 for channel in channels},
                        "fused_count": 0,
                    },
                },
            )

        fusion = reciprocal_rank_fusion(
            channels,
            approved_scopes=approved_scopes,
            top_k=top_k,
        )
        results = [fused_memory_search_result(candidate) for candidate in fusion.candidates]
        return MemorySearchResponse(
            results=results,
            metadata={
                **metadata,
                "memory_fusion": {
                    "algorithm": "reciprocal_rank_fusion",
                    "policy_version": FUSION_POLICY_VERSION,
                    "input_counts": fusion.diagnostics.input_counts,
                    "eligible_counts": fusion.diagnostics.eligible_counts,
                    "filtered_count": fusion.diagnostics.filtered_count,
                    "fused_count": fusion.diagnostics.fused_count,
                },
            },
        )


def memory_item_from_search_result(result: MemorySearchResult, *, source: str) -> MemoryItem:
    stable_id = result.fact_id or result.candidate_id or f"{result.note_id}:{result.chunk_id}"
    channels = tuple(dict.fromkeys((*result.retrieval_channels, source)))
    item = MemoryItem(
        id=stable_id,
        kind=result.memory_kind or infer_memory_kind(result),
        status=result.lifecycle_status or "active",
        score=float(result.score),
        provenance=MemoryItemProvenance(
            source=source,
            source_scope=result.source_scope,
            retrieval_mode=result.retrieval_mode,
            channels=channels,
        ),
        result=result,
    )
    return replace(
        item,
        entity_refs=tuple(result.entity_refs),
        evidence_refs=tuple(result.evidence_refs),
        citation_refs=tuple(result.citation_refs),
    )


def fused_memory_search_result(candidate) -> MemorySearchResult:
    item: MemoryItem = candidate.payload
    result = item.result
    outer_channels = [contribution.channel for contribution in candidate.contributions]
    channels = list(dict.fromkeys([*result.retrieval_channels, *outer_channels]))
    ranks = {**result.channel_ranks, **candidate.channel_ranks}
    contributions = [
        *result.retrieval_contributions,
        *[
            RetrievalContribution(
                channel=contribution.channel,
                rank=contribution.rank,
                rrf_component=contribution.component,
            )
            for contribution in candidate.contributions
        ],
    ]
    return result.model_copy(
        update={
            "score": candidate.score,
            "retrieval_channels": channels,
            "channel_ranks": ranks,
            "retrieval_contributions": contributions,
            "score_breakdown": {
                **result.score_breakdown,
                "source_score": item.score,
                "memory_fusion_rrf": candidate.score,
            },
        }
    )


def graph_fact_candidates(store: MemoryGraphStore, *, query: str, limit: int) -> list[MemoryGraphFact]:
    candidate_limit = max(1, min(limit, 200))
    facts = dedupe_graph_facts(store.list_facts(query=query.strip() or None, limit=candidate_limit))
    for term in significant_terms(query):
        if len(facts) >= candidate_limit:
            break
        facts = dedupe_graph_facts((*facts, *store.list_facts(query=term, limit=candidate_limit)))
    return facts[:candidate_limit]


def inactive_long_term_signatures(facts: Sequence[MemoryGraphFact]) -> frozenset[tuple[str, str]]:
    inactive_statuses = {
        MemoryFactStatus.ARCHIVED,
        MemoryFactStatus.FORGOTTEN,
        MemoryFactStatus.REJECTED,
        MemoryFactStatus.SUPERSEDED,
        MemoryFactStatus.WRONG,
        MemoryFactStatus.SENSITIVE_BLOCKED,
    }
    return frozenset(
        (fact.subject.casefold(), fact.object.casefold())
        for fact in facts
        if fact.status in inactive_statuses
    )


def matches_inactive_long_term_fact(
    result: MemorySearchResult,
    signatures: frozenset[tuple[str, str]],
) -> bool:
    if not signatures or not result.relative_path.replace("\\", "/").startswith("Memories/LongTerm/"):
        return False
    haystack = " ".join([result.title, result.heading or "", result.snippet]).casefold()
    return any(subject in haystack and object_value in haystack for subject, object_value in signatures)


def graph_result_snippet(fact: MemoryGraphFact) -> str:
    status_part = "" if fact.status is MemoryFactStatus.ACTIVE else f" (status={fact.status.value})"
    return f"{fact.subject} {fact.predicate} {fact.object}{status_part}"


def _graph_result_title(relative_path: str) -> str:
    return PurePosixPath(relative_path).stem if relative_path else "Structured memory"


def significant_terms(query: str) -> tuple[str, ...]:
    stop_words = {"about", "does", "what", "when", "where", "which"}
    terms = []
    for raw in query.replace("?", " ").replace(",", " ").split():
        term = raw.strip().casefold()
        if len(term) >= 3 and term not in stop_words:
            terms.append(term)
    return tuple(dict.fromkeys(terms))


def dedupe_graph_facts(facts: Sequence[MemoryGraphFact]) -> list[MemoryGraphFact]:
    seen: set[str] = set()
    deduped: list[MemoryGraphFact] = []
    for fact in facts:
        if fact.id not in seen:
            seen.add(fact.id)
            deduped.append(fact)
    return deduped


def infer_memory_kind(result: MemorySearchResult) -> str:
    if result.source_scope == "diary_objects":
        return "diary"
    if result.fact_id:
        return "fact"
    if result.candidate_id:
        return "candidate"
    return "note"


def normalized_fusion_status(status: str) -> str:
    return "active" if status in {"", "indexed", "ready"} else status


def memory_item_content_hash(item: MemoryItem) -> str:
    result = item.result
    return sha256_hex(
        "\n".join(
            (
                item.id,
                item.kind,
                result.relative_path,
                result.heading or "",
                result.snippet,
            )
        )
    )
