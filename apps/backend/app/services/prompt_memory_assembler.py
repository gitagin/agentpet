from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Sequence

from app.agents.immediate_understanding import ImmediateUnderstanding, immediate_understanding_context_block
from app.agents.retrieval.scoping import _source_scope_label
from app.agents.state import ActionPlan, SemanticAnalysisResult
from app.models.api import MemoryRecallPermissions, MemorySearchResult
from app.services.memory_permissions import (
    MemoryPromptSections,
    MemoryPromptUsage,
    ensure_recall_permissions,
    split_recall_prompt_sections,
)
from app.services.prompt_context_types import PromptRecentTurn
from app.services.prompt_profile_provider import PromptProfileItem
from app.utils.text import is_greeting_only


PROMPT_MEMORY_TELEMETRY_SCHEMA = "prompt_memory_telemetry_v1"
_PROMPT_CHAR_BUDGET_FILTER_REASON = "prompt_char_budget_exceeded"
PROMPT_MEMORY_DROP_REASONS = frozenset(
    {
        "char_budget_exceeded",
        "recent_turn_too_long",
        "recent_turns_char_budget_exceeded",
        "unknown_drop_reason",
    }
)


@dataclass(frozen=True, slots=True)
class PromptMemoryBudgetConfig:
    current_turn_understanding_chars: int = 4_000
    stable_profile_chars: int = 4_000
    activated_facts_chars: int = 8_000
    episodic_memory_chars: int = 8_000
    recall_answer_context_chars: int = 12_000
    style_only_chars: int = 4_000
    proactive_mentions_chars: int = 6_000
    action_suggestions_chars: int = 6_000
    continuity_chars: int = 6_000
    action_plan_chars: int = 2_000
    recent_turns_chars: int = 2_000
    recent_turn_chars: int = 600
    current_user_message_chars: int = 12_000


@dataclass(frozen=True, slots=True)
class PromptMemorySection:
    key: str
    title: str
    content: str
    item_count: int
    char_budget: int
    used_chars: int
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptMemorySectionMetric:
    key: str
    item_count: int
    used_chars: int
    char_budget: int
    dropped_count: int = 0
    drop_reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PromptMemoryTelemetry:
    sections: tuple[PromptMemorySectionMetric, ...]
    total_used_chars: int
    total_dropped_count: int
    permission_usage_counts: dict[str, int] = field(default_factory=dict)
    filtered_count: int = 0
    schema: str = PROMPT_MEMORY_TELEMETRY_SCHEMA


@dataclass(frozen=True, slots=True)
class PromptMemoryAssemblyInput:
    user_message: str
    immediate_understanding: ImmediateUnderstanding | None = None
    semantic_analysis: SemanticAnalysisResult | None = None
    citations: Sequence[MemorySearchResult] = ()
    action_plan: ActionPlan | None = None
    continuity_block: str = ""
    recent_turns: Sequence[PromptRecentTurn | str] = ()
    stable_profile_items: Sequence[PromptProfileItem | str] = ()
    conversation_id: str | None = None
    message_id: str | None = None
    agent_run_id: str | None = None
    recall_sections: MemoryPromptSections | None = None


@dataclass(frozen=True, slots=True)
class PromptMemoryAssembly:
    prompt_text: str
    sections: tuple[PromptMemorySection, ...]
    recall_sections: MemoryPromptSections | None
    telemetry: PromptMemoryTelemetry


@dataclass(slots=True)
class _RecallSectionBuilder:
    key: str
    title: str
    header: str
    char_budget: int
    line_prefix: str = ""
    values: list[str] = field(default_factory=list)
    candidate_count: int = 0
    dropped_count: int = 0

    def register_candidate(self) -> None:
        self.candidate_count += 1

    def can_append(self, value: str) -> bool:
        return len(self._content((*self.values, value))) <= max(0, self.char_budget)

    def append(self, value: str) -> None:
        self.values.append(value)

    def drop(self) -> None:
        self.dropped_count += 1

    def to_section(self) -> PromptMemorySection | None:
        if self.candidate_count == 0:
            return None
        content = self._content(tuple(self.values)) if self.values else ""
        return PromptMemorySection(
            key=self.key,
            title=self.title,
            content=content,
            item_count=len(self.values),
            char_budget=max(0, self.char_budget),
            used_chars=len(content),
            dropped_count=self.dropped_count,
            drop_reasons=("char_budget_exceeded",) if self.dropped_count else (),
        )

    def _content(self, values: Sequence[str]) -> str:
        rendered = "\n".join(f"{self.line_prefix}{value}" for value in values)
        return f"{self.header}\n{rendered}"


