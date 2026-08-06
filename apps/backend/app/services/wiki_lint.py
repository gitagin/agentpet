from __future__ import annotations

import sqlite3
import re
from dataclasses import dataclass
from pathlib import Path

from app.models.api import (
    WikiLintIssue,
    WikiLintRepairProposal,
    WikiLintRequest,
    WikiLintReportResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
    WikiResearchQuestion,
)
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso
from app.services.wiki import WIKI_PAGE_TEMPLATE_SECTIONS, WIKI_ROOT, WikiService
from app.storage.markdown import read_markdown


@dataclass(frozen=True)
class _WikiPage:
    title: str
    relative_path: str
    links: list[str]
    content_hash: str
    frontmatter: dict[str, str | list[str]]
    body: str


@dataclass(frozen=True)
class WikiDiagnosticsQueueItem:
    diagnostic_type: str
    severity: str
    issue_code: str
    title: str
    message: str
    path: str | None = None
    target: str | None = None
    repair_preview: WikiLintRepairProposal | None = None


class WikiLintService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        vault_id: str,
        vault_root: str | Path,
        wiki: WikiService | None = None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.vault_id = vault_id
        self.vault_root = Path(vault_root)
        self.wiki = wiki

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def run(self, request: WikiLintRequest | None = None) -> WikiLintReportResponse:
        lint_request = request or WikiLintRequest()
        if self.wiki is not None:
            self.wiki.ensure_core_files()
        generated_at = utc_now_iso()
        pages = self._load_pages()
        issues: list[WikiLintIssue] = []
        issues.extend(self._core_file_issues(pages))
        issues.extend(_schema_frontmatter_issues(pages))
        issues.extend(_duplicate_title_issues(pages))
        issues.extend(_template_section_issues(pages))
        issues.extend(_evidence_source_issues(pages))
        issues.extend(_version_log_issues(pages, self.vault_root))
        issues.extend(_orphan_page_issues(pages))
        issues.extend(_inbound_link_count_issues(pages))
        issues.extend(_broken_link_issues(pages))
        issues.extend(_format_trap_issues(pages))
        issues.extend(self._index_issues(pages))
        issues.extend(self._index_job_issues())
        issues.extend(self._vector_index_issues(pages))
        issues.extend(self._graph_conflict_issues())
        issues.extend(_contradiction_marker_issues(pages))
        issues.extend(_stale_marker_issues(pages))
        issues.extend(_missing_concept_issues(pages))
        issues.extend(_duplicate_entity_issues(pages))
        research_questions = _research_questions(issues)
        repair_proposals = _repair_proposals(issues, pages)
        summary = _summary(pages, issues, research_questions, repair_proposals)
        report_page = None
        if lint_request.write_report and self.wiki is not None:
            report_page = self._write_report(generated_at, summary, issues, research_questions, repair_proposals)
        if self.wiki is not None:
            self.wiki.append_log(
                "lint",
                "Wiki 检查",
                f"- 问题：{summary.get('issues', 0)}\n- 错误：{summary.get('errors', 0)}\n- 待研究问题：{summary.get('research_questions', 0)}",
            )
        return WikiLintReportResponse(
            generated_at=generated_at,
            summary=summary,
            issues=sorted(
                issues,
                key=lambda issue: (
                    _severity_rank(issue.severity),
                    issue.code,
                    issue.path or "",
                    issue.target or "",
                ),
            ),
            research_questions=research_questions,
            repair_proposals=repair_proposals,
            report_page=report_page,
        )

    def diagnostics_queue(self) -> list[WikiDiagnosticsQueueItem]:
        pages = self._load_pages()
        issues: list[WikiLintIssue] = []
        issues.extend(_contradiction_marker_issues(pages))
        issues.extend(_stale_marker_issues(pages))
        issues.extend(_broken_link_issues(pages))
        issues.extend(_missing_concept_issues(pages))
        return _diagnostics_queue_items(issues, pages)

    def _load_pages(self) -> list[_WikiPage]:
        root = self.vault_root / WIKI_ROOT
        if not root.exists():
            return []
        pages = []
        for path in sorted(root.rglob("*.md")):
            try:
                parsed = read_markdown(path)
                relative_path = path.relative_to(self.vault_root).as_posix()
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            if relative_path.startswith(f"{WIKI_ROOT}/Reports/"):
                continue
            pages.append(
                _WikiPage(
                    title=parsed.title,
                    relative_path=relative_path,
                    links=parsed.links,
                    content_hash=parsed.content_hash,
                    frontmatter=parsed.frontmatter,
                    body=parsed.body,
                )
            )
        return pages

    def _core_file_issues(self, pages: list[_WikiPage]) -> list[WikiLintIssue]:
        root = self.vault_root / WIKI_ROOT
        issues: list[WikiLintIssue] = []
        core_paths = ("Wiki/AGENTS.md", "Wiki/index.md", "Wiki/log.md")
        for relative_path in core_paths:
            if self.wiki is None and not (self.vault_root / relative_path).exists():
                issues.append(
                    WikiLintIssue(
                        severity="error",
                        code="wiki_core_file_missing",
                        message=f"缺少必需的 Karpathy LLM Wiki 核心文件：{relative_path}",
                        path=relative_path,
                    )
                )
        index_path = root / "index.md"
        if index_path.exists():
            index_text = index_path.read_text(encoding="utf-8")
            for page in pages:
                if page.relative_path in {"Wiki/AGENTS.md", "Wiki/index.md", "Wiki/log.md"}:
                    continue
                if f"[[{page.relative_path}]]" not in index_text:
                    issues.append(
                        WikiLintIssue(
                            severity="warning",
                            code="wiki_index_entry_missing",
                            message="Wiki 页面未写入 Wiki/index.md。",
                            path=page.relative_path,
                        )
                    )
        log_path = root / "log.md"
        if log_path.exists() and "## [" not in log_path.read_text(encoding="utf-8"):
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_log_entry_missing",
                    message="Wiki/log.md 暂无操作记录。",
                    path="Wiki/log.md",
                )
            )
        return issues

    def _index_issues(self, pages: list[_WikiPage]) -> list[WikiLintIssue]:
        rows = self.conn.execute(
            """
            SELECT relative_path, title, content_hash, status
            FROM notes
            WHERE vault_id = ?
            """,
            (self.vault_id,),
        ).fetchall()
        indexed = {
            str(row["relative_path"]): row
            for row in rows
            if not str(row["relative_path"]).startswith(f"{WIKI_ROOT}/Reports/")
        }
        page_paths = {page.relative_path for page in pages}
        issues: list[WikiLintIssue] = []
        for page in pages:
            row = indexed.get(page.relative_path)
            if row is None or str(row["status"]) == "deleted":
                issues.append(
                    WikiLintIssue(
                        severity="warning",
                        code="wiki_file_not_indexed",
                        message="Wiki 页面存在于磁盘，但未出现在当前活动索引中。",
                        path=page.relative_path,
                    )
                )
                continue
            if str(row["content_hash"]) != page.content_hash:
                issues.append(
                    WikiLintIssue(
                        severity="warning",
                        code="wiki_index_stale",
                        message="Wiki 页面哈希与索引中的哈希不一致。",
                        path=page.relative_path,
                    )
                )
        for relative_path, row in indexed.items():
            if relative_path.startswith(f"{WIKI_ROOT}/") and str(row["status"]) != "deleted" and relative_path not in page_paths:
                issues.append(
                    WikiLintIssue(
                        severity="warning",
                        code="wiki_index_missing_file",
                        message="活动索引记录指向了磁盘上已不存在的 Wiki 页面。",
                        path=relative_path,
                    )
                )
        return issues

    def _index_job_issues(self) -> list[WikiLintIssue]:
        rows = self.conn.execute(
            """
            SELECT id, status, error
            FROM index_jobs
            WHERE vault_id = ?
            ORDER BY created_at DESC
            LIMIT 5
            """,
            (self.vault_id,),
        ).fetchall()
        return [
            WikiLintIssue(
                severity="error",
                code="recent_index_job_failed",
                message=f"最近的索引任务失败：{row['error'] or row['id']}",
                target=str(row["id"]),
            )
            for row in rows
            if str(row["status"]) == "failed"
        ]

    def _vector_index_issues(self, pages: list[_WikiPage]) -> list[WikiLintIssue]:
        table_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'vector_chunks'"
        ).fetchone()
        if table_exists is None:
            return []
        rows = self.conn.execute(
            "SELECT DISTINCT relative_path FROM vector_chunks WHERE vault_id = ?",
            (self.vault_id,),
        ).fetchall()
        vector_paths = {str(row["relative_path"]) for row in rows}
        return [
            WikiLintIssue(
                severity="info",
                code="wiki_vector_missing",
                message="Wiki 页面已进入全文索引，但没有对应的向量镜像记录。",
                path=page.relative_path,
            )
            for page in pages
            if page.relative_path not in vector_paths
        ]

    def _graph_conflict_issues(self) -> list[WikiLintIssue]:
        table_exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'memory_graph_facts'"
        ).fetchone()
        if table_exists is None:
            return []
        rows = self.conn.execute(
            """
            SELECT id, subject, predicate, object, conflicts_with
            FROM memory_graph_facts
            WHERE status = 'quarantined' AND conflicts_with IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 20
            """
        ).fetchall()
        return [
            WikiLintIssue(
                severity="warning",
                code="graph_conflict_candidate",
                message=f"结构化记忆存在潜在冲突：{row['subject']} {row['predicate']} {row['object']}",
                target=str(row["id"]),
            )
            for row in rows
        ]

    def _write_report(
        self,
        generated_at: str,
        summary: dict[str, int],
        issues: list[WikiLintIssue],
        research_questions: list[WikiResearchQuestion],
        repair_proposals: list[WikiLintRepairProposal],
    ) -> WikiPageResponse:
        assert self.wiki is not None
        date = generated_at[:10]
        content = _report_markdown(generated_at, summary, issues, research_questions, repair_proposals)
        return self.wiki.write_page(
            WikiPageWriteRequest(
                title=f"Wiki Lint {date}",
                content=content,
                operation="replace_section",
                target_path=f"Wiki/Reports/Lint-{date}.md",
                section="Lint Report",
                tags=["wiki-lint"],
            )
        )


