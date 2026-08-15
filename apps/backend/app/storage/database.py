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


class MigrationRunner:
    _ADD_COLUMN_RE = re.compile(
        r"^\s*ALTER\s+TABLE\s+(?P<table>[\"`\[]?\w+[\"`\]]?)\s+ADD\s+COLUMN\s+(?P<column>[\"`\[]?\w+[\"`\]]?)\b",
        re.IGNORECASE,
    )
    _DUPLICATE_COLUMN_RE = re.compile(r"duplicate column name:\s*(?P<column>\w+)", re.IGNORECASE)

    def __init__(self, database: Database, migrations_dir: str | Path | None = None) -> None:
        self.database = database
        self.migrations_dir = Path(migrations_dir) if migrations_dir else self._default_dir()

    def apply(self) -> list[str]:
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
                with conn:
                    try:
                        conn.executescript(script)
                    except sqlite3.OperationalError as exc:
                        if not self._has_duplicate_column_error(exc):
                            raise
                        self._apply_script_allowing_duplicate_columns(conn, script)
                    conn.execute(
                        "INSERT INTO schema_migrations(version) VALUES (?)",
                        (version,),
                    )
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

    def _apply_script_allowing_duplicate_columns(self, conn: sqlite3.Connection, script: str) -> None:
        for statement in self._split_sql_statements(script):
            try:
                conn.execute(statement)
            except sqlite3.OperationalError as exc:
                if not self._is_duplicate_add_column_error(exc, statement):
                    raise

    def _is_duplicate_add_column_error(self, exc: sqlite3.OperationalError, statement: str) -> bool:
        duplicate = self._DUPLICATE_COLUMN_RE.search(str(exc))
        add_column = self._ADD_COLUMN_RE.match(statement)
        if duplicate is None or add_column is None:
            return False
        return self._normalize_identifier(add_column.group("column")) == duplicate.group("column").casefold()

    def _has_duplicate_column_error(self, exc: sqlite3.OperationalError) -> bool:
        return self._DUPLICATE_COLUMN_RE.search(str(exc)) is not None

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
