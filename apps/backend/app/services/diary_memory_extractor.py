from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.enums import MemoryFactStatus
from app.services.memory_policy import evaluate_memory_content


MAX_DIARY_MEMORY_OBJECTS = 5
MIN_DIARY_MEMORY_CONFIDENCE = 0.4
QUARANTINE_CONFIDENCE_MAX = 0.6
DEFAULT_DIARY_MEMORY_TYPE = "event"
ALLOWED_DIARY_MEMORY_TYPES = frozenset(
    {
        "episode",
        "qa",
        "event",
        "mood",
        "project_update",
    }
)
PROFILEISH_DIARY_MEMORY_TYPES = frozenset(
    {
        "preference",
        "identity",
        "relationship",
        "project",
        "profile",
        "inference",
        "recent_state",
        "fact",
        "boundary",
        "personality",
    }
)
PROFILEISH_DIARY_MEMORY_FIELDS = (
    "category",
    "kind",
    "memory_kind",
    "profile_group",
    "group",
    "scope",
    "entity_type",
)

_EXCHANGE_BLOCKER_PATTERN = re.compile(
    r"不要记住|別保存|别保存|不要保存|不要记录|不要紀錄|不要归档|不要歸檔|仅本次|僅本次|只限本次|"
    r"\bdo\s+not\s+(?:remember|save|store|record|archive)\b|"
    r"\bdon't\s+(?:remember|save|store|record|archive)\b|"
    r"\bjust\s+this\s+(?:turn|time|session)\b",
    re.IGNORECASE,
)
_JOKE_PATTERN = re.compile(
    r"只是开玩笑|只是開玩笑|开个玩笑|開個玩笑|玩笑|"
    r"\bjoking\s+only\b|\bjust\s+kidding\b|\bjust\s+a\s+joke\b|\bas\s+a\s+joke\b|\bsilly\s+bit\b",
    re.IGNORECASE,
)
_OBJECT_INTERNAL_PATTERN = re.compile(
    r"source_text|source_excerpt|raw[_\s-]?evidence|evidence_id|agent_run_id|"
    r"\bauthorization\b|\bbearer\b|\btoken\b|tool_call|<tool_call|</tool_call>|"
    r"\braw\s+log\b|stack trace|Traceback \(most recent call last\)|\bFile \"[^\"]+\", line \d+",
    re.IGNORECASE,
)
_PROFILEISH_CONTENT_PATTERN = re.compile(
    r"\buser\s+prefers\b|\bi\s+prefer\b|\bprefers\s+concise\b|\bfavorite\b|"
    r"\bidentity\b|\brelationship\b|\bboundary\b|\bpersonality\b|"
    r"用户偏好|我喜欢|我更喜欢|身份|关系|边界|人格",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_PATH_PATTERN = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)")
_POSIX_ABSOLUTE_PATH_PATTERN = re.compile(r"(?<!\w)/(?:Users|home|var|etc|tmp|mnt|opt|root)/", re.IGNORECASE)
_SHORT_TERM_MOOD_PATTERN = re.compile(
    r"\b(?:today|right now|recently|lately|this week|this morning|this evening)\b|"
    r"今天|刚才|剛才|最近|这周|這周|现在|現在|心情",
    re.IGNORECASE,
)
_MOOD_WORD_PATTERN = re.compile(
    r"\b(?:anxious|stressed|tired|frustrated|sad|angry|relieved|excited|overwhelmed|worried)\b|"
    r"焦虑|焦慮|压力|壓力|疲惫|疲憊|沮丧|沮喪|难过|難過|生气|生氣|开心|開心|低落|烦|煩",
    re.IGNORECASE,
)


logger = logging.getLogger(__name__)


class DiaryExtractionModelProtocol(Protocol):
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> Any: ...


@dataclass(frozen=True, slots=True)
class DiaryMemoryObject:
    summary: str
    topic: str
    emotion: str
    people: tuple[str, ...]
    keywords: tuple[str, ...]
    source_text: str
    importance: float
    confidence: float
    status: MemoryFactStatus
    type: str = DEFAULT_DIARY_MEMORY_TYPE


class DiaryMemoryExtractor:
    def __init__(self, model_client: DiaryExtractionModelProtocol | None = None) -> None:
        self.model_client = model_client

    async def extract(
        self,
        diary_text: str,
        *,
        memory_date: str | None = None,
        source_path: str | None = None,
    ) -> list[DiaryMemoryObject]:
        text = diary_text.strip()
        if not text or self.model_client is None:
            return []
        if _should_block_exchange(text):
            return []

        try:
            response = await self.model_client.complete(
                user_message=_user_prompt(text, memory_date=memory_date, source_path=source_path),
                system_prompt=DIARY_EXTRACTION_SYSTEM_PROMPT,
            )
            payload = _parse_json_payload(str(response))
        except Exception:
            logger.warning(
                "Diary memory extraction failed; skipping durable memories",
                exc_info=True,
                extra={"memory_date": memory_date, "source_path": source_path},
            )
            return []

        raw_objects = _extract_object_list(payload)
        extracted: list[DiaryMemoryObject] = []
        for raw in raw_objects:
            item = _normalize_object(raw)
            if item is None:
                continue
            extracted.append(item)
            if len(extracted) >= MAX_DIARY_MEMORY_OBJECTS:
                break
        return extracted


