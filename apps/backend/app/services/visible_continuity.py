from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.models.visible_continuity import (
    VisibleContinuityPlaybackPreview,
    VisibleContinuityProjectCard,
    VisibleContinuityReceipt,
    VisibleContinuitySnapshotResponse,
    VisibleContinuityTodayCard,
)
from app.services.retrospectives import RetrospectiveService
from app.storage.database import open_database_connection
from app.utils.time import utc_now_iso


EMPTY_TODAY_TITLE = "今天随时可以开始"
EMPTY_TODAY_SUMMARY = "暂时还没有最近的本地活动。先聊一句、记一条笔记或建一个任务，我会把整理结果放在这里。"
EMPTY_PLAYBACK_TITLE = "周回放正在积累素材"
EMPTY_PLAYBACK_SUMMARY = "本地历史还不够多，暂时无法生成有用的周回放。"
DEFAULT_NEXT_STEP = "先继续一个具体的下一步。"
MAX_SAFE_TEXT_CHARS = 220
ACTIVE_PROJECT_STATUSES = {"active", "pending", "open", "in_progress", "todo"}
COMPLETED_PROJECT_STATUSES = {"done", "completed", "archived"}
BLOCKED_PROJECT_STATUSES = {"blocked", "paused"}
TERMINAL_PROJECT_STATUSES = {"cancelled", "canceled", "rejected", "forgotten", "superseded"}
COMPLETION_HINTS = ("completed", "finished", "shipped", "done", "wrapped up", "closed", "归档", "完成")
SECRET_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bAuthorization:\s*Bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\b(?:sk|pk|rk|ghp|gho|ghu|github_pat|xox[baprs]|AKIA)[A-Za-z0-9_\-]{8,}\b", re.IGNORECASE),
    re.compile(r"(?i)\b(?:password|passwd|pwd|secret|token|api[_ -]?key)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.IGNORECASE | re.DOTALL),
)


@dataclass(frozen=True, slots=True)
class VisibleContinuityOptions:
    receipt_limit: int = 8
    project_limit: int = 5
    now_iso: str | None = None


