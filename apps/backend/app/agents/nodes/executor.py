from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import sqlite3
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import ValidationError

from app.models.api import AgentActionResponse
from app.services.agent_actions import AgentActionCreate

from ..contracts import (
    ActionProposal,
    ExecutionClaim,
    ExecutionReceipt,
    PolicyDecision,
    VerificationResult,
)
from ..roles.verifier_agent import verify_execution_receipt

logger = logging.getLogger(__name__)


# A process-level owner lets request-scoped runtimes share one execution
# namespace while still allowing a new sidecar process to recover a stale
# claim after a crash.  The database remains the authority; this value is
# only used to distinguish an in-flight local execution from a stale one.
# The owner is durable metadata used to distinguish a live request process
# from a process that disappeared.  It is not an idempotency store; the
# SQLite action row remains the only source of truth for claims and receipts.
_PROCESS_LIFECYCLE_OWNER = f"{os.getpid()}:{uuid.uuid4().hex}"


# 用户可见的活动账本标题：面向中文用户，不能把内部 action_type 或英文
# "Action: ..." 直接展示。前端还有一份同义映射用于降级兜底，这里负责
# 权威写入时的 title。
_ACTION_TYPE_TITLES: dict[str, str] = {
    "agent.negotiation": "已完成证据复核",
    "agent_action.revert": "撤回自动整理",
    "chat.daily_archive": "已归档聊天日记",
    "chat.auto_memory.skip": "已跳过自动整理",
    "continuity.identity": "身份线索整理",
    "continuity.relationship": "关系理解整理",
    "continuity.mood": "情绪状态整理",
    "continuity.energy": "能量状态整理",
    "continuity.open_thread": "下次接着聊",
    "continuity.proposal.activate": "已确认陪伴状态",
    "diary.structured_memory": "已提取结构化日记",
    "markdown.bulk_rewrite": "批量改写本机文本",
    "markdown.delete": "删除本机文本",
    "markdown.move": "移动本机文本",
    "memory.consolidation.candidate": "已整理长期记忆候选",
    "memory.consolidation.safety_event": "已记录记忆安全事件",
    "memory.consolidation.skip": "已跳过长期记忆整理",
    "memory.entity_relation": "提取实体关系",
    "memory.long_term.write": "已更新长期记忆",
    "memory.long_term.skip": "已跳过长期记忆",
    "memory.profile.action": "画像记忆管理",
    "memory.promote_conflict": "记忆冲突整理",
    "memory.proposal": "记忆提案",
    "memory.proposal.confirm": "已确认记忆提案",
    "memory.proposal.reject": "已拒绝记忆提案",
    "memory.proposal.defer": "已暂缓记忆提案",
    "memory.feedback.apply": "已应用记忆反馈",
    "memory.hygiene.apply": "已应用记忆整理",
    "memory.graph.entity": "记忆实体管理",
    "memory.graph.statement": "记忆事实管理",
    "memory.graph.relation": "记忆关系管理",
    "memory.graph.rebuild": "已重建记忆图谱",
    "continuity.proposal.confirm": "已确认陪伴提案",
    "continuity.proposal.reject": "已拒绝陪伴提案",
    "reminder.delivery.reserve": "已预留提醒派发",
    "reminder.delivery.display": "已调用系统通知",
    "reminder.delivery.recover": "已恢复提醒派发",
    "metrics.feedback": "已记录产品反馈",
    "sqlite.schema_change": "本机数据结构变更",
    "task.create": "创建任务",
    "task.complete": "完成任务",
    "task.approve": "确认任务",
    "task.reject": "拒绝任务",
    "task.cancel": "取消任务",
    "task.patch": "更新任务",
    "vault.bind": "绑定本机文件夹",
    "vault.switch": "切换本机文件夹",
    "wiki.ingest.apply": "资料页应用",
    "wiki.lint.repair": "资料页检查修复",
    "wiki.lint.report": "已生成资料页检查报告",
    "wiki.answer_summary.write": "已自动总结到资料页",
    "wiki.answer_summary.skip": "已跳过资料页摘要",
    "wiki.page.write": "已整理资料页",
    "wiki.page.replace_section": "资料页章节替换",
    "wiki.query_archive.write": "已整理资料页查询",
    "wiki.synthesize.write": "已综合整理资料页",
    "wiki.retrospective_report.write": "已生成复盘报告",
    "wiki.weekly_report.write": "已生成周报",
    "wiki.monthly_report.write": "已生成月报",
}