class WikiDiagnosticsQueueService(WikiLintService):
    def list_items(self) -> list[WikiDiagnosticsQueueItem]:
        return self.diagnostics_queue()


def _duplicate_title_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    by_title: dict[str, list[_WikiPage]] = {}
    for page in pages:
        by_title.setdefault(page.title.casefold(), []).append(page)
    issues = []
    for duplicates in by_title.values():
        if len(duplicates) < 2:
            continue
        paths = ", ".join(page.relative_path for page in duplicates)
        for page in duplicates:
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="duplicate_title",
                    message=f"多个 Wiki 页面使用相同标题“{page.title}”：{paths}",
                    path=page.relative_path,
                )
            )
    return issues


def _template_section_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    for page in _maintained_pages(pages):
        missing = [section for section in WIKI_PAGE_TEMPLATE_SECTIONS if not _has_heading(page.body, section)]
        if missing:
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_template_section_missing",
                    message="Wiki 页面缺少固定 8 章模板章节：" + ", ".join(missing),
                    path=page.relative_path,
                    target=", ".join(missing),
                )
            )
    return issues


def _evidence_source_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    for page in _maintained_pages(pages):
        sources = _frontmatter_list(page.frontmatter.get("sources"))
        has_source_section = _has_heading(page.body, "原文出处")
        has_obsidian_source = "[[Memories/" in page.body or "[[Wiki/Sources/" in page.body or any(
            source.startswith(("Memories/", "Wiki/Sources/", "message:")) for source in sources
        )
        if not sources or not has_source_section or not has_obsidian_source:
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_source_reference_missing",
                    message="Wiki 页面应在 frontmatter 和“原文出处”中标明证据、来源路径或触发消息。",
                    path=page.relative_path,
                )
            )
        if _is_automatic_page(page) and ("触发来源" not in page.body or "agent_run_id" not in page.body):
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_trigger_source_missing",
                    message="自动整理页面应记录触发来源、message id 和 agent_run_id。",
                    path=page.relative_path,
                )
            )
    return issues


