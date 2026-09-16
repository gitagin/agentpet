from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field


MemoryScope = Literal[
    "none",
    "graph_facts",
    "knowledge_base",
    "personal_memory",
    "diary_objects",
    "daily_chat",
]
MemoryAnswerStyle = Literal["casual", "concise", "grounded", "clarifying"]


_EXPLICIT_READ_SCOPE_MARKERS: dict[MemoryScope, tuple[str, ...]] = {
    "knowledge_base": (
        "knowledge base",
        "knowledge-base",
        "知识库",
        "资料库",
        "wiki",
    ),
    "personal_memory": (
        "personal memory",
        "long-term memory",
        "long term memory",
        "长期记忆",
        "记忆本",
    ),
    "daily_chat": (
        "daily chat",
        "chat diary",
        "聊天日记",
        "聊天记录",
        "每日聊天",
    ),
}
_READ_REQUEST_MARKERS = (
    "?",
    "？",
    "what",
    "which",
    "find",
    "search",
    "show",
    "list",
    "lookup",
    "什么",
    "哪些",
    "有没有",
    "有多少",
    "中有",
    "里有",
    "查",
    "搜",
    "找",
    "列出",
    "看看",
)
_MUTATION_REQUEST_MARKERS = (
    "add to",
    "archive to",
    "create",
    "save to",
    "update",
    "write to",
    "保存到",
    "写入",
    "创建",
    "归档到",
    "整理到",
    "更新",
    "添加到",
)


class MemoryRoute(BaseModel):
    primary_scopes: tuple[MemoryScope, ...] = Field(default_factory=tuple)
    fallback_scopes: tuple[MemoryScope, ...] = Field(default_factory=tuple)
    query: str = ""
    answer_style: MemoryAnswerStyle = "casual"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    semantic_fallback: bool = False
    retrieval_top_k: int = Field(default=5, ge=1, le=20)

    @property
    def all_scopes(self) -> tuple[MemoryScope, ...]:
        return _dedupe_scopes((*self.primary_scopes, *self.fallback_scopes))

    @property
    def legacy_source_scope(self) -> Literal["none", "personal_memory", "daily_chat", "knowledge_base", "all"]:
        """Best-effort bridge for the current single-scope retrieval contract."""
        legacy_scopes = _dedupe_legacy_scopes(self.all_scopes)
        if not legacy_scopes:
            return "none"
        if "knowledge_base" in legacy_scopes and len(legacy_scopes) == 1:
            return "knowledge_base"
        if "personal_memory" in legacy_scopes and len(legacy_scopes) == 1:
            return "personal_memory"
        if "daily_chat" in legacy_scopes and len(legacy_scopes) == 1:
            return "daily_chat"
        return "all"


class MemoryRouter:
    """Deterministic routing policy for future multi-scope memory retrieval."""

    def route(self, message: str) -> MemoryRoute:
        query = _clean_query(message)
        if not query:
            return MemoryRoute(
                primary_scopes=("none",),
                query="",
                answer_style="clarifying",
                confidence=0.0,
                reason="empty_query",
            )

        normalized = query.casefold()

        if _is_explicit_date_recall(query, normalized):
            return MemoryRoute(
                primary_scopes=("daily_chat",),
                fallback_scopes=("diary_objects", "personal_memory"),
                query=query,
                answer_style="grounded",
                confidence=0.92,
                reason="explicit_date_recall",
                retrieval_top_k=20,
            )

        if _is_recent_chat_recall_query(query, normalized):
            return MemoryRoute(
                primary_scopes=("daily_chat",),
                fallback_scopes=("diary_objects", "personal_memory"),
                query=query,
                answer_style="grounded",
                confidence=0.85,
                reason="recent_chat_recall",
                retrieval_top_k=12,
            )

        explicit_scope = explicit_memory_read_scope(query)
        if explicit_scope is not None:
            return MemoryRoute(
                primary_scopes=(explicit_scope,),
                fallback_scopes=("none",),
                query=query,
                answer_style="grounded",
                confidence=0.96,
                reason=f"explicit_{explicit_scope}_scope",
            )

        if _is_long_term_preference_query(query, normalized):
            return MemoryRoute(
                primary_scopes=("graph_facts", "personal_memory"),
                fallback_scopes=("diary_objects", "daily_chat"),
                query=query,
                answer_style="grounded",
                confidence=0.88,
                reason="long_term_preference",
            )

        if _is_personal_experience_or_emotional_continuity(query, normalized):
            return MemoryRoute(
                primary_scopes=("diary_objects",),
                fallback_scopes=("daily_chat",),
                query=query,
                answer_style="grounded",
                confidence=0.84,
                reason="personal_experience_or_emotional_continuity",
            )

        if _is_technical_knowledge_query(query, normalized):
            return MemoryRoute(
                primary_scopes=("knowledge_base",),
                fallback_scopes=("none",),
                query=query,
                answer_style="concise",
                confidence=0.86,
                reason="technical_knowledge",
            )

        if _is_ambiguous_memory_request(query, normalized):
            return MemoryRoute(
                primary_scopes=(),
                fallback_scopes=("knowledge_base", "personal_memory", "diary_objects", "daily_chat"),
                query=query,
                answer_style="clarifying",
                confidence=0.42,
                reason="ambiguous_memory_request_semantic_fallback",
                semantic_fallback=True,
            )

        return MemoryRoute(
            primary_scopes=("none",),
            query=query,
            answer_style="casual",
            confidence=0.62,
            reason="no_memory_context_needed",
        )


