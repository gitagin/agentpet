from __future__ import annotations

import inspect
import json
from typing import Any

from pydantic import BaseModel, Field

from app.agents.nodes.common import extract_text, parse_json_response
from app.models.enums import AgentId


class MemoryReviewResult(BaseModel):
    approved: bool
    revised_draft: dict[str, Any] | None = None
    review_notes: str
    confidence: float = Field(ge=0.0, le=1.0)


class MemoryReviewerNode:
    def __init__(self, model_registry: Any | None = None, model: Any | None = None) -> None:
        self.model_registry = model_registry
        self.model = model

    async def __call__(self, draft: dict[str, Any], existing_memories: list[Any]) -> MemoryReviewResult:
        prompt = self._build_prompt(draft, existing_memories)
        raw_result = await self._invoke_model(prompt)
        if isinstance(raw_result, MemoryReviewResult):
            return raw_result
        if isinstance(raw_result, dict):
            return MemoryReviewResult(**raw_result)
        return MemoryReviewResult(**parse_json_response(extract_text(raw_result)))

    def _build_prompt(self, draft: dict[str, Any], existing_memories: list[Any]) -> str:
        return "\n".join(
            [
                "你是 memory_reviewer，复核待写入长期记忆的草案。",
                "请审查四个维度：内容准确性、分类合理性、与既有记忆是否重复或矛盾、格式完整性。",
                "只返回 JSON，不要有任何前缀或 markdown 代码块。",
                "JSON 字段：approved(boolean), revised_draft(object|null), review_notes(string), confidence(number)。",
                "approved=true 时 revised_draft 必须为 null；approved=false 时 revised_draft 必须给出修正后的草案。",
                "",
                "待审查草案：",
                json.dumps(draft, ensure_ascii=False, default=str),
                "",
                "已有记忆：",
                json.dumps(existing_memories, ensure_ascii=False, default=str),
            ]
        )

    async def _invoke_model(self, prompt: str) -> Any:
        model = self._model()
        if hasattr(model, "complete"):
            result = self._call_complete(model, prompt)
        elif hasattr(model, "ainvoke"):
            result = model.ainvoke(prompt)
        elif hasattr(model, "invoke"):
            result = model.invoke(prompt)
        elif callable(model):
            result = model(prompt)
        else:
            raise TypeError("Memory reviewer model must be callable or expose complete/ainvoke/invoke.")

        if inspect.isawaitable(result):
            return await result
        return result

    def _model(self) -> Any:
        if self.model is not None:
            return self.model
        if self.model_registry is not None:
            return self.model_registry.get(AgentId.CHAT_AGENT)
        raise ValueError("Memory reviewer requires a chat model or model registry.")

    def _call_complete(self, model: Any, prompt: str) -> Any:
        try:
            return model.complete(user_message=prompt, system_prompt="你是 memory_reviewer，只返回 JSON。")
        except TypeError:
            return model.complete(prompt)
