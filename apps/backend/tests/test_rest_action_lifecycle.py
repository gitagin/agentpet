from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.services import adapters
from app.models.enums import MemoryFactStatus, MemoryProposalStatus
from app.services.continuity import ContinuityService
from app.services.memory import MemoryProposalStore
from app.services.memory_candidates import MemoryCandidateCreate
from app.services.memory_graph import MemoryFactCandidate
from app.services.memory_lifecycle import MemoryLifecycleService
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RiskTier, SourceTrack
from tests.conftest import auth_headers


def _bind_vault(client: TestClient, vault: Path) -> None:
    response = client.post(
        "/api/vaults/init",
        headers=auth_headers(),
        json={"path": str(vault), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200


def _create_task(client: TestClient, title: str, *, with_reminder: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {"title": title}
    if with_reminder:
        payload.update({"remind_at": "2099-01-01T00:00:00Z", "timezone": "UTC"})
    response = client.post("/api/tasks", headers=auth_headers(), json=payload)
    assert response.status_code == 200
    return response.json()


def _action_rows(client: TestClient, action_type: str) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM agent_actions WHERE action_type = ? ORDER BY created_at",
            (action_type,),
        ).fetchall()


def _create_continuity_proposal(client: TestClient, message: str) -> str:
    service = ContinuityService(client.app.state.database.path)
    try:
        proposals = asyncio.run(
            service.create_proposals_from_exchange(
                user_message=message,
                assistant_answer="We can continue later.",
                conversation_id="conversation-lifecycle",
                source_message_id="message-lifecycle",
                agent_run_id="run-lifecycle",
            )
        )
    finally:
        service.close()
    assert proposals
    return proposals[0].id


def _create_memory_fact(client: TestClient, *, subject: str, object_value: str) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        fact = service.graph.upsert_candidate(
            MemoryFactCandidate(
                category="preference",
                memory_type="preference",
                subject=subject,
                predicate="is",
                object=object_value,
                source_text=f"{subject} is {object_value}.",
                confidence=0.9,
                importance=0.8,
            )
        ).fact
        assert fact.status is MemoryFactStatus.ACTIVE
        return fact.id
    finally:
        service.close()


def _create_expired_hygiene_candidate(client: TestClient, *, summary: str) -> str:
    service = MemoryLifecycleService(client.app.state.database.path)
    try:
        return service.candidates.create_candidate(
            MemoryCandidateCreate(
                memory_kind=MemoryKind.RECENT_STATE,
                memory_scope=MemoryScope.TEMPORARY,
                summary=summary,
                normalized_value=summary.casefold(),
                source_text=summary,
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                risk_tier=RiskTier.LOW,
                confidence=0.8,
                importance=0.5,
                status=LifecycleStatus.ACTIVE,
                expires_at="2020-01-01T00:00:00Z",
            )
        ).id
    finally:
        service.close()


def _hygiene_suggestion(client: TestClient, suggestion_type: str) -> dict[str, object]:
    response = client.get("/api/memory/hygiene/preview", headers=auth_headers())
    assert response.status_code == 200
    return next(item for item in response.json()["suggestions"] if item["type"] == suggestion_type)


def test_task_rest_mutations_share_claim_receipt_registry_and_repeat_once(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        cases = [
            ("task.complete", "post", "/complete", None, "done", True),
            ("task.approve", "post", "/approve", None, "pending", False),
            ("task.reject", "post", "/reject", None, "cancelled", True),
            ("task.cancel", "post", "/cancel", None, "cancelled", True),
            ("task.patch", "patch", "", {"status": "done"}, "done", True),
        ]

        for index, (action_type, method_name, suffix, body, expected_status, with_reminder) in enumerate(cases):
            task = _create_task(client, f"Lifecycle mutation {index}", with_reminder=with_reminder)
            task_id = str(task["task_id"])
            method = getattr(client, method_name)
            url = f"/api/tasks/{task_id}{suffix}"
            first = method(url, headers=auth_headers(), json=body) if body is not None else method(url, headers=auth_headers())
            second = method(url, headers=auth_headers(), json=body) if body is not None else method(url, headers=auth_headers())

            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json() == first.json()
            assert first.json()["status"] == expected_status
            if action_type == "task.approve":
                assert first.json()["approved"] is True
                assert first.json()["rejected"] is False
            if action_type == "task.reject":
                assert first.json()["approved"] is False
                assert first.json()["rejected"] is True

            rows = _action_rows(client, action_type)
            assert len(rows) == 1
            metadata = json.loads(str(rows[0]["metadata_json"]))
            assert rows[0]["status"] == "completed"
            assert metadata["execution_receipt"]["status"] == "verified"
            if expected_status in {"done", "cancelled"}:
                with sqlite3.connect(client.app.state.database.path) as conn:
                    reminders = conn.execute(
                        "SELECT status, scheduler_job_id FROM reminders WHERE task_id = ?",
                        (task_id,),
                    ).fetchall()
                assert reminders
                assert all(status == "cancelled" and job_id is None for status, job_id in reminders)


def test_task_complete_api_recovers_effect_before_receipt_without_repeating_reminder_cancel(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._task_mutation_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            result = await inner(proposal, policy, claim)
            if policy.action_type == "task.complete":
                calls += 1
                raise RuntimeError("receipt interrupted after task commit")
            return result

        return execute

    monkeypatch.setattr(adapters, "_task_mutation_adapter", interrupted_factory)

    with client_factory(data_dir=tmp_path / "data") as client:
        task = _create_task(client, "Recover complete mutation")
        task_id = str(task["task_id"])

        first = client.post(f"/api/tasks/{task_id}/complete", headers=auth_headers())
        second = client.post(f"/api/tasks/{task_id}/complete", headers=auth_headers())

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == first.json() == {"task_id": task_id, "status": "done"}
        assert calls == 1
        rows = _action_rows(client, "task.complete")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        assert metadata["execution_receipt"]["result"]["untriggered_reminders_cancelled"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            reminder = conn.execute(
                "SELECT status, scheduler_job_id FROM reminders WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        assert reminder == ("cancelled", None)


def test_memory_confirm_api_reconciles_marker_after_markdown_commit_and_reuses_receipt(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_update_status = MemoryProposalStore.update_status
    interrupted = False

    def interrupt_confirm_status(self, proposal_id, status, **kwargs):
        nonlocal interrupted
        if status == MemoryProposalStatus.CONFIRMED and not interrupted:
            interrupted = True
            raise RuntimeError("receipt interrupted after markdown commit")
        return original_update_status(self, proposal_id, status, **kwargs)

    monkeypatch.setattr(MemoryProposalStore, "update_status", interrupt_confirm_status)

    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, vault)
        content = "- Marker-backed memory confirmation."
        created = client.post(
            "/api/memory/proposals",
            headers=auth_headers(),
            json={
                "type": "fact",
                "content": content,
                "target_path": "Inbox/Pending Memories.md",
            },
        )
        proposal_id = created.json()["proposal_id"]

        first = client.post(f"/api/memory/proposals/{proposal_id}/confirm", headers=auth_headers())
        second = client.post(f"/api/memory/proposals/{proposal_id}/confirm", headers=auth_headers())

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == first.json()
        assert interrupted is True
        markdown = (vault / "Inbox" / "Pending Memories.md").read_text(encoding="utf-8")
        assert markdown.count(content) == 1
        assert len(re.findall(r"<!-- llmwiki-memory-confirm:[0-9a-f]{64} -->", markdown)) == 1
        with sqlite3.connect(client.app.state.database.path) as conn:
            proposal = conn.execute(
                "SELECT status, written_path FROM memory_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        assert proposal == ("confirmed", str(vault / "Inbox" / "Pending Memories.md"))
        rows = _action_rows(client, "memory.proposal.confirm")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        receipt = metadata["execution_receipt"]
        assert receipt["status"] == "verified"
        assert receipt["result"]["recovered_from_authoritative_state"] is True


def test_memory_reject_api_returns_original_receipt_without_markdown_effect(
    client_factory,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, vault)
        content = "- This rejected candidate must never be written."
        created = client.post(
            "/api/memory/proposals",
            headers=auth_headers(),
            json={
                "type": "fact",
                "content": content,
                "target_path": "Inbox/Pending Memories.md",
            },
        )
        proposal_id = created.json()["proposal_id"]
        request = {"reason": "not durable knowledge"}

        first = client.post(
            f"/api/memory/proposals/{proposal_id}/reject",
            headers=auth_headers(),
            json=request,
        )
        second = client.post(
            f"/api/memory/proposals/{proposal_id}/reject",
            headers=auth_headers(),
            json=request,
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json() == first.json()
        assert content not in (vault / "Inbox" / "Pending Memories.md").read_text(encoding="utf-8")
        rows = _action_rows(client, "memory.proposal.reject")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["status"] == "verified"


def test_memory_feedback_rest_reuses_one_claim_receipt_and_domain_event(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = _create_memory_fact(
            client,
            subject="feedback lifecycle preference",
            object_value="concise updates",
        )
        payload = {
            "target_type": "fact",
            "target_id": fact_id,
            "operation": "forget",
            "feedback_text": "Remove this preference.",
        }

        first = client.post("/api/memory/feedback", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/feedback", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        rows = _action_rows(client, "memory.feedback.apply")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["status"] == "verified"
        with sqlite3.connect(client.app.state.database.path) as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) FROM memory_feedback_events WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()[0]
            status = conn.execute(
                "SELECT status FROM memory_graph_facts WHERE id = ?",
                (fact_id,),
            ).fetchone()[0]
        assert event_count == 1
        assert status == "forgotten"


def test_memory_feedback_recovers_effect_before_receipt_from_action_link(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._memory_feedback_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after feedback commit")

        return execute

    monkeypatch.setattr(adapters, "_memory_feedback_adapter", interrupted_factory)

    with client_factory(data_dir=tmp_path / "data") as client:
        fact_id = _create_memory_fact(
            client,
            subject="feedback recovery preference",
            object_value="verbose updates",
        )
        payload = {
            "target_type": "fact",
            "target_id": fact_id,
            "operation": "forget",
            "feedback_text": "Remove this preference.",
        }

        first = client.post("/api/memory/feedback", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/feedback", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        assert calls == 1
        rows = _action_rows(client, "memory.feedback.apply")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["status"] == "verified"
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) FROM memory_feedback_events WHERE fact_id = ?",
                (fact_id,),
            ).fetchone()[0]
        assert event_count == 1


def test_memory_hygiene_rest_reuses_one_claim_receipt_and_transition(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = _create_expired_hygiene_candidate(
            client,
            summary="Expired temporary state for idempotency.",
        )
        suggestion = _hygiene_suggestion(client, "stale_recent_state")
        payload = {"suggestion_id": suggestion["id"], "confirmed": True}

        first = client.post("/api/memory/hygiene/actions", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/hygiene/actions", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        rows = _action_rows(client, "memory.hygiene.apply")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["status"] == "verified"
        with sqlite3.connect(client.app.state.database.path) as conn:
            transitions = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_lifecycle_events
                WHERE candidate_id = ? AND agent_action_id = ?
                """,
                (candidate_id, first.json()["action_id"]),
            ).fetchone()[0]
            status_value = conn.execute(
                "SELECT status FROM memory_candidates WHERE id = ?",
                (candidate_id,),
            ).fetchone()[0]
        assert transitions == 1
        assert status_value == "archived"


def test_memory_hygiene_recovers_effect_before_receipt_from_action_link(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._memory_hygiene_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after hygiene commit")

        return execute

    monkeypatch.setattr(adapters, "_memory_hygiene_adapter", interrupted_factory)

    with client_factory(data_dir=tmp_path / "data") as client:
        candidate_id = _create_expired_hygiene_candidate(
            client,
            summary="Expired temporary state for recovery.",
        )
        suggestion = _hygiene_suggestion(client, "stale_recent_state")
        payload = {"suggestion_id": suggestion["id"], "confirmed": True}

        first = client.post("/api/memory/hygiene/actions", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/hygiene/actions", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        assert calls == 1
        rows = _action_rows(client, "memory.hygiene.apply")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            transitions = conn.execute(
                """
                SELECT COUNT(*)
                FROM memory_lifecycle_events
                WHERE candidate_id = ? AND agent_action_id = ?
                """,
                (candidate_id, first.json()["action_id"]),
            ).fetchone()[0]
        assert transitions == 1


def test_retrospective_report_rest_reuses_one_claim_receipt_and_markdown(
    client_factory,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, vault)
        payload = {"days": 7}

        first = client.post("/api/memory/retrospectives/report", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/retrospectives/report", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        rows = _action_rows(client, "wiki.retrospective_report.write")
        assert len(rows) == 1
        response = first.json()
        report_path = vault.joinpath(*str(response["page"]["relative_path"]).split("/"))
        markdown = report_path.read_text(encoding="utf-8")
        assert markdown.count("<!-- llmwiki-retrospective-report ") == 1
        assert f"action_id={response['action']['action_id']}" in markdown
        assert len(list((vault / "Wiki" / "Companion" / "Reports").glob("*.md"))) == 1


def test_retrospective_report_recovers_effect_before_receipt_from_bound_markdown(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._retrospective_report_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after retrospective Markdown commit")

        return execute

    monkeypatch.setattr(adapters, "_retrospective_report_adapter", interrupted_factory)

    vault = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _bind_vault(client, vault)
        payload = {"period": "weekly"}

        first = client.post("/api/memory/retrospectives/report", headers=auth_headers(), json=payload)
        second = client.post("/api/memory/retrospectives/report", headers=auth_headers(), json=payload)

        assert first.status_code == 200
        assert second.json() == first.json()
        assert calls == 1
        rows = _action_rows(client, "wiki.weekly_report.write")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        receipt = metadata["execution_receipt"]
        assert receipt["status"] == "verified"
        assert receipt["result"]["recovered_from_authoritative_state"] is True
        report_path = vault.joinpath(*str(first.json()["page"]["relative_path"]).split("/"))
        markdown = report_path.read_text(encoding="utf-8")
        assert markdown.count("<!-- llmwiki-retrospective-report ") == 1
        assert f"action_id={first.json()['action']['action_id']}" in markdown
        assert len(list((vault / "Wiki" / "Companion" / "Reports").glob("*.md"))) == 1


def test_continuity_rest_mutations_use_one_claim_receipt_and_one_domain_event(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory(data_dir=tmp_path / "data") as client:
        confirmed_id = _create_continuity_proposal(client, "I feel tired today.")
        rejected_id = _create_continuity_proposal(client, "I feel lonely tonight.")

        first_confirm = client.post(
            f"/api/continuity/proposals/{confirmed_id}/confirm",
            headers=auth_headers(),
        )
        second_confirm = client.post(
            f"/api/continuity/proposals/{confirmed_id}/confirm",
            headers=auth_headers(),
        )
        reject_payload = {"reason": "not a durable state"}
        first_reject = client.post(
            f"/api/continuity/proposals/{rejected_id}/reject",
            headers=auth_headers(),
            json=reject_payload,
        )
        second_reject = client.post(
            f"/api/continuity/proposals/{rejected_id}/reject",
            headers=auth_headers(),
            json=reject_payload,
        )

        assert first_confirm.status_code == 200
        assert second_confirm.json() == first_confirm.json()
        assert first_confirm.json() == {"proposal_id": confirmed_id, "status": "confirmed"}
        assert first_reject.status_code == 200
        assert second_reject.json() == first_reject.json()
        assert first_reject.json() == {"proposal_id": rejected_id, "status": "rejected"}
        assert len(_action_rows(client, "continuity.proposal.confirm")) == 1
        assert len(_action_rows(client, "continuity.proposal.reject")) == 1
        with sqlite3.connect(client.app.state.database.path) as conn:
            events = conn.execute(
                """
                SELECT proposal_id, action, COUNT(*)
                FROM continuity_events
                WHERE proposal_id IN (?, ?) AND action IN ('confirmed', 'rejected')
                GROUP BY proposal_id, action
                ORDER BY proposal_id
                """,
                (confirmed_id, rejected_id),
            ).fetchall()
        assert sorted((proposal_id, action, count) for proposal_id, action, count in events) == sorted(
            [(confirmed_id, "confirmed", 1), (rejected_id, "rejected", 1)]
        )


def test_continuity_confirm_recovers_effect_before_receipt_from_sqlite(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = adapters._continuity_confirm_adapter
    calls = 0

    def interrupted_factory(request):
        inner = original_factory(request)

        async def execute(proposal, policy, claim):
            nonlocal calls
            await inner(proposal, policy, claim)
            calls += 1
            raise RuntimeError("receipt interrupted after continuity commit")

        return execute

    monkeypatch.setattr(adapters, "_continuity_confirm_adapter", interrupted_factory)

    with client_factory(data_dir=tmp_path / "data") as client:
        proposal_id = _create_continuity_proposal(client, "I feel tired today.")

        first = client.post(
            f"/api/continuity/proposals/{proposal_id}/confirm",
            headers=auth_headers(),
        )
        second = client.post(
            f"/api/continuity/proposals/{proposal_id}/confirm",
            headers=auth_headers(),
        )

        assert first.status_code == 200
        assert second.json() == first.json() == {"proposal_id": proposal_id, "status": "confirmed"}
        assert calls == 1
        rows = _action_rows(client, "continuity.proposal.confirm")
        assert len(rows) == 1
        metadata = json.loads(str(rows[0]["metadata_json"]))
        assert metadata["execution_receipt"]["status"] == "verified"
        assert metadata["execution_receipt"]["result"]["recovered_from_authoritative_state"] is True
        with sqlite3.connect(client.app.state.database.path) as conn:
            event_count = conn.execute(
                "SELECT COUNT(*) FROM continuity_events WHERE proposal_id = ? AND action = 'confirmed'",
                (proposal_id,),
            ).fetchone()[0]
        assert event_count == 1
