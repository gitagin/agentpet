from __future__ import annotations

from collections import OrderedDict
from dataclasses import replace
from math import isclose
from datetime import datetime, timezone

import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from app.agents.retrieval.scoping import _force_search_memory_source_scope
from app.agents.tools import AgentToolSet, SearchMemoryInput
from app.services.retrieval_fusion import (
    MAX_CANDIDATES_PER_CHANNEL,
    RRF_K,
    FusionCandidate,
    reciprocal_rank_fusion,
)
from app.models.enums import MemoryFactStatus
from app.models.api import MemoryRecallPermissions, MemorySearchRequest, MemorySearchResult
from app.agents.nodes.retrieval import (
    _fuse_structured_memory_results,
    _select_fused_memory_context,
)
from app.services.diary_memory import DiaryMemoryObjectRecord, diary_records_to_search_results
from app.services.retrieval import InvalidRetrievalSourceScopeError, RetrievalService
from app.storage.database import Database
from tests.test_retrieval_hybrid import StubVectorIndex, _authoritative_candidate, _indexed_service


def _candidate(
    stable_id: str,
    *,
    content_hash: str | None = None,
    source_scope: str = "vault_note",
    raw_score: float = 0.0,
    **changes,
) -> FusionCandidate:
    vault_id = changes.pop("vault_id", "vault-1")
    return FusionCandidate(
        stable_id=stable_id,
        content_hash=content_hash or f"hash-{stable_id}",
        source_scope=source_scope,
        payload={"stable_id": stable_id, "raw_score": raw_score},
        vault_id=vault_id,
        **changes,
    )


def test_rrf_uses_only_channel_ranks_and_records_contributions() -> None:
    channels = {
        "fts": [
            _candidate("shared", raw_score=10_000.0),
            _candidate("fts-only", raw_score=9_999.0),
        ],
        "vector": [
            _candidate("vector-only", raw_score=-100.0),
            _candidate("shared", raw_score=-200.0),
        ],
    }

    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=("vault_note",),
        top_k=10,
        required_vault_id="vault-1",
    )

    assert [candidate.stable_id for candidate in result.candidates] == [
        "shared",
        "vector-only",
        "fts-only",
    ]
    shared = result.candidates[0]
    assert shared.channel_ranks == {"fts": 1, "vector": 2}
    assert isclose(shared.score, (1 / (RRF_K + 1)) + (1 / (RRF_K + 2)))
    assert shared.score_components == {
        "fts": 1 / (RRF_K + 1),
        "vector": 1 / (RRF_K + 2),
    }

    raw_scores_changed = {
        channel: [replace(candidate, payload={"raw_score": index * -1_000_000.0}) for index, candidate in enumerate(items)]
        for channel, items in channels.items()
    }
    changed = reciprocal_rank_fusion(
        raw_scores_changed,
        approved_scopes=("vault_note",),
        top_k=10,
        required_vault_id="vault-1",
    )
    assert [candidate.stable_id for candidate in changed.candidates] == [
        candidate.stable_id for candidate in result.candidates
    ]
    assert [candidate.score for candidate in changed.candidates] == [
        candidate.score for candidate in result.candidates
    ]


def test_rrf_is_independent_of_branch_completion_order() -> None:
    fts = [_candidate("b"), _candidate("a"), _candidate("c")]
    vector = [_candidate("a"), _candidate("c"), _candidate("b")]
    forward = reciprocal_rank_fusion(
        OrderedDict((("fts", fts), ("vector", vector))),
        approved_scopes=("vault_note",),
        top_k=10,
    )
    reversed_completion = reciprocal_rank_fusion(
        OrderedDict((("vector", vector), ("fts", fts))),
        approved_scopes=("vault_note",),
        top_k=10,
    )

    assert forward == reversed_completion


def test_rrf_tie_breaks_by_scope_then_best_rank_then_stable_id() -> None:
    channels = {
        "active_memory": [_candidate("memory-b", source_scope="personal_memory")],
        "fts": [_candidate("wiki-z", source_scope="wiki")],
        "vector": [_candidate("memory-a", source_scope="personal_memory")],
    }

    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=("personal_memory", "wiki"),
        top_k=10,
    )

    assert [candidate.stable_id for candidate in result.candidates] == [
        "memory-a",
        "memory-b",
        "wiki-z",
    ]


