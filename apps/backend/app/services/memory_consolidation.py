from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Mapping

from app.models.enums import MemoryFactStatus
from app.services.long_term_memory import extract_long_term_memory_candidate
from app.services.memory_candidates import (
    MemoryCandidateCreate,
    MemoryCandidateRecord,
    MemoryCandidateStore,
    MemoryEvidenceCreate,
    MemoryEvidenceRecord,
    MemoryLifecycleEventRecord,
)
from app.services.memory_entity_graph import (
    EntityGraphError,
    MemoryEntityGraphStore,
    lookup_fingerprint,
)
from app.services.memory_policy import evaluate_memory_content
from app.services.memory_taxonomy import (
    LifecycleStatus,
    MemoryKind,
    MemoryScope,
    MemoryTaxonomy,
    RiskTier,
    SourceTrack,
    classify_memory,
)


RECENT_STATE_TTL_DAYS = 7
PROJECT_CONTEXT_TTL_DAYS = 90
MAX_EVIDENCE_EXCERPT = 500
REDACTED_EVIDENCE = "[redacted sensitive content]"


@dataclass(frozen=True, slots=True)
class MemoryConsolidationItem:
    candidate: MemoryCandidateRecord
    evidence: MemoryEvidenceRecord | None
    lifecycle_event: MemoryLifecycleEventRecord | None
    taxonomy: MemoryTaxonomy
    reason: str
    graph_fact_id: str | None = None
    graph_status: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryConsolidationResult:
    items: tuple[MemoryConsolidationItem, ...]
    skipped_reason: str | None = None

    @property
    def candidate_count(self) -> int:
        return len(self.items)

    @property
    def evidence_count(self) -> int:
        return sum(1 for item in self.items if item.evidence is not None)

    @property
    def rejected_count(self) -> int:
        return sum(1 for item in self.items if item.candidate.status is LifecycleStatus.REJECTED)

    @property
    def highest_risk_tier(self) -> RiskTier:
        order = {RiskTier.LOW: 0, RiskTier.MEDIUM: 1, RiskTier.HIGH: 2}
        highest = RiskTier.LOW
        for item in self.items:
            if order[item.candidate.risk_tier] > order[highest]:
                highest = item.candidate.risk_tier
        return highest


@dataclass(frozen=True, slots=True)
class MemoryConsolidationPreview:
    candidate_count: int
    has_sensitive_signal: bool


@dataclass(frozen=True, slots=True)
class _GraphClaimSpec:
    entity_type: str
    subject: str
    predicate: str
    value: str


@dataclass(frozen=True, slots=True)
class _CandidateSpec:
    memory_kind: MemoryKind
    memory_scope: MemoryScope
    summary: str
    normalized_value: str
    evidence_text: str
    evidence_source_type: str
    source_track: SourceTrack
    confidence: float
    importance: float
    status: LifecycleStatus | None
    reason: str
    expires_at: str | None = None
    sensitive: bool = False
    conflicting: bool = False
    transition_to: LifecycleStatus | None = None
    metadata: Mapping[str, object] | None = None
    graph_claim: _GraphClaimSpec | None = None


