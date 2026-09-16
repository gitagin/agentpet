from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import fsum, isfinite


RRF_K = 60
MAX_CANDIDATES_PER_CHANNEL = 40
FUSION_POLICY_VERSION = "retrieval-fusion.v1"

_PRESENTATION_CHANNEL_ORDER = (
    "vector",
    "fts",
    "active_memory",
    "diary",
    "daily_chat",
    "graph",
)
_ACTIVE_LIFECYCLE_STATUSES = frozenset({"active", "indexed", "ready"})


@dataclass(frozen=True, slots=True)
class FusionCandidate:
    stable_id: str
    content_hash: str
    source_scope: str
    payload: object
    stable_order_key: str = ""
    permission_allowed: bool = True
    lifecycle_status: str = "active"
    metadata_filter_passed: bool = True
    vault_id: str | None = None
    generation_valid: bool = True


@dataclass(frozen=True, slots=True)
class FusionContribution:
    channel: str
    rank: int
    component: float


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    stable_id: str
    content_hash: str
    source_scope: str
    payload: object
    score: float
    best_rank: int
    contributions: tuple[FusionContribution, ...]
    stable_order_key: str = ""

    @property
    def channels(self) -> tuple[str, ...]:
        return tuple(contribution.channel for contribution in self.contributions)

    @property
    def channel_ranks(self) -> dict[str, int]:
        return {contribution.channel: contribution.rank for contribution in self.contributions}

    @property
    def score_components(self) -> dict[str, float]:
        return {contribution.channel: contribution.component for contribution in self.contributions}


@dataclass(frozen=True, slots=True)
class FusionDiagnostics:
    input_counts: dict[str, int]
    eligible_counts: dict[str, int]
    filtered_count: int
    within_channel_duplicate_count: int
    conflicting_identity_count: int
    fused_count: int


@dataclass(frozen=True, slots=True)
class FusionResult:
    candidates: tuple[FusedCandidate, ...]
    diagnostics: FusionDiagnostics


