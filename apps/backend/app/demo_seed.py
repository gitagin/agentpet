from __future__ import annotations

import argparse
import json
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.models.api import AutomationSettingsRequest
from app.repositories.storage import VaultRepository
from app.services.agent_actions import AgentActionCreate, AgentActionStore, markdown_snapshot
from app.services.chat_auto_memory import ChatAutoMemoryService, ChatAutoMemoryStore
from app.services.memory import SafeMarkdownWriter
from app.services.memory_graph import MemoryFactCandidate, MemoryGraphStore
from app.services.retrieval import RetrievalService
from app.services.settings import SettingsStore
from app.services.tasks import TaskService, TaskStore
from app.storage.database import Database, MigrationRunner


@dataclass(frozen=True, slots=True)
class DemoSeedManifest:
    root: str
    sqlite_path: str
    data_dir: str
    vault_root: str
    vault_id: str
    markdown_files: int
    memory_facts: int
    tasks: int
    indexed_files: int


_DEMO_FACTS = (
    ("preference", "用户", "偏好开会时间", "下午", "用户更喜欢下午开会。", "preference", 0.95),
    ("preference", "用户", "偏好回答风格", "简洁且带来源", "用户希望回答简洁，并能看到本地来源。", "preference", 0.94),
    ("project", "用户", "正在准备", "Agent Pet 作品集 Demo", "用户正在准备 Agent Pet 求职作品集 Demo。", "project", 0.93),
    ("boundary", "用户", "数据边界", "敏感内容不发送到远程模型", "用户要求敏感内容只走本地隐私路径。", "boundary", 0.98),
    ("preference", "用户", "开发环境", "Windows PowerShell", "用户主要在 Windows PowerShell 中开发。", "preference", 0.9),
)

_DEMO_PROJECT_PATH = "Wiki/Projects/Agent-Pet-Demo.md"


