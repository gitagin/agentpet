from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.chat_model import StructuredRoleAgent, create_structured_role_agent

from ..contracts import DraftClaim, EvidenceEnvelope, IndependentAgentRoleId, ReviewDecision, ReviewInput
from ..prompts.system import role_system_prompt


ROLE_ID = IndependentAgentRoleId.REVIEWER


def build_review_input(
    *,
    input_ref: str,
    review_attempt: int,
    repair_already_used: bool,
    draft_claims: tuple[DraftClaim, ...],
    accepted_evidence: tuple[EvidenceEnvelope, ...],
) -> ReviewInput:
    """Build the only private projection the Reviewer is allowed to receive."""

    return ReviewInput(
        input_ref=input_ref,
        review_attempt=review_attempt,
        repair_already_used=repair_already_used,
        draft_claims=draft_claims,
        accepted_evidence=accepted_evidence,
    )


def build_role_agent(*, model: Any, tools: Sequence[Any] = ()) -> StructuredRoleAgent:
    if tools:
        raise ValueError("reviewer does not allow tools")
    return create_structured_role_agent(
        model=model,
        system_prompt=role_system_prompt(ROLE_ID),
        output_schema=ReviewDecision,
    )
