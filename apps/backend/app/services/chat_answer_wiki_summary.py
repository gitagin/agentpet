from __future__ import annotations

import re
from dataclasses import dataclass, replace

from app.services.memory_policy import evaluate_memory_content
from app.services.wiki import slugify_wiki_title


KNOWLEDGE_KEYWORDS = (
    "wiki",
    "日记",
    "记忆",
    "知识",
    "总结",
    "整理",
    "流程",
    "规则",
    "模板",
    "证据",
    "出处",
    "自检",
    "日志",
    "版本",
    "术语",
    "实现",
    "架构",
    "测试",
    "验证",
    "代码",
    "agent",
    "retrieval",
    "workflow",
    "template",
    "evidence",
)

LOW_VALUE_PATTERNS = (
    r"^(你好|hello|hi|在吗|谢谢|好的|ok|嗯|啊)[。.!！\s]*$",
    r"^(记下|帮我记一下|提醒我|今天我).{0,40}$",
)


@dataclass(frozen=True)
class ChatAnswerWikiSummaryPlan:
    title: str
    target_path: str
    content: str
    summary: str
    confidence: float
    source_paths: tuple[str, ...]
    tags: tuple[str, ...]
    links: tuple[str, ...]
    skipped_reason: str | None = None


class ChatAnswerWikiSummaryService:
    """Distill useful completed chat answers into auditable Wiki pages."""

    async def plan_with_model(self, *, model=None, **kwargs) -> ChatAnswerWikiSummaryPlan | None:
        plan = self.plan(**kwargs)
        if plan is None or model is None:
            return plan
        from app.services.wiki.compiler import read_source

        notes = await read_source(model, kwargs["assistant_answer"])
        if not notes:
            return None
        content = _summary_markdown(
            title=plan.title, question=kwargs["user_question"], answer=kwargs["assistant_answer"],
            conversation_id=kwargs["conversation_id"], user_message_id=kwargs["user_message_id"],
            assistant_message_id=kwargs["assistant_message_id"], agent_run_id=kwargs["agent_run_id"],
            diary_markdown_path=kwargs.get("diary_markdown_path"),
            diary_object_ids=kwargs.get("diary_object_ids", ()), source_paths=plan.source_paths,
            key_points=[note["statement"] for note in notes],
        )
        return replace(plan, content=content)

    def plan(
        self,
        *,
        user_question: str,
        assistant_answer: str,
        conversation_id: str,
        user_message_id: str,
        assistant_message_id: str,
        agent_run_id: str,
        diary_markdown_path: str | None,
        memory_date: str | None,
        diary_object_ids: tuple[str, ...] = (),
    ) -> ChatAnswerWikiSummaryPlan | None:
        question = _clean_text(user_question)
        answer = _clean_text(assistant_answer)
        if not question or not answer:
            return None
        if _looks_low_value(question, answer):
            return None
        if not evaluate_memory_content(f"{question}\n{answer}").allowed:
            return None

        score = _knowledge_score(question, answer)
        if score < 0.65:
            return None

        title = _summary_title(question)
        date_prefix = (memory_date or "")[:10] or "undated"
        target_path = f"Wiki/Companion/Summaries/{date_prefix}-{slugify_wiki_title(title)}.md"
        source_paths = tuple(path for path in [diary_markdown_path] if path)
        links = _summary_links(source_paths)
        tags = ("companion-summary", "auto-wiki", "chat-distilled")
        content = _summary_markdown(
            title=title,
            question=question,
            answer=answer,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            agent_run_id=agent_run_id,
            diary_markdown_path=diary_markdown_path,
            diary_object_ids=diary_object_ids,
            source_paths=source_paths,
        )
        return ChatAnswerWikiSummaryPlan(
            title=title,
            target_path=target_path,
            content=content,
            summary=f"把本轮回答自我总结到 {target_path}",
            confidence=score,
            source_paths=source_paths,
            tags=tags,
            links=links,
        )

    def skip_reason(self, *, user_question: str, assistant_answer: str) -> str:
        question = _clean_text(user_question)
        answer = _clean_text(assistant_answer)
        if not question or not answer or _looks_low_value(question, answer):
            return "low_value_chat"
        policy = evaluate_memory_content(f"{question}\n{answer}")
        if not policy.allowed:
            return policy.reason or "sensitive_content"
        if _knowledge_score(question, answer) < 0.65:
            return "low_knowledge_score"
        return "no_saveable_content"