def test_rrf_tie_break_uses_stable_source_order_across_runtime_id_rebuilds() -> None:
    def run(logical_a_id: str, logical_b_id: str):
        logical_a = _candidate(
            logical_a_id,
            content_hash="hash-logical-a",
            stable_order_key="Vault/A.md\0hash-logical-a",
        )
        logical_b = _candidate(
            logical_b_id,
            content_hash="hash-logical-b",
            stable_order_key="Vault/B.md\0hash-logical-b",
        )
        return reciprocal_rank_fusion(
            {
                "fts": [logical_a, logical_b],
                "vector": [logical_b, logical_a],
            },
            approved_scopes=("vault_note",),
            top_k=10,
        )

    first = run("runtime-z", "runtime-a")
    rebuilt = run("runtime-a", "runtime-z")

    assert [candidate.stable_order_key for candidate in first.candidates] == [
        "Vault/A.md\0hash-logical-a",
        "Vault/B.md\0hash-logical-b",
    ]
    assert [candidate.stable_order_key for candidate in rebuilt.candidates] == [
        candidate.stable_order_key for candidate in first.candidates
    ]


@pytest.mark.asyncio
async def test_retrieval_agent_scope_wrapper_forces_proven_fts_mode() -> None:
    calls: list[dict[str, object]] = []

    async def search_memory(
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> dict[str, object]:
        calls.append(
            {
                "query": query,
                "top_k": top_k,
                "mode": mode,
                "source_scope": source_scope,
            }
        )
        return {"results": [], "metadata": {}}

    tool = StructuredTool.from_function(
        coroutine=search_memory,
        name="search_memory",
        description="Test-only memory search.",
        args_schema=SearchMemoryInput,
    )
    wrapped = _force_search_memory_source_scope(
        [tool],
        "Use search_memory with source_scope='personal_memory'.",
    )

    await wrapped[0].ainvoke(
        {
            "query": "remembered preference",
            "top_k": 7,
            "source_scope": "all",
        }
    )

    assert calls == [
        {
            "query": "remembered preference",
            "top_k": 7,
            "mode": "fts",
            "source_scope": "personal_memory",
        }
    ]


@pytest.mark.asyncio
async def test_retrieval_agent_scope_wrapper_forces_route_result_budget() -> None:
    calls: list[dict[str, object]] = []

    async def search_memory(
        query: str,
        top_k: int = 5,
        mode: str = "fts",
        source_scope: str = "all",
    ) -> dict[str, object]:
        calls.append(
            {
                "query": query,
                "top_k": top_k,
                "mode": mode,
                "source_scope": source_scope,
            }
        )
        return {"results": [], "metadata": {}}

    tool = StructuredTool.from_function(
        coroutine=search_memory,
        name="search_memory",
        description="Test-only memory search.",
        args_schema=SearchMemoryInput,
    )
    wrapped = _force_search_memory_source_scope(
        [tool],
        "Use search_memory with source_scope='daily_chat'.",
        forced_top_k=20,
    )

    await wrapped[0].ainvoke(
        {
            "query": "yesterday",
            "top_k": 5,
            "source_scope": "all",
        }
    )

    assert calls == [
        {
            "query": "yesterday",
            "top_k": 20,
            "mode": "fts",
            "source_scope": "daily_chat",
        }
    ]


@pytest.mark.asyncio
async def test_agent_tool_forces_fts_and_does_not_retry_internal_type_error() -> None:
    class BrokenScopedRetrieval:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def search(
            self,
            query: str,
            top_k: int = 5,
            mode: str = "fts",
            source_scope: str = "all",
        ) -> None:
            self.calls.append(
                {
                    "query": query,
                    "top_k": top_k,
                    "mode": mode,
                    "source_scope": source_scope,
                }
            )
            raise TypeError("internal retrieval bug")

    retrieval = BrokenScopedRetrieval()
    toolset = AgentToolSet(retrieval=retrieval)

    with pytest.raises(TypeError, match="internal retrieval bug"):
        await toolset.search_memory(
            "remembered preference",
            top_k=7,
            source_scope="personal_memory",
        )

    assert retrieval.calls == [
        {
            "query": "remembered preference",
            "top_k": 7,
            "mode": "fts",
            "source_scope": "personal_memory",
        }
    ]


def test_search_memory_tool_schema_rejects_retrieval_mode() -> None:
    with pytest.raises(ValueError):
        SearchMemoryInput.model_validate(
            {
                "query": "remembered preference",
                "mode": "hybrid",
            }
        )


def test_hard_filters_run_before_fusion_and_conflicting_identity_fails_closed() -> None:
    allowed = _candidate("allowed")
    channels = {
        "fts": [
            allowed,
            _candidate("permission", permission_allowed=False),
            _candidate("lifecycle", lifecycle_status="inactive"),
            _candidate("metadata", metadata_filter_passed=False),
            _candidate("generation", generation_valid=False),
            _candidate("foreign", vault_id="vault-2"),
            _candidate("scope", source_scope="graph"),
            _candidate("conflict", content_hash="hash-a"),
        ],
        "vector": [
            _candidate("conflict", content_hash="hash-b"),
            allowed,
        ],
    }

    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=("vault_note",),
        top_k=10,
        required_vault_id="vault-1",
    )

    assert [candidate.stable_id for candidate in result.candidates] == ["allowed"]
    assert result.diagnostics.filtered_count == 6
    assert result.diagnostics.conflicting_identity_count == 1
    assert result.candidates[0].channels == ("fts", "vector")