def _version_log_issues(pages: list[_WikiPage], vault_root: Path) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    log_text = ""
    log_path = vault_root / WIKI_ROOT / "log.md"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
    for page in _maintained_pages(pages):
        if not page.frontmatter.get("revision"):
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_revision_missing",
                    message="Wiki 页面 frontmatter 应包含 revision，以便追踪版本演进。",
                    path=page.relative_path,
                )
            )
        if not _has_heading(page.body, "更新日志"):
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_page_update_log_missing",
                    message="Wiki 页面应包含内嵌更新日志。",
                    path=page.relative_path,
                )
            )
        if log_text and page.relative_path not in log_text:
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_central_log_missing",
                    message="Wiki/log.md 中没有找到该页面路径的集中日志记录。",
                    path=page.relative_path,
                )
            )
    return issues


def _inbound_link_count_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    for target in _maintained_pages(pages):
        count = 0
        aliases = {
            target.title.casefold(),
            Path(target.relative_path).stem.casefold(),
            target.relative_path.casefold(),
        }
        for page in pages:
            if page.relative_path == target.relative_path:
                continue
            for link in page.links:
                normalized = link.strip().replace("\\", "/").strip("/").casefold()
                if normalized in aliases:
                    count += 1
                    break
        if count < 3:
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_inbound_link_count_low",
                    message=f"Wiki 页面入链数量为 {count}，低于 3；应从相关页面补足双向链接。",
                    path=target.relative_path,
                    target=str(count),
                )
            )
    return issues


