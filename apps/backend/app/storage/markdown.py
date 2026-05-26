from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.utils.hash import sha256_hex


FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
TAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9_\-/]+)")
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")


@dataclass(frozen=True)
class MarkdownChunk:
    index: int
    heading: str | None
    content: str
    start_line: int
    end_line: int
    content_hash: str


@dataclass(frozen=True)
class ParsedMarkdown:
    title: str
    frontmatter: dict[str, str | list[str]]
    tags: list[str]
    links: list[str]
    body: str
    chunks: list[MarkdownChunk] = field(default_factory=list)
    content_hash: str = ""


def parse_markdown(text: str, *, fallback_title: str = "未命名", max_chunk_chars: int = 1200) -> ParsedMarkdown:
    content_hash = sha256_text(text)
    frontmatter, body = _split_frontmatter(text)
    title = _title_from(frontmatter, body, fallback_title)
    tags = sorted(set(_frontmatter_tags(frontmatter) + TAG_RE.findall(body)))
    links = sorted(set(link.strip() for link in WIKILINK_RE.findall(body) if link.strip()))
    chunks = chunk_markdown(body, max_chunk_chars=max_chunk_chars)
    return ParsedMarkdown(
        title=title,
        frontmatter=frontmatter,
        tags=tags,
        links=links,
        body=body,
        chunks=chunks,
        content_hash=content_hash,
    )


def chunk_markdown(body: str, *, max_chunk_chars: int = 1200) -> list[MarkdownChunk]:
    lines = body.splitlines()
    chunks: list[MarkdownChunk] = []
    current: list[str] = []
    current_heading: str | None = None
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal current, start_line
        content = "\n".join(current).strip()
        if not content:
            current = []
            start_line = end_line + 1
            return
        chunks.append(
            MarkdownChunk(
                index=len(chunks),
                heading=current_heading,
                content=content,
                start_line=start_line,
                end_line=end_line,
                content_hash=sha256_text(content),
            )
        )
        current = []
        start_line = end_line + 1

    for line_no, line in enumerate(lines, start=1):
        heading_match = HEADING_RE.match(line)
        would_exceed = current and len("\n".join([*current, line])) > max_chunk_chars
        if heading_match and current:
            flush(line_no - 1)
        elif would_exceed:
            flush(line_no - 1)
        if not current:
            start_line = line_no
        if heading_match:
            current_heading = heading_match.group(2).strip()
        current.append(line)
    flush(len(lines))
    return chunks


def sha256_text(text: str) -> str:
    return sha256_hex(text)


def read_markdown(path: Path) -> ParsedMarkdown:
    text = path.read_text(encoding="utf-8-sig")
    return parse_markdown(text, fallback_title=path.stem)


def _split_frontmatter(text: str) -> tuple[dict[str, str | list[str]], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    return _parse_simple_frontmatter(match.group(1)), text[match.end() :]


def _parse_simple_frontmatter(raw: str) -> dict[str, str | list[str]]:
    data: dict[str, str | list[str]] = {}
    current_key: str | None = None
    current_items: list[str] = []
    for line in raw.splitlines():
        stripped_line = line.strip()
        if current_key is not None and stripped_line.startswith("- "):
            item = stripped_line[2:].strip()
            if item:
                current_items.append(item.strip("'\""))
            continue
        if current_key is not None:
            data[current_key] = current_items
            current_key = None
            current_items = []
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith("[") and value.endswith("]"):
            data[key] = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        elif not value:
            current_key = key
            current_items = []
        else:
            data[key] = value.strip("'\"")
    if current_key is not None:
        data[current_key] = current_items
    return data


def _title_from(frontmatter: dict[str, str | list[str]], body: str, fallback: str) -> str:
    fm_title = frontmatter.get("title")
    if isinstance(fm_title, str) and fm_title.strip():
        return fm_title.strip()
    for line in body.splitlines():
        match = HEADING_RE.match(line)
        if match and len(match.group(1)) == 1:
            return match.group(2).strip()
    return fallback


def _frontmatter_tags(frontmatter: dict[str, str | list[str]]) -> list[str]:
    value = frontmatter.get("tags", [])
    if isinstance(value, str):
        return [tag.strip().lstrip("#") for tag in value.split(",") if tag.strip()]
    return [tag.strip().lstrip("#") for tag in value if tag.strip()]
