from __future__ import annotations

from pathlib import Path

from app.repositories.storage import NoteRepository, VaultRepository, _bigram_cjk, _to_fts_query
from app.services.fts_bigram_backfill import BACKFILL_MARKER, ensure_bigram_fts
from app.services.retrieval import RetrievalService
from app.storage.database import Database, MigrationRunner
from app.storage.markdown import parse_markdown


def test_bigram_cjk_splits_long_runs_and_preserves_short_words() -> None:
    assert _bigram_cjk("我喜欢牛奶") == " 我喜 喜欢 欢牛 牛奶 "
    assert _bigram_cjk("牛奶") == "牛奶"
    assert _bigram_cjk("BDV 变压器 test") == "BDV  变压 压器  test"
    assert _bigram_cjk("plain english") == "plain english"


def test_fts_query_bigrams_chinese_but_keeps_latin_tokens() -> None:
    assert _to_fts_query("我喜欢牛奶") == '"我喜" "喜欢" "欢牛" "牛奶"'


def test_chinese_substring_search_hits_with_bigram_index(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# 记忆\n\n我喜欢牛奶，每天一杯。", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="牛奶", top_k=5)

    assert response.results
    assert "[牛奶]" in response.results[0].snippet  # 高亮落在原词上，且展示原始文本而非 bigram


def test_retrieval_cache_hits_on_identical_query_and_misses_after_write(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# 记忆\n\n我喜欢牛奶。", encoding="utf-8")
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    first = service.search(vault_id=vault_id, query="牛奶", top_k=5)
    second = service.search(vault_id=vault_id, query="牛奶", top_k=5)

    assert first.metadata.get("cache_status") is None
    assert second.metadata["cache_status"] == "hit"

    (vault / "Memory.md").write_text("# 记忆\n\n我改喝咖啡了。", encoding="utf-8")
    service.rebuild_index(vault_id)

    after_write = service.search(vault_id=vault_id, query="牛奶", top_k=5)
    assert after_write.metadata.get("cache_status") is None


def test_identifier_query_weights_fts_channel_at_3x(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# M\n\nAPOLLO-17 checklist lives here.", encoding="utf-8")
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="APOLLO-17 是什么？", mode="hybrid", top_k=5)

    assert response.metadata["fusion"]["channel_weights"].get("fts") == 3.0


def test_ordinary_query_keeps_equal_channel_weights(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    service = RetrievalService(db)
    service.initialize()
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Memory.md").write_text("# M\n\n我喜欢喝牛奶。", encoding="utf-8")
    vault_id = service.bind_vault(str(vault))
    service.rebuild_index(vault_id)

    response = service.search(vault_id=vault_id, query="我喜欢什么饮料", mode="hybrid", top_k=5)

    assert response.metadata["fusion"]["channel_weights"].get("fts") == 1.0


def test_backfill_rewrites_legacy_fts_rows_once(tmp_path: Path) -> None:
    db = Database(tmp_path / "app.db")
    MigrationRunner(db).apply()
    with db.session() as conn:
        with conn:
            vault_id = VaultRepository(conn).upsert(tmp_path / "vault")
            NoteRepository(conn).replace_note(
                vault_id=vault_id,
                relative_path="Legacy.md",
                markdown=parse_markdown("# 旧标题\n\n旧内容", fallback_title="Legacy"),
                modified_at=1.0,
            )
        # 模拟 bigram 改造前写入的 legacy 行：内容未 bigram
        conn.execute("DELETE FROM note_fts")
        row = conn.execute("SELECT * FROM note_chunks").fetchone()
        conn.execute(
            "INSERT INTO note_fts(chunk_id, note_id, vault_id, relative_path, title, heading, content)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(row["id"]),
                str(row["note_id"]),
                str(row["vault_id"]),
                str(row["relative_path"]),
                str(row["title"]),
                str(row["heading"] or ""),
                str(row["content"]),
            ),
        )

    ensure_bigram_fts(db)

    with db.session() as conn:
        with conn:
            fts_content = conn.execute("SELECT content FROM note_fts").fetchone()[0]
            marker = conn.execute("SELECT value FROM app_state WHERE key = ?", (BACKFILL_MARKER,)).fetchone()

    assert "旧内" in str(fts_content)
    assert marker is not None

    ensure_bigram_fts(db)
    with db.session() as conn:
        with conn:
            count = conn.execute("SELECT count(*) FROM note_fts").fetchone()[0]
    assert count == 1
