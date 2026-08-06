from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.retrospectives import (
    RetrospectiveDiarySummary,
    RetrospectiveMemoryItem,
    RetrospectivePreference,
    RetrospectiveReportPeriod,
    RetrospectiveReportResponse,
    RetrospectiveSourceReference,
    RetrospectiveTaskStats,
    RetrospectiveTopic,
    RetrospectiveWindow,
)
from app.storage.database import open_database_connection
from app.models.wiki import WikiPageResponse
from app.services.agent_actions import AgentActionCreate, AgentActionService, markdown_snapshot
from app.services.memory import SafeMarkdownWriter
from app.utils.hash import sha256_hex
from app.utils.time import utc_now_iso


RETROSPECTIVE_WINDOWS = (1, 7, 30, 90)
REPORT_ROOT = "Wiki/Companion/Reports"


class RetrospectiveService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        vault_id: str,
        writer: SafeMarkdownWriter | None = None,
        agent_actions: AgentActionService | None = None,
        index_refresh=None,
        now_provider=None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.vault_id = vault_id
        self.writer = writer
        self.agent_actions = agent_actions
        self.index_refresh = index_refresh
        self.now_provider = now_provider or utc_now_iso

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def build_windows(self) -> list[RetrospectiveWindow]:
        end_at = self._now()
        return [self.build_window(days, end_at=end_at) for days in RETROSPECTIVE_WINDOWS]

    def build_window(self, days: int, *, end_at: datetime | None = None) -> RetrospectiveWindow:
        safe_days = _normalize_days(days)
        end = end_at or self._now()
        start = end - timedelta(days=safe_days)
        start_iso = _iso(start)
        end_iso = _iso(end)

        diary_rows = self._diary_rows(start_iso, end_iso)
        memory_rows = self._memory_rows(start_iso, end_iso)
        task_rows = self._task_rows(start_iso, end_iso)
        wiki_rows = self._wiki_action_rows(start_iso, end_iso)

        topics = _topics_from_diary(diary_rows)
        preferences = _preferences_from_rows(diary_rows, memory_rows)
        task_stats = _task_stats(task_rows, now_iso=end_iso)
        diary_summaries = [_diary_summary(row) for row in diary_rows[:8]]
        long_term = [_memory_item(row) for row in memory_rows[:8]]
        wiki_updates = [_wiki_item(row) for row in wiki_rows[:8]]
        summary = {
            "diary_objects": len(diary_rows),
            "long_term_memories": len(memory_rows),
            "tasks": len(task_rows),
            "wiki_updates": len(wiki_rows),
            "topics": len(topics),
            "repeated_preferences": len(preferences),
        }
        return RetrospectiveWindow(
            days=safe_days,
            label=_window_label(safe_days),
            start_at=start_iso,
            end_at=end_iso,
            summary=summary,
            topics=topics,
            diary_summaries=diary_summaries,
            long_term_memories=long_term,
            tasks=task_stats,
            wiki_updates=wiki_updates,
            repeated_preferences=preferences,
            has_data=any(summary.values()),
        )

    def write_report(self, days: int):
        return self._write_report(self.build_window(days), report_kind="retrospective")

    def write_period_report(self, period: RetrospectiveReportPeriod):
        report_period = _normalize_report_period(period)
        days = 7 if report_period == "weekly" else 30
        label = "周报" if report_period == "weekly" else "月报"
        window = self.build_window(days).model_copy(update={"label": label})
        return self._write_report(window, report_kind=report_period)

    def _write_report(self, window: RetrospectiveWindow, *, report_kind: str):
        if self.writer is None or self.agent_actions is None:
            raise RuntimeError("retrospective_report_requires_vault")
        markdown = retrospective_report_markdown(window, report_kind=report_kind)
        target_path = _report_path(window, report_kind=report_kind)
        before = markdown_snapshot(self.writer, [target_path])
        self.writer.write(target_path, markdown)
        index_job_id = self.index_refresh(target_path) if self.index_refresh is not None else None
        after = markdown_snapshot(self.writer, [target_path])
        action_type = f"wiki.{report_kind}_report.write"
        if report_kind == "retrospective":
            action_type = "wiki.retrospective_report.write"
        action = self.agent_actions.record(
            AgentActionCreate(
                action_type=action_type,
                title=f"已生成 {window.label} Markdown 报告",
                summary=f"本地 {window.label} 报告写入 {target_path}",
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(target_path,),
                before_snapshot=before,
                after_snapshot=after,
                metadata={
                    "days": window.days,
                    "report_kind": report_kind,
                    "source_counts": window.summary,
                    "source_paths": _source_paths(window),
                },
                reversible=True,
                completed_at=utc_now_iso(),
            )
        )
        return RetrospectiveReportResponse(
            page=WikiPageResponse(
                title=_report_title(window, report_kind=report_kind),
                relative_path=target_path,
                operation="replace",
                status="updated" if before.get("exists", {}).get(target_path) else "created",
                index_job_id=index_job_id,
                action_id=action.action_id,
            ),
            action=action,
            markdown=markdown,
        )

    def _now(self) -> datetime:
        value = self.now_provider()
        if isinstance(value, datetime):
            current = value
        else:
            current = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc)

    def _diary_rows(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT o.*, s.markdown_path, s.agent_run_id
            FROM diary_memory_objects o
            LEFT JOIN diary_memory_object_sources s ON s.object_id = o.id
            WHERE o.vault_id = ?
              AND julianday(o.occurred_at) >= julianday(?)
              AND julianday(o.occurred_at) <= julianday(?)
              AND o.status IN ('active', 'candidate')
            ORDER BY o.importance DESC, o.confidence DESC, o.occurred_at DESC
            LIMIT 200
            """,
            (self.vault_id, start_iso, end_iso),
        ).fetchall()

    def _memory_rows(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT *
            FROM memory_graph_facts
            WHERE julianday(created_at) >= julianday(?)
              AND julianday(created_at) <= julianday(?)
              AND status IN ('active', 'candidate')
            ORDER BY importance DESC, confidence DESC, created_at DESC
            LIMIT 100
            """,
            (start_iso, end_iso),
        ).fetchall()

    def _task_rows(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT t.*, r.remind_at_utc, r.status AS reminder_status
            FROM tasks t
            LEFT JOIN reminders r ON r.task_id = t.id
            WHERE julianday(COALESCE(t.updated_at, t.created_at)) >= julianday(?)
              AND julianday(COALESCE(t.updated_at, t.created_at)) <= julianday(?)
            ORDER BY COALESCE(t.due_at_utc, t.updated_at, t.created_at) DESC
            LIMIT 200
            """,
            (start_iso, end_iso),
        ).fetchall()

    def _wiki_action_rows(self, start_iso: str, end_iso: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT *
            FROM agent_actions
            WHERE julianday(created_at) >= julianday(?)
              AND julianday(created_at) <= julianday(?)
              AND action_type LIKE 'wiki.%'
              AND status IN ('completed', 'reverted')
            ORDER BY created_at DESC
            LIMIT 100
            """,
            (start_iso, end_iso),
        ).fetchall()