def test_same_channel_conflicting_hash_fails_closed_before_rank_assignment() -> None:
    hash_a = _candidate("conflict", content_hash="hash-a")
    hash_b = _candidate("conflict", content_hash="hash-b")
    visible = _candidate("visible")

    forward = reciprocal_rank_fusion(
        {"fts": [hash_a, hash_b, visible]},
        approved_scopes=("vault_note",),
        top_k=10,
    )
    reversed_conflict = reciprocal_rank_fusion(
        {"fts": [hash_b, hash_a, visible]},
        approved_scopes=("vault_note",),
        top_k=10,
    )

    for result in (forward, reversed_conflict):
        assert [candidate.stable_id for candidate in result.candidates] == ["visible"]
        assert result.candidates[0].channel_ranks == {"fts": 1}
        assert result.diagnostics.conflicting_identity_count == 1
        assert result.diagnostics.within_channel_duplicate_count == 0


def test_empty_approved_scopes_fail_closed() -> None:
    result = reciprocal_rank_fusion(
        {"fts": [_candidate("personal", source_scope="personal_memory")]},
        approved_scopes=(),
        top_k=10,
    )

    assert result.candidates == ()
    assert result.diagnostics.filtered_count == 1
    assert result.diagnostics.eligible_counts == {"fts": 0}


def test_invalid_source_scope_is_rejected_in_model_and_service(tmp_path) -> None:
    with pytest.raises(ValidationError):
        MemorySearchRequest(query="scope", source_scope="personal_memroy")

    service, vault_id = _indexed_service(tmp_path)
    with pytest.raises(InvalidRetrievalSourceScopeError):
        service.search(
            vault_id=vault_id,
            query="exact-token",
            source_scope="personal_memroy",
            mode="fts",
        )


def test_filtered_and_duplicate_candidates_do_not_consume_visible_rrf_ranks() -> None:
    visible = _candidate("visible")
    channels = {
        "fts": [
            _candidate("blocked", permission_allowed=False),
            _candidate("duplicate", lifecycle_status="inactive"),
            _candidate("duplicate"),
            visible,
        ]
    }

    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=("vault_note",),
        top_k=10,
    )

    assert [candidate.stable_id for candidate in result.candidates] == ["duplicate", "visible"]
    assert result.candidates[0].channel_ranks == {"fts": 1}
    assert result.candidates[1].channel_ranks == {"fts": 2}


def test_channel_and_cross_channel_dedup_preserve_distinct_authoritative_ids() -> None:
    same_content_hash = "shared-content-hash"
    duplicate = _candidate("id-a", content_hash=same_content_hash)
    channels = {
        "fts": [duplicate, duplicate, _candidate("id-b", content_hash=same_content_hash)],
        "vector": [duplicate],
    }

    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=("vault_note",),
        top_k=10,
    )

    assert [candidate.stable_id for candidate in result.candidates] == ["id-a", "id-b"]
    assert result.diagnostics.within_channel_duplicate_count == 1
    assert result.candidates[0].channels == ("fts", "vector")


