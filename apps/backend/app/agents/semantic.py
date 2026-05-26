from __future__ import annotations

import json
import re
from html import unescape

from app.models.enums import AgentIntent

from .runtime_helpers import _strip_search_command
from .state import AgentState, SemanticAnalysisResult

# 从 graph_runtime.py 迁移，原函数名：_parse_semantic_analysis, _extract_json_object, _fallback_semantic_analysis, _fallback_source_scope, _forced_source_scope, _is_daily_chat_date_recall, _parse_text_search_tool_call


def _parse_semantic_analysis(text: str, user_message: str) -> SemanticAnalysisResult:
    data = json.loads(_extract_json_object(text))
    result = SemanticAnalysisResult.model_validate(data)
    forced_scope = _forced_source_scope(user_message)
    if forced_scope is not None:
        return result.model_copy(
            update={
                "needs_context": True,
                "source_scope": forced_scope,
                "query": user_message,
                "answer_style": "grounded",
                "reason": "forced_date_or_memory_scope",
            }
        )
    if result.needs_context and not result.query.strip():
        return result.model_copy(update={"query": user_message})
    return result


def _extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("semantic_analysis_json_missing")
    return text[start : end + 1]


def _fallback_semantic_analysis(state: AgentState) -> SemanticAnalysisResult:
    source_scope = _fallback_source_scope(state.user_message)
    if source_scope != "none":
        return SemanticAnalysisResult(
            needs_context=True,
            source_scope=source_scope,
            query=_strip_search_command(state.user_message),
            answer_style="grounded",
            confidence=state.route.confidence if state.route else 0.65,
            reason=state.route.reason if state.route else "fallback_context",
        )
    if state.route and state.route.intent == AgentIntent.SEARCH_MEMORY:
        return SemanticAnalysisResult(
            needs_context=True,
            source_scope="all",
            query=_strip_search_command(state.user_message),
            answer_style="grounded",
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    if state.route and state.route.intent == AgentIntent.MANAGE_WIKI:
        return SemanticAnalysisResult(
            needs_context=False,
            source_scope="none",
            query=state.user_message,
            answer_style="concise",
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    return SemanticAnalysisResult(
        needs_context=False,
        source_scope="none",
        query=state.user_message,
        answer_style="casual",
        confidence=0.4,
        reason="fallback_chat",
    )


def _fallback_source_scope(message: str) -> str:
    forced_scope = _forced_source_scope(message)
    if forced_scope is not None:
        return forced_scope
    normalized = message.casefold()
    if re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*(号|日)?", message) or "之前" in message or "回忆" in message:
        return "daily_chat"
    if "知识库" in message or "文档" in message or "笔记" in message or "docs" in normalized:
        return "knowledge_base"
    if any(marker in message for marker in ("我喜欢", "我偏好", "我的喜好", "我的偏好", "你记得我", "记得我")):
        return "personal_memory"
    return "none"


def _forced_source_scope(message: str) -> str | None:
    if _is_daily_chat_date_recall(message):
        return "daily_chat"
    return None


def _is_daily_chat_date_recall(message: str) -> bool:
    if not re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*(?:号|日)?", message):
        return False
    markers = (
        "我说了什么",
        "我们说了什么",
        "咱们说了什么",
        "聊了什么",
        "问了什么",
        "提了什么",
        "说过什么",
        "什么事情",
        "什么事",
    )
    return any(marker in message for marker in markers)


def _parse_text_search_tool_call(text: str) -> str | None:
    if "<tool_call" not in text.casefold():
        return None
    tool_name = re.search(
        r"<function\s*=\s*['\"]?(search_memory|search_notes|search_docs)['\"]?\s*>",
        text,
        re.IGNORECASE,
    )
    if tool_name is None:
        return None
    query = re.search(
        r"<parameter\s*=\s*['\"]?query['\"]?\s*>(.*?)</parameter>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if query is None:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", query.group(1))).strip()
