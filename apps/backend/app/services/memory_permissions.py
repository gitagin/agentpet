from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from app.models.api import MemoryRecallPermissions, MemorySearchResult
from app.services.memory_activation import MemoryActivationDecision
from app.services.memory_candidates import MemoryActivationEventCreate, MemoryCandidateStore
from app.services.memory_taxonomy import LifecycleStatus, MemoryKind, MemoryScope, RecallPermissions, RiskTier


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryPromptUsage:
    result: MemorySearchResult
    used_for_style: bool = False
    used_for_answer_context: bool = False
    used_for_proactive_mention: bool = False
    used_for_action_suggestion: bool = False
    filtered_reason: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryPromptSections:
    style_hints: tuple[str, ...]
    answer_context_lines: tuple[str, ...]
    proactive_mention_lines: tuple[str, ...]
    action_suggestion_lines: tuple[str, ...]
    usages: tuple[MemoryPromptUsage, ...]

    @property
    def has_prompt_content(self) -> bool:
        return any(
            (
                self.style_hints,
                self.answer_context_lines,
                self.proactive_mention_lines,
                self.action_suggestion_lines,
            )
        )


class MemoryActivationEventRecorder:
    def __init__(self, db: str | Path):
        self.db = db

    def record_usage(
        self,
        *,
        result: MemorySearchResult,
        conversation_id: str,
        message_id: str,
        agent_run_id: str,
        used_for_style: bool,
        used_for_answer_context: bool,
        used_for_proactive_mention: bool,
        used_for_action_suggestion: bool,
        filtered_reason: str | None = None,
    ) -> None:
        store = MemoryCandidateStore(self.db)
        try:
            store.record_activation(
                MemoryActivationEventCreate(
                    candidate_id=result.candidate_id,
                    fact_id=result.fact_id,
                    conversation_id=conversation_id,
                    message_id=message_id,
                    agent_run_id=agent_run_id,
                    activation_score=result.activation_score if result.activation_score is not None else result.score,
                    permissions=result.recall_permissions.model_dump(),
                    score_breakdown=result.score_breakdown,
                    used_for_style=used_for_style,
                    used_for_answer_context=used_for_answer_context,
                    used_for_proactive_mention=used_for_proactive_mention,
                    used_for_action_suggestion=used_for_action_suggestion,
                    filtered_reason=filtered_reason,
                )
            )
        finally:
            store.close()


def permissions_from_activation_decision(
    decision: MemoryActivationDecision,
    *,
    query: str,
) -> MemoryRecallPermissions:
    item = decision.item
    if not decision.allowed:
        return MemoryRecallPermissions(
            can_style_response=False,
            can_answer_context=False,
            can_proactively_mention=False,
            can_suggest_action=False,
        )

    can_style = decision.can_style_response
    can_answer = decision.can_answer_context
    can_proactive = decision.can_proactively_mention
    can_suggest = decision.can_suggest_action

    direct_relevance = _direct_relevance(query, item.text)
    if item.memory_kind is MemoryKind.INFERENCE:
        can_answer = False
        can_proactive = False
        can_suggest = False
        can_style = True
    elif item.memory_kind is MemoryKind.RECENT_STATE:
        can_answer = can_answer and direct_relevance
        can_proactive = False
        can_style = can_style or True
    elif item.memory_kind is MemoryKind.PROJECT_CONTEXT:
        project_relevant = _project_relevance(query, item.text)
        can_answer = can_answer and project_relevant
        can_proactive = can_proactive and project_relevant
        can_suggest = can_suggest and project_relevant

    if item.lifecycle_status is not LifecycleStatus.ACTIVE:
        can_proactive = False
    if item.memory_scope is MemoryScope.SENSITIVE or item.risk_tier is RiskTier.HIGH:
        can_style = can_answer = can_proactive = can_suggest = False

    return MemoryRecallPermissions(
        can_style_response=can_style,
        can_answer_context=can_answer,
        can_proactively_mention=can_proactive,
        can_suggest_action=can_suggest,
    )


