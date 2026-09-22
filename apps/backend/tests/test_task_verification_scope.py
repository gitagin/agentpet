"""t33:动作校验期望状态的**范围**回归(不依赖负载的确定性证据)。

背景(根因,见 t26 报告):
    `task.create` 的校验期望曾包含 `reminder_status` —— 一个由**调度器拥有、会合法变更**的字段。
    校验要求「执行时记录的值 == 校验时读到的值」,而调度器会在提醒到期时**自主**把
    `scheduled` 改为 `triggered` ⇒ 提醒只要落在「执行 → 校验」窗口内到期就必然 mismatch
    ⇒ `RuntimeError("action_lifecycle_verification_mismatch")` ⇒ `POST /api/tasks` 返回 500,
    **而动作其实已经生效**(任务与提醒都已落库、提醒已触发) ⇒ 调用方据 500 重试可能重复创建。

本测试在**真实路径**上钉住修复后的契约:
    ① 校验期望(`expected_state` / `after_snapshot`)**不含**调度器拥有的字段;
    ② 记录(`result`)仍**保留** `reminder_status` ⇒ 调用方读取与 API 响应不变;
    ③ 正常创建的动作校验**通过**(`error` 为 None)。

**它不依赖 CPU 负载** ⇒ 可作为「修复改变了根因」的**确定性**证据;
与「负载下跑原 flaky 用例」互为补充(后者见 t33 报告 §5.3)。
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tests.conftest import auth_headers

#: 由**时间驱动子系统**(提醒调度器)拥有的状态字段 —— 不得进入校验期望。
SCHEDULER_OWNED = ("reminder_status", "reminder_states", "triggered_at")


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory(session_token="t33-token") as test_client:
        yield test_client


def _auth(request_id: str) -> dict[str, str]:
    return auth_headers("t33-token", request_id=request_id)


def _task_create_receipt(client: TestClient) -> dict:
    """返回最近一条 `task.create` 动作的回执(从动作账本读取,不经 API)。"""
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT metadata_json FROM agent_actions WHERE action_type = ? ORDER BY created_at DESC LIMIT 1",
            ("task.create",),
        ).fetchone()
    assert row is not None, "未找到 task.create 动作"
    metadata = json.loads(row["metadata_json"])
    receipt = metadata.get("execution_receipt")
    assert isinstance(receipt, dict), "回执缺失"
    return receipt


def test_task_create_verification_excludes_scheduler_owned_state(client: TestClient) -> None:
    """核心回归:调度器拥有的字段**不得**进入校验期望,但**必须**仍留在记录里。"""
    remind_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    response = client.post(
        "/api/tasks",
        headers=_auth("t33-verify-scope"),
        json={"title": "t33 scope", "remind_at": remind_at, "timezone": "UTC"},
    )
    assert response.status_code == 200, response.text

    receipt = _task_create_receipt(client)
    result = receipt.get("result") or {}
    expected_state = result.get("expected_state") or {}
    after_snapshot = receipt.get("after_snapshot") or {}

    # ① 校验期望不含调度器拥有的字段(两个取值路径都要覆盖 —— 验证器优先取 result.expected_state)
    for field in SCHEDULER_OWNED:
        assert field not in expected_state, f"{field} 不得进入校验期望(result.expected_state)"
        assert field not in after_snapshot, f"{field} 不得进入校验期望(after_snapshot)"

    # ② 记录仍保留提醒的创建时状态 ⇒ 调用方读取与 API 响应不变
    assert result.get("reminder_status") == "scheduled"
    assert response.json()["metadata"].get("reminder_status") == "scheduled"

    # ③ 本动作的校验**通过**(修复前:若提醒在窗口内到期,这里会是 failed_recovery)
    assert receipt.get("status") == "verified"
    assert receipt.get("safe_error_code") is None


def test_task_create_verification_still_checks_owned_fields(client: TestClient) -> None:
    """校验力未被削弱的**对照**:本动作拥有的字段仍在期望内,故仍会被比对。"""
    remind_at = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    response = client.post(
        "/api/tasks",
        headers=_auth("t33-owned-fields"),
        json={"title": "t33 owned", "remind_at": remind_at, "timezone": "UTC"},
    )
    assert response.status_code == 200, response.text

    expected_state = (_task_create_receipt(client).get("result") or {}).get("expected_state") or {}

    # 这些是**本动作的效果**(创建事实 / 仅显式并发动作可改),必须仍在校验内。
    for field in ("task_id", "title", "status", "due_at", "target_ref",
                  "reminder_id", "remind_at", "timezone", "timezone_label"):
        assert field in expected_state, f"{field} 属于本动作拥有的字段,不得被移出校验"