def route_memory(message: str) -> MemoryRoute:
    return MemoryRouter().route(message)


def explicit_memory_read_scope(message: str) -> MemoryScope | None:
    normalized = _clean_query(message).casefold()
    if not normalized or any(marker in normalized for marker in _MUTATION_REQUEST_MARKERS):
        return None
    if not any(marker in normalized for marker in _READ_REQUEST_MARKERS):
        return None
    matches = tuple(
        scope
        for scope, markers in _EXPLICIT_READ_SCOPE_MARKERS.items()
        if any(marker in normalized for marker in markers)
    )
    return matches[0] if len(matches) == 1 else None


def _clean_query(message: str) -> str:
    return " ".join(message.strip().split())


def _dedupe_scopes(scopes: tuple[MemoryScope, ...]) -> tuple[MemoryScope, ...]:
    seen: set[MemoryScope] = set()
    result: list[MemoryScope] = []
    for scope in scopes:
        if scope in seen:
            continue
        seen.add(scope)
        result.append(scope)
    return tuple(result)


def _dedupe_legacy_scopes(
    scopes: tuple[MemoryScope, ...],
) -> tuple[Literal["personal_memory", "daily_chat", "knowledge_base"], ...]:
    seen: set[Literal["personal_memory", "daily_chat", "knowledge_base"]] = set()
    mapped: list[Literal["personal_memory", "daily_chat", "knowledge_base"]] = []
    for scope in scopes:
        if scope in {"none"}:
            continue
        if scope in {"graph_facts", "diary_objects"}:
            legacy_scope: Literal["personal_memory", "daily_chat", "knowledge_base"] = "daily_chat"
            if scope == "graph_facts":
                legacy_scope = "personal_memory"
        else:
            legacy_scope = scope
        if legacy_scope in seen:
            continue
        seen.add(legacy_scope)
        mapped.append(legacy_scope)
    return tuple(mapped)


def _is_explicit_date_recall(query: str, normalized: str) -> bool:
    if not _has_date_reference(query, normalized):
        return False
    recall_markers = (
        "what did i say",
        "what did we say",
        "what did i tell you",
        "what did we talk",
        "what did i ask",
        "what happened to me",
        "our conversation",
        "chat",
        "conversation",
        "recall",
        "remember",
        "\u6211\u8bf4\u4e86\u4ec0\u4e48",
        "\u6211\u4eec\u8bf4\u4e86\u4ec0\u4e48",
        "\u54b1\u4eec\u8bf4\u4e86\u4ec0\u4e48",
        "\u804a\u4e86\u4ec0\u4e48",
        "\u804a\u5929\u8bb0\u5f55",
        "\u95ee\u4e86\u4ec0\u4e48",
        "\u63d0\u4e86\u4ec0\u4e48",
        "\u8bf4\u4e86\u4ec0\u4e48",
        "\u8bf4\u8fc7\u4ec0\u4e48",
        "\u8bb0\u5f55\u4e86\u4ec0\u4e48",
        "\u6709\u4ec0\u4e48\u8bb0\u5f55",
        "\u4ec0\u4e48\u4e8b\u60c5",
        "\u56de\u5fc6",
        "\u8bb0\u5f97",
    )
    return any(marker in normalized or marker in query for marker in recall_markers)


