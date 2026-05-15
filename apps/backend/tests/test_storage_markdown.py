from app.storage.markdown import parse_markdown


def test_parse_markdown_extracts_metadata_and_chunks() -> None:
    parsed = parse_markdown(
        """---
title: Project Memory
tags: [agent, memory]
---
# Main Title

Body with #local-tag and [[Linked Note]].

## Details

More text.
""",
        fallback_title="Fallback",
        max_chunk_chars=80,
    )

    assert parsed.title == "Project Memory"
    assert parsed.frontmatter["title"] == "Project Memory"
    assert parsed.tags == ["agent", "local-tag", "memory"]
    assert parsed.links == ["Linked Note"]
    assert len(parsed.chunks) >= 2
    assert parsed.chunks[0].heading == "Main Title"


def test_parse_markdown_extracts_simple_block_list_frontmatter() -> None:
    parsed = parse_markdown(
        """---
title: Wiki Concept
type: concept
aliases:
  - Concept Alias
  - Another Alias
sources:
  - Wiki/Sources/Source-A.md
  - message:run-1
---
# Wiki Concept

Body.
""",
        fallback_title="Fallback",
    )

    assert parsed.title == "Wiki Concept"
    assert parsed.frontmatter["type"] == "concept"
    assert parsed.frontmatter["aliases"] == ["Concept Alias", "Another Alias"]
    assert parsed.frontmatter["sources"] == ["Wiki/Sources/Source-A.md", "message:run-1"]
