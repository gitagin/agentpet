from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.models.api import AgentActionResponse, AutomationSettingsRequest, AutomationSettingsResponse
from app.models.common import new_id
from app.services.memory import SafeMarkdownWriter, content_hash_text
from app.utils.time import utc_now_iso


RiskTier = Literal["low", "medium", "high"]
Decision = Literal["auto", "notify", "ask"]


@dataclass(frozen=True, slots=True)
class AutomationDecision:
    action_type: str
    risk_tier: RiskTier
    decision: Decision
    reversible: bool
    reason: str


@dataclass(frozen=True, slots=True)
class AgentActionCreate:
    action_type: str
    title: str
    summary: str = ""
    source_agent_run_id: str | None = None
    source_conversation_id: str | None = None
    source_message_id: str | None = None
    risk_tier: RiskTier = "low"
    decision: Decision = "auto"
    status: str = "completed"
    target_paths: tuple[str, ...] = ()
    before_snapshot: dict[str, object] = field(default_factory=dict)
    after_snapshot: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    reversible: bool = False
    error: str | None = None
    completed_at: str | None = None
    action_id: str | None = None


class AgentActionNotFoundError(Exception):
    pass


class AgentActionRevertError(Exception):
    pass


class AutomationPolicy:
    """Classify companion organization actions before execution."""

    HIGH_RISK_TYPES = {
        "vault.bind",
        "vault.switch",
        "markdown.delete",
        "markdown.move",
        "markdown.bulk_rewrite",
        "sqlite.schema_change",
        "local_state.reset",
        "sensitive_content",
    }
    MEDIUM_RISK_TYPES = {
        "wiki.ingest.apply",
        "wiki.lint.repair",
        "wiki.page.replace_section",
        "memory.promote_conflict",
        "continuity.identity",
        "continuity.relationship",
    }
    NOTIFY_TYPES = {
        "agent.notice",
        "agent_action.notice",
    }

    def decide(
        self,
        action_type: str,
        *,
        target_paths: list[str] | tuple[str, ...] = (),
        confidence: float | None = None,
        sensitive: bool = False,
        overwrite: bool = False,
        destructive: bool = False,
        reversible: bool = False,
    ) -> AutomationDecision:
        normalized = action_type.strip().casefold()
        target_path_risk = _target_path_risk(normalized, target_paths)
        if target_path_risk is not None:
            return AutomationDecision(
                action_type=action_type,
                risk_tier="high",
                decision="ask",
                reversible=False,
                reason=target_path_risk,
            )
        if sensitive or destructive or normalized in self.HIGH_RISK_TYPES:
            return AutomationDecision(action_type=action_type, risk_tier="high", decision="ask", reversible=False, reason="high_risk")
        if overwrite or normalized in self.MEDIUM_RISK_TYPES or (confidence is not None and confidence < 0.65):
            return AutomationDecision(
                action_type=action_type,
                risk_tier="medium",
                decision="ask",
                reversible=reversible,
                reason="needs_confirmation",
            )
        if normalized in self.NOTIFY_TYPES:
            return AutomationDecision(
                action_type=action_type,
                risk_tier="low",
                decision="notify",
                reversible=False,
                reason="passive_notification",
            )
        return AutomationDecision(
            action_type=action_type,
            risk_tier="low",
            decision="auto",
            reversible=reversible,
            reason="low_risk_private_companion",
        )


def _target_path_risk(action_type: str, target_paths: list[str] | tuple[str, ...]) -> str | None:
    for raw_path in target_paths:
        path = str(raw_path).replace("\\", "/").strip()
        parts = [part for part in path.split("/") if part]
        if not path or path.startswith("/") or ":" in path or ".." in parts or "." in parts:
            return "unsafe_target_path"
        if any(part.startswith(".") for part in parts):
            return "unsafe_target_path"
        if action_type.startswith("wiki.") and (not path.startswith("Wiki/") or not path.lower().endswith(".md")):
            return "wiki_write_outside_wiki"
    return None


