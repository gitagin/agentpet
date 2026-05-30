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


DEFAULT_SCHEMA_MARKDOWN = """# LLM Wiki 规范

## 目标
从不可变的原始资料中维护一个不断增长的 Markdown Wiki。助手是 Wiki 维护者，不是一次性聊天机器人。

## 层级
- 原始来源是只读证据。不要重写或替换它们。
- Wiki Markdown 是 `Wiki/` 下的维护知识层。
- 本规范定义页面契约、工作流规则和质量检查。

## 必需文件
- `Wiki/index.md` 是内容地图。每个维护页面都必须有对应条目。
- `Wiki/log.md` 是仅追加的操作时间线。
- `Wiki/AGENTS.md` 是此规则层。

## 页面类型
- source：一个来源摘要和引用。
- entity：人、公司、项目、论文、文件、决策或其他命名对象。
- concept：可复用的想法或术语。
- synthesis：从多个页面或来源得出的结论。
- comparison：实体、概念或方法之间的结构化对比。
- report：操作输出，如检查或查询归档报告。

## 硬边界
- 原始来源目录和原始日记文件是只读证据。永远不要删除、重写或静默规范化它们。
- Wiki 页面可以总结、链接和注释证据，但不得将推断的摘要冒充为原始声明。
- 每个维护页面都应添加内部链接、引用来源路径、更新索引并追加中央日志。

## 必需页面模板
每个维护的知识页面应按顺序保留以下八个部分：
1. 核心定义
2. 核心要点
3. 经典案例
4. 实践方法
5. 常见误区
6. 相关知识点
7. 原文出处
8. 对用户/决策的意义

页面可在八个必需部分之后添加额外的 `更新日志` 和 `自检清单` 部分。

## 证据与触发来源
- 从原始资料复制或推导的声明必须引用 Obsidian 链接，如 `[[Memories/Daily/...]]` 或 `[[Wiki/Sources/...]]`。
- `原文出处` 部分必须区分原始声明和助手推断。
- 自动写入必须记录触发来源：用户查询/消息 ID、Agent 运行 ID 以及来源路径（如有）。

## 审查与自检
认为写入完成之前，运行七项自检：
1. 索引同步
2. 关键词同步
3. 关系图谱
4. 入链检查
5. AGENTS 同步
6. 内嵌日志
7. 集中日志

## 版本与日志
- 前置元数据应尽可能包含 `revision`、`confidence`、`disputed` 和 `sources`。
- 冲突的知识被标记而非删除；保留双方并引用其来源。
- 需要双层日志：每页 `更新日志` 加上仅追加的 `Wiki/log.md`。

## 导入
1. 保存原始来源和来源哈希。
2. 创建或更新来源页面。
3. 更新相关的实体、概念、综合或对比页面。
4. 更新 `Wiki/index.md`。
5. 追加 `Wiki/log.md`。
6. 运行检查或记录检查摘要。

## 查询
1. 首先阅读 `Wiki/index.md` 以确定相关页面。
2. 阅读相关的 Wiki 页面和必要的原始来源。
3. 只从证据中回答。
4. 当有价值且安全时，将答案保存为维护页面。
5. 更新 `Wiki/index.md`。
6. 追加页面更新日志和 `Wiki/log.md`。
7. 运行或安排检查/自检。

## 检查
检查矛盾、过时声明、孤立页面、断裂链接、缺失的索引条目、缺失的日志记录、重复概念、命名偏差以及规范/前置元数据缺失。

## 术语与格式陷阱
- 查询：从日记、记忆和 Wiki 证据中回答用户问题。
- 整理：从可复用证据中创建或更新维护的 Wiki 页面。
- 来源：不可变的原始证据或日记记录。
- 综合：必须标注为推断的助手推断。
- 常见陷阱：未填写的占位符计数、不一致的标题格式、孤立页面、零字节页面、Wiki/Memories 外的链接、空的 `sources`、缺失的页面日志。

## 写作规则
- 保持页面简洁、结构化且可链接。
- 以结论开头，然后是证据。
- 重要声明需要来源引用。
- 不要静默合并冲突；记录冲突的来源和差异。
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
            raise WikiWriteError("写入 Wiki 页面失败。") from exc

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
