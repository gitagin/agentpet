from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from app.models.api import (
    WikiBrokenLink,
    WikiGraphEdge,
    WikiGraphNode,
    WikiGraphSummaryResponse,
    WikiIndexEntry,
    WikiIndexResponse,
    WikiLogEntry,
    WikiLogResponse,
    WikiPageResponse,
    WikiPageSummary,
    WikiPageWriteRequest,
    WikiSchemaStatus,
)
from app.services.memory import MarkdownWriteError, SafeMarkdownWriter
from app.services.write_policy import MarkdownWritePolicyRequest, evaluate_markdown_write
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso
from app.storage.markdown import read_markdown


WIKI_ROOT = "Wiki"
WIKI_SCHEMA_PATH = f"{WIKI_ROOT}/AGENTS.md"
WIKI_INDEX_PATH = f"{WIKI_ROOT}/index.md"
WIKI_LOG_PATH = f"{WIKI_ROOT}/log.md"
WIKI_CORE_PATHS = {WIKI_SCHEMA_PATH, WIKI_INDEX_PATH, WIKI_LOG_PATH}
WIKI_PAGE_TEMPLATE_SECTIONS = (
    "核心定义",
    "核心要点",
    "经典案例",
    "实践方法",
    "常见误区",
    "相关知识点",
    "原文出处",
    "对用户/决策的意义",
)
WIKI_SELF_CHECK_ITEMS = (
    "索引同步",
    "关键词同步",
    "关系图谱",
    "入链检查",
    "AGENTS 同步",
    "内嵌日志",
    "集中日志",
)


@dataclass(frozen=True)
class _GraphPage:
    title: str
    relative_path: str
    links: list[str]
    frontmatter: dict[str, str | list[str]]


DEFAULT_SCHEMA_MARKDOWN = """# LLM Wiki Schema

## Goal
Maintain a growing markdown wiki from immutable source material. The assistant is a wiki maintainer, not a one-off chat bot.

## Layers
- Raw sources are read-only evidence. Do not rewrite or replace them.
- Wiki markdown is the maintained knowledge layer under `Wiki/`.
- This schema defines page contracts, workflow rules, and quality checks.

## Required Files
- `Wiki/index.md` is the content map. Every maintained page must have an entry.
- `Wiki/log.md` is the append-only operation timeline.
- `Wiki/AGENTS.md` is this rule layer.

## Page Types
- source: one source summary and citations.
- entity: person, company, project, paper, file, decision, or other named object.
- concept: reusable idea or term.
- synthesis: conclusion drawn from multiple pages or sources.
- comparison: structured contrast between entities, concepts, or approaches.
- report: operational output such as lint or query archive reports.

## Hard Boundaries
- Raw source directories and original diary files are read-only evidence. Never delete, rewrite, or silently normalize them.
- Wiki pages may summarize, link, and annotate evidence, but must not pretend inferred summaries are original claims.
- Every maintained page should add internal links, cite source paths, update the index, and append the central log.

## Required Page Template
Every maintained knowledge page should keep these eight sections in order:
1. 核心定义
2. 核心要点
3. 经典案例
4. 实践方法
5. 常见误区
6. 相关知识点
7. 原文出处
8. 对用户/决策的意义

Pages may add an extra `更新日志` and `自检清单` section after the eight required sections.

## Evidence And Trigger Source
- Claims copied or derived from source material must cite Obsidian links such as `[[Memories/Daily/...]]` or `[[Wiki/Sources/...]]`.
- The `原文出处` section must separate original claims from assistant inference.
- Automatic writes must record trigger source: user query/message id, agent run id, and source paths when available.

## Review And Self Check
Before considering a write complete, run the seven-item self-check:
1. 索引同步
2. 关键词同步
3. 关系图谱
4. 入链检查
5. AGENTS 同步
6. 内嵌日志
7. 集中日志

## Version And Logs
- Frontmatter should include `revision`, `confidence`, `disputed`, and `sources` when possible.
- Conflicting knowledge is marked instead of deleted; preserve both sides and cite their sources.
- Double-layer logs are required: per-page `更新日志` plus append-only `Wiki/log.md`.

## Ingest
1. Preserve the raw source and source hash.
2. Create or update a source page.
3. Update related entity, concept, synthesis, or comparison pages.
4. Update `Wiki/index.md`.
5. Append `Wiki/log.md`.
6. Run lint or record the lint summary.

## Query
1. Read `Wiki/index.md` first to identify relevant pages.
2. Read relevant wiki pages and necessary raw sources.
3. Answer only from evidence.
4. Save valuable answers as maintained pages when they are reusable and safe.
5. Update `Wiki/index.md`.
6. Append page update log and `Wiki/log.md`.
7. Run or schedule lint/self-check.

## Lint
Check contradictions, stale statements, orphan pages, broken links, missing index entries, missing log records, duplicate concepts, naming drift, and schema/frontmatter gaps.

## Terminology And Format Traps
- query: answer a user question from diary, memory, and Wiki evidence.
- organize: create or update maintained Wiki pages from reusable evidence.
- source: immutable raw evidence or diary record.
- synthesis: assistant inference that must be labeled as inference.
- Common traps: placeholder counts left unfilled, inconsistent heading formats, orphan pages, zero-byte pages, links outside Wiki/Memories, empty `sources`, missing page logs.

## Writing Rules
- Keep pages concise, structured, and linkable.
- Start with conclusions, then evidence.
- Important claims need source references.
- Do not merge conflicts silently; record the conflicting sources and the difference.
"""


