from __future__ import annotations

import asyncio
import json

from app.models.enums import MemoryFactStatus
from app.services.diary_memory_extractor import DiaryMemoryExtractor, extract_diary_memories


class FakeDiaryModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str | None]] = []

    def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
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
    assert result[0].status == MemoryFactStatus.QUARANTINED
    assert result[0].importance == 1.0
    assert result[0].confidence == 0.59
    assert result[0].people == ("Ada",)
    assert result[0].keywords == ("wiki", "import")
    assert result[1].status == MemoryFactStatus.ACTIVE
    assert result[1].importance == 0.0
    assert result[1].people == ("Lin", "Mei")
    assert result[1].keywords == ("pairing", "backend")
    assert model.calls
    assert "Return JSON only" in str(model.calls[0]["system_prompt"])
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


def test_returns_no_objects_on_unparseable_model_output() -> None:
    model = FakeDiaryModel("Here are the memories: none.")

    result = asyncio.run(DiaryMemoryExtractor(model).extract("Diary text"))

    assert result == []


def test_returns_no_objects_when_model_raises() -> None:
    class FailingModel:
        def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
            raise RuntimeError("provider down")

    result = asyncio.run(DiaryMemoryExtractor(FailingModel()).extract("Diary text"))

    assert result == []
