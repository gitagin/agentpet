from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from app.agents.contracts import reflection_wiki_summary_target
from app.services.reflection_proposals import (
    APPLIED,
    PENDING,
    REJECTED,
    ReflectionProposalService,
)

AUTH = {"Authorization": "Bearer test-token"}


def _init_vault(client: TestClient, root: Path) -> None:
    response = client.post(
        "/api/vaults/init",
        headers=AUTH,
        json={"path": str(root), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200, response.text


def _seed_proposal(
    client: TestClient,
    *,
    content: str = "用户偏好用 VS Code 写 Python。",
    proposal_kind: str = "structured_memory",
    action_type: str = "diary.structured_memory",
    target_ref: str | None = None,
) -> str:
    service = ReflectionProposalService(client.app.state.database.path)
    try:
        record = service.record(
            proposal_kind=proposal_kind,
            action_type=action_type,
            target_ref=target_ref,
            content=content,
            confidence=0.8,
            status=PENDING,
            source_conversation_id="conversation-1",
            source_message_id="message-1",
            agent_run_id="run-1",
        )
        return record.id
    finally:
        service.close()


def _memory_proposals(client: TestClient) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute("SELECT * FROM memory_proposals ORDER BY created_at"))


def _reflection_row(client: TestClient, proposal_id: str) -> sqlite3.Row:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM reflection_proposals WHERE id = ?", (proposal_id,)
        ).fetchone()


def test_listing_returns_pending_proposals(client_factory, tmp_path: Path) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)

        response = client.get("/api/reflection/proposals", headers=AUTH)

        assert response.status_code == 200, response.text
        proposals = response.json()["proposals"]
        assert [item["proposal_id"] for item in proposals] == [proposal_id]
        assert proposals[0]["content"] == "用户偏好用 VS Code 写 Python。"
        assert proposals[0]["status"] == PENDING
        assert proposals[0]["source_message_id"] == "message-1"


def test_confirming_a_proposal_creates_and_confirms_a_memory_proposal(
    client_factory,
    tmp_path: Path,
) -> None:
    # 一步到位:一次用户决定产生一次真实效果(记忆提案已确认写入 Markdown)。
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["proposal_id"] == proposal_id
        assert body["status"] == APPLIED
        assert body["memory_proposal_id"]

        rows = _memory_proposals(client)
        assert len(rows) == 1
        assert rows[0]["id"] == body["memory_proposal_id"]
        assert rows[0]["content"] == "用户偏好用 VS Code 写 Python。"
        assert rows[0]["status"] == "confirmed"
        assert rows[0]["target_path"].endswith("Pending Memories.md")

        applied = _reflection_row(client, proposal_id)
        assert applied["status"] == APPLIED
        assert applied["applied_ref"] == body["memory_proposal_id"]

        # 已处理的建议不再出现在待审阅列表里。
        assert client.get("/api/reflection/proposals", headers=AUTH).json()["proposals"] == []