def retrospective_report_markdown(window: RetrospectiveWindow, *, report_kind: str = "retrospective") -> str:
    report_title = _report_title(window, report_kind=report_kind)
    lines = [
        "---",
        f"title: {report_title}",
        f"type: {_report_frontmatter_type(report_kind)}",
        f"report_kind: {report_kind}",
        f"window_days: {window.days}",
        f"generated_at: {window.end_at}",
        f"updated_at: {window.end_at}",
        "---",
        "",
        f"# {report_title}",
        "",
        f"- 更新时间：{window.end_at}",
        f"- 时间窗口：{window.start_at} 至 {window.end_at}",
        f"- 结构化日记：{window.summary.get('diary_objects', 0)}",
        f"- 长期记忆：{window.summary.get('long_term_memories', 0)}",
        f"- 任务：{window.tasks.total}（完成 {window.tasks.completed}，未完成 {window.tasks.pending}）",
        f"- Wiki 更新：{window.summary.get('wiki_updates', 0)}",
        "",
        f"## {_period_prefix(report_kind)}主要主题",
    ]
    if window.topics:
        for topic in window.topics:
            lines.append(f"- {topic.name}：{topic.count} 次；来源：{_markdown_sources(topic.sources)}")
    else:
        lines.append("- 暂无可聚合主题。")
    lines.extend(["", "## 重要对话和日记摘要"])
    if window.diary_summaries:
        for item in window.diary_summaries:
            topic = f"（{item.topic}）" if item.topic else ""
            source = f"；来源：`{item.source_path}`" if item.source_path else "；来源：diary_memory:" + item.id
            lines.append(f"- {item.summary}{topic}{source}；时间：{item.occurred_at}")
    else:
        lines.append("- 暂无重要对话或结构化日记摘要。")
    lines.extend(["", "## 新增长期记忆"])
    if window.long_term_memories:
        for item in window.long_term_memories:
            source = f"；来源：{item.source_path}" if item.source_path else ""
            lines.append(f"- {item.summary}（{item.category} / {item.status} / {item.confidence:.2f}{source}）")
    else:
        lines.append("- 暂无新增长期记忆。")
    lines.extend(["", "## 任务完成与延迟"])
    if window.tasks.total:
        lines.append(
            f"- 共 {window.tasks.total} 个任务；完成 {window.tasks.completed}，未完成 {window.tasks.pending}，"
            f"取消 {window.tasks.cancelled}，逾期 {window.tasks.overdue}。"
        )
        lines.append(f"- 来源：{_markdown_sources(window.tasks.sources)}")
    else:
        lines.append("- 暂无任务变化。")
    lines.extend(["", "## 新增知识页"])
    if window.wiki_updates:
        for item in window.wiki_updates:
            lines.append(f"- {item.title}：`{item.path}`（{item.action_type}）")
    else:
        lines.append("- 暂无 Wiki 更新。")
    lines.extend(["", "## 反复出现的偏好或关注点"])
    if window.repeated_preferences:
        for pref in window.repeated_preferences:
            lines.append(f"- {pref.name}：{pref.count} 次；来源：{_markdown_sources(pref.sources)}")
    else:
        lines.append("- 暂无重复出现的偏好或关注点。")
    lines.extend(["", "## 值得回顾的问题"])
    for question in _review_questions(window):
        lines.append(f"- {question}")
    lines.extend(
        [
            "",
            "## 来源路径",
            *_source_path_lines(window),
            "",
            "## 来源说明",
            "本报告只使用本地 SQLite 与 Vault 中已有的可追踪记录，不调用外部模型，不做无来源推断。",
            "",
        ]
    )
    return "\n".join(lines)