def recall_permissions_to_taxonomy(value: MemoryRecallPermissions) -> RecallPermissions:
    return RecallPermissions(
        can_style_response=value.can_style_response,
        can_answer_context=value.can_answer_context,
        can_proactively_mention=value.can_proactively_mention,
        can_suggest_action=value.can_suggest_action,
    )


def result_with_activation_permissions(
    result: MemorySearchResult,
    decision: MemoryActivationDecision,
    *,
    query: str,
    fact_id: str | None = None,
    candidate_id: str | None = None,
) -> MemorySearchResult:
    permissions = permissions_from_activation_decision(decision, query=query)
    item = decision.item
    return result.model_copy(
        update={
            "recall_permissions": permissions,
            "activation_score": decision.activation_score,
            "score_breakdown": decision.score_breakdown,
            "filtered_reason": decision.filtered_reason,
            "memory_kind": item.memory_kind.value,
            "memory_scope": item.memory_scope.value,
            "lifecycle_status": item.lifecycle_status.value,
            "risk_tier": item.risk_tier.value,
            "fact_id": fact_id,
            "candidate_id": candidate_id,
        }
    )


def ensure_recall_permissions(result: MemorySearchResult) -> MemorySearchResult:
    permissions = result.recall_permissions
    if isinstance(permissions, MemoryRecallPermissions):
        return result
    if isinstance(permissions, Mapping):
        return result.model_copy(update={"recall_permissions": MemoryRecallPermissions.model_validate(permissions)})
    return result.model_copy(update={"recall_permissions": MemoryRecallPermissions()})


def split_recall_prompt_sections(
    results: Iterable[MemorySearchResult],
    *,
    query: str,
) -> MemoryPromptSections:
    style_hints: list[str] = []
    answer_context_lines: list[str] = []
    proactive_mention_lines: list[str] = []
    action_suggestion_lines: list[str] = []
    usages: list[MemoryPromptUsage] = []

    for result in results:
        result = ensure_recall_permissions(result)
        permissions = _contextual_permissions(result, query=query)
        used_style = False
        used_answer = False
        used_proactive = False
        used_action = False

        if permissions.can_style_response:
            hint = style_hint_for_memory(result)
            if hint and hint not in style_hints:
                style_hints.append(hint)
                used_style = True
        if permissions.can_answer_context:
            answer_context_lines.append(_source_context_line(result))
            used_answer = True
        if permissions.can_proactively_mention:
            proactive_mention_lines.append(_source_context_line(result))
            used_proactive = True
        if permissions.can_suggest_action:
            action_suggestion_lines.append(_source_context_line(result))
            used_action = True

        usages.append(
            MemoryPromptUsage(
                result=result.model_copy(update={"recall_permissions": permissions}),
                used_for_style=used_style,
                used_for_answer_context=used_answer,
                used_for_proactive_mention=used_proactive,
                used_for_action_suggestion=used_action,
                filtered_reason=None
                if any((used_style, used_answer, used_proactive, used_action))
                else result.filtered_reason or "permission_gate_no_prompt_section",
            )
        )

    return MemoryPromptSections(
        style_hints=tuple(style_hints),
        answer_context_lines=tuple(answer_context_lines),
        proactive_mention_lines=tuple(proactive_mention_lines),
        action_suggestion_lines=tuple(action_suggestion_lines),
        usages=tuple(usages),
    )


def record_prompt_section_usage(
    recorder,
    *,
    sections: MemoryPromptSections,
    conversation_id: str,
    message_id: str,
    agent_run_id: str,
) -> None:
    if recorder is None:
        return
    for usage in sections.usages:
        try:
            recorder.record_usage(
                result=usage.result,
                conversation_id=conversation_id,
                message_id=message_id,
                agent_run_id=agent_run_id,
                used_for_style=usage.used_for_style,
                used_for_answer_context=usage.used_for_answer_context,
                used_for_proactive_mention=usage.used_for_proactive_mention,
                used_for_action_suggestion=usage.used_for_action_suggestion,
                filtered_reason=usage.filtered_reason,
            )
        except Exception:
            logger.warning("Memory activation usage recording failed; continuing", exc_info=True)