def _action_type_title(action_type: str) -> str:
    """Return a user-facing Chinese title for an action type."""
    return _ACTION_TYPE_TITLES.get(action_type, action_type)


@dataclass(frozen=True, slots=True)
class AdapterExecutionResult:
    result: dict[str, Any]
    before_snapshot: dict[str, Any] = field(default_factory=dict)
    after_snapshot: dict[str, Any] = field(default_factory=dict)
    target_paths: tuple[str, ...] = ()
    fully_applied: bool = True
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ActionLifecycleOutcome:
    receipt: ExecutionReceipt
    verification: VerificationResult | None
    action: AgentActionResponse
    duplicate: bool = False


class ActionLedgerProtocol(Protocol):
    def claim_execution(
        self,
        request: AgentActionCreate,
        *,
        idempotency_key: str,
    ) -> tuple[AgentActionResponse, bool]: ...

    def record_policy_decision(
        self,
        request: AgentActionCreate,
        *,
        idempotency_key: str,
        status: str,
    ) -> tuple[AgentActionResponse, bool]: ...

    def find_execution(self, idempotency_key: str) -> AgentActionResponse | None: ...

    def begin_execution(
        self,
        action_id: str,
        *,
        owner_id: str,
        takeover: bool = False,
    ) -> tuple[AgentActionResponse, bool]: ...

    def mark_execution_interrupted(
        self,
        action_id: str,
        *,
        owner_id: str,
    ) -> AgentActionResponse: ...

    def update_execution(self, action_id: str, **kwargs: Any) -> AgentActionResponse: ...


