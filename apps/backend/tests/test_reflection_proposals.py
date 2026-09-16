from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from apps.backend.tests._schema import migrate_db
from app.services.reflection_proposals import (
    APPLIED,
    APPLYING,
    ATTENTION_STATUSES,
    DENIED,
    FAILED,
    MAX_APPLY_ATTEMPTS,
    PENDING,
    REJECTED,
    ReflectionProposalNotFoundError,
    ReflectionProposalService,
    ReflectionProposalStateError,
    reflection_proposal_hash,
)


def _service(tmp_path: Path) -> ReflectionProposalService:
    return ReflectionProposalService(migrate_db(tmp_path / "state.sqlite3"))


def _record(service: ReflectionProposalService, *, content: str = "用户偏好 VS Code。", **overrides):
    payload = {
        "proposal_kind": "structured_memory",
        "action_type": "diary.structured_memory",
        "content": content,
        "confidence": 0.8,
        "status": PENDING,
        "source_conversation_id": "conversation-1",
        "source_message_id": "message-1",
        "agent_run_id": "run-1",
    }
    payload.update(overrides)
    return service.record(**payload)


def test_proposal_identity_is_content_derived_not_per_turn(tmp_path: Path) -> None:
    # 身份不含 source_message_id / agent_run_id:同一建议在下一轮再被提出时,
    # 必须映射到同一行,否则用户拒绝过的建议每轮都会重新出现。
    service = _service(tmp_path)
    try:
        first = _record(service, source_message_id="message-1", agent_run_id="run-1")
        same = _record(service, source_message_id="message-2", agent_run_id="run-2")

        assert same.id == first.id
        assert len(service.list_proposals()) == 1
        # 首次出现的时间与来源被保留:那是最有用的溯源信息。
        assert same.source_message_id == "message-1"
        assert same.agent_run_id == "run-1"
    finally:
        service.close()


def test_identity_differs_by_kind_action_and_wording(tmp_path: Path) -> None:
    assert reflection_proposal_hash(
        proposal_kind="structured_memory", action_type="diary.structured_memory", content="甲"
    ) != reflection_proposal_hash(
        proposal_kind="daily_diary", action_type="diary.structured_memory", content="甲"
    )
    assert reflection_proposal_hash(
        proposal_kind="structured_memory", action_type="diary.structured_memory", content="甲"
    ) != reflection_proposal_hash(
        proposal_kind="structured_memory", action_type="diary.structured_memory", content="乙"
    )
    # 空白差异不算不同建议。
    assert reflection_proposal_hash(
        proposal_kind="structured_memory", action_type="diary.structured_memory", content="用 户"
    ) == reflection_proposal_hash(
        proposal_kind="structured_memory", action_type="diary.structured_memory", content="用  户"
    )