def _report_title(window: RetrospectiveWindow, *, report_kind: str) -> str:
    if report_kind == "weekly":
        return f"{window.end_at[:10]} 周报"
    if report_kind == "monthly":
        return f"{window.end_at[:7]} 月报"
    return f"{window.label} 长期回顾"


def _report_frontmatter_type(report_kind: str) -> str:
    if report_kind == "weekly":
        return "weekly_report"
    if report_kind == "monthly":
        return "monthly_report"
    return "retrospective_report"


def _period_prefix(report_kind: str) -> str:
    if report_kind == "weekly":
        return "本周"
    if report_kind == "monthly":
        return "本月"
    return ""


def _normalize_report_period(period: str) -> RetrospectiveReportPeriod:
    if period not in {"weekly", "monthly"}:
        raise ValueError("unsupported_retrospective_report_period")
    return period  # type: ignore[return-value]


def _normalize_days(days: int) -> int:
    if days in RETROSPECTIVE_WINDOWS:
        return days
    if days <= 7:
        return 7
    if days <= 30:
        return 30
    return 90


def _window_label(days: int) -> str:
    if days == 1:
        return "Today"
    return f"{days}-day"


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _source(kind: str, id_value: str, label: str, *, path: str | None = None, created_at: str | None = None):
    return RetrospectiveSourceReference(kind=kind, id=id_value, label=label, path=path, created_at=created_at)


