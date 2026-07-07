from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from app.models.enums import MemoryFactStatus
from app.services.diary_memory import DiaryMemoryObjectSource, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_candidates import MemoryCandidateCreate, MemoryCandidateStore
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from app.services.prompt_profile_provider import PromptProfileProvider
from tests._schema import migrated_connection


def test_active_preference_and_boundary_enter_stable_profile_groups() -> None:
    conn = migrated_connection()
    try:
        _create_candidate(conn, summary="用户偏好简洁回答。", kind=MemoryKind.PREFERENCE, importance=0.7)
        _create_candidate(conn, summary="不要主动展开私人关系话题。", kind=MemoryKind.BOUNDARY, importance=0.9)

        selection = PromptProfileProvider(conn).select()

        assert [item.permission_group for item in selection.items] == ["boundary_profile", "style_profile"]
        assert selection.items[0].category == "boundaries"
        assert selection.items[1].category == "preferences"
        assert selection.telemetry.selected_count == 2
    finally:
        conn.close()


def test_graph_fact_preference_and_boundary_are_supported_without_raw_ids() -> None:
    conn = migrated_connection()
    try:
        preference_id = _create_fact(
            conn,
            kind=MemoryKind.PREFERENCE,
            subject="回答风格",
            predicate="偏好",
            object_value="直接给结论",
        )
        boundary_id = _create_fact(
            conn,
            kind=MemoryKind.BOUNDARY,
            subject="回答边界",
            predicate="遵守",
            object_value="不要主动提及敏感话题",
            importance=0.95,
        )

        selection = PromptProfileProvider(conn).select()
        payload = json.dumps(asdict(selection), ensure_ascii=False)

        assert "直接给结论" in payload
        assert "不要主动提及敏感话题" in payload
        assert preference_id not in payload
        assert boundary_id not in payload
        assert "fact:" not in payload
        assert "target_id" not in payload
    finally:
        conn.close()


def test_diary_mood_objects_do_not_enter_stable_profile() -> None:
    conn = migrated_connection()
    try:
        conn.execute("INSERT INTO vaults(id, root_path, name) VALUES ('vault-1', 'Vault', 'Vault')")
        store = DiaryMemoryStore(conn)
        record = store.insert_object(
            vault_id="vault-1",
            extracted=DiaryMemoryObject(
                summary="User felt frustrated today about flaky tests.",
                topic="work",
                emotion="frustrated",
                people=(),
                keywords=("tests",),
                source_text="User felt frustrated today about flaky tests.",
                importance=0.5,
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
                type="mood",
            ),
            occurred_at="2026-05-13T10:30:00+08:00",
            timezone="Asia/Shanghai",
            source=DiaryMemoryObjectSource(object_id="", source_type="chat_exchange", source_id="run-mood"),
        )

        selection = PromptProfileProvider(conn).select()

        assert record is not None
        assert selection.items == ()
    finally:
        conn.close()


def test_graph_fact_forbidden_profile_buckets_do_not_enter_stable_profile() -> None:
    conn = migrated_connection()
    try:
        def make(*, kind: MemoryKind, object_value: str, **kwargs) -> str:
            return _create_fact(
                conn,
                kind=kind,
                object_value=object_value,
                subject=f"profile:{object_value}",
                **kwargs,
            )

        make(kind=MemoryKind.PREFERENCE, object_value="allowed preference", category="preference")
        make(kind=MemoryKind.PREFERENCE, object_value="allowed empty category", category="")
        make(kind=MemoryKind.BOUNDARY, object_value="allowed boundary", category="boundary")
        make(kind=MemoryKind.BOUNDARY, object_value="allowed empty boundary", category="")

        forbidden_ids = [
            make(
                kind=MemoryKind.PREFERENCE,
                object_value="relationship category bypass",
                category="relationship",
            ),
            make(
                kind=MemoryKind.PREFERENCE,
                object_value="relationship entity bypass",
                category="preference",
                entity_type="relationship",
            ),
            make(
                kind=MemoryKind.BOUNDARY,
                object_value="project category bypass",
                category="project",
            ),
        ]
        for category in ("identity", "person", "name", "profile"):
            forbidden_ids.append(
                make(
                    kind=MemoryKind.PREFERENCE,
                    object_value=f"{category} category bypass",
                    category=category,
                )
            )
        for key, value in (
            ("memory_scope", "relationship"),
            ("scope", "project"),
            ("profile_group", "identity"),
            ("memory_kind", "recent_state"),
            ("kind", "inference"),
            ("category", "historical"),
        ):
            forbidden_ids.append(
                make(
                    kind=MemoryKind.PREFERENCE,
                    object_value=f"metadata {value} bypass",
                    category="preference",
                    metadata={key: value},
                )
            )

        selection = PromptProfileProvider(conn).select()
        payload = json.dumps(asdict(selection), ensure_ascii=False)

        for allowed in (
            "allowed preference",
            "allowed empty category",
            "allowed boundary",
            "allowed empty boundary",
        ):
            assert allowed in payload
        for forbidden in (
            "relationship category bypass",
            "relationship entity bypass",
            "project category bypass",
            "identity category bypass",
            "person category bypass",
            "name category bypass",
            "profile category bypass",
            "metadata relationship bypass",
            "metadata project bypass",
            "metadata identity bypass",
            "metadata recent_state bypass",
            "metadata inference bypass",
            "metadata historical bypass",
        ):
            assert forbidden not in payload
        for raw_id in forbidden_ids:
            assert raw_id not in payload
    finally:
        conn.close()