def test_each_channel_is_bounded_to_forty_candidates() -> None:
    candidates = [_candidate(f"id-{index:02d}") for index in range(MAX_CANDIDATES_PER_CHANNEL + 5)]

    result = reciprocal_rank_fusion(
        {"fts": candidates},
        approved_scopes=("vault_note",),
        top_k=MAX_CANDIDATES_PER_CHANNEL,
    )

    assert len(result.candidates) == MAX_CANDIDATES_PER_CHANNEL
    assert result.diagnostics.input_counts == {"fts": MAX_CANDIDATES_PER_CHANNEL}
    assert "id-40" not in {candidate.stable_id for candidate in result.candidates}


def test_retrieval_service_exposes_typed_rrf_provenance_and_disabled_reranker(tmp_path) -> None:
    service, vault_id = _indexed_service(tmp_path)
    candidate = _authoritative_candidate(service, vault_id)
    service.vector_index = StubVectorIndex(results=[replace(candidate, score=999_999.0)])

    first = service.search(vault_id=vault_id, query="exact-token", mode="hybrid")
    service.vector_index = StubVectorIndex(results=[replace(candidate, score=-999_999.0)])
    second = service.search(vault_id=vault_id, query="exact-token", mode="hybrid")

    assert first.results[0].chunk_id == candidate.chunk_id
    assert first.results[0].retrieval_mode == "vector"
    assert first.results[0].retrieval_channels == ["fts", "vector"]
    assert first.results[0].channel_ranks == {"fts": 1, "vector": 1}
    assert [item.model_dump() for item in first.results[0].retrieval_contributions] == [
        {"channel": "fts", "rank": 1, "rrf_component": 1 / 61},
        {"channel": "vector", "rank": 1, "rrf_component": 1 / 61},
    ]
    assert first.results[0].content_hash == candidate.content_hash
    assert first.results[0].score == 2 / 61
    assert second.results[0].score == first.results[0].score
    assert first.metadata["fusion"]["algorithm"] == "reciprocal_rank_fusion"
    assert first.metadata["fusion"]["rrf_k"] == 60
    assert first.metadata["reranker"]["status"] == "disabled"
    assert first.metadata["reranker"]["external_request_count"] == 0
    assert first.metadata["reranker"]["external_cost_usd"] == 0.0


def test_structured_diary_projection_excludes_non_active_lifecycle_states() -> None:
    now = datetime.now(timezone.utc).isoformat()

    def record(stable_id: str, status: MemoryFactStatus) -> DiaryMemoryObjectRecord:
        return DiaryMemoryObjectRecord(
            id=stable_id,
            vault_id="vault-1",
            type="event",
            summary=f"summary-{stable_id}",
            topic="topic",
            emotion=None,
            people=(),
            keywords=(),
            importance=0.8,
            confidence=0.9,
            occurred_at=now,
            timezone="UTC",
            status=status,
            object_hash=f"hash-{stable_id}",
            extraction_model=None,
            created_at=now,
            updated_at=now,
        )

    results = diary_records_to_search_results(
        (
            record("active", MemoryFactStatus.ACTIVE),
            record("candidate", MemoryFactStatus.CANDIDATE),
            record("quarantined", MemoryFactStatus.QUARANTINED),
            record("superseded", MemoryFactStatus.SUPERSEDED),
            record("sensitive", MemoryFactStatus.SENSITIVE_BLOCKED),
        )
    )

    assert [result.chunk_id for result in results] == ["active"]
    assert results[0].lifecycle_status == "active"
    assert results[0].content_hash == "hash-active"
    assert results[0].retrieval_channels == ["diary"]


def test_retrieval_candidate_policy_filters_before_fusion_and_fails_closed(tmp_path) -> None:
    service, vault_id = _indexed_service(tmp_path)
    service.candidate_filter = lambda result: result.chunk_id == "never-allowed"

    rejected = service.search(vault_id=vault_id, query="exact-token", mode="fts")

    assert rejected.results == []
    assert rejected.metadata["fusion"]["filtered_count"] == 1

    def broken_policy(_result):
        raise RuntimeError("private policy detail")

    service.candidate_filter = broken_policy
    failed_closed = service.search(vault_id=vault_id, query="exact-token", mode="fts")

    assert failed_closed.results == []
    assert failed_closed.metadata["fusion"]["filtered_count"] == 1
    assert "private policy detail" not in str(failed_closed.metadata)