class PromptMemoryAssembler:
    def __init__(self, budget: PromptMemoryBudgetConfig | None = None) -> None:
        self.budget = budget or PromptMemoryBudgetConfig()

    def assemble(self, payload: PromptMemoryAssemblyInput) -> PromptMemoryAssembly:
        sections: list[PromptMemorySection] = []
        safe_citations = tuple(_prompt_safe_result(result) for result in payload.citations)
        recall_sections = payload.recall_sections
        if recall_sections is None and safe_citations:
            recall_sections = split_recall_prompt_sections(safe_citations, query=payload.user_message)

        recall_prompt_text = ""
        if recall_sections is not None:
            recall_prompt_text, recall_sections, recall_prompt_sections = self._format_recall_sections(
                recall_sections
            )
            sections.extend(self._classified_memory_sections(recall_sections))
            sections.extend(recall_prompt_sections)

        immediate_block = immediate_understanding_context_block(payload.immediate_understanding)
        immediate_section = self._section(
            "current_turn_understanding",
            "Current-turn understanding",
            immediate_block,
            item_count=1 if immediate_block else 0,
            char_budget=self.budget.current_turn_understanding_chars,
        )
        if immediate_section is not None:
            sections.append(immediate_section)
            immediate_block = immediate_section.content

        stable_profile = _stable_profile_block(payload.stable_profile_items)
        stable_profile_section = self._section(
            "stable_profile",
            "Stable profile memory",
            stable_profile,
            item_count=len(payload.stable_profile_items),
            char_budget=self.budget.stable_profile_chars,
        )
        if stable_profile_section is not None:
            sections.append(stable_profile_section)

        recent_turns_section = self._recent_turns_section(payload.recent_turns)
        if recent_turns_section is not None:
            sections.append(recent_turns_section)

        user_section = self._section(
            "current_user_message",
            "Current user message",
            payload.user_message,
            item_count=1 if payload.user_message else 0,
            char_budget=max(len(payload.user_message), self.budget.current_user_message_chars),
            clip=False,
        )
        if user_section is not None:
            sections.append(user_section)
        current_user_message = user_section.content if user_section is not None else payload.user_message

        user_message = self._message_with_citation_context(
            user_message=current_user_message,
            citations=safe_citations,
            semantic_analysis=payload.semantic_analysis,
            prompt_sections_text=recall_prompt_text,
            stable_profile_text=stable_profile_section.content if stable_profile_section is not None else "",
            recent_turns_text=recent_turns_section.content if recent_turns_section is not None else "",
        )

        action_plan_block = _action_plan_block(payload.action_plan)
        action_plan_section = self._section(
            "action_plan",
            "Planned local action",
            action_plan_block,
            item_count=1 if action_plan_block else 0,
            char_budget=self.budget.action_plan_chars,
        )
        if action_plan_section is not None:
            sections.append(action_plan_section)
            user_message = f"{user_message}\n\n{action_plan_section.content}"

        if immediate_block:
            user_message = f"{immediate_block}\n\nCurrent user message:\n{user_message}"

        continuity_section = self._section(
            "continuity",
            "Continuity context",
            payload.continuity_block.strip(),
            item_count=1 if payload.continuity_block.strip() else 0,
            char_budget=self.budget.continuity_chars,
        )
        if continuity_section is not None:
            sections.append(continuity_section)
            user_message = f"{continuity_section.content}\n\nCurrent user message:\n{user_message}"

        section_tuple = tuple(sections)
        metrics = tuple(_section_metric(section) for section in section_tuple)
        telemetry = PromptMemoryTelemetry(
            sections=metrics,
            total_used_chars=sum(section.used_chars for section in section_tuple),
            total_dropped_count=sum(metric.dropped_count for metric in metrics),
            permission_usage_counts=_permission_usage_counts(recall_sections),
            filtered_count=_filtered_count(recall_sections),
        )
        return PromptMemoryAssembly(
            prompt_text=user_message,
            sections=section_tuple,
            recall_sections=recall_sections,
            telemetry=telemetry,
        )

    def _format_recall_sections(
        self,
        sections: MemoryPromptSections,
    ) -> tuple[str, MemoryPromptSections, list[PromptMemorySection]]:
        builders = (
            _RecallSectionBuilder(
                "style_only",
                "Style memory",
                "Style memory (tone only; do not mention as facts):",
                self.budget.style_only_chars,
                line_prefix="- ",
            ),
            _RecallSectionBuilder(
                "recall_answer_context",
                "Answer context",
                "Answer context (may be used as answer evidence):",
                self.budget.recall_answer_context_chars,
            ),
            _RecallSectionBuilder(
                "proactive_mentions",
                "Proactive mention candidates",
                "Proactive mention candidates (may be directly mentioned if useful):",
                self.budget.proactive_mentions_chars,
            ),
            _RecallSectionBuilder(
                "action_suggestions",
                "Action suggestion support",
                "Action suggestion support (may support suggestions):",
                self.budget.action_suggestions_chars,
            ),
        )
        values_by_flag = {
            "used_for_style": iter(sections.style_hints),
            "used_for_answer_context": iter(sections.answer_context_lines),
            "used_for_proactive_mention": iter(sections.proactive_mention_lines),
            "used_for_action_suggestion": iter(sections.action_suggestion_lines),
        }
        builders_by_flag = {
            "used_for_style": builders[0],
            "used_for_answer_context": builders[1],
            "used_for_proactive_mention": builders[2],
            "used_for_action_suggestion": builders[3],
        }
        updated_usages: list[MemoryPromptUsage] = []
        for usage in sections.usages:
            entries: list[tuple[_RecallSectionBuilder, str]] = []
            for flag, values in values_by_flag.items():
                if not getattr(usage, flag):
                    continue
                builder = builders_by_flag[flag]
                builder.register_candidate()
                entries.append((builder, next(values)))

            if not entries or all(builder.can_append(value) for builder, value in entries):
                for builder, value in entries:
                    builder.append(value)
                updated_usages.append(usage)
                continue

            for builder, _ in entries:
                builder.drop()
            updated_usages.append(
                replace(
                    usage,
                    used_for_style=False,
                    used_for_answer_context=False,
                    used_for_proactive_mention=False,
                    used_for_action_suggestion=False,
                    filtered_reason=_PROMPT_CHAR_BUDGET_FILTER_REASON,
                )
            )

        bounded_sections = MemoryPromptSections(
            style_hints=tuple(builders[0].values),
            answer_context_lines=tuple(builders[1].values),
            proactive_mention_lines=tuple(builders[2].values),
            action_suggestion_lines=tuple(builders[3].values),
            usages=tuple(updated_usages),
        )
        prompt_sections = [section for builder in builders if (section := builder.to_section()) is not None]
        blocks = [section.content for section in prompt_sections if section.content]
        if not blocks:
            return (
                "No recalled item has permission to enter the reply prompt.",
                bounded_sections,
                prompt_sections,
            )
        return "\n\n".join(blocks), bounded_sections, prompt_sections

    def _classified_memory_sections(self, sections: MemoryPromptSections) -> list[PromptMemorySection]:
        activated_lines: list[str] = []
        episodic_lines: list[str] = []
        for usage in sections.usages:
            if not any(
                (
                    usage.used_for_answer_context,
                    usage.used_for_proactive_mention,
                    usage.used_for_action_suggestion,
                )
            ):
                continue
            result = usage.result
            line = _source_context_line(result)
            if _is_episodic_result(result):
                if line not in episodic_lines:
                    episodic_lines.append(line)
            elif _is_activated_fact_result(result):
                if line not in activated_lines:
                    activated_lines.append(line)

        result: list[PromptMemorySection] = []
        activated = self._section(
            "activated_facts",
            "Activated graph facts / active memories",
            "\n".join(activated_lines),
            item_count=len(activated_lines),
            char_budget=self.budget.activated_facts_chars,
        )
        if activated is not None:
            result.append(activated)
        episodic = self._section(
            "episodic_memory",
            "Retrieved episodic memory / diary snippets",
            "\n".join(episodic_lines),
            item_count=len(episodic_lines),
            char_budget=self.budget.episodic_memory_chars,
        )
        if episodic is not None:
            result.append(episodic)
        return result

    def _message_with_citation_context(
        self,
        *,
        user_message: str,
        citations: Sequence[MemorySearchResult],
        semantic_analysis: SemanticAnalysisResult | None,
        prompt_sections_text: str,
        stable_profile_text: str = "",
        recent_turns_text: str = "",
    ) -> str:
        stable_profile_text = stable_profile_text.strip()
        recent_turns_text = recent_turns_text.strip()
        # 用户没提起的话题不要自己延续;纯问候时更只是问候。这条规则要出现在
        # "有引用"和"没引用"两条返回路径上(线上那次就是 0 引用)。
        conversation_scope_instructions = _conversation_scope_instructions(user_message)
        if not citations:
            context_blocks = [block for block in (stable_profile_text, recent_turns_text) if block]
            if context_blocks:
                context_text = "\n\n".join(context_blocks)
                return (
                    f"{context_text}\n\nCurrent user message:\n{user_message}\n\n"
                    f"{conversation_scope_instructions}"
                )
            return f"{user_message}\n\n{conversation_scope_instructions}"
        semantic = semantic_analysis
        answer_style = semantic.answer_style if semantic else "grounded"
        source_scope = semantic.source_scope if semantic else "all"
        source_label = _source_scope_label(source_scope)
        source_instruction = (
            "这些只是聊天日记里的弱记录，不能称为已经确认的长期记忆；如果据此回答，必须明确说还没沉淀为长期记忆。"
            if source_scope == "daily_chat"
            else f"只能概括为我翻到的{source_label}显示，并在不确定时主动说明。"
        )
        stable_profile_block = f"{stable_profile_text}\n\n" if stable_profile_text else ""
        recent_turns_block = f"{recent_turns_text}\n\n" if recent_turns_text else ""
        return (
            f"{stable_profile_block}"
            f"用户问题：{user_message}\n\n"
            f"上下文范围：{source_scope}（{source_label}）\n"
            f"回答风格：{answer_style}\n"
            f"已检索到的上下文片段：\n{prompt_sections_text}\n\n"
            f"{recent_turns_block}"
            f"{conversation_scope_instructions}"
            "请以本地长期记忆陪伴体的口吻给出简短自然回答。不要逐条展开引用路径或原始 snippet；"
            "只在记忆能直接帮助当前问题时自然带入，不要为了证明检索到了而提及路径、状态、分数或原文；"
            "需要使用记忆时，请改写成温和的一句话背景判断，避免逐字复述；"
            "标着 kind=我们自己之前的对话记录_不是用户资料 的片段是你说过的话，不是资料库内容："
            "先用它核对是不是同一件事，不要把上一轮的话题当成这一轮的答案；"
            "如果用户明确要清单（例如“所有链接”“都列出来”），可以按条目把链接列出来，不必压成一句；"
            "不要把候选、待确认、被拒绝、隔离、封存、标错或已撤回内容说成已确认记忆；"
            f"{source_instruction}"
        )

    def _section(
        self,
        key: str,
        title: str,
        content: str,
        *,
        item_count: int,
        char_budget: int,
        clip: bool = True,
    ) -> PromptMemorySection | None:
        if not content.strip():
            return None
        if clip:
            clipped, dropped_count, drop_reasons = _clip(content, char_budget)
        else:
            clipped, dropped_count, drop_reasons = content, 0, ()
        return PromptMemorySection(
            key=key,
            title=title,
            content=clipped,
            item_count=item_count,
            char_budget=char_budget,
            used_chars=len(clipped),
            dropped_count=dropped_count,
            drop_reasons=drop_reasons,
        )

    @staticmethod
    def _join_items(items: Sequence[str]) -> str:
        return "\n".join(f"- {item}" for item in items if item.strip())

    def _recent_turns_section(
        self,
        turns: Sequence[PromptRecentTurn | str],
    ) -> PromptMemorySection | None:
        normalized = tuple(_normalize_recent_turn(turn) for turn in turns)
        normalized = tuple(turn for turn in normalized if turn is not None)
        if not normalized:
            return None

        header = (
            "[Recent conversation]\n"
            "Use only for local continuity in this conversation. Do not treat it as long-term memory."
        )
        selected_reversed: list[str] = []
        dropped_count = 0
        drop_reasons: list[str] = []
        used_chars = len(header)
        budget = max(0, self.budget.recent_turns_chars)
        item_budget = max(0, self.budget.recent_turn_chars)

        for turn in reversed(normalized):
            if len(turn.content) > item_budget:
                dropped_count += 1
                if "recent_turn_too_long" not in drop_reasons:
                    drop_reasons.append("recent_turn_too_long")
                continue
            line = f"- {_recent_turn_role_label(turn.role)}：{turn.content}"
            additional_chars = len(line) + 1
            if used_chars + additional_chars > budget:
                dropped_count += 1
                if "recent_turns_char_budget_exceeded" not in drop_reasons:
                    drop_reasons.append("recent_turns_char_budget_exceeded")
                continue
            selected_reversed.append(line)
            used_chars += additional_chars

        if not selected_reversed:
            return None

        lines = list(reversed(selected_reversed))
        content = header + "\n" + "\n".join(lines)
        return PromptMemorySection(
            key="recent_turns",
            title="Recent conversation",
            content=content,
            item_count=len(lines),
            char_budget=budget,
            used_chars=len(content),
            dropped_count=dropped_count,
            drop_reasons=tuple(drop_reasons),
        )


