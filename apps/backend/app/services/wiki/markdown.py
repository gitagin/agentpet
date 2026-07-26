from .common import *
from .planning_candidates import _entity_kind_from_key
from .utility import _table_cell, _unique

def _source_summary_markdown(
    request: WikiIngestPreviewRequest,
    source_hash: str,
    links: list[str],
) -> str:
    summary = _summary_from_source(request.content)
    lines = [
        "## 来源摘要",
        "",
        f"- 来源类型：`{request.source_type}`",
        f"- 来源哈希：`{source_hash}`",
    ]
    if request.source_uri:
        lines.append(f"- 来源地址：{request.source_uri}")
    if links:
        lines.append("- 关联链接：" + ", ".join(f"[[{link}]]" for link in links))
    lines.extend(["", summary])
    return "\n".join(lines).strip()


def _concept_update_markdown(title: str, request: WikiIngestPreviewRequest, source_path: str) -> str:
    excerpt = _summary_from_source(request.content, max_lines=3)
    return "\n".join(
        [
            f"## 来源：{request.title}",
            "",
            f"- 来源页面：`{source_path}`",
            f"- 来源类型：`{request.source_type}`",
            "",
            excerpt,
        ]
    ).strip()


def _entity_update_markdown(
    candidate,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> str:
    lines = [
        f"## 来源：{request.title}",
        "",
        f"- 实体类型：`{candidate.kind}`",
        f"- 来源页面：`{source_path}`",
    ]
    if candidate.evidence:
        lines.append(f"- 提取信号：{candidate.evidence}")
    lines.extend(["", _summary_from_source(request.content, max_lines=4)])
    return "\n".join(lines).strip()


def _comparison_update_markdown(
    candidate,
    request: WikiIngestPreviewRequest,
    source_path: str,
) -> str:
    lines = [
        f"## 来源：{request.title}",
        "",
        f"- 来源页面：`{source_path}`",
        f"- 对比页面：[[{candidate.left}]] 和 [[{candidate.right}]]",
        f"- 提取信号：{candidate.reason or '对比'}",
        "",
        _summary_from_source(request.content, max_lines=4),
    ]
    return "\n".join(lines).strip()


def _ingest_synthesis_markdown(
    request: WikiIngestPreviewRequest,
    *,
    source_path: str,
    related_titles: list[str],
    entity_candidates: list,
    comparison_candidates: list,
) -> str:
    lines = [
        f"## 综合：{request.title}",
        "",
        f"- 来源页面：`{source_path}`",
        f"- 关联概念：{', '.join(related_titles) if related_titles else '无'}",
        f"- 实体：{', '.join(candidate.title for candidate in entity_candidates) if entity_candidates else '无'}",
        f"- 对比：{', '.join(_comparison_title(candidate) for candidate in comparison_candidates) if comparison_candidates else '无'}",
        "",
        _summary_from_source(request.content, max_lines=5),
    ]
    return "\n".join(lines).strip()


def _maintenance_markdown(request: WikiIngestPreviewRequest, *, source_path: str) -> str:
    signals = _maintenance_signals(request.content)
    lines = [
        f"## 维护：{request.title}",
        "",
        f"- 来源页面：`{source_path}`",
        f"- 信号：{', '.join(signals) if signals else '审查'}",
        "- 操作：在应用为持久化事实之前，审查冲突、过时声明、重复项和缺失的跟进页面。",
        "",
        _summary_from_source(request.content, max_lines=5),
    ]
    return "\n".join(lines).strip()


def _maintenance_signals(content: str) -> list[str]:
    normalized = content.casefold()
    return [
        marker
        for marker in (
            "conflict",
            "contradict",
            "inconsistent",
            "stale",
            "duplicate",
            "drift",
            "todo",
            "follow-up",
            "open question",
            "unclear",
            "disagreement",
        )
        if marker in normalized
    ]


def _comparison_title(candidate) -> str:
    return f"{candidate.left} vs {candidate.right}"


def _query_archive_markdown(request: QueryArchiveRequest, citations: list[MemorySearchResult]) -> str:
    lines = [
        "## 查询归档",
        "",
        "### 问题",
        "",
        request.question.strip(),
        "",
        "### 回答",
        "",
        request.answer.strip(),
        "",
        "### 引用",
        "",
        "| 来源 | 标题 | 范围 | 检索方式 | 摘要 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for citation in citations:
        lines.append(
            "| "
            + " | ".join(
                [
                    _table_cell(citation.relative_path),
                    _table_cell(citation.heading or ""),
                    _table_cell(citation.source_scope),
                    _table_cell(citation.retrieval_mode),
                    _table_cell(citation.snippet),
                ]
            )
            + " |"
        )
    if request.agent_run_id or request.source_message_id:
        lines.extend(["", "### 元数据", ""])
        if request.agent_run_id:
            lines.append(f"- 智能体运行：`{request.agent_run_id}`")
        if request.source_message_id:
            lines.append(f"- 来源消息：`{request.source_message_id}`")
    return "\n".join(lines).strip()


def _synthesis_markdown(request: WikiSynthesizeRequest) -> str:
    lines = [
        "## 综合整理",
        "",
        request.content.strip(),
    ]
    if request.source_paths:
        lines.extend(["", "### 来源页面", ""])
        for path in request.source_paths:
            lines.append(f"- [[{path}]]")
    return "\n".join(lines).strip()


def _ingest_log_details(
    *,
    run_status: str,
    pages_written: int,
    results: list[WikiIngestPageResult],
) -> str:
    lines = [
        f"- 状态：{run_status}",
        f"- 已写入页面：{pages_written}",
        "- 页面：",
    ]
    for result in results:
        lines.append(f"  - `{result.relative_path}` ({result.status})")
    return "\n".join(lines)


def _summary_from_source(content: str, *, max_lines: int = 8) -> str:
    parsed = parse_markdown(content, fallback_title="来源")
    lines = []
    for line in parsed.body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("# "):
            continue
        lines.append(stripped)
        if len(lines) >= max_lines:
            break
    if not lines:
        lines = [parsed.title]
    return "\n".join(f"- {line}" for line in lines)


def _related_titles(
    request: WikiIngestPreviewRequest,
    parsed_links: list[str],
    parsed_tags: list[str] | None = None,
) -> list[str]:
    titles = [*request.links, *parsed_links]
    for tag in _unique([*request.tags, *(parsed_tags or [])]):
        title = _concept_title_from_tag(tag)
        if title:
            titles.append(title)
    return [title for title in _unique(titles) if title and title.casefold() != request.title.casefold()]


def _concept_title_from_tag(tag: str) -> str:
    marker, separator, raw_title = tag.partition("/")
    if separator and _entity_kind_from_key(marker) is not None:
        return ""
    value = raw_title if separator else tag
    return value.replace("-", " ").replace("_", " ").strip().title()


def _citation_links(citations: list[MemorySearchResult]) -> list[str]:
    return _unique(citation.title for citation in citations if citation.title)


def _default_query_title(question: str) -> str:
    compact = re.sub(r"\s+", " ", question).strip()
    if len(compact) > 72:
        compact = compact[:72].rstrip()
    return f"查询归档 - {compact or '回答'}"


def _query_archive_section(request: QueryArchiveRequest) -> str:
    if request.agent_run_id:
        return f"查询归档 - {request.agent_run_id}"
    digest = sha256_hex(f"{request.question}\n{request.answer}")[:12]
    return f"查询归档 - {digest}"
