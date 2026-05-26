from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from app.models.enums import MemoryFactStatus
from app.services.memory_policy import evaluate_memory_content


MAX_DIARY_MEMORY_OBJECTS = 5
MIN_DIARY_MEMORY_CONFIDENCE = 0.4
QUARANTINE_CONFIDENCE_MAX = 0.6


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
    "You are a pure diary memory extraction model. Return JSON only: either an array of objects "
    "or {\"objects\":[...]}. Return at most 5 objects. Each object must use these keys: "
    "summary, topic, emotion, people, keywords, source_text, importance, confidence. "
    "people and keywords must be arrays of short strings. importance and confidence must be "
    "numbers from 0 to 1. source_text must be a short diary excerpt supporting the object. "
    "Return [] when the diary has no durable memory objects. Do not include markdown, prose, "
    "comments, secrets, credentials, or fields outside the JSON payload."
)


def _user_prompt(diary_text: str, *, memory_date: str | None, source_path: str | None) -> str:
    metadata: list[str] = []
    if memory_date:
        metadata.append(f"date: {memory_date}")
    if source_path:
        metadata.append(f"source_path: {source_path}")
    metadata_block = "\n".join(metadata) if metadata else "date: unknown"
    return (
        "Extract durable memory objects from this diary entry. Use only information present in "
        "the entry and return JSON only.\n\n"
        f"{metadata_block}\n\n"
        f"diary_text:\n{_truncate(diary_text, 4000)}"
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
