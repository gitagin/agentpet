from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import memory as memory_api
from app.services.agent_actions import AgentActionCreate, AgentActionStore
from app.services.memory_candidates import MemoryCandidateCreate, MemoryEvidenceCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from app.utils.time import utc_now_iso
from tests.conftest import auth_headers


def auth() -> dict[str, str]:
    return auth_headers()


def create_candidate(
    client: TestClient,
    *,
    summary: str,
    kind: MemoryKind = MemoryKind.PREFERENCE,
    scope: MemoryScope = MemoryScope.GLOBAL,
    status: LifecycleStatus = LifecycleStatus.ACTIVE,
    risk: RiskTier = RiskTier.LOW,
    confidence: float = 0.9,
    superseded_by: str | None = None,
) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        return service.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=kind,
                memory_scope=scope,
                summary=summary,
                normalized_value=summary.casefold(),
                source_text=summary,
                source_track=SourceTrack.EXPLICIT_USER,
                risk_tier=risk,
                confidence=confidence,
                importance=0.8,
                status=status,
                superseded_by=superseded_by,
            )
        ).id
    finally:
        service.close()


def create_preference_fact(client: TestClient, *, object_value: str = "简洁") -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category=MemoryKind.PREFERENCE.value,
                memory_type=MemoryKind.PREFERENCE.value,
                subject="回答风格",
                predicate="是",
                object=object_value,
                source_text=f"用户偏好回答{object_value}",
                source_type="user_message",
                confidence=0.9,
                importance=0.8,
            )
        ).fact
        return fact.id
    finally:
        service.close()


