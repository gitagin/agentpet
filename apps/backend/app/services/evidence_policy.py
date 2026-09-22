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


# 两轴正交(设计 docs/source-identity-migration-design.md:198-206)：
#   1. 陈述权威轴(谁说的)：用户陈述 > 外部来源；
#   2. 事实范畴轴(关于什么)：偏好类 vs 外部事实类。
# 用户对自己的偏好/身份等有唯一权威；用户转述的外部事实只权威于「用户确实说过这话」，
# 既不赋予外部事实权威，也不与外部来源互相覆盖(冲突时保留双方声明)。
_USER_AUTHORITY_CATEGORIES = frozenset(
    {"preference", "identity", "relationship", "health", "crisis"}
)


def _normalized_category(content_category: object) -> str:
    return str(content_category or "").strip().casefold()


def statement_authority(
    kind: ProvenanceKind | None, content_category: object = None
) -> str:
    """陈述权威轴的取值：user | external | mixed。

    只描述「谁对这条主张有权威」，不授予读取权限，也不判定事实真假。
    """
    if kind is ProvenanceKind.USER_STATEMENT:
        if _normalized_category(content_category) in _USER_AUTHORITY_CATEGORIES:
            return "user"
        return "mixed"
    return "external"


def user_statement_overrides_external(
    kind: ProvenanceKind | None, content_category: object = None
) -> bool:
    """偏好类用户陈述是否优先于外部来源。

    仅偏好类(用户对自己的偏好/身份/关系/健康/危机)成立——此时用户是唯一权威，
    外部来源不能「纠正」用户偏好；外部事实类一律返回 False(保留双方声明)。
    """
    return (
        kind is ProvenanceKind.USER_STATEMENT
        and _normalized_category(content_category) in _USER_AUTHORITY_CATEGORIES
    )


_STATEMENT_AUTHORITY_ORDER = {"user": 0, "mixed": 1, "external": 2}


def statement_authority_of(source_type: object, content_category: object) -> str:
    """两轴汇合点:由**已记录**的来源标签与事实范畴推出陈述权威。

    source_type 是写入期记录的原始 ingress 标签(不是派生结论);
    缺失/未知标签经 source_provenance_kind() 归一为 None,此时权威轴保守判 external。
    """
    kind = source_provenance_kind(None if source_type is None else str(source_type))
    return statement_authority(kind, content_category)


def statement_authority_order(authority: object) -> int:
    """权威排序键:user(0) < mixed(1) < external(2);未知值排最后(3)。

    只决定**稳定排序**的相对次序。不授予读取权限,不判定事实真假,
    也不改变任何准入集合——排序永远不是权限决定。
    """
    return _STATEMENT_AUTHORITY_ORDER.get(str(authority or "").strip().casefold(), 3)


def statement_authority_sort_key(item: object) -> int:
    """给带 source_type/content_category 的检索结果算权威排序键。

    故意鸭子类型(不 import 结果模型):证据门与提示词组装层都要用同一个键,
    而它们分属不同层,不该为此互相依赖。缺属性一律按未知处理(排最后)。
    """
    return statement_authority_order(
        statement_authority_of(
            getattr(item, "source_type", None),
            getattr(item, "content_category", None),
        )
    )


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
