"""Export the FastAPI OpenAPI schema to a canonical, committed JSON file.

``apps/backend/openapi.json`` is the single source of truth that downstream
consumers derive from instead of hand-maintaining parallel route lists:

- the desktop renderer's generated API types
  (``npm run generate:api-types`` in ``apps/desktop``), replacing the
  hand-written mirror in ``src/types.ts`` over time;
- future tooling for the Electron proxy allowlist (fix backlog item #9).

``tests/test_openapi_snapshot.py`` fails whenever the committed file lags
behind the code, so route/model changes force a regeneration commit and the
drift becomes visible in review diffs.

Usage (from ``apps/backend``, inside the project environment)::

    python -m app.openapi_export

or from the repo root::

    ./scripts/generate-openapi.ps1
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "openapi.json"


def canonical_openapi_json() -> str:
    """Render the current app's OpenAPI schema as deterministic JSON."""
    # Imported lazily so this module stays importable without FastAPI
    # installed (e.g. for tooling that only needs DEFAULT_OUTPUT).
    from app.main import create_app

    schema = create_app().openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def export(path: Path = DEFAULT_OUTPUT) -> Path:
    path.write_text(canonical_openapi_json(), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    target = export()
    print(f"OpenAPI schema written to {target}")