def test_unstable_or_unsupported_profile_items_are_excluded() -> None:
    conn = migrated_connection()
    try:
        _create_candidate(conn, summary="keep", kind=MemoryKind.PREFERENCE)
        _create_candidate(conn, summary="candidate", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.CANDIDATE)
        _create_candidate(conn, summary="stale", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.STALE)
        _create_candidate(conn, summary="rejected", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.REJECTED)
        _create_candidate(conn, summary="forgotten", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.FORGOTTEN)
        _create_candidate(conn, summary="superseded", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.SUPERSEDED)
        _create_candidate(conn, summary="archived", kind=MemoryKind.PREFERENCE, status=LifecycleStatus.ARCHIVED)
        _create_candidate(conn, summary="low confidence", kind=MemoryKind.PREFERENCE, confidence=0.74)
        _create_candidate(conn, summary="recent state", kind=MemoryKind.RECENT_STATE)
        _create_candidate(conn, summary="identity fact", kind=MemoryKind.FACT)
        _create_candidate(conn, summary="project context", kind=MemoryKind.PROJECT_CONTEXT)
        _create_candidate(conn, summary="relationship preference", kind=MemoryKind.PREFERENCE, scope=MemoryScope.RELATIONSHIP)
        _create_candidate(conn, summary="project preference", kind=MemoryKind.PREFERENCE, scope=MemoryScope.PROJECT)
        _create_candidate(conn, summary="temporary preference", kind=MemoryKind.PREFERENCE, scope=MemoryScope.TEMPORARY)
        _create_candidate(conn, summary="inference", kind=MemoryKind.INFERENCE)
        _create_candidate(conn, summary="historical", kind=MemoryKind.HISTORICAL)

        selection = PromptProfileProvider(conn).select()
        payload = json.dumps(asdict(selection), ensure_ascii=False)

        assert [item.summary for item in selection.items] == ["keep"]
        for forbidden in (
            "candidate",
            "stale",
            "rejected",
            "forgotten",
            "superseded",
            "archived",
            "low confidence",
            "recent state",
            "identity fact",
            "project context",
            "relationship preference",
            "project preference",
            "temporary preference",
            "inference",
            "historical",
        ):
            assert forbidden not in payload
    finally:
        conn.close()


def test_sensitive_risky_redacted_or_internal_text_is_excluded() -> None:
    conn = migrated_connection()
    try:
        _create_candidate(conn, summary="safe preference", kind=MemoryKind.PREFERENCE)
        _create_candidate(conn, summary="medium risk", kind=MemoryKind.PREFERENCE, risk=RiskTier.MEDIUM)
        _create_candidate(conn, summary="high risk", kind=MemoryKind.PREFERENCE, risk=RiskTier.HIGH)
        _create_candidate(conn, summary="sensitive scope", kind=MemoryKind.PREFERENCE, scope=MemoryScope.SENSITIVE)
        _create_candidate(conn, summary="Authorization token source_text source_excerpt", kind=MemoryKind.PREFERENCE)
        _create_candidate(conn, summary="C:\\Users\\Ada\\Vault\\secret.md", kind=MemoryKind.PREFERENCE)
        _create_candidate(conn, summary="candidate:raw fact:raw target_id memory_candidates FTS vector lifecycle_status", kind=MemoryKind.PREFERENCE)
        _create_candidate(conn, summary="敏感细节已隐藏", kind=MemoryKind.PREFERENCE)

        selection = PromptProfileProvider(conn).select()
        payload = json.dumps(asdict(selection), ensure_ascii=False)

        assert [item.summary for item in selection.items] == ["safe preference"]
        assert "Authorization" not in payload
        assert "token" not in payload
        assert "source_text" not in payload
        assert "source_excerpt" not in payload
        assert "C:\\Users" not in payload
        assert "candidate:" not in payload
        assert "fact:" not in payload
        assert "target_id" not in payload
        assert "memory_candidates" not in payload
        assert "FTS" not in payload
        assert "vector" not in payload
        assert "lifecycle_status" not in payload
        assert "敏感细节已隐藏" not in payload
    finally:
        conn.close()