class WikiWriteError(Exception):
    code = "wiki_write_failed"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        self.reason = reason
        super().__init__(message)


class SensitiveWikiRejectedError(Exception):
    code = "sensitive_wiki_rejected"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "sensitive_content"
        super().__init__("Wiki 内容未通过记忆污染策略检查。")


class WikiService:
    def __init__(
        self,
        writer: SafeMarkdownWriter,
        *,
        index_refresh: Callable[[str], str | None] | None = None,
    ) -> None:
        self.writer = writer
        self.index_refresh = index_refresh

    def write_page(self, request: WikiPageWriteRequest) -> WikiPageResponse:
        relative_path = resolve_wiki_path(request.title, request.target_path)
        policy = evaluate_markdown_write(
            MarkdownWritePolicyRequest(
                scope="wiki",
                target_path=relative_path,
                title=request.title,
                content=request.content,
                metadata=_write_policy_metadata(request),
            )
        )
        if not policy.allowed:
            raise SensitiveWikiRejectedError(policy.reason)

        self.ensure_core_files()
        target = self.writer.resolve_markdown_path(relative_path)
        existed = target.exists()
        now = utc_now_iso()
        frontmatter = _wiki_frontmatter(request, relative_path)
        metadata = _metadata_block(tags=request.tags, links=request.links)

        try:
            if request.operation == "replace_section":
                section = (request.section or request.title).strip()
                markdown = _replace_section(
                    _read_text(target),
                    title=request.title,
                    section=section,
                    content=request.content,
                    metadata=metadata,
                    frontmatter=frontmatter,
                )
                self.writer.write(relative_path, markdown)
            else:
                entry = _append_entry(
                    title=request.title,
                    content=request.content,
                    section=request.section,
                    metadata=metadata,
                    timestamp=now,
                    include_title=not existed,
                    frontmatter=frontmatter if not existed else {},
                )
                if request.operation == "create" and not existed:
                    self.writer.write(relative_path, entry)
                else:
                    self.writer.append(relative_path, entry)
        except MarkdownWriteError:
            raise
        except Exception as exc:
            raise WikiWriteError("Failed to write wiki page.") from exc

        index_job_id = self.index_refresh(relative_path) if self.index_refresh else None
        return WikiPageResponse(
            title=request.title,
            relative_path=relative_path,
            operation=request.operation,
            status="created" if not existed else "updated",
            index_job_id=index_job_id,
        )

    def list_pages(self) -> list[WikiPageSummary]:
        self.ensure_core_files()
        root = self.writer.vault_root / WIKI_ROOT
        if not root.exists():
            return []
        pages: list[WikiPageSummary] = []
        for path in sorted(root.rglob("*.md")):
            try:
                relative_path = path.relative_to(self.writer.vault_root).as_posix()
            except ValueError:
                continue
            if relative_path in WIKI_CORE_PATHS:
                continue
            pages.append(
                WikiPageSummary(
                    title=_page_title(path),
                    relative_path=relative_path,
                    updated_at=utc_now_iso_from_mtime(path),
                )
            )
        return pages

    def ensure_core_files(self) -> None:
        self._write_if_missing(WIKI_SCHEMA_PATH, DEFAULT_SCHEMA_MARKDOWN)
        self._write_if_missing(WIKI_INDEX_PATH, _render_index([]))
        self._write_if_missing(WIKI_LOG_PATH, "# Wiki Log\n\n")

    def get_schema_status(self) -> WikiSchemaStatus:
        self.ensure_core_files()
        path = self.writer.resolve_markdown_path(WIKI_SCHEMA_PATH)
        return WikiSchemaStatus(
            exists=path.exists(),
            updated_at=utc_now_iso_from_mtime(path) if path.exists() else None,
            content=_read_text(path),
        )

    def refresh_index(self) -> WikiIndexResponse:
        self.ensure_core_files()
        entries = self._index_entries()
        markdown = _render_index(entries)
        self.writer.write(WIKI_INDEX_PATH, markdown)
        if self.index_refresh:
            self.index_refresh(WIKI_INDEX_PATH)
        return WikiIndexResponse(
            updated_at=utc_now_iso(),
            entries=entries,
            content=markdown,
        )

    def get_index(self) -> WikiIndexResponse:
        self.ensure_core_files()
        path = self.writer.resolve_markdown_path(WIKI_INDEX_PATH)
        content = _read_text(path)
        return WikiIndexResponse(
            updated_at=utc_now_iso_from_mtime(path) if path.exists() else None,
            entries=_parse_index_entries(content),
            content=content,
        )

    def get_graph_summary(self) -> WikiGraphSummaryResponse:
        pages = self._graph_pages()
        index_entries = _parse_index_entries(_read_text(self.writer.vault_root / WIKI_INDEX_PATH))
        indexed_paths = {entry.relative_path for entry in index_entries}
        by_title = {page.title.casefold(): page for page in pages}
        by_slug = {Path(page.relative_path).stem.casefold(): page for page in pages}
        by_relative_path = {page.relative_path.casefold(): page for page in pages}
        nodes_by_path: dict[str, WikiGraphNode] = {
            page.relative_path: WikiGraphNode(
                title=page.title,
                relative_path=page.relative_path,
                page_type=_page_type(page.relative_path, page.frontmatter),
                vault_relative_path=page.relative_path,
                obsidian_uri=_obsidian_uri(page.relative_path),
                indexed=page.relative_path in indexed_paths,
            )
            for page in pages
        }
        edges: list[WikiGraphEdge] = []
        broken_links: list[WikiBrokenLink] = []
        incoming_counts = {path: 0 for path in nodes_by_path}
        outgoing_counts = {path: 0 for path in nodes_by_path}

        for page in pages:
            for link in page.links:
                target = _resolve_graph_link(link, by_title=by_title, by_slug=by_slug, by_relative_path=by_relative_path)
                if target is None:
                    edges.append(WikiGraphEdge(source_path=page.relative_path, target=link, resolved=False))
                    broken_links.append(WikiBrokenLink(source_path=page.relative_path, target=link))
                    continue
                outgoing_counts[page.relative_path] += 1
                incoming_counts[target.relative_path] += 1
                edges.append(
                    WikiGraphEdge(
                        source_path=page.relative_path,
                        target_path=target.relative_path,
                        target=link,
                        resolved=True,
                    )
                )

        nodes: list[WikiGraphNode] = []
        for path, node in nodes_by_path.items():
            nodes.append(
                node.model_copy(
                    update={
                        "in_degree": incoming_counts[path],
                        "out_degree": outgoing_counts[path],
                    }
                )
            )
        nodes = sorted(nodes, key=lambda node: (node.relative_path.casefold(), node.title.casefold()))
        hubs = sorted(
            [node for node in nodes if node.in_degree + node.out_degree > 0],
            key=lambda node: (-(node.in_degree + node.out_degree), -node.in_degree, node.relative_path.casefold()),
        )[:10]
        orphans = [
            node
            for node in nodes
            if node.in_degree == 0 and node.out_degree == 0 and node.relative_path not in WIKI_CORE_PATHS
        ]
        return WikiGraphSummaryResponse(
            generated_at=utc_now_iso(),
            summary={
                "nodes": len(nodes),
                "edges": len(edges),
                "resolved_edges": sum(1 for edge in edges if edge.resolved),
                "broken_links": len(broken_links),
                "hubs": len(hubs),
                "orphans": len(orphans),
                "indexed_nodes": sum(1 for node in nodes if node.indexed),
            },
            nodes=nodes,
            edges=sorted(edges, key=lambda edge: (edge.source_path.casefold(), edge.target.casefold())),
            hubs=hubs,
            orphans=orphans,
            broken_links=sorted(broken_links, key=lambda link: (link.source_path.casefold(), link.target.casefold())),
        )

    def append_log(self, operation: str, title: str, details: str = "") -> WikiLogResponse:
        self.ensure_core_files()
        timestamp = _compact_timestamp(utc_now_iso())
        safe_operation = operation.strip() or "operation"
        safe_title = title.strip() or "Untitled"
        entry = f"## [{timestamp}] {safe_operation} | {safe_title}\n\n{details.strip()}\n"
        self.writer.append(WIKI_LOG_PATH, entry)
        if self.index_refresh:
            self.index_refresh(WIKI_LOG_PATH)
        return self.get_log()

    def get_log(self, limit: int = 50) -> WikiLogResponse:
        self.ensure_core_files()
        path = self.writer.resolve_markdown_path(WIKI_LOG_PATH)
        content = _read_text(path)
        return WikiLogResponse(
            updated_at=utc_now_iso_from_mtime(path) if path.exists() else None,
            entries=_parse_log_entries(content)[: max(1, min(limit, 200))],
            content=content,
        )

    def core_lint_summary(self) -> dict[str, object]:
        self.ensure_core_files()
        index_paths = {entry.relative_path for entry in self.get_index().entries}
        page_paths = {entry.relative_path for entry in self._index_entries()}
        missing_index_entries = sorted(page_paths - index_paths)
        return {
            "core_files": 3,
            "indexed_pages": len(index_paths),
            "wiki_pages": len(page_paths),
            "missing_index_entries": len(missing_index_entries),
        }

    def _write_if_missing(self, relative_path: str, markdown: str) -> None:
        path = self.writer.resolve_markdown_path(relative_path)
        if path.exists():
            return
        self.writer.write(relative_path, markdown)

    def _index_entries(self) -> list[WikiIndexEntry]:
        root = self.writer.vault_root / WIKI_ROOT
        if not root.exists():
            return []
        entries: list[WikiIndexEntry] = []
        for path in sorted(root.rglob("*.md")):
            try:
                relative_path = path.relative_to(self.writer.vault_root).as_posix()
            except ValueError:
                continue
            if relative_path in WIKI_CORE_PATHS:
                continue
            entries.append(_index_entry_for(path, relative_path))
        return entries

    def _graph_pages(self) -> list["_GraphPage"]:
        root = self.writer.vault_root / WIKI_ROOT
        if not root.exists():
            return []
        pages: list[_GraphPage] = []
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = read_markdown(path)
                relative_path = path.relative_to(self.writer.vault_root).as_posix()
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            pages.append(
                _GraphPage(
                    title=parsed.title,
                    relative_path=relative_path,
                    links=parsed.links,
                    frontmatter=parsed.frontmatter,
                )
            )
        return pages


