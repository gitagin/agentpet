from __future__ import annotations

from collections.abc import Sequence
from math import fsum

from pydantic import ValidationError

from ..contracts import (
    AgentResultEnvelope,
    EvidenceEnvelope,
    EvidenceMergeResult,
    ParallelEvidenceCandidate,
    RetrievalProvenance,
)


RRF_K = 60
MAX_MERGED_EVIDENCE = 5
_ACTIVE_LIFECYCLES = frozenset({"active", "indexed", "historical_approved"})


def merge_parallel_evidence(
    results: Sequence[AgentResultEnvelope],
    *,
    approved_scopes: Sequence[str],
    top_k: int = MAX_MERGED_EVIDENCE,
) -> EvidenceMergeResult:
    if not 1 <= top_k <= MAX_MERGED_EVIDENCE:
        raise ValueError("parallel evidence top_k must be between 1 and 5")
    ordered_scopes = tuple(dict.fromkeys(scope.strip() for scope in approved_scopes if scope.strip()))
    scope_positions = {scope: index for index, scope in enumerate(ordered_scopes)}
    accepted_scopes = set(ordered_scopes)
    candidates: list[ParallelEvidenceCandidate] = []
    input_count = 0
    filtered_count = 0

    for result in results:
        raw_candidates = result.output.get("evidence_candidates", ())
        if not isinstance(raw_candidates, list | tuple):
            filtered_count += 1
            continue
        for raw in raw_candidates:
            input_count += 1
            try:
                candidate = ParallelEvidenceCandidate.model_validate(raw)
            except ValidationError:
                filtered_count += 1
                continue
            if not _candidate_is_eligible(candidate, accepted_scopes=accepted_scopes):
                filtered_count += 1
                continue
            candidates.append(candidate)

    hashes_by_id: dict[str, set[str]] = {}
    for candidate in candidates:
        hashes_by_id.setdefault(candidate.stable_id, set()).add(candidate.content_hash)
    conflicting_ids = {
        stable_id for stable_id, content_hashes in hashes_by_id.items() if len(content_hashes) != 1
    }
    conflicting_candidate_count = sum(
        candidate.stable_id in conflicting_ids for candidate in candidates
    )

    grouped: dict[str, list[ParallelEvidenceCandidate]] = {}
    for candidate in candidates:
        if candidate.stable_id in conflicting_ids:
            continue
        grouped.setdefault(candidate.stable_id, []).append(candidate)

    ranked: list[tuple[float, int, int, str, EvidenceEnvelope]] = []
    for stable_id, identity_candidates in grouped.items():
        presentation = min(
            identity_candidates,
            key=lambda candidate: (
                scope_positions[candidate.source_scope],
                _best_rank(candidate.evidence),
                candidate.evidence.source,
                candidate.evidence.chunk_id,
            ),
        )
        best_ranks_by_channel: dict[str, int] = {}
        for candidate in identity_candidates:
            for contribution in candidate.evidence.retrieval_provenance:
                current = best_ranks_by_channel.get(contribution.channel)
                if current is None or contribution.rank < current:
                    best_ranks_by_channel[contribution.channel] = contribution.rank
        provenance = tuple(
            RetrievalProvenance(
                channel=channel,
                rank=rank,
                score_component=1.0 / (RRF_K + rank),
            )
            for channel, rank in sorted(best_ranks_by_channel.items())
        )
        merged = presentation.evidence.model_copy(update={"retrieval_provenance": provenance})
        ranked.append(
            (
                fsum(item.score_component for item in provenance),
                scope_positions[presentation.source_scope],
                min(item.rank for item in provenance),
                stable_id,
                merged,
            )
        )

    ranked.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))
    return EvidenceMergeResult(
        accepted=tuple(item[4] for item in ranked[:top_k]),
        input_count=input_count,
        filtered_count=filtered_count + conflicting_candidate_count,
        conflicting_identity_count=len(conflicting_ids),
    )


def _candidate_is_eligible(
    candidate: ParallelEvidenceCandidate,
    *,
    accepted_scopes: set[str],
) -> bool:
    return bool(
        candidate.permission_allowed
        and candidate.source_scope in accepted_scopes
        and candidate.evidence.lifecycle_status in _ACTIVE_LIFECYCLES
        and candidate.stable_id == candidate.evidence.citation_id
        and candidate.evidence.retrieval_provenance
    )


def _best_rank(evidence: EvidenceEnvelope) -> int:
    return min(item.rank for item in evidence.retrieval_provenance)
