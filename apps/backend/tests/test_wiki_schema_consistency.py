"""保证 AGENTS.md 是唯一规则来源，contracts.py 与其一致，LLM 审查读它。"""
from __future__ import annotations

import re
from pathlib import Path

from app.services.wiki.contracts import PAGE_TYPE_CONTRACTS
from app.services.wiki.review import _review_system_prompt


def _schema_markdown() -> str:
    resource = Path(__file__).resolve().parents[1] / "app" / "resources" / "wiki" / "AGENTS.md"
    return resource.read_text(encoding="utf-8")


def _schema_page_types(markdown: str) -> set[str]:
    return set(re.findall(r"^###\s+(\w+)", markdown, flags=re.MULTILINE))


def test_page_type_contracts_mirror_agents_md() -> None:
    """contracts.py 的页面类型必须与 AGENTS.md 的页面类型一致，防止硬编码漂移。"""
    assert set(PAGE_TYPE_CONTRACTS) == _schema_page_types(_schema_markdown())


def test_review_prompt_includes_agents_md_schema() -> None:
    """LLM 审查 prompt 必须注入 AGENTS.md 内容，而不是盲审。"""
    schema = _schema_markdown()
    prompt = _review_system_prompt()
    assert "权威边界" in prompt
    assert "页面类型" in prompt
    # 注入的是真实规范内容（不只是路径/标题）
    assert schema.splitlines()[0] in prompt
