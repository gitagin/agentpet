from __future__ import annotations

import inspect
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Callable
from zoneinfo import ZoneInfo

from app.services.memory import SafeMarkdownWriter
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore, MemoryGraphWriteResult
from app.services.memory_policy import evaluate_memory_content
from app.services.write_policy import MarkdownWritePolicyRequest, evaluate_markdown_write
from app.utils.hash import sha256_hex
DEFAULT_LONG_TERM_MEMORY_TIMEZONE = "Asia/Shanghai"

logger = logging.getLogger(__name__)

PREFERENCES_PATH = "Memories/LongTerm/Preferences.md"
PROFILE_PATH = "Memories/LongTerm/Profile.md"


@dataclass(frozen=True)
class LongTermMemoryWriteResult:
    written: bool
    target_path: str | None = None
    index_job_id: str | None = None
    reason: str | None = None
    graph_fact_id: str | None = None
    graph_status: str | None = None


@dataclass(frozen=True)
class LongTermMemoryCandidate:
    target_path: str
    category: str
    subject: str
    value: str
    source_text: str
    predicate: str = "is"
    confidence: float = 0.85
    memory_type: str | None = None
    entity_type: str | None = None
    importance: float = 0.5
    metadata_json: str | None = None


class LongTermMemoryService:
    def __init__(
        self,
        writer: SafeMarkdownWriter,
        *,
        timezone_name: str = DEFAULT_LONG_TERM_MEMORY_TIMEZONE,
        now_provider: Callable[[], datetime] | None = None,
        index_refresh: Callable[[str], str | None] | None = None,
        graph_store: MemoryGraphStore | None = None,
        extraction_model: object | None = None,
        extraction_model_name: str | None = None,
    ) -> None:
        self.writer = writer
        self.timezone = ZoneInfo(timezone_name)
        self.now_provider = now_provider
        self.index_refresh = index_refresh
        self.graph_store = graph_store
        self.extraction_model = extraction_model
        self.extraction_model_name = extraction_model_name

    def close(self) -> None:
        if self.graph_store is not None:
            self.graph_store.close()

    def remember_from_user_message(
        self,
        user_message: str,
        *,
        conversation_id: str,
        user_message_id: str,
        agent_run_id: str,
    ) -> LongTermMemoryWriteResult:
        source_policy = evaluate_memory_content(user_message)
        if not source_policy.allowed:
            return LongTermMemoryWriteResult(written=False, reason=source_policy.reason)

        candidate = extract_long_term_memory_candidate(user_message)
        if candidate is None:
            model_result = self._remember_model_extracted_facts(
                user_message,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                agent_run_id=agent_run_id,
            )
            if model_result is not None:
                return model_result
            return LongTermMemoryWriteResult(written=False, reason="no_explicit_memory")
        sensitive_field = _sensitive_field_reason(candidate.subject)
        if sensitive_field is not None:
            return LongTermMemoryWriteResult(written=False, reason=sensitive_field)

        markdown = self._entry_markdown(
            candidate,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            agent_run_id=agent_run_id,
        )
        policy = evaluate_markdown_write(
            MarkdownWritePolicyRequest(
                scope="long_term_memory",
                target_path=candidate.target_path,
                title=candidate.subject,
                content=markdown,
                metadata={"category": candidate.category},
            )
        )
        if not policy.allowed:
            return LongTermMemoryWriteResult(written=False, reason=policy.reason)

        if self._already_recorded(candidate):
            graph_result = self._write_graph_fact(
                candidate,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                agent_run_id=agent_run_id,
            )
            return LongTermMemoryWriteResult(
                written=False,
                target_path=candidate.target_path,
                reason="already_recorded",
                graph_fact_id=graph_result.fact.id if graph_result else None,
                graph_status=graph_result.fact.status.value if graph_result else None,
            )

        graph_result = self._write_graph_fact(
            candidate,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            agent_run_id=agent_run_id,
        )

        header = self._header_for(candidate.target_path)
        if self.writer.current_hash(candidate.target_path) is None:
            markdown = f"{header}\n\n{markdown}"
        self.writer.append(candidate.target_path, markdown)
        index_job_id = self.index_refresh(candidate.target_path) if self.index_refresh else None
        return LongTermMemoryWriteResult(
            written=True,
            target_path=candidate.target_path,
            index_job_id=index_job_id,
            graph_fact_id=graph_result.fact.id if graph_result else None,
            graph_status=graph_result.fact.status.value if graph_result else None,
        )

    def _write_graph_fact(
        self,
        candidate: LongTermMemoryCandidate,
        *,
        conversation_id: str,
        user_message_id: str,
        agent_run_id: str,
    ) -> MemoryGraphWriteResult | None:
        if self.graph_store is None:
            return None
        return self.graph_store.upsert_candidate(
            MemoryFactCandidate(
                category=candidate.category,
                subject=candidate.subject,
                predicate=candidate.predicate,
                object=candidate.value,
                source_text=candidate.source_text,
                source_type="user_message",
                confidence=candidate.confidence,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                agent_run_id=agent_run_id,
                memory_type=candidate.memory_type,
                entity_type=candidate.entity_type,
                importance=candidate.importance,
                metadata_json=candidate.metadata_json,
            )
        )

    def _remember_model_extracted_facts(
        self,
        user_message: str,
        *,
        conversation_id: str,
        user_message_id: str,
        agent_run_id: str,
    ) -> LongTermMemoryWriteResult | None:
        if self.graph_store is None or self.extraction_model is None:
            return None
        candidates = _extract_model_long_term_candidates(
            self.extraction_model,
            user_message,
            model_name=self.extraction_model_name,
        )
        if not candidates:
            return None
        first_result = None
        inserted = False
        for candidate in candidates:
            sensitive_field = _sensitive_field_reason(candidate.subject)
            if sensitive_field is not None:
                continue
            if not evaluate_memory_content(candidate.source_text).allowed:
                continue
            result = self._write_graph_fact(
                candidate,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                agent_run_id=agent_run_id,
            )
            if result is None:
                continue
            first_result = first_result or result
            inserted = inserted or result.inserted
        if first_result is None:
            return None
        return LongTermMemoryWriteResult(
            written=inserted,
            reason=None if inserted else first_result.reason or "already_recorded",
            graph_fact_id=first_result.fact.id,
            graph_status=first_result.fact.status.value,
        )

    def _entry_markdown(
        self,
        candidate: LongTermMemoryCandidate,
        *,
        conversation_id: str,
        user_message_id: str,
        agent_run_id: str,
    ) -> str:
        local_now = self._local_now()
        entry_id = _candidate_hash(candidate)
        return "\n".join(
            [
                f"## {local_now:%Y-%m-%d %H:%M:%S}",
                "",
                f"- 类型：{candidate.category}",
                f"- 主题：{candidate.subject}",
                f"- 内容：用户的{candidate.subject}是{candidate.value}",
                f"- 来源原文：{candidate.source_text}",
                f"- memory_key：`{entry_id}`",
                f"- conversation_id：`{conversation_id}`",
                f"- user_message_id：`{user_message_id}`",
                f"- agent_run_id：`{agent_run_id}`",
                "",
            ]
        )

    def _local_now(self) -> datetime:
        current = self.now_provider() if self.now_provider is not None else datetime.now(self.timezone)
        if current.tzinfo is None:
            current = current.replace(tzinfo=self.timezone)
        return current.astimezone(self.timezone)

    def _header_for(self, target_path: str) -> str:
        if target_path == PREFERENCES_PATH:
            return "# Long-Term Preferences"
        return "# Long-Term Profile"

    def _already_recorded(self, candidate: LongTermMemoryCandidate) -> bool:
        target = self.writer.resolve_markdown_path(candidate.target_path)
        if not target.exists():
            return False
        text = target.read_text(encoding="utf-8")
        return f"memory_key：`{_candidate_hash(candidate)}`" in text