def style_hint_for_memory(result: MemorySearchResult) -> str:
    return style_hint_from_text(result.snippet)


def style_hint_from_text(value: str) -> str:
    text = value.casefold()
    if any(marker in text for marker in ("preachy", "lecture", "sermon", "说教")):
        return "Avoid preachy framing; keep the answer respectful and direct."
    if any(marker in text for marker in ("pressure", "stressed", "stress", "tired", "焦虑", "压力", "累")):
        return "Use a softer, low-pressure tone and avoid adding extra burden."
    if any(marker in text for marker in ("concise", "brief", "short", "简洁", "短")):
        return "Keep the answer concise."
    return "Adapt tone using eligible style memory, but do not mention the memory."


def _contextual_permissions(result: MemorySearchResult, *, query: str) -> MemoryRecallPermissions:
    permissions = result.recall_permissions
    memory_kind = result.memory_kind or ""
    snippet = result.snippet
    if _is_unconfirmed_or_inactive_result(result):
        return permissions.model_copy(
            update={
                "can_answer_context": False,
                "can_proactively_mention": False,
                "can_suggest_action": False,
            }
        )
    if memory_kind == MemoryKind.RECENT_STATE.value:
        direct = _direct_relevance(query, snippet)
        return permissions.model_copy(
            update={
                "can_answer_context": permissions.can_answer_context and direct,
                "can_proactively_mention": False,
            }
        )
    if memory_kind == MemoryKind.INFERENCE.value:
        return permissions.model_copy(update={"can_answer_context": False, "can_proactively_mention": False, "can_suggest_action": False})
    if memory_kind == MemoryKind.PROJECT_CONTEXT.value:
        relevant = _project_relevance(query, snippet)
        return permissions.model_copy(
            update={
                "can_answer_context": permissions.can_answer_context and relevant,
                "can_proactively_mention": permissions.can_proactively_mention and relevant,
                "can_suggest_action": permissions.can_suggest_action and relevant,
            }
        )
    return permissions


def _is_unconfirmed_or_inactive_result(result: MemorySearchResult) -> bool:
    inactive_statuses = {
        "candidate",
        "pending",
        "quarantined",
        "rejected",
        "archived",
        "forgotten",
        "sensitive_blocked",
        "wrong",
        "superseded",
        "reverted",
    }
    if result.lifecycle_status and result.lifecycle_status.casefold() in inactive_statuses:
        return True
    snippet = result.snippet.casefold()
    return any(f"status={status}" in snippet for status in inactive_statuses)


def _source_context_line(result: MemorySearchResult) -> str:
    heading = f" / {result.heading}" if result.heading else ""
    return f"- {result.relative_path}{heading}: {result.snippet}"


def _direct_relevance(query: str, text: str) -> bool:
    query_terms = set(_terms(query))
    text_terms = set(_terms(text))
    if not query_terms or not text_terms:
        return False
    return bool(query_terms & text_terms)


def _project_relevance(query: str, text: str) -> bool:
    normalized_query = query.casefold()
    if "project" not in normalized_query and "项目" not in normalized_query:
        return False
    return _direct_relevance(query, text)


def _terms(value: str) -> tuple[str, ...]:
    cleaned = "".join(char.casefold() if char.isalnum() else " " for char in value)
    return tuple(term for term in cleaned.split() if len(term) >= 3 and term not in _STOP_WORDS)


_STOP_WORDS = {
    "about",
    "after",
    "again",
    "before",
    "does",
    "have",
    "that",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "your",
}
