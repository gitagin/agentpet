from __future__ import annotations

import re

from app.models.enums import AgentIntent

from .state import AgentRoute


_TASK_PATTERNS = (
    r"\b(remind me|reminder|todo|to-do|task|due)\b",
    r"(?:\u63d0\u9192\u6211|\u63d0\u9192|\u5f85\u529e|\u4efb\u52a1|\u5230\u671f|\u622a\u6b62|\u5b89\u6392)",
    r"(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,4})\s*(?:秒钟|秒|分钟|小时)\s*后.*(?:提醒我|提醒)",
)
_PROPOSE_MEMORY_PATTERNS = (
    r"\b(remember this|remember that|remember:|please remember|save this memory)\b",
    r"(?:\u8bb0\u4f4f|\u8bf7\u8bb0\u5f97|\u5e2e\u6211\u8bb0\u5f97|\u4fdd\u5b58\u8bb0\u5fc6|\u52a0\u5165\u8bb0\u5fc6|\u957f\u671f\u504f\u597d|\u957f\u671f\u8bb0\u5fc6|\u4fdd\u5b58\u4e0b\u6765)",
)
_SEARCH_PATTERNS = (
    r"\b(search memory|search memories|find in memory|lookup memory|search notes|search docs|what do you remember|recall)\b",
    r"(?:\u641c\u7d22\u8bb0\u5fc6|\u67e5\u627e\u8bb0\u5fc6|\u68c0\u7d22\u8bb0\u5fc6|\u67e5\u4e00\u4e0b\u8bb0\u5fc6|\u67e5\u4e00\u4e0b\u77e5\u8bc6\u5e93|\u4f60\u8bb0\u5f97\u4ec0\u4e48|\u4f60\u8bb0\u5f97\u6211|\u56de\u5fc6\u4e00\u4e0b|\u77e5\u8bc6\u5e93\u91cc|\u7b14\u8bb0\u91cc|\u6587\u6863\u91cc|\u4e4b\u524d\u8bb0\u5f55)",
)
_WIKI_MANAGEMENT_PATTERNS = (
    r"\b(add to wiki|update wiki|create wiki page|organize into wiki|save to knowledge base|archive to wiki)\b",
    r"(?:\u5199\u5165\s*wiki|\u66f4\u65b0\s*wiki|\u521b\u5efa\s*wiki\s*\u9875\u9762|\u6574\u7406\u5230\s*wiki|\u4fdd\u5b58\u5230\u77e5\u8bc6\u5e93|\u5f52\u6863\u5230\u77e5\u8bc6\u5e93|\u6574\u7406\u5230\u77e5\u8bc6\u5e93|\u5199\u5165\u77e5\u8bc6\u5e93)",
)
_MEMORY_RECALL_MARKERS = (
    "\u4f60\u8bb0\u5f97",
    "\u8bb0\u5f97\u6211",
    "\u4e4b\u524d\u8bb0\u5f55",
    "\u56de\u5fc6\u4e00\u4e0b",
    "\u8bb0\u5fc6\u4e2d",
    "\u8bb0\u5fc6\u91cc",
)
_DAILY_CHAT_MARKERS = (
    "\u6211\u8bf4\u4e86\u4ec0\u4e48",
    "\u6211\u4eec\u8bf4\u4e86\u4ec0\u4e48",
    "\u54b1\u4eec\u8bf4\u4e86\u4ec0\u4e48",
    "\u804a\u4e86\u4ec0\u4e48",
    "\u95ee\u4e86\u4ec0\u4e48",
    "\u63d0\u4e86\u4ec0\u4e48",
    "\u8bf4\u8fc7\u4ec0\u4e48",
)


def route_intent(message: str) -> AgentRoute:
    normalized = " ".join(message.strip().lower().split())
    if not normalized:
        return AgentRoute(
            intent=AgentIntent.CHAT,
            confidence=0.0,
            reason="empty message defaults to chat",
        )

    if _matches_any(_WIKI_MANAGEMENT_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.MANAGE_WIKI,
            confidence=0.94,
            reason="explicit wiki management command",
        )

    if _matches_any(_PROPOSE_MEMORY_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.PROPOSE_MEMORY,
            confidence=0.95,
            reason="explicit memory proposal command",
        )

    if _matches_any(_TASK_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.CREATE_TASK,
            confidence=0.9,
            reason="explicit task or reminder command",
        )

    if _is_daily_chat_recall_query(message) or _is_memory_recall_query(message):
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.82,
            reason="context recall question",
        )

    if _matches_any(_SEARCH_PATTERNS, normalized):
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.9,
            reason="explicit memory or knowledge search command",
        )

    question_about_memory = re.search(r"\b(memory|memories|remember)\b", normalized)
    if question_about_memory and "?" in message:
        return AgentRoute(
            intent=AgentIntent.SEARCH_MEMORY,
            confidence=0.72,
            reason="memory-related question",
        )

    return AgentRoute(
        intent=AgentIntent.CHAT,
        confidence=0.55,
        reason="default desktop-pet chat path",
    )


def _matches_any(patterns: tuple[str, ...], message: str) -> bool:
    return any(re.search(pattern, message, re.IGNORECASE) for pattern in patterns)


def _is_memory_recall_query(message: str) -> bool:
    return any(marker in message for marker in _MEMORY_RECALL_MARKERS)


def _is_daily_chat_recall_query(message: str) -> bool:
    if not re.search(r"\d{1,2}\s*\u6708\s*\d{1,2}\s*(?:\u53f7|\u65e5)?", message):
        return False
    return any(marker in message for marker in _DAILY_CHAT_MARKERS)