def seed_agent_run(client: TestClient, run_id: str) -> None:
    now = utc_now_iso()
    with sqlite3.connect(client.app.state.database.path) as conn:
        with conn:
            conn.execute(
                "INSERT INTO conversations (id, title, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("conv-profile-1", "memory receipt test", "active", now, now),
            )
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("msg-profile-user-1", "conv-profile-1", "user", "请记住我喜欢简洁回答", "completed", now, now),
            )
            conn.execute(
                """
                INSERT INTO agent_runs (id, conversation_id, user_message_id, status, intent, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, "conv-profile-1", "msg-profile-user-1", "success", "chat", now, now),
            )


def seed_answer_memory_usage(client: TestClient, run_id: str) -> None:
    now = utc_now_iso()
    with sqlite3.connect(client.app.state.database.path) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO memory_activation_events (
                    id, candidate_id, fact_id, conversation_id, message_id,
                    agent_run_id, activation_score, permissions_json,
                    score_breakdown_json, used_for_style, used_for_answer_context,
                    used_for_proactive_mention, used_for_action_suggestion,
                    filtered_reason, created_at
                )
                VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, 0, 1, 0, 0, NULL, ?)
                """,
                (
                    "activation-profile-used",
                    "conv-profile-1",
                    "msg-profile-user-1",
                    run_id,
                    0.91,
                    "{}",
                    "{}",
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO companion_retrieval_reports (
                    id, agent_run_id, strategy, query_hash, candidate_count, selected_count,
                    duplicate_drop_count, per_scope_drop_count, budget_drop_count,
                    item_budget, per_scope_limit, char_budget, used_chars,
                    source_counts_json, selected_scopes_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "retrieval-report-profile-used",
                    run_id,
                    "hybrid",
                    "query-hash",
                    3,
                    2,
                    0,
                    0,
                    0,
                    8,
                    4,
                    1200,
                    360,
                    "{}",
                    '["personal_memory"]',
                    now,
                ),
            )


def string_values(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from string_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from string_values(nested)


def assert_no_profile_action_leaks(value: object, *raw_ids: str) -> None:
    forbidden = (
        "candidate:",
        "fact:",
        "target_id",
        "memory_candidates",
        "source_text",
        "source_excerpt",
        "Authorization",
        "token",
        "agent_run_id",
    )
    for text in string_values(value):
        for raw_id in raw_ids:
            assert raw_id not in text
        for term in forbidden:
            assert term not in text


def find_profile_item(payload: dict[str, object], summary_text: str) -> dict[str, object]:
    for group in (
        "identity",
        "preferences",
        "boundaries",
        "projects",
        "relationships",
        "recent_state",
        "conflicts",
        "needs_confirmation",
        "filtered",
    ):
        for item in payload[group]:
            if summary_text in item["summary"]:
                return item
    raise AssertionError(f"profile item not found: {summary_text}")


def profile_item_for(client: TestClient, summary_text: str) -> dict[str, object]:
    response = client.get("/api/memory/profile-projection", headers=auth())
    assert response.status_code == 200
    return find_profile_item(response.json(), summary_text)


def test_profile_projection_groups_active_preference_boundary_and_candidates(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        create_preference_fact(client)
        boundary_id = create_candidate(
            client,
            summary="不要在早上主动提醒我任务。",
            kind=MemoryKind.BOUNDARY,
            scope=MemoryScope.GLOBAL,
        )
        low_confidence_id = create_candidate(
            client,
            summary="也许用户偶尔喜欢很长的解释。",
            confidence=0.4,
        )

        response = client.get("/api/memory/profile-projection", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        assert any("简洁" in item["summary"] for item in payload["preferences"])
        assert payload["boundaries"]
        assert payload["needs_confirmation"]
        for value in string_values(payload):
            assert boundary_id not in value
            assert low_confidence_id not in value
            assert "memory_candidates" not in value
            assert "lifecycle_status" not in value
        assert payload["generated_at"]
        assert payload["redaction_note"]


def test_profile_projection_filters_rejected_forgotten_superseded_and_sensitive(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        rejected_id = create_candidate(
            client,
            summary="Rejected raw preference should not appear.",
            status=LifecycleStatus.REJECTED,
        )
        forgotten_id = create_candidate(
            client,
            summary="Forgotten raw preference should not appear.",
            status=LifecycleStatus.FORGOTTEN,
        )
        replacement_id = create_candidate(client, summary="以后回答保持简洁。")
        superseded_id = create_candidate(
            client,
            summary="Old superseded preference should not be current.",
            status=LifecycleStatus.SUPERSEDED,
            superseded_by=replacement_id,
        )
        sensitive_id = create_candidate(
            client,
            summary="token=sk-profile-secret-12345678901234567890",
            risk=RiskTier.HIGH,
        )

        response = client.get("/api/memory/profile-projection", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        ordinary_groups = [
            *payload["identity"],
            *payload["preferences"],
            *payload["boundaries"],
            *payload["projects"],
            *payload["relationships"],
            *payload["recent_state"],
            *payload["needs_confirmation"],
        ]
        assert payload["conflicts"]
        assert payload["filtered"]
        body = response.text
        assert "sk-profile-secret" not in body
        assert "token=" not in body
        assert "Rejected raw preference" not in body
        assert "Forgotten raw preference" not in body
        for raw_id in (rejected_id, forgotten_id, superseded_id, sensitive_id):
            assert raw_id not in body


def test_profile_projection_and_receipts_do_not_return_raw_sources_or_internal_paths(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        create_candidate(
            client,
            summary=r"请不要展示 E:\Users\Alice\Vault\Secret.md",
            risk=RiskTier.HIGH,
        )
        profile = client.get("/api/memory/profile-projection", headers=auth())

        assert profile.status_code == 200
        profile_body = profile.text
        for forbidden in (
            "source_text",
            "source_excerpt",
            r"E:\\Users\\Alice",
            "Authorization",
            "Bearer",
        ):
            assert forbidden not in profile_body

        run_id = "run-memory-receipt-1"
        seed_agent_run(client, run_id)
        service = MemoryLifecycleService(client.app.state.database.path)
        try:
            remembered = service.candidates.create_candidate(
                MemoryCandidateCreate(
                    memory_kind=MemoryKind.PREFERENCE,
                    memory_scope=MemoryScope.GLOBAL,
                    summary="用户喜欢简洁回答。",
                    normalized_value="用户喜欢简洁回答。",
                    source_text="raw source text must not leak",
                    source_track=SourceTrack.EXPLICIT_USER,
                    risk_tier=RiskTier.LOW,
                    confidence=0.9,
                    importance=0.8,
                    status=LifecycleStatus.ACTIVE,
                )
            )
            needs_confirmation = service.candidates.create_candidate(
                MemoryCandidateCreate(
                    memory_kind=MemoryKind.PREFERENCE,
                    memory_scope=MemoryScope.GLOBAL,
                    summary="也许用户喜欢长篇解释。",
                    normalized_value="也许用户喜欢长篇解释。",
                    source_text="low confidence raw source must not leak",
                    source_track=SourceTrack.SLOW_CONSOLIDATION,
                    risk_tier=RiskTier.MEDIUM,
                    confidence=0.4,
                    importance=0.5,
                    status=LifecycleStatus.CANDIDATE,
                )
            )
            service.candidates.add_evidence(
                MemoryEvidenceCreate(
                    candidate_id=remembered.id,
                    source_text="RAW_SOURCE_TEXT_SHOULD_NOT_LEAK",
                    source_excerpt="RAW_SOURCE_EXCERPT_SHOULD_NOT_LEAK",
                    agent_run_id=run_id,
                    confidence=0.9,
                )
            )
            service.candidates.add_evidence(
                MemoryEvidenceCreate(
                    candidate_id=needs_confirmation.id,
                    source_text="LOW_CONF_RAW_SOURCE_SHOULD_NOT_LEAK",
                    source_excerpt="LOW_CONF_RAW_EXCERPT_SHOULD_NOT_LEAK",
                    agent_run_id=run_id,
                    confidence=0.4,
                )
            )
        finally:
            service.close()
        store = AgentActionStore(client.app.state.database.path)
        try:
            store.create(
                AgentActionCreate(
                    action_type="memory.consolidation.skip",
                    title="skip",
                    summary="no durable memory",
                    source_agent_run_id=run_id,
                    status="skipped",
                    metadata={"output_count": 0},
                )
            )
        finally:
            store.close()

        receipt = client.get(f"/api/memory/receipts?agent_run_id={run_id}", headers=auth())

        assert receipt.status_code == 200
        payload = receipt.json()
        kinds = {item["kind"] for item in payload["items"]}
        assert {"remembered", "needs_confirmation", "skipped"}.issubset(kinds)
        for value in string_values(payload):
            assert run_id not in value
            assert f"receipt:used:{run_id}" not in value
        for item in payload["items"]:
            related_memory_id = item.get("related_memory_id")
            if related_memory_id:
                assert remembered.id not in related_memory_id
                assert needs_confirmation.id not in related_memory_id
        receipt_body = receipt.text
        for forbidden in (
            "source_text",
            "source_excerpt",
            "RAW_SOURCE_TEXT_SHOULD_NOT_LEAK",
            "RAW_SOURCE_EXCERPT_SHOULD_NOT_LEAK",
            "Authorization",
            "Bearer",
        ):
            assert forbidden not in receipt_body


def test_memory_receipts_use_opaque_ids_and_dedupe_answer_usage(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        run_id = "run-secret-answer-usage-1"
        seed_agent_run(client, run_id)
        seed_answer_memory_usage(client, run_id)

        response = client.get(f"/api/memory/receipts?agent_run_id={run_id}", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        used_for_answer = [item for item in payload["items"] if item["kind"] == "used_for_answer"]
        assert len(used_for_answer) == 1
        for value in string_values(payload):
            assert run_id not in value
            assert f"receipt:used:{run_id}" not in value
            assert "agent_run_id" not in value
            assert "memory_candidates" not in value
            assert "lifecycle_status" not in value
            assert "FTS" not in value
            assert "vector" not in value


def test_profile_detail_uses_opaque_id_and_safe_chinese_labels(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="Use compact status reports.")

        item = profile_item_for(client, "Use compact status reports.")
        item_id = str(item["id"])
        assert item_id.startswith("profile_")
        assert candidate_id not in item_id
        assert "candidate" not in item_id
        assert "memory" not in item_id

        response = client.get(f"/api/memory/profile-projection/items/{item_id}", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        assert payload["id"] == item_id
        assert payload["summary"] == "Use compact status reports."
        assert payload["category_label"] == "偏好"
        assert payload["status_label"]
        assert payload["confidence_label"]
        assert payload["importance_label"]
        assert payload["source_label"]
        assert "可用于回答" in payload["permissions"]
        assert {action["action"] for action in payload["available_actions"]} >= {"forget", "mark_inaccurate"}
        for value in string_values(payload):
            assert candidate_id not in value
            assert "agent_run_id" not in value
            assert "source_text" not in value
            assert "source_excerpt" not in value
            assert "Authorization" not in value
            assert "token" not in value
            assert "memory_candidates" not in value
            assert "FTS" not in value
            assert "vector" not in value
            assert "lifecycle_status" not in value


def test_profile_detail_source_summary_uses_safe_aggregate_counts(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        run_id = "run-source-summary-secret-1"
        seed_agent_run(client, run_id)
        candidate_id = create_candidate(client, summary="Prefer short source summaries.")
        service = MemoryLifecycleService(client.app.state.database.path)
        try:
            service.candidates.add_evidence(
                MemoryEvidenceCreate(
                    candidate_id=candidate_id,
                    source_type="chat_message",
                    source_text="RAW_SOURCE_TEXT_SHOULD_NOT_LEAK E:\\Users\\Alice\\Vault\\Secret.md",
                    source_excerpt="RAW_SOURCE_EXCERPT_SHOULD_NOT_LEAK",
                    agent_run_id=run_id,
                    confidence=0.9,
                )
            )
            service.candidates.add_evidence(
                MemoryEvidenceCreate(
                    candidate_id=candidate_id,
                    source_type="user_message",
                    source_text="Authorization: Bearer hidden-token",
                    source_excerpt="SECOND_RAW_EXCERPT_SHOULD_NOT_LEAK",
                    agent_run_id=run_id,
                    confidence=0.8,
                )
            )
        finally:
            service.close()

        item = profile_item_for(client, "Prefer short source summaries.")
        response = client.get(f"/api/memory/profile-projection/items/{item['id']}", headers=auth())

        assert response.status_code == 200
        payload = response.json()
        source_summary = payload["source_summary"]
        assert source_summary is not None
        assert "2" in source_summary["evidence_count_label"]
        assert "安全来源" in source_summary["evidence_count_label"]
        assert source_summary["last_seen_label"].startswith("最近更新于 ")
        assert source_summary["safety_note"] == "来源内容已做安全摘要，未显示原文。"
        body = response.text
        for forbidden in (
            candidate_id,
            run_id,
            "RAW_SOURCE_TEXT_SHOULD_NOT_LEAK",
            "RAW_SOURCE_EXCERPT_SHOULD_NOT_LEAK",
            "SECOND_RAW_EXCERPT_SHOULD_NOT_LEAK",
            "source_text",
            "source_excerpt",
            "agent_run_id",
            "Authorization",
            "hidden-token",
            r"E:\\Users\\Alice",
            "memory_candidates",
            "FTS",
            "vector",
            "lifecycle_status",
        ):
            assert forbidden not in body


def test_profile_detail_redacts_sensitive_memory(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        raw_secret = "token=sk-profile-detail-secret-1234567890"
        candidate_id = create_candidate(client, summary=raw_secret, risk=RiskTier.HIGH)
        response = client.get("/api/memory/profile-projection", headers=auth())
        assert response.status_code == 200
        filtered = response.json()["filtered"]
        assert filtered
        item_id = filtered[0]["id"]
        assert candidate_id not in item_id

        detail = client.get(f"/api/memory/profile-projection/items/{item_id}", headers=auth())

        assert detail.status_code == 200
        payload = detail.json()
        assert payload["safety_note"]
        assert payload["source_summary"]["label"] == "来源细节已隐藏"
        assert payload["source_summary"]["safety_note"] == "来源细节已隐藏。"
        assert payload["source_summary"]["evidence_count_label"] is None
        assert payload["available_actions"] == []
        body = detail.text
        assert "sk-profile-detail-secret" not in body
        assert "token=" not in body
        assert candidate_id not in body


def test_profile_detail_allows_missing_source_summary(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="No safe source summary yet.")
        with sqlite3.connect(client.app.state.database.path) as conn:
            with conn:
                conn.execute("UPDATE memory_candidates SET evidence_count = 0 WHERE id = ?", (candidate_id,))

        item = profile_item_for(client, "No safe source summary yet.")
        detail = client.get(f"/api/memory/profile-projection/items/{item['id']}", headers=auth())

        assert detail.status_code == 200
        payload = detail.json()
        assert payload["source_summary"] is None
        assert_no_profile_action_leaks(payload, candidate_id)


def test_profile_action_requires_confirmation_and_does_not_write(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="Require confirmation before forgetting.")
        item = profile_item_for(client, "Require confirmation before forgetting.")

        response = client.post(
            f"/api/memory/profile-projection/items/{item['id']}/actions",
            headers=auth(),
            json={"action": "forget", "confirmed": False},
        )

        assert response.status_code == 400
        with sqlite3.connect(client.app.state.database.path) as conn:
            row = conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
        assert row[0] == LifecycleStatus.ACTIVE.value

        missing = client.post(
            f"/api/memory/profile-projection/items/{item['id']}/actions",
            headers=auth(),
            json={"action": "forget"},
        )

        assert missing.status_code == 400
        assert_no_profile_action_leaks(missing.json(), candidate_id)
        with sqlite3.connect(client.app.state.database.path) as conn:
            row = conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
        assert row[0] == LifecycleStatus.ACTIVE.value


def test_profile_make_temporary_requires_valid_future_expiry(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="Make this profile item temporary.")
        item = profile_item_for(client, "Make this profile item temporary.")

        requests = [
            {"action": "make_temporary", "confirmed": True},
            {"action": "make_temporary", "confirmed": True, "expires_at": "not-a-date"},
            {
                "action": "make_temporary",
                "confirmed": True,
                "expires_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            },
        ]

        for payload in requests:
            response = client.post(
                f"/api/memory/profile-projection/items/{item['id']}/actions",
                headers=auth(),
                json=payload,
            )
            assert response.status_code == 400
            assert_no_profile_action_leaks(response.json(), candidate_id)

        with sqlite3.connect(client.app.state.database.path) as conn:
            row = conn.execute(
                "SELECT status, memory_kind, memory_scope, expires_at FROM memory_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()
        assert row == (
            LifecycleStatus.ACTIVE.value,
            MemoryKind.PREFERENCE.value,
            MemoryScope.GLOBAL.value,
            None,
        )


def test_profile_actions_update_candidate_without_exposing_raw_ids(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        forget_id = create_candidate(client, summary="Forget this profile item.")
        keep_id = create_candidate(
            client,
            summary="Confirm this pending profile item.",
            status=LifecycleStatus.CANDIDATE,
            confidence=0.45,
        )
        inaccurate_id = create_candidate(client, summary="This profile item is inaccurate.")

        forget_item = profile_item_for(client, "Forget this profile item.")
        keep_item = profile_item_for(client, "Confirm this pending profile item.")
        inaccurate_item = profile_item_for(client, "This profile item is inaccurate.")

        forget = client.post(
            f"/api/memory/profile-projection/items/{forget_item['id']}/actions",
            headers=auth(),
            json={"action": "forget", "confirmed": True},
        )
        keep = client.post(
            f"/api/memory/profile-projection/items/{keep_item['id']}/actions",
            headers=auth(),
            json={"action": "keep", "confirmed": True},
        )
        inaccurate = client.post(
            f"/api/memory/profile-projection/items/{inaccurate_item['id']}/actions",
            headers=auth(),
            json={"action": "mark_inaccurate", "confirmed": True},
        )

        assert forget.status_code == 200
        assert keep.status_code == 200
        assert inaccurate.status_code == 200
        for response, raw_id in ((forget, forget_id), (keep, keep_id), (inaccurate, inaccurate_id)):
            assert_no_profile_action_leaks(response.json(), raw_id)
            assert response.json()["item_id"].startswith("profile_")

        with sqlite3.connect(client.app.state.database.path) as conn:
            statuses = dict(conn.execute("SELECT id, status FROM memory_candidates").fetchall())
        assert statuses[forget_id] == LifecycleStatus.FORGOTTEN.value
        assert statuses[keep_id] == LifecycleStatus.ACTIVE.value
        assert statuses[inaccurate_id] == LifecycleStatus.REJECTED.value

        projection = client.get("/api/memory/profile-projection", headers=auth()).json()
        ordinary = [
            *projection["identity"],
            *projection["preferences"],
            *projection["boundaries"],
            *projection["projects"],
            *projection["relationships"],
            *projection["recent_state"],
            *projection["needs_confirmation"],
        ]
        assert all(item["id"] != forget_item["id"] for item in ordinary)
        assert all(item["id"] != inaccurate_item["id"] for item in ordinary)


def test_profile_action_records_safe_agent_action(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="Record a safe profile action.")
        item = profile_item_for(client, "Record a safe profile action.")

        response = client.post(
            f"/api/memory/profile-projection/items/{item['id']}/actions",
            headers=auth(),
            json={"action": "forget", "confirmed": True},
        )

        assert response.status_code == 200
        actions = client.get("/api/agent/actions?limit=10", headers=auth())
        assert actions.status_code == 200
        body = actions.text
        assert candidate_id not in body
        assert "candidate:" not in body
        assert "target_id" not in body
        assert "memory_candidates" not in body

        payload = actions.json()
        profile_actions = [
            action for action in payload["actions"] if action["action_type"] == "memory.profile.action"
        ]
        assert profile_actions
        action = profile_actions[0]
        assert action["summary"] == "已撤回一条画像记忆"
        assert action["metadata"]["profile_item_id"] == item["id"]
        assert_no_profile_action_leaks(action, candidate_id)


def test_profile_action_failure_response_is_safe(client_factory, tmp_path: Path, monkeypatch) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = create_candidate(client, summary="Fail safely when feedback errors.")
        item = profile_item_for(client, "Fail safely when feedback errors.")

        class FailingLifecycleService:
            def apply_feedback(self, **kwargs):
                raise KeyError(f"target_id={kwargs.get('target_id')}")

            def close(self) -> None:
                pass

        monkeypatch.setattr(memory_api, "memory_lifecycle_service", lambda request: FailingLifecycleService())

        response = client.post(
            f"/api/memory/profile-projection/items/{item['id']}/actions",
            headers=auth(),
            json={"action": "forget", "confirmed": True},
        )

        assert response.status_code == 422
        assert_no_profile_action_leaks(response.json(), candidate_id)
        with sqlite3.connect(client.app.state.database.path) as conn:
            status_row = conn.execute("SELECT status FROM memory_candidates WHERE id = ?", (candidate_id,)).fetchone()
            action_count = conn.execute("SELECT COUNT(*) FROM agent_actions").fetchone()[0]
        assert status_row[0] == LifecycleStatus.ACTIVE.value
        assert action_count == 0


def test_profile_action_marks_graph_fact_inaccurate_safely(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = create_preference_fact(client, object_value="fact detail marker")
        item = profile_item_for(client, "fact detail marker")

        response = client.post(
            f"/api/memory/profile-projection/items/{item['id']}/actions",
            headers=auth(),
            json={"action": "mark_inaccurate", "confirmed": True},
        )

        assert response.status_code == 200
        assert_no_profile_action_leaks(response.json(), fact_id)
        with sqlite3.connect(client.app.state.database.path) as conn:
            row = conn.execute("SELECT status FROM memory_graph_facts WHERE id = ?", (fact_id,)).fetchone()
        assert row[0] == "wrong"


def test_memory_projection_endpoints_require_authentication(client_factory, tmp_path: Path) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        profile = client.get("/api/memory/profile-projection")
        receipts = client.get("/api/memory/receipts")
        detail = client.get("/api/memory/profile-projection/items/profile_missing")

        assert profile.status_code in {401, 403}
        assert receipts.status_code in {401, 403}
        assert detail.status_code in {401, 403}