def test_re_recording_never_resurrects_a_decision(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        first = _record(service)
        service.reject(first.id, "不需要记这个")

        again = _record(service)

        assert again.id == first.id
        assert again.status == REJECTED
        assert again.rejected_reason == "不需要记这个"
    finally:
        service.close()


def test_reject_is_idempotent_and_applied_requires_pending(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        first = _record(service)
        service.reject(first.id, "不要")

        assert service.reject(first.id, "不要").status == REJECTED
        with pytest.raises(ReflectionProposalStateError):
            service.mark_applied(first.id, applied_ref="candidate-1")
    finally:
        service.close()


def test_confirm_path_records_applied_reference(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        pending = _record(service)
        applied = service.mark_applied(pending.id, applied_ref="candidate-1")

        assert applied.status == APPLIED
        assert applied.applied_ref == "candidate-1"
        assert service.list_proposals(statuses=(PENDING,)) == []
        assert [item.id for item in service.list_proposals(statuses=(APPLIED,))] == [pending.id]
    finally:
        service.close()


def test_failed_proposal_keeps_its_reason(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        pending = _record(service)
        failed = service.mark_failed(pending.id, error="reflection_execution_failed")

        assert failed.status == "failed"
        assert failed.error == "reflection_execution_failed"
    finally:
        service.close()


def test_denied_proposals_are_stored_but_never_pending(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        denied = _record(service, status=DENIED, error="unknown_action_type")

        assert denied.status == DENIED
        assert denied.error == "unknown_action_type"
        assert service.list_proposals(statuses=(PENDING,)) == []
    finally:
        service.close()


def test_unknown_status_is_rejected_loudly(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        with pytest.raises(ValueError):
            _record(service, status="whatever")
    finally:
        service.close()


def test_missing_proposal_raises_not_found(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        with pytest.raises(ReflectionProposalNotFoundError):
            service.get("no-such-proposal")
    finally:
        service.close()


def test_claim_for_apply_is_compare_and_set(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        pending = _record(service)
        claimed = service.claim_for_apply(pending.id)
        assert claimed.status == APPLYING
        with pytest.raises(ReflectionProposalStateError):
            service.claim_for_apply(pending.id)
        applied = service.mark_applied(pending.id, applied_ref="effect-1")
        assert applied.status == APPLIED
    finally:
        service.close()


def test_concurrent_claimers_allow_only_one_confirm_path(tmp_path: Path) -> None:
    db_path = migrate_db(tmp_path / "state.sqlite3")
    seed = ReflectionProposalService(db_path)
    try:
        pending = _record(seed)
    finally:
        seed.close()

    def claim() -> str:
        service = ReflectionProposalService(db_path)
        try:
            return service.claim_for_apply(pending.id).status
        except ReflectionProposalStateError:
            return "conflict"
        finally:
            service.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))

    assert sorted(results) == ["applying", "conflict"]


def test_failed_apply_is_retryable_within_budget(tmp_path: Path) -> None:
    # 系统失败不是用户的决定:它必须能重来,而且重来要换尝试身份(attempts 递增),
    # 否则动作账本会按原幂等键回放失败回执,重试等于什么都不做。
    service = _service(tmp_path)
    try:
        pending = _record(service)
        first = service.claim_for_apply(pending.id)
        assert first.apply_attempts == 1

        failed = service.mark_failed(pending.id, error="reflection_execution_failed")
        assert failed.status == FAILED

        retried = service.claim_for_apply(pending.id)
        assert retried.status == APPLYING
        assert retried.apply_attempts == 2
    finally:
        service.close()


def test_re_recording_a_failed_proposal_keeps_its_retry_budget(tmp_path: Path) -> None:
    # 同一建议会被反复重提:重提不能把用掉的预算清零,否则永久性失败每轮都会重来。
    service = _service(tmp_path)
    try:
        pending = _record(service)
        service.claim_for_apply(pending.id)
        service.mark_failed(pending.id, error="reflection_execution_failed")

        re_recorded = _record(service)

        assert re_recorded.id == pending.id
        assert re_recorded.status == FAILED
        assert re_recorded.apply_attempts == 1
    finally:
        service.close()


def test_apply_retry_stops_at_the_budget(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        pending = _record(service)
        for _ in range(MAX_APPLY_ATTEMPTS):
            service.claim_for_apply(pending.id)
            service.mark_failed(pending.id, error="reflection_execution_failed")

        assert service.get(pending.id).apply_attempts == MAX_APPLY_ATTEMPTS
        with pytest.raises(ReflectionProposalStateError):
            service.claim_for_apply(pending.id)
    finally:
        service.close()


def test_wiki_summary_apply_is_never_retried_under_a_new_identity(tmp_path: Path) -> None:
    # Wiki 摘要的效果是按尝试身份追加的日志行:换身份重试会重复追加,所以它不是
    # 可重试的失败,只能由用户忽略。
    service = _service(tmp_path)
    try:
        pending = _record(
            service,
            proposal_kind="wiki_summary",
            action_type="wiki.answer_summary.write",
        )
        service.claim_for_apply(pending.id)
        service.mark_failed(pending.id, error="wiki_page_conflict")

        with pytest.raises(ReflectionProposalStateError):
            service.claim_for_apply(pending.id)
    finally:
        service.close()


def test_attention_queue_holds_pending_and_failed_but_not_user_decisions(tmp_path: Path) -> None:
    service = _service(tmp_path)
    try:
        pending = _record(service, content="待决定")
        broken = _record(service, content="执行失败")
        service.claim_for_apply(broken.id)
        service.mark_failed(broken.id, error="reflection_execution_failed")
        rejected = _record(service, content="已被忽略")
        service.reject(rejected.id, reason="不要再提")

        attention = service.list_proposals(statuses=ATTENTION_STATUSES)

        assert {item.content for item in attention} == {"待决定", "执行失败"}
        assert service.list_proposals(statuses=(REJECTED,)) == [service.get(rejected.id)]
    finally:
        service.close()
