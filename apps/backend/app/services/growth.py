from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.models.api import (
    GrowthDimensionResponse,
    GrowthEventResponse,
    GrowthSnapshotResponse,
    LocalAssetStatsResponse,
)
from app.services.local_assets import LocalAssetStatsService
from app.utils.time import utc_now_iso


@dataclass(frozen=True, slots=True)
class _GrowthSpec:
    key: str
    label: str
    description: str
    thresholds: tuple[int, ...]
    level_labels: tuple[str, ...]
    data_sources: tuple[str, ...]


_GROWTH_SPECS = {
    "memory_depth": _GrowthSpec(
        key="memory_depth",
        label="记忆脉络",
        description="聊天日记和长期记忆越多，桌宠越能接住连续话题。",
        thresholds=(1, 3, 8, 20),
        level_labels=("刚开始认识你", "记得住片段", "能接住日常", "形成长期脉络", "稳定陪伴"),
        data_sources=("daily_chat_memory_entries", "memory_graph_facts"),
    ),
    "response_affinity": _GrowthSpec(
        key="response_affinity",
        label="回应默契",
        description="偏好、边界和风格类记忆越明确，回复越贴近你的表达习惯。",
        thresholds=(1, 2, 5, 12),
        level_labels=("还在试探语气", "记住一点偏好", "开始贴合表达", "能稳定迁就风格", "默契成熟"),
        data_sources=("memory_graph_facts", "diary_memory_objects"),
    ),
    "trust_boundary": _GrowthSpec(
        key="trust_boundary",
        label="安心边界",
        description="撤回、跳过和可撤销记录越清楚，桌宠越能展示边界感。",
        thresholds=(1, 2, 4, 9),
        level_labels=("边界刚建立", "能留下痕迹", "能被纠正", "边界稳定", "信任闭环清楚"),
        data_sources=("agent_actions", "memory_feedback_events"),
    ),
    "knowledge_links": _GrowthSpec(
        key="knowledge_links",
        label="知识连接",
        description="Wiki 页面和资料整理越多，桌宠越能把零散内容连成可回看的线索。",
        thresholds=(1, 3, 8, 18),
        level_labels=("还没有知识枝条", "长出第一批资料", "能串起主题", "知识脉络清楚", "资料网络稳定"),
        data_sources=("vault/Wiki", "agent_actions"),
    ),
}