class ActionLifecycleCoordinator:
    def __init__(
        self,
        *,
        ledger: ActionLedgerProtocol,
        adapters: Mapping[str, Callable[[ActionProposal, PolicyDecision, ExecutionClaim], Any]],
        readers: Mapping[str, Callable[[ExecutionReceipt], Any]],
        timeout_seconds: float = 10.0,
    ) -> None:
        self.ledger = ledger
        self.adapters = dict(adapters)
        self.readers = dict(readers)
        self.timeout_seconds = max(0.001, min(float(timeout_seconds), 30.0))
        self.owner_id = _PROCESS_LIFECYCLE_OWNER

    async def execute(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        source_run_id: str,
        source_conversation_id: str | None = None,
    ) -> ActionLifecycleOutcome:
        self._validate_binding(proposal, policy)
        if policy.decision != "approved":
            return self._record_nonexecuting(
                proposal,
                policy,
                source_run_id=source_run_id,
                source_conversation_id=source_conversation_id,
            )

        request = self._ledger_request(
            proposal,
            policy,
            source_run_id=source_run_id,
            source_conversation_id=source_conversation_id,
            status="claimed",
        )
        action, created = self.ledger.claim_execution(
            request,
            idempotency_key=policy.idempotency_key,
        )
        duplicate = not created
        claim = ExecutionClaim(
            claim_id=action.action_id,
            proposal_id=proposal.proposal_id,
            source_run_id=source_run_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
        )
        if created:
            # A claim must be durable before an adapter is allowed to run.
            # Persist the claim binding separately because the generated
            # action id is only known after the INSERT succeeds.
            action = self.ledger.update_execution(
                action.action_id,
                status="claimed",
                metadata={
                    "control_state": "claimed",
                    "execution_claim": claim.model_dump(mode="json"),
                    "canonical_payload_hash": _canonical_payload_hash(policy),
                    "idempotency_key": policy.idempotency_key,
                    "proposal_id": proposal.proposal_id,
                    "policy_version": policy.policy_version,
                },
            )
        if not created:
            recovered = await self._recover_existing_claim(action, proposal, policy, claim)
            if recovered is not None:
                return recovered

        interrupted = bool(action.metadata.get("execution_interrupted"))
        current_owner = str(action.metadata.get("lifecycle_owner") or "")
        action, acquired = self._begin_execution(
            action,
            owner_id=self.owner_id,
            takeover=duplicate and (interrupted or current_owner != self.owner_id),
        )
        if not acquired:
            waited = await self._wait_for_terminal_receipt(action, proposal, policy)
            if waited is not None:
                return waited
            # A same-process caller must never overwrite an active execution
            # with a second adapter call.  Leave the durable row in its
            # current state so the owner can finish or a later recovery pass
            # can inspect it.
            return self._in_progress_outcome(action, proposal, policy, duplicate=True)

        adapter = self.adapters.get(policy.action_type)
        if adapter is None:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="action_adapter_unavailable",
                duplicate=duplicate,
            )

        try:
            return await self._execute_owned(
                action,
                proposal,
                policy,
                claim,
                adapter,
                duplicate=duplicate,
            )
        except BaseException:
            # A supervisor/test can interrupt the coroutine after the claim
            # (or after the external effect) but before the receipt is
            # durable.  Keep the row executing for auditability, mark the
            # interruption durably, and let the next invocation read back or
            # safely reacquire it.  A real process exit skips this block; the
            # owner PID check in the store handles that case on restart.
            try:
                self.ledger.mark_execution_interrupted(
                    action.action_id,
                    owner_id=self.owner_id,
                )
            except Exception:
                pass
            raise

    async def _execute_owned(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
        adapter: Callable[[ActionProposal, PolicyDecision, ExecutionClaim], Any],
        *,
        duplicate: bool,
    ) -> ActionLifecycleOutcome:
        action = self.ledger.update_execution(
            action.action_id,
            status="executing",
            metadata={
                "control_state": "executing",
                "execution_claim": claim.model_dump(mode="json"),
                "lifecycle_owner": self.owner_id,
            },
        )
        try:
            raw_result = adapter(proposal, policy, claim)
            if inspect.isawaitable(raw_result):
                raw_result = await asyncio.wait_for(raw_result, timeout=self.timeout_seconds)
            result = _coerce_adapter_result(raw_result)
        except (asyncio.TimeoutError, TimeoutError):
            return await self._recover_after_adapter_error(
                action,
                proposal,
                policy,
                claim,
                fallback_error_code="action_timeout",
            )
        except Exception as exc:
            # Unknown adapter failures must remain recoverable without
            # leaking exception text into the receipt. Domain exceptions may
            # provide a stable safe code; all other failures use one generic
            # lifecycle code and still trigger authoritative readback.
            error_code = _safe_exception_code(exc) or "action_failed"
            # 本地日志保留原始堆栈:回执里只能放安全码,但如果连日志都不记,
            # 这类失败(例如满载时某个适配器抛出的底层异常)就再也无法归因。
            logger.warning(
                "Action adapter failed for action_type=%s action_id=%s code=%s",
                policy.action_type,
                action.action_id,
                error_code,
                exc_info=True,
            )
            return await self._recover_after_adapter_error(
                action,
                proposal,
                policy,
                claim,
                fallback_error_code=error_code,
            )

        if not result.fully_applied:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code=result.safe_error_code or "partial_success",
                before_snapshot=result.before_snapshot,
                after_snapshot=result.after_snapshot,
                duplicate=duplicate,
            )

        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=claim.claim_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="applied",
            # The recovery probe carries the normalized intent when a process
            # dies before this receipt is durable.  The persisted receipt
            # keeps only the adapter's safe public projection.
            result={
                **result.result,
                "expected_effect": proposal.expected_effect,
            },
            before_snapshot=result.before_snapshot,
            after_snapshot=result.after_snapshot,
            reversible=proposal.reversible,
        )
        action = self.ledger.update_execution(
            action.action_id,
            status="verifying",
            before_snapshot=result.before_snapshot,
            after_snapshot=result.after_snapshot,
            target_paths=result.target_paths or None,
            metadata={
                "control_state": "verifying",
                "execution_receipt": receipt.model_dump(mode="json"),
                "target_paths": list(result.target_paths),
            },
            reversible=proposal.reversible,
        )
        return await self._verify_and_complete(
            action,
            receipt,
            proposal,
            policy,
            target_paths=result.target_paths,
            duplicate=duplicate,
        )

    @staticmethod
    def _validate_binding(proposal: ActionProposal, policy: PolicyDecision) -> None:
        if proposal.proposal_id != policy.proposal_id:
            raise ValueError("proposal_policy_identity_mismatch")
        if proposal.action_type.casefold() != policy.action_type:
            raise ValueError("proposal_policy_action_mismatch")
        if proposal.idempotency_key is not None and proposal.idempotency_key != policy.idempotency_key:
            raise ValueError("proposal_policy_idempotency_mismatch")

    async def _recover_existing_claim(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
    ) -> ActionLifecycleOutcome | None:
        stored_hash = action.metadata.get("canonical_payload_hash")
        if stored_hash is not None and str(stored_hash) != _canonical_payload_hash(policy):
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="idempotency_key_conflict",
                duplicate=True,
            )
        try:
            terminal = self._terminal_outcome(action, proposal, policy)
            stored_receipt = self._stored_receipt(action, proposal, policy)
        except ValueError:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="stored_receipt_invalid",
                duplicate=True,
            )
        if terminal is not None:
            return terminal
        if stored_receipt is not None:
            return await self._verify_and_complete(
                action,
                stored_receipt,
                proposal,
                policy,
                duplicate=True,
            )
        if action.status not in {"claimed", "executing", "verifying"}:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="ambiguous_prior_execution",
                duplicate=True,
            )

        matches, read_error = await self._read_authoritative_matches(
            self._recovery_probe_receipt(action, proposal, policy),
        )
        if read_error is not None:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code=read_error,
                duplicate=True,
            )
        if len(matches) > 1:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="ambiguous_authoritative_state",
                duplicate=True,
            )
        if matches:
            return self._outcome_from_matches(
                action,
                proposal,
                policy,
                claim,
                matches,
                read_error=None,
                zero_error_code="authoritative_state_not_found",
                allow_zero=False,
                duplicate=True,
            )

        # No authoritative effect exists yet.  The caller may acquire the
        # persistent execution slot below; if another local owner is already
        # executing, it must wait/recover instead of dispatching a duplicate.
        return None

    def _begin_execution(
        self,
        action: AgentActionResponse,
        *,
        owner_id: str,
        takeover: bool,
    ) -> tuple[AgentActionResponse, bool]:
        begin = getattr(self.ledger, "begin_execution", None)
        if begin is None:
            # Legacy ledgers do not expose the persistent CAS. A newly-created
            # claim is still safe to start; duplicate claims fail closed.
            return action, action.status == "claimed" and not takeover
        return begin(action.action_id, owner_id=owner_id, takeover=takeover)

    async def _wait_for_terminal_receipt(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
    ) -> ActionLifecycleOutcome | None:
        # Request-scoped runtimes can race while the owning adapter is still
        # finishing.  A bounded readback wait makes the losing caller return
        # the same durable receipt without touching the effect or ledger
        # status.  A later invocation handles a crashed owner.
        deadline = asyncio.get_running_loop().time() + min(self.timeout_seconds, 1.0)
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.01)
            current = self.ledger.find_execution(policy.idempotency_key)
            if current is None:
                return None
            try:
                terminal = self._terminal_outcome(current, proposal, policy)
            except ValueError:
                return self._fail_recovery(
                    current,
                    proposal,
                    policy,
                    ExecutionClaim(
                        claim_id=current.action_id,
                        proposal_id=proposal.proposal_id,
                        source_run_id="recovery",
                        idempotency_key=policy.idempotency_key,
                        action_type=policy.action_type,
                        normalized_target=policy.normalized_target,
                    ),
                    safe_error_code="stored_receipt_invalid",
                    duplicate=True,
                )
            if terminal is not None:
                return terminal
        return None

    @staticmethod
    def _in_progress_outcome(
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        duplicate: bool,
    ) -> ActionLifecycleOutcome:
        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=action.action_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="failed_recovery",
            safe_error_code="execution_in_progress",
            result={"expected_effect": proposal.expected_effect},
        )
        return ActionLifecycleOutcome(
            receipt=receipt,
            verification=None,
            action=action,
            duplicate=duplicate,
        )

    async def _recover_after_adapter_error(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
        *,
        fallback_error_code: str,
    ) -> ActionLifecycleOutcome:
        matches, read_error = await self._read_authoritative_matches(
            self._recovery_probe_receipt(action, proposal, policy),
        )
        if read_error == "verification_reader_unavailable":
            read_error = fallback_error_code
        recovered = self._outcome_from_matches(
            action,
            proposal,
            policy,
            claim,
            matches,
            read_error=read_error,
            zero_error_code=fallback_error_code,
            allow_zero=False,
            duplicate=False,
        )
        if recovered is not None:
            return recovered
        return self._fail_recovery(
            action,
            proposal,
            policy,
            claim,
            safe_error_code=fallback_error_code,
        )

    async def _verify_and_complete(
        self,
        action: AgentActionResponse,
        receipt: ExecutionReceipt,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        target_paths: tuple[str, ...] | list[str] | None = None,
        duplicate: bool = False,
    ) -> ActionLifecycleOutcome:
        reader = self.readers.get(policy.action_type)
        verification = await verify_execution_receipt(
            receipt,
            reader=reader or _missing_reader,
        )
        if verification.status != "verified":
            failed = receipt.model_copy(
                update={
                    "status": "failed_recovery",
                    "safe_error_code": verification.safe_error_code or "verification_failed",
                }
            )
            updated = self.ledger.update_execution(
                action.action_id,
                status="failed_recovery",
                metadata={
                    "control_state": "failed_recovery",
                    "execution_receipt": failed.model_dump(mode="json"),
                    "verification_result": verification.model_dump(mode="json"),
                },
                error=failed.safe_error_code,
            )
            return ActionLifecycleOutcome(
                receipt=failed,
                verification=verification,
                action=updated,
                duplicate=duplicate,
            )
        verified = receipt.model_copy(update={"status": "verified"})
        completion_metadata: dict[str, Any] = {
            "control_state": "completed",
            "execution_receipt": verified.model_dump(mode="json"),
            "verification_result": verification.model_dump(mode="json"),
        }
        action_metadata = verified.result.get("action_metadata")
        if isinstance(action_metadata, Mapping):
            completion_metadata.update(
                {
                    str(key): value
                    for key, value in action_metadata.items()
                    if str(key) not in completion_metadata
                }
            )
        persisted_target_paths = _first_target_paths(
            target_paths,
            verified.result.get("target_paths"),
            action.target_paths,
        )
        updated = self.ledger.update_execution(
            action.action_id,
            status="completed",
            metadata=completion_metadata,
            target_paths=persisted_target_paths or None,
            reversible=proposal.reversible,
        )
        return ActionLifecycleOutcome(
            receipt=verified,
            verification=verification,
            action=updated,
            duplicate=duplicate,
        )

    async def _read_authoritative_matches(
        self,
        receipt: ExecutionReceipt,
    ) -> tuple[tuple[dict[str, Any], ...], str | None]:
        reader = self.readers.get(receipt.action_type)
        if reader is None:
            return (), "verification_reader_unavailable"
        try:
            observed = reader(receipt)
            if inspect.isawaitable(observed):
                observed = await asyncio.wait_for(observed, timeout=self.timeout_seconds)
        except (asyncio.TimeoutError, TimeoutError):
            return (), "verification_read_failed"
        except Exception:
            return (), "verification_read_failed"
        if observed is None:
            return (), None
        if isinstance(observed, Mapping):
            return (dict(observed),), None
        if isinstance(observed, Sequence) and not isinstance(observed, (str, bytes, bytearray)):
            if not all(isinstance(item, Mapping) for item in observed):
                return (), "verification_state_invalid"
            return tuple(dict(item) for item in observed), None
        return (), "verification_state_invalid"

    def _outcome_from_matches(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
        matches: tuple[dict[str, Any], ...],
        *,
        read_error: str | None,
        zero_error_code: str,
        allow_zero: bool,
        duplicate: bool,
    ) -> ActionLifecycleOutcome | None:
        if read_error is not None:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code=read_error,
                duplicate=duplicate,
            )
        if len(matches) > 1:
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code="ambiguous_authoritative_state",
                duplicate=duplicate,
            )
        if not matches:
            if allow_zero:
                return None
            return self._fail_recovery(
                action,
                proposal,
                policy,
                claim,
                safe_error_code=zero_error_code,
                duplicate=duplicate,
            )
        observed = matches[0]
        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=claim.claim_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="verified",
            result={
                "recovered_from_authoritative_state": True,
                **observed,
                "expected_effect": proposal.expected_effect,
            },
            after_snapshot=observed,
            reversible=proposal.reversible,
        )
        verification = VerificationResult(
            receipt_ref=receipt.receipt_ref,
            status="verified",
            checked_state_ref=str(observed.get("state_ref") or policy.normalized_target),
            matched_checks=("authoritative_read",),
            expected_effect=proposal.expected_effect or None,
            observed_effect=str(observed.get("observed_effect") or "") or None,
            policy_version=policy.policy_version,
        )
        recovery_metadata: dict[str, Any] = {
            "control_state": "completed",
            "execution_receipt": receipt.model_dump(mode="json"),
            "verification_result": verification.model_dump(mode="json"),
            "recovered_from_authoritative_state": True,
        }
        action_metadata = observed.get("action_metadata")
        if isinstance(action_metadata, Mapping):
            recovery_metadata.update(
                {
                    str(key): value
                    for key, value in action_metadata.items()
                    if str(key) not in recovery_metadata
                }
            )
        persisted_target_paths = _first_target_paths(observed.get("target_paths"), action.target_paths)
        updated = self.ledger.update_execution(
            action.action_id,
            status="completed",
            after_snapshot=observed,
            metadata=recovery_metadata,
            target_paths=persisted_target_paths or None,
            reversible=proposal.reversible,
        )
        return ActionLifecycleOutcome(
            receipt=receipt,
            verification=verification,
            action=updated,
            duplicate=duplicate,
        )

    def _recovery_probe_receipt(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
    ) -> ExecutionReceipt:
        return ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=action.action_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="applied",
            result={
                "expected_effect": proposal.expected_effect,
                "canonical_parameters": policy.canonical_parameters,
            },
            reversible=False,
        )

    def _stored_receipt(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
    ) -> ExecutionReceipt | None:
        raw_receipt = action.metadata.get("execution_receipt")
        if not isinstance(raw_receipt, Mapping):
            return None
        receipt = ExecutionReceipt.model_validate(raw_receipt)
        if (
            receipt.claim_id != action.action_id
            or receipt.proposal_id != proposal.proposal_id
            or receipt.idempotency_key != policy.idempotency_key
            or receipt.action_type != policy.action_type
        ):
            raise ValueError("stored_receipt_binding_mismatch")
        return receipt

    def _terminal_outcome(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
    ) -> ActionLifecycleOutcome | None:
        receipt = self._stored_receipt(action, proposal, policy)
        if receipt is None or receipt.status == "applied":
            return None
        raw_verification = action.metadata.get("verification_result")
        verification = (
            VerificationResult.model_validate(raw_verification)
            if isinstance(raw_verification, Mapping)
            else None
        )
        return ActionLifecycleOutcome(
            receipt=receipt,
            verification=verification,
            action=action,
            duplicate=True,
        )

    def _record_nonexecuting(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        source_run_id: str,
        source_conversation_id: str | None,
    ) -> ActionLifecycleOutcome:
        status = "pending_confirmation" if policy.decision == "pending_confirmation" else "denied"
        request = self._ledger_request(
            proposal,
            policy,
            source_run_id=source_run_id,
            source_conversation_id=source_conversation_id,
            status=status,
        )
        action, created = self.ledger.record_policy_decision(
            request,
            idempotency_key=policy.idempotency_key,
            status=status,
        )
        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=action.action_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status=status,
            result={"policy_reason": policy.reason_code},
            safe_error_code="confirmation_required" if status == "pending_confirmation" else "policy_denied",
        )
        if created:
            self.ledger.update_execution(
                action.action_id,
                status=status,
                metadata={
                    "control_state": status,
                    "execution_receipt": receipt.model_dump(mode="json"),
                },
            )
        current = self.ledger.find_execution(policy.idempotency_key) or action
        return ActionLifecycleOutcome(
            receipt=receipt,
            verification=None,
            action=current,
            duplicate=not created,
        )

    def _fail_recovery(
        self,
        action: AgentActionResponse,
        proposal: ActionProposal,
        policy: PolicyDecision,
        claim: ExecutionClaim,
        *,
        safe_error_code: str,
        before_snapshot: dict[str, Any] | None = None,
        after_snapshot: dict[str, Any] | None = None,
        duplicate: bool = False,
    ) -> ActionLifecycleOutcome:
        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=claim.claim_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="failed_recovery",
            before_snapshot=before_snapshot or {},
            after_snapshot=after_snapshot or {},
            safe_error_code=safe_error_code,
            reversible=False,
        )
        self.ledger.update_execution(
            action.action_id,
            status="failed_recovery",
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            metadata={
                "control_state": "failed_recovery",
                "execution_receipt": receipt.model_dump(mode="json"),
            },
            reversible=False,
            error=safe_error_code,
        )
        updated = self.ledger.find_execution(policy.idempotency_key) or action
        return ActionLifecycleOutcome(
            receipt=receipt,
            verification=None,
            action=updated,
            duplicate=duplicate,
        )

    def _ledger_request(
        self,
        proposal: ActionProposal,
        policy: PolicyDecision,
        *,
        source_run_id: str,
        source_conversation_id: str | None,
        status: str,
    ) -> AgentActionCreate:
        target_paths = ()
        raw_target_paths = policy.canonical_parameters.get("target_paths")
        if isinstance(raw_target_paths, list):
            target_paths = tuple(str(path) for path in raw_target_paths)
        elif policy.canonical_parameters.get("target_path"):
            target_paths = (str(policy.canonical_parameters["target_path"]),)
        raw_title = policy.canonical_parameters.get("title")
        if policy.action_type == "task.create" and raw_title:
            display_title = str(raw_title).strip() or "任务"
        elif policy.action_type.startswith("wiki.") and raw_title:
            display_title = f"资料页：{str(raw_title).strip()}"
        elif policy.action_type == "memory.proposal":
            display_title = "记忆提案"
        else:
            display_title = _action_type_title(policy.action_type)
        return AgentActionCreate(
            action_type=policy.action_type,
            title=display_title,
            summary=proposal.expected_effect,
            source_agent_run_id=source_run_id,
            source_conversation_id=source_conversation_id,
            source_message_id=proposal.source_message_id,
            risk_tier=policy.risk_tier,
            decision="ask" if policy.requires_confirmation or policy.decision == "denied" else "auto",
            status=status,
            target_paths=target_paths,
            metadata={
                "proposal_id": proposal.proposal_id,
                "policy_version": policy.policy_version,
                "policy_reason": policy.reason_code,
                "normalized_target": policy.normalized_target,
                "target_ref": policy.normalized_target,
                "lifecycle_owner": self.owner_id,
            },
            reversible=proposal.reversible and policy.decision == "approved",
        )