def resolve_wiki_path(title: str, target_path: str | None = None) -> str:
    if target_path:
        normalized = target_path.replace("\\", "/").strip("/")
    else:
        normalized = f"{WIKI_ROOT}/{slugify_wiki_title(title)}.md"
    parts = [part for part in normalized.split("/") if part]
    if not parts or parts[0] != WIKI_ROOT:
        raise MarkdownWriteError("wiki target_path must be under Wiki/")
    if any(part in {"..", "."} or part.startswith(".") for part in parts):
        raise MarkdownWriteError("wiki target_path contains an invalid path segment")
    if not normalized.lower().endswith(".md"):
        raise MarkdownWriteError("wiki target_path must point to a Markdown file")
    return "/".join(parts)


def slugify_wiki_title(title: str) -> str:
    compact = re.sub(r"\s+", "-", title.strip())
    compact = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", compact)
    compact = compact.strip(".- ")
    if not compact:
        compact = sha256_hex(title)[:12]
    return compact[:80]


def utc_now_iso_from_mtime(path: Path) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")


def _compact_timestamp(value: str) -> str:
    return value[:16].replace("T", " ")


def _index_entry_for(path: Path, relative_path: str) -> WikiIndexEntry:
    try:
        parsed = read_markdown(path)
        title = parsed.title
        body = parsed.body
        frontmatter = parsed.frontmatter
    except (OSError, UnicodeDecodeError):
        title = path.stem
        body = ""
        frontmatter = {}
    page_type = _page_type(relative_path, frontmatter)
    sources = _frontmatter_list(frontmatter, "sources")
    return WikiIndexEntry(
        title=title,
        relative_path=relative_path,
        page_type=page_type,
        summary=_page_summary(body, title),
        source_count=_source_count(page_type, body, frontmatter),
        aliases=_frontmatter_list(frontmatter, "aliases"),
        sources=sources,
        updated_at=utc_now_iso_from_mtime(path),
    )