def _has_date_reference(query: str, normalized: str) -> bool:
    relative_date_markers = (
        "前天",
        "昨天",
        "今天",
        "今日",
        "明天",
        "后天",
        "day before yesterday",
        "yesterday",
        "today",
        "tomorrow",
        "day after tomorrow",
    )
    if any(marker in query or marker in normalized for marker in relative_date_markers):
        return True
    month_names = (
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
    )
    if re.search(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b", normalized):
        return True
    if re.search(r"\b\d{1,2}[-/]\d{1,2}(?:[-/]\d{2,4})?\b", normalized):
        return True
    if re.search(rf"\b(?:{'|'.join(month_names)})\.?\s+\d{{1,2}}(?:,\s*\d{{4}})?\b", normalized):
        return True
    if re.search(r"\d{1,2}\s*\u6708\s*\d{1,2}\s*(?:\u53f7|\u65e5)?", query):
        return True
    return False


_RECENT_CHAT_TIME_MARKERS = (
    "刚刚",
    "刚才",
    "刚",
    "之前",
    "上次",
    "昨晚",
    "刚才那会儿",
)
_RECENT_CHAT_VERB_MARKERS = (
    "说",
    "聊",
    "讲",
    "问",
    "提",
    "讨论",
    "talk",
    "say",
    "mention",
    "chat",
    "ask",
    "discuss",
)
_RECENT_CHAT_INTERROGATIVES = (
    "什么",
    "啥",
    "哪些",
    "怎么",
    "吗",
    "what",
    "said",
    "say",
    "talk",
    "chat",
)


def _is_recent_chat_recall_query(query: str, normalized: str) -> bool:
    """Catch colloquial "what did I just say" queries without dates or
    explicit memory markers: 我刚刚说了什么 / 我刚才聊了什么 / 我之前说过什么."""
    has_time = any(marker in query or marker in normalized for marker in _RECENT_CHAT_TIME_MARKERS)
    if not has_time:
        return False
    has_verb = any(marker in normalized or marker in query for marker in _RECENT_CHAT_VERB_MARKERS)
    if not has_verb:
        return False
    return any(marker in query or marker in normalized for marker in _RECENT_CHAT_INTERROGATIVES)


_PREFERENCE_QUESTION_SIGNALS = (
    "\u5417",
    "\u4ec0\u4e48",
    "\u54ea\u4e9b",
    "\u662f\u4e0d\u662f",
    "\u6709\u6ca1\u6709",
    "\u5462",
    "\uff1f",
    "?",
)


def _has_preference_question_signal(query: str, normalized: str) -> bool:
    return any(signal in query or signal in normalized for signal in _PREFERENCE_QUESTION_SIGNALS)


def _is_long_term_preference_query(query: str, normalized: str) -> bool:
    english_markers = (
        "my preference",
        "my preferences",
        "my preferred",
        "do i prefer",
        "what do i prefer",
        "what i prefer",
        "my favorite",
        "my favourite",
        "do i like",
        "what do i like",
        "my writing style",
        "my coding style",
        "my long-term",
        "long term preference",
        "long-term preference",
        "profile",
    )
    remember_my = (
        "remember my",
        "know about my",
        "what do you know about my",
        "\u8bb0\u5f97\u6211",
        "\u4f60\u8bb0\u5f97\u6211",
    )
    if any(marker in normalized or marker in query for marker in english_markers):
        return True
    if any(marker in normalized or marker in query for marker in remember_my):
        return True
    # 中文「我喜欢X / 我偏好X」默认是"告知偏好"的陈述句，应走普通聊天，让回复后的
    # 抽取流水线把偏好记录下来；只有带疑问信号（吗/什么/是不是/问号…）时，才视为
    # "询问我的偏好"而触发检索——否则"我喜欢牛奶"会被回答成"没找到能引用的记录"。
    chinese_markers = (
        "\u6211\u559c\u6b22",
        "\u6211\u504f\u597d",
        "\u6211\u7684\u504f\u597d",
        "\u6211\u7684\u559c\u597d",
        "\u6211\u6700\u559c\u6b22",
        "\u6211\u5e38\u7528",
        "\u957f\u671f\u504f\u597d",
        "\u957f\u671f\u8bb0\u5fc6",
    )
    if any(marker in query for marker in chinese_markers):
        return _has_preference_question_signal(query, normalized)
    return False


def _is_personal_experience_or_emotional_continuity(query: str, normalized: str) -> bool:
    personal_markers = (
        "how i felt",
        "how was i feeling",
        "i felt",
        "i was sad",
        "i was anxious",
        "i was upset",
        "i was worried",
        "my mood",
        "my emotion",
        "my emotions",
        "personal experience",
        "what happened to me",
        "did i tell you",
        "remember when i",
        "last time i felt",
        "the situation with",
        "our last conversation about",
        "\u6211\u5f53\u65f6\u611f\u89c9",
        "\u6211\u611f\u5230",
        "\u6211\u96be\u8fc7",
        "\u6211\u7126\u8651",
        "\u6211\u62c5\u5fc3",
        "\u6211\u7684\u60c5\u7eea",
        "\u6211\u7684\u7ecf\u5386",
        "\u6211\u8ddf\u4f60\u8bf4\u8fc7",
    )
    continuity_markers = (
        "remember",
        "recall",
        "last time",
        "before",
        "earlier",
        "\u8bb0\u5f97",
        "\u56de\u5fc6",
        "\u4e0a\u6b21",
        "\u4e4b\u524d",
    )
    if any(marker in normalized or marker in query for marker in personal_markers):
        return True
    return any(marker in normalized or marker in query for marker in continuity_markers) and any(
        marker in normalized
        for marker in ("felt", "feeling", "mood", "emotion", "sad", "anxious", "worried")
    )


def _is_technical_knowledge_query(query: str, normalized: str) -> bool:
    question_markers = (
        "how do i",
        "how to",
        "what is",
        "what are",
        "why does",
        "explain",
        "debug",
        "implement",
        "difference between",
        "best practice",
        "api",
        "docs",
        "documentation",
        "wiki",
        "knowledge base",
        "\u5982\u4f55",
        "\u600e\u4e48",
        "\u89e3\u91ca",
        "\u4ec0\u4e48\u662f",
        "\u77e5\u8bc6\u5e93",
        "\u6587\u6863",
    )
    technical_terms = (
        "python",
        "typescript",
        "javascript",
        "react",
        "electron",
        "fastapi",
        "sql",
        "sqlite",
        "database",
        "schema",
        "migration",
        "api",
        "http",
        "pytest",
        "vite",
        "node",
        "package",
        "library",
        "framework",
        "algorithm",
        "exception",
        "stack trace",
        "error",
        "bug",
        "code",
        "\u4ee3\u7801",
        "\u62a5\u9519",
        "\u9519\u8bef",
        "\u63a5\u53e3",
        "\u6570\u636e\u5e93",
        "\u7b97\u6cd5",
        "\u6846\u67b6",
    )
    has_question_marker = any(marker in normalized or marker in query for marker in question_markers)
    has_technical_term = any(term in normalized or term in query for term in technical_terms)
    return has_question_marker and has_technical_term


def _is_ambiguous_memory_request(query: str, normalized: str) -> bool:
    markers = (
        "remember",
        "memory",
        "memories",
        "recall",
        "context",
        "earlier",
        "before",
        "last time",
        "previous",
        "\u8bb0\u5f97",
        "\u8bb0\u5fc6",
        "\u56de\u5fc6",
        "\u4e0a\u4e0b\u6587",
        "\u4e4b\u524d",
        "\u4e0a\u6b21",
    )
    return any(marker in normalized or marker in query for marker in markers)
