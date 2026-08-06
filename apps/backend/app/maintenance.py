from __future__ import annotations

import argparse
from pathlib import Path

from app.config import get_settings
from app.storage.database import Database, MigrationRunner


def purge_deleted_content(database_path: str | Path) -> None:
    """Securely reclaim freed SQLite pages as an explicit operator action."""
    MigrationRunner(Database(database_path)).purge_deleted_content()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agent Pet backend maintenance commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    purge = subparsers.add_parser(
        "purge-deleted-content",
        help="checkpoint WAL, enable secure_delete, and VACUUM the SQLite database",
    )
    purge.add_argument(
        "--database",
        type=Path,
        default=None,
        help="SQLite path; defaults to AGENT_PET_SQLITE_PATH",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "purge-deleted-content":
        database_path = args.database or get_settings().sqlite_path
        purge_deleted_content(database_path)
        print(f"Purged deleted SQLite content: {database_path}")
        return 0
    raise AssertionError(f"Unhandled maintenance command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