def _duplicate_entity_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    entity_pages = [page for page in pages if page.relative_path.startswith(f"{WIKI_ROOT}/Entities/")]
    by_key: dict[str, list[_WikiPage]] = {}
    for page in entity_pages:
        by_key.setdefault(_entity_key(page.title), []).append(page)
        aliases = page.frontmatter.get("aliases")
        if isinstance(aliases, list):
            alias_values = aliases
        elif isinstance(aliases, str):
            alias_values = aliases.split(",")
        else:
            alias_values = []
        for alias in alias_values:
            if alias.strip():
                by_key.setdefault(_entity_key(alias), []).append(page)
    issues: list[WikiLintIssue] = []
    seen: set[tuple[str, str]] = set()
    for key, candidates in by_key.items():
        unique = {page.relative_path: page for page in candidates}
        if len(unique) < 2:
            continue
        paths = sorted(unique)
        for path in paths:
            issue_key = (key, path)
            if issue_key in seen:
                continue
            seen.add(issue_key)
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="duplicate_entity_candidate",
                    message=f"Multiple entity pages appear to describe the same entity key `{key}`: {', '.join(paths)}",
                    path=path,
                    target=", ".join(candidate for candidate in paths if candidate != path),
                )
            )
    return issues


def _schema_frontmatter_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    typed_roots = {
        f"{WIKI_ROOT}/Sources/": "source",
        f"{WIKI_ROOT}/Entities/": "entity",
        f"{WIKI_ROOT}/Concepts/": "concept",
        f"{WIKI_ROOT}/Syntheses/": "synthesis",
        f"{WIKI_ROOT}/Companion/Summaries/": "synthesis",
        f"{WIKI_ROOT}/Comparisons/": "comparison",
    }
    for page in pages:
        if page.relative_path in {"Wiki/AGENTS.md", "Wiki/index.md", "Wiki/log.md"}:
            continue
        if page.relative_path.startswith(f"{WIKI_ROOT}/Reports/"):
            continue
        expected_type = "page"
        for prefix, page_type in typed_roots.items():
            if page.relative_path.startswith(prefix):
                expected_type = page_type
                break
        actual_type = page.frontmatter.get("type")
        title = page.frontmatter.get("title")
        if actual_type != expected_type or not title:
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_schema_frontmatter_missing",
                    message=f"Wiki {expected_type} 页面应包含 schema frontmatter，并填写匹配的类型和标题。",
                    path=page.relative_path,
                )
            )
    return issues


def _orphan_page_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    if len(pages) <= 1:
        return []
    linked_titles = {link.casefold() for page in pages for link in page.links}
    return [
        WikiLintIssue(
            severity="info",
            code="orphan_wiki_page",
            message="Wiki 页面未被其他 Wiki 页面引用。",
            path=page.relative_path,
        )
        for page in pages
        if page.title.casefold() not in linked_titles and "Reports/" not in page.relative_path
    ]


