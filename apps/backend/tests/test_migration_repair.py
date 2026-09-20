from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.storage.database import Database, MigrationRunner, MigrationStatementError
from apps.backend.tests._schema import MIGRATIONS_DIR


def test_repair_migration_recreates_app_state_after_drift(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite3")
    MigrationRunner(db).apply()

    # 模拟漂移:该库是"旧 002 时代"的安装——027 从未应用(无标记),
    # 且 app_state 表缺失(旧 002 没有建这张表)。
    with db.session() as conn:
        conn.execute("DROP TABLE app_state")
        conn.execute("DELETE FROM schema_migrations WHERE version = '027_repair_missing_app_state'")

    applied = MigrationRunner(db).apply()

    assert "027_repair_missing_app_state" in applied
    with db.session() as conn:
        conn.execute("INSERT INTO app_state(key, value) VALUES ('k', 'v')")
        assert conn.execute("SELECT value FROM app_state WHERE key = 'k'").fetchone()[0] == "v"


def test_repair_migration_is_idempotent_on_healthy_databases(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite3")
    MigrationRunner(db).apply()
    again = MigrationRunner(db).apply()

    assert again == []
    with db.session() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'app_state' AND type = 'table'"
        ).fetchone()
        assert row is not None


def test_repair_migration_matches_the_drifted_schema(tmp_path: Path) -> None:
    migration = (MIGRATIONS_DIR / "027_repair_missing_app_state.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS app_state" in migration


def test_failed_migration_rolls_back_schema_data_and_marker(tmp_path: Path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_base.sql").write_text(
        "CREATE TABLE base(value TEXT); INSERT INTO base(value) VALUES ('kept');",
        encoding="utf-8",
    )
    (migrations / "002_fails.sql").write_text(
        "CREATE TABLE transient(value TEXT); INSERT INTO missing_table(value) VALUES ('rolled back');",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    runner = MigrationRunner(db, migrations_dir=migrations)
    with pytest.raises(sqlite3.OperationalError):
        runner.apply()

    with db.session() as conn:
        assert conn.execute("SELECT value FROM base").fetchone()[0] == "kept"
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'transient'"
        ).fetchone() is None
        versions = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
        assert versions == {"001_base"}


def test_foreign_key_pragma_header_is_skipped_without_losing_foreign_keys(tmp_path: Path) -> None:
    # 迁移文件普遍以 PRAGMA foreign_keys = ON 开头。事务内它是空操作,而连接本身
    # 已经开启外键,所以运行器明确跳过它——跳过比"执行一条假装生效的语句"诚实。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_base.sql").write_text(
        "PRAGMA foreign_keys = ON;\n"
        "CREATE TABLE parent(id TEXT PRIMARY KEY);\n"
        "CREATE TABLE child(id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id));\n",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    assert MigrationRunner(db, migrations_dir=migrations).apply() == ["001_base"]

    with db.session() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'child'"
        ).fetchone() is not None


@pytest.mark.parametrize(
    "pragma",
    [
        "PRAGMA journal_mode = DELETE;",
    ],
)
def test_transaction_sensitive_pragma_is_refused_loudly(tmp_path: Path, pragma: str) -> None:
    # 这类 PRAGMA 在事务内不生效。静默放过会让"表重建前关外键"这种意图悄悄失效,
    # 所以运行器直接拒绝,并让这条迁移保持未应用。
    # 注:PRAGMA foreign_keys = OFF 已移出本参数化 —— 它作为脚本首条语句时是受支持的
    # 重建类迁移机制(见 test_first_statement_foreign_keys_off_*),仅允许事务外切换;
    # 脚本中途出现仍被拒绝(test_mid_script_foreign_keys_off_is_refused_loudly)。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_needs_no_transaction.sql").write_text(
        f"{pragma}\nCREATE TABLE base(value TEXT);\n",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    with pytest.raises(MigrationStatementError):
        MigrationRunner(db, migrations_dir=migrations).apply()

    with db.session() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'base'"
        ).fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_first_statement_foreign_keys_off_applies_without_losing_foreign_keys(
    tmp_path: Path,
) -> None:
    # 重建类迁移(12 步重建表,如 035_source_identity)以 PRAGMA foreign_keys = OFF
    # 作为脚本首条语句:运行器在 BEGIN 之前关闭外键、提交/回滚后恢复,迁移正常应用,
    # 且应用后外键强制仍然生效。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_rebuild.sql").write_text(
        "-- 重建类迁移头注释\n"
        "PRAGMA foreign_keys = OFF;\n"
        "CREATE TABLE parent(id TEXT PRIMARY KEY);\n"
        "CREATE TABLE child(id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id));\n"
        "INSERT INTO parent(id) VALUES ('p1');\n"
        "INSERT INTO child(id, parent_id) VALUES ('c1', 'p1');\n",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    assert MigrationRunner(db, migrations_dir=migrations).apply() == ["001_rebuild"]

    with db.session() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM child").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO child(id, parent_id) VALUES ('c2', 'missing')")


def test_mid_script_foreign_keys_off_is_refused_loudly(tmp_path: Path) -> None:
    # 契约保留:foreign_keys pragma 不是首条语句(脚本中途出现)时仍然拒绝,
    # 避免"表重建前关外键"这种意图在事务内悄悄失效。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_rebuild.sql").write_text(
        "CREATE TABLE base(value TEXT);\nPRAGMA foreign_keys = OFF;\n",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    with pytest.raises(MigrationStatementError):
        MigrationRunner(db, migrations_dir=migrations).apply()

    with db.session() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'base'"
        ).fetchone() is None
        assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_pragmas_that_do_work_inside_a_transaction_still_run(tmp_path: Path) -> None:
    # secure_delete 这类连接级开关在事务内是生效的,不能被上面的规则误伤。
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_secure.sql").write_text(
        "PRAGMA secure_delete = ON;\nCREATE TABLE base(value TEXT);\nVACUUM;\n",
        encoding="utf-8",
    )

    db = Database(tmp_path / "state.sqlite3")
    assert MigrationRunner(db, migrations_dir=migrations).apply() == ["001_secure"]
    with db.session() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'base'"
        ).fetchone() is not None