class MemoryConsolidationService:
    def __init__(
        self,
        store: MemoryCandidateStore,
        *,
        entity_graph: MemoryEntityGraphStore | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.entity_graph = entity_graph
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def close(self) -> None:
        if self.entity_graph is not None:
            self.entity_graph.close()
        self.store.close()

    def consolidate(
        self,
        *,
        user_message: str,
        assistant_answer: str = "",
        conversation_id: str | None = None,
        user_message_id: str | None = None,
        assistant_message_id: str | None = None,
        agent_run_id: str | None = None,
        diary_object_ids: Iterable[str] = (),
        diary_markdown_path: str | None = None,
    ) -> MemoryConsolidationResult:
        specs = tuple(
            self._extract_specs(
                user_message=user_message,
                assistant_answer=assistant_answer,
                diary_object_ids=tuple(diary_object_ids),
                diary_markdown_path=diary_markdown_path,
            )
        )
        if not specs:
            return MemoryConsolidationResult(items=(), skipped_reason="no_signal")

        items: list[MemoryConsolidationItem] = []
        for spec in specs:
            items.append(
                self._store_spec(
                    spec,
                    conversation_id=conversation_id,
                    user_message_id=user_message_id,
                    assistant_message_id=assistant_message_id,
                    agent_run_id=agent_run_id,
                )
            )
        return MemoryConsolidationResult(items=tuple(items))

    def preview(
        self,
        *,
        user_message: str,
        assistant_answer: str = "",
        diary_object_ids: Iterable[str] = (),
        diary_markdown_path: str | None = None,
    ) -> MemoryConsolidationPreview:
        """Classify the deterministic write plan without persisting it."""
        specs = tuple(
            self._extract_specs(
                user_message=user_message,
                assistant_answer=assistant_answer,
                diary_object_ids=tuple(diary_object_ids),
                diary_markdown_path=diary_markdown_path,
            )
        )
        return MemoryConsolidationPreview(
            candidate_count=len(specs),
            has_sensitive_signal=any(spec.sensitive for spec in specs),
        )

    def _extract_specs(
        self,
        *,
        user_message: str,
        assistant_answer: str,
        diary_object_ids: tuple[str, ...],
        diary_markdown_path: str | None,
    ) -> Iterable[_CandidateSpec]:
        user_text = _compact(user_message)
        assistant_text = _compact(assistant_answer)
        if not user_text and not assistant_text:
            return ()

        safety = self._safety_spec(user_text=user_text, assistant_text=assistant_text)
        if safety is not None:
            return (safety,)

        boundary_specs = tuple(self._boundary_specs(user_text))
        if any(spec.metadata and spec.metadata.get("blocks_other_candidates") for spec in boundary_specs):
            return boundary_specs

        specs: list[_CandidateSpec] = list(boundary_specs)
        explicit = self._explicit_user_memory_spec(user_text)
        if explicit is not None:
            specs.append(explicit)
        specs.extend(self._stable_preference_specs(user_text))
        specs.extend(self._project_context_specs(user_text, diary_object_ids=diary_object_ids, diary_markdown_path=diary_markdown_path))
        specs.extend(self._recent_state_specs(user_text))
        inference = self._assistant_inference_spec(assistant_text)
        if inference is not None:
            specs.append(inference)
        return _dedupe_specs(specs)

    def _safety_spec(self, *, user_text: str, assistant_text: str) -> _CandidateSpec | None:
        for source_name, text in (("user_message", user_text), ("assistant_answer", assistant_text)):
            if not text:
                continue
            decision = evaluate_memory_content(text)
            if decision.allowed:
                continue
            reason = decision.reason or "sensitive_content"
            return _CandidateSpec(
                memory_kind=MemoryKind.INFERENCE,
                memory_scope=MemoryScope.SENSITIVE,
                summary="慢整合阶段拒绝了敏感内容，未写入记忆。",
                normalized_value=f"safety_event:{reason}",
                evidence_text="",
                evidence_source_type=source_name,
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                confidence=1.0,
                importance=1.0,
                status=LifecycleStatus.CANDIDATE,
                reason=reason,
                sensitive=True,
                transition_to=LifecycleStatus.REJECTED,
                metadata={"safety_event": True, "sensitive_reason": reason, "redacted": True},
            )
        return None

    def _boundary_specs(self, user_text: str) -> Iterable[_CandidateSpec]:
        lowered = user_text.casefold()
        boundary_patterns = (
            (
                "do_not_save",
                re.compile(r"\b(?:do not|don't|dont|please do not)\s+(?:save|store|remember)\s+(?:this|that|it)\b"),
                "User asked that this turn should not be saved as ordinary memory.",
                "boundary:no_save_this_turn",
                True,
            ),
            (
                "do_not_nag",
                re.compile(r"\b(?:do not|don't|dont|please do not)\s+nag\s+me\b"),
                "User does not want nagging reminders.",
                "boundary:do_not_nag",
                False,
            ),
            (
                "do_not_be_preachy",
                re.compile(r"\b(?:do not|don't|dont|please do not)\s+be\s+preachy\b"),
                "User does not want preachy responses.",
                "boundary:do_not_be_preachy",
                False,
            ),
        )
        for reason, pattern, summary, normalized, blocks_other in boundary_patterns:
            if pattern.search(lowered):
                yield _CandidateSpec(
                    memory_kind=MemoryKind.BOUNDARY,
                    memory_scope=MemoryScope.GLOBAL,
                    summary=summary,
                    normalized_value=normalized,
                    evidence_text=user_text,
                    evidence_source_type="chat_message",
                    source_track=SourceTrack.EXPLICIT_USER,
                    confidence=0.98,
                    importance=0.95,
                    status=LifecycleStatus.ACTIVE,
                    reason=reason,
                    metadata={"blocks_other_candidates": blocks_other},
                )

    def _explicit_user_memory_spec(self, user_text: str) -> _CandidateSpec | None:
        if not _looks_explicit_memory_request(user_text):
            return None

        existing_candidate = extract_long_term_memory_candidate(user_text)
        if existing_candidate is not None:
            kind = MemoryKind.PREFERENCE if existing_candidate.category.casefold() == "preference" else MemoryKind.FACT
            return _CandidateSpec(
                memory_kind=kind,
                memory_scope=MemoryScope.GLOBAL,
                summary=_summary_for_subject_value(kind=kind, subject=existing_candidate.subject, value=existing_candidate.value),
                normalized_value=f"{kind.value}:{existing_candidate.subject.casefold()}={existing_candidate.value.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.EXPLICIT_USER,
                confidence=0.96,
                importance=0.85,
                status=LifecycleStatus.ACTIVE,
                reason="explicit_remember",
                metadata={
                    "legacy_category": existing_candidate.category,
                    "legacy_target_path": existing_candidate.target_path,
                },
                graph_claim=_explicit_graph_claim(
                    memory_kind=kind,
                    subject=existing_candidate.subject,
                    predicate=existing_candidate.predicate,
                    value=existing_candidate.value,
                ),
            )

        assignment = _extract_assignment(user_text)
        if assignment is not None:
            subject, value = assignment
            kind = MemoryKind.PREFERENCE if _looks_like_preference_subject(subject) else MemoryKind.FACT
            return _CandidateSpec(
                memory_kind=kind,
                memory_scope=MemoryScope.GLOBAL,
                summary=_summary_for_subject_value(kind=kind, subject=subject, value=value),
                normalized_value=f"{kind.value}:{subject.casefold()}={value.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.EXPLICIT_USER,
                confidence=0.96,
                importance=0.85,
                status=LifecycleStatus.ACTIVE,
                reason="explicit_remember",
                graph_claim=_explicit_graph_claim(
                    memory_kind=kind,
                    subject=subject,
                    predicate="is",
                    value=value,
                ),
            )

        preference = _extract_preference_value(user_text)
        if preference:
            return _CandidateSpec(
                memory_kind=MemoryKind.PREFERENCE,
                memory_scope=MemoryScope.GLOBAL,
                summary=f"User prefers {preference}.",
                normalized_value=f"preference:{preference.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.EXPLICIT_USER,
                confidence=0.94,
                importance=0.8,
                status=LifecycleStatus.ACTIVE,
                reason="explicit_remember_preference",
                graph_claim=_explicit_graph_claim(
                    memory_kind=MemoryKind.PREFERENCE,
                    subject="preference",
                    predicate="is",
                    value=preference,
                ),
            )

        # 兜底：显式"记住/记得"但偏好/资料/assignment 提取器都不命中时，
        # 剥离命令前缀后把剩余内容作为显式事实候选沉淀，避免
        # "记住:我下周要去北京出差"这类内容在慢记忆整合里静默丢失。
        # 这里不生成 graph_claim（无法从自由文本确定三元组），只落候选。
        from app.agents.runtime_helpers import _strip_memory_command

        content = _strip_memory_command(user_text)
        if content and content != user_text:
            return _CandidateSpec(
                memory_kind=MemoryKind.FACT,
                memory_scope=MemoryScope.GLOBAL,
                summary=_trim_value(content, limit=220),
                normalized_value=f"fact:{content.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.EXPLICIT_USER,
                confidence=0.85,
                importance=0.7,
                status=LifecycleStatus.ACTIVE,
                reason="explicit_remember_fallback",
            )
        return None

    def _stable_preference_specs(self, user_text: str) -> Iterable[_CandidateSpec]:
        if _looks_explicit_memory_request(user_text) or _looks_like_memory_recall_question(user_text):
            return ()
        preference = _extract_preference_value(user_text)
        if not preference:
            return ()
        return (
            _CandidateSpec(
                memory_kind=MemoryKind.PREFERENCE,
                memory_scope=MemoryScope.GLOBAL,
                summary=f"User prefers {preference}.",
                normalized_value=f"preference:{preference.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                confidence=0.62,
                importance=0.62,
                status=LifecycleStatus.CANDIDATE,
                reason="stable_preference_signal",
            ),
        )

    def _project_context_specs(
        self,
        user_text: str,
        *,
        diary_object_ids: tuple[str, ...],
        diary_markdown_path: str | None,
    ) -> Iterable[_CandidateSpec]:
        specs: list[_CandidateSpec] = []
        project = _extract_project_name(user_text)
        if project:
            specs.append(
                _CandidateSpec(
                    memory_kind=MemoryKind.PROJECT_CONTEXT,
                    memory_scope=MemoryScope.PROJECT,
                    summary=f"User is working on {project}.",
                    normalized_value=f"project:{project.casefold()}",
                    evidence_text=user_text,
                    evidence_source_type="chat_message",
                    source_track=SourceTrack.SLOW_CONSOLIDATION,
                    confidence=0.66,
                    importance=0.7,
                    status=LifecycleStatus.CANDIDATE,
                    expires_at=self._expires_after(days=PROJECT_CONTEXT_TTL_DAYS),
                    reason="project_context_signal",
                    metadata={
                        "diary_object_ids": list(diary_object_ids),
                        "diary_markdown_path": diary_markdown_path,
                    },
                )
            )

        tools = _extract_tool_stack(user_text)
        if tools:
            normalized_tools = ", ".join(tools)
            specs.append(
                _CandidateSpec(
                    memory_kind=MemoryKind.PROJECT_CONTEXT,
                    memory_scope=MemoryScope.TOPIC,
                    summary=f"User mentioned a tool stack: {normalized_tools}.",
                    normalized_value=f"tool_stack:{'|'.join(tool.casefold() for tool in tools)}",
                    evidence_text=user_text,
                    evidence_source_type="chat_message",
                    source_track=SourceTrack.SLOW_CONSOLIDATION,
                    confidence=0.66,
                    importance=0.6,
                    status=LifecycleStatus.CANDIDATE,
                    expires_at=self._expires_after(days=PROJECT_CONTEXT_TTL_DAYS),
                    reason="tool_stack_signal",
                    metadata={
                        "tools": list(tools),
                        "diary_object_ids": list(diary_object_ids),
                        "diary_markdown_path": diary_markdown_path,
                    },
                )
            )
        return specs

    def _recent_state_specs(self, user_text: str) -> Iterable[_CandidateSpec]:
        state = _extract_recent_state(user_text)
        if state is None:
            return ()
        return (
            _CandidateSpec(
                memory_kind=MemoryKind.RECENT_STATE,
                memory_scope=MemoryScope.TEMPORARY,
                summary=f"User recently mentioned feeling {state}.",
                normalized_value=f"recent_state:{state.casefold()}",
                evidence_text=user_text,
                evidence_source_type="chat_message",
                source_track=SourceTrack.SLOW_CONSOLIDATION,
                confidence=0.58,
                importance=0.45,
                status=LifecycleStatus.CANDIDATE,
                expires_at=self._expires_after(days=RECENT_STATE_TTL_DAYS),
                reason="temporary_state_signal",
            ),
        )

    def _assistant_inference_spec(self, assistant_text: str) -> _CandidateSpec | None:
        label = _extract_assistant_personality_inference(assistant_text)
        if label is None:
            return None
        return _CandidateSpec(
            memory_kind=MemoryKind.INFERENCE,
            memory_scope=MemoryScope.RELATIONSHIP,
            summary=f"Assistant inferred that the user may be {label}.",
            normalized_value=f"inference:{label.casefold()}",
            evidence_text=assistant_text,
            evidence_source_type="assistant_inference",
            source_track=SourceTrack.MODEL_EXTRACTED,
            confidence=0.42,
            importance=0.25,
            status=LifecycleStatus.CANDIDATE,
            reason="assistant_inference_downgraded",
            metadata={"model_output_only": True},
        )

    def _store_spec(
        self,
        spec: _CandidateSpec,
        *,
        conversation_id: str | None,
        user_message_id: str | None,
        assistant_message_id: str | None,
        agent_run_id: str | None,
    ) -> MemoryConsolidationItem:
        confidence = self._confidence_with_existing_evidence(spec)
        taxonomy = classify_memory(
            memory_kind=spec.memory_kind,
            memory_scope=spec.memory_scope,
            source_track=spec.source_track,
            lifecycle_status=spec.status,
            confidence=confidence,
            importance=spec.importance,
            expires_at=spec.expires_at,
            source_text="" if spec.sensitive else spec.evidence_text,
            conflicting=spec.conflicting,
            sensitive=spec.sensitive,
        )
        metadata = {
            **dict(spec.metadata or {}),
            "consolidation_reason": spec.reason,
            "taxonomy_reasons": list(taxonomy.reasons),
            "recall_permissions": _permissions_dict(taxonomy),
            "requires_confirmation": taxonomy.requires_confirmation,
        }
        candidate = self.store.create_candidate(
            MemoryCandidateCreate(
                memory_kind=spec.memory_kind,
                memory_scope=spec.memory_scope,
                summary=spec.summary,
                normalized_value=spec.normalized_value,
                source_text="",
                source_track=spec.source_track,
                risk_tier=taxonomy.risk_tier,
                confidence=taxonomy.confidence,
                importance=taxonomy.importance,
                status=taxonomy.lifecycle_status,
                expires_at=taxonomy.expires_at,
                metadata=metadata,
            )
        )
        evidence = self.store.add_evidence(
            MemoryEvidenceCreate(
                candidate_id=candidate.id,
                source_type=spec.evidence_source_type,
                source_text="" if spec.sensitive else spec.evidence_text,
                source_excerpt=REDACTED_EVIDENCE if spec.sensitive else _excerpt(spec.evidence_text),
                conversation_id=conversation_id,
                message_id=assistant_message_id if spec.evidence_source_type == "assistant_inference" else user_message_id,
                agent_run_id=agent_run_id,
                confidence=taxonomy.confidence,
                metadata={
                    "consolidation_reason": spec.reason,
                    "redacted": spec.sensitive,
                },
            )
        )
        candidate = self.store.get_candidate(candidate.id)
        lifecycle_event = None
        if spec.transition_to is not None and candidate.status is not spec.transition_to:
            lifecycle_event = self.store.transition(
                candidate_id=candidate.id,
                to_status=spec.transition_to,
                reason=spec.reason,
                source_agent_run_id=agent_run_id,
                source_message_id=user_message_id,
                metadata={"consolidation_reason": spec.reason},
            )
            candidate = self.store.get_candidate(candidate.id)
        try:
            graph_fact_id, graph_status = self._materialize_explicit_fact(
                spec,
                candidate=candidate,
                evidence=evidence,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                agent_run_id=agent_run_id,
            )
        except EntityGraphError:
            # graph claim 因歧义/身份冲突无法安全写入时，降级为待确认候选，
            # 而不是让整个 consolidate 报错并留下"active 候选但无 graph fact"
            # 的半激活状态 + 孤儿数据。
            graph_fact_id, graph_status = None, None
            if candidate.status is LifecycleStatus.ACTIVE:
                self.store.transition(
                    candidate_id=candidate.id,
                    to_status=LifecycleStatus.CANDIDATE,
                    reason="explicit_graph_materialization_failed",
                    source_agent_run_id=agent_run_id,
                    source_message_id=user_message_id,
                    metadata={"consolidation_reason": spec.reason},
                )
        candidate = self.store.get_candidate(candidate.id)
        if evidence is not None:
            evidence = self.store.get_evidence(evidence.id)
        return MemoryConsolidationItem(
            candidate=candidate,
            evidence=evidence,
            lifecycle_event=lifecycle_event,
            taxonomy=taxonomy,
            reason=spec.reason,
            graph_fact_id=graph_fact_id,
            graph_status=graph_status,
        )

    def _materialize_explicit_fact(
        self,
        spec: _CandidateSpec,
        *,
        candidate: MemoryCandidateRecord,
        evidence: MemoryEvidenceRecord | None,
        conversation_id: str | None,
        user_message_id: str | None,
        agent_run_id: str | None,
    ) -> tuple[str | None, str | None]:
        """Promote only explicit, low-risk declarations into the typed graph."""
        graph = self.entity_graph
        if (
            graph is None
            or spec.source_track is not SourceTrack.EXPLICIT_USER
            or candidate.status is not LifecycleStatus.ACTIVE
            or candidate.risk_tier is not RiskTier.LOW
            or evidence is None
            or not spec.evidence_text.strip()
        ):
            return None, None

        claim = spec.graph_claim
        if claim is None:
            return None, None
        if candidate.fact_id:
            fact = graph.get(candidate.fact_id)
            # 显式记忆命中既有候选/隔离事实时，用户明确要求记住，
            # 应把它激活；否则显式事实永不激活、永远不可召回。
            if fact.status in {MemoryFactStatus.CANDIDATE, MemoryFactStatus.QUARANTINED}:
                fact = graph.update_status(fact.id, MemoryFactStatus.ACTIVE, reason="explicit_user_memory")
        elif spec.memory_kind is MemoryKind.PREFERENCE:
            # 偏好声明：创建偏好实体（如「苹果」）+「自己 prefers 实体」关系边，
            # 而不是落一条 subject 为关系类型名的整句 claim（那是「偏好 is 吃苹果」错误的来源）。
            self_entity = graph.ensure_self()
            preference_entity = _find_or_create_explicit_entity(
                graph,
                entity_type="preference",
                subject=claim.value,
                confidence=candidate.confidence,
            )
            fact = graph.create_relation(
                relation_type="prefers",
                subject_entity_id=self_entity.id,
                object_entity_id=preference_entity.id,
                source_text=spec.evidence_text,
                source_type="explicit_user",
                confidence=candidate.confidence,
                evidence_id=evidence.id,
            )
            graph.bind_entity_evidence(entity_id=preference_entity.id, evidence_id=evidence.id, role="describes")
            self.store.attach_fact(candidate.id, fact.id)
            candidate = self.store.get_candidate(candidate.id)
        else:
            entity = _find_or_create_explicit_entity(
                graph,
                entity_type=claim.entity_type,
                subject=claim.subject,
                confidence=candidate.confidence,
            )
            fact = graph.create_claim(
                subject_entity_id=entity.id,
                predicate=claim.predicate,
                literal_value=claim.value,
                category=candidate.memory_kind.value,
                source_text=spec.evidence_text,
                source_type="explicit_user",
                confidence=candidate.confidence,
                evidence_id=evidence.id,
                metadata={
                    "candidate_id": candidate.id,
                    "conversation_id": conversation_id,
                    "user_message_id": user_message_id,
                    "agent_run_id": agent_run_id,
                    "source_track": SourceTrack.EXPLICIT_USER.value,
                },
            )
            graph.bind_entity_evidence(entity_id=entity.id, evidence_id=evidence.id, role="describes")
            self.store.attach_fact(candidate.id, fact.id)
            candidate = self.store.get_candidate(candidate.id)
        return fact.id, fact.status.value

    def _confidence_with_existing_evidence(self, spec: _CandidateSpec) -> float:
        if spec.source_track is SourceTrack.EXPLICIT_USER or spec.sensitive:
            return spec.confidence
        for candidate in self.store.list_candidates(memory_kind=spec.memory_kind, limit=200):
            if (
                candidate.memory_scope is spec.memory_scope
                and candidate.source_track is spec.source_track
                and candidate.normalized_value == spec.normalized_value
            ):
                return min(0.9, max(spec.confidence, candidate.confidence + 0.08))
        return spec.confidence

    def _expires_after(self, *, days: int) -> str:
        current = self.now_provider()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return (current.astimezone(timezone.utc) + timedelta(days=days)).isoformat().replace("+00:00", "Z")


def _looks_explicit_memory_request(text: str) -> bool:
    lowered = text.casefold()
    if _looks_like_memory_recall_question(text):
        return False

    english_command = (
        r"(?:(?:please\s+)?(?:remember|save|store)\b"
        r"|(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:remember|save|store)\b"
        r"|i\s+(?:want|need|would\s+like)\s+you\s+to\s+(?:remember|save|store)\b"
        r"|keep\s+this\s+in\s+memory\b)"
    )
    return bool(
        re.search(rf"^\s*{english_command}", lowered)
        or re.search(rf"[,;.!?]\s*(?:and\s+)?{english_command}", lowered)
        or re.search(
            r"^\s*(?:(?:请\s*(?:帮我\s*)?|帮我\s*)?(?:记得|记住)|(?:请|帮我)?\s*(?:保存|存下|记下来))",
            text,
        )
        or re.search(
            r"[,，;；。]\s*(?:并且|并)?\s*(?:(?:请\s*(?:帮我\s*)?|帮我\s*)?(?:记得|记住)|(?:请|帮我)?\s*(?:保存|存下|记下来))",
            text,
        )
    )


def _looks_like_memory_recall_question(text: str) -> bool:
    lowered = text.casefold()
    return bool(
        re.search(r"^\s*(?:do|did)\s+you\s+(?:still\s+)?remember\b", lowered)
        or re.search(r"^\s*what\s+(?:do|did)\s+you\s+remember\b", lowered)
        or re.search(r"^\s*你(?:还|仍然)?记得", text)
        or re.search(r"^\s*(?:还|仍然)?记得.+(?:吗|么|[?？])\s*$", text)
    )


def _extract_assignment(text: str) -> tuple[str, str] | None:
    patterns = (
        r"\b(?:remember\s+(?:this|that)?\s*[:,-]?\s*)?(?:my|our)\s+(?P<subject>[a-z][a-z0-9 _-]{1,50})\s+(?:is|are|=)\s+(?P<value>[^.?!]{1,120})",
        r"\b(?:remember\s+(?:this|that)?\s*[:,-]?\s*)?the\s+(?P<subject>[a-z][a-z0-9 _-]{1,50})\s+(?:is|=)\s+(?P<value>[^.?!]{1,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            subject = _trim_value(match.group("subject"), limit=80)
            value = _trim_value(match.group("value"), limit=160)
            if subject and value:
                return subject, value
    return None


def _extract_preference_value(text: str) -> str:
    patterns = (
        r"\b(?:i prefer|i like|please keep|keep|please make|make)\s+(?P<value>[^.?!]{2,120})",
        r"\b(?:my favorite)\s+(?P<subject>[a-z][a-z0-9 _-]{1,40})\s+is\s+(?P<value>[^.?!]{2,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        if match.groupdict().get("subject"):
            return _trim_value(f"{match.group('subject')} = {match.group('value')}", limit=160)
        value = _trim_value(match.group("value"), limit=160)
        if value:
            return value
    if re.search(r"\bconcise\s+(?:answers|replies|responses|style)\b", text, re.IGNORECASE):
        return "concise replies"
    return ""


def _extract_project_name(text: str) -> str:
    patterns = (
        r"\b(?:working on|building|maintaining)\s+(?P<project>(?:project\s+)?[A-Z][A-Za-z0-9_-]{1,50})",
        r"\bproject\s+(?P<project>[A-Z][A-Za-z0-9_-]{1,50})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _trim_value(match.group("project"), limit=80)
    return ""


def _extract_tool_stack(text: str) -> tuple[str, ...]:
    known = (
        "Python",
        "FastAPI",
        "React",
        "TypeScript",
        "Electron",
        "Vite",
        "SQLite",
        "Obsidian",
        "LangGraph",
        "pytest",
    )
    lowered = text.casefold()
    if not any(marker in lowered for marker in ("use ", "using ", "stack", "built with", "tool")):
        return ()
    tools = tuple(tool for tool in known if re.search(rf"\b{re.escape(tool)}\b", text, re.IGNORECASE))
    return tools[:6]


def _extract_recent_state(text: str) -> str | None:
    lowered = text.casefold()
    state_patterns = (
        "under pressure",
        "overwhelmed",
        "stressed",
        "anxious",
        "tired",
        "exhausted",
        "frustrated",
        "relieved",
        "busy",
        "sad",
        "excited",
    )
    has_temporal_hint = any(marker in lowered for marker in ("today", "right now", "this week", "lately", "recently", "deadline"))
    has_self_report = any(marker in lowered for marker in ("i feel", "i'm", "i am", "i have been", "i've been"))
    if not (has_temporal_hint or has_self_report):
        return None
    for state in state_patterns:
        if state in lowered:
            return state
    if re.search(r"\b(?:plan|need|have)\s+to\s+[^.?!]{2,80}\b", lowered) and has_temporal_hint:
        return "short-term plan"
    return None


def _extract_assistant_personality_inference(text: str) -> str | None:
    if not text:
        return None
    patterns = (
        r"\b(?:the user|you)\s+(?:is|are|seems?|appear(?:s)?)\s+(?:like\s+)?(?:an?\s+)?(?P<label>[a-z][a-z -]{2,60})(?:\s+person|\s+personality)?\b",
        r"\b(?:the user|you)\s+has\s+(?:an?\s+)?(?P<label>[a-z][a-z -]{2,60})(?:\s+personality)?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            continue
        label = _trim_value(match.group("label"), limit=80).casefold()
        label = re.sub(r"\s+(?:person|personality|user)$", "", label).strip()
        if _looks_like_personality_label(label):
            return label
    return None


def _looks_like_personality_label(label: str) -> bool:
    labels = (
        "anxious",
        "depressed",
        "lazy",
        "avoidant",
        "needy",
        "angry",
        "emotional",
        "introvert",
        "introverted",
        "perfectionist",
        "unreliable",
        "insecure",
    )
    return any(marker in label for marker in labels)


def _looks_like_preference_subject(subject: str) -> bool:
    lowered = subject.casefold()
    return any(marker in lowered for marker in ("prefer", "preference", "favorite", "style", "tone", "editor"))


def _summary_for_subject_value(*, kind: MemoryKind, subject: str, value: str) -> str:
    if kind is MemoryKind.PREFERENCE:
        return f"偏好：{value}"
    return f"用户陈述：{subject} = {value}"


def _explicit_graph_claim(
    *,
    memory_kind: MemoryKind,
    subject: str,
    predicate: str,
    value: str,
) -> _GraphClaimSpec | None:
    normalized_subject = _trim_value(subject, limit=80)
    normalized_value = _trim_value(value, limit=200)
    if not normalized_value:
        return None
    if memory_kind is MemoryKind.PREFERENCE:
        # 偏好事实的主语是「自己」（self），关系类型是「偏好」；
        # 不要生成 entity_type="preference"、name="偏好" 的错误实体。
        return _GraphClaimSpec(
            entity_type="self",
            subject="自己",
            predicate="偏好",
            value=normalized_value,
        )
    if not normalized_subject:
        return None
    return _GraphClaimSpec(
        entity_type="self",
        subject="自己",
        predicate=normalized_subject,
        value=normalized_value,
    )


def _find_or_create_explicit_entity(
    graph: MemoryEntityGraphStore,
    *,
    entity_type: str,
    subject: str,
    confidence: float,
):
    if entity_type == "self":
        return graph.ensure_self()
    fingerprint = lookup_fingerprint(entity_type, subject)
    rows = graph.conn.execute(
        """
        SELECT id FROM memory_entities
        WHERE entity_type = ? AND lookup_fingerprint = ?
          AND status IN ('active', 'candidate')
        ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, created_at, id
        """,
        (entity_type, fingerprint),
    ).fetchall()
    if len(rows) > 1:
        raise EntityGraphError("explicit_entity_disambiguation_required")
    if rows:
        entity = graph.get_entity(str(rows[0]["id"]))
        if entity.status == "candidate":
            return graph.activate_entity_candidate(entity.id, reason="explicit_user_memory")
        return entity
    return graph.create_entity(
        entity_type=entity_type,
        canonical_name=subject,
        status="active",
        risk_tier="low",
        confidence=confidence,
        metadata={"origin": "explicit_user_memory"},
    )


def _permissions_dict(taxonomy: MemoryTaxonomy) -> dict[str, bool]:
    permissions = taxonomy.recall_permissions
    return {
        "can_style_response": permissions.can_style_response,
        "can_answer_context": permissions.can_answer_context,
        "can_proactively_mention": permissions.can_proactively_mention,
        "can_suggest_action": permissions.can_suggest_action,
        "can_persist": permissions.can_persist,
    }


def _dedupe_specs(specs: Iterable[_CandidateSpec]) -> tuple[_CandidateSpec, ...]:
    seen: set[tuple[MemoryKind, MemoryScope, SourceTrack, str]] = set()
    deduped: list[_CandidateSpec] = []
    for spec in specs:
        key = (spec.memory_kind, spec.memory_scope, spec.source_track, spec.normalized_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(spec)
    return tuple(deduped)


def _trim_value(value: str, *, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,:;\"'")
    return cleaned[:limit].strip(" .,:;\"'")


def _excerpt(value: str) -> str:
    return _trim_value(value, limit=MAX_EVIDENCE_EXCERPT)


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