def _broken_link_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    existing_titles = {page.title.casefold() for page in pages}
    existing_slugs = {Path(page.relative_path).stem.casefold() for page in pages}
    existing_paths = {page.relative_path.casefold() for page in pages}
    issues = []
    for page in pages:
        for link in page.links:
            normalized = link.strip().replace("\\", "/").strip("/")
            if normalized.startswith("Memories/"):
                continue
            key = normalized.casefold()
            if key in existing_titles or key in existing_slugs or key in existing_paths:
                continue
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="missing_wiki_link",
                    message=f"Wiki 链接目标缺失：[[{link}]]",
                    path=page.relative_path,
                    target=link,
                )
            )
    return issues


def _contradiction_marker_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    markers = ("contradict", "contradiction", "conflict", "conflicts with", "disagrees with")
    issues: list[WikiLintIssue] = []
    for page in pages:
        text = page.body.casefold()
        if any(marker in text for marker in markers):
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_contradiction_marker",
                    message="Wiki 页面包含需要人工审查的矛盾或冲突标记。",
                    path=page.relative_path,
                )
            )
    return issues


def _stale_marker_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    markers = ("stale", "outdated", "superseded", "deprecated", "needs refresh", "needs update")
    issues: list[WikiLintIssue] = []
    for page in pages:
        text = page.body.casefold()
        if any(marker in text for marker in markers):
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_stale_marker",
                    message="Wiki 页面包含应刷新或确认的过时标记。",
                    path=page.relative_path,
                )
            )
    return issues


def _missing_concept_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    concept_titles = {
        page.title.casefold()
        for page in pages
        if page.relative_path.startswith(f"{WIKI_ROOT}/Concepts/")
    }
    concept_slugs = {
        Path(page.relative_path).stem.casefold()
        for page in pages
        if page.relative_path.startswith(f"{WIKI_ROOT}/Concepts/")
    }
    issues: list[WikiLintIssue] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        if page.relative_path.startswith(f"{WIKI_ROOT}/Concepts/"):
            continue
        for link in page.links:
            if link.casefold() in concept_titles or _slugify(link).casefold() in concept_slugs:
                continue
            if not _looks_like_concept_link(link):
                continue
            issue_key = (page.relative_path, link)
            if issue_key in seen:
                continue
            seen.add(issue_key)
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="missing_concept_page",
                    message=f"Wiki 引用了概念 `[[{link}]]`，但没有对应的 Wiki/Concepts 页面。",
                    path=page.relative_path,
                    target=link,
                )
            )
    return issues


def _format_trap_issues(pages: list[_WikiPage]) -> list[WikiLintIssue]:
    issues: list[WikiLintIssue] = []
    for page in _maintained_pages(pages):
        if not page.body.strip():
            issues.append(
                WikiLintIssue(
                    severity="warning",
                    code="wiki_empty_page",
                    message="Wiki 页面为空，可能是创建失败或重复创建留下的空文件。",
                    path=page.relative_path,
                )
            )
        for link in page.links:
            normalized = link.strip().replace("\\", "/").strip("/")
            if "/" in normalized and not normalized.startswith((f"{WIKI_ROOT}/", "Memories/")):
                issues.append(
                    WikiLintIssue(
                        severity="info",
                        code="wiki_link_path_outside_known_roots",
                        message=f"Wiki 链接路径不在 Wiki/ 或 Memories/ 内：[[{link}]]",
                        path=page.relative_path,
                        target=link,
                    )
                )
        if "TODO" in page.body or "待补" in page.body:
            issues.append(
                WikiLintIssue(
                    severity="info",
                    code="wiki_placeholder_left",
                    message="Wiki 页面仍有占位内容，需要补全或明确标记为待研究问题。",
                    path=page.relative_path,
                )
            )
    return issues