def _page_type(relative_path: str, frontmatter: dict[str, str | list[str]]) -> str:
    fm_type = frontmatter.get("type")
    if isinstance(fm_type, str) and fm_type.strip():
        return fm_type.strip()
    normalized = relative_path.replace("\\", "/")
    parts = normalized.split("/")
    folder = parts[1].casefold() if len(parts) > 2 else ""
    return {
        "sources": "source",
        "entities": "entity",
        "concepts": "concept",
        "syntheses": "synthesis",
        "companion": "synthesis",
        "comparisons": "comparison",
        "reports": "report",
    }.get(folder, "page")


def _page_summary(body: str, fallback: str) -> str:
    in_frontmatter = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter or not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("Tags:") or stripped.startswith("Links:"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        return stripped[:180]
    return fallback[:180]


def _source_count(page_type: str, body: str, frontmatter: dict[str, str | list[str]]) -> int:
    value = frontmatter.get("sources")
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if page_type == "source":
        return 1
    return max(body.count("Source page:"), body.count("Source:"), body.count("[[Sources/"))


def _frontmatter_list(frontmatter: dict[str, str | list[str]], key: str) -> list[str]:
    value = frontmatter.get(key, [])
    if isinstance(value, list):
        return [item.strip() for item in value if item.strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _render_index(entries: list[WikiIndexEntry]) -> str:
    lines = [
        "# Wiki Index",
        "",
        "This file is the required content map for the LLM-maintained wiki.",
        "",
        "| Type | Page | Summary | Aliases | Sources | Updated |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for entry in sorted(entries, key=lambda item: (item.page_type, item.title.casefold(), item.relative_path)):
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_cell(entry.page_type),
                    f"[[{entry.relative_path}]]",
                    _table_cell(entry.summary),
                    _table_cell(", ".join(entry.aliases)),
                    str(entry.source_count),
                    _table_cell(entry.updated_at or ""),
                ]
            )
            + " |"
        )
    if not entries:
        lines.append("| _empty_ | _No wiki pages yet_ | Add sources through ingest. |  | 0 |  |")
    return "\n".join(lines).strip() + "\n"


