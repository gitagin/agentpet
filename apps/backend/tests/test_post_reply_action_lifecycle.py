from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.state import AgentState
from app.api.wiring import AppContext
from app.models.config import AutomationSettingsResponse
from app.models.enums import MemoryFactStatus
from app.services.diary_memory import DiaryMemoryService, DiaryMemoryStore
from app.services.diary_memory_extractor import DiaryMemoryObject
from app.services.memory_candidates import MemoryCandidateCreate, MemoryCandidateStore, MemoryEvidenceCreate
from app.services.memory_consolidation import MemoryConsolidationPreview, MemoryConsolidationService


def _automation(*, daily: bool = False, structured: bool = False, slow: bool = False):
    return AutomationSettingsResponse(
        auto_chat_diary=daily,
        auto_structured_memory=structured,
        auto_long_term_memory=slow,
        auto_wiki_organize=False,
    )


def _state(run_id: str) -> AgentState:
    return AgentState(
        conversation_id=f"conversation-{run_id}",
        message_id=f"user-{run_id}",
        agent_run_id=run_id,
        user_message="Remember this: my favorite editor is VS Code.",
    )


def _init_vault(client: TestClient, root: Path) -> None:
    response = client.post(
        "/api/vaults/init",
        headers={"Authorization": "Bearer test-token"},
        json={"path": str(root), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200, response.text


def _action_rows(client: TestClient, action_type: str) -> list[sqlite3.Row]:
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        return list(
            conn.execute(
                "SELECT * FROM agent_actions WHERE action_type = ? ORDER BY created_at, id",
                (action_type,),
            )
        )


def _seed_exchange(client: TestClient, state: AgentState, assistant_message_id: str) -> None:
    now = "2026-08-10T00:00:00Z"
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO conversations (id, title, status, created_at, updated_at)
            VALUES (?, 'lifecycle', 'active', ?, ?)
            """,
            (state.conversation_id, now, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
                (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, 'user', ?, 'completed', ?, ?)
            """,
            (state.message_id, state.conversation_id, state.user_message, now, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO messages
                (id, conversation_id, role, content, status, created_at, updated_at)
            VALUES (?, ?, 'assistant', ?, 'completed', ?, ?)
            """,
            (assistant_message_id, state.conversation_id, "The editor choice is recorded.", now, now),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_runs
                (id, conversation_id, user_message_id, assistant_message_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'success', ?, ?)
            """,
            (state.agent_run_id, state.conversation_id, state.message_id, assistant_message_id, now, now),
        )
        conn.commit()


@pytest.mark.asyncio
async def test_daily_archive_claim_exists_before_markdown_effect_and_recovers_without_replay(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_factory() as client:
        vault = tmp_path / "daily-vault"
        _init_vault(client, vault)
        import app.services.chat_pipeline.diary as stage

        original_factory = stage.chat_auto_memory_service
        calls = 0
        first_effect_failure = True

        def wrapped_factory(context):
            service = original_factory(context)
            original_append = service.append_chat_exchange

            def append(**kwargs):
                nonlocal calls, first_effect_failure
                rows = _action_rows(client, "chat.daily_archive")
                assert rows and rows[-1]["status"] == "executing"
                calls += 1
                result = original_append(**kwargs)
                if first_effect_failure:
                    first_effect_failure = False
                    raise RuntimeError("crash_after_daily_effect")
                return result

            service.append_chat_exchange = append
            return service

        monkeypatch.setattr(stage, "chat_auto_memory_service", wrapped_factory)
        context = AppContext(app=client.app)
        state = _state("daily-lifecycle-run")
        pending = stage.archive_daily_diary(
            context=context,
            state=state,
            assistant_message_id="assistant-daily-lifecycle",
            assistant_answer="The editor choice is recorded.",
            automation=_automation(daily=True),
            policy=object(),
            raise_errors=True,
        )
        first_result, first_actions = await pending
        second_result, second_actions = await stage.archive_daily_diary(
            context=context,
            state=state,
            assistant_message_id="assistant-daily-lifecycle",
            assistant_answer="The editor choice is recorded.",
            automation=_automation(daily=True),
            policy=object(),
            raise_errors=True,
        )

        assert calls == 1
        assert first_result is not None and second_result is not None
        assert first_result.entry.id == second_result.entry.id
        assert first_actions[0].action_id == second_actions[0].action_id
        assert len(_action_rows(client, "chat.daily_archive")) == 1
        assert len(list((vault / "Memories" / "Daily").rglob("*.md"))) == 1


class _FixedDiaryExtractor:
    async def extract(self, diary_text: str, *, memory_date=None, source_path=None):
        return [
            DiaryMemoryObject(
                summary="Project Atlas checkpoint was reviewed.",
                topic="Project Atlas",
                emotion="focused",
                people=(),
                keywords=("atlas", "checkpoint"),
                source_text="Project Atlas checkpoint was reviewed.",
                importance=0.8,
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
                type="event",
            )
        ]


class _TwoObjectDiaryExtractor:
    async def extract(self, diary_text: str, *, memory_date=None, source_path=None):
        return [
            DiaryMemoryObject(
                summary="Project Atlas checkpoint was reviewed.",
                topic="Project Atlas",
                emotion="focused",
                people=(),
                keywords=("atlas", "checkpoint"),
                source_text="Project Atlas checkpoint was reviewed.",
                importance=0.8,
                confidence=0.9,
                status=MemoryFactStatus.ACTIVE,
                type="event",
            ),
            DiaryMemoryObject(
                summary="Project Atlas release risk was recorded.",
                topic="Project Atlas",
                emotion="concerned",
                people=(),
                keywords=("atlas", "risk"),
                source_text="Project Atlas release risk was recorded.",
                importance=0.75,
                confidence=0.88,
                status=MemoryFactStatus.ACTIVE,
                type="event",
            ),
        ]


@pytest.mark.asyncio
async def test_structured_diary_claim_precedes_sqlite_effect_and_recovery_is_idempotent(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_factory() as client:
        vault = tmp_path / "structured-vault"
        _init_vault(client, vault)
        with sqlite3.connect(client.app.state.database.path) as conn:
            vault_id = str(conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()[0])
        import app.services.chat_pipeline.diary_memory as stage

        calls = 0
        first_effect_failure = True

        def factory(_context):
            service = DiaryMemoryService(
                DiaryMemoryStore(client.app.state.database.path),
                vault_id=vault_id,
                extractor=_FixedDiaryExtractor(),
                extraction_model="fixed-test",
            )
            original_archive = service.archive_chat_exchange

            async def archive(**kwargs):
                nonlocal calls, first_effect_failure
                rows = _action_rows(client, "diary.structured_memory")
                assert rows and rows[-1]["status"] == "executing"
                calls += 1
                result = await original_archive(**kwargs)
                if first_effect_failure:
                    first_effect_failure = False
                    raise RuntimeError("crash_after_structured_effect")
                return result

            service.archive_chat_exchange = archive
            return service

        monkeypatch.setattr(stage, "diary_memory_service", factory)
        context = AppContext(app=client.app)
        state = _state("structured-lifecycle-run")
        kwargs = {
            "context": context,
            "state": state,
            "assistant_message_id": "assistant-structured-lifecycle",
            "assistant_answer": "The checkpoint is recorded.",
            "daily_result": None,
            "automation": _automation(structured=True),
            "policy": object(),
            "raise_errors": True,
        }
        first_ids, first_actions = await stage.archive_structured_diary_memory(**kwargs)
        second_ids, second_actions = await stage.archive_structured_diary_memory(**kwargs)

        assert calls == 1
        assert first_ids == second_ids and first_ids
        assert first_actions[0].action_id == second_actions[0].action_id
        assert len(_action_rows(client, "diary.structured_memory")) == 1
        with sqlite3.connect(client.app.state.database.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_structured_diary_partial_object_set_is_not_verified_as_complete(
    client_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_factory() as client:
        _init_vault(client, tmp_path / "structured-partial-vault")
        with sqlite3.connect(client.app.state.database.path) as conn:
            vault_id = str(conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()[0])
        import app.services.chat_pipeline.diary_memory as stage

        insert_calls = 0

        def factory(_context):
            nonlocal insert_calls
            service = DiaryMemoryService(
                DiaryMemoryStore(client.app.state.database.path),
                vault_id=vault_id,
                extractor=_TwoObjectDiaryExtractor(),
                extraction_model="fixed-two-object-test",
            )
            original_insert = service.store.insert_object

            def insert_object(**kwargs):
                nonlocal insert_calls
                insert_calls += 1
                if insert_calls == 2:
                    raise RuntimeError("crash_after_first_structured_object")
                return original_insert(**kwargs)

            service.store.insert_object = insert_object
            return service

        monkeypatch.setattr(stage, "diary_memory_service", factory)
        state = _state("structured-partial-run")

        with pytest.raises(RuntimeError):
            await stage.archive_structured_diary_memory(
                context=AppContext(app=client.app),
                state=state,
                assistant_message_id="assistant-structured-partial",
                assistant_answer="The checkpoint and release risk are recorded.",
                daily_result=None,
                automation=_automation(structured=True),
                policy=object(),
                raise_errors=True,
            )

        rows = _action_rows(client, "diary.structured_memory")
        assert len(rows) == 1
        assert rows[0]["status"] == "failed_recovery"
        with sqlite3.connect(client.app.state.database.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM diary_memory_objects").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_slow_consolidation_claim_precedes_candidate_effect_and_recovery_is_idempotent(
    client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_factory() as client:
        import app.services.chat_pipeline.consolidation as stage

        calls = 0
        first_effect_failure = True
        original_factory = stage.memory_consolidation_service

        def wrapped_factory(context):
            service: MemoryConsolidationService = original_factory(context)
            original_consolidate = service.consolidate

            def consolidate(**kwargs):
                nonlocal calls, first_effect_failure
                rows = _action_rows(client, "memory.consolidation.candidate")
                assert rows and rows[-1]["status"] == "executing"
                calls += 1
                result = original_consolidate(**kwargs)
                if first_effect_failure:
                    first_effect_failure = False
                    raise RuntimeError("crash_after_consolidation_effect")
                return result

            service.consolidate = consolidate
            return service

        monkeypatch.setattr(stage, "memory_consolidation_service", wrapped_factory)
        context = AppContext(app=client.app)
        state = _state("consolidation-lifecycle-run")
        _seed_exchange(client, state, "assistant-consolidation-lifecycle")
        kwargs = {
            "context": context,
            "state": state,
            "assistant_message_id": "assistant-consolidation-lifecycle",
            "assistant_answer": "The editor choice is recorded.",
            "daily_result": None,
            "diary_object_ids": (),
            "automation": _automation(slow=True),
            "policy": object(),
            "raise_errors": True,
        }
        first_actions = await stage.consolidate_slow_memory(**kwargs)
        second_actions = await stage.consolidate_slow_memory(**kwargs)

        assert calls == 1
        assert first_actions[0].action_id == second_actions[0].action_id
        assert len(_action_rows(client, "memory.consolidation.candidate")) == 1
        with sqlite3.connect(client.app.state.database.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 1
            metric_counts = dict(
                conn.execute(
                    """
                    SELECT event_type, COUNT(*)
                    FROM product_metric_events
                    WHERE event_type IN ('candidate_created', 'activated')
                    GROUP BY event_type
                    """
                ).fetchall()
            )
        assert metric_counts == {"activated": 2, "candidate_created": 1}


@pytest.mark.asyncio
async def test_slow_consolidation_partial_candidate_set_is_not_verified_as_complete(
    client_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with client_factory() as client:
        import app.services.chat_pipeline.consolidation as stage

        consolidate_calls = 0

        def factory(_context):
            service = MemoryConsolidationService(MemoryCandidateStore(client.app.state.database.path))

            def preview(**kwargs):
                return MemoryConsolidationPreview(candidate_count=2, has_sensitive_signal=False)

            def consolidate(**kwargs):
                nonlocal consolidate_calls
                consolidate_calls += 1
                candidate = service.store.create_candidate(
                    MemoryCandidateCreate(
                        memory_kind="preference",
                        memory_scope="global",
                        summary="User prefers VS Code.",
                        normalized_value="preference:editor=vs code",
                        source_track="slow_consolidation",
                        confidence=0.7,
                        importance=0.7,
                    )
                )
                service.store.add_evidence(
                    MemoryEvidenceCreate(
                        candidate_id=candidate.id,
                        source_type="chat_message",
                        source_text="My favorite editor is VS Code.",
                        source_excerpt="My favorite editor is VS Code.",
                        conversation_id=str(kwargs.get("conversation_id") or ""),
                        message_id=str(kwargs.get("user_message_id") or ""),
                        agent_run_id=str(kwargs.get("agent_run_id") or ""),
                        confidence=0.7,
                    )
                )
                raise RuntimeError("crash_after_first_consolidation_candidate")

            service.preview = preview
            service.consolidate = consolidate
            return service

        monkeypatch.setattr(stage, "memory_consolidation_service", factory)
        context = AppContext(app=client.app)
        state = _state("consolidation-partial-run")
        _seed_exchange(client, state, "assistant-consolidation-partial")

        with pytest.raises(RuntimeError):
            await stage.consolidate_slow_memory(
                context=context,
                state=state,
                assistant_message_id="assistant-consolidation-partial",
                assistant_answer="The editor choice and project context are recorded.",
                daily_result=None,
                diary_object_ids=(),
                automation=_automation(slow=True),
                policy=object(),
                raise_errors=True,
            )

        assert consolidate_calls == 1
        rows = _action_rows(client, "memory.consolidation.candidate")
        assert len(rows) == 1
        assert rows[0]["status"] == "failed_recovery"
        with sqlite3.connect(client.app.state.database.path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM memory_candidates").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM memory_evidence").fetchone()[0] == 1