def format_recall_prompt_sections(
    sections: MemoryPromptSections,
    *,
    budget: PromptMemoryBudgetConfig | None = None,
) -> str:
    return PromptMemoryAssembler(budget)._format_recall_sections(sections)[0]


def _action_plan_block(action_plan: ActionPlan | None) -> str:
    if action_plan is None:
        return ""
    return (
        "Planned local action:\n"
        f"- type: {action_plan.action_type}\n"
        f"- risk: {action_plan.risk_score}\n"
        f"- decision: {action_plan.decision}\n"
        f"- user-facing draft: {action_plan.confirm_text}\n"
        "Reply naturally using this draft. Do not claim the action has finished yet."
    )


def _stable_profile_block(items: Sequence[PromptProfileItem | str]) -> str:
    lines = [_stable_profile_line(item) for item in items]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return (
        "[Stable user preferences and boundaries]\n"
        "Use these notes only when directly helpful. Do not mention them unless the user asks.\n"
        + "\n".join(lines)
    )


def _stable_profile_line(item: PromptProfileItem | str) -> str:
    if isinstance(item, PromptProfileItem):
        summary = item.summary.strip()
        if not summary:
            return ""
        if item.permission_group == "boundary_profile":
            return f"- 回答边界（请遵守，但不要主动提及）：{summary}"
        return f"- 回答偏好（只用于调整语气，不作为事实依据）：{summary}"
    text = str(item).strip()
    if not text:
        return ""
    return f"- 回答偏好（只用于调整语气，不作为事实依据）：{text}"


