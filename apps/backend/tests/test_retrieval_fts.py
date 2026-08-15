from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.repositories.storage import NoteRepository, VaultRepository
from app.services.retrieval import RetrievalService
from app.services.vector_index import LangChainQdrantVectorIndex, VectorIndexConfig
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import parse_markdown


def test_rebuild_index_and_search_returns_citation_fields(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# Memory\n\nAlpha keyword lives here.", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))

    rebuild = service.rebuild_index(vault_id)
    response = service.search(vault_id=vault_id, query="keyword", top_k=5)

    assert rebuild.status == "success"
    assert rebuild.files_seen == 1
    assert response.results
    assert response.results[0].relative_path == "Memory.md"
    assert "keyword" in response.results[0].snippet


def test_replace_note_keeps_chunks_and_fts_transactionally_consistent(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    MigrationRunner(db).apply()
    with db.connect() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(tmp_path / "vault")
        repo = NoteRepository(conn)

        repo.replace_note(
            vault_id=vault_id,
            relative_path="Memory.md",
            markdown=parse_markdown("# Old\n\nalpha", fallback_title="Memory"),
            modified_at=1.0,
        )
        repo.replace_note(
            vault_id=vault_id,
            relative_path="Memory.md",
            markdown=parse_markdown("# New\n\nbeta", fallback_title="Memory"),
            modified_at=2.0,
        )

        chunk_count = conn.execute("SELECT count(*) FROM note_chunks").fetchone()[0]
        fts_count = conn.execute("SELECT count(*) FROM note_fts").fetchone()[0]
        alpha_count = conn.execute("SELECT count(*) FROM note_fts WHERE note_fts MATCH 'alpha'").fetchone()[0]
        beta_count = conn.execute("SELECT count(*) FROM note_fts WHERE note_fts MATCH 'beta'").fetchone()[0]

    assert chunk_count == fts_count == 1
    assert alpha_count == 0
    assert beta_count == 1


def test_rebuild_index_removes_deleted_markdown_from_search(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    stale = vault / "Old.md"
    current = vault / "Current.md"
    stale.write_text("# Old\n\nstale-keyword", encoding="utf-8")
    current.write_text("# Current\n\ncurrent-keyword", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    stale.unlink()
    rebuild = service.rebuild_index(vault_id)

    assert rebuild.status == "success"
    assert service.search(vault_id=vault_id, query="stale-keyword", top_k=5).results == []
    current_results = service.search(vault_id=vault_id, query="current-keyword", top_k=5).results
    assert current_results
    assert current_results[0].relative_path == "Current.md"


def test_search_treats_punctuation_as_user_text(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# Memory\n\nalpha beta", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query='alpha )*"', top_k=5)

    assert response.results


def test_search_requires_query_identifiers_in_authoritative_evidence(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Unrelated.md").write_text(
        "# Inventory\n\nPrior inventory content must not satisfy an unrelated identifier.",
        encoding="utf-8",
    )
    (vault / "Matching.md").write_text(
        "# Incident\n\nThe local incident reference is OBSIDIAN-NEBULA-404.",
        encoding="utf-8",
    )
    service = RetrievalService(Database(tmp_path / "app.db"))
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    matching = service.search(
        vault_id=vault_id,
        query="Return OBSIDIAN-NEBULA-404",
        top_k=5,
    )
    unsupported = service.search(
        vault_id=vault_id,
        query="Invent a citation for PHANTOM-EDGE-004",
        top_k=5,
    )

    assert [result.relative_path for result in matching.results] == ["Matching.md"]
    assert unsupported.results == []


def test_search_falls_back_to_substring_for_chinese_phrases(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text(
        "# 中文记忆\n\n我喜欢使用桌面记忆助手管理本地知识库。",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="桌面记忆助手", top_k=5)

    assert response.results
    assert response.results[0].relative_path == "Memory.md"
    assert "[桌面记忆助手]" in response.results[0].snippet


def test_search_normalizes_english_question_to_significant_terms(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "People.md").write_text(
        "# Ada\n\nAda prefers concise status updates.",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(
        vault_id=vault_id,
        query="What does the vault say about Ada preference?",
        top_k=5,
    )

    assert response.results
    assert response.results[0].relative_path == "People.md"
    assert "Ada" in response.results[0].snippet


def test_search_normalizes_chinese_question_to_preference_synonyms(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "People.md").write_text(
        "# Ada\n\nAda 喜欢简洁状态更新。",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="Ada 有什么偏好？", top_k=5)

    assert response.results
    assert response.results[0].relative_path == "People.md"
    assert "喜欢" in response.results[0].snippet


def test_search_handles_colloquial_chinese_preference_question_with_citation_metadata(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    memory_dir = vault / "Memories" / "LongTerm"
    memory_dir.mkdir(parents=True)
    (memory_dir / "Profile.md").write_text(
        "# 个人偏好\n\n用户喜欢简洁的状态更新，也偏好可追溯的来源说明。",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="我之前是不是说过自己喜欢什么样的更新？", top_k=5)

    assert response.results
    result = response.results[0]
    assert result.relative_path == "Memories/LongTerm/Profile.md"
    assert result.source_scope == "personal_memory"
    assert result.retrieval_mode == "fts"
    assert "喜欢" in result.snippet


def test_search_source_scope_filters_and_sanitizes_daily_chat(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    daily_path = vault / "Memories" / "Daily" / "2026" / "05" / "\u7b2c1\u5468_05-01\u81f305-07" / "\u661f\u671f\u65e5"
    daily_path.mkdir(parents=True)
    (daily_path / "2026-05-03.md").write_text(
        "# 2026-05-03 \u804a\u5929\u8bb0\u5fc6\n\n"
        "## 12:00:00\n\n"
        "- \u7528\u6237\u95ee\u9898\uff1a`5\u67083\u65e5\u6211\u8bf4\u4e86\u4ec0\u4e48`\n"
        "- \u684c\u5ba0\u56de\u7b54\uff1a\u4f60\u8bf4\u4e86 scope-token\u3002\n"
        "- conversation_id\uff1a`conversation-secret`\n"
        "- user_message_id\uff1a`user-secret`\n"
        "- assistant_message_id\uff1a`assistant-secret`\n"
        "- agent_run_id\uff1a`run-secret`\n",
        encoding="utf-8",
    )
    old_daily_path = vault / "2026" / "05" / "\u7b2c1\u5468_05-01\u81f305-07" / "\u661f\u671f\u65e5"
    old_daily_path.mkdir(parents=True)
    (old_daily_path / "2026-05-03.md").write_text(
        "# Old Daily\n\nscope-token old root daily should be knowledge.",
        encoding="utf-8",
    )
    long_term = vault / "Memories" / "LongTerm"
    long_term.mkdir(parents=True)
    (long_term / "Preferences.md").write_text(
        "# Preferences\n\nscope-token confirmed preference.",
        encoding="utf-8",
    )
    (vault / "Knowledge.md").write_text("# Knowledge\n\nscope-token knowledge note.", encoding="utf-8")
    (vault / "Inbox").mkdir()
    (vault / "Inbox" / "Pending Memories.md").write_text(
        "# Pending\n\nscope-token pending memory.",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    daily = service.search(vault_id=vault_id, query="scope-token", top_k=5, source_scope="daily_chat")
    knowledge = service.search(vault_id=vault_id, query="scope-token", top_k=5, source_scope="knowledge_base")
    personal = service.search(vault_id=vault_id, query="scope-token", top_k=5, source_scope="personal_memory")
    mixed = service.search(vault_id=vault_id, query="scope-token", top_k=10, source_scope="all")

    assert [result.source_scope for result in daily.results] == ["daily_chat"]
    assert "conversation_id" not in daily.results[0].snippet
    assert "agent_run_id" not in daily.results[0].snippet
    assert "Memories/Daily" in daily.results[0].relative_path
    assert all(not result.relative_path.startswith("2026/") for result in daily.results)
    assert [result.relative_path for result in knowledge.results] == ["Knowledge.md"]
    assert [result.relative_path for result in personal.results] == ["Memories/LongTerm/Preferences.md"]
    assert all(result.relative_path != "Inbox/Pending Memories.md" for result in mixed.results)
    assert all(not result.relative_path.startswith("2026/") for result in mixed.results)


def test_daily_chat_date_query_matches_daily_file_even_without_keyword_overlap(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    daily_path = vault / "Memories" / "Daily" / "2026" / "05" / "\u7b2c1\u5468_05-01\u81f305-07" / "\u661f\u671f\u4e00"
    daily_path.mkdir(parents=True)
    (daily_path / "2026-05-04.md").write_text(
        "# 2026-05-04 \u804a\u5929\u8bb0\u5fc6\n\n"
        "## 01:38:46\n\n"
        "- \u7528\u6237\u95ee\u9898\uff1a\u6211\u559c\u6b22\u82f9\u679c\n"
        "- \u684c\u5ba0\u56de\u7b54\uff1a\u6211\u4e5f\u559c\u6b22\u82f9\u679c\u3002\n"
        "- conversation_id\uff1a`conversation-secret`\n"
        "- agent_run_id\uff1a`run-secret`\n",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="我在5月4号说了什么事情吗", top_k=5, source_scope="daily_chat")

    assert response.results
    assert response.results[0].relative_path.endswith("2026-05-04.md")
    assert response.results[0].source_scope == "daily_chat"
    assert "我喜欢苹果" in response.results[0].snippet
    assert "conversation_id" not in response.results[0].snippet
    assert "agent_run_id" not in response.results[0].snippet


@pytest.mark.parametrize("mode", ["fts", "hybrid", "vector"])
def test_relative_date_query_uses_shanghai_day_and_only_returns_that_daily_file(
    tmp_path: Path,
    mode: str,
) -> None:
    vault = tmp_path / "vault"
    for day, topic in ((5, "旅行计划"), (6, "我昨天和你聊了什么")):
        daily_path = vault / "Memories" / "Daily" / "2026" / "08" / "第1周_08-01至08-07" / f"星期{day}"
        daily_path.mkdir(parents=True)
        (daily_path / f"2026-08-{day:02d}.md").write_text(
            f"# 2026-08-{day:02d} 聊天记忆\n\n- 用户问题：{topic}\n- 桌宠回答：已记录。\n",
            encoding="utf-8",
        )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(
        vault_id=vault_id,
        query="我昨天和你聊了什么",
        top_k=5,
        source_scope="daily_chat",
        mode=mode,
        now=datetime(2026, 8, 5, 17, 0, tzinfo=timezone.utc),
    )

    assert response.results
    assert {
        result.relative_path for result in response.results
    } == {"Memories/Daily/2026/08/第1周_08-01至08-07/星期5/2026-08-05.md"}
    assert "旅行计划" in response.results[0].snippet


@pytest.mark.parametrize("mode", ["fts", "hybrid", "vector"])
def test_date_constrained_daily_chat_honors_top_k_and_supports_a_larger_route_budget(
    tmp_path: Path,
    mode: str,
) -> None:
    vault = tmp_path / "vault"
    daily_path = vault / "Memories" / "Daily" / "2026" / "08" / "第1周_08-01至08-07" / "星期三"
    daily_path.mkdir(parents=True)
    conversations = [
        f"## 1{index}:00:00\n\n- 用户问题：当天话题{index}\n- 桌宠回答：当天回答{index}。"
        for index in range(1, 8)
    ]
    (daily_path / "2026-08-05.md").write_text(
        "# 2026-08-05 聊天记忆\n\n" + "\n\n".join(conversations) + "\n",
        encoding="utf-8",
    )
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    limited = service.search(
        vault_id=vault_id,
        query="我昨天和你聊了什么",
        top_k=5,
        source_scope="daily_chat",
        mode=mode,
        now=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
    )
    complete = service.search(
        vault_id=vault_id,
        query="我昨天和你聊了什么",
        top_k=20,
        source_scope="daily_chat",
        mode=mode,
        now=datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc),
    )

    combined_snippets = "\n".join(result.snippet for result in complete.results)
    assert len(limited.results) == 5
    assert len(complete.results) >= 7
    assert len(complete.results) <= 20
    assert all(f"当天话题{index}" in combined_snippets for index in range(1, 8))
    assert complete.metadata["fusion"]["selected_count"] == len(complete.results)


def test_hybrid_search_falls_back_to_fts_when_vector_index_unavailable(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# Memory\n\nfallback-vector-keyword", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="fallback-vector-keyword", top_k=5, mode="hybrid")

    assert response.results
    assert response.results[0].retrieval_mode == "fts"
    assert response.metadata["retrieval_mode"] == "hybrid"
    assert response.metadata["vector_available"] is False


def test_hybrid_search_reports_vector_unavailable_reason(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# Memory\n\nmissing-key-vector-fallback", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    vector_index = LangChainQdrantVectorIndex(
        VectorIndexConfig(
            enabled=False,
            root_path=tmp_path / "vector-index",
            collection_name="test_collection",
            embedding_model="test-embedding",
            unavailable_reason="embedding_api_key_missing",
        )
    )
    service = RetrievalService(db, vector_index=vector_index)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="missing-key-vector-fallback", top_k=5, mode="hybrid")

    assert response.results
    assert response.results[0].retrieval_mode == "fts"
    assert response.metadata["vector_available"] is False
    assert response.metadata["vector_unavailable_reason"] == "embedding_api_key_missing"


class RecordingVectorStore:
    def __init__(self) -> None:
        self.add_documents_called = False

    def delete(self, *, ids) -> None:
        raise RuntimeError("delete failed")

    def add_documents(self, *, documents, ids) -> None:
        self.add_documents_called = True


class DeleteFailingVectorIndex(LangChainQdrantVectorIndex):
    def __init__(self, store: RecordingVectorStore, root_path: Path) -> None:
        super().__init__(
            VectorIndexConfig(
                enabled=True,
                root_path=root_path,
                collection_name="test_collection",
                embedding_model="test-embedding",
                embeddings=object(),
            )
        )
        self.store = store

    def _store(self):
        return self.store

    def _document(self, *, page_content: str, metadata: dict):
        return {"page_content": page_content, "metadata": metadata}


def test_vector_upsert_stops_before_add_documents_when_delete_fails(tmp_path: Path) -> None:
    store = RecordingVectorStore()
    index = DeleteFailingVectorIndex(store, tmp_path / "vector-index")

    with pytest.raises(RuntimeError, match="delete failed"):
        index.upsert_markdown(
            vault_id="vault-1",
            note_id="note-1",
            relative_path="Memory.md",
            markdown=parse_markdown("# Memory\n\nalpha beta", fallback_title="Memory"),
        )

    assert store.add_documents_called is False
