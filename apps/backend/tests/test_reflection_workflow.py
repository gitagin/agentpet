from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from tests.agent_runtime_fakes import make_state

from app.agents.contracts import (
    ReflectionProposal,
    ReflectionProposalBatch,
    reflection_wiki_summary_target,
)
from app.agents.reflection_graph import (
    REFLECTION_RESULT_RETENTION,
    ReflectionJobInput,
    ReflectionJobManager,
    ReflectionJobRunner,
    deterministic_reflection_job_id,
)
from app.agents.roles import reflection_agent
from app.agents.roles.reflection_agent import (
    MAX_REFLECTION_PROPOSALS,
    normalize_reflection_batch,
)
from app.models.enums import AgentRunStatus


def _done_state(message: str):
    state = make_state(message)
    state.status = AgentRunStatus.SUCCESS
    return state


def _batch(*, proposal_id: str = "proposal:reflection:1") -> ReflectionProposalBatch:
    return ReflectionProposalBatch(
        proposals=(
            ReflectionProposal(
                proposal_id=proposal_id,
                source_message_id="message-1",
                proposal_kind="daily_diary",
                action_type="chat.daily_archive",
                target_ref=None,
                content="A bounded reflection proposal.",
                confidence=0.95,
                reversible=True,
            ),
        )
    )


def test_reflection_starts_only_from_bounded_projection_and_routes_low_risk_proposal() -> None:
    calls: list[dict] = []
    executions: list[str] = []

    async def reflector(projection):
        calls.append(projection)
        return _batch()

    async def executor(proposal):
        executions.append(proposal.proposal_id)

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("please remember this safe preference"),
                assistant_answer="A concise answer.",
                reflector=reflector,
                executor=executor,
            )
        )
    )

    assert run.state.status == "completed"
    assert run.state.model_calls == 1
    assert run.state.proposal_results[0].status == "executed"
    assert executions == ["proposal:reflection:1"]
    assert calls[0]["schema_version"] == "reflection-input.v1"
    assert set(calls[0]) == {
        "schema_version",
        "source_message_id",
        "source_agent_run_id",
        "user_message",
        "assistant_answer",
        "approved_action_refs",
    }


def test_reflection_contract_rejects_kind_action_mismatch() -> None:
    with pytest.raises(ValidationError, match="reflection_proposal_action_mismatch"):
        ReflectionProposal(
            proposal_id="proposal:reflection:invalid-action",
            source_message_id="message-1",
            proposal_kind="daily_diary",
            action_type="markdown.delete",
            target_ref=None,
            content="A bounded reflection proposal.",
            confidence=0.95,
            reversible=True,
        )


def test_local_privacy_or_sensitive_input_makes_zero_reflection_model_calls() -> None:
    calls = 0

    async def reflector(_projection):
        nonlocal calls
        calls += 1
        return _batch()

    private_state = _done_state("api_key=private-value-123456")
    private_state.local_privacy_mode = True
    private_state.local_privacy_sensitive_reason = "credential"
    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=private_state,
                assistant_answer="I will not retain this.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "skipped"
    assert run.state.safe_error_code == "sensitive_or_private_input"
    assert calls == 0


def test_reflection_before_foreground_done_is_skipped_without_model_call() -> None:
    calls = 0

    async def reflector(_projection):
        nonlocal calls
        calls += 1
        return _batch()

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=make_state("not done yet"),
                assistant_answer="Partial.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "skipped"
    assert run.state.safe_error_code == "foreground_not_done"
    assert calls == 0


def test_reflection_provider_failure_is_background_only_and_safe() -> None:
    async def reflector(_projection):
        raise RuntimeError("provider failure with private path C:\\Users\\Ada\\Vault\\Secret.md")

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("summarize this"),
                assistant_answer="Done.",
                reflector=reflector,
            )
        )
    )

    assert run.state.status == "failed"
    assert run.state.safe_error_code == "reflection_failed"
    assert run.state.proposal_results == ()


def test_reflection_manager_deduplicates_source_message_and_cancels_owned_jobs() -> None:
    gate = asyncio.Event()

    async def reflector(_projection):
        await gate.wait()
        return _batch()

    async def run_case():
        manager = ReflectionJobManager()
        payload = ReflectionJobInput(
            state=_done_state("deduplicate this"),
            assistant_answer="Done.",
            reflector=reflector,
        )
        first = manager.start(payload)
        second = manager.start(payload)
        await asyncio.sleep(0)
        await manager.shutdown()
        return first, second, manager

    first, second, manager = asyncio.run(run_case())

    assert first is second
    assert first is not None and first.cancelled()
    assert manager.get(deterministic_reflection_job_id("message-1")) is None