class VisibleContinuityService:
    def __init__(
        self,
        db: str | Path | sqlite3.Connection,
        *,
        vault_id: str | None = None,
        options: VisibleContinuityOptions | None = None,
    ) -> None:
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = open_database_connection(db)
        self.conn.row_factory = sqlite3.Row
        self.vault_id = vault_id
        self.options = options or VisibleContinuityOptions()

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def snapshot(self) -> VisibleContinuitySnapshotResponse:
        messages = self._recent_messages(limit=12)
        threads = self._unfinished_threads(limit=8)
        tasks = self._active_tasks(limit=12)
        diary = self._recent_diary_objects(limit=12)
        reports = self._recent_companion_reports(limit=8)
        receipts = self._recent_receipts(limit=self.options.receipt_limit)
        projects = self._project_cards(limit=self.options.project_limit)
        playback = self._playback_preview()
        today = self._today_card(
            messages=messages,
            threads=threads,
            tasks=tasks,
            diary=diary,
            reports=reports,
            receipts=receipts,
            projects=projects,
        )
        return VisibleContinuitySnapshotResponse(
            today_card=today,
            recent_receipts=receipts,
            project_cards=projects,
            playback_preview=playback,
        )

    def _today_card(
        self,
        *,
        messages: list[sqlite3.Row],
        threads: list[sqlite3.Row],
        tasks: list[sqlite3.Row],
        diary: list[sqlite3.Row],
        reports: list[sqlite3.Row],
        receipts: list[VisibleContinuityReceipt],
        projects: list[VisibleContinuityProjectCard],
    ) -> VisibleContinuityTodayCard:
        sources = len(messages) + len(threads) + len(tasks) + len(diary) + len(reports) + len(receipts) + len(projects)
        updated_at = _max_time(
            [row["updated_at"] for row in messages if _has_column(row, "updated_at")]
            + [row["updated_at"] for row in threads if _has_column(row, "updated_at")]
            + [row["updated_at"] for row in tasks if _has_column(row, "updated_at")]
            + [row["updated_at"] for row in diary if _has_column(row, "updated_at")]
            + [row["created_at"] for row in reports if _has_column(row, "created_at")]
            + [receipt.created_at for receipt in receipts]
            + [project.last_touched_at for project in projects if project.last_touched_at]
        )
        if sources == 0:
            return VisibleContinuityTodayCard(
                title=EMPTY_TODAY_TITLE,
                summary=EMPTY_TODAY_SUMMARY,
                carry_over_items=[],
                suggested_next_steps=["先开始一段聊天，或记录一条笔记。"],
                continuation_prompts=["帮我判断今天值得继续推进什么。"],
                source_count=0,
                updated_at=self._now_iso(),
            )

        carry_over: list[str] = []
        for task in tasks[:3]:
            carry_over.append(f"任务：{_safe_text(str(task['title']))}")
        for project in projects[:2]:
            carry_over.append(f"{project.title}: {project.current_state}")
        for item in diary[:2]:
            carry_over.append(_safe_text(str(item["summary"])))
        for thread in threads[:2]:
            carry_over.append(f"对话线索：{_safe_text(str(thread['title'] or thread['id']))}")
        if not carry_over and messages:
            carry_over.append(_safe_text(str(messages[0]["content"])))

        next_steps = []
        if tasks:
            next_steps.append(f"继续处理：{_safe_text(str(tasks[0]['title']))}。")
        if projects:
            next_steps.append(projects[0].next_step)
        if threads:
            next_steps.append(f"继续这条对话线索：{_safe_text(str(threads[0]['title'] or threads[0]['id']))}。")
        if receipts:
            next_steps.append("如果想撤销内容，可以先检查最近的整理记录。")
        if not next_steps:
            next_steps.append(DEFAULT_NEXT_STEP)
        prompts = _continuation_prompts(tasks=tasks, threads=threads, projects=projects, diary=diary, receipts=receipts)

        return VisibleContinuityTodayCard(
            title=_today_title(tasks=tasks, threads=threads, projects=projects),
            summary=_safe_text(_today_summary(tasks=tasks, threads=threads, projects=projects, diary=diary, receipts=receipts)),
            carry_over_items=_dedupe(carry_over)[:5],
            suggested_next_steps=_dedupe(next_steps)[:4],
            continuation_prompts=prompts,
            source_count=sources,
            updated_at=updated_at or self._now_iso(),
        )

    def _recent_receipts(self, *, limit: int) -> list[VisibleContinuityReceipt]:
        if not _table_exists(self.conn, "agent_actions"):
            return []
        rows = self.conn.execute(
            """
            SELECT id, action_type, risk_tier, decision, status, title, summary,
                   target_paths_json, reversible, reverted_by, reverts_action_id,
                   metadata_json, created_at
            FROM agent_actions
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
        receipts: list[VisibleContinuityReceipt] = []
        for row in rows:
            target_paths = _json_list(row["target_paths_json"])
            target_path = _safe_target_path(target_paths[0]) if target_paths else None
            summary = str(row["summary"] or "")
            if not summary:
                metadata = _json_dict(row["metadata_json"])
                summary = str(metadata.get("skipped_reason") or row["status"] or "")
            receipts.append(
                VisibleContinuityReceipt(
                    action_id=str(row["id"]),
                    action_type=str(row["action_type"]),
                    title=_safe_text(str(row["title"] or row["action_type"])),
                    summary=_safe_text(summary or "已记录本地整理活动。"),
                    decision=str(row["decision"]),  # type: ignore[arg-type]
                    risk_tier=str(row["risk_tier"]),  # type: ignore[arg-type]
                    status=str(row["status"] or "completed"),
                    reversible=bool(row["reversible"]),
                    reverted_by=_safe_optional_text(row["reverted_by"], limit=80),
                    reverts_action_id=_safe_optional_text(row["reverts_action_id"], limit=80),
                    target_path=target_path,
                    created_at=str(row["created_at"]),
                )
            )
        return receipts

    def _project_cards(self, *, limit: int) -> list[VisibleContinuityProjectCard]:
        buckets: dict[str, dict[str, object]] = defaultdict(_new_project_bucket)
        self._add_project_memory_buckets(buckets)
        self._add_project_task_buckets(buckets)
        self._add_project_diary_buckets(buckets)
        self._add_project_message_buckets(buckets)
        cards = [
            _project_card_from_bucket(project_id, bucket)
            for project_id, bucket in buckets.items()
            if _bucket_has_enough_signal(bucket)
        ]
        cards.sort(key=lambda card: card.last_touched_at or "", reverse=True)
        return cards[: max(1, min(limit, 20))]

    def _playback_preview(self) -> VisibleContinuityPlaybackPreview:
        if not self.vault_id:
            return VisibleContinuityPlaybackPreview(
                period="weekly",
                title=EMPTY_PLAYBACK_TITLE,
                summary=EMPTY_PLAYBACK_SUMMARY,
                themes=[],
                completed=[],
                stuck_points=[],
                next_focus=["绑定本地保存位置后，周回放才能汇总日记上下文。"],
                source_count=0,
            )
        retrospective = RetrospectiveService(
            self.conn,
            vault_id=self.vault_id,
            now_provider=self._now_iso,
        )
        window = retrospective.build_window(7)
        source_count = sum(int(value or 0) for value in window.summary.values())
        if source_count == 0:
            return VisibleContinuityPlaybackPreview(
                period="weekly",
                title=EMPTY_PLAYBACK_TITLE,
                summary=EMPTY_PLAYBACK_SUMMARY,
                themes=[],
                completed=[],
                stuck_points=[],
                next_focus=["先积累几段聊天、任务或笔记。"],
                source_count=0,
            )

        themes = [_safe_text(topic.name, limit=80) for topic in window.topics[:5]]
        if not themes:
            themes = _top_terms([item.summary for item in window.long_term_memories] + [item.summary for item in window.diary_summaries])
        completed = [_safe_text(source.label) for source in window.tasks.sources[:5] if source.label and window.tasks.completed]
        stuck = [_safe_text(source.label) for source in window.tasks.sources[:5] if source.label and window.tasks.pending]
        if not stuck:
            stuck = [_safe_text(item.title) for item in window.wiki_updates if item.action_type and "failed" in item.action_type][:3]
        next_focus = themes[:3] or stuck[:2] or ["先选一条线索继续推进。"]
        return VisibleContinuityPlaybackPreview(
            period="weekly",
            title="本地周回放预览",
            summary=_safe_text(
                f"最近 7 天找到 {window.summary.get('diary_objects', 0)} 条日记对象、"
                f"{window.summary.get('long_term_memories', 0)} 条长期记忆、"
                f"{window.summary.get('tasks', 0)} 条任务更新，以及 "
                f"{window.summary.get('wiki_updates', 0)} 条 Wiki/活动更新。"
            ),
            themes=themes[:5],
            completed=completed,
            stuck_points=stuck,
            next_focus=next_focus,
            source_count=source_count,
        )

    def _recent_messages(self, *, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "messages"):
            return []
        return self.conn.execute(
            """
            SELECT id, conversation_id, role, content, status, created_at, updated_at
            FROM messages
            WHERE status IN ('completed', 'partial')
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _unfinished_threads(self, *, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "conversations"):
            return []
        return self.conn.execute(
            """
            SELECT id, title, status, created_at, updated_at
            FROM conversations
            WHERE status = 'active'
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _active_tasks(self, *, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "tasks"):
            return []
        return self.conn.execute(
            """
            SELECT id, title, description, due_at_utc, status, source_text, created_at, updated_at
            FROM tasks
            WHERE status NOT IN ('done', 'completed', 'cancelled')
            ORDER BY COALESCE(due_at_utc, updated_at, created_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _recent_diary_objects(self, *, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "diary_memory_objects"):
            return []
        params: list[object] = []
        vault_clause = ""
        if self.vault_id:
            vault_clause = "AND vault_id = ?"
            params.append(self.vault_id)
        params.append(limit)
        return self.conn.execute(
            f"""
            SELECT id, vault_id, type, summary, topic, keywords_json, importance,
                   confidence, occurred_at, status, created_at, updated_at
            FROM diary_memory_objects
            WHERE status IN ('active', 'candidate') {vault_clause}
            ORDER BY occurred_at DESC, importance DESC
            LIMIT ?
            """,
            params,
        ).fetchall()

    def _recent_companion_reports(self, *, limit: int) -> list[sqlite3.Row]:
        if not _table_exists(self.conn, "companion_retrieval_reports"):
            return []
        return self.conn.execute(
            """
            SELECT id, agent_run_id, strategy, candidate_count, selected_count, source_counts_json, created_at
            FROM companion_retrieval_reports
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def _add_project_memory_buckets(self, buckets: dict[str, dict[str, object]]) -> None:
        if _table_exists(self.conn, "memory_graph_facts"):
            rows = self.conn.execute(
                """
                SELECT id, subject, predicate, object, status, memory_type, category, importance, updated_at, created_at
                FROM memory_graph_facts
                WHERE status IN ('active', 'candidate', 'stale', 'archived')
                  AND (memory_type = 'project_context' OR category LIKE '%project%' OR subject LIKE '%project%')
                ORDER BY importance DESC, updated_at DESC
                LIMIT 80
                """
            ).fetchall()
            for row in rows:
                fact_text = f"{row['subject']} {row['predicate']} {row['object']}"
                title = _project_title(fact_text)
                if not title:
                    continue
                bucket = buckets[_stable_key(title)]
                _touch_bucket(bucket, title=title, at=str(row["updated_at"] or row["created_at"]))
                _append_bucket(bucket, "progress", _safe_text(fact_text))
                status = str(row["status"] or "")
                if status in COMPLETED_PROJECT_STATUSES or _looks_completed(fact_text):
                    _record_project_signal(bucket, "completed")
                elif status == "active":
                    _record_project_signal(bucket, "active")
                else:
                    _record_project_signal(bucket, "tentative")
                _add_source(bucket, f"memory_graph_facts:{row['id']}")
        if _table_exists(self.conn, "memory_candidates"):
            rows = self.conn.execute(
                """
                SELECT id, summary, normalized_value, status, confidence, importance, evidence_count, updated_at, created_at
                FROM memory_candidates
                WHERE memory_kind = 'project_context'
                  AND status IN ('active', 'candidate', 'stale', 'archived')
                  AND risk_tier != 'high'
                ORDER BY importance DESC, updated_at DESC
                LIMIT 80
                """
            ).fetchall()
            for row in rows:
                confidence = float(row["confidence"] or 0)
                evidence_count = int(row["evidence_count"] or 0)
                status = str(row["status"] or "")
                if status == "candidate" and confidence < 0.55 and evidence_count < 2:
                    continue
                summary_text = str(row["summary"])
                normalized_text = str(row["normalized_value"])
                title = _project_title(summary_text) or _project_title(normalized_text)
                if not title:
                    continue
                bucket = buckets[_stable_key(title)]
                _touch_bucket(bucket, title=title, at=str(row["updated_at"] or row["created_at"]))
                _append_bucket(bucket, "progress", _safe_text(str(row["summary"])))
                if status in COMPLETED_PROJECT_STATUSES or _looks_completed(normalized_text) or _looks_completed(summary_text):
                    _record_project_signal(bucket, "completed")
                elif status == "active":
                    _record_project_signal(bucket, "active")
                else:
                    _record_project_signal(bucket, "tentative")
                _add_source(bucket, f"memory_candidates:{row['id']}")

    def _add_project_task_buckets(self, buckets: dict[str, dict[str, object]]) -> None:
        if not _table_exists(self.conn, "tasks"):
            return
        rows = self.conn.execute(
            """
            SELECT id, title, description, status, updated_at, created_at
            FROM tasks
            ORDER BY updated_at DESC, created_at DESC
            LIMIT 100
            """
        ).fetchall()
        for row in rows:
            title = _project_title(f"{row['title']} {row['description'] or ''}")
            if not title:
                continue
            bucket = buckets[_stable_key(title)]
            _touch_bucket(bucket, title=title, at=str(row["updated_at"] or row["created_at"]))
            status = str(row["status"]).casefold()
            if status in COMPLETED_PROJECT_STATUSES:
                _append_bucket(bucket, "progress", f"已完成任务：{_safe_text(str(row['title']))}")
                _record_project_signal(bucket, "completed")
            elif status in TERMINAL_PROJECT_STATUSES:
                _append_bucket(bucket, "blockers", f"已取消任务：{_safe_text(str(row['title']))}")
                _record_project_signal(bucket, "completed")
            elif status in BLOCKED_PROJECT_STATUSES:
                _append_bucket(bucket, "blockers", f"受阻任务：{_safe_text(str(row['title']))}")
                _record_project_signal(bucket, "blocked")
            else:
                _append_bucket(bucket, "progress", f"未完成任务：{_safe_text(str(row['title']))}")
                _record_project_signal(bucket, "active")
            _add_source(bucket, f"tasks:{row['id']}")

    def _add_project_diary_buckets(self, buckets: dict[str, dict[str, object]]) -> None:
        if not _table_exists(self.conn, "diary_memory_objects"):
            return
        rows = self._recent_diary_objects(limit=80)
        for row in rows:
            title = _project_title(" ".join([str(row["topic"] or ""), *_json_list(row["keywords_json"])]))
            if not title:
                continue
            confidence = float(row["confidence"] or 0)
            if str(row["status"] or "") == "candidate" and confidence < 0.55:
                continue
            bucket = buckets[_stable_key(title)]
            _touch_bucket(bucket, title=title, at=str(row["updated_at"] or row["occurred_at"]))
            _append_bucket(bucket, "progress", _safe_text(str(row["summary"])))
            if _looks_completed(str(row["summary"])):
                _record_project_signal(bucket, "completed")
            elif str(row["status"] or "") == "candidate" or confidence < 0.65:
                _record_project_signal(bucket, "tentative")
            else:
                _record_project_signal(bucket, "active")
            _add_source(bucket, f"diary_memory_objects:{row['id']}")

    def _add_project_message_buckets(self, buckets: dict[str, dict[str, object]]) -> None:
        if not _table_exists(self.conn, "messages"):
            return
        rows = self.conn.execute(
            """
            SELECT id, conversation_id, role, content, status, created_at, updated_at
            FROM messages
            WHERE status IN ('completed', 'partial')
              AND role IN ('user', 'assistant')
            ORDER BY created_at DESC, rowid DESC
            LIMIT 100
            """
        ).fetchall()
        grouped: dict[str, dict[str, object]] = defaultdict(lambda: {"title": "", "rows": []})
        for row in rows:
            content = _safe_text(str(row["content"]), limit=260)
            title = _project_title(content)
            if not title:
                continue
            project_id = _stable_key(title)
            grouped[project_id]["title"] = title
            grouped_rows = grouped[project_id]["rows"]
            if isinstance(grouped_rows, list):
                grouped_rows.append(row)

        for project_id, group in grouped.items():
            grouped_rows = group["rows"]
            if not isinstance(grouped_rows, list) or len(grouped_rows) < 2:
                continue
            title = str(group["title"])
            latest = grouped_rows[0]
            bucket = buckets[project_id]
            _touch_bucket(bucket, title=title, at=str(latest["updated_at"] or latest["created_at"]))
            _append_bucket(
                bucket,
                "progress",
                f"最近 {len(grouped_rows)} 条消息提到；最新内容：{_safe_text(str(latest['content']), limit=120)}",
            )
            _record_project_signal(bucket, "discussion", count=len(grouped_rows))
            for row in grouped_rows[:3]:
                _add_source(bucket, f"messages:{row['id']}")

    def _now_iso(self) -> str:
        return self.options.now_iso or utc_now_iso()


def _summary_from_sources(
    *,
    messages: list[sqlite3.Row],
    threads: list[sqlite3.Row],
    tasks: list[sqlite3.Row],
    diary: list[sqlite3.Row],
    reports: list[sqlite3.Row],
    receipts: list[VisibleContinuityReceipt],
) -> str:
    parts = []
    if messages:
        parts.append(f"{len(messages)} 条最近消息")
    if threads:
        parts.append(f"{len(threads)} 条活跃对话线索")
    if tasks:
        parts.append(f"{len(tasks)} 个未完成任务")
    if diary:
        parts.append(f"{len(diary)} 条日记记忆对象")
    if reports:
        parts.append(f"{len(reports)} 条陪伴检索报告")
    if receipts:
        parts.append(f"{len(receipts)} 条整理记录")
    return f"已从本地状态汇总：{'、'.join(parts)}。"


def _today_title(
    *,
    tasks: list[sqlite3.Row],
    threads: list[sqlite3.Row],
    projects: list[VisibleContinuityProjectCard],
) -> str:
    if tasks:
        return "继续今天未完成的工作"
    if projects:
        return "接上最近的任务线索"
    if threads:
        return "继续最近的对话"
    return "从最近的本地上下文继续"


def _today_summary(
    *,
    tasks: list[sqlite3.Row],
    threads: list[sqlite3.Row],
    projects: list[VisibleContinuityProjectCard],
    diary: list[sqlite3.Row],
    receipts: list[VisibleContinuityReceipt],
) -> str:
    unfinished: list[str] = []
    if tasks:
        unfinished.append(f"{len(tasks)} 个未完成任务")
    if projects:
        unfinished.append(f"{len(projects)} 张任务/主题卡片")
    if threads:
        unfinished.append(f"{len(threads)} 条活跃对话线索")

    remember: list[str] = []
    for project in projects[:2]:
        remember.append(f"{project.title}: {project.current_state}")
    for item in diary[:2]:
        remember.append(_safe_text(str(item["summary"]), limit=90))

    ignore = "暂时没有需要立刻清理的内容。"
    if receipts:
        reversible_count = sum(1 for receipt in receipts if receipt.reversible and receipt.status == "completed")
        if reversible_count:
            ignore = f"{reversible_count} 条最近可撤销整理记录可以先放着，除非你想撤销它们。"
        else:
            ignore = "最近整理记录已保存，目前不需要手动复核记忆。"

    if unfinished:
        return (
            f"未收尾：{'、'.join(unfinished)}。"
            f"值得继续：{_safe_join(remember[:2], fallback='最近的本地线索')}。"
            f"可以暂时忽略：{ignore}"
        )
    return (
        f"当前没有紧急未收尾事项。值得记住："
        f"{_safe_join(remember[:2], fallback='再积累一点聊天和笔记后，这里会显示最近线索')}。"
        f"可以暂时忽略：{ignore}"
    )


def _continuation_prompts(
    *,
    tasks: list[sqlite3.Row],
    threads: list[sqlite3.Row],
    projects: list[VisibleContinuityProjectCard],
    diary: list[sqlite3.Row],
    receipts: list[VisibleContinuityReceipt],
) -> list[str]:
    prompts: list[str] = []
    if tasks:
        prompts.append(f"帮我继续处理这个任务：{_safe_text(str(tasks[0]['title']), limit=120)}")
    if projects:
        prompts.append(f"帮我为 {projects[0].title} 选择下一步。")
    if threads:
        prompts.append(f"继续这条线索：{_safe_text(str(threads[0]['title'] or threads[0]['id']), limit=120)}")
    if diary:
        prompts.append(f"这条最近笔记里有什么值得记住：{_safe_text(str(diary[0]['summary']), limit=120)}")
    if receipts and not prompts:
        prompts.append("回顾你最近整理过的内容，并建议接下来继续什么。")
    if not prompts:
        prompts.append("帮我判断今天值得继续推进什么。")
    return _dedupe(prompts)[:3]


def _safe_join(values: Sequence[str], *, fallback: str) -> str:
    cleaned = [_safe_text(value, limit=110) for value in values if value.strip()]
    return "; ".join(cleaned) if cleaned else fallback


def _new_project_bucket() -> dict[str, object]:
    return {
        "sources": set(),
        "progress": [],
        "blockers": [],
        "active_signal_count": 0,
        "completed_signal_count": 0,
        "blocked_signal_count": 0,
        "tentative_signal_count": 0,
        "discussion_signal_count": 0,
    }


def _bucket_has_enough_signal(bucket: dict[str, object]) -> bool:
    active = int(bucket.get("active_signal_count") or 0)
    blocked = int(bucket.get("blocked_signal_count") or 0)
    completed = int(bucket.get("completed_signal_count") or 0)
    tentative = int(bucket.get("tentative_signal_count") or 0)
    discussion = int(bucket.get("discussion_signal_count") or 0)
    if active or blocked:
        return True
    if completed:
        return True
    return discussion >= 2 or tentative >= 2


def _project_card_from_bucket(project_id: str, bucket: dict[str, object]) -> VisibleContinuityProjectCard:
    title = _safe_text(str(bucket.get("title") or project_id.replace("-", " ").title()), limit=80)
    progress = [str(item) for item in bucket.get("progress", []) if str(item).strip()]
    blockers = [str(item) for item in bucket.get("blockers", []) if str(item).strip()]
    sources = sorted(str(item) for item in bucket.get("sources", set()))
    recent_progress = progress[0] if progress else "最近的本地信号提到了这个项目。"
    current_state = _project_current_state(bucket)
    next_step = _next_step_from_progress(title, progress, blockers, current_state=current_state)
    return VisibleContinuityProjectCard(
        project_id=project_id,
        title=title,
        current_state=current_state,
        recent_progress=_safe_text(recent_progress),
        next_step=_safe_text(next_step),
        blockers=[_safe_text(item) for item in blockers[:3]],
        last_touched_at=str(bucket.get("last_touched_at") or "") or None,
        sources=sources[:6],
    )


def _project_current_state(bucket: dict[str, object]) -> str:
    active = int(bucket.get("active_signal_count") or 0)
    blocked = int(bucket.get("blocked_signal_count") or 0)
    completed = int(bucket.get("completed_signal_count") or 0)
    tentative = int(bucket.get("tentative_signal_count") or 0)
    discussion = int(bucket.get("discussion_signal_count") or 0)
    if blocked:
        return "需要关注"
    if completed and not active:
        return "历史线索"
    if active:
        return "进行中"
    if tentative or discussion:
        return "待确认主题"
    return "进行中"


def _next_step_from_progress(title: str, progress: Sequence[str], blockers: Sequence[str], *, current_state: str) -> str:
    if blockers:
        return f"先处理：{blockers[0]}"
    if current_state == "历史线索":
        return "保留给回放即可，当前不需要动作。"
    if current_state == "待确认主题":
        return f"如果 {title} 要变成当前事项，可以再提一次。"
    if progress:
        return f"从最近未收尾的线索继续 {title}。"
    return DEFAULT_NEXT_STEP


def _record_project_signal(bucket: dict[str, object], kind: str, *, count: int = 1) -> None:
    key_by_kind = {
        "active": "active_signal_count",
        "completed": "completed_signal_count",
        "blocked": "blocked_signal_count",
        "tentative": "tentative_signal_count",
        "discussion": "discussion_signal_count",
    }
    key = key_by_kind.get(kind)
    if not key:
        return
    bucket[key] = int(bucket.get(key) or 0) + max(1, count)


def _safe_text(value: str, *, limit: int = MAX_SAFE_TEXT_CHARS) -> str:
    text = " ".join((value or "").split())
    for pattern in SECRET_TEXT_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[: max(0, limit - 3)].rstrip() + "..."
    return text or "没有可安全展示的摘要。"


def _safe_optional_text(value: object, *, limit: int = MAX_SAFE_TEXT_CHARS) -> str | None:
    if value is None:
        return None
    text = _safe_text(str(value), limit=limit)
    return None if text == "没有可安全展示的摘要。" else text


def _safe_target_path(value: str) -> str | None:
    path = _safe_text(value, limit=160)
    normalized = path.replace("\\", "/").strip()
    parts = [part for part in normalized.split("/") if part]
    if (
        not normalized
        or normalized.startswith("/")
        or ":" in normalized
        or ".." in parts
        or "." in parts
        or any(part.startswith(".") for part in parts)
        or not normalized.lower().endswith(".md")
    ):
        return None
    return normalized


def _project_title(value: str) -> str:
    text = _safe_text(value, limit=120)
    if "[REDACTED]" in text:
        return ""
    patterns = (
        r"\bproject[:= ]+(?P<title>[A-Za-z0-9][A-Za-z0-9 _-]{1,48}?)(?:\s+(?:is|was|needs|has|with|for|and|but)\b|[.。,:;]|$)",
        r"\bworking on (?P<title>[A-Za-z0-9][A-Za-z0-9 _-]{1,48}?)(?:\s+(?:is|was|needs|has|with|for|and|but)\b|[.。,:;]|$)",
        r"\bbuilding (?P<title>[A-Za-z0-9][A-Za-z0-9 _-]{1,48}?)(?:\s+(?:is|was|needs|has|with|for|and|but)\b|[.。,:;]|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return _clean_project_name(match.group("title"))
    if "project_context:" in text:
        return _clean_project_name(text.split("project_context:", 1)[1])
    if text.lower().startswith("project:"):
        return _clean_project_name(text.split(":", 1)[1])
    if "project" in text.casefold() or "项目" in text:
        return _clean_project_name(text)
    return ""


def _clean_project_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff _-]", " ", value)
    text = " ".join(text.split())
    text = re.sub(r"^(project|项目)\s+", "", text, flags=re.IGNORECASE).strip()
    text = re.split(
        r"\s+(?:is|was|needs|has|with|for|and|but|status|blocked|completed|finished|shipped|done|归档|完成)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip()
    return text[:64].strip()


def _looks_completed(value: str) -> bool:
    text = _safe_text(value, limit=260).casefold()
    return any(hint in text for hint in COMPLETION_HINTS)


def _stable_key(value: str) -> str:
    key = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff]+", "-", value.casefold()).strip("-")
    return key or "project"


def _touch_bucket(bucket: dict[str, object], *, title: str, at: str) -> None:
    if not bucket.get("title"):
        bucket["title"] = title
    current = str(bucket.get("last_touched_at") or "")
    if not current or at > current:
        bucket["last_touched_at"] = at


def _append_bucket(bucket: dict[str, object], key: str, value: str) -> None:
    values = bucket.setdefault(key, [])
    if isinstance(values, list):
        safe = _safe_text(value)
        if safe not in values:
            values.append(safe)


def _add_source(bucket: dict[str, object], value: str) -> None:
    sources = bucket.setdefault("sources", set())
    if isinstance(sources, set):
        sources.add(value)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (table,)).fetchone()
    return row is not None


def _json_list(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _json_dict(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value.strip()))


def _top_terms(values: Iterable[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for value in values:
        term = _safe_text(value, limit=80).strip()
        if not term or term == "没有可安全展示的摘要。":
            continue
        counts[term] += 1
    return [term for term, _ in counts.most_common(8)]


def _max_time(values: Iterable[str]) -> str | None:
    cleaned = [value for value in values if value]
    return max(cleaned) if cleaned else None


def _has_column(row: sqlite3.Row, column: str) -> bool:
    return column in row.keys()