def extract_long_term_memory_candidate(user_message: str) -> LongTermMemoryCandidate | None:
    text = " ".join(user_message.strip().split())
    if not text:
        return None
    if not evaluate_memory_content(text).allowed:
        return LongTermMemoryCandidate(
            target_path=PROFILE_PATH,
            category="profile",
            subject="敏感内容",
            value=text,
            source_text=text,
        )

    preference = _extract_preference(text)
    if preference is not None:
        subject, value = preference
        return LongTermMemoryCandidate(
            target_path=PREFERENCES_PATH,
            category="preference",
            subject=subject,
            value=value,
            source_text=text,
        )

    profile = _extract_profile_fact(text)
    if profile is not None:
        subject, value = profile
        return LongTermMemoryCandidate(
            target_path=PROFILE_PATH,
            category="profile",
            subject=subject,
            value=value,
            source_text=text,
        )
    return None


def _extract_preference(text: str) -> tuple[str, str] | None:
    patterns = (
        r"我喜欢的(?P<subject>[\u4e00-\u9fffA-Za-z0-9_ -]{1,20})[是叫为:：](?P<value>[\u4e00-\u9fffA-Za-z0-9_ -]{1,40})",
        r"我的(?P<subject>[\u4e00-\u9fffA-Za-z0-9_ -]{1,20})(?:偏好|喜好)[是叫为:：](?P<value>[\u4e00-\u9fffA-Za-z0-9_ -]{1,40})",
        r"我(?:最)?喜欢(?P<value>[\u4e00-\u9fffA-Za-z0-9_ -]{1,40})",
        r"i like (?P<value>[A-Za-z0-9_ -]{1,40})",
        r"my favorite (?P<subject>[A-Za-z0-9_ -]{1,20}) is (?P<value>[A-Za-z0-9_ -]{1,40})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is None:
            continue
        subject = (match.groupdict().get("subject") or "偏好").strip(" ，。,.")
        value = match.group("value").strip(" ，。,.")
        if value and not _looks_like_question(text):
            return subject, value
    return None


def _extract_profile_fact(text: str) -> tuple[str, str] | None:
    match = re.search(
        r"我的(?P<subject>[\u4e00-\u9fffA-Za-z0-9_ -]{1,20})[是叫为:：](?P<value>[\u4e00-\u9fffA-Za-z0-9_ -]{1,40})",
        text,
        re.IGNORECASE,
    )
    if match is None or _looks_like_question(text):
        return None
    return match.group("subject").strip(" ，。,.") or "资料", match.group("value").strip(" ，。,.")


def _looks_like_question(text: str) -> bool:
    return any(marker in text for marker in ("?", "？", "什么", "多少", "吗", "怎么", "如何"))


def _candidate_hash(candidate: LongTermMemoryCandidate) -> str:
    normalized = "\n".join(
        [
            candidate.target_path.casefold().strip(),
            candidate.category.casefold().strip(),
            candidate.subject.casefold().strip(),
            candidate.value.casefold().strip(),
        ]
    )
    return sha256_hex(normalized)[:16]


def _sensitive_field_reason(subject: str) -> str | None:
    normalized = subject.casefold().replace(" ", "").replace("_", "-")
    credential_markers = (
        "apikey",
        "api-key",
        "token",
        "secret",
        "password",
        "passwd",
        "pwd",
        "密钥",
        "密码",
        "令牌",
        "凭证",
    )
    sensitive_domain_markers = (
        "身份证",
        "手机号",
        "电话",
        "住址",
        "地址",
        "位置",
        "健康",
        "疾病",
        "诊断",
        "用药",
        "财务",
        "收入",
        "工资",
        "银行",
        "银行卡",
        "法律",
        "诉讼",
        "情绪",
        "抑郁",
        "焦虑",
        "自杀",
        "关系",
        "伴侣",
        "家人",
    )
    if any(marker in normalized for marker in credential_markers):
        return "sensitive_field"
    if any(marker in normalized for marker in sensitive_domain_markers):
        return "sensitive_life_domain"
    return None


LONG_TERM_EXTRACTION_SYSTEM_PROMPT = (
    "You extract durable long-term user memory facts. Return JSON only as an array or "
    "{\"facts\":[...]}. At most 5 facts. Each fact must include category, subject, "
    "predicate, object, source_text, confidence, memory_type, entity_type, importance. "
    "Use short strings. Return [] when the message has no durable preference, profile, "
    "goal, habit, relationship, event, or emotional continuity fact."
)


def _extract_model_long_term_candidates(
    model: object,
    user_message: str,
    *,
    model_name: str | None,
) -> list[LongTermMemoryCandidate]:
    try:
        response = model.complete(
            user_message=(
                "Extract long-term memory facts from this user message. JSON only.\n\n"
                f"user_message:\n{user_message}"
            ),
            system_prompt=LONG_TERM_EXTRACTION_SYSTEM_PROMPT,
        )
        text = _await_if_needed_sync(response)
        payload = _parse_json_payload(str(text))
    except Exception:
        logger.warning(
            "Long-term memory model extraction failed; skipping model candidates",
            exc_info=True,
            extra={"model_name": model_name},
        )
        return []
    raw_facts = _extract_fact_list(payload)
    candidates: list[LongTermMemoryCandidate] = []
    for raw in raw_facts[:5]:
        candidate = _normalize_model_fact(raw, source_fallback=user_message, model_name=model_name)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _await_if_needed_sync(value):
    if inspect.isawaitable(value):
        try:
            import asyncio

            return asyncio.run(value)
        except RuntimeError:
            logger.warning(
                "Long-term memory model await failed; treating response as unavailable",
                exc_info=True,
            )
            return ""
    return value


def _parse_json_payload(text: str):
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    start_candidates = [index for index in (stripped.find("["), stripped.find("{")) if index >= 0]
    if start_candidates:
        start = min(start_candidates)
        closer = "]" if stripped[start] == "[" else "}"
        end = stripped.rfind(closer)
        if end >= start:
            stripped = stripped[start : end + 1]
    return json.loads(stripped)


def _extract_fact_list(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("facts", "objects", "memories", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if any(key in payload for key in ("subject", "predicate", "object")):
            return [payload]
    return []


def _normalize_model_fact(raw: dict, *, source_fallback: str, model_name: str | None) -> LongTermMemoryCandidate | None:
    category = _clean_model_text(raw.get("category") or raw.get("memory_type"), limit=40)
    subject = _clean_model_text(raw.get("subject"), limit=80)
    predicate = _clean_model_text(raw.get("predicate") or "is", limit=40)
    object_value = _clean_model_text(raw.get("object") or raw.get("value"), limit=200)
    source_text = _clean_model_text(raw.get("source_text") or source_fallback, limit=500)
    confidence = _clamp_float(raw.get("confidence"), default=0.0)
    importance = _clamp_float(raw.get("importance"), default=0.5)
    if confidence < 0.4 or not subject or not predicate or not object_value or not source_text:
        return None
    if not category:
        category = "model_fact"
    metadata = {
        "extractor": model_name or "long_term_model",
    }
    return LongTermMemoryCandidate(
        target_path=PROFILE_PATH,
        category=category,
        subject=subject,
        value=object_value,
        source_text=source_text,
        predicate=predicate,
        confidence=confidence,
        memory_type=_clean_model_text(raw.get("memory_type"), limit=40) or category,
        entity_type=_clean_model_text(raw.get("entity_type"), limit=40) or None,
        importance=importance,
        metadata_json=json.dumps(metadata, ensure_ascii=True, sort_keys=True),
    )


def _clean_model_text(value, *, limit: int) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    return text[:limit].strip()


def _clamp_float(value, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))
