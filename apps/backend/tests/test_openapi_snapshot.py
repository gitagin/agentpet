"""Drift guard: the committed openapi.json must match the live schema.

Companion to ``app/openapi_export.py``. When this test is red, a route or
model changed without regenerating the snapshot — run::

    python -m app.openapi_export

from ``apps/backend`` and commit the updated ``openapi.json`` together with
the code change. Downstream consumers (generated desktop API types, and
eventually the Electron proxy allowlist) all derive from that file, so an
up-to-date snapshot is what keeps them honest.
"""

from __future__ import annotations

from app.openapi_export import DEFAULT_OUTPUT, canonical_openapi_json


def test_openapi_snapshot_exists() -> None:
    assert DEFAULT_OUTPUT.exists(), (
        "apps/backend/openapi.json is missing. Generate it with "
        "`python -m app.openapi_export` (run from apps/backend) and commit it."
    )


def test_openapi_snapshot_is_current() -> None:
    if not DEFAULT_OUTPUT.exists():  # covered by the test above
        return
    committed = DEFAULT_OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert committed == canonical_openapi_json(), (
        "apps/backend/openapi.json is stale relative to the code. Regenerate "
        "it with `python -m app.openapi_export` (run from apps/backend) and "
        "commit the update alongside your route/model change."
    )
