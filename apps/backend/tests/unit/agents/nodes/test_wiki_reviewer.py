from __future__ import annotations

import pytest

from app.agents.nodes.wiki_reviewer import WikiReviewerNode
from app.agents.prompts.system import _wiki_system_prompt


@pytest.mark.asyncio
async def test_wiki_reviewer_flags_missing_frontmatter() -> None:
    node = WikiReviewerNode()

    result = await node("# Summary\n\ncontent", {"sections": [{"title": "Summary"}]})

    assert result.approved is False
    assert any("frontmatter" in issue for issue in result.issues)


@pytest.mark.asyncio
async def test_wiki_reviewer_approves_complete_draft() -> None:
    node = WikiReviewerNode()
    draft = """---
title: Test Page
date: 2026-05-26
tags: [test]
---
# Summary

content

# Sources

- https://example.com/source
"""

    result = await node(draft, {"sections": [{"title": "Summary"}, {"title": "Sources"}]})

    assert result.approved is True
    assert result.issues == []
    assert result.revised_content is None
    assert result.confidence >= 0.8


def test_wiki_manager_prompt_includes_revision_issues() -> None:
    prompt = _wiki_system_prompt(revision_issues=["补全 frontmatter", "补充 Sources section"])

    assert "补全 frontmatter" in prompt
    assert "补充 Sources section" in prompt
    assert "addressing these review issues" in prompt