async def extract_diary_memories(
    diary_text: str,
    *,
    model_client: DiaryExtractionModelProtocol | None,
    memory_date: str | None = None,
    source_path: str | None = None,
) -> list[DiaryMemoryObject]:
    return await DiaryMemoryExtractor(model_client).extract(
        diary_text,
        memory_date=memory_date,
        source_path=source_path,
    )


DIARY_EXTRACTION_SYSTEM_PROMPT = (
    "你是日记记忆提取模型。只返回 JSON：对象数组或 {\"objects\":[...]}。"
    "最多返回 5 个对象。每个对象必须包含以下键："
    "summary, topic, emotion, people, keywords, source_text, importance, confidence。"
    "people 和 keywords 必须是短字符串数组。importance 和 confidence 必须是 0 到 1 之间的数字。"
    "source_text 必须是支撑该对象的简短日记摘录。"
    "当日记没有持久化记忆对象时返回 []。不要包含 markdown、散文、注释、密钥、凭据或 JSON 负载之外的字段。"
)


DIARY_EXTRACTION_SYSTEM_PROMPT = DIARY_EXTRACTION_SYSTEM_PROMPT + (
    " Return the field type for every object. type must be one of episode, qa, event, mood, project_update. "
    "episode means a contextual experience or conversation fragment. qa means a user question with a safe answer summary. "
    "event means a low-risk concrete event. mood means a short-term emotional state, not a personality label. "
    "project_update means a project phase, decision, blocker, or next step. "
    "Do not write stable preferences, identity, relationships, personality inferences, boundaries, or raw facts as diary episodes. "
    "Do not treat assistant inference as user fact. Return [] for jokes, do-not-remember requests, credentials, raw logs, tool calls, or raw evidence."
)


def _user_prompt(diary_text: str, *, memory_date: str | None, source_path: str | None) -> str:
    metadata: list[str] = []
    if memory_date:
        metadata.append(f"date: {memory_date}")
    if source_path:
        metadata.append(f"source_path: {source_path}")
    metadata_block = "\n".join(metadata) if metadata else "date: unknown"
    return (
        "从此日记条目中提取持久化记忆对象。只使用条目中的信息，只返回 JSON。\n\n"
        f"{metadata_block}\n\n"
        f"日记内容：\n{_truncate(diary_text, 4000)}"
    )


def _parse_json_payload(text: str) -> Any:
    candidates = [_strip_code_fence(text)]
    extracted = _extract_json_substring(candidates[0])
    if extracted not in candidates:
        candidates.append(extracted)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise ValueError("diary_memory_json_unparseable")


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    if lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_substring(text: str) -> str:
    stripped = text.strip()
    starts = [index for index in (stripped.find("["), stripped.find("{")) if index >= 0]
    if not starts:
        return stripped
    start = min(starts)
    opener = stripped[start]
    closer = "]" if opener == "[" else "}"
    end = stripped.rfind(closer)
    if end < start:
        return stripped
    return stripped[start : end + 1].strip()