def _research_questions(issues: list[WikiLintIssue]) -> list[WikiResearchQuestion]:
    questions = []
    for issue in issues:
        if issue.code == "missing_wiki_link" and issue.target:
            questions.append(
                WikiResearchQuestion(
                    question=f"Wiki 应该如何描述“{issue.target}”？",
                    reason="missing_cross_link_target",
                    related_paths=[issue.path] if issue.path else [],
                )
            )
        elif issue.code == "graph_conflict_candidate":
            questions.append(
                WikiResearchQuestion(
                    question="哪个结构化记忆事实应被视为当前事实？",
                    reason="graph_conflict_candidate",
                    related_paths=[],
                )
            )
    deduped: dict[tuple[str, str], WikiResearchQuestion] = {}
    for question in questions:
        deduped[(question.question, question.reason)] = question
    return list(deduped.values())[:10]


def _repair_proposals(issues: list[WikiLintIssue], pages: list[_WikiPage]) -> list[WikiLintRepairProposal]:
    page_by_path = {page.relative_path: page for page in pages}
    proposals: list[WikiLintRepairProposal] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for issue in sorted(
        issues,
        key=lambda item: (_severity_rank(item.severity), item.code, item.path or "", item.target or ""),
    ):
        proposal = _repair_proposal(issue, page_by_path)
        if proposal is None:
            continue
        key = (proposal.issue_code, proposal.target_path, proposal.markdown_preview)
        if key in seen:
            continue
        seen.add(key)
        proposals.append(proposal)
    return proposals[:50]


def _repair_proposal(
    issue: WikiLintIssue,
    page_by_path: dict[str, _WikiPage],
) -> WikiLintRepairProposal | None:
    related_paths = [issue.path] if issue.path else []
    if issue.code in {"wiki_index_stale", "wiki_file_not_indexed", "wiki_vector_missing"}:
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Refresh Wiki index",
            target_path=issue.path,
            operation="reindex",
            reason=issue.message,
            markdown_preview=f"在信任搜索或向量镜像之前，为 `{issue.path}` 重建索引记录。",
            related_paths=related_paths,
        )
    if issue.code == "wiki_index_missing_file":
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Review missing indexed Wiki file",
            target_path=issue.path,
            operation="delete_index_record",
            reason=issue.message,
            markdown_preview=f"确认 `{issue.path}` 已被有意删除，然后移除或标记该过期索引条目。",
            related_paths=related_paths,
        )
    if issue.code in {"missing_wiki_link", "missing_concept_page"} and issue.target:
        target_path = f"{WIKI_ROOT}/Concepts/{_slugify(issue.target)}.md"
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title=f"Create concept page for {issue.target}",
            target_path=target_path,
            operation="create",
            reason=issue.message,
            markdown_preview=_concept_page_preview(issue.target, issue.path),
            related_paths=related_paths,
        )
    if issue.code == "orphan_wiki_page" and issue.path:
        page = page_by_path.get(issue.path)
        link_text = page.title if page else Path(issue.path).stem
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title=f"Link orphan page {link_text}",
            target_path=f"{WIKI_ROOT}/index.md",
            operation="append",
            reason=issue.message,
            markdown_preview=f"- [[{link_text}]] - 审查后将此页面添加到相关的索引部分。",
            related_paths=related_paths,
        )
    if issue.code in {"duplicate_title", "duplicate_entity_candidate"}:
        paths = [path.strip() for path in (issue.target or "").split(",") if path.strip()]
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Merge or disambiguate duplicate Wiki pages",
            target_path=issue.path,
            operation="review",
            reason=issue.message,
            markdown_preview="审查重复候选项并选择一个规范页面；在确认写入中添加重定向、别名或消歧标题。",
            related_paths=[path for path in [issue.path, *paths] if path],
        )
    if issue.code in {"wiki_contradiction_marker", "graph_conflict_candidate"}:
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Resolve contradiction candidate",
            target_path=issue.path,
            operation="review",
            reason=issue.message,
            markdown_preview="比较冲突声明，选取当前有引用依据的事实，仅在确认后撰写替换部分。",
            related_paths=related_paths,
        )
    if issue.code == "wiki_stale_marker":
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Refresh stale Wiki claim",
            target_path=issue.path,
            operation="replace_section",
            reason=issue.message,
            markdown_preview="撰写带有当前引用的更新部分；在替换文本被审查之前不要覆盖页面。",
            related_paths=related_paths,
        )
    if issue.code == "wiki_schema_frontmatter_missing" and issue.path:
        page_type = _expected_page_type(issue.path)
        page = page_by_path.get(issue.path)
        title = page.title if page else Path(issue.path).stem
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Add Wiki schema frontmatter",
            target_path=issue.path,
            operation="replace_section",
            reason=issue.message,
            markdown_preview=_frontmatter_preview(title, page_type),
            related_paths=related_paths,
        )
    if issue.code in {
        "wiki_template_section_missing",
        "wiki_source_reference_missing",
        "wiki_trigger_source_missing",
        "wiki_revision_missing",
        "wiki_page_update_log_missing",
        "wiki_central_log_missing",
        "wiki_inbound_link_count_low",
        "wiki_empty_page",
        "wiki_link_path_outside_known_roots",
        "wiki_placeholder_left",
    }:
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Complete Wiki page contract",
            target_path=issue.path,
            operation="replace_section",
            reason=issue.message,
            markdown_preview="补齐固定 8 章模板、原文出处、更新日志、自检清单、集中日志和必要入链；涉及覆盖内容时先走确认。",
            related_paths=related_paths,
        )
    if issue.code in {"wiki_index_entry_missing", "wiki_core_file_missing", "wiki_log_entry_missing"}:
        return WikiLintRepairProposal(
            issue_code=issue.code,
            title="Repair Wiki core metadata",
            target_path=issue.path,
            operation="append" if issue.code != "wiki_core_file_missing" else "create",
            reason=issue.message,
            markdown_preview=f"通过 Wiki 服务修复 `{issue.path}`，使索引和日志规范保持一致。",
            related_paths=related_paths,
        )
    return None