def _normalize_recent_turn(turn: PromptRecentTurn | str) -> PromptRecentTurn | None:
    if isinstance(turn, PromptRecentTurn):
        content = turn.content.strip()
        if not content or turn.role not in {"user", "assistant"}:
            return None
        return PromptRecentTurn(role=turn.role, content=content, created_at=turn.created_at)
    text = str(turn).strip()
    if not text:
        return None
    return PromptRecentTurn(role="user", content=text)


def _recent_turn_role_label(role: str) -> str:
    return "我" if role == "assistant" else "用户"


def _conversation_scope_instructions(user_message: str) -> str:
    """Rules that keep the assistant from re-raising a topic by itself.

    Reuses the shared greeting predicate rather than a second regex, so "纯问候"
    means the same thing here as it does for open-thread creation.

    Deliberately NOT part of the [Recent conversation] header: that section's
    character budget counts its header, so a longer header silently drops older
    turns.  These rules belong with the other reply instructions instead, and
    they are returned for the no-citation path too -- that is exactly the case
    where the model answers from conversation context alone.
    """
    parts = ["不要自行延续上一个话题：用户没有提起它时，不要主动拉回来或提议接着聊。\n"]
    if is_greeting_only(user_message):
        parts.append(
            "当前这句话只是问候，只回应问候，不要提议接着聊某件事——除非上面明确列出了未完话题。\n"
        )
    return "".join(parts)