def test_structured_channels_filter_before_rrf_and_preserve_fused_budget_order() -> None:
    def structured(
        stable_id: str,
        *,
        source_scope: str,
        retrieval_mode: str,
        lifecycle_status: str = "active",
        permissions: MemoryRecallPermissions | None = None,
        risk_tier: str | None = None,
    ) -> MemorySearchResult:
        return MemorySearchResult(
            note_id=stable_id,
            chunk_id=stable_id,
            relative_path=(
                f"DiaryMemory/{stable_id}"
                if source_scope == "diary_objects"
                else "MemoryGraph/LongTerm"
            ),
            title="Structured memory",
            heading="topic",
            snippet=f"synthetic-{stable_id}",
            score=999_999.0,
            content_hash=f"hash-{stable_id}",
            source_scope=source_scope,
            retrieval_mode=retrieval_mode,
            recall_permissions=permissions or MemoryRecallPermissions(),
            lifecycle_status=lifecycle_status,
            risk_tier=risk_tier,
            fact_id=stable_id if source_scope == "personal_memory" else None,
        )

    style_only = structured(
        "style",
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=False),
    )
    diary = structured("diary", source_scope="diary_objects", retrieval_mode="diary_object")
    candidate = structured(
        "candidate",
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        lifecycle_status="candidate",
    )
    denied = structured(
        "denied",
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        permissions=MemoryRecallPermissions(can_answer_context=False),
    )
    high_risk = structured(
        "high-risk",
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        risk_tier="high",
    )

    forward = _fuse_structured_memory_results(
        [style_only, diary, candidate, denied, high_risk],
        preferred_scopes=("personal_memory", "diary_objects"),
    )
    reverse_completion = _fuse_structured_memory_results(
        [diary, style_only, high_risk, denied, candidate],
        preferred_scopes=("personal_memory", "diary_objects"),
    )

    assert [result.chunk_id for result in forward] == ["style", "diary"]
    assert [result.chunk_id for result in reverse_completion] == ["style", "diary"]
    assert forward[0].retrieval_channels == ["active_memory"]
    assert forward[0].retrieval_contributions[0].rank == 1
    assert forward[1].retrieval_channels == ["diary"]

    selected = _select_fused_memory_context(
        forward,
        [style_only, diary, candidate, denied, high_risk],
        limit=2,
        per_scope_limit=1,
    )
    assert [result.chunk_id for result in selected.selected] == ["style", "diary"]
    assert selected.telemetry.candidate_count == 5
    assert selected.telemetry.selected_count == 2


def test_vault_lifecycle_directories_are_filtered_before_fts_fusion(tmp_path) -> None:
    vault = tmp_path / "vault"
    active_path = vault / "Memories" / "LongTerm" / "Profile.md"
    superseded_path = vault / "Memories" / "LongTerm" / "Superseded" / "Old.md"
    active_path.parent.mkdir(parents=True)
    superseded_path.parent.mkdir(parents=True)
    active_path.write_text("# Profile\n\nactive-lifecycle-token", encoding="utf-8")
    superseded_path.write_text("# Old\n\nsuperseded-lifecycle-token", encoding="utf-8")
    service = RetrievalService(Database(tmp_path / "state.sqlite3"))
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    assert service.rebuild_index(vault_id).status == "success"

    active = service.search(vault_id=vault_id, query="active-lifecycle-token", mode="fts")
    superseded = service.search(vault_id=vault_id, query="superseded-lifecycle-token", mode="fts")

    assert [result.relative_path for result in active.results] == ["Memories/LongTerm/Profile.md"]
    assert superseded.results == []
    assert superseded.metadata["fusion"]["filtered_count"] == 1

def test_weighted_rrf_components_scale_by_channel_weight() -> None:
    from app.services.retrieval_fusion import reciprocal_rank_fusion

    def cand(cid: str, scope: str = "knowledge_base") -> FusionCandidate:
        return FusionCandidate(
            stable_id=cid,
            content_hash=f"hash-{cid}",
            source_scope=scope,
            payload=object(),
        )

    channels = {
        "fts": [cand("a"), cand("b")],
        "vector": [cand("b"), cand("a")],
    }
    result = reciprocal_rank_fusion(
        channels,
        approved_scopes=["knowledge_base"],
        top_k=5,
        channel_weights={"fts": 3.0},
    )

    by_id = {candidate.stable_id: candidate for candidate in result.candidates}
    fts_component = by_id["a"].score_components["fts"]
    vector_component = by_id["a"].score_components["vector"]
    assert abs(fts_component - 3.0 / (60 + 1)) < 1e-9
    assert abs(vector_component - 1.0 / (60 + 2)) < 1e-9