def _knowledge_score(question: str, answer: str) -> float:
    text = f"{question}\n{answer}".casefold()
    keyword_hits = sum(1 for keyword in KNOWLEDGE_KEYWORDS if keyword.casefold() in text)
    path_hits = len(re.findall(r"\b(?:apps|docs|scripts|Wiki|Memories)/[A-Za-z0-9_\-./]+", text))
    structure_hits = sum(1 for marker in ("1.", "2.", "- ", "## ", "：", ":") if marker in answer)
    length_bonus = min(len(answer) / 600, 0.25)
    score = 0.35 + min(keyword_hits, 6) * 0.07 + min(path_hits, 3) * 0.04 + min(structure_hits, 3) * 0.03 + length_bonus
    return min(score, 0.95)


def _looks_low_value(question: str, answer: str) -> bool:
    if len(answer) < 40:
        return True
    compact_question = " ".join(question.split())
    if any(re.match(pattern, compact_question, re.IGNORECASE) for pattern in LOW_VALUE_PATTERNS):
        return len(answer) < 160
    return False


def _summary_title(question: str) -> str:
    compact = re.sub(r"[#`*_>\[\]{}()（）《》\"'“”‘’]", "", question).strip()
    compact = re.sub(r"\s+", " ", compact)
    compact = compact.strip("，。！？,.!?:：;；- ")
    if not compact:
        return "桌宠自动总结"
    if len(compact) <= 28:
        return compact
    return compact[:28].rstrip() + "…"


def _summary_links(source_paths: tuple[str, ...]) -> tuple[str, ...]:
    links = ["[[Wiki/index.md]]", "[[Wiki/AGENTS.md]]"]
    links.extend(f"[[{path}]]" for path in source_paths)
    return tuple(links)


def _summary_markdown(
    *,
    title: str,
    question: str,
    answer: str,
    conversation_id: str,
    user_message_id: str,
    assistant_message_id: str,
    agent_run_id: str,
    diary_markdown_path: str | None,
    diary_object_ids: tuple[str, ...],
    source_paths: tuple[str, ...],
    key_points: list[str] | None = None,
) -> str:
    key_points = _key_points(answer) if key_points is None else key_points
    lines = [
        "## 来源摘要",
        "",
        "- 页面性质：单来源聊天摘要，不是多来源综合结论。",
        "- 摘要只保留回答中可复用的表述；原始来源仍以日记或触发消息为准。",
        "",
        "## 问题",
        "",
        question,
        "",
        "## 结论",
        "",
        *[f"- {point}" for point in key_points],
        "",
        "## 证据状态",
        "",
        "- 状态：待基于独立来源进一步综合。",
        "- 冲突或未验证的内容不会被提升为确定事实。",
        "",
        "## 来源",
        "",
        f"- 触发消息：`message:{user_message_id}`",
    ]
    if diary_markdown_path:
        lines.append(f"- 日记来源：[[{diary_markdown_path}]]")
    lines.extend(
        [
            f"- conversation_id：`{conversation_id}`",
            f"- assistant_message_id：`{assistant_message_id}`",
            f"- agent_run_id：`{agent_run_id}`",
        ]
    )
    if diary_object_ids:
        lines.extend(["", "## 结构化证据", "", *[f"- `{item}`" for item in diary_object_ids]])
    lines.extend(
        [
            "",
            "## 更新记录",
            "",
            f"- 触发消息：`message:{user_message_id}`",
            "- 页面写入、索引和集中日志的最终状态以动作回执及权威读回为准。",
        ]
    )
    return "\n".join(lines).strip()


def _key_points(answer: str) -> list[str]:
    lines = []
    for raw_line in answer.splitlines():
        line = raw_line.strip(" -\t")
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    if len(lines) < 2:
        lines = [part.strip() for part in re.split(r"[。！？.!?]\s*", answer) if part.strip()]
    points = [_truncate(point, 120) for point in lines[:4]]
    return points or ["本轮回答包含可复用知识，已按证据和日志规则沉淀到 Wiki。"]


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "..."


def _clean_text(value: str) -> str:
    return value.strip().replace("\r\n", "\n").replace("\r", "\n")