def _prompt_safe_result(result: MemorySearchResult) -> MemorySearchResult:
    result = ensure_recall_permissions(result)
    reason = _prompt_exclusion_reason(result)
    if reason is None:
        return result
    return result.model_copy(
        update={
            "recall_permissions": MemoryRecallPermissions(
                can_style_response=False,
                can_answer_context=False,
                can_proactively_mention=False,
                can_suggest_action=False,
            ),
            "filtered_reason": result.filtered_reason or reason,
        }
    )


def _prompt_exclusion_reason(result: MemorySearchResult) -> str | None:
    memory_scope = (result.memory_scope or "").casefold()
    risk_tier = (result.risk_tier or "").casefold()
    status = (result.lifecycle_status or "").casefold()
    filtered_reason = (result.filtered_reason or "").casefold()
    if memory_scope == "sensitive" or risk_tier == "high":
        return "sensitive_memory"
    if filtered_reason == "expired_recent_state":
        return "expired_recent_state"
    inactive_statuses = {
        "forgotten",
        "rejected",
        "superseded",
        "sensitive_blocked",
        "wrong",
        "reverted",
    }
    if status in inactive_statuses:
        return f"{status}_memory"
    snippet = result.snippet.casefold()
    for inactive in inactive_statuses:
        if f"status={inactive}" in snippet:
            return f"{inactive}_memory"
    return None


