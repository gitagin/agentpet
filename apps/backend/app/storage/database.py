from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Callable, Iterator

# SQLite busy timeout: with WAL enabled, writers are exclusive. The stdlib
# default of 5s is too tight when background jobs and streaming writes
# overlap; 30s keeps "database is locked" errors out of normal operation.
CONNECT_TIMEOUT_SECONDS = 30.0
BUSY_TIMEOUT_MILLISECONDS = int(CONNECT_TIMEOUT_SECONDS * 1000)

_WAL_INITIALIZED_PATHS: set[str] = set()
_WAL_INITIALIZATION_LOCK = Lock()


def _database_path_key(path: str | Path) -> str:
    return str(Path(path).resolve())


def configure_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    """Apply the project-wide per-connection PRAGMA set.

    SQLite's foreign_keys flag is per-connection (default OFF), so every
    code path that opens its own connection MUST run through here —
    otherwise the same database gets two different integrity semantics.
    """
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # sqlite3.connect(timeout=...) installs a busy handler too, but make the
    # effective value explicit so connections created by callers/tests share
    # the same contention policy.
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MILLISECONDS}")
    return conn


def open_database_connection(
    db: str | Path | sqlite3.Connection,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    """Open every service-owned SQLite connection with shared semantics.

    Long-lived service objects cannot use ``Database.session()`` because they
    retain a connection across method calls. They still must share the same
    timeout, row factory, foreign-key and WAL policy. ``:memory:`` is kept as a
    real in-memory database for isolated services and tests; WAL is not
    supported for that SQLite mode.
    """
    if isinstance(db, sqlite3.Connection):
        return configure_connection(db)
    if str(db) == ":memory:":
        return configure_connection(
            sqlite3.connect(
                ":memory:",
                timeout=CONNECT_TIMEOUT_SECONDS,
                check_same_thread=check_same_thread,
            )
        )
    return Database(db).connect(check_same_thread=check_same_thread)


def _initialize_wal_mode_once(path: str | Path, conn: sqlite3.Connection) -> None:
    """Enable WAL once per database path; it is a persistent database flag."""
    key = _database_path_key(path)
    with _WAL_INITIALIZATION_LOCK:
        if key in _WAL_INITIALIZED_PATHS:
            return
        mode = str(conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]).lower()
        if mode != "wal":
            raise RuntimeError(f"SQLite WAL mode could not be enabled for {path}: {mode}")
        _WAL_INITIALIZED_PATHS.add(key)