def _extract_object_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("objects", "memories", "items", "diary_memories", "candidates"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if _looks_like_memory_object(payload):
            return [payload]
    return []


def _looks_like_memory_object(payload: dict[str, Any]) -> bool:
    return any(key in payload for key in ("summary", "source_text", "confidence", "importance"))


def _normalize_object(raw: dict[str, Any]) -> DiaryMemoryObject | None:
    memory_type = _memory_type_from_raw(raw)
    if memory_type is None:
        return None
    summary = _coerce_text(raw.get("summary"), limit=500)
    topic = _coerce_text(raw.get("topic"), limit=120)
    emotion = _coerce_text(raw.get("emotion"), limit=120)
    source_text = _coerce_text(raw.get("source_text") or raw.get("source") or raw.get("evidence"), limit=500)
    people = _coerce_string_list(raw.get("people"), limit=12, item_limit=80)
    keywords = _coerce_string_list(raw.get("keywords"), limit=12, item_limit=80)
    importance = _clamp_float(raw.get("importance"), default=0.0)
    confidence = _clamp_float(raw.get("confidence"), default=0.0)

    if not summary or not source_text:
        return None
    if _object_should_block(
        summary=summary,
        topic=topic,
        emotion=emotion,
        people=people,
        keywords=keywords,
        source_text=source_text,
    ):
        return None
    if confidence < MIN_DIARY_MEMORY_CONFIDENCE:
        return None
    if not _passes_memory_policy(
        summary=summary,
        topic=topic,
        emotion=emotion,
        people=people,
        keywords=keywords,
        source_text=source_text,
    ):
        return None

    if _looks_like_short_term_mood(summary=summary, topic=topic, emotion=emotion, source_text=source_text):
        memory_type = "mood"

    if _looks_like_personality_inference(summary=summary, source_text=source_text):
        status = MemoryFactStatus.QUARANTINED
    else:
        status = (
            MemoryFactStatus.QUARANTINED
            if confidence <= QUARANTINE_CONFIDENCE_MAX
            else MemoryFactStatus.ACTIVE
        )
    return DiaryMemoryObject(
        summary=summary,
        topic=topic,
        emotion=emotion,
        people=people,
        keywords=keywords,
        source_text=source_text,
        importance=importance,
        confidence=confidence,
        status=status,
        type=memory_type,
    )


def _memory_type_from_raw(raw: dict[str, Any]) -> str | None:
    if _has_profileish_metadata(raw):
        return None
    explicit_type = raw.get("type") or raw.get("memory_type")
    if explicit_type is not None and str(explicit_type).strip():
        return _normalize_memory_type(explicit_type)
    category = _coerce_text(raw.get("category"), limit=80).casefold().replace("-", "_").replace(" ", "_")
    if category in PROFILEISH_DIARY_MEMORY_TYPES:
        return None
    if category in ALLOWED_DIARY_MEMORY_TYPES:
        return category
    return DEFAULT_DIARY_MEMORY_TYPE


def _normalize_memory_type(value: Any) -> str | None:
    raw = _coerce_text(value, limit=80).casefold().replace("-", "_").replace(" ", "_")
    if not raw:
        return DEFAULT_DIARY_MEMORY_TYPE
    if raw in PROFILEISH_DIARY_MEMORY_TYPES:
        return None
    if raw in ALLOWED_DIARY_MEMORY_TYPES:
        return raw
    return None


def _has_profileish_metadata(raw: dict[str, Any]) -> bool:
    for field in PROFILEISH_DIARY_MEMORY_FIELDS:
        value = _coerce_text(raw.get(field), limit=80).casefold().replace("-", "_").replace(" ", "_")
        if value in PROFILEISH_DIARY_MEMORY_TYPES:
            return True
    return False


def _should_block_exchange(text: str) -> bool:
    return bool(_EXCHANGE_BLOCKER_PATTERN.search(text) or _JOKE_PATTERN.search(text))


def _object_should_block(
    *,
    summary: str,
    topic: str,
    emotion: str,
    people: tuple[str, ...],
    keywords: tuple[str, ...],
    source_text: str,
) -> bool:
    text = "\n".join(value for value in (summary, topic, emotion, *people, *keywords, source_text) if value)
    return bool(
        _JOKE_PATTERN.search(text)
        or _PROFILEISH_CONTENT_PATTERN.search(text)
        or _OBJECT_INTERNAL_PATTERN.search(text)
        or _WINDOWS_ABSOLUTE_PATH_PATTERN.search(text)
        or _POSIX_ABSOLUTE_PATH_PATTERN.search(text)
    )


def _passes_memory_policy(
    *,
    summary: str,
    topic: str,
    emotion: str,
    people: tuple[str, ...],
    keywords: tuple[str, ...],
    source_text: str,
) -> bool:
    values = [summary, topic, emotion, *people, *keywords, source_text]
    return all(evaluate_memory_content(value).allowed for value in values if value)


def _looks_like_personality_inference(*, summary: str, source_text: str) -> bool:
    text = f"{summary} {source_text}".casefold()
    if not any(marker in text for marker in ("user is", "the user is", "user seems", "the user seems", "assistant inferred")):
        return False
    labels = (
        "anxious person",
        "depressed person",
        "lazy person",
        "avoidant person",
        "needy person",
        "angry person",
        "emotional person",
        "introvert",
        "perfectionist",
        "unreliable person",
        "insecure person",
    )
    return any(label in text for label in labels)


def _looks_like_short_term_mood(*, summary: str, topic: str, emotion: str, source_text: str) -> bool:
    text = f"{summary} {topic} {emotion} {source_text}"
    return bool(_SHORT_TERM_MOOD_PATTERN.search(text) and _MOOD_WORD_PATTERN.search(text))


def _coerce_text(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        text = " ".join(str(item) for item in value if item is not None)
    else:
        text = str(value)
    return _truncate(" ".join(text.split()), limit)


def _coerce_string_list(value: Any, *, limit: int, item_limit: int) -> tuple[str, ...]:
    raw_items: list[Any]
    if value is None:
        raw_items = []
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    elif isinstance(value, str):
        raw_items = _split_list_text(value)
    else:
        raw_items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _coerce_text(item, limit=item_limit)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return tuple(normalized)


def _split_list_text(value: str) -> list[str]:
    text = value.replace("\n", ",").replace(";", ",").replace("\uff1b", ",").replace("\uff0c", ",")
    return [item.strip() for item in text.split(",")]


def _clamp_float(value: Any, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(0.0, min(1.0, number))


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."
