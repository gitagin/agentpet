from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.models.config import AutomationSettingsResponse
from app.models.enums import MemoryFactStatus
from app.services.agent_actions import AutomationPolicy
from app.services.diary_memory import DiaryMemoryService, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryExtractor, DiaryMemoryObject


class FakeDiaryExtractor:
    def __init__(self, objects: list[DiaryMemoryObject]) -> None:
        self.objects = objects
        self.calls: list[dict[str, str | None]] = []

    async def extract(
        self,
        diary_text: str,
        *,
        memory_date: str | None = None,
        source_path: str | None = None,
    ) -> list[DiaryMemoryObject]:
        self.calls.append(
            {
                "diary_text": diary_text,
                "memory_date": memory_date,
                "source_path": source_path,
            }
        )
        return self.objects


class FakeDiaryModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, str | None]] = []

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        self.calls.append({"user_message": user_message, "system_prompt": system_prompt})
        return self.response


class DiaryServiceFactory:
    def __init__(self, db_path: Path, objects: list[DiaryMemoryObject]) -> None:
        self.db_path = db_path
        self.objects = objects
        self.extractors: list[FakeDiaryExtractor] = []

    def __call__(self, _context: object) -> DiaryMemoryService:
        extractor = FakeDiaryExtractor(self.objects)
        self.extractors.append(extractor)
        return DiaryMemoryService(
            DiaryMemoryStore(self.db_path),
            vault_id="vault-1",
            extractor=extractor,
            extraction_model="fake-diary-extractor",
        )


@pytest.fixture()
def client(client_factory) -> Iterator[TestClient]:
    with client_factory() as test_client:
        yield test_client


def _memory_object(*, summary: str = "Project Atlas checkpoint was reviewed.", type: str = "event") -> DiaryMemoryObject:
    return DiaryMemoryObject(
        summary=summary,
        topic="Project Atlas",
        emotion="focused",
        people=(),
        keywords=("atlas", "checkpoint"),
        source_text=summary,
        importance=0.7,
        confidence=0.9,
        status=MemoryFactStatus.ACTIVE,
        type=type,
    )


def _state(*, user_message: str = "We reviewed the Project Atlas checkpoint.") -> AgentState:
    return AgentState(
        conversation_id="conversation-structured",
        message_id="user-message-1",
        agent_run_id="agent-run-1",
        user_message=user_message,
    )


def _automation(
    *,
    auto_chat_diary: bool = False,
    auto_structured_memory: bool = True,
    auto_long_term_memory: bool = False,
    auto_wiki_organize: bool = False,
) -> AutomationSettingsResponse:
    return AutomationSettingsResponse(
        auto_chat_diary=auto_chat_diary,
        auto_structured_memory=auto_structured_memory,
        auto_long_term_memory=auto_long_term_memory,
        auto_wiki_organize=auto_wiki_organize,
    )


def _context(client: TestClient) -> AppContext:
    from app.api.wiring import AppContext

    return AppContext(app=client.app, request_id="request-structured")


def _insert_vault_row(client: TestClient, vault_root: Path) -> None:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO vaults(id, root_path, name) VALUES (?, ?, ?)",
            ("vault-1", str(vault_root), "Test Vault"),
        )


def _rows(client: TestClient, table: str) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return list(conn.execute(f"SELECT * FROM {table} ORDER BY rowid"))


def _no_markdown_files(vault_root: Path) -> bool:
    return not vault_root.exists() or not list(vault_root.rglob("*.md"))


def _diary_memory_stage():
    import app.services.chat_pipeline.diary_memory as diary_memory_stage

    return diary_memory_stage


def _chat_pipeline():
    import app.services.chat_pipeline as chat_pipeline

    return chat_pipeline