def _parse_index_entries(content: str) -> list[WikiIndexEntry]:
    entries: list[WikiIndexEntry] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| ---") or "Page" in stripped and "Summary" in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5 or cells[0] == "_empty_":
            continue
        path_match = re.search(r"\[\[([^\]]+)\]\]", cells[1])
        relative_path = path_match.group(1) if path_match else cells[1]
        aliases: list[str] = []
        source_cell_index = 3
        updated_cell_index = 4
        if len(cells) >= 6:
            aliases = [item.strip() for item in cells[3].split(",") if item.strip()]
            source_cell_index = 4
            updated_cell_index = 5
        try:
            source_count = int(cells[source_cell_index])
        except ValueError:
            source_count = 0
        entries.append(
            WikiIndexEntry(
                title=Path(relative_path).stem,
                relative_path=relative_path,
                page_type=cells[0],
                summary=cells[2],
                source_count=source_count,
                aliases=aliases,
                updated_at=cells[updated_cell_index] or None,
            )
        )
    return entries


def _parse_log_entries(content: str) -> list[WikiLogEntry]:
    pattern = re.compile(r"^##\s+\[([^\]]+)\]\s+([^|]+)\|\s*(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    entries: list[WikiLogEntry] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        entries.append(
            WikiLogEntry(
                timestamp=match.group(1).strip(),
                operation=match.group(2).strip(),
                title=match.group(3).strip(),
                details=content[start:end].strip(),
            )
        )
    return list(reversed(entries))


def _page_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].strip() or path.stem
    except UnicodeDecodeError:
        return path.stem
    return path.stem


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _metadata_block(*, tags: list[str], links: list[str]) -> str:
    lines: list[str] = []
    clean_tags = [tag.strip().lstrip("#") for tag in tags if tag.strip()]
    clean_links = [link.strip() for link in links if link.strip()]
    if clean_tags:
        lines.append("Tags: " + " ".join(f"#{tag}" for tag in clean_tags))
    if clean_links:
        lines.append("Links: " + ", ".join(clean_links))
    return "\n".join(lines)


def _write_policy_metadata(request: WikiPageWriteRequest) -> dict[str, str]:
    values = {
        "page_type": request.page_type or "",
        "confidence": request.confidence or "",
        "expiry": request.expiry or "",
        "source_message_id": request.source_message_id or "",
        "tags": ", ".join(request.tags),
        "links": ", ".join(request.links),
        "authors": ", ".join(request.authors),
        "contributors": ", ".join(request.contributors),
        "aliases": ", ".join(request.aliases),
        "sources": ", ".join(request.sources),
    }
    return {key: value for key, value in values.items() if value}


