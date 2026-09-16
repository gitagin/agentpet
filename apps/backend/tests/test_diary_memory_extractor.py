from __future__ import annotations

import asyncio
import json

import pytest

from app.models.enums import MemoryFactStatus
from app.services.diary_memory_extractor import (
    DiaryMemoryExtractionError,
    DiaryMemoryExtractor,
    extract_diary_memories,
)


class FakeDiaryModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append({"user_message": user_message, "system_prompt": system_prompt})
        return self.response


class AsyncFakeDiaryModel(FakeDiaryModel):
    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append({"user_message": user_message, "system_prompt": system_prompt})
        return self.response


def test_returns_no_objects_without_model() -> None:
    result = asyncio.run(
        extract_diary_memories(
            "I finished the refactor and felt relieved.",
            model_client=None,
            memory_date="2026-05-13",
        )
    )

    assert result == []


def test_extracts_wrapper_json_and_classifies_status_by_confidence() -> None:
    model = FakeDiaryModel(
        json.dumps(
            {
                "objects": [
                    {
                        "summary": "Finished the notebook import plan.",
                        "topic": "wiki import",
                        "emotion": "relieved",
                        "people": ["Ada", "Ada"],
                        "keywords": ["wiki", "import", "wiki"],
                        "source_text": "I finished the notebook import plan and felt relieved.",
                        "importance": 1.5,
                        "confidence": 0.59,
                    },
                    {
                        "summary": "Pairing session with Lin was useful.",
                        "topic": "collaboration",
                        "emotion": "focused",
                        "people": "Lin, Mei",
                        "keywords": "pairing;backend",
                        "source_text": "Lin and Mei helped me narrow the backend issue.",
                        "importance": -0.2,
                        "confidence": 0.61,
                    },
                ]
            }
        )
    )

    result = asyncio.run(
        DiaryMemoryExtractor(model).extract(
            "I finished the notebook import plan and felt relieved.",
            memory_date="2026-05-13",
            source_path="Memories/Daily/2026-05-13.md",
        )
    )

    assert len(result) == 2
    assert result[0].type == "event"
    assert result[0].status == MemoryFactStatus.QUARANTINED
    assert result[0].importance == 1.0
    assert result[0].confidence == 0.59
    assert result[0].people == ("Ada",)
    assert result[0].keywords == ("wiki", "import")
    assert result[1].status == MemoryFactStatus.ACTIVE
    assert result[1].importance == 0.0
    assert result[1].type == "event"
    assert result[1].people == ("Lin", "Mei")
    assert result[1].keywords == ("pairing", "backend")
    assert model.calls
    assert "Return the field type for every object" in str(model.calls[0]["system_prompt"])
    assert "只返回 JSON" in str(model.calls[0]["system_prompt"])
    assert "2026-05-13" in str(model.calls[0]["user_message"])


def test_accepts_fenced_json_from_async_model_and_limits_to_five_objects() -> None:
    payload = [
        {
            "summary": f"Durable diary memory {index}",
            "topic": "daily work",
            "emotion": "steady",
            "people": [],
            "keywords": [f"k{index}"],
            "source_text": f"Source excerpt {index}",
            "importance": 0.5,
            "confidence": 0.8,
        }
        for index in range(7)
    ]
    model = AsyncFakeDiaryModel(f"```json\n{json.dumps(payload)}\n```")

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Long diary text"))

    assert len(result) == 5
    assert [item.summary for item in result] == [f"Durable diary memory {index}" for index in range(5)]


def test_extracts_whitelisted_episode_types() -> None:
    payload = [
        {
            "type": memory_type,
            "summary": f"Safe {memory_type} summary.",
            "topic": memory_type,
            "emotion": "steady",
            "people": [],
            "keywords": [memory_type],
            "source_text": f"Safe {memory_type} source.",
            "importance": 0.7,
            "confidence": 0.85,
        }
        for memory_type in ("episode", "qa", "event", "mood", "project_update")
    ]
    model = FakeDiaryModel(json.dumps({"objects": payload}))

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert [item.type for item in result] == ["episode", "qa", "event", "mood", "project_update"]


