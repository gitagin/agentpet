"""Source identity migration acceptance tests (T4).

Red-first acceptance suite for migration 035_source_identity.sql (design:
docs/source-identity-migration-design.md).  The suite pins the post-migration
contract:  stable source_id identity independent of content hash, same-body
sources may coexist, source versions bump without identity change, and legacy
hash-only references fail closed instead of being guessed.

Every test here is expected to FAIL on the current hash-only schema/code and
PASS once the migration and v2 code paths land (T5):
- same-body coexistence tests fail because `wiki_sources.source_hash` is still
  globally UNIQUE and confirm is hash-first (wiki_ingest_source_identity_conflict
  / wiki_ingest_source_scope_unverified);
- the legacy fail-closed test fails on the UNIQUE constraint itself;
- the reference-consistency tests fail because new graph/evidence references
  still use the content hash instead of the stable source identity.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.models.wiki import (
    WikiIngestApplyRequest,
    WikiIngestConfirmRequest,
    WikiIngestPreviewRequest,
    WikiIngestReviewRequest,
)
from app.services.wiki.common import WikiWorkflowError
from app.services.wiki.memory_closure import (
    WikiMemoryClosureError,
    prepare_wiki_synthesis_authority,
)
from app.storage.database import Database
from app.utils.hash import sha256_hex
from tests.test_wiki_workflows import _workflow_service

# 中文语料：来源正文与用例标题（验收场景本体）。
SOURCE_BODY = "LLM Wiki 是一个基于来源证据的个人知识库，回答必须引用来源。"


def _enable_source_identity_v2(database):
    """Enable the v2 identity rules (design §5.1-2) through the app_state flag.

    The flag does not exist yet; T5 introduces both the setting key and its
    readers.  Writing it here keeps the suite green-ready for the v2 gate.
    """
    with database.session() as conn:
        conn.execute(
            "INSERT INTO app_state(key, value) VALUES ('source_identity_v2', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(True),),
        )


def confirm(service, preview):
    return service.confirm_ingest(
        WikiIngestConfirmRequest(preview_token=preview.preview_token, user_confirmed=True)
    )


def ingest_request(
    title: str,
    *,
    content: str = SOURCE_BODY,
    source_type: str = "manual",
    source_uri: str | None = None,
):
    return WikiIngestPreviewRequest(
        title=title, content=content, source_type=source_type,
        source_uri=source_uri, max_pages=1,
    )


def confirm_and_apply(service, request):
    """Full ingest pipeline: preview → confirm → review → apply (source page)."""
    confirmed = confirm(service, service.preview_ingest(request))
    review = asyncio.run(service.review_ingest(
        WikiIngestReviewRequest(run_id=confirmed.run_id)
    ))
    applied = service.apply_ingest(WikiIngestApplyRequest(
        run_id=confirmed.run_id,
        approved_targets=[p.target_path for p in confirmed.page_plans],
        review_id=review.review_id,
        review_acknowledged=True,
    ))
    assert applied.status == "applied"
    return confirmed, confirmed.page_plans[0].target_path


def authority(service, paths):
    with service.database.session() as conn:
        return prepare_wiki_synthesis_authority(
            conn, vault_root=service.wiki.writer.vault_root,
            target_path="Wiki/Syntheses/Combined.md", page_type="synthesis",
            title="Combined", source_paths=paths,
        )


@pytest.fixture
def service(tmp_path):
    return _workflow_service(Database(tmp_path / "state.sqlite3"), tmp_path / "Vault")


@pytest.fixture
def services(tmp_path):
    database = Database(tmp_path / "state.sqlite3")
    return (
        _workflow_service(database, tmp_path / "FirstVault"),
        _workflow_service(database, tmp_path / "OtherVault"),
    )


def test_same_body_same_vault_sources_coexist_with_independent_identity(service):
    """验收 1：相同正文、不同身份的两个来源可以共存（各自独立 source_id）。"""
    _enable_source_identity_v2(service.database)
    first = confirm(service, service.preview_ingest(
        ingest_request("知识库介绍", source_uri="source:official")
    ))
    second = confirm(service, service.preview_ingest(
        ingest_request("同名文档乙", source_uri="source:mirror")
    ))

    assert first.source_id != second.source_id
    assert first.source_hash == second.source_hash
    with service.database.session() as conn:
        rows = conn.execute(
            "SELECT id, source_hash, source_version FROM wiki_sources ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        assert {row["source_hash"] for row in rows} == {first.source_hash}
        assert all(row["source_version"] == 1 for row in rows)


def test_same_body_in_different_vaults_is_independent(services):
    """验收 2：不同 vault 的相同正文来源互不干扰、各自成立。"""
    first, other = services
    _enable_source_identity_v2(first.database)
    body = "不同仓库中的同一篇正文，身份互不干扰。"

    a = confirm(first, first.preview_ingest(
        ingest_request("仓库甲", content=body, source_uri="source:shared")
    ))
    b = confirm(other, other.preview_ingest(
        ingest_request("仓库乙", content=body, source_uri="source:shared")
    ))

    assert a.source_id != b.source_id
    assert a.source_hash == b.source_hash
    with first.database.session() as conn:
        rows = conn.execute(
            """SELECT w.id, w.vault_id, v.root_path
               FROM wiki_sources w JOIN vaults v ON v.id = w.vault_id
               ORDER BY w.id"""
        ).fetchall()
        assert len(rows) == 2
        assert {row["root_path"] for row in rows} == {
            str(first.wiki.writer.vault_root.resolve()),
            str(other.wiki.writer.vault_root.resolve()),
        }


def test_raw_source_and_user_statement_with_same_body_are_distinct(service):
    """验收 3：RAW_SOURCE 与 USER_STATEMENT 两种来源性质身份独立。"""
    _enable_source_identity_v2(service.database)
    body = "用户偏好：希望回答始终使用中文。"

    raw = confirm(service, service.preview_ingest(
        ingest_request("外部文档", content=body, source_type="manual",
                       source_uri="source:external")
    ))
    user = confirm(service, service.preview_ingest(
        ingest_request("用户陈述", content=body, source_type="explicit_user",
                       source_uri="message:2026-09-19")
    ))

    assert raw.source_id != user.source_id
    assert raw.source_hash == user.source_hash
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 2


def test_forgotten_duplicate_source_blocks_answers_while_active_one_remains(service):
    """验收 4：同正文两个来源，forgotten 的不得支持事实回答，有效的继续可用。"""
    _enable_source_identity_v2(service.database)
    body = "供应商 A 在华东区域运营。"

    first, path_a = confirm_and_apply(service, ingest_request(
        "华东供应商", content=body, source_uri="source:a"
    ))
    second, path_b = confirm_and_apply(service, ingest_request(
        "供应商同名记录", content=body, source_uri="source:b"
    ))
    assert first.source_id != second.source_id

    # 遗忘前：两个来源各自都能支撑合成事实回答。
    assert authority(service, [path_b]).evidence_ids

    # 遗忘来源乙的来源候选：乙不再可激活，甲不受影响。
    with service.database.session() as conn:
        conn.execute(
            """UPDATE memory_candidates SET status = 'forgotten'
               WHERE summary = 'Wiki source provenance'
                 AND json_extract(metadata_json, '$.source_id') = ?""",
            (second.source_id,),
        )
    with pytest.raises(WikiMemoryClosureError, match="source_candidate_not_activatable"):
        authority(service, [path_b])

    active = authority(service, [path_a])
    assert active.evidence_ids
    with service.database.session() as conn:
        forgotten_evidence = {
            row["id"] for row in conn.execute(
                """SELECT id FROM memory_evidence
                   WHERE json_extract(metadata_json, '$.source_id') = ?""",
                (second.source_id,),
            )
        }
    assert forgotten_evidence.isdisjoint(active.evidence_ids)


def test_duplicate_sources_do_not_double_count_evidence(service):
    """验收 5：重复来源不增加独立证据数量（按根来源去重）。"""
    _enable_source_identity_v2(service.database)
    body = "重复导入同一正文，证据数量按根来源去重。"

    a, path_a = confirm_and_apply(service, ingest_request(
        "重复来源甲", content=body, source_uri="source:dup-a"
    ))
    b, path_b = confirm_and_apply(service, ingest_request(
        "重复来源乙", content=body, source_uri="source:dup-b"
    ))

    only_a = authority(service, [path_a])
    only_b = authority(service, [path_b])
    combined = authority(service, [path_a, path_b])

    # 每个根来源的证据互不重叠（身份独立）。
    assert set(only_a.evidence_ids).isdisjoint(only_b.evidence_ids)
    # 并列引用只取并集，不因同正文重复计数。
    assert set(combined.evidence_ids) == set(only_a.evidence_ids) | set(only_b.evidence_ids)
    assert len(combined.evidence_ids) == len(set(combined.evidence_ids))
    assert len(combined.evidence_ids) == len(only_a.evidence_ids) + len(only_b.evidence_ids)


def test_legacy_hash_only_identity_fails_closed(service):
    """验收 6：legacy hash-only 身份无法确定时 fail closed，绝不猜成新身份。"""
    _enable_source_identity_v2(service.database)
    body = "旧数据：同正文两份来源，身份无法判定。"
    digest = sha256_hex(body)

    # 035 契约：同一 content_hash 允许多行（目前被 UNIQUE 拒绝 → 本用例为红）。
    with service.database.session() as conn:
        conn.execute(
            """INSERT INTO wiki_sources
               (id, source_hash, title, source_type, source_uri, content_preview, raw_content)
               VALUES ('legacy-a', ?, '旧来源甲', 'manual', 'source:legacy', ?, ?)""",
            (digest, body, body),
        )
        conn.execute(
            """INSERT INTO wiki_sources
               (id, source_hash, title, source_type, source_uri, content_preview, raw_content)
               VALUES ('legacy-b', ?, '旧来源乙', 'manual', 'source:legacy', ?, ?)""",
            (digest, body, body),
        )

    # 两个 legacy 行身份字段完全相同：hash 召回命中多候选且无法判定 → 拒绝，不猜测。
    preview = service.preview_ingest(ingest_request(
        "第三次导入", content=body, source_uri="source:legacy"
    ))
    with pytest.raises(
        WikiWorkflowError, match="source_identity_conflict|source_scope_unverified"
    ):
        confirm(service, preview)
    with service.database.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_sources").fetchone()[0] == 2


def test_migrated_references_are_consistent_after_apply(service):
    """验收 7：evidence / graph / synthesis 在迁移后的引用一致性。"""
    _enable_source_identity_v2(service.database)
    body = "引用一致性：证据、图关系、编译依赖都以来源身份为准。"

    first, _ = confirm_and_apply(service, ingest_request(
        "引用来源甲", content=body, source_uri="source:ref-a"
    ))
    second, _ = confirm_and_apply(service, ingest_request(
        "引用来源乙", content=body, source_uri="source:ref-b"
    ))
    identities = {first.source_id, second.source_id}

    with service.database.session() as conn:
        # 图关系 documented_in 以稳定来源身份为前缀，而不是内容哈希。
        relations = conn.execute(
            "SELECT source_text FROM memory_graph_facts WHERE relation_type = 'documented_in'"
        ).fetchall()
        assert relations
        for row in relations:
            assert row["source_text"].startswith(tuple(f"{sid}:" for sid in identities)), (
                row["source_text"]
            )
        # 证据记录携带落地时的来源身份与版本。
        evidence = conn.execute("SELECT metadata_json FROM memory_evidence").fetchall()
        assert evidence
        for row in evidence:
            meta = json.loads(row["metadata_json"])
            assert meta.get("source_id") in identities
            assert meta.get("source_version") == 1


def test_same_identity_content_change_bumps_source_version(service):
    """验收补充（设计 §1.2/§5.1-3）：身份不变、正文变化 → 同 id，source_version +1。"""
    _enable_source_identity_v2(service.database)
    original = ingest_request(
        "知识库介绍", content="LLM Wiki 是一个基于来源证据的个人知识库。",
        source_uri="source:official",
    )
    first = confirm(service, service.preview_ingest(original))
    revised = confirm(service, service.preview_ingest(original.model_copy(
        update={"content": "LLM Wiki 是一个基于来源证据的个人知识库，回答必须引用来源。"}
    )))

    assert revised.source_id == first.source_id
    assert revised.source_hash != first.source_hash
    with service.database.session() as conn:
        row = conn.execute(
            "SELECT source_hash, source_version FROM wiki_sources WHERE id = ?",
            (first.source_id,),
        ).fetchone()
        assert row["source_hash"] == revised.source_hash
        assert row["source_version"] == 2
        history = conn.execute(
            """SELECT source_version, content_hash FROM wiki_source_version_history
               WHERE source_id = ? ORDER BY source_version""",
            (first.source_id,),
        ).fetchall()
        assert len(history) == 1
        assert history[0]["source_version"] == 1
        assert history[0]["content_hash"] == first.source_hash