def _topics_from_diary(rows: list[sqlite3.Row]) -> list[RetrospectiveTopic]:
    counts: Counter[str] = Counter()
    sources: dict[str, list[RetrospectiveSourceReference]] = defaultdict(list)
    for row in rows:
        terms = []
        if row["topic"]:
            terms.append(str(row["topic"]))
        terms.extend(_json_list(row["keywords_json"])[:4])
        for raw in terms:
            term = _clean_term(raw)
            if not term:
                continue
            counts[term] += 1
            if len(sources[term]) < 3:
                sources[term].append(
                    _source(
                        "diary_memory",
                        str(row["id"]),
                        str(row["summary"])[:80],
                        path=row["markdown_path"],
                        created_at=row["occurred_at"],
                    )
                )
    return [
        RetrospectiveTopic(name=name, count=count, sources=sources[name])
        for name, count in counts.most_common(8)
    ]


def _preferences_from_rows(diary_rows: list[sqlite3.Row], memory_rows: list[sqlite3.Row]) -> list[RetrospectivePreference]:
    counts: Counter[str] = Counter()
    sources: dict[str, list[RetrospectiveSourceReference]] = defaultdict(list)
    preference_markers = ("preference", "goal", "habit", "concern", "focus", "偏好", "目标", "习惯", "关注")
    for row in memory_rows:
        category = str(row["category"] or "")
        memory_type = str(row["memory_type"] or "")
        if any(marker in f"{category} {memory_type}".casefold() for marker in preference_markers):
            name = _clean_term(str(row["subject"] or row["object"]))
            if name:
                counts[name] += int(row["support_count"] or 1)
                sources[name].append(
                    _source("long_term_memory", str(row["id"]), str(row["object"])[:80], created_at=row["created_at"])
                )
    for row in diary_rows:
        for term in _json_list(row["keywords_json"]):
            name = _clean_term(term)
            if not name:
                continue
            counts[name] += 1
            if len(sources[name]) < 3:
                sources[name].append(
                    _source(
                        "diary_memory",
                        str(row["id"]),
                        str(row["summary"])[:80],
                        path=row["markdown_path"],
                        created_at=row["occurred_at"],
                    )
                )
    return [
        RetrospectivePreference(name=name, count=count, sources=sources[name][:3])
        for name, count in counts.most_common(8)
        if count >= 2
    ]


def _diary_summary(row: sqlite3.Row) -> RetrospectiveDiarySummary:
    return RetrospectiveDiarySummary(
        id=str(row["id"]),
        summary=str(row["summary"]),
        topic=str(row["topic"]) if row["topic"] else None,
        source_path=str(row["markdown_path"]) if row["markdown_path"] else None,
        occurred_at=str(row["occurred_at"]),
    )


def _task_stats(rows: list[sqlite3.Row], *, now_iso: str) -> RetrospectiveTaskStats:
    stats = RetrospectiveTaskStats(total=len(rows))
    sources: list[RetrospectiveSourceReference] = []
    for row in rows:
        status = str(row["status"])
        if status == "done":
            stats.completed += 1
        elif status == "cancelled":
            stats.cancelled += 1
        else:
            stats.pending += 1
        due_at = row["due_at_utc"]
        if status not in {"done", "cancelled"} and due_at and str(due_at) < now_iso:
            stats.overdue += 1
        if len(sources) < 5:
            sources.append(_source("task", str(row["id"]), str(row["title"]), created_at=row["created_at"]))
    stats.sources = sources
    return stats


