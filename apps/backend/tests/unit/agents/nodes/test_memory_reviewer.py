from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from app.agents.nodes.memory_reviewer import MemoryReviewerNode
from app.agents.prompts.system import _memory_system_prompt
from app.models.enums import AgentId


@dataclass
class ModelResult:
    text: str


class Registry:
    def __init__(self, model: object) -> None:
        self.model = model
        self.requested_agent_ids: list[AgentId] = []

    def get(self, agent_id: AgentId):
        self.requested_agent_ids.append(agent_id)
        return self.model


@pytest.mark.asyncio
async def test_memory_reviewer_returns_approved_result() -> None:
    model = type(
        "Model",
        (),
        {
            "complete": AsyncMock(
                return_value=ModelResult(
                    text=json.dumps(
                        {
                            "approved": True,
                            "revised_draft": None,
                            "review_notes": "草案准确且格式完整。",
                            "confidence": 0.92,
                        }
                    )
                )
            )
        },
    )()
    registry = Registry(model)
    node = MemoryReviewerNode(model_registry=registry)

    result = await node(
        {"title": "偏好", "content": "用户喜欢苹果", "tags": ["preference"]},
        [{"title": "饮食", "content": "用户喜欢水果"}],
    )

    assert result.approved is True
    assert result.revised_draft is None
    assert result.review_notes == "草案准确且格式完整。"
    assert result.confidence == 0.92
    assert registry.requested_agent_ids == [AgentId.CHAT_AGENT]
    assert model.complete.await_count == 1


@pytest.mark.asyncio
async def test_memory_reviewer_returns_revised_draft_when_not_approved() -> None:
    revised_draft = {
        "title": "水果偏好",
        "content": "用户提到喜欢苹果。",
        "tags": ["preference", "food"],
    }
    model = type(
        "Model",
        (),
        {
            "complete": AsyncMock(
                return_value=ModelResult(
                    text=json.dumps(
                        {
                            "approved": False,
                            "revised_draft": revised_draft,
                            "review_notes": "原草案分类过宽，已补充标题和标签。",
                            "confidence": 0.86,
                        }
                    )
                )
            )
        },
    )()
    node = MemoryReviewerNode(model=model)

    result = await node({"content": "喜欢苹果"}, [])

    assert result.approved is False
    assert result.revised_draft == revised_draft
    assert result.review_notes == "原草案分类过宽，已补充标题和标签。"
    assert result.confidence == 0.86


def test_memory_proposal_prompt_includes_revision_notes() -> None:
    prompt = _memory_system_prompt(revision_notes="请补充分类，并避免与现有记忆重复。")

    assert "请补充分类，并避免与现有记忆重复。" in prompt
    assert "根据以下审查意见修正草案" in prompt