def test_drops_low_confidence_and_sensitive_fields() -> None:
    model = FakeDiaryModel(
        json.dumps(
            [
                {
                    "summary": "Low confidence item",
                    "topic": "maybe",
                    "emotion": "uncertain",
                    "people": [],
                    "keywords": [],
                    "source_text": "Could be true.",
                    "importance": 0.8,
                    "confidence": 0.39,
                },
                {
                    "summary": "Provider key was mentioned.",
                    "topic": "security",
                    "emotion": "worried",
                    "people": [],
                    "keywords": ["secret"],
                    "source_text": "The API key is sk-diary-secret-1234567890.",
                    "importance": 0.8,
                    "confidence": 0.95,
                },
                {
                    "summary": "Kept the release checklist small.",
                    "topic": "release",
                    "emotion": "calm",
                    "people": [],
                    "keywords": ["release"],
                    "source_text": "I kept the release checklist small.",
                    "importance": 0.8,
                    "confidence": 0.95,
                },
            ]
        )
    )

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert [item.summary for item in result] == ["Kept the release checklist small."]
    assert result[0].status == MemoryFactStatus.ACTIVE


def test_rejects_unsupported_and_profileish_types() -> None:
    payload = [
        {
            "type": memory_type,
            "summary": f"Should not persist {memory_type}.",
            "topic": "profile",
            "emotion": "",
            "people": [],
            "keywords": [],
            "source_text": f"Profile-like {memory_type} source.",
            "importance": 0.8,
            "confidence": 0.95,
        }
        for memory_type in (
            "preference",
            "identity",
            "relationship",
            "project",
            "profile",
            "inference",
            "recent_state",
            "fact",
            "boundary",
            "debug_log",
        )
    ]
    payload.append(
        {
            "type": "qa",
            "summary": "Safe question answer summary.",
            "topic": "support",
            "emotion": "calm",
            "people": [],
            "keywords": ["qa"],
            "source_text": "User asked how to continue and got a safe answer.",
            "importance": 0.7,
            "confidence": 0.9,
        }
    )
    model = FakeDiaryModel(json.dumps(payload))

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert [item.summary for item in result] == ["Safe question answer summary."]
    assert result[0].type == "qa"


def test_profileish_metadata_and_content_cannot_bypass_with_allowed_type() -> None:
    payload = [
        {
            "type": "event",
            "category": "preference",
            "summary": "Category marker should reject this object.",
            "topic": "profile",
            "emotion": "",
            "people": [],
            "keywords": [],
            "source_text": "A preference category marker appeared.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "episode",
            "memory_kind": "identity",
            "summary": "Memory kind marker should reject this object.",
            "topic": "identity",
            "emotion": "",
            "people": [],
            "keywords": [],
            "source_text": "An identity marker appeared.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "event",
            "profile_group": "relationship",
            "summary": "Profile group marker should reject this object.",
            "topic": "relationship",
            "emotion": "",
            "people": [],
            "keywords": [],
            "source_text": "A relationship marker appeared.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "event",
            "summary": "User prefers concise replies.",
            "topic": "reply style",
            "emotion": "",
            "people": [],
            "keywords": ["style"],
            "source_text": "User prefers concise replies.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "event",
            "summary": "\u7528\u6237\u504f\u597d\u7b80\u6d01\u56de\u7b54",
            "topic": "reply style",
            "emotion": "",
            "people": [],
            "keywords": ["style"],
            "source_text": "\u7528\u6237\u504f\u597d\u7b80\u6d01\u56de\u7b54",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "event",
            "summary": "\u6211\u559c\u6b22\u7b80\u6d01\u56de\u7b54",
            "topic": "reply style",
            "emotion": "",
            "people": [],
            "keywords": ["style"],
            "source_text": "\u6211\u559c\u6b22\u7b80\u6d01\u56de\u7b54",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "project_update",
            "category": "project_update",
            "summary": "Project Atlas decision moved to next week.",
            "topic": "Project Atlas",
            "emotion": "focused",
            "people": [],
            "keywords": ["atlas", "decision"],
            "source_text": "Project Atlas decision moved to next week.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "event",
            "summary": "Safe release checkpoint happened.",
            "topic": "release",
            "emotion": "calm",
            "people": [],
            "keywords": ["release"],
            "source_text": "The release checkpoint happened safely.",
            "importance": 0.8,
            "confidence": 0.95,
        },
        {
            "type": "qa",
            "summary": "User asked how to compare parser options.",
            "topic": "parser choice",
            "emotion": "calm",
            "people": [],
            "keywords": ["parser"],
            "source_text": "User asked how to compare parser options.",
            "importance": 0.8,
            "confidence": 0.95,
        },
    ]
    model = FakeDiaryModel(json.dumps(payload))

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert [(item.type, item.summary) for item in result] == [
        ("project_update", "Project Atlas decision moved to next week."),
        ("event", "Safe release checkpoint happened."),
        ("qa", "User asked how to compare parser options."),
    ]


