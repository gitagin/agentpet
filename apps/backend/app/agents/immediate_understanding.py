from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field

from app.utils.hash import sha256_hex


InteractionStyle = Literal["direct", "detailed", "gentle", "sharp", "concise"]


class ImmediateUnderstanding(BaseModel):
    current_task: str | None = None
    interaction_style: InteractionStyle | None = None
    current_topic: str | None = None
    temporary_constraints: tuple[str, ...] = Field(default_factory=tuple)
    applies_this_turn_only: bool = False
    trace: dict[str, object] = Field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.current_task,
                self.interaction_style,
                self.current_topic,
                self.temporary_constraints,
                self.applies_this_turn_only,
            )
        )


def extract_immediate_understanding(
    user_message: str,
    *,
    existing: ImmediateUnderstanding | None = None,
) -> ImmediateUnderstanding:
    text = " ".join(user_message.split())
    lowered = text.casefold()
    matched: list[str] = []

    style, style_markers = _interaction_style(lowered)
    matched.extend(style_markers)

    turn_only = _has_any(lowered, _TURN_ONLY_MARKERS)
    if turn_only:
        matched.append("turn_only")

    constraints = _temporary_constraints(text, lowered)
    if constraints:
        matched.append("temporary_constraints")

    task = _current_task(text, lowered)
    if task:
        matched.append("current_task")

    topic = _current_topic(text, lowered)
    if topic:
        matched.append("current_topic")

    if existing is not None and not existing.applies_this_turn_only:
        style = style or existing.interaction_style
        task = task or existing.current_task
        topic = topic or existing.current_topic
        constraints = _dedupe((*existing.temporary_constraints, *constraints))

    trace = {
        "source": "current_user_message",
        "message_hash": sha256_hex(text),
        "matched_signals": matched,
        "raw_text_stored": False,
    }
    return ImmediateUnderstanding(
        current_task=task,
        interaction_style=style,
        current_topic=topic,
        temporary_constraints=constraints,
        applies_this_turn_only=turn_only,
        trace=trace,
    )


def immediate_understanding_context_block(understanding: ImmediateUnderstanding | None) -> str:
    if understanding is None or understanding.is_empty:
        return ""
    lines = [
        "Current-turn understanding (state-only, not durable memory):",
        "- Use this only to shape the current reply.",
        "- Do not save, promote, or treat it as a long-term user fact.",
    ]
    if understanding.current_task:
        lines.append(f"- current_task: {understanding.current_task}")
    if understanding.interaction_style:
        lines.append(f"- interaction_style: {understanding.interaction_style}")
    if understanding.current_topic:
        lines.append(f"- current_topic: {understanding.current_topic}")
    if understanding.temporary_constraints:
        lines.append("- temporary_constraints: " + "; ".join(understanding.temporary_constraints))
    if understanding.applies_this_turn_only:
        lines.append("- scope: this turn only")
    trace = understanding.trace
    if trace:
        matched = trace.get("matched_signals")
        if isinstance(matched, list):
            lines.append("- trace_signals: " + ", ".join(str(item) for item in matched))
        if trace.get("message_hash"):
            lines.append(f"- source_hash: {trace['message_hash']}")
    return "\n".join(lines)


_STYLE_MARKERS: tuple[tuple[InteractionStyle, tuple[str, ...]], ...] = (
    ("direct", ("be blunt", "blunt critique", "no sugarcoat", "no sugarcoating", "straight talk", "tell me directly")),
    ("sharp", ("be sharp", "rip into", "tear apart", "harsh critique", "尖锐", "犀利")),
    ("concise", ("be concise", "keep it short", "short answer", "briefly", "tl;dr", "简短", "简洁")),
    ("detailed", ("be detailed", "go deep", "step by step", "详细", "展开")),
    ("gentle", ("be gentle", "softly", "gently", "温柔", "委婉")),
)

_TURN_ONLY_MARKERS = (
    "only this time",
    "this time only",
    "just this once",
    "for this turn",
    "for now",
    "temporarily",
    "本次",
    "只这次",
    "仅这次",
    "仅本次",
    "这次先",
    "临时",
)

_TASK_MARKERS = (
    "review",
    "critique",
    "debug",
    "fix",
    "implement",
    "design",
    "plan",
    "refactor",
    "explain",
    "analyze",
    "审查",
    "批评",
    "调试",
    "修复",
    "实现",
    "设计",
    "计划",
    "重构",
    "解释",
    "分析",
)

_TOPIC_MARKERS = {
    "code": ("code", "repo", "test", "api", "runtime", "migration", "schema", "backend", "frontend", "代码", "测试", "后端", "前端"),
    "writing": ("draft", "essay", "copy", "文案", "写作", "草稿"),
    "planning": ("plan", "roadmap", "timeline", "计划", "路线图"),
    "emotion": ("feel", "overwhelmed", "tired", "anxious", "情绪", "累", "焦虑"),
}


def _interaction_style(lowered: str) -> tuple[InteractionStyle | None, list[str]]:
    for style, markers in _STYLE_MARKERS:
        for marker in markers:
            if marker in lowered:
                return style, [f"style:{style}"]
    return None, []


def _temporary_constraints(text: str, lowered: str) -> tuple[str, ...]:
    constraints: list[str] = []
    if _has_any(lowered, _TURN_ONLY_MARKERS):
        constraints.append("applies only to the current turn")
    if "do not save" in lowered or "don't save" in lowered or "不要保存" in text:
        constraints.append("do not save this request as memory")
    if "no tools" in lowered or "不要调用工具" in text:
        constraints.append("avoid tool use unless already required")
    return tuple(constraints)


def _current_task(text: str, lowered: str) -> str | None:
    if not _has_any(lowered, _TASK_MARKERS) and _current_topic(text, lowered) is None:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    return _compact(cleaned, 140)


def _current_topic(text: str, lowered: str) -> str | None:
    for topic, markers in _TOPIC_MARKERS.items():
        if any(marker in lowered for marker in markers):
            return topic
    return None


def _has_any(lowered: str, markers: tuple[str, ...]) -> bool:
    return any(marker in lowered for marker in markers)


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _compact(value: str, limit: int) -> str:
    compacted = " ".join(value.strip().split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: max(0, limit - 3)].rstrip() + "..."
