from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from app.models.wiki import WikiIngestPagePlan, WikiIngestPreviewRequest
from app.utils.hash import sha256_hex


_INGEST_INTENT_SCHEMA_VERSION = "wiki-ingest-intent.v1"


def assert_independent_ingest_source(source_type: str) -> None:
    from app.services.evidence_policy import independent_source_rejection_reason
    from .common import WikiWorkflowError

    reason = independent_source_rejection_reason(source_type)
    if reason:
        raise WikiWorkflowError(reason)


def assert_ingest_source_scope(
    conn: sqlite3.Connection, row: sqlite3.Row | None, vault_root: Path
) -> None:
    from .common import WikiWorkflowError

    if row is None:
        raise WikiWorkflowError("wiki_ingest_source_missing")
    vault = conn.execute(
        "SELECT id FROM vaults WHERE root_path = ?", (str(vault_root.resolve()),)
    ).fetchone()
    if vault is None or not row["vault_id"] or row["vault_id"] != vault["id"]:
        raise WikiWorkflowError("wiki_ingest_source_scope_unverified")


def assert_ingest_source_matches(
    row: sqlite3.Row, request: WikiIngestPreviewRequest
) -> None:
    from .common import WikiWorkflowError
    from .compiler import COMPILER_KEY

    try:
        stored_metadata = json.loads(row["metadata_json"])
    except (TypeError, ValueError) as exc:
        raise WikiWorkflowError("wiki_ingest_source_metadata_invalid") from exc
    if not isinstance(stored_metadata, dict):
        raise WikiWorkflowError("wiki_ingest_source_metadata_invalid")

    # Compiler output belongs to a run, not to the identity of its input.
    run_fields = {COMPILER_KEY, "compilation_status"}
    stored_identity = {k: v for k, v in stored_metadata.items() if k not in run_fields}
    requested_identity = {
        k: v for k, v in request.source_metadata.items() if k not in run_fields
    }
    if (
        row["source_hash"] != sha256_hex(request.content)
        or row["raw_content"] != request.content
        or row["source_type"] != request.source_type
        or row["source_uri"] != request.source_uri
        or stored_identity != requested_identity
    ):
        raise WikiWorkflowError("wiki_ingest_source_identity_conflict")


def wiki_ingest_intent_key(
    request: WikiIngestPreviewRequest,
    page_plans: Sequence[WikiIngestPagePlan],
) -> str:
    request_payload = request.model_dump(mode="json")
    content = str(request_payload.pop("content"))
    plans = []
    for plan in page_plans:
        plan_payload = plan.model_dump(mode="json")
        plan_content = str(plan_payload.pop("content"))
        plans.append({**plan_payload, "content_sha256": sha256_hex(plan_content)})
    payload = {
        "schema_version": _INGEST_INTENT_SCHEMA_VERSION,
        "request": {
            **request_payload,
            "content_sha256": sha256_hex(content),
        },
        "page_plans": plans,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256_hex(canonical)
