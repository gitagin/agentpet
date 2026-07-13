from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.services.agent_actions import AgentActionCreate, AgentActionService

from ..contracts import (
    ActionProposal,
    ExecutionClaim,
    ExecutionReceipt,
    PolicyDecision,
    VerificationResult,
)
from ..roles.verifier_agent import verify_execution_receipt


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
    duplicate: bool = False


class ActionLifecycleCoordinator:
    def __init__(
        self,
        *,
        ledger: AgentActionService,
        adapters: Mapping[str, Callable[[ActionProposal, PolicyDecision, ExecutionClaim], Any]],
        readers: Mapping[str, Callable[[ExecutionReceipt], Any]],
        timeout_seconds: float = 10.0,
    ) -> None:
        self.ledger = ledger
        self.adapters = dict(adapters)
        self.readers = dict(readers)
        self.timeout_seconds = max(0.001, min(float(timeout_seconds), 30.0))

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
        if not created:
            return self._duplicate_outcome(action.metadata, proposal, policy, action.action_id)

        claim = ExecutionClaim(
            claim_id=action.action_id,
            proposal_id=proposal.proposal_id,
            source_run_id=source_run_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
        )
        adapter = self.adapters.get(policy.action_type)
        if adapter is None:
            return self._fail_recovery(
                action.action_id,
                proposal,
                policy,
                claim,
                safe_error_code="action_adapter_unavailable",
            )

        self.ledger.update_execution(
            action.action_id,
            status="executing",
            metadata={"control_state": "executing", "execution_claim": claim.model_dump(mode="json")},
        )
        try:
            raw_result = adapter(proposal, policy, claim)
            if inspect.isawaitable(raw_result):
                raw_result = await asyncio.wait_for(raw_result, timeout=self.timeout_seconds)
            result = _coerce_adapter_result(raw_result)
        except (asyncio.TimeoutError, TimeoutError):
            return self._fail_recovery(
                action.action_id,
                proposal,
                policy,
                claim,
                safe_error_code="action_timeout",
            )
        except Exception:
            return self._fail_recovery(
                action.action_id,
                proposal,
                policy,
                claim,
                safe_error_code="action_failed",
            )

        if not result.fully_applied:
            return self._fail_recovery(
                action.action_id,
                proposal,
                policy,
                claim,
                safe_error_code=result.safe_error_code or "partial_success",
                before_snapshot=result.before_snapshot,
                after_snapshot=result.after_snapshot,
            )

        receipt = ExecutionReceipt(
            receipt_ref=f"receipt:{action.action_id}",
            claim_id=claim.claim_id,
            proposal_id=proposal.proposal_id,
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
            status="applied",
            result={**result.result, "expected_effect": proposal.expected_effect},
            before_snapshot=result.before_snapshot,
            after_snapshot=result.after_snapshot,
            reversible=proposal.reversible,
        )
        self.ledger.update_execution(
            action.action_id,
            status="verifying",
            before_snapshot=result.before_snapshot,
            after_snapshot=result.after_snapshot,
            metadata={
                "control_state": "verifying",
                "execution_receipt": receipt.model_dump(mode="json"),
                "target_paths": list(result.target_paths),
            },
            reversible=proposal.reversible,
        )
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
            self.ledger.update_execution(
                action.action_id,
                status="failed_recovery",
                metadata={
                    "control_state": "failed_recovery",
                    "execution_receipt": failed.model_dump(mode="json"),
                    "verification_result": verification.model_dump(mode="json"),
                },
                error=failed.safe_error_code,
            )
            return ActionLifecycleOutcome(receipt=failed, verification=verification)

        verified = receipt.model_copy(update={"status": "verified"})
        self.ledger.update_execution(
            action.action_id,
            status="completed",
            metadata={
                "control_state": "completed",
                "execution_receipt": verified.model_dump(mode="json"),
                "verification_result": verification.model_dump(mode="json"),
            },
            reversible=proposal.reversible,
        )
        return ActionLifecycleOutcome(receipt=verified, verification=verification)

    @staticmethod
    def _validate_binding(proposal: ActionProposal, policy: PolicyDecision) -> None:
        if proposal.proposal_id != policy.proposal_id:
            raise ValueError("proposal_policy_identity_mismatch")
        if proposal.action_type.casefold() != policy.action_type:
            raise ValueError("proposal_policy_action_mismatch")
        if proposal.idempotency_key is not None and proposal.idempotency_key != policy.idempotency_key:
            raise ValueError("proposal_policy_idempotency_mismatch")

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
        return ActionLifecycleOutcome(receipt=receipt, verification=None, duplicate=not created)

    def _duplicate_outcome(
        self,
        metadata: Mapping[str, Any],
        proposal: ActionProposal,
        policy: PolicyDecision,
        action_id: str,
    ) -> ActionLifecycleOutcome:
        raw_receipt = metadata.get("execution_receipt")
        raw_verification = metadata.get("verification_result")
        if isinstance(raw_receipt, Mapping):
            receipt = ExecutionReceipt.model_validate(raw_receipt)
            verification = (
                VerificationResult.model_validate(raw_verification)
                if isinstance(raw_verification, Mapping)
                else None
            )
            return ActionLifecycleOutcome(receipt=receipt, verification=verification, duplicate=True)
        claim = ExecutionClaim(
            claim_id=action_id,
            proposal_id=proposal.proposal_id,
            source_run_id="duplicate",
            idempotency_key=policy.idempotency_key,
            action_type=policy.action_type,
            normalized_target=policy.normalized_target,
        )
        return self._fail_recovery(
            action_id,
            proposal,
            policy,
            claim,
            safe_error_code="ambiguous_prior_execution",
            duplicate=True,
        )

    def _fail_recovery(
        self,
        action_id: str,
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
            receipt_ref=f"receipt:{action_id}",
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
            action_id,
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
        return ActionLifecycleOutcome(receipt=receipt, verification=None, duplicate=duplicate)

    @staticmethod
    def _ledger_request(
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
        return AgentActionCreate(
            action_type=policy.action_type,
            title=f"Action: {policy.action_type}",
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


def _missing_reader(receipt: ExecutionReceipt) -> None:
    return None