class AgentActionStore:
    def __init__(self, db: str | Path | sqlite3.Connection):
        self._owns_connection = not isinstance(db, sqlite3.Connection)
        self.conn = sqlite3.connect(db) if self._owns_connection else db
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def create(self, request: AgentActionCreate) -> AgentActionResponse:
        now = utc_now_iso()
        action_id = request.action_id or new_id()
        completed_at = request.completed_at if request.status == "completed" else request.completed_at
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO agent_actions (
                    id, source_agent_run_id, source_conversation_id, source_message_id,
                    action_type, risk_tier, decision, status, title, summary,
                    target_paths_json, before_snapshot_json, after_snapshot_json,
                    metadata_json, reversible, error, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    request.source_agent_run_id,
                    request.source_conversation_id,
                    request.source_message_id,
                    request.action_type,
                    request.risk_tier,
                    request.decision,
                    request.status,
                    request.title,
                    request.summary,
                    _json(list(request.target_paths)),
                    _json(request.before_snapshot),
                    _json(request.after_snapshot),
                    _json(request.metadata),
                    1 if request.reversible else 0,
                    request.error,
                    now,
                    now,
                    completed_at or (now if request.status == "completed" else None),
                ),
            )
        return self.get(action_id)

    def list_recent(self, *, limit: int = 50, source_agent_run_id: str | None = None) -> list[AgentActionResponse]:
        capped = max(1, min(limit, 200))
        if source_agent_run_id:
            rows = self.conn.execute(
                """
                SELECT *
                FROM agent_actions
                WHERE source_agent_run_id = ?
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (source_agent_run_id, capped),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT *
                FROM agent_actions
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [self._map(row) for row in rows]

    def get(self, action_id: str) -> AgentActionResponse:
        row = self.conn.execute("SELECT * FROM agent_actions WHERE id = ?", (action_id,)).fetchone()
        if row is None:
            raise AgentActionNotFoundError(action_id)
        return self._map(row)

    def mark_reverted(self, action_id: str, reverted_by: str) -> AgentActionResponse:
        with self.conn:
            self.conn.execute(
                """
                UPDATE agent_actions
                SET status = 'reverted', reverted_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (reverted_by, utc_now_iso(), action_id),
            )
        return self.get(action_id)

    def get_automation_settings(self) -> AutomationSettingsResponse:
        row = self.conn.execute("SELECT * FROM automation_settings WHERE id = 1").fetchone()
        if row is None:
            return AutomationSettingsResponse()
        return AutomationSettingsResponse(
            auto_chat_diary=bool(row["auto_chat_diary"]),
            auto_structured_memory=bool(row["auto_structured_memory"]),
            auto_long_term_memory=bool(row["auto_long_term_memory"]),
            auto_wiki_organize=bool(row["auto_wiki_organize"]),
            high_risk_confirmation_required=bool(row["high_risk_confirmation_required"]),
            updated_at=str(row["updated_at"]),
        )

    def set_automation_settings(self, settings: AutomationSettingsRequest) -> AutomationSettingsResponse:
        now = utc_now_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO automation_settings (
                    id, auto_chat_diary, auto_structured_memory, auto_long_term_memory,
                    auto_wiki_organize, high_risk_confirmation_required, created_at, updated_at
                )
                VALUES (1, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    auto_chat_diary = excluded.auto_chat_diary,
                    auto_structured_memory = excluded.auto_structured_memory,
                    auto_long_term_memory = excluded.auto_long_term_memory,
                    auto_wiki_organize = excluded.auto_wiki_organize,
                    high_risk_confirmation_required = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    1 if settings.auto_chat_diary else 0,
                    1 if settings.auto_structured_memory else 0,
                    1 if settings.auto_long_term_memory else 0,
                    1 if settings.auto_wiki_organize else 0,
                    now,
                    now,
                ),
            )
        return self.get_automation_settings()

    def _map(self, row: sqlite3.Row) -> AgentActionResponse:
        metadata = _json_load(row["metadata_json"], {})
        before_snapshot = _json_load(row["before_snapshot_json"], {})
        after_snapshot = _json_load(row["after_snapshot_json"], {})
        target_paths = [str(item) for item in _json_load(row["target_paths_json"], [])]
        return AgentActionResponse(
            action_id=str(row["id"]),
            source_agent_run_id=_optional_str(row["source_agent_run_id"]),
            source_conversation_id=_optional_str(row["source_conversation_id"]),
            source_message_id=_optional_str(row["source_message_id"]),
            action_type=str(row["action_type"]),
            risk_tier=str(row["risk_tier"]),  # type: ignore[arg-type]
            decision=str(row["decision"]),  # type: ignore[arg-type]
            status=str(row["status"]),
            title=str(row["title"]),
            summary=str(row["summary"] or ""),
            target_paths=target_paths,
            reversible=bool(row["reversible"]),
            reverted_by=_optional_str(row["reverted_by"]),
            reverts_action_id=_optional_str(row["reverts_action_id"]),
            error=_optional_str(row["error"]),
            source=_action_source(row, metadata),
            diff_summary=_diff_summary(target_paths, before_snapshot, after_snapshot),
            metadata=metadata if isinstance(metadata, dict) else {},
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            completed_at=_optional_str(row["completed_at"]),
        )