def seed_demo_environment(demo_root: str | Path) -> DemoSeedManifest:
    root = Path(demo_root).resolve(strict=False)
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Demo directory is not empty: {root}")

    data_dir = root / "data"
    vault_root = root / "vault"
    sqlite_path = data_dir / "agent-pet-demo.sqlite3"
    data_dir.mkdir(parents=True, exist_ok=True)
    vault_root.mkdir(parents=True, exist_ok=True)

    markdown_files = _write_demo_markdown(vault_root)
    database = Database(sqlite_path)
    MigrationRunner(database).apply()
    markdown_files += _write_demo_diaries(vault_root, sqlite_path)

    retrieval = RetrievalService(database)
    vault_id = retrieval.bind_vault(str(vault_root), name="Agent Pet Demo Vault")
    with database.session() as conn:
        with conn:
            VaultRepository(conn).set_active(vault_id)
    index_result = retrieval.rebuild_index(vault_id)

    graph_store = MemoryGraphStore(sqlite_path)
    try:
        for category, subject, predicate, value, source_text, memory_type, confidence in _DEMO_FACTS:
            graph_store.upsert_candidate(
                MemoryFactCandidate(
                    category=category,
                    subject=subject,
                    predicate=predicate,
                    object=value,
                    source_text=source_text,
                    source_type="demo_seed",
                    confidence=confidence,
                    memory_type=memory_type,
                    entity_type="person",
                    importance=0.8,
                    metadata_json=json.dumps({"demo": True}, ensure_ascii=False),
                )
            )
    finally:
        graph_store.close()

    task_store = TaskStore(sqlite_path)
    try:
        task_service = TaskService(task_store)
        local_now = datetime.now(ZoneInfo("Asia/Shanghai"))
        first_reminder = (local_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
        second_reminder = (local_now + timedelta(days=2)).replace(hour=16, minute=0, second=0, microsecond=0)
        task_service.create(
            title="整理面试演示提纲",
            remind_at=first_reminder.isoformat(),
            timezone="Asia/Shanghai",
            source_text="明天上午十点整理面试演示提纲",
        )
        task_service.create(
            title="检查 Demo 录屏素材",
            remind_at=second_reminder.isoformat(),
            timezone="Asia/Shanghai",
            source_text="后天下午四点检查 Demo 录屏素材",
        )
    finally:
        task_store.close()

    settings = SettingsStore(sqlite_path)
    try:
        settings.set_automation_settings(
            AutomationSettingsRequest(
                auto_chat_diary=True,
                auto_structured_memory=True,
                auto_long_term_memory=True,
                auto_wiki_organize=False,
                local_privacy_mode=True,
                proactive_trigger_frequency="off",
                use_negotiation=True,
                max_rounds=2,
            )
        )
    finally:
        settings.close()

    action_store = AgentActionStore(sqlite_path)
    try:
        action_store.create(
            AgentActionCreate(
                action_type="demo.seed",
                title="已准备隔离 Demo 数据",
                summary="预置本地记忆、日记、资料和任务，未读取真实用户数据。",
                risk_tier="low",
                decision="auto",
                status="completed",
                metadata={"demo": True, "vault_id": vault_id},
            )
        )
        action_store.create(
            AgentActionCreate(
                action_type="memory.demo_seed",
                title="已载入 5 条演示长期记忆",
                summary="用于带来源的本地记忆回答演示。",
                risk_tier="low",
                decision="auto",
                status="completed",
                metadata={"demo": True, "count": len(_DEMO_FACTS)},
            )
        )
        action_store.create(
            AgentActionCreate(
                action_type="task.demo_seed",
                title="已载入 2 个演示任务",
                summary="用于任务列表和提醒回执演示。",
                risk_tier="low",
                decision="auto",
                status="completed",
                metadata={"demo": True, "count": 2},
            )
        )
        writer = SafeMarkdownWriter(vault_root)
        before_snapshot = {
            "target_paths": [_DEMO_PROJECT_PATH],
            "contents": {_DEMO_PROJECT_PATH: ""},
            "hashes": {_DEMO_PROJECT_PATH: None},
            "exists": {_DEMO_PROJECT_PATH: False},
        }
        action_store.create(
            AgentActionCreate(
                action_type="demo.project_note.write",
                title="已创建 Demo 项目资料",
                summary="这是一条真实可撤回的隔离 Markdown 写入，用于演示活动账本与撤回回执。",
                risk_tier="low",
                decision="auto",
                status="completed",
                target_paths=(_DEMO_PROJECT_PATH,),
                before_snapshot=before_snapshot,
                after_snapshot=markdown_snapshot(writer, [_DEMO_PROJECT_PATH]),
                reversible=True,
                metadata={"demo": True, "purpose": "revert_walkthrough"},
            )
        )
    finally:
        action_store.close()

    manifest = DemoSeedManifest(
        root=str(root),
        sqlite_path=str(sqlite_path),
        data_dir=str(data_dir),
        vault_root=str(vault_root),
        vault_id=vault_id,
        markdown_files=markdown_files,
        memory_facts=len(_DEMO_FACTS),
        tasks=2,
        indexed_files=index_result.files_indexed,
    )
    (root / "demo-manifest.json").write_text(
        json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _write_demo_markdown(vault_root: Path) -> int:
    files: dict[Path, str] = {
        vault_root / "Memories" / "LongTerm" / "Preferences.md": (
            "# 下午开会与长期偏好\n\n"
            "## 开会时间\n\n用户更喜欢下午开会，上午适合独立专注。\n\n"
            "## 回答方式\n\n回答要简洁、可追踪，并在使用本地资料时给出来源。\n\n"
            "## 工作环境\n\n主要使用 Windows PowerShell 开发 Agent Pet。\n"
        ),
        vault_root.joinpath(*_DEMO_PROJECT_PATH.split("/")): (
            "# Agent Pet Demo\n\n"
            "## 目标\n\n展示 LangGraph 有界证据复核、本地记忆检索、引用、任务和确认边界。\n\n"
            "## 黄金路径\n\n1. 带来源的偏好回答。\n2. 一句话创建提醒并整理记忆。\n"
        ),
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return len(files)


def _write_demo_diaries(vault_root: Path, sqlite_path: Path) -> int:
    timezone = ZoneInfo("Asia/Shanghai")
    today = datetime.now(timezone).date()
    diary_exchanges = (
        (
            "演示数据会读取真实个人知识库吗？",
            "不会。这个演示只使用隔离数据，不读取真实个人知识库。",
        ),
        (
            "我更喜欢什么时候开会？",
            "你更喜欢下午开会，上午适合独立专注。",
        ),
        (
            "这次 Demo 的演示顺序是什么？",
            "先展示带来源回答，再创建任务和记忆，最后展示确认、活动账本与撤回。",
        ),
    )
    diary_times = iter(
        datetime.combine(today - timedelta(days=offset), time(hour=9 + index), tzinfo=timezone)
        for index, offset in enumerate(range(4, 1, -1))
    )
    service = ChatAutoMemoryService(
        ChatAutoMemoryStore(sqlite_path),
        SafeMarkdownWriter(vault_root),
        timezone_name="Asia/Shanghai",
        now_provider=lambda: next(diary_times),
    )
    try:
        for index, (question, answer) in enumerate(diary_exchanges, start=1):
            service.append_chat_exchange(
                conversation_id=f"demo-conversation-{index}",
                user_message_id=f"demo-user-message-{index}",
                assistant_message_id=f"demo-assistant-message-{index}",
                agent_run_id=f"demo-agent-run-{index}",
                user_question=question,
                assistant_answer=answer,
            )
    finally:
        service.close()
    return len(diary_exchanges)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare an isolated Agent Pet demo workspace.")
    parser.add_argument("--demo-root", required=True, help="Empty directory used only for disposable demo state.")
    args = parser.parse_args()
    manifest = seed_demo_environment(_validated_cli_demo_root(args.demo_root))
    print(json.dumps(asdict(manifest), ensure_ascii=False, indent=2))
    return 0


def _validated_cli_demo_root(value: str | Path) -> Path:
    repository_root = Path(__file__).resolve().parents[3]
    trusted_tmp_root = (repository_root / ".tmp").resolve(strict=False)
    lexical_target = Path(value).absolute()
    resolved_target = lexical_target.resolve(strict=False)
    try:
        relative = resolved_target.relative_to(trusted_tmp_root)
    except ValueError as exc:
        raise ValueError(f"Demo root must resolve inside {trusted_tmp_root}") from exc
    if not relative.parts:
        raise ValueError("Demo root must be a child directory of the repository .tmp folder")

    current = lexical_target.anchor and Path(lexical_target.anchor) or Path()
    for part in lexical_target.parts[1:] if lexical_target.anchor else lexical_target.parts:
        current /= part
        if not current.exists():
            break
        attributes = getattr(current.lstat(), "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if current.is_symlink() or attributes & reparse_flag:
            raise ValueError(f"Demo root must not traverse a symlink or reparse point: {current}")
    return resolved_target


if __name__ == "__main__":
    raise SystemExit(main())
