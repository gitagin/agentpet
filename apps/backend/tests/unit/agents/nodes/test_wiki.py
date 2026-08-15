from __future__ import annotations

import pytest

from app.agents.nodes.wiki import _wiki_proposal_kind


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("archive query to wiki", "query_archive"),
        ("请归档查询回答", "query_archive"),
        ("synthesize these notes", "synthesize"),
        ("把这些来源综合整理", "synthesize"),
        ("run a wiki lint report", "lint"),
        ("检查 wiki", "lint"),
        ("整理到 Wiki", "ingest"),
    ],
)
def test_wiki_proposal_kind(message: str, expected: str) -> None:
    assert _wiki_proposal_kind(message) == expected
