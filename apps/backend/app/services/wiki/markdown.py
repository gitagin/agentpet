from .common import *
from .contracts import unique_evidence, validate_page_type
from .planning_candidates import _entity_kind_from_key
from .utility import _table_cell, _unique

def _source_summary_markdown(
    request: WikiIngestPreviewRequest,
    source_hash: str,
    links: list[str],
) -> str:
    summary = _summary_from_source(request.content)
    lines = [
        f"- 来源类型：`{request.source_type}`",
        f"- 来源哈希：`{source_hash}`",
    ]
    if request.source_uri:
        lines.append(f"- 来源地址：{request.source_uri}")
    if links:
        lines.append("- 关联链接：" + ", ".join(f"[[{link}]]" for link in links))
    lines.extend(["", "## 不可变摘录", "", summary])
    return "\n".join(lines).strip()


def _concept_update_markdown(title: str, request: WikiIngestPreviewRequest, source_path: str) -> str:
    excerpt = _summary_from_source(request.content, max_lines=3)
    return "\n".join(
        [
            "## 定义",
            "",
            f"{title} 的当前定义来自已保存来源，尚未由独立证据扩展。",
            "",
            "## 来源",
            "",
            f"- 来源页面：`{source_path}`",
            f"- 来源类型：`{request.source_type}`",
            "",
            "## 证据摘录",
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
        "## 实体定义",
        "",
        f"{candidate.title}（{candidate.kind}）由来源中的明确实体信号指向。",
        "",
        "## 已确认事实",
        "",
        _summary_from_source(request.content, max_lines=4),
        "",
        "## 来源",
        "",
        f"- 实体类型：`{candidate.kind}`",
        f"- 来源页面：`{source_path}`",
    ]
    if candidate.evidence:
        lines.extend([f"- 提取信号：{candidate.evidence}"])
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


def _query_archive_markdown(request: QueryArchiveRequest, citations: list[MemorySearchResult]) -> str:
    lines = [
        "## 范围",
        "",
        request.question.strip(),
        "",
        "## 结果",
        "",
        request.answer.strip(),
        "",
        "## 证据",
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
        lines.extend(["", "## 生成信息", ""])
        if request.agent_run_id:
            lines.append(f"- 智能体运行：`{request.agent_run_id}`")
        if request.source_message_id:
            lines.append(f"- 来源消息：`{request.source_message_id}`")
    return "\n".join(lines).strip()


def _synthesis_markdown(request: WikiSynthesizeRequest) -> str:
    page_type = request.page_type
    sources = list(unique_evidence(request.source_paths))
    evidence_ids = list(unique_evidence(request.evidence_ids))
    validate_page_type(
        page_type,
        sources=sources,
        evidence_ids=evidence_ids,
        user_decision=request.user_decision,
        inference=page_type != "decision",
    )
    source_lines = [f"- [[{path}]]" for path in sources]
    evidence_lines = [f"- `{item}`" for item in evidence_ids]
    if page_type == "decision":
        sections = [("用户决定", request.user_decision or ""), ("背景", request.content)]
    elif page_type == "comparison":
        sections = [
            ("比较对象", request.title),
            ("差异", request.content),
            ("共同证据", "\n".join(source_lines or evidence_lines)),
        ]
    elif page_type == "report":
        sections = [("范围", request.title), ("结果", request.content)]
    else:
        sections = [("问题", request.title), ("结论", request.content)]
    lines: list[str] = []
    for heading, body in sections:
        cleaned = body.strip()
        if not cleaned:
            continue
        lines.extend([f"## {heading}", "", cleaned])
    if page_type == "decision":
        lines.extend(["", "## 依据", "", *(source_lines or evidence_lines)])
    elif page_type in {"synthesis", "comparison"}:
        lines.extend(["", "## 支持证据", "", *(source_lines or evidence_lines)])
    elif page_type == "report":
        lines.extend(["", "## 证据", "", *(source_lines or evidence_lines)])
    if source_lines:
        lines.extend(["", "## 来源", "", *source_lines])
    if page_type in {"synthesis", "comparison"}:
        lines.extend(["", "## 反证与不确定性", "", "未解决冲突不会进入确定性结论。"])
    if page_type == "decision" and request.links:
        lines.extend(["", "## 替代方案", "", *[f"- [[{path}]]" for path in _unique(request.links)]])
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
