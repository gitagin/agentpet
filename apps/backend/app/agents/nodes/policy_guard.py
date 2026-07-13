from __future__ import annotations

import hashlib
import json
from typing import Any

from app.services.agent_actions import AutomationPolicy
from app.services.memory_policy import evaluate_memory_content

from ..contracts import ActionProposal, PolicyDecision


ACTION_POLICY_VERSION = "action-policy.v1"

AUTO_ACTION_TYPES = frozenset(
    {
        "task.create",
        "memory.proposal",
        "wiki.page.write",
        "wiki.answer_summary.write",
        "wiki.retrospective_report.write",
        "wiki.ingest.write",
        "wiki.query_archive.write",
        "wiki.synthesize.write",
        "wiki.lint.write",
        "wiki.ingest.plan",
        "wiki.query_archive.plan",
        "wiki.synthesize.plan",
        "wiki.lint.plan",
    }
)

KNOWN_CONFIRMATION_TYPES = frozenset(
    AutomationPolicy.HIGH_RISK_TYPES
    | AutomationPolicy.MEDIUM_RISK_TYPES
    | {
        "local.destructive_request",
        "wiki.ingest.apply",
        "wiki.query_archive.apply",
        "wiki.synthesize.apply",
        "wiki.lint.repair",
        "memory.long_term.write",
    }
)

HIGH_CONFIRMATION_TYPES = frozenset(
    AutomationPolicy.HIGH_RISK_TYPES
    | {
        "local.destructive_request",
        "memory.long_term.write",
    }
)


def evaluate_action_proposal(proposal: ActionProposal) -> PolicyDecision:
    action_type = proposal.action_type.strip().casefold()
    canonical_parameters = _canonicalize_parameters(proposal.parameters)
    normalized_target = _normalized_target(proposal, canonical_parameters)
    idempotency_key = derive_action_idempotency_key(
        proposal=proposal,
        action_type=action_type,
        normalized_target=normalized_target,
        canonical_parameters=canonical_parameters,
    )
    target_paths = _target_paths(normalized_target, canonical_parameters)

    if _normalized_target_is_unsafe(normalized_target):
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier="high",
            decision="denied",
            requires_confirmation=False,
            reason_code="unsafe_target",
        )

    if proposal.idempotency_key is not None and proposal.idempotency_key != idempotency_key:
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier="high",
            decision="denied",
            requires_confirmation=False,
            reason_code="invalid_proposal",
        )

    content_policy = evaluate_memory_content(json.dumps(canonical_parameters, ensure_ascii=False))
    if not content_policy.allowed:
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier="high",
            decision="denied",
            requires_confirmation=False,
            reason_code="sensitive_content",
        )

    automation = AutomationPolicy().decide(
        action_type,
        target_paths=target_paths,
        overwrite=bool(canonical_parameters.get("overwrite")),
        destructive=action_type in AutomationPolicy.HIGH_RISK_TYPES,
        reversible=proposal.reversible,
    )
    if automation.reason in {"unsafe_target_path", "wiki_write_outside_wiki"}:
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier="high",
            decision="denied",
            requires_confirmation=False,
            reason_code="unsafe_target",
        )

    if action_type in AUTO_ACTION_TYPES and automation.decision == "auto" and not proposal.requested_confirmation:
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier="low",
            decision="approved",
            requires_confirmation=False,
            reason_code="allowlisted_low_risk",
        )

    if action_type in KNOWN_CONFIRMATION_TYPES or automation.decision == "ask" or proposal.requested_confirmation:
        return _decision(
            proposal,
            action_type=action_type,
            normalized_target=normalized_target,
            canonical_parameters=canonical_parameters,
            idempotency_key=idempotency_key,
            risk_tier=(
                "high"
                if automation.risk_tier == "high" or action_type in HIGH_CONFIRMATION_TYPES
                else "medium"
            ),
            decision="pending_confirmation",
            requires_confirmation=True,
            reason_code="confirmation_required",
        )

    return _decision(
        proposal,
        action_type=action_type,
        normalized_target=normalized_target,
        canonical_parameters=canonical_parameters,
        idempotency_key=idempotency_key,
        risk_tier="high",
        decision="denied",
        requires_confirmation=False,
        reason_code="unknown_action_type",
    )


def derive_action_idempotency_key(
    *,
    proposal: ActionProposal,
    action_type: str,
    normalized_target: str,
    canonical_parameters: dict[str, Any],
) -> str:
    payload = {
        "schema_version": proposal.schema_version,
        "source_message_id": proposal.source_message_id or "",
        "explicit_intent_ref": proposal.explicit_intent_ref,
        "action_type": action_type,
        "normalized_target": normalized_target,
        "canonical_parameter_hash": hashlib.sha256(
            json.dumps(canonical_parameters, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _canonicalize_parameters(value: dict[str, Any]) -> dict[str, Any]:
    return {str(key): _canonical_value(value[key]) for key in sorted(value)}


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value)}
    if isinstance(value, list | tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str):
        return " ".join(value.split())
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)


def _normalized_target(proposal: ActionProposal, parameters: dict[str, Any]) -> str:
    raw = (
        proposal.normalized_target
        or proposal.target_ref
        or parameters.get("target_path")
        or parameters.get("title")
        or proposal.explicit_intent_ref
    )
    normalized = " ".join(str(raw).strip().replace("\\", "/").split())
    return normalized[:256] or proposal.explicit_intent_ref[:256]


def _target_paths(normalized_target: str, parameters: dict[str, Any]) -> tuple[str, ...]:
    raw_paths = parameters.get("target_paths")
    if isinstance(raw_paths, list | tuple):
        return tuple(str(path) for path in raw_paths)
    target_path = parameters.get("target_path")
    if target_path:
        return (str(target_path),)
    if normalized_target.startswith("Wiki/"):
        return (normalized_target,)
    if normalized_target.casefold().endswith(".md"):
        return (normalized_target,)
    return ()


def _normalized_target_is_unsafe(normalized_target: str) -> bool:
    path = normalized_target.replace("\\", "/")
    parts = tuple(part for part in path.split("/") if part)
    if path.startswith("/") or ".." in parts or "." in parts:
        return True
    if any(part.startswith(".") for part in parts):
        return True
    return bool(":" in path and not path.startswith(("task:", "wiki-title:", "intent:")))


def _decision(
    proposal: ActionProposal,
    *,
    action_type: str,
    normalized_target: str,
    canonical_parameters: dict[str, Any],
    idempotency_key: str,
    risk_tier: str,
    decision: str,
    requires_confirmation: bool,
    reason_code: str,
) -> PolicyDecision:
    confirmation_digest = None
    if requires_confirmation:
        confirmation_digest = hashlib.sha256(
            f"{proposal.proposal_id}:{idempotency_key}:{ACTION_POLICY_VERSION}".encode("utf-8")
        ).hexdigest()
    return PolicyDecision(
        proposal_id=proposal.proposal_id,
        action_type=action_type,
        normalized_target=normalized_target,
        canonical_parameters=canonical_parameters,
        risk_tier=risk_tier,
        decision=decision,
        requires_confirmation=requires_confirmation,
        confirmation_digest=confirmation_digest,
        reason_code=reason_code,
        idempotency_key=idempotency_key,
    )
