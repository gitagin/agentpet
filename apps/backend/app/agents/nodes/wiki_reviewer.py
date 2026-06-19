from __future__ import annotations

import inspect
import json
import re
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AgentId


class WikiReviewResult(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revised_content: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class WikiReviewerNode:
    def __init__(self, model_registry: Any | None = None, model: Any | None = None) -> None:
        self.model_registry = model_registry
        self.model = model

    async def __call__(self, draft_content: str, plan: dict[str, Any]) -> WikiReviewResult:
        deterministic_issues = self._deterministic_issues(draft_content, plan)
        model = self._model(optional=True)
        if model is None:
            return WikiReviewResult(
                approved=not deterministic_issues,
                issues=deterministic_issues,
                revised_content=None,
                confidence=0.85 if not deterministic_issues else 0.65,
            )

        prompt = self._build_prompt(draft_content, plan, deterministic_issues)
        raw_result = await self._invoke_model(model, prompt)
        result = self._coerce_result(raw_result)
        issues = [*deterministic_issues, *result.issues]
        return WikiReviewResult(
            approved=not issues and result.approved,
            issues=issues,
            revised_content=result.revised_content,
            confidence=result.confidence,
        )

    def _build_prompt(self, draft_content: str, plan: dict[str, Any], deterministic_issues: list[str]) -> str:
        return "\n".join(
            [
                "你是 wiki_reviewer，复核即将提交给用户确认的 Vault Markdown 草稿。",
                "请审查：frontmatter 完整性、外链格式、section 结构是否符合 plan、内容与对话上下文的一致性。",
                "只返回 JSON，不要有任何前缀或 markdown 代码块。",
                "JSON 字段：approved(boolean), issues(array[string]), revised_content(string|null), confidence(number)。",
                "",
                "确定性检查发现的问题：",
                json.dumps(deterministic_issues, ensure_ascii=False),
                "",
                "计划：",
                json.dumps(plan, ensure_ascii=False, default=str),
                "",
                "草稿：",
                draft_content,
            ]
        )

    def _deterministic_issues(self, draft_content: str, plan: dict[str, Any]) -> list[str]:
        issues: list[str] = []
        frontmatter = self._frontmatter(draft_content)
        if frontmatter is None:
            issues.append("缺少 frontmatter。")
        else:
            for field in ("title", "date", "tags"):
                if not re.search(rf"(?m)^{field}:\s*\S", frontmatter):
                    issues.append(f"frontmatter 缺少 {field} 字段。")

        for match in re.finditer(r"https?://[^\s)\]]+", draft_content):
            url = match.group(0)
            if not re.match(r"^https?://[^\s/$.?#].[^\s]*$", url):
                issues.append(f"外链格式可能无效：{url}")

        for section in plan.get("sections", []) or []:
            title = section.get("title") if isinstance(section, dict) else str(section)
            if title and not re.search(rf"(?m)^#+\s+{re.escape(title)}\s*$", draft_content):
                issues.append(f"缺少计划中的 section：{title}")

        return issues

    def _frontmatter(self, draft_content: str) -> str | None:
        if not draft_content.startswith("---\n"):
            return None
        end = draft_content.find("\n---", 4)
        if end == -1:
            return None
        return draft_content[4:end]

    async def _invoke_model(self, model: Any, prompt: str) -> Any:
        if hasattr(model, "complete"):
            result = self._call_complete(model, prompt)
        elif hasattr(model, "ainvoke"):
            result = model.ainvoke(prompt)
        elif hasattr(model, "invoke"):
            result = model.invoke(prompt)
        elif callable(model):
            result = model(prompt)
        else:
            raise TypeError("Wiki reviewer model must be callable or expose complete/ainvoke/invoke.")

        if inspect.isawaitable(result):
            return await result
        return result

    def _model(self, *, optional: bool = False) -> Any:
        if self.model is not None:
            return self.model
        if self.model_registry is not None:
            return self.model_registry.get(AgentId.ACTION_AGENT)
        if optional:
            return None
        raise ValueError("Wiki reviewer requires a model or model registry.")

    def _call_complete(self, model: Any, prompt: str) -> Any:
        try:
            return model.complete(user_message=prompt, system_prompt="你是 wiki_reviewer，只返回 JSON。")
        except TypeError:
            return model.complete(prompt)

    def _coerce_result(self, raw_result: Any) -> WikiReviewResult:
        if isinstance(raw_result, WikiReviewResult):
            return raw_result
        if isinstance(raw_result, dict):
            return WikiReviewResult(**raw_result)
        return WikiReviewResult(**self._parse_json_response(self._extract_text(raw_result)))

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                stripped = "\n".join(lines[1:-1]).strip()
                if stripped.startswith("json"):
                    stripped = stripped[4:].strip()
        return json.loads(stripped)

    def _extract_text(self, raw_result: Any) -> str:
        if isinstance(raw_result, str):
            return raw_result
        if hasattr(raw_result, "text"):
            return str(raw_result.text)
        if hasattr(raw_result, "content"):
            return str(raw_result.content)
        return str(raw_result)