def test_reflection_job_id_changes_with_policy_version() -> None:
    assert deterministic_reflection_job_id("message-1") != deterministic_reflection_job_id(
        "message-1", "reflection-policy.v2"
    )


class _CompleteOnlyModel:
    """与生产同形:项目自己的模型客户端只承诺 complete()。"""

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append((user_message, system_prompt))
        return self.text


def test_reflection_reads_json_from_a_complete_only_client() -> None:
    # 线上失败形态:反思角色拿到的是只有 complete() 的项目客户端,却被要求支持
    # provider 侧的 output schema 绑定,于是必然抛 TypeError(9/9 全败)。
    # 现在走"提示词约定 JSON + 本地校验",不依赖任何 provider 能力。
    model = _CompleteOnlyModel(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_kind": "structured_memory",
                        "action_type": "diary.structured_memory",
                        "content": "用户偏好 VS Code。",
                        "confidence": 0.9,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("remember my editor preference"),
                assistant_answer="Noted.",
                model=model,
            )
        )
    )

    assert run.state.status == "done_with_pending"
    assert run.state.model_calls == 1
    proposal = run.proposals.proposals[0]
    assert proposal.content == "用户偏好 VS Code。"
    assert proposal.proposal_id.startswith("proposal:")
    assert proposal.source_message_id == "message-1"
    # 没有执行器 => 转入审阅队列,而不是记成 failed/executor_unavailable。
    assert run.state.proposal_results[0].status == "pending_confirmation"
    assert run.state.proposal_results[0].reason_code == "reflection_review_required"
    assert "reflection-proposal-batch.v1" in model.calls[0][0]
    assert model.calls[0][1] == reflection_agent.REFLECTION_SYSTEM_PROMPT


def test_normalize_replaces_model_identity_and_drops_unusable_items() -> None:
    payload = {
        "proposals": [
            {
                "proposal_id": "!!! not a valid id !!!",
                "source_message_id": "wrong-message",
                "proposal_kind": "structured_memory",
                "action_type": "Diary.Structured_Memory",
                "content": "  用户偏好 VS Code。  ",
                "confidence": 1.7,
            },
            {"proposal_kind": "structured_memory", "action_type": "x.y", "content": "   "},
            "not-a-dict",
            {"proposal_kind": "not_a_kind", "action_type": "x.y", "content": "坏的类型"},
        ]
    }

    batch = normalize_reflection_batch(payload, projection={"source_message_id": "message-1"})

    assert len(batch.proposals) == 1
    proposal = batch.proposals[0]
    assert proposal.proposal_id.startswith("proposal:")
    assert proposal.source_message_id == "message-1"
    assert proposal.content == "用户偏好 VS Code。"
    assert proposal.confidence == 1.0
    assert proposal.action_type == "diary.structured_memory"


def test_normalize_assigns_wiki_summary_target_server_side() -> None:
    content = "把这轮关于检索范围的结论整理成 Wiki 摘要。"
    batch = normalize_reflection_batch(
        {
            "proposals": [
                {
                    "proposal_kind": "wiki_summary",
                    "target_ref": None,
                    "content": content,
                    "confidence": 0.91,
                }
            ]
        },
        projection={"source_message_id": "message-1"},
    )

    assert len(batch.proposals) == 1
    proposal = batch.proposals[0]
    assert proposal.action_type == "wiki.answer_summary.write"
    assert proposal.target_ref == reflection_wiki_summary_target(content)


def test_normalize_deduplicates_identity_and_enforces_the_budget() -> None:
    first = {"proposal_kind": "structured_memory", "action_type": "a.b", "content": "建议 0"}
    rest = [
        {"proposal_kind": "structured_memory", "action_type": "a.b", "content": f"建议 {index}"}
        for index in range(1, 6)
    ]

    batch = normalize_reflection_batch(
        {"proposals": [first, dict(first), *rest]},
        projection={"source_message_id": "message-1"},
    )

    assert len(batch.proposals) == MAX_REFLECTION_PROPOSALS
    assert len({proposal.proposal_id for proposal in batch.proposals}) == MAX_REFLECTION_PROPOSALS