def _wiki_frontmatter(request: WikiPageWriteRequest, relative_path: str) -> dict[str, str | list[str]]:
    page_type = (request.page_type or _page_type(relative_path, {})).strip() or "page"
    sources = _clean_list(request.sources)
    if request.source_message_id:
        sources = _unique_list([*sources, f"message:{request.source_message_id.strip()}"])
    data: dict[str, str | list[str]] = {
        "title": request.title.strip(),
        "type": page_type,
        "revision": "1",
        "disputed": "true" if request.disputed else "false",
    }
    optional_scalars = {
        "confidence": request.confidence,
        "expiry": request.expiry,
    }
    for key, value in optional_scalars.items():
        if value and value.strip():
            data[key] = value.strip()
    optional_lists = {
        "tags": [tag.strip().lstrip("#") for tag in request.tags],
        "authors": request.authors,
        "contributors": request.contributors,
        "aliases": request.aliases,
        "sources": sources,
    }
    for key, values in optional_lists.items():
        clean_values = _clean_list(values)
        if clean_values:
            data[key] = clean_values
    return data


def _frontmatter_markdown(frontmatter: dict[str, str | list[str]]) -> str:
    if not frontmatter:
        return ""
    lines = ["---"]
    for key, value in frontmatter.items():
        if isinstance(value, list):
            if not value:
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: str) -> str:
    text = value.strip()
    if not text:
        return '""'
    if re.search(r"[:#\[\]{},&*!|>'\"%@`]", text) or text.lower() in {"true", "false", "null"}:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _clean_list(values: list[str]) -> list[str]:
    return _unique_list([value.strip() for value in values if value and value.strip()])


def _unique_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _append_entry(
    *,
    title: str,
    content: str,
    section: str | None,
    metadata: str,
    timestamp: str,
    include_title: bool,
    frontmatter: dict[str, str | list[str]],
) -> str:
    lines: list[str] = []
    frontmatter_text = _frontmatter_markdown(frontmatter)
    if frontmatter_text:
        lines.extend([frontmatter_text, ""])
    if include_title:
        lines.extend([f"# {title.strip()}", ""])
    lines.extend([f"## {section.strip() if section else timestamp}", "", content.strip()])
    if metadata:
        lines.extend(["", metadata])
    return "\n".join(lines).strip() + "\n"


def _replace_section(
    existing: str,
    *,
    title: str,
    section: str,
    content: str,
    metadata: str,
    frontmatter: dict[str, str | list[str]],
) -> str:
    base = existing.strip()
    if not base:
        frontmatter_text = _frontmatter_markdown(frontmatter)
        base = f"{frontmatter_text}\n\n# {title.strip()}" if frontmatter_text else f"# {title.strip()}"
    block_lines = [f"## {section}", "", content.strip()]
    if metadata:
        block_lines.extend(["", metadata])
    block = "\n".join(block_lines).strip()
    pattern = re.compile(rf"(^##\s+{re.escape(section)}\s*$)(.*?)(?=^##\s+|\Z)", re.MULTILINE | re.DOTALL)
    if pattern.search(base):
        return pattern.sub(block + "\n", base).strip() + "\n"
    return f"{base}\n\n{block}\n"


def _table_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def _resolve_graph_link(
    link: str,
    *,
    by_title: dict[str, _GraphPage],
    by_slug: dict[str, _GraphPage],
    by_relative_path: dict[str, _GraphPage],
) -> _GraphPage | None:
    normalized = link.strip().replace("\\", "/").strip("/")
    if not normalized:
        return None
    candidates = [normalized]
    if not normalized.lower().endswith(".md"):
        candidates.append(f"{normalized}.md")
    if not normalized.startswith(f"{WIKI_ROOT}/"):
        candidates.append(f"{WIKI_ROOT}/{normalized}")
        if not normalized.lower().endswith(".md"):
            candidates.append(f"{WIKI_ROOT}/{normalized}.md")
    for candidate in candidates:
        page = by_relative_path.get(candidate.casefold())
        if page is not None:
            return page
    return by_title.get(normalized.casefold()) or by_slug.get(Path(normalized).stem.casefold())


def _obsidian_uri(relative_path: str) -> str:
    return f"obsidian://open?path={quote(relative_path, safe='')}"