@pytest.mark.asyncio
async def test_structured_diary_archives_sqlite_object_when_daily_diary_disabled(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)
    factory = DiaryServiceFactory(client.app.state.database.path, [_memory_object()])
    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", factory)

    object_ids, actions = await diary_memory_stage.archive_structured_diary_memory(
        context=_context(client),
        state=_state(),
        assistant_message_id="assistant-message-1",
        assistant_answer="The checkpoint is now recorded as reviewed.",
        daily_result=None,
        automation=_automation(auto_chat_diary=False, auto_structured_memory=True),
        policy=AutomationPolicy(),
    )

    objects = _rows(client, "diary_memory_objects")
    sources = _rows(client, "diary_memory_object_sources")
    assert len(object_ids) == 1
    assert len(actions) == 1
    assert [row["summary"] for row in objects] == ["Project Atlas checkpoint was reviewed."]
    assert sources[0]["source_type"] == "chat_exchange"
    assert sources[0]["source_id"] == "agent-run-1"
    assert sources[0]["conversation_id"] == "conversation-structured"
    assert sources[0]["user_message_id"] == "user-message-1"
    assert sources[0]["assistant_message_id"] == "assistant-message-1"
    assert sources[0]["agent_run_id"] == "agent-run-1"
    assert sources[0]["markdown_path"] is None
    assert factory.extractors[0].calls[0]["source_path"] is None
    assert _no_markdown_files(vault_root)


@pytest.mark.asyncio
async def test_structured_diary_accepts_daily_result_with_no_markdown_path(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)
    factory = DiaryServiceFactory(client.app.state.database.path, [_memory_object(type="qa")])
    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", factory)
    daily_result = SimpleNamespace(
        entry=SimpleNamespace(created_at="2026-07-07T01:02:03+00:00", markdown_path=None)
    )

    object_ids, _actions = await diary_memory_stage.archive_structured_diary_memory(
        context=_context(client),
        state=_state(),
        assistant_message_id="assistant-message-1",
        assistant_answer="The answer summary was safe.",
        daily_result=daily_result,
        automation=_automation(auto_chat_diary=True, auto_structured_memory=True),
        policy=AutomationPolicy(),
    )

    objects = _rows(client, "diary_memory_objects")
    sources = _rows(client, "diary_memory_object_sources")
    assert len(object_ids) == 1
    assert objects[0]["type"] == "qa"
    assert objects[0]["occurred_at"] == "2026-07-07T01:02:03+00:00"
    assert sources[0]["markdown_path"] is None
    assert factory.extractors[0].calls[0]["memory_date"] == "2026-07-07"
    assert factory.extractors[0].calls[0]["source_path"] is None
    assert _no_markdown_files(vault_root)


@pytest.mark.asyncio
async def test_structured_diary_preserves_daily_markdown_source_when_present(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)
    factory = DiaryServiceFactory(client.app.state.database.path, [_memory_object(type="project_update")])
    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", factory)
    markdown_path = "Memories/Daily/2026/07/week/2026-07-07.md"
    daily_result = SimpleNamespace(
        entry=SimpleNamespace(created_at="2026-07-07T02:03:04+00:00", markdown_path=markdown_path)
    )

    object_ids, _actions = await diary_memory_stage.archive_structured_diary_memory(
        context=_context(client),
        state=_state(),
        assistant_message_id="assistant-message-1",
        assistant_answer="Project Atlas next step is ready.",
        daily_result=daily_result,
        automation=_automation(auto_chat_diary=True, auto_structured_memory=True),
        policy=AutomationPolicy(),
    )

    objects = _rows(client, "diary_memory_objects")
    sources = _rows(client, "diary_memory_object_sources")
    assert len(object_ids) == 1
    assert objects[0]["type"] == "project_update"
    assert sources[0]["markdown_path"] == markdown_path
    assert factory.extractors[0].calls[0]["source_path"] == markdown_path
    assert _no_markdown_files(vault_root)