def test_exchange_blockers_return_empty_without_calling_model() -> None:
    for text in (
        "Please do not remember this conversation.",
        "请不要记住这件事。",
        "这只是开玩笑，不要保存。",
    ):
        model = FakeDiaryModel("[]")

        result = asyncio.run(DiaryMemoryExtractor(model).extract(text))

        assert result == []
        assert model.calls == []


def test_object_internal_fields_drop_only_unsafe_object() -> None:
    unsafe_sources = [
        "source_text: raw hidden",
        "source_excerpt: raw hidden",
        "raw_evidence should not persist",
        "evidence_id=e-1",
        "agent_run_id=run-1",
        "token should not persist",
        "Authorization: Bearer secret-token-value",
        r"C:\Users\Ada\Vault\Secret.md",
        'Traceback (most recent call last): File "app.py", line 1',
        "raw log: stack details",
        "<tool_call>{}</tool_call>",
    ]
    payload = [
        {
            "type": "episode",
            "summary": f"Unsafe object {index}",
            "topic": "unsafe",
            "emotion": "",
            "people": [],
            "keywords": [],
            "source_text": source,
            "importance": 0.8,
            "confidence": 0.95,
        }
        for index, source in enumerate(unsafe_sources)
    ]
    payload.append(
        {
            "type": "event",
            "summary": "Safe event survives.",
            "topic": "release",
            "emotion": "calm",
            "people": [],
            "keywords": ["release"],
            "source_text": "The release checklist was reviewed safely.",
            "importance": 0.8,
            "confidence": 0.95,
        }
    )
    model = FakeDiaryModel(json.dumps(payload))

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert [item.summary for item in result] == ["Safe event survives."]


def test_one_off_complaint_is_mood_not_personality_label() -> None:
    model = FakeDiaryModel(
        json.dumps(
            [
                {
                    "type": "event",
                    "summary": "User felt frustrated today about flaky tests.",
                    "topic": "work",
                    "emotion": "frustrated",
                    "people": [],
                    "keywords": ["tests"],
                    "source_text": "I feel frustrated today because the tests are flaky.",
                    "importance": 0.5,
                    "confidence": 0.82,
                },
                {
                    "type": "fact",
                    "summary": "User is a frustrated person.",
                    "topic": "personality",
                    "emotion": "frustrated",
                    "people": [],
                    "keywords": ["personality"],
                    "source_text": "User is a frustrated person.",
                    "importance": 0.9,
                    "confidence": 0.9,
                },
            ]
        )
    )

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert len(result) == 1
    assert result[0].type == "mood"
    assert result[0].summary == "User felt frustrated today about flaky tests."


def test_quarantines_model_personality_inference() -> None:
    model = FakeDiaryModel(
        json.dumps(
            [
                {
                    "type": "episode",
                    "summary": "The user is an anxious person.",
                    "topic": "model inference",
                    "emotion": "anxious",
                    "people": [],
                    "keywords": ["inference"],
                    "source_text": "The user is an anxious person.",
                    "importance": 0.8,
                    "confidence": 0.95,
                }
            ]
        )
    )

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert len(result) == 1
    assert result[0].status == MemoryFactStatus.QUARANTINED
    assert result[0].type == "episode"


def test_unparseable_model_output_fails_instead_of_reporting_nothing() -> None:
    # 模型被要求只返回 JSON 却回了散文:这是这一轮抽取失败,不是"没有内容可记"。
    # 收敛成空列表会让动作以"零效果"收尾,记忆随之静默丢失且无人重试。
    model = FakeDiaryModel("Here are the memories: none.")

    with pytest.raises(DiaryMemoryExtractionError) as excinfo:
        asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert excinfo.value.code == "diary_memory_extraction_failed"


def test_model_failure_fails_instead_of_reporting_nothing() -> None:
    class FailingModel:
        async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            raise RuntimeError("provider down")

    with pytest.raises(DiaryMemoryExtractionError) as excinfo:
        asyncio.run(DiaryMemoryExtractor(FailingModel()).extract("Diary text"))

    assert excinfo.value.code == "diary_memory_extraction_failed"