def test_normalize_requires_an_object_payload() -> None:
    # 完全不是 JSON 对象时按"没有建议"处理,而不是崩掉整个后台任务。
    assert normalize_reflection_batch("not json", projection={"source_message_id": "m"}).proposals == ()
    assert normalize_reflection_batch({}, projection={"source_message_id": "m"}).proposals == ()


def test_unknown_kind_on_an_otherwise_valid_item_still_validates_strictly() -> None:
    batch = normalize_reflection_batch(
        {
            "proposals": [
                {"proposal_kind": "daily_diary", "action_type": "a.b", "content": "有效建议"}
            ]
        },
        projection={"source_message_id": "m"},
    )
    assert batch.proposals[0].proposal_kind == "daily_diary"
    with pytest.raises(ValidationError):
        ReflectionProposal.model_validate(
            {
                "proposal_id": "proposal:x",
                "source_message_id": "m",
                "proposal_kind": "not_a_kind",
                "action_type": "a.b",
                "content": "x",
                "confidence": 0.5,
            }
        )


def test_reflection_records_the_finished_run_and_contains_recorder_failure() -> None:
    recorded: list = []

    async def reflector(_projection):
        return _batch()

    def recorder(run):
        recorded.append(run)

    run = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("record this"),
                assistant_answer="Done.",
                reflector=reflector,
                recorder=recorder,
            )
        )
    )

    assert recorded == [run]

    def failing_recorder(_run):
        raise RuntimeError("queue unavailable")

    contained = asyncio.run(
        ReflectionJobRunner().run(
            ReflectionJobInput(
                state=_done_state("record this too"),
                assistant_answer="Done.",
                reflector=reflector,
                recorder=failing_recorder,
            )
        )
    )

    # 记录失败不能把一批可用建议变成失败任务。
    assert contained.state.status == "done_with_pending"


def test_reflection_recorder_persists_rows_into_the_review_queue(client_factory) -> None:
    # 端到端:路由结论真的落进 reflection_proposals,审阅队列里有东西可看。
    with client_factory() as client:
        import app.services.chat_pipeline as pipeline
        from app.api.wiring import AppContext
        from app.services.reflection_proposals import PENDING, ReflectionProposalService

        async def reflector(_projection):
            return _batch()

        run = asyncio.run(
            ReflectionJobRunner().run(
                ReflectionJobInput(
                    state=_done_state("queue this"),
                    assistant_answer="Done.",
                    reflector=reflector,
                )
            )
        )
        recorder = pipeline.reflection_recorder(
            AppContext(app=client.app),
            conversation_id="conversation-1",
        )
        recorder(run)

        service = ReflectionProposalService(client.app.state.database.path)
        try:
            pending = service.list_proposals(statuses=(PENDING,))
        finally:
            service.close()

        assert len(pending) == 1
        assert pending[0].content == "A bounded reflection proposal."
        assert pending[0].proposal_kind == "daily_diary"
        assert pending[0].source_message_id == "message-1"
        assert pending[0].agent_run_id == run.state.source_agent_run_id
        assert pending[0].source_conversation_id == "conversation-1"


def test_finished_reflection_jobs_do_not_accumulate_in_memory() -> None:
    # 每轮回复都会起一个反思任务,而每个结果都握着一份深拷贝的对话。无上限地留住
    # 已完成的运行会让常驻内存随对话历史一起涨。
    async def reflector(_projection):
        return ReflectionProposalBatch()

    async def run_case():
        manager = ReflectionJobManager()
        for index in range(REFLECTION_RESULT_RETENTION + 5):
            state = _done_state(f"message {index}")
            state.message_id = f"message-{index}"
            task = manager.start(
                ReflectionJobInput(state=state, assistant_answer="Done.", reflector=reflector)
            )
            assert task is not None
            await task
        return manager

    manager = asyncio.run(run_case())

    assert len(manager._results) == REFLECTION_RESULT_RETENTION
    assert manager._tasks == {}
    assert manager.get(deterministic_reflection_job_id(f"message-{REFLECTION_RESULT_RETENTION + 4}")) is not None
    assert manager.get(deterministic_reflection_job_id("message-0")) is None