def _source_context_line(result: MemorySearchResult) -> str:
    heading = f" / {result.heading}" if result.heading else ""
    return f"- {result.relative_path}{heading}: {result.snippet}"


def _is_episodic_result(result: MemorySearchResult) -> bool:
    return result.source_scope in {"diary_objects", "daily_chat"} or result.retrieval_mode in {
        "diary_object",
        "daily_chat",
    }


def _is_activated_fact_result(result: MemorySearchResult) -> bool:
    return bool(result.fact_id or result.candidate_id) or result.retrieval_mode in {
        "graph",
        "graph_activation",
    }


def _permission_usage_counts(sections: MemoryPromptSections | None) -> dict[str, int]:
    counts = {
        "style": 0,
        "answer_context": 0,
        "proactive_mention": 0,
        "action_suggestion": 0,
    }
    if sections is None:
        return counts
    for usage in sections.usages:
        if usage.used_for_style:
            counts["style"] += 1
        if usage.used_for_answer_context:
            counts["answer_context"] += 1
        if usage.used_for_proactive_mention:
            counts["proactive_mention"] += 1
        if usage.used_for_action_suggestion:
            counts["action_suggestion"] += 1
    return counts


def _section_metric(section: PromptMemorySection) -> PromptMemorySectionMetric:
    return PromptMemorySectionMetric(
        key=section.key,
        item_count=section.item_count,
        used_chars=section.used_chars,
        char_budget=section.char_budget,
        dropped_count=section.dropped_count,
        drop_reasons=_safe_drop_reasons(section.drop_reasons),
    )


def _safe_drop_reasons(reasons: tuple[str, ...]) -> tuple[str, ...]:
    safe: list[str] = []
    for reason in reasons:
        value = str(reason)
        safe.append(value if value in PROMPT_MEMORY_DROP_REASONS else "unknown_drop_reason")
    return tuple(dict.fromkeys(safe))


def _filtered_count(sections: MemoryPromptSections | None) -> int:
    if sections is None:
        return 0
    return sum(1 for usage in sections.usages if usage.filtered_reason)


def _clip(content: str, char_budget: int) -> tuple[str, int, tuple[str, ...]]:
    budget = max(0, int(char_budget))
    if len(content) <= budget:
        return content, 0, ()
    if budget <= 3:
        return content[:budget], 1, ("char_budget_exceeded",)
    return content[: budget - 3].rstrip() + "...", 1, ("char_budget_exceeded",)