class AgentActionService:
    def __init__(
        self,
        store: AgentActionStore,
        *,
        writer: SafeMarkdownWriter | None = None,
        index_refresh=None,
    ) -> None:
        self.store = store
        self.writer = writer
        self.index_refresh = index_refresh

    def close(self) -> None:
        self.store.close()

    def record(self, request: AgentActionCreate) -> AgentActionResponse:
        return self.store.create(request)

    def list_recent(self, *, limit: int = 50, source_agent_run_id: str | None = None) -> list[AgentActionResponse]:
        return self.store.list_recent(limit=limit, source_agent_run_id=source_agent_run_id)

    def get_automation_settings(self) -> AutomationSettingsResponse:
        return self.store.get_automation_settings()

    def set_automation_settings(self, settings: AutomationSettingsRequest) -> AutomationSettingsResponse:
        return self.store.set_automation_settings(settings)

    def revert(self, action_id: str) -> tuple[AgentActionResponse, AgentActionResponse]:
        original = self.store.get(action_id)
        if original.status == "reverted":
            raise AgentActionRevertError("该动作已经撤销。")
        if not original.reversible:
            raise AgentActionRevertError("该动作没有可用的自动撤销记录。")
        if self.writer is None:
            raise AgentActionRevertError("当前没有绑定 Vault，无法撤销 Markdown 写入。")

        before = self._snapshot_for_revert(action_id)
        target_paths = before.get("target_paths")
        if not isinstance(target_paths, list) or not target_paths:
            target_paths = original.target_paths
        contents = before.get("contents")
        if not isinstance(contents, dict):
            raise AgentActionRevertError("撤销快照缺少 Markdown 内容。")
        exists_map = before.get("exists")
        if not isinstance(exists_map, dict):
            exists_map = {}

        for relative_path in target_paths:
            content = contents.get(str(relative_path))
            if not isinstance(content, str):
                continue
            existed_before = bool(exists_map.get(str(relative_path), False))
            path = self.writer.resolve_markdown_path(str(relative_path))
            if not existed_before and path.exists():
                path.unlink()
            else:
                self.writer.write(str(relative_path), content)
            if self.index_refresh is not None:
                self.index_refresh(str(relative_path))

        reverted = self.store.create(
            AgentActionCreate(
                action_type="agent_action.revert",
                title=f"已撤销：{original.title}",
                summary=f"恢复 {len(target_paths)} 个 Markdown 目标。",
                source_agent_run_id=original.source_agent_run_id,
                source_conversation_id=original.source_conversation_id,
                source_message_id=original.source_message_id,
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=tuple(str(path) for path in target_paths),
                metadata={"reverted_action_id": action_id},
                reversible=False,
                completed_at=utc_now_iso(),
            )
        )
        with self.store.conn:
            self.store.conn.execute(
                "UPDATE agent_actions SET reverts_action_id = ? WHERE id = ?",
                (action_id, reverted.action_id),
            )
        updated = self.store.mark_reverted(action_id, reverted.action_id)
        return updated, self.store.get(reverted.action_id)

    def _snapshot_for_revert(self, action_id: str) -> dict[str, object]:
        row = self.store.conn.execute(
            "SELECT before_snapshot_json FROM agent_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        if row is None:
            raise AgentActionNotFoundError(action_id)
        payload = _json_load(row["before_snapshot_json"], {})
        return payload if isinstance(payload, dict) else {}


def markdown_snapshot(writer: SafeMarkdownWriter, target_paths: list[str] | tuple[str, ...]) -> dict[str, object]:
    contents: dict[str, str] = {}
    hashes: dict[str, str | None] = {}
    exists: dict[str, bool] = {}
    for relative_path in target_paths:
        path = writer.resolve_markdown_path(relative_path)
        if path.exists():
            text = path.read_text(encoding="utf-8")
            contents[relative_path] = text
            hashes[relative_path] = content_hash_text(text)
            exists[relative_path] = True
        else:
            contents[relative_path] = ""
            hashes[relative_path] = None
            exists[relative_path] = False
    return {"target_paths": list(target_paths), "contents": contents, "hashes": hashes, "exists": exists}


def _action_source(row: sqlite3.Row, metadata: object) -> dict[str, str]:
    source: dict[str, str] = {}
    if isinstance(metadata, dict):
        raw_source = metadata.get("source")
        if isinstance(raw_source, str) and raw_source.strip():
            source["label"] = raw_source.strip()
        elif isinstance(raw_source, dict):
            for key, value in raw_source.items():
                if isinstance(key, str) and isinstance(value, str) and value.strip():
                    source[key] = value.strip()
    for key in ("source_agent_run_id", "source_conversation_id", "source_message_id"):
        value = _optional_str(row[key])
        if value:
            source[key] = value
    return source


def _diff_summary(target_paths: list[str], before_snapshot: object, after_snapshot: object) -> str:
    before = before_snapshot if isinstance(before_snapshot, dict) else {}
    after = after_snapshot if isinstance(after_snapshot, dict) else {}
    before_hashes = before.get("hashes") if isinstance(before.get("hashes"), dict) else {}
    after_hashes = after.get("hashes") if isinstance(after.get("hashes"), dict) else {}
    before_exists = before.get("exists") if isinstance(before.get("exists"), dict) else {}
    after_exists = after.get("exists") if isinstance(after.get("exists"), dict) else {}
    added = 0
    updated = 0
    removed = 0
    unchanged = 0
    for path in target_paths:
        existed_before = bool(before_exists.get(path, before_hashes.get(path) is not None))
        exists_after = bool(after_exists.get(path, after_hashes.get(path) is not None))
        if not existed_before and exists_after:
            added += 1
        elif existed_before and not exists_after:
            removed += 1
        elif before_hashes.get(path) != after_hashes.get(path):
            updated += 1
        else:
            unchanged += 1
    parts = []
    if added:
        parts.append(f"新增 {added} 个文件")
    if updated:
        parts.append(f"更新 {updated} 个文件")
    if removed:
        parts.append(f"删除 {removed} 个文件")
    if unchanged and not parts:
        parts.append(f"未改变 {unchanged} 个文件")
    return "，".join(parts)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: object, default):
    if value is None:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
