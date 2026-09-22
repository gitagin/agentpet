"""阶段 D 固定题集的语料构建器(设计 §1.1 的 vault_fixture 变体)。

每个变体都在同一套基础语料上叠加一种状态,供评测驱动按题集要求构造 vault。
复用 tests/test_wiki_workflows 的既有测试基建(_workflow_service / 真实 ingest 链路),
不新造编译或写入路径。
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import NamedTuple

from app.models.wiki import (
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.storage.database import Database
from tests.test_wiki_workflows import _workflow_service

# 基础语料(与题集 golden 的路径严格对应)
ALPHA_PATH = "Wiki/Sources/Supplier-Alpha.md"
EAST_PATH = "Wiki/Sources/Region-East.md"
SOUTH_PATH = "Wiki/Sources/Region-South.md"
BETA_PATH = "Wiki/Sources/Supplier-Beta.md"
PRODUCT_PATH = "Wiki/Concepts/Product-P.md"
ALT_PATH = "Wiki/Sources/Supplier-Alpha-Alt.md"
LONG_PATH = "Wiki/Sources/Supplier-Long.md"
REVOKED_PATH = "Wiki/Sources/Supplier-Alpha-Revoked.md"

BASE_SOURCES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "Supplier-Alpha",
        "# Supplier-Alpha\n\n标准交货周期为 14 天。\n\n结算方式为月结 30 天。"
        "\n\n不支持加急发货。\n\n旺季(11 月至次年 1 月)顺延 7 天。\n\n[[Product-P]]",
        ("Product-P",),
    ),
    ("Region-East", "# Region-East\n\n华东区交货周期为 14 天。\n\n结算方式为月结 30 天。\n\n不支持加急。", ()),
    ("Region-South", "# Region-South\n\n华南区交货周期为 21 天。\n\n结算方式为预付 50%。\n\n支持加急。", ()),
    ("Supplier-Beta", "# Supplier-Beta\n\nBeta 是产品 P 的替代供应商。", ()),
    # 第二跳页:链接目标概念页在无模型时是占位内容,不能承载事实;
    # 这里额外摄入一条真实来源,使「两跳 A+B」在脚本模式下可验证。
    ("Product-P", "# Product-P\n\nProduct-P 由 Supplier-Alpha 供应。\n\nProduct-P 的标准交货周期为 14 天。", ()),
    ("Filler-1", "# Filler-1\n\n供应商背景材料 1:交货周期相关的弱相关补充说明。", ()),
    ("Filler-2", "# Filler-2\n\n供应商背景材料 2:交货周期相关的弱相关补充说明。", ()),
    ("Filler-3", "# Filler-3\n\n供应商背景材料 3:交货周期相关的弱相关补充说明。", ()),
    ("Filler-4", "# Filler-4\n\n供应商背景材料 4:交货周期相关的弱相关补充说明。", ()),
    ("Filler-5", "# Filler-5\n\n供应商背景材料 5:交货周期相关的弱相关补充说明。", ()),
    ("Filler-6", "# Filler-6\n\n供应商背景材料 6:交货周期相关的弱相关补充说明。", ()),
    ("Filler-7", "# Filler-7\n\n供应商背景材料 7:交货周期相关的弱相关补充说明。", ()),
    ("Filler-8", "# Filler-8\n\n供应商背景材料 8:交货周期相关的弱相关补充说明。", ()),
)

# mixed_freshness 变体:仅此来源为 verified,使其成为候选里唯一 fresh 的页。
MIXED_FRESHNESS_VERIFIED = ("Filler-7",)

VARIANTS = (
    "published", "wiki_missing", "raw_updated", "conflict", "oversized",
    "revoked", "forgotten", "quarantined", "assistant_summary",
    "mixed_freshness",
)


class Corpus(NamedTuple):
    database: Database
    vault_root: Path
    service: object


def build_corpus(variant: str, root: Path) -> Corpus:
    """按变体名构建 vault;未知变体立即失败,不静默降级。"""
    if variant not in VARIANTS:
        raise ValueError(f"unknown vault_fixture: {variant!r}")
    database = Database(root / "state.sqlite3")
    vault_root = root / "Vault"
    service = _workflow_service(database, vault_root)
    for title, content, links in BASE_SOURCES:
        # mixed_freshness:只让排在候选第 9 位的页为 verified(fresh),
        # 其余保持 unverified(unknown) —— 这是第九页准入可触发的必要条件:
        # 额外候选须在**新鲜度维度**上占优(score×1.0 > 最低held×0.6)。
        verified = True if variant != "mixed_freshness" else title in MIXED_FRESHNESS_VERIFIED
        _ingest(service, title=title, content=content, links=links, verified=verified)
    if variant == "wiki_missing":
        _write_note(
            vault_root, "Notes/Suppliers.md",
            "# 供应商笔记\n\nGamma 在笔记中有提及,但尚未整理进 Wiki。\n",
            database=database,
        )
    elif variant == "raw_updated":
        _touch_raw_content(database, ALPHA_PATH)
    elif variant == "conflict":
        _ingest(service, title="Supplier-Alpha-Alt", content="# Supplier-Alpha-Alt\n\n另一份资料称交货周期为 21 天。", links=())
    elif variant == "oversized":
        _ingest(service, title="Supplier-Long", content=_long_source(), links=())
    elif variant == "revoked":
        _ingest(service, title="Supplier-Alpha-Revoked", content="# Supplier-Alpha-Revoked\n\n已撤销来源:交货周期为 14 天。", links=())
        _set_binding(database, REVOKED_PATH, status="active", revoked=True)
    elif variant == "forgotten":
        _ingest(service, title="Supplier-Alpha-Revoked", content="# Supplier-Alpha-Revoked\n\n已遗忘来源:交货周期为 14 天。", links=())
        _set_binding(database, REVOKED_PATH, status="forgotten", revoked=False)
    elif variant == "quarantined":
        _ingest(service, title="Supplier-Alpha-Revoked", content="# Supplier-Alpha-Revoked\n\n待核验来源:结算方式为月结 30 天。", links=())
        _set_binding(database, REVOKED_PATH, status="quarantined", revoked=False)
    elif variant == "assistant_summary":
        _write_note(
            vault_root, "Wiki/Companion/Summaries/Alpha.md",
            "# 助手摘要\n\n## 来源摘要\n\n助手称交货周期为 14 天。\n",
        )
    return Corpus(database=database, vault_root=vault_root, service=service)


def _ingest(service, *, title: str, content: str, links: tuple[str, ...], verified: bool = True) -> None:
    preview = service.preview_ingest(
        WikiIngestPreviewRequest(title=title, content=content, links=list(links), max_pages=3)
    )
    confirmed = service.confirm_ingest(
        WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True)
    )
    if verified:
        # 在 review/apply 之前写入验证状态,使 apply 捕获的依赖戳带上它
        # (与 test_phase_c_query_node 的 published_with_source_state 同口径)。
        with service.database.session() as conn:
            conn.execute(
                "UPDATE wiki_sources SET verification_status = ?, verified_at = ? WHERE id = ?",
                ("verified", "2026-09-20T00:00:00Z", confirmed.source_id),
            )
            conn.commit()
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
    applied = service.apply_ingest(
        WikiIngestApplyRequest(
            run_id=confirmed.run_id,
            approved_targets=[plan.target_path for plan in confirmed.page_plans],
            review_id=review.review_id,
            review_acknowledged=True,
        )
    )
    if applied.status != "applied":
        raise RuntimeError(f"ingest {title!r} did not apply: {applied.status}")


def _long_source() -> str:
    body = "".join(f"\n\n## 章节 {index}\n\n补充说明 {index}。" for index in range(1, 40))
    return "# Supplier-Long\n\n标准交货周期为 14 天。" + body


def _write_note(
    vault_root: Path, relative_path: str, content: str, *, database: Database | None = None
) -> None:
    path = vault_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if database is None:
        return
    # 直接落盘的文件不会自动进 notes 表,而 vault 兜底检索查的正是该表;
    # 不索引则兜底路径永远找不到这条笔记(评测会误判为「兜底不可用」)。
    from app.repositories.storage import NoteRepository, VaultRepository
    from app.storage.markdown import read_markdown

    with database.session() as conn:
        vault_id = VaultRepository(conn).upsert(
            vault_root, name=vault_root.name or "Vault"
        )
        NoteRepository(conn).replace_note(
            vault_id=vault_id, relative_path=relative_path,
            markdown=read_markdown(path), modified_at=path.stat().st_mtime,
        )
        conn.commit()


def _touch_raw_content(database: Database, relative_path: str) -> None:
    """模拟原始资料在发布之后被更新:水印应随之变化。"""
    with database.session() as conn:
        conn.execute(
            "UPDATE wiki_sources SET raw_content = raw_content || ?, updated_at = datetime('now') "
            "WHERE id IN ("
            "  SELECT r.source_id FROM wiki_workflow_runs r "
            "  JOIN wiki_workflow_page_updates u ON u.run_id = r.id "
            "  WHERE u.target_path = ?"
            ")",
            ("\n\n(资料已更新:交货周期调整为 21 天。)", relative_path),
        )
        conn.commit()


def _set_binding(database: Database, relative_path: str, *, status: str, revoked: bool) -> None:
    with database.session() as conn:
        conn.execute(
            "UPDATE wiki_page_bindings SET status = ?, revoked_at = ? WHERE wiki_relative_path = ?",
            (status, "2026-09-20T00:00:00Z" if revoked else None, relative_path),
        )
        conn.commit()
