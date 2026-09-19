"""Shared lifecycle policy for evidence entering any prompt surface."""

from __future__ import annotations

import sqlite3
from enum import Enum
from pathlib import Path, PurePosixPath
from collections.abc import Mapping

from app.storage.markdown import read_markdown

INACTIVE_EVIDENCE_STATUSES = frozenset(
    {
        "candidate", "pending", "quarantined", "rejected", "archived",
        "forgotten", "sensitive_blocked", "wrong", "superseded", "reverted",
        "deleted", "inactive", "stale", "expired", "revoked", "unverified",
    }
)


class ProvenanceKind(str, Enum):
    RAW_SOURCE = "RAW_SOURCE"
    USER_STATEMENT = "USER_STATEMENT"
    COMPILED_WIKI = "COMPILED_WIKI"
    SYNTHESIS = "SYNTHESIS"
    QUERY_REPORT = "QUERY_REPORT"
    ASSISTANT_OUTPUT = "ASSISTANT_OUTPUT"


_SOURCE_PROVENANCE = {
    **dict.fromkeys(
        ("manual", "file", "folder", "url", "webpage_text", "image_asset"),
        ProvenanceKind.RAW_SOURCE,
    ),
    **dict.fromkeys(("explicit_user", "user_message"), ProvenanceKind.USER_STATEMENT),
    **dict.fromkeys(("wiki", "compiled_wiki"), ProvenanceKind.COMPILED_WIKI),
    "synthesis": ProvenanceKind.SYNTHESIS,
    **dict.fromkeys(("report", "query_report"), ProvenanceKind.QUERY_REPORT),
    **dict.fromkeys(("agent_chat", "assistant_output"), ProvenanceKind.ASSISTANT_OUTPUT),
}


def source_provenance_kind(source_type: str | None) -> ProvenanceKind | None:
    """Classify an ingress label, without granting permission or verifying truth."""
    return _SOURCE_PROVENANCE.get((source_type or "").strip().casefold())


def independent_source_rejection_reason(source_type: str | None) -> str | None:
    kind = source_provenance_kind(source_type)
    if kind is None:
        return "unknown_source_provenance"
    if kind not in {ProvenanceKind.RAW_SOURCE, ProvenanceKind.USER_STATEMENT}:
        return "derived_source_requires_verified_roots"
    return None


def derived_document_source_type(relative_path: str, frontmatter: Mapping[str, object]) -> str | None:
    normalized = "/" + relative_path.replace("\\", "/").casefold().lstrip("/")
    if "/wiki/companion/summaries/" in normalized:
        return "assistant_output"
    page_type = str(frontmatter.get("page_type") or frontmatter.get("type") or "").casefold()
    if page_type == "report":
        return "query_report"
    if frontmatter.get("wiki_id"):
        return "synthesis" if page_type in {"synthesis", "comparison"} else "compiled_wiki"
    return None


def wiki_document_rejection_reason(
    relative_path: str, frontmatter: Mapping[str, object],
) -> str | None:
    # Legacy summaries used "source"; their reserved producer path is not a root.
    normalized = relative_path.replace("\\", "/").casefold()
    if normalized.startswith("wiki/companion/summaries/"):
        return "assistant_output_requires_verified_roots"
    page_type = str(frontmatter.get("page_type") or frontmatter.get("type") or "").casefold()
    if page_type == "report" or normalized.startswith(("wiki/reports/", "wiki/companion/reports/")):
        return "derived_report_requires_verified_roots"
    return None


def inactive_evidence_status(status: str | None, excerpt: str = "") -> str | None:
    normalized = (status or "").strip().casefold()
    if normalized in INACTIVE_EVIDENCE_STATUSES:
        return normalized
    text = excerpt.casefold()
    return next(
        (value for value in sorted(INACTIVE_EVIDENCE_STATUSES) if f"status={value}" in text),
        None,
    )


def wiki_page_rejection_reason(
    conn: sqlite3.Connection, *, vault_id: str, relative_path: str,
    require_index: bool = True, expected_content_hash: str | None = None,
) -> str | None:
    """Check editable Wiki authority independently of search caches/projections.

    Search requires an aligned index; direct reads validate their captured body
    against the binding without depending on asynchronous indexing.
    This is not a snapshot lease.
    """
    normalized = relative_path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or parts[0].casefold() != "wiki":
        return None
    if any(part.startswith(".") for part in parts) or ":" in normalized:
        return "inaccessible_source_path"
    row = conn.execute(
        """SELECT b.status, b.content_hash, n.content_hash AS indexed_hash,
                  v.root_path
           FROM vaults v
           LEFT JOIN wiki_page_bindings b
             ON b.vault_id = v.id AND b.wiki_relative_path = ?
           LEFT JOIN notes n ON n.vault_id = v.id AND n.relative_path = ?
           WHERE v.id = ?""",
        (normalized, normalized, vault_id),
    ).fetchone()
    if row is None or row["status"] is None:
        return "unverified_wiki_page"
    if row["status"] != "active":
        return f"inactive_wiki_{row['status']}"
    if not row["content_hash"]:
        return "unverified_wiki_page"
    if require_index and row["content_hash"] != row["indexed_hash"]:
        return "stale_wiki_index"
    if expected_content_hash is not None and expected_content_hash != row["content_hash"]:
        return "unverified_wiki_edit"
    try:
        root = Path(row["root_path"]).resolve()
        path = (root / normalized).resolve()
        if not path.is_relative_to(root):
            return "inaccessible_source_path"
        parsed = read_markdown(path)
        if parsed.content_hash != row["content_hash"]:
            return "unverified_wiki_edit"
        return wiki_document_rejection_reason(normalized, parsed.frontmatter)
    except (OSError, ValueError, RuntimeError):
        return "unavailable_wiki_page"
    return None
