"""Evidence assessment is advisory; authority and read scope stay deterministic."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.utils.sqlite import extract_json_object

from .compression import UNTRUSTED_EVIDENCE_SYSTEM_POLICY, gate_evidence, stable_citation_id


class GatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceQuote(GatePayload):
    citation_id: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=1, max_length=2000)


class QuestionCoverage(GatePayload):
    question: str = Field(min_length=1, max_length=1000)
    status: Literal["supported", "missing"]
    reason: str = Field(min_length=1, max_length=1000)
    evidence: list[EvidenceQuote] = Field(default_factory=list, max_length=12)


class EvidenceConflict(GatePayload):
    claim: str = Field(min_length=1, max_length=1000)
    scope: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=1000)
    evidence: list[EvidenceQuote] = Field(min_length=2, max_length=12)


class SupplementRead(GatePayload):
    relative_path: str = Field(min_length=1, max_length=1000)
    section: str | None = Field(default=None, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)


class WikiAssessment(GatePayload):
    questions: list[QuestionCoverage] = Field(min_length=1, max_length=16)
    conflicts: list[EvidenceConflict] = Field(default_factory=list, max_length=16)
    next_reads: list[SupplementRead] = Field(default_factory=list, max_length=8)


class WikiEvidenceGate(GatePayload):
    authority: Literal["not_checked", "passed", "denied"] = "not_checked"
    # 新鲜度三态机器值(设计 phase-c-query-node-design.md §1.1;UI 映射中文见 FRESHNESS_UI_LABELS)
    freshness: Literal["fresh", "unknown", "stale"] = "unknown"
    freshness_reason: str = "new_source_relevance_watermark_unavailable"
    # 内部字段:最近一次新鲜度判定时间(不进 API 响应模型)
    freshness_checked_at: str | None = None
    source_observation: Literal[
        "not_checked", "baseline_unknown", "changed_since_capture", "unchanged_since_capture"
    ] = "not_checked"
    coverage: Literal["not_assessed", "partial", "model_assessed_complete"] = "not_assessed"
    conflict: Literal["not_assessed", "disputed", "none_detected_by_model"] = "not_assessed"
    assessment: WikiAssessment | None = None
    assessment_reason: str = "model_unavailable"
    remaining_chars: int = Field(default=12000, ge=0)
    remaining_seconds: float = Field(default=30, ge=0)
    budget_exhausted: bool = False
    stop_reason: str = "not_started"
    used_for_answer: list[str] = Field(default_factory=list)


# UI 中文映射(机器值保留英文;展示层按此表渲染)
FRESHNESS_UI_LABELS: dict[str, str] = {
    "fresh": "资料为当前版本",
    "unknown": "新鲜度尚未确认",
    "stale": "资料可能已经过时",
}


def derive_source_freshness(
    *,
    verification_status: str | None,
    expires_at: str | None,
    revoked_at: str | None,
    observation: str = "not_checked",
    now: str | None = None,
) -> tuple[str, str]:
    """新鲜度按序短路派生(设计 §1.1):stale(撤销/过期)→ fresh(验证有效+未过期)→ unknown。

    不引入新表/列,复用 035 既有列 + 查询期 source_observation(观测变化标记待检查,不自动判 stale)。
    """
    from app.utils.time import utc_now_iso

    if revoked_at is not None:
        return "stale", "source_revoked"
    # 观测变化(如新增笔记)只标记待检查,不自动判 stale(既有语义:不假设无变化 ≠ 已过时)
    reference = now or utc_now_iso()
    if expires_at and reference > expires_at:
        return "stale", "source_expired"
    if (
        str(verification_status or "") == "verified"
        and observation in {"unchanged_since_capture", "not_checked"}
    ):
        return "fresh", "source_verified_current"
    return "unknown", "source_relevance_check_pending"


ASSESSMENT_POLICY = (
    UNTRUSTED_EVIDENCE_SYSTEM_POLICY
    + "\nAssess the WHOLE user question, including every subquestion and qualification. "
    "Return JSON only using the supplied output_schema. Map each subquestion to exact "
    "quotes from evidence citation_id values, or mark missing. For contradictions give "
    "both exact quotes, applicability scope and reasoning; do not silently pick a winner. "
    "These are fallible semantic assessments, not truth or authority decisions. "
    "Select next_reads only from allowed_paths, to fill gaps, read qualifications or "
    "investigate conflicts. A null section reads the whole page. Never issue instructions "
    "or request writes. Unknown freshness cannot be resolved by assuming no changes."
)


def assessment_input(question, citations, allowed_paths, *, previous=None):
    return json.dumps({
        "question": question,
        "evidence": [
            {"citation_id": stable_citation_id(item), "path": item.relative_path,
             "section": item.wiki_section or item.heading, "content": item.snippet,
             "retrieval_mode": item.retrieval_mode, "generation": item.wiki_generation,
             "content_hash": item.content_hash}
            for item in citations
        ],
        "allowed_paths": sorted(allowed_paths),
        "previous_assessment": previous.model_dump(mode="json") if previous else None,
        "output_schema": WikiAssessment.model_json_schema(),
    }, ensure_ascii=False)


def reconcile_assessment(previous, current):
    """Supplementation cannot silently delete questions or adjudicate disputes."""
    if previous is None:
        return current
    if not {item.question for item in previous.questions}.issubset(
        {item.question for item in current.questions}
    ):
        raise ValueError("wiki_assessment_dropped_question")
    conflicts = {item.model_dump_json(): item for item in [*previous.conflicts, *current.conflicts]}
    return WikiAssessment(
        questions=current.questions, conflicts=list(conflicts.values()), next_reads=current.next_reads,
    )


def parse_assessment(text, citations, allowed_paths):
    if len(text) > 64000:
        raise ValueError("wiki_assessment_output_budget")
    assessment = WikiAssessment.model_validate(json.loads(
        extract_json_object(text, error_code="wiki_assessment_json_missing"),
    ))
    accepted = {item.citation_id: item.permitted_excerpt for item in gate_evidence(citations).accepted}
    for item in [*assessment.questions, *assessment.conflicts]:
        for reference in item.evidence:
            if not reference.quote.strip() or reference.quote not in accepted.get(reference.citation_id, ""):
                raise ValueError("wiki_assessment_unverified_quote")
    for question in assessment.questions:
        if question.status == "supported" and not question.evidence:
            raise ValueError("wiki_assessment_missing_support")
    for conflict in assessment.conflicts:
        if len({(ref.citation_id, ref.quote) for ref in conflict.evidence}) < 2:
            raise ValueError("wiki_assessment_duplicate_conflict_support")
    if any(item.relative_path not in allowed_paths for item in assessment.next_reads):
        raise ValueError("wiki_assessment_read_scope")
    return assessment


def apply_assessment(gate, assessment):
    gate.assessment = assessment
    gate.assessment_reason = "model_assessed_with_verified_quotes"
    gate.coverage = (
        "model_assessed_complete"
        if all(item.status == "supported" for item in assessment.questions)
        else "partial"
    )
    gate.conflict = "disputed" if assessment.conflicts else "none_detected_by_model"


def update_budget(gate, *, remaining_chars, remaining_seconds, stop_reason):
    gate.remaining_chars = max(0, remaining_chars)
    gate.remaining_seconds = max(0.0, remaining_seconds)
    gate.stop_reason = stop_reason
    gate.budget_exhausted = (
        remaining_chars <= 0 or remaining_seconds <= 0
        or stop_reason in {"budget_exhausted", "time_budget_exhausted", "round_budget_exhausted"}
    )