class Database:
    def __init__(self, path: str | Path, *, on_path_access: Callable[["Database"], None] | None = None) -> None:
        self._path = Path(path)
        self._on_path_access = on_path_access

    @property
    def path(self) -> Path:
        if self._on_path_access:
            self._on_path_access(self)
        return self._path

    def connect(
        self,
        *,
        check_same_thread: bool = True,
        read_only: bool = False,
    ) -> sqlite3.Connection:
        """Open a configured connection.

        The caller owns the connection lifetime and must close it.
        Prefer session() for scoped use — sqlite3's own context manager
        only commits/rolls back and never closes, which historically
        leaked one file descriptor per call site.
        """
        if read_only:
            path = self._path.resolve(strict=True)
            conn = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro",
                uri=True,
                timeout=CONNECT_TIMEOUT_SECONDS,
                check_same_thread=check_same_thread,
            )
            return configure_connection(conn)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self._path,
            timeout=CONNECT_TIMEOUT_SECONDS,
            check_same_thread=check_same_thread,
        )
        try:
            configure_connection(conn)
            _initialize_wal_mode_once(self._path, conn)
        except BaseException:
            conn.close()
            raise
        return conn

    @contextmanager
    def session(
        self,
        *,
        check_same_thread: bool = True,
        read_only: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        """Scoped connection: commit on success, rollback on error, always close."""
        conn = self.connect(check_same_thread=check_same_thread, read_only=read_only)
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            if not read_only:
                conn.commit()
        finally:
            conn.close()


class MigrationStatementError(ValueError):
    """A migration statement cannot run inside the runner's single transaction."""


class MigrationRunner:
    _ADD_COLUMN_RE = re.compile(
        r"^\s*ALTER\s+TABLE\s+(?P<table>[\"`\[]?\w+[\"`\]]?)\s+ADD\s+COLUMN\s+(?P<column>[\"`\[]?\w+[\"`\]]?)\b",
        re.IGNORECASE,
    )
    _DUPLICATE_COLUMN_RE = re.compile(r"duplicate column name:\s*(?P<column>\w+)", re.IGNORECASE)
    # SQLite applies these only outside a transaction; inside one they are silent
    # no-ops.  A migration that carries one must be seen: either it is redundant
    # (the connection already enables foreign keys) or it needs a real table
    # rebuild, and neither may be swallowed as "ran but changed nothing".
    _CONNECTION_SATISFIED_PRAGMAS = frozenset({"foreign_keys = on"})
    _TRANSACTION_SENSITIVE_PRAGMAS = frozenset({"foreign_keys", "journal_mode"})
    # 重建类迁移(如 035_source_identity)以 PRAGMA foreign_keys = OFF 作为脚本首条语句
    # (允许前置 -- 注释行)。匹配后由 apply() 在 BEGIN 之前关闭外键、提交/回滚后恢复;
    # 事务内切换外键是静默空操作,SQLite 要求事务外切换。
    _FK_OFF_HEADER_RE = re.compile(
        r"^\s*(?:--[^\n]*\n\s*)*PRAGMA\s+foreign_keys\s*=\s*OFF\s*;",
        re.IGNORECASE,
    )

    def __init__(self, database: Database, migrations_dir: str | Path | None = None) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir) if migrations_dir else self._default_dir()

    def apply(self) -> list[str]:
        """Apply pending migrations in file order, each in its own transaction.

        Migration files are IMMUTABLE once an install may have applied them:
        editing an applied migration does not re-run on those databases (the
        version marker already exists), which silently desynchronizes schema
        from code. Fixes for shipped migrations are new forward-only repair
        migrations (e.g. 027_repair_missing_app_state.sql).

        Schema, data and the version marker share one transaction, so a
        statement that is only honored outside a transaction (``PRAGMA
        foreign_keys``, ``PRAGMA journal_mode``) is refused instead of quietly
        changing nothing.
        """
        applied: list[str] = []
        with self.database.session() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            seen = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for migration in sorted(self.migrations_dir.glob("*.sql")):
                version = migration.stem
                if version in seen:
                    continue
                script = migration.read_text(encoding="utf-8")
                statements = self._split_sql_statements(script)
                # 重建类迁移(如 035_source_identity)以 PRAGMA foreign_keys = OFF 作为
                # 脚本首条语句:SQLite 要求外键开关只能在事务外切换(事务内是空操作),故在
                # BEGIN 之前关闭、迁移提交/回滚后再恢复 —— 12 步重建表流程依赖此机制;
                # 其余位置出现 foreign_keys pragma 仍按下方策略拒绝,避免静默空操作。
                disable_fk = bool(self._FK_OFF_HEADER_RE.match(script))
                if disable_fk:
                    conn.execute("PRAGMA foreign_keys = OFF")
                    statements = [
                        s for s in statements
                        if not self._is_foreign_keys_pragma(s)
                    ]
                transactional, post_commit = self._partition_migration_statements(statements)
                try:
                    # sqlite3.Connection.executescript() commits any pending
                    # transaction before it starts.  Execute each statement
                    # ourselves so the schema/data and marker share one
                    # transaction, including migrations with compatibility
                    # ALTER TABLE statements.
                    conn.execute("BEGIN IMMEDIATE")
                    self._execute_migration_statements(conn, transactional)
                    conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES (?)",
                        (version,),
                    )
                    conn.commit()
                except BaseException:
                    conn.rollback()
                    if disable_fk:
                        conn.execute("PRAGMA foreign_keys = ON")
                    raise
                if disable_fk:
                    # 同一连接会继续执行后续迁移,必须恢复外键强制
                    conn.execute("PRAGMA foreign_keys = ON")

                # VACUUM is a database maintenance command and SQLite rejects
                # it while a transaction is active.  Run it only after the
                # migration marker is durable; a failed maintenance pass must
                # never roll back an already committed schema migration.
                for statement in post_commit:
                    conn.execute(statement)
                applied.append(version)
                # Database migrations must remain bounded and non-destructive
                # with respect to freed pages.  Secure scrubbing is exposed by
                # purge_deleted_content() as an explicit maintenance action.
        return applied

    def purge_deleted_content(self) -> None:
        """Explicit maintenance: securely scrub freed pages (checkpoint + VACUUM)."""
        with self.database.session() as conn:
            self._purge_deleted_content(conn)

    def _purge_deleted_content(self, conn: sqlite3.Connection) -> None:
        conn.commit()
        conn.execute("PRAGMA secure_delete = ON")
        journal_mode = str(conn.execute("PRAGMA journal_mode").fetchone()[0]).lower()
        if journal_mode == "wal":
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("VACUUM")
        if journal_mode == "wal":
            conn.execute("PRAGMA journal_mode = WAL")

    def _execute_migration_statements(self, conn: sqlite3.Connection, statements: list[str]) -> None:
        for statement in statements:
            pragma = self._pragma_body(statement)
            if pragma in self._CONNECTION_SATISFIED_PRAGMAS:
                # 连接本身已经满足(configure_connection 开外键):事务内执行等于空操作,
                # 这里明确跳过,而不是执行一条假装生效的语句。
                continue
            if pragma is not None and self._pragma_name(pragma) in self._TRANSACTION_SENSITIVE_PRAGMAS:
                raise MigrationStatementError(
                    f"migration statement is ignored inside a transaction: {statement.strip()}"
                )
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if not self._is_duplicate_add_column_error(exc, statement):
                    raise

    @classmethod
    def _is_foreign_keys_pragma(cls, statement: str) -> bool:
        body = cls._pragma_body(statement)
        return body is not None and cls._pragma_name(body) == "foreign_keys"

    @staticmethod
    def _pragma_body(statement: str) -> str | None:
        """Normalized body of a PRAGMA statement, or None for anything else."""
        normalized = " ".join(statement.split()).rstrip(";").casefold()
        if not normalized.startswith("pragma "):
            return None
        return normalized[len("pragma ") :].strip()

    @staticmethod
    def _pragma_name(body: str) -> str:
        return body.split("=", 1)[0].strip().split(" ", 1)[0]

    @staticmethod
    def _partition_migration_statements(statements: list[str]) -> tuple[list[str], list[str]]:
        transactional: list[str] = []
        post_commit: list[str] = []
        for statement in statements:
            keyword = statement.lstrip().split(None, 1)[0].rstrip(";").upper() if statement.strip() else ""
            if keyword == "VACUUM":
                post_commit.append(statement)
            else:
                transactional.append(statement)
        return transactional, post_commit

    def _is_duplicate_add_column_error(self, exc: sqlite3.OperationalError, statement: str) -> bool:
        duplicate = self._DUPLICATE_COLUMN_RE.search(str(exc))
        add_column = self._ADD_COLUMN_RE.match(statement)
        if duplicate is None or add_column is None:
            return False
        return self._normalize_identifier(add_column.group("column")) == duplicate.group("column").casefold()

    @staticmethod
    def _split_sql_statements(script: str) -> list[str]:
        statements: list[str] = []
        current: list[str] = []
        quote: str | None = None
        previous = ""
        for char in script:
            current.append(char)
            if char in {"'", '"'} and previous != "\\":
                quote = None if quote == char else char if quote is None else quote
            if char == ";" and quote is None:
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
            previous = char
        statement = "".join(current).strip()
        if statement:
            statements.append(statement)
        return statements

    @staticmethod
    def _normalize_identifier(identifier: str) -> str:
        return identifier.strip().strip('"`[]').casefold()

    @staticmethod
    def _default_dir() -> Path:
        return Path(__file__).resolve().parents[2] / "migrations"