def _coerce_adapter_result(value: Any) -> AdapterExecutionResult:
    if isinstance(value, AdapterExecutionResult):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("action adapter must return AdapterExecutionResult or mapping")
    return AdapterExecutionResult(
        result=dict(value.get("result") or {}),
        before_snapshot=dict(value.get("before_snapshot") or {}),
        after_snapshot=dict(value.get("after_snapshot") or {}),
        target_paths=tuple(str(path) for path in value.get("target_paths") or ()),
        fully_applied=bool(value.get("fully_applied", True)),
        safe_error_code=str(value["safe_error_code"]) if value.get("safe_error_code") else None,
    )


def _first_target_paths(*values: object) -> tuple[str, ...]:
    """Return the first non-empty, normalized target-path collection."""
    for value in values:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                return (normalized,)
            continue
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            paths = tuple(
                normalized
                for item in value
                if (normalized := str(item).strip())
            )
            if paths:
                return paths
    return ()


def _canonical_payload_hash(policy: PolicyDecision) -> str:
    payload = json.dumps(
        policy.canonical_parameters,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _missing_reader(receipt: ExecutionReceipt) -> None:
    return None


def _safe_exception_code(exc: BaseException) -> str | None:
    raw = getattr(exc, "code", None)
    if raw is None:
        # 领域异常带自己的安全码;下面两类底层失败给出稳定分类,其余仍归入调用方的
        # 通用码。没有这一步时,存储故障、参数校验失败和未知 bug 在回执与接口上长得
        # 完全一样,线上遇到的间歇失败因此无法归因。
        if isinstance(exc, sqlite3.Error):
            return "storage_unavailable"
        if isinstance(exc, ValidationError):
            return "invalid_action_parameters"
        return None
    code = str(raw).strip().casefold()
    if not code or not all(char.isalnum() or char == "_" for char in code):
        return None
    return code[:128]
