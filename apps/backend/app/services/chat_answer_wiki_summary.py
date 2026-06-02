from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.models.api import WikiPageResponse, WikiPageWriteRequest
from app.services.agent_actions import markdown_snapshot
from app.services.memory_policy import evaluate_memory_content
from app.services.wiki import WikiService, slugify_wiki_title


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


@dataclass(frozen=True)
class ChatAnswerWikiSummaryWriteResult:
    page: WikiPageResponse
    before_snapshot: dict[str, object]
    after_snapshot: dict[str, object]


class ChatAnswerWikiSummaryService:
    """Distill useful completed chat answers into auditable Wiki pages."""

    def __init__(self, wiki: WikiService) -> None:
        self.wiki = wiki

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

    def write(self, plan: ChatAnswerWikiSummaryPlan, *, source_message_id: str) -> ChatAnswerWikiSummaryWriteResult:
        before = markdown_snapshot(self.wiki.writer, [plan.target_path])
        page = self.wiki.write_page(
            WikiPageWriteRequest(
                title=plan.title,
                content=plan.content,
                operation="replace_section",
                target_path=plan.target_path,
                section="自动总结",
                tags=list(plan.tags),
                links=list(plan.links),
                source_message_id=source_message_id,
                page_type="synthesis",
                confidence="medium",
                authors=["chat_answer_wiki_summary_agent"],
                sources=list(plan.source_paths),
            )
        )
        self.wiki.refresh_index()
        self.wiki.append_log(
            "auto-summary",
            plan.title,
            "\n".join(
                [
                    f"- 页面：`{page.relative_path}`",
                    f"- 触发消息：`{source_message_id}`",
                    f"- 置信度：{plan.confidence:.2f}",
                    f"- 来源路径：{len(plan.source_paths)}",
                ]
            ),
        )
        after = markdown_snapshot(self.wiki.writer, [plan.target_path])
        return ChatAnswerWikiSummaryWriteResult(page=page, before_snapshot=before, after_snapshot=after)


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
) -> str:
    key_points = _key_points(answer)
    source_link = f"[[{diary_markdown_path}]]" if diary_markdown_path else "`未生成日记路径`"
    related = ["[[Wiki/index.md]]", "[[Wiki/AGENTS.md]]", *[f"[[{path}]]" for path in source_paths]]
    return "\n".join(
        [
            "### 核心定义",
            "",
            f"- {title}：桌宠根据本轮用户输入和回复自动提炼出的可复用知识。该内容是整理性总结，不是原始日记的逐字摘录。",
            "",
            "### 核心要点",
            "",
            *[f"- {point}" for point in key_points],
            "",
            "### 经典案例",
            "",
            f"- 用户提出：{question}",
            f"- 桌宠回答后，把本轮交互先归档到日记，再提炼为这个 Wiki 知识页。",
            "",
            "### 实践方法",
            "",
            "1. 先按用户意图检索日记、长期记忆和 Wiki。",
            "2. 回答用户时只使用可解释的上下文。",
            "3. 回答完成后写入每日聊天日记和结构化日记对象。",
            "4. 对本轮回答做自我总结，只把可复用、非敏感、有出处的内容沉淀到 Wiki。",
            "5. 写入后更新索引、追加集中日志，并保留活动账本用于撤销。",
            "",
            "### 常见误区",
            "",
            "- 不要把原始日记或来源文件改写成整理后的观点。",
            "- 不要把没有出处的推断伪装成原文事实。",
            "- 不要为普通寒暄、短句确认或敏感凭据创建 Wiki 页面。",
            "",
            "### 相关知识点",
            "",
            *[f"- {link}" for link in related],
            "",
            "### 原文出处",
            "",
            f"- 触发来源：用户查询 `message:{user_message_id}`。",
            f"- 日记出处：{source_link}。",
            f"- conversation_id：`{conversation_id}`。",
            f"- assistant_message_id：`{assistant_message_id}`。",
            f"- agent_run_id：`{agent_run_id}`。",
            f"- 结构化日记对象：{', '.join(f'`{item}`' for item in diary_object_ids) if diary_object_ids else '`无`'}。",
            "- 证据说明：以上内容是基于本轮问答的整理性推断；若与原始日记冲突，以原始日记为准并标记矛盾。",
            "",
            "### 对用户/决策的意义",
            "",
            "- 用户只需要对桌宠自然输入；桌宠负责检索、回答、归档、总结和维护 Wiki。",
            "- 自动沉淀必须可追踪、可撤销、可解释，普通整理不打断对话。",
            "",
            "### 更新日志",
            "",
            "| 日期 | 操作类型 | 触发来源 | 变更内容 |",
            "| --- | --- | --- | --- |",
            f"| 自动生成 | 创建 | 用户查询 `{user_message_id}` | 从聊天回答生成 Wiki 自动总结 |",
            "",
            "### 自检清单",
            "",
            "- [x] 索引同步：写入后调用 Wiki index refresh。",
            "- [x] 关键词同步：标题、标签和来源写入 frontmatter。",
            "- [x] 关系图谱：保留 Wiki/index、Wiki/AGENTS 与日记来源链接。",
            "- [x] 入链检查：新页至少进入索引，并通过后续 lint 检查补足上下文入链。",
            "- [x] AGENTS 同步：遵守 Wiki/AGENTS 的只读来源和证据规则。",
            "- [x] 内嵌日志：页面含更新日志。",
            "- [x] 集中日志：写入 Wiki/log.md。",
        ]
    ).strip()


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
