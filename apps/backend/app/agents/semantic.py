from __future__ import annotations

import json
import re
from html import unescape

from app.models.enums import AgentIntent

from .runtime_helpers import _strip_search_command
from .state import AgentState, ClassifierResult, SemanticAnalysisResult

from app.utils.sqlite import extract_json_object

# 从 graph_runtime.py 迁移，原函数名：_parse_semantic_analysis, _extract_json_object, _fallback_semantic_analysis, _fallback_source_scope, _forced_source_scope, _is_daily_chat_date_recall, _parse_text_search_tool_call


def _parse_semantic_analysis(text: str, user_message: str) -> SemanticAnalysisResult:
    data = json.loads(extract_json_object(text, error_code="semantic_analysis_json_missing"))
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


def _parse_classifier_analysis(text: str, user_message: str) -> tuple[ClassifierResult, SemanticAnalysisResult]:
    data = json.loads(extract_json_object(text, error_code="semantic_analysis_json_missing"))
    if "intent" not in data:
        semantic = _semantic_from_legacy_payload(data, user_message)
        return _classifier_from_semantic(semantic), semantic

    classifier = ClassifierResult.model_validate(data)
    semantic = _semantic_from_classifier(classifier, user_message)
    return classifier, semantic




def _semantic_from_legacy_payload(data: dict[str, object], user_message: str) -> SemanticAnalysisResult:
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


def _semantic_from_classifier(classifier: ClassifierResult, user_message: str) -> SemanticAnalysisResult:
    if classifier.intent != "need_retrieval":
        return SemanticAnalysisResult(
            needs_context=False,
            source_scope="none",
            query=classifier.retrieval_query or user_message,
            answer_style="casual" if classifier.intent == "chat" else "concise",
            confidence=classifier.confidence,
            reason=classifier.reason or "classifier_action_or_chat",
        )
    source_scope = _semantic_scope_from_classifier_scope(classifier.retrieval_scope)
    return SemanticAnalysisResult(
        needs_context=source_scope != "none",
        source_scope=source_scope,
        query=(classifier.retrieval_query or user_message).strip(),
        answer_style="grounded",
        confidence=classifier.confidence,
        reason=classifier.reason or "classifier_retrieval",
    )


def _classifier_from_semantic(semantic: SemanticAnalysisResult) -> ClassifierResult:
    if semantic.needs_context and semantic.source_scope != "none":
        return ClassifierResult(
            intent="need_retrieval",
            retrieval_scope=_classifier_scope_from_semantic_scope(semantic.source_scope),
            retrieval_query=semantic.query,
            confidence=semantic.confidence,
            reason=semantic.reason,
        )
    return ClassifierResult(
        intent="chat",
        retrieval_query=None,
        confidence=semantic.confidence,
        reason=semantic.reason,
    )


def _semantic_scope_from_classifier_scope(scope: str | None) -> str:
    if scope == "both":
        return "all"
    if scope in {"personal_memory", "knowledge_base"}:
        return scope
    return "none"


def _classifier_scope_from_semantic_scope(scope: str) -> str | None:
    if scope == "all":
        return "both"
    if scope in {"personal_memory", "knowledge_base"}:
        return scope
    if scope in {"daily_chat", "diary_objects"}:
        return "personal_memory"
    return None


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


def _fallback_classifier(state: AgentState) -> ClassifierResult:
    semantic = state.semantic_analysis or _fallback_semantic_analysis(state)
    if state.route and state.route.intent == AgentIntent.PROPOSE_MEMORY:
        return ClassifierResult(
            intent="action",
            action_type="memory_proposal",
            action_params={"content": state.user_message},
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    if state.route and state.route.intent == AgentIntent.MANAGE_WIKI:
        return ClassifierResult(
            intent="action",
            action_type="wiki",
            action_params={"content": state.user_message},
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    if state.route and state.route.intent == AgentIntent.CREATE_TASK:
        return ClassifierResult(
            intent="action",
            action_type="task",
            action_params={"source_text": state.user_message},
            confidence=state.route.confidence,
            reason=state.route.reason,
        )
    return _classifier_from_semantic(semantic)


def _fallback_source_scope(message: str) -> str:
    forced_scope = _forced_source_scope(message)
    if forced_scope is not None:
        return forced_scope
    normalized = message.casefold()
    if re.search(r"\d{1,2}\s*月\s*\d{1,2}\s*(号|日)?", message) or "之前" in message or "回忆" in message:
        return "daily_chat"
    if "知识库" in message or "文档" in message or "笔记" in message or "docs" in normalized:
        return "knowledge_base"
    if any(marker in message for marker in ("你记得我", "记得我")):
        return "personal_memory"
    # 「我喜欢X / 我偏好X」是"告知偏好"的陈述句，不是检索请求；
    # 只有带疑问词/问号时才算"询问我的偏好"（与 memory_router 保持一致）。
    if any(marker in message for marker in ("我喜欢", "我偏好", "我的喜好", "我的偏好", "我最喜欢", "我常用")):
        if any(signal in message for signal in ("吗", "什么", "哪些", "是不是", "有没有", "呢", "？", "?")):
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