_QUEUE_DIAGNOSTIC_TYPES = {
    "wiki_contradiction_marker": "contradiction",
    "wiki_stale_marker": "stale_claim",
    "missing_wiki_link": "missing_link",
    "missing_concept_page": "missing_concept",
}


_QUEUE_TITLES = {
    "contradiction": "审查矛盾候选项",
    "stale_claim": "刷新过时声明",
    "missing_link": "解决缺失的 Wiki 链接",
    "missing_concept": "起草缺失的概念页面",
}


_QUEUE_TYPE_RANK = {
    "contradiction": 0,
    "stale_claim": 1,
    "missing_link": 2,
    "missing_concept": 3,
}


def _diagnostics_queue_items(
    issues: list[WikiLintIssue],
    pages: list[_WikiPage],
) -> list[WikiDiagnosticsQueueItem]:
    page_by_path = {page.relative_path: page for page in pages}
    items: list[WikiDiagnosticsQueueItem] = []
    seen: set[tuple[str, str, str, str]] = set()
    for issue in sorted(
        issues,
        key=lambda item: (
            _QUEUE_TYPE_RANK.get(_QUEUE_DIAGNOSTIC_TYPES.get(item.code, ""), 99),
            item.path or "",
            item.target or "",
            item.code,
        ),
    ):
        diagnostic_type = _QUEUE_DIAGNOSTIC_TYPES.get(issue.code)
        if diagnostic_type is None:
            continue
        key = (diagnostic_type, issue.code, issue.path or "", issue.target or "")
        if key in seen:
            continue
        seen.add(key)
        items.append(
            WikiDiagnosticsQueueItem(
                diagnostic_type=diagnostic_type,
                severity=issue.severity,
                issue_code=issue.code,
                title=_QUEUE_TITLES[diagnostic_type],
                message=issue.message,
                path=issue.path,
                target=issue.target,
                repair_preview=_repair_proposal(issue, page_by_path),
            )
        )
    return items


def _summary(
    pages: list[_WikiPage],
    issues: list[WikiLintIssue],
    research_questions: list[WikiResearchQuestion],
    repair_proposals: list[WikiLintRepairProposal],
) -> dict[str, int]:
    return {
        "pages": len(pages),
        "issues": len(issues),
        "errors": sum(1 for issue in issues if issue.severity == "error"),
        "warnings": sum(1 for issue in issues if issue.severity == "warning"),
        "info": sum(1 for issue in issues if issue.severity == "info"),
        "research_questions": len(research_questions),
        "repair_proposals": len(repair_proposals),
    }