def reciprocal_rank_fusion(
    channels: Mapping[str, Sequence[FusionCandidate]],
    *,
    approved_scopes: Sequence[str],
    top_k: int,
    required_vault_id: str | None = None,
    rrf_k: int = RRF_K,
    channel_weights: Mapping[str, float] | None = None,
    scope_weights: Mapping[str, float] | None = None,
) -> FusionResult:
    """Fuse ranked channels; optional per-channel weights scale contributions.

    Weighted RRF (Qdrant v1.17+): contribution = weight / (rrf_k + rank).
    Weights must be finite and positive; channels without a weight keep 1.0.
    Per-channel rank is unaffected, so primary_channel stays weight-free.

    scope_weights additionally scales the FINAL fused score by the presented
    candidate's source scope (e.g. downweighting chat-log echoes when knowledge
    candidates compete). Contributions stay the raw weighted-RRF components,
    so diagnostics remain interpretable.
    """
    if not 1 <= top_k <= MAX_CANDIDATES_PER_CHANNEL:
        raise ValueError("top_k must be between 1 and 40")
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    weights: dict[str, float] = {}
    if channel_weights is not None:
        for channel, weight in channel_weights.items():
            if not isfinite(weight) or weight <= 0:
                raise ValueError("channel weights must be finite and positive")
            weights[str(channel)] = float(weight)
    scope_scale: dict[str, float] = {}
    if scope_weights is not None:
        for scope, weight in scope_weights.items():
            if not isfinite(weight) or weight <= 0:
                raise ValueError("scope weights must be finite and positive")
            scope_scale[str(scope)] = float(weight)

    ordered_scopes = _ordered_scopes(approved_scopes)
    allowed_scopes = set(ordered_scopes)
    scope_positions = {scope: index for index, scope in enumerate(ordered_scopes)}
    input_counts: dict[str, int] = {}
    eligible_counts: dict[str, int] = {}
    eligible_by_channel: dict[str, list[tuple[str, FusionCandidate]]] = {}
    identity_hashes: dict[str, set[str]] = {}
    conflicting_identities: set[str] = set()
    filtered_count = 0
    duplicate_count = 0

    for channel in sorted(channels):
        raw_candidates = tuple(channels[channel])[:MAX_CANDIDATES_PER_CHANNEL]
        input_counts[channel] = len(raw_candidates)
        seen_in_channel: dict[str, str] = {}
        channel_conflicts: set[str] = set()
        channel_candidates: list[tuple[str, FusionCandidate]] = []
        for candidate in raw_candidates:
            stable_id = candidate.stable_id.strip()
            if not _candidate_is_eligible(
                candidate,
                allowed_scopes=allowed_scopes,
                required_vault_id=required_vault_id,
            ):
                filtered_count += 1
                continue
            if stable_id in channel_conflicts:
                continue
            previous_hash = seen_in_channel.get(stable_id)
            if previous_hash is not None:
                if previous_hash == candidate.content_hash:
                    duplicate_count += 1
                else:
                    channel_conflicts.add(stable_id)
                    conflicting_identities.add(stable_id)
                continue
            seen_in_channel[stable_id] = candidate.content_hash
            channel_candidates.append((stable_id, candidate))
        eligible_by_channel[channel] = channel_candidates
        for stable_id, candidate in channel_candidates:
            identity_hashes.setdefault(stable_id, set()).add(candidate.content_hash)

    conflicting_identities.update(
        stable_id for stable_id, hashes in identity_hashes.items() if len(hashes) != 1
    )
    ranked_by_identity: dict[str, list[tuple[str, int, FusionCandidate]]] = {}
    for channel, channel_candidates in eligible_by_channel.items():
        rank = 0
        for stable_id, candidate in channel_candidates:
            if stable_id in conflicting_identities:
                continue
            rank += 1
            ranked_by_identity.setdefault(stable_id, []).append((channel, rank, candidate))
        eligible_counts[channel] = rank

    fused: list[FusedCandidate] = []
    for stable_id, ranked_candidates in ranked_by_identity.items():
        presentation_channel, _, presentation_candidate = min(
            ranked_candidates,
            key=lambda item: (
                item[1],
                _presentation_channel_position(item[0]),
                item[0],
            ),
        )
        del presentation_channel
        contributions = tuple(
            FusionContribution(
                channel=channel,
                rank=rank,
                component=weights.get(channel, 1.0) / (rrf_k + rank),
            )
            for channel, rank, _ in sorted(ranked_candidates, key=lambda item: item[0])
        )
        fused.append(
            FusedCandidate(
                stable_id=stable_id,
                content_hash=presentation_candidate.content_hash,
                source_scope=presentation_candidate.source_scope,
                payload=presentation_candidate.payload,
                score=fsum(contribution.component for contribution in contributions)
                * scope_scale.get(presentation_candidate.source_scope, 1.0),
                best_rank=min(contribution.rank for contribution in contributions),
                contributions=contributions,
                stable_order_key=(
                    presentation_candidate.stable_order_key or presentation_candidate.stable_id
                ),
            )
        )

    fused.sort(
        key=lambda candidate: (
            -candidate.score,
            scope_positions[candidate.source_scope],
            candidate.best_rank,
            candidate.stable_order_key,
            candidate.stable_id,
        )
    )
    diagnostics = FusionDiagnostics(
        input_counts=input_counts,
        eligible_counts=eligible_counts,
        filtered_count=filtered_count,
        within_channel_duplicate_count=duplicate_count,
        conflicting_identity_count=len(conflicting_identities),
        fused_count=len(fused),
    )
    return FusionResult(candidates=tuple(fused[:top_k]), diagnostics=diagnostics)


def primary_channel(candidate: FusedCandidate) -> str:
    contribution = min(
        candidate.contributions,
        key=lambda item: (
            item.rank,
            _presentation_channel_position(item.channel),
            item.channel,
        ),
    )
    return contribution.channel


def _candidate_is_eligible(
    candidate: FusionCandidate,
    *,
    allowed_scopes: set[str],
    required_vault_id: str | None,
) -> bool:
    if not candidate.stable_id.strip() or not candidate.content_hash.strip():
        return False
    if not candidate.permission_allowed or not candidate.metadata_filter_passed:
        return False
    if candidate.lifecycle_status not in _ACTIVE_LIFECYCLE_STATUSES:
        return False
    if not candidate.generation_valid:
        return False
    if candidate.source_scope not in allowed_scopes:
        return False
    if required_vault_id is not None and candidate.vault_id != required_vault_id:
        return False
    return True


def _ordered_scopes(approved_scopes: Sequence[str]) -> tuple[str, ...]:
    ordered: list[str] = []
    for scope in approved_scopes:
        normalized = str(scope).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def _presentation_channel_position(channel: str) -> int:
    try:
        return _PRESENTATION_CHANNEL_ORDER.index(channel)
    except ValueError:
        return len(_PRESENTATION_CHANNEL_ORDER)
