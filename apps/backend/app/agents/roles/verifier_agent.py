from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from typing import Any

from ..contracts import ExecutionReceipt, VerificationResult


async def verify_execution_receipt(
    receipt: ExecutionReceipt,
    *,
    reader: Callable[[ExecutionReceipt], Any],
) -> VerificationResult:
    try:
        observed = reader(receipt)
        if inspect.isawaitable(observed):
            observed = await observed
    except Exception:
        return VerificationResult(
            receipt_ref=receipt.receipt_ref,
            status="read_failed",
            failed_checks=("authoritative_read",),
            safe_error_code="verification_read_failed",
            expected_effect=str(receipt.result.get("expected_effect") or "") or None,
            policy_version="action-policy.v1",
        )
    if observed is None:
        return VerificationResult(
            receipt_ref=receipt.receipt_ref,
            status="not_found",
            failed_checks=("target_exists",),
            safe_error_code="verification_target_not_found",
            expected_effect=str(receipt.result.get("expected_effect") or "") or None,
            policy_version="action-policy.v1",
        )
    if not isinstance(observed, Mapping):
        return VerificationResult(
            receipt_ref=receipt.receipt_ref,
            status="read_failed",
            failed_checks=("authoritative_state_shape",),
            safe_error_code="verification_state_invalid",
            policy_version="action-policy.v1",
        )

    expected = receipt.result.get("expected_state")
    if not isinstance(expected, Mapping):
        expected = receipt.after_snapshot
    matched: list[str] = []
    failed: list[str] = []
    for key, value in expected.items():
        if observed.get(key) == value:
            matched.append(str(key))
        else:
            failed.append(str(key))
    return VerificationResult(
        receipt_ref=receipt.receipt_ref,
        status="verified" if not failed else "mismatch",
        checked_state_ref=str(observed.get("state_ref") or receipt.normalized_target),
        matched_checks=tuple(sorted(matched)),
        failed_checks=tuple(sorted(failed)),
        safe_error_code=None if not failed else "verification_mismatch",
        expected_effect=str(receipt.result.get("expected_effect") or "") or None,
        observed_effect=str(observed.get("observed_effect") or "") or None,
        policy_version="action-policy.v1",
    )