def _maintained_pages(pages: list[_WikiPage]) -> list[_WikiPage]:
    excluded = {f"{WIKI_ROOT}/AGENTS.md", f"{WIKI_ROOT}/index.md", f"{WIKI_ROOT}/log.md"}
    return [
        page
        for page in pages
        if page.relative_path not in excluded and not page.relative_path.startswith(f"{WIKI_ROOT}/Reports/")
    ]


def _has_heading(body: str, heading: str) -> bool:
    pattern = re.compile(rf"^##+\s+{re.escape(heading)}\s*$", re.MULTILINE)
    return bool(pattern.search(body))


def _frontmatter_list(value: str | list[str] | object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _is_automatic_page(page: _WikiPage) -> bool:
    tags = _frontmatter_list(page.frontmatter.get("tags"))
    text = " ".join([page.relative_path, page.body, *tags]).casefold()
    return "auto-wiki" in text or "companion/summaries" in text or "query-archive" in text


def _report_markdown(
    generated_at: str,
    summary: dict[str, int],
    issues: list[WikiLintIssue],
    research_questions: list[WikiResearchQuestion],
    repair_proposals: list[WikiLintRepairProposal],
) -> str:
    lines = [
        "## 检查报告",
        "",
        f"- 生成时间：`{generated_at}`",
        f"- 页面数：{summary.get('pages', 0)}",
        f"- 问题数：{summary.get('issues', 0)}",
        f"- 待研究问题：{summary.get('research_questions', 0)}",
        "",
        "### 问题",
        "",
    ]
    if issues:
        for issue in issues:
            location = f" `{issue.path}`" if issue.path else ""
            target = f" -> `{issue.target}`" if issue.target else ""
            lines.append(f"- **{issue.code}** ({issue.severity}){location}{target}: {issue.message}")
    else:
        lines.append("- 未发现确定性的 Wiki 健康问题。")
    lines.extend(["", "### 待研究问题", ""])
    if research_questions:
        for question in research_questions:
            lines.append(f"- {question.question} ({question.reason})")
    else:
        lines.append("- 未生成待研究问题。")
    lines.extend(["", "### 修复建议", ""])
    if repair_proposals:
        for proposal in repair_proposals:
            target = f" `{proposal.target_path}`" if proposal.target_path else ""
            lines.append(f"- **{proposal.issue_code}** ({proposal.operation}){target}: {proposal.title}")
    else:
        lines.append("- 未生成非写入修复建议。")
    return "\n".join(lines)


def _concept_page_preview(title: str, source_path: str | None) -> str:
    source = f"\n\n## Related\n\n- Source: `{source_path}`" if source_path else ""
    return "\n".join(
        [
            "---",
            f"title: {title}",
            "type: concept",
            "tags: [wiki-concept]",
            "---",
            "",
            f"# {title}",
            "",
            "## Summary",
            "",
            "在应用此建议之前，撰写带有引用的简洁定义。",
            source,
        ]
    ).strip()


def _frontmatter_preview(title: str, page_type: str) -> str:
    return "\n".join(
        [
            "---",
            f"title: {title}",
            f"type: {page_type}",
            "tags: []",
            "---",
        ]
    )


def _expected_page_type(relative_path: str) -> str:
    typed_roots = {
        f"{WIKI_ROOT}/Sources/": "source",
        f"{WIKI_ROOT}/Entities/": "entity",
        f"{WIKI_ROOT}/Concepts/": "concept",
        f"{WIKI_ROOT}/Syntheses/": "synthesis",
        f"{WIKI_ROOT}/Comparisons/": "comparison",
    }
    for prefix, page_type in typed_roots.items():
        if relative_path.startswith(prefix):
            return page_type
    return "page"


def _looks_like_concept_link(link: str) -> bool:
    text = link.strip()
    if not text:
        return False
    lower = text.casefold()
    if lower.startswith(("wiki/", "http://", "https://")):
        return False
    if "/" in text:
        return False
    return any(char.isspace() for char in text) or "-" in text or "_" in text


def _entity_key(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _slugify(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.strip():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "Untitled"


def _severity_rank(severity: str) -> int:
    return {"error": 0, "warning": 1, "info": 2}.get(severity, 3)