def test_expired_or_temporary_items_are_excluded() -> None:
    conn = migrated_connection()
    try:
        future = datetime.now(timezone.utc) + timedelta(days=1)
        _create_candidate(conn, summary="safe preference", kind=MemoryKind.PREFERENCE)
        _create_candidate(
            conn,
            summary="future temporary preference",
            kind=MemoryKind.PREFERENCE,
            expires_at=future.isoformat(),
        )
        _create_candidate(
            conn,
            summary="expired preference",
            kind=MemoryKind.PREFERENCE,
            expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        )

        selection = PromptProfileProvider(conn).select()

        assert [item.summary for item in selection.items] == ["safe preference"]
    finally:
        conn.close()


def test_top_n_and_budget_drop_whole_items_with_telemetry() -> None:
    conn = migrated_connection()
    try:
        _create_candidate(conn, summary="边界一", kind=MemoryKind.BOUNDARY, importance=0.9)
        _create_candidate(conn, summary="偏好一", kind=MemoryKind.PREFERENCE, importance=0.8)
        _create_candidate(conn, summary="偏好二", kind=MemoryKind.PREFERENCE, importance=0.7)

        limited = PromptProfileProvider(conn, item_limit=2, char_budget=800).select()
        assert [item.summary for item in limited.items] == ["边界一", "偏好一"]
        assert limited.telemetry.dropped_count == 1
        assert "item_limit_exceeded" in limited.telemetry.drop_reasons

        _create_candidate(conn, summary="x" * 220, kind=MemoryKind.BOUNDARY, importance=1.0)
        budgeted = PromptProfileProvider(conn, item_limit=5, char_budget=40).select()
        assert all(len(item.summary) < 100 for item in budgeted.items)
        assert budgeted.telemetry.dropped_count > 0
        assert "char_budget_exceeded" in budgeted.telemetry.drop_reasons
    finally:
        conn.close()


def test_graph_fact_non_active_or_sensitive_statuses_are_excluded() -> None:
    conn = migrated_connection()
    try:
        good = _create_fact(conn, kind=MemoryKind.PREFERENCE, object_value="安全事实")
        wrong = _create_fact(conn, kind=MemoryKind.PREFERENCE, object_value="错误事实")
        sensitive = _create_fact(conn, kind=MemoryKind.PREFERENCE, object_value="敏感事实")
        store = MemoryGraphStore(conn)
        store.update_status(wrong, MemoryFactStatus.WRONG)
        store.update_status(sensitive, MemoryFactStatus.SENSITIVE_BLOCKED)

        selection = PromptProfileProvider(conn).select()
        payload = json.dumps(asdict(selection), ensure_ascii=False)

        assert "安全事实" in payload
        assert "错误事实" not in payload
        assert "敏感事实" not in payload
        assert good not in payload
        assert wrong not in payload
        assert sensitive not in payload
    finally:
        conn.close()


def _create_candidate(
    conn,
    *,
    summary: str,
    kind: MemoryKind,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    risk: RiskTier = RiskTier.LOW,
    confidence: float = 0.9,
    importance: float = 0.8,
    expires_at: str | None = None,
) -> str:
    store = MemoryCandidateStore(conn)
    return store.create_candidate(
        MemoryCandidateCreate(
            memory_kind=kind,
            memory_scope=scope,
            summary=summary,
            normalized_value=summary.casefold(),
            source_text=summary,
            source_track=SourceTrack.EXPLICIT_USER,
            risk_tier=risk,
            confidence=confidence,
            importance=importance,
            status=status,
            expires_at=expires_at,
        )
    ).id


def _create_fact(
    conn,
    *,
    kind: MemoryKind,
    object_value: str,
    subject: str = "用户偏好",
    predicate: str = "是",
    category: str | None = None,
    entity_type: str | None = None,
    metadata: dict[str, object] | None = None,
    confidence: float = 0.9,
    importance: float = 0.8,
) -> str:
    store = MemoryGraphStore(conn)
    return store.upsert_candidate(
        MemoryFactCandidate(
            category=kind.value if category is None else category,
            memory_type=kind.value,
            entity_type=entity_type,
            subject=subject,
            predicate=predicate,
            object=object_value,
            source_text=object_value,
            source_type="user_message",
            confidence=confidence,
            importance=importance,
            metadata_json=json.dumps(metadata) if metadata is not None else None,
        )
    ).fact.id
