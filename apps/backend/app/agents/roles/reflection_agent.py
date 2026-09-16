"""Turn a completed exchange into locally validated reflection proposals.

The project model protocol guarantees ``complete()`` but not provider-side
schema binding, so this role requests JSON and validates it with pydantic before
anything enters policy or storage.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from app.services.chat_model import ChatModelClientProtocol
from app.utils.hash import sha256_hex
from app.utils.sqlite import extract_json_object

from ..contracts import (
    REFLECTION_ACTION_TYPES,
    ReflectionProposal,
    ReflectionProposalBatch,
    reflection_wiki_summary_target,
)

logger = logging.getLogger(__name__)

MAX_REFLECTION_PROPOSALS = 4

# proposal_kind -> 动作类型由代码决定,不由模型决定。
# 策略门禁只认可已知动作类型:模型自创的类型会被判 unknown_action_type 直接拒绝,
# 建议就永远进不了审阅队列。这四个映射都落在策略的"低风险可自动执行"集合里,
# 而在没有执行器的部署中会被路由到人工审阅(见 reflection_graph._route_proposals)。
REFLECTION_SYSTEM_PROMPT = (
    "You are the Background Reflection Agent. Return only reflection-proposal-batch.v1. "
    "Use the bounded completed-exchange projection supplied by the coordinator. "
    "Produce at most four typed proposals. Never write, execute, approve, confirm, "
    "retrieve, expose prompts, credentials, private paths, or reasoning."
)

_REFLECTION_JSON_CONTRACT = (
    "只返回一个 JSON 对象,不要散文、不要代码围栏:\n"
    '{"schema_version":"reflection-proposal-batch.v1","proposals":[\n'
    '  {"proposal_kind":"daily_diary|structured_memory|long_term_memory|wiki_summary",\n'
    '   "target_ref":null,\n'
    '   "content":"一句简短的中文陈述",\n'
    '   "confidence":0.0,\n'
    '   "reversible":true}\n'
    "]}\n"
    '没有值得提出的建议时返回 {"proposals": []}。'
)


async def propose_reflection_batch(
    *,
    model_client: ChatModelClientProtocol,
    projection: Mapping[str, Any],
) -> ReflectionProposalBatch:
    """Ask the model for a proposal batch and validate it locally."""
    text = await model_client.complete(
        user_message=_user_prompt(projection),
        system_prompt=REFLECTION_SYSTEM_PROMPT,
    )
    payload = json.loads(extract_json_object(str(text), error_code="reflection_json_missing"))
    return normalize_reflection_batch(payload, projection=projection)


def normalize_reflection_batch(
    payload: object,
    *,
    projection: Mapping[str, Any],
) -> ReflectionProposalBatch:
    """Validate a raw model payload into a proposal batch.

    Identity and provenance are ours, not the model's: ``proposal_id`` is
    derived from the proposal's own meaning (kind + action type + content) and
    ``source_message_id`` is copied from the projection.  Letting a
    model-authored slug decide that id meant one badly formatted string could
    discard every good suggestion in the batch.

    Each item is validated on its own and a failing item is dropped rather than
    failing its siblings, for the same reason: one malformed suggestion should
    cost that suggestion, not the whole batch.  Survivors are still validated
    strictly, deduplicated by identity and truncated to the proposal budget.
    """
    source_message_id = str(projection.get("source_message_id") or "")
    raw_items = payload.get("proposals") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        raw_items = []

    proposals: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    dropped = 0
    for raw in raw_items:
        candidate = _candidate(raw, source_message_id=source_message_id)
        if candidate is None:
            dropped += 1
            continue
        try:
            proposal = ReflectionProposal.model_validate(candidate)
        except ValidationError:
            dropped += 1
            continue
        if proposal.proposal_id in seen_ids:
            dropped += 1
            continue
        seen_ids.add(proposal.proposal_id)
        proposals.append(proposal.model_dump())
        if len(proposals) >= MAX_REFLECTION_PROPOSALS:
            break

    if dropped:
        logger.warning(
            "Reflection dropped %d unusable proposal(s); kept %d",
            dropped,
            len(proposals),
        )

    return ReflectionProposalBatch.model_validate(
        {"schema_version": "reflection-proposal-batch.v1", "proposals": proposals}
    )


def _candidate(raw: object, *, source_message_id: str) -> dict[str, Any] | None:
    """Rebuild one raw item with our identity, provenance and action type.

    Returns None when the item carries no usable content or an unknown kind, so
    the caller can count it as dropped instead of guessing a meaning for it.
    """
    if not isinstance(raw, dict):
        return None
    content = " ".join(str(raw.get("content") or "").split())
    proposal_kind = str(raw.get("proposal_kind") or "").strip()
    action_type = REFLECTION_ACTION_TYPES.get(proposal_kind)
    if not content or action_type is None:
        return None
    proposal_id = _proposal_id(
        proposal_kind=proposal_kind,
        action_type=action_type,
        content=content,
    )
    target_ref = reflection_wiki_summary_target(content) if proposal_kind == "wiki_summary" else None
    return {
        "proposal_id": proposal_id,
        "source_message_id": source_message_id,
        "proposal_kind": proposal_kind,
        "action_type": action_type,
        "target_ref": target_ref,
        "content": content,
        "confidence": _confidence(raw.get("confidence")),
        "reversible": bool(raw.get("reversible", True)),
    }


def _proposal_id(*, proposal_kind: str, action_type: str, content: str) -> str:
    digest = sha256_hex("\n".join([proposal_kind.casefold(), action_type, content.casefold()]))[:16]
    return f"proposal:{digest}"


def _confidence(value: object) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, number))


def _user_prompt(projection: Mapping[str, Any]) -> str:
    return (
        "回顾这轮已完成的对话,只提出值得用户确认的后续记忆／整理建议。\n"
        f"{_REFLECTION_JSON_CONTRACT}\n\n"
        "投影:\n"
        f"{json.dumps(dict(projection), ensure_ascii=False, sort_keys=True)}"
    )