def _memory_item(row: sqlite3.Row) -> RetrospectiveMemoryItem:
    source_path = None
    metadata = _json_dict(row["metadata_json"])
    if isinstance(metadata.get("target_path"), str):
        source_path = str(metadata["target_path"])
    summary = f"{row['subject']} {row['predicate']} {row['object']}"
    return RetrospectiveMemoryItem(
        id=str(row["id"]),
        summary=summary,
        category=str(row["category"]),
        status=str(row["status"]),
        confidence=float(row["confidence"] or 0),
        source_path=source_path,
        created_at=str(row["created_at"]),
    )


def _wiki_item(row: sqlite3.Row) -> dict:
    target_paths = _json_list(row["target_paths_json"])
    path = target_paths[0] if target_paths else ""
    return {
        "path": path,
        "title": str(row["title"]),
        "action_type": str(row["action_type"]),
        "created_at": str(row["created_at"]),
        "action_id": str(row["id"]),
    }


def _json_dict(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _clean_term(value: str) -> str:
    text = " ".join(value.strip().split())
    text = re.sub(r"[`*_#\[\]{}()<>]", "", text)
    return text[:48]


def _report_path(window: RetrospectiveWindow, *, report_kind: str = "retrospective") -> str:
    stamp = window.end_at[:10]
    digest = sha256_hex(f"{report_kind}:{window.days}:{window.start_at}:{window.end_at}")[:8]
    if report_kind in {"weekly", "monthly"}:
        return f"{REPORT_ROOT}/{stamp}-{report_kind}-{digest}.md"
    return f"{REPORT_ROOT}/{stamp}-{window.days}d-{digest}.md"


def _source_paths(window: RetrospectiveWindow) -> list[str]:
    paths: list[str] = []
    for topic in window.topics:
        paths.extend(source.path for source in topic.sources if source.path)
    paths.extend(item.source_path for item in window.diary_summaries if item.source_path)
    paths.extend(item.source_path for item in window.long_term_memories if item.source_path)
    paths.extend(item.path for item in window.wiki_updates if item.path)
    return list(dict.fromkeys(paths))


def _source_path_lines(window: RetrospectiveWindow) -> list[str]:
    paths = _source_paths(window)
    if not paths:
        return ["- 暂无可写入报告的 Vault 相对路径；本报告仍保留 SQLite 记录 ID 作为来源。"]
    return [f"- `{path}`" for path in paths]


def _review_questions(window: RetrospectiveWindow) -> list[str]:
    questions: list[str] = []
    if window.tasks.overdue:
        questions.append(f"哪些逾期任务需要重新安排？来源：{_markdown_sources(window.tasks.sources)}")
    if window.topics:
        topic = window.topics[0]
        questions.append(f"围绕「{topic.name}」是否需要沉淀为新的 Wiki 页面或任务？来源：{_markdown_sources(topic.sources)}")
    if window.wiki_updates:
        path = window.wiki_updates[0].path or "agent_action"
        questions.append(f"新增知识页是否需要补充证据、自检或反向链接？来源：`{path}`")
    if window.repeated_preferences:
        pref = window.repeated_preferences[0]
        questions.append(f"反复出现的「{pref.name}」是否代表稳定偏好或长期目标？来源：{_markdown_sources(pref.sources)}")
    if not questions:
        questions.append("本窗口数据较少，下一次回顾时优先确认是否有新的日记、任务或 Wiki 页面值得纳入。")
    return questions[:5]


def _markdown_sources(sources: list[RetrospectiveSourceReference]) -> str:
    if not sources:
        return "无"
    labels = []
    for source in sources[:3]:
        if source.path:
            labels.append(f"`{source.path}`")
        else:
            labels.append(f"{source.kind}:{source.id}")
    return "；".join(labels)