@pytest.mark.asyncio
async def test_daily_diary_failure_does_not_block_structured_diary_or_hide_daily_action(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    chat_pipeline = _chat_pipeline()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)
    factory = DiaryServiceFactory(client.app.state.database.path, [_memory_object()])
    daily_failure_action = AgentActionEvent(
        agent_run_id="agent-run-1",
        action_id="daily-failed",
        action_type="chat.diary",
        risk_tier="low",
        decision="auto",
        status="failed",
        title="Daily diary failed",
        summary="Daily diary write failed safely.",
        target_paths=[],
        reversible=False,
    )
    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", factory)
    monkeypatch.setattr(
        chat_pipeline,
        "automation_settings",
        lambda _context: _automation(auto_chat_diary=True, auto_structured_memory=True),
    )
    monkeypatch.setattr(chat_pipeline, "archive_daily_diary", lambda **_kwargs: (None, [daily_failure_action]))
    monkeypatch.setattr(chat_pipeline, "consolidate_slow_memory", lambda **_kwargs: [])
    monkeypatch.setattr(chat_pipeline, "archive_wiki_answer_summary", lambda **_kwargs: [])

    actions = await chat_pipeline.archive_chat_memory(
        context=_context(client),
        state=_state(),
        assistant_message_id="assistant-message-1",
        assistant_answer="The checkpoint is now recorded as reviewed.",
    )

    assert [action.action_id for action in actions if action.action_id == "daily-failed"] == ["daily-failed"]
    assert len(_rows(client, "diary_memory_objects")) == 1
    assert _rows(client, "diary_memory_object_sources")[0]["markdown_path"] is None
    assert _no_markdown_files(vault_root)


@pytest.mark.asyncio
async def test_auto_structured_memory_false_skips_sqlite_diary_object(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)
    factory = DiaryServiceFactory(client.app.state.database.path, [_memory_object()])
    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", factory)

    object_ids, actions = await diary_memory_stage.archive_structured_diary_memory(
        context=_context(client),
        state=_state(),
        assistant_message_id="assistant-message-1",
        assistant_answer="The checkpoint is now recorded as reviewed.",
        daily_result=None,
        automation=_automation(auto_chat_diary=False, auto_structured_memory=False),
        policy=AutomationPolicy(),
    )

    assert object_ids == ()
    assert actions == []
    assert factory.extractors == []
    assert _rows(client, "diary_memory_objects") == []
    assert _no_markdown_files(vault_root)


@pytest.mark.asyncio
async def test_do_not_remember_and_sensitive_payloads_do_not_write_diary_objects(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diary_memory_stage = _diary_memory_stage()
    vault_root = tmp_path / "Vault"
    _insert_vault_row(client, vault_root)

    do_not_remember_model = FakeDiaryModel(
        """
        [{"type":"event","summary":"Should not write.","topic":"private","emotion":"","people":[],"keywords":[],"source_text":"Should not write.","importance":0.8,"confidence":0.9}]
        """
    )
    sensitive_model = FakeDiaryModel(
        """
        [{"type":"event","summary":"Credential was discussed.","topic":"security","emotion":"worried","people":[],"keywords":["credential"],"source_text":"Authorization: Bearer secret-token-value","importance":0.8,"confidence":0.9}]
        """
    )
    models = iter((do_not_remember_model, sensitive_model))

    def service_factory(_context: object) -> DiaryMemoryService:
        return DiaryMemoryService(
            DiaryMemoryStore(client.app.state.database.path),
            vault_id="vault-1",
            extractor=DiaryMemoryExtractor(next(models)),
            extraction_model="fake-diary-model",
        )

    monkeypatch.setattr(diary_memory_stage, "diary_memory_service", service_factory)

    for user_message in (
        "Please do not remember this conversation.",
        "We discussed a temporary Authorization token in this debugging note.",
    ):
        await diary_memory_stage.archive_structured_diary_memory(
            context=_context(client),
            state=_state(user_message=user_message),
            assistant_message_id="assistant-message-1",
            assistant_answer="Understood.",
            daily_result=None,
            automation=_automation(auto_chat_diary=False, auto_structured_memory=True),
            policy=AutomationPolicy(),
        )

    assert _rows(client, "diary_memory_objects") == []
    assert do_not_remember_model.calls == []
    assert len(sensitive_model.calls) == 1
    assert _no_markdown_files(vault_root)