def test_confirming_wiki_summary_writes_wiki_without_creating_memory_proposal(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory() as client:
        vault_root = tmp_path / "vault"
        _init_vault(client, vault_root)
        content = "显式知识库范围必须由检索参数强制执行。"
        target_ref = reflection_wiki_summary_target(content)
        proposal_id = _seed_proposal(
            client,
            content=content,
            proposal_kind="wiki_summary",
            action_type="wiki.answer_summary.write",
            target_ref=target_ref,
        )

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == APPLIED
        assert body["memory_proposal_id"] is None
        assert _memory_proposals(client) == []
        page = vault_root / Path(target_ref)
        assert page.exists()
        assert content in page.read_text(encoding="utf-8")
        row = _reflection_row(client, proposal_id)
        assert row["applied_ref"] == target_ref


def test_confirm_rejects_tampered_wiki_target_before_any_effect(client_factory, tmp_path: Path) -> None:
    with client_factory() as client:
        vault_root = tmp_path / "vault"
        _init_vault(client, vault_root)
        content = "这条摘要不能写到被篡改的目标。"
        proposal_id = _seed_proposal(
            client,
            content=content,
            proposal_kind="wiki_summary",
            action_type="wiki.answer_summary.write",
            target_ref="Wiki/Companion/Summaries/Tampered.md",
        )

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "reflection_proposal_state_conflict"
        assert _memory_proposals(client) == []
        assert not (vault_root / "Wiki" / "Companion" / "Summaries" / "Tampered.md").exists()


def test_confirm_rejects_stored_kind_action_mismatch_before_any_effect(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.execute(
                "UPDATE reflection_proposals SET action_type = ? WHERE id = ?",
                ("wiki.answer_summary.write", proposal_id),
            )
            conn.commit()

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "reflection_proposal_state_conflict"
        assert _memory_proposals(client) == []


def test_confirming_twice_is_a_state_conflict_not_a_second_effect(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)
        assert client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH).status_code == 200

        second = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert second.status_code == 409
        assert second.json()["error"]["code"] == "reflection_proposal_state_conflict"
        assert len(_memory_proposals(client)) == 1


def test_rejecting_a_proposal_records_the_reason_without_memory_effect(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)

        response = client.post(
            f"/api/reflection/proposals/{proposal_id}/reject",
            headers=AUTH,
            json={"reason": "不需要记这个"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == REJECTED
        assert _memory_proposals(client) == []
        row = _reflection_row(client, proposal_id)
        assert row["status"] == REJECTED
        assert row["rejected_reason"] == "不需要记这个"


def test_unknown_proposal_is_not_found(client_factory, tmp_path: Path) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")

        response = client.post("/api/reflection/proposals/no-such-proposal/confirm", headers=AUTH)

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "reflection_proposal_not_found"


def test_an_off_contract_stored_kind_does_not_break_the_whole_list(
    client_factory,
    tmp_path: Path,
) -> None:
    # 读取路径不假设库里的取值一定合契约:一行坏数据只该照原样显示,
    # 不该让整张队列 500。
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.execute(
                "UPDATE reflection_proposals SET proposal_kind = ? WHERE id = ?",
                ("something_else", proposal_id),
            )
            conn.commit()

        response = client.get("/api/reflection/proposals", headers=AUTH)

        assert response.status_code == 200, response.text
        assert response.json()["proposals"][0]["proposal_kind"] == "something_else"


def _mark_failed(client: TestClient, proposal_id: str, *, error: str = "reflection_execution_failed") -> None:
    service = ReflectionProposalService(client.app.state.database.path)
    try:
        service.claim_for_apply(proposal_id)
        service.mark_failed(proposal_id, error=error)
    finally:
        service.close()


def test_attention_queue_shows_a_failed_proposal_the_user_can_retry(
    client_factory,
    tmp_path: Path,
) -> None:
    # 系统失败不是"已处理":它必须留在用户看得见的队列里,否则建议静默消失。
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        pending_id = _seed_proposal(client, content="待决定")
        failed_id = _seed_proposal(client, content="执行失败")
        _mark_failed(client, failed_id)

        response = client.get("/api/reflection/proposals?status=attention", headers=AUTH)

        assert response.status_code == 200, response.text
        by_id = {item["proposal_id"]: item["status"] for item in response.json()["proposals"]}
        assert by_id == {pending_id: PENDING, failed_id: "failed"}


def test_confirming_a_failed_proposal_re_runs_the_apply(
    client_factory,
    tmp_path: Path,
) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        proposal_id = _seed_proposal(client)
        _mark_failed(client, proposal_id)

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == APPLIED
        row = _reflection_row(client, proposal_id)
        assert row["status"] == APPLIED
        assert row["apply_attempts"] == 2
        assert len(_memory_proposals(client)) == 1


def test_confirming_a_failed_wiki_summary_refuses_a_second_apply(
    client_factory,
    tmp_path: Path,
) -> None:
    # Wiki 摘要的效果按尝试身份追加,换身份重试会重复追加:接口必须明确拒绝,
    # 而不是让用户点一个会产生重复日志的按钮。
    with client_factory() as client:
        _init_vault(client, tmp_path / "vault")
        content = "这次对话值得写成一条摘要。"
        proposal_id = _seed_proposal(
            client,
            content=content,
            proposal_kind="wiki_summary",
            action_type="wiki.answer_summary.write",
            target_ref=reflection_wiki_summary_target(content),
        )
        _mark_failed(client, proposal_id, error="wiki_page_conflict")

        response = client.post(f"/api/reflection/proposals/{proposal_id}/confirm", headers=AUTH)

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "reflection_proposal_state_conflict"