class GrowthSnapshotService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        vault_id: str | None = None,
        vault_root: str | Path | None = None,
    ) -> None:
        self.conn = conn
        self.vault_id = vault_id
        self.vault_root = Path(vault_root) if vault_root else None

    def snapshot(self) -> GrowthSnapshotResponse:
        stats = LocalAssetStatsService(
            self.conn,
            vault_id=self.vault_id,
            vault_root=self.vault_root,
        ).summarize()
        stats_response = LocalAssetStatsResponse(
            vault_configured=stats.vault_configured,
            vault_id=stats.vault_id,
            chat_diary_days=stats.chat_diary_days,
            chat_diary_entries=stats.chat_diary_entries,
            long_term_memory_count=stats.long_term_memory_count,
            wiki_page_count=stats.wiki_page_count,
            task_count=stats.task_count,
            completed_task_count=stats.completed_task_count,
            latest_organization_at=stats.latest_organization_at,
            reversible_operation_count=stats.reversible_operation_count,
        )
        values = {
            "memory_depth": stats.chat_diary_entries + stats.long_term_memory_count,
            "response_affinity": self._response_affinity_count(),
            "trust_boundary": stats.reversible_operation_count
            + self._reverted_action_count()
            + self._skipped_boundary_count()
            + self._feedback_event_count(),
            "knowledge_links": stats.wiki_page_count,
        }
        changed_at = {
            "memory_depth": self._latest_at(
                "SELECT MAX(COALESCE(updated_at, created_at)) AS latest FROM daily_chat_memory_entries",
                "SELECT MAX(updated_at) AS latest FROM memory_graph_facts",
            ),
            "response_affinity": self._latest_at(
                """
                SELECT MAX(updated_at) AS latest
                FROM memory_graph_facts
                WHERE status IN ('active', 'candidate')
                  AND (
                    category IN ('preference', 'boundary')
                    OR COALESCE(memory_type, '') IN ('preference', 'boundary')
                  )
                """,
                """
                SELECT MAX(updated_at) AS latest
                FROM diary_memory_objects
                WHERE status IN ('active', 'candidate')
                  AND type IN ('preference', 'habit', 'boundary')
                """,
            ),
            "trust_boundary": self._latest_at(
                """
                SELECT MAX(COALESCE(completed_at, updated_at, created_at)) AS latest
                FROM agent_actions
                WHERE reversible = 1
                   OR status IN ('reverted', 'skipped')
                   OR reverts_action_id IS NOT NULL
                   OR action_type LIKE '%.skip%'
                """,
                "SELECT MAX(created_at) AS latest FROM memory_feedback_events",
            ),
            "knowledge_links": self._latest_at(
                """
                SELECT MAX(COALESCE(completed_at, updated_at, created_at)) AS latest
                FROM agent_actions
                WHERE action_type LIKE 'wiki.%'
                """,
            )
            or stats.latest_organization_at,
        }
        return GrowthSnapshotResponse(
            generated_at=utc_now_iso(),
            dimensions=[
                self._dimension_response(_GROWTH_SPECS[key], values[key], changed_at[key])
                for key in ("memory_depth", "response_affinity", "trust_boundary", "knowledge_links")
            ],
            events=self._recent_events(),
            stats=stats_response,
        )

    def _dimension_response(
        self,
        spec: _GrowthSpec,
        current_value: int,
        last_changed_at: str | None,
    ) -> GrowthDimensionResponse:
        level = sum(1 for threshold in spec.thresholds if current_value >= threshold)
        next_threshold = next((threshold for threshold in spec.thresholds if current_value < threshold), None)
        if next_threshold is None:
            progress = 100
        else:
            previous_threshold = spec.thresholds[level - 1] if level > 0 else 0
            span = max(1, next_threshold - previous_threshold)
            progress = round(((current_value - previous_threshold) / span) * 100)
            progress = max(0, min(99, progress))
        return GrowthDimensionResponse(
            key=spec.key,
            label=spec.label,
            level=level,
            level_label=spec.level_labels[level],
            current_value=current_value,
            next_threshold=next_threshold,
            progress=progress,
            description=spec.description,
            data_sources=list(spec.data_sources),
            last_changed_at=last_changed_at,
        )

    def _response_affinity_count(self) -> int:
        graph = self._count(
            """
            SELECT COUNT(*) AS count
            FROM memory_graph_facts
            WHERE status IN ('active', 'candidate')
              AND (
                category IN ('preference', 'boundary')
                OR COALESCE(memory_type, '') IN ('preference', 'boundary')
              )
            """
        )
        diary = self._count(
            """
            SELECT COUNT(*) AS count
            FROM diary_memory_objects
            WHERE status IN ('active', 'candidate')
              AND type IN ('preference', 'habit', 'boundary')
            """
        )
        return graph + diary

    def _reverted_action_count(self) -> int:
        return self._count(
            """
            SELECT COUNT(*) AS count
            FROM agent_actions
            WHERE status = 'reverted' OR reverts_action_id IS NOT NULL
            """
        )

    def _skipped_boundary_count(self) -> int:
        return self._count(
            """
            SELECT COUNT(*) AS count
            FROM agent_actions
            WHERE status = 'skipped'
               OR action_type LIKE '%.skip'
               OR action_type LIKE '%.skip.%'
            """
        )

    def _feedback_event_count(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM memory_feedback_events")

    def _count(self, sql: str) -> int:
        row = self.conn.execute(sql).fetchone()
        return int(row["count"] or 0)

    def _latest_at(self, *queries: str) -> str | None:
        latest: str | None = None
        for query in queries:
            row = self.conn.execute(query).fetchone()
            value = str(row["latest"]) if row and row["latest"] else None
            if value and (latest is None or value > latest):
                latest = value
        return latest

    def _recent_events(self, limit: int = 20) -> list[GrowthEventResponse]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM agent_actions
            WHERE action_type IN (
                'chat.daily_archive',
                'diary.structured_memory',
                'memory.long_term.write',
                'memory.consolidation.candidate',
                'agent_action.revert'
            )
               OR action_type LIKE 'wiki.%'
               OR action_type LIKE '%.skip%'
               OR status IN ('reverted', 'skipped')
               OR reversible = 1
            ORDER BY COALESCE(completed_at, updated_at, created_at) DESC, rowid DESC
            LIMIT ?
            """,
            (max(1, min(limit, 50)),),
        ).fetchall()
        return [self._event_response(row) for row in rows]

    def _event_response(self, row: sqlite3.Row) -> GrowthEventResponse:
        action_type = str(row["action_type"])
        return GrowthEventResponse(
            event_id=str(row["id"]),
            occurred_at=str(row["completed_at"] or row["updated_at"] or row["created_at"]),
            dimension_key=self._dimension_for_action(action_type, str(row["status"] or ""), bool(row["reversible"])),
            title=str(row["title"]),
            summary=str(row["summary"] or ""),
            source_action_id=str(row["id"]),
            source_action_type=action_type,
            target_paths=_json_string_list(row["target_paths_json"]),
        )

    def _dimension_for_action(self, action_type: str, status: str, reversible: bool) -> str:
        normalized = action_type.casefold()
        if normalized.startswith("wiki."):
            return "knowledge_links"
        if normalized == "agent_action.revert" or status in {"reverted", "skipped"} or ".skip" in normalized or reversible:
            return "trust_boundary"
        if normalized in {"diary.structured_memory", "memory.long_term.write", "memory.consolidation.candidate"}:
            return "response_affinity"
        return "memory_depth"


def _json_string_list(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]

