"""Export the FastAPI OpenAPI schema to a canonical, committed JSON file.

``apps/backend/openapi.json`` is the single source of truth that downstream
consumers derive from instead of hand-maintaining parallel route lists:

- the desktop renderer's generated API types and the versioned Electron proxy
  route artifact (``npm run generate:api-contracts`` in ``apps/desktop``),
  with renderer-only exclusions in the explicit proxy exemption document.

Usage (from ``apps/backend``, inside the project environment)::

    python -m app.openapi_export
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "openapi.json"


def canonical_openapi_json() -> str:
    """Render the current app's OpenAPI schema as deterministic JSON."""
    # App construction initializes storage-backed services. Contract
    # generation must never migrate, lock, or otherwise depend on a user's
    # live database, so force an isolated disposable data directory.
    with _isolated_openapi_environment():
        # Imported lazily so this module stays importable without FastAPI
        # installed (e.g. for tooling that only needs DEFAULT_OUTPUT).
        from app.config import get_settings

        get_settings.cache_clear()
        try:
            from app.main import create_app

            schema = create_app().openapi()
        finally:
            get_settings.cache_clear()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


@contextmanager
def _isolated_openapi_environment() -> Iterator[None]:
    names = ("AGENT_PET_DATA_DIR", "AGENT_PET_SQLITE_PATH")
    previous = {name: os.environ.get(name) for name in names}
    with TemporaryDirectory(prefix="agent-pet-openapi-", ignore_cleanup_errors=True) as temp_dir:
        os.environ["AGENT_PET_DATA_DIR"] = temp_dir
        os.environ.pop("AGENT_PET_SQLITE_PATH", None)
        try:
            yield
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


def export(path: Path = DEFAULT_OUTPUT) -> Path:
    path.write_text(canonical_openapi_json(), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    target = export()
    print(f"OpenAPI schema written to {target}")
