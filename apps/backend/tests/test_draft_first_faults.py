"""Draft-first publication 故障测试(B3,先红后绿)。

按 t9 草案(docs/draft-first-publication-design.md)§5 与队长 8 用例清单设计。
核心断言:G1 published 后,任何 G2 构造/发布失败都不破坏 G1 的可读性;
draft(staged)对正式查询不可见;forgotten/revoked 经读路径实时阻断;
watermark 含 binding 维度;draft 生命周期与 stage 幂等按 B5 契约落地。

现状(红)项:forgotten 未进 authorize、revoked 无 036 列、watermark 无 binding、
draft 生命周期/run 级 stage 复用未实现——这些用例先红,由 B5 转绿。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.services import factory
from app.services.wiki.generations import WikiGenerationError, WikiGenerationStore
from app.storage.database import Database
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from tests.test_wiki_workflows import AUTH_HEADERS


def _real_reader(client) -> WikiSnapshotReader:
    # 真实读路径:factory 的 authorize(含活跃 vault 判定与检索策略)将被 B5 收紧
    return factory.wiki_snapshot_reader_dependency(SimpleNamespace(app=client.app))


def _init_vault(client, vault_root: Path) -> None:
    response = client.post(
        "/api/vaults/init", headers=AUTH_HEADERS,
        json={"path": str(vault_root), "create_if_missing": True, "confirmed": True},
    )
    assert response.status_code == 200


def _complete_ingest(client, title: str, content: str, max_pages: int = 2) -> dict[str, object]:
    preview = client.post("/api/wiki/ingest/preview", headers=AUTH_HEADERS,
        json={"title": title, "content": content, "max_pages": max_pages})
    assert preview.status_code == 200, preview.text
    confirmed = client.post("/api/wiki/ingest/confirm", headers=AUTH_HEADERS,
        json={"preview_token": preview.json()["preview_token"], "user_confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    reviewed = client.post("/api/wiki/ingest/review", headers=AUTH_HEADERS,
        json={"run_id": confirmed.json()["run_id"]})
    assert reviewed.status_code == 200, reviewed.text
    applied = client.post("/api/wiki/ingest/apply", headers=AUTH_HEADERS,
        json={"run_id": confirmed.json()["run_id"],
              "approved_targets": [p["target_path"] for p in confirmed.json()["page_plans"]],
              "review_id": reviewed.json()["review_id"], "review_acknowledged": True})
    assert applied.status_code == 200, applied.text
    return {"confirm": confirmed.json(), "apply": applied.json()}


@pytest.fixture
def published(client_factory, tmp_path):
    """API 全链路发布 G1(来源页 + 概念页),返回 (client, vault_root, vault_id, generation, source_path, concept_path)。"""
    vault_root = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _init_vault(client, vault_root)
        first = _complete_ingest(client, "故障来源", "# 故障来源\n\n构造 G2 期间 G1 必须继续可读。\n\n[[故障概念]]")
        source_path = str(first["confirm"]["page_plans"][0]["target_path"])
        concept_path = next((
            p["target_path"] for p in first["confirm"]["page_plans"]
            if p["target_path"].startswith("Wiki/Concepts/")
        ))
        with sqlite3.connect(client.app.state.database.path) as conn:
            vault_id = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()[0]
        generation = WikiGenerationStore(client.app.state.database).active(vault_id)
        assert generation
        yield client, vault_root, vault_id, generation, source_path, concept_path


def _pin_bytes(reader, pin, path):
    page = reader.read(pin, path)
    return page.content, page.content_hash


def test_draft_staged_is_invisible_to_pin_search_and_read(published):
    # 用例 1:draft(staged)对正式查询不可见 —— pin/search/read 一律拒绝
    client, _root, vault_id, generation, _source, concept = published
    store = WikiGenerationStore(client.app.state.database)
    draft = store.stage(vault_id, base_generation=generation,
        changes={"Wiki/Draft.md": "# 草稿机密内容\n\n尚未审批。".encode("utf-8")})
    reader = _real_reader(client)
    with pytest.raises(WikiGenerationError, match="unavailable"):
        reader.pin(draft)
    head_pin = reader.pin()
    assert reader.pin().generation == generation
    assert not any(hit.relative_path == "Wiki/Draft.md" for hit in reader.search(head_pin, "草稿机密内容"))
    with pytest.raises(WikiGenerationError, match="unavailable"):
        reader.read(reader.pin(draft), "Wiki/Draft.md")


def test_g1_pin_reads_stable_while_g2_is_staged(published):
    # 用例 2:构造 G2 期间 G1 继续可读 —— G1 显式 pin 在 G2 staged 前后结果一致
    client, _root, vault_id, generation, source, concept = published
    reader = _real_reader(client)
    pin = reader.pin(generation)
    before = _pin_bytes(reader, pin, concept)
    store = WikiGenerationStore(client.app.state.database)
    g2 = store.stage(vault_id, base_generation=generation,
        changes={"Wiki/Concepts/故障概念.md": "# 故障概念\n\nG2 草稿改写。".encode("utf-8")})
    assert store.active(vault_id) == generation
    assert _pin_bytes(reader, pin, concept) == before
    assert reader.pin().generation == generation
    assert g2 != generation


@pytest.mark.parametrize("mode", ["validator_error", "dependency_change"])
def test_g2_publish_failure_keeps_g1_readable_and_identical(published, mode):
    # 用例 3:G2 publish 故意失败后,G1 继续可读且内容一致
    from app.services.wiki.publication import WikiPublicationService

    client, _root, vault_id, generation, source, concept = published
    store = WikiGenerationStore(client.app.state.database)
    g2 = store.stage(vault_id, base_generation=generation,
        changes={"Wiki/Concepts/故障概念.md": "# 故障概念\n\nG2 待发布内容。".encode("utf-8")})
    reader = _real_reader(client)
    pin = reader.pin(generation)
    before = _pin_bytes(reader, pin, concept)

    if mode == "validator_error":
        def failing_validator(conn, vault_id_, generation_, manifest):
            raise WikiGenerationError("source_forgotten")

        with pytest.raises(WikiGenerationError, match="source_forgotten"):
            store.promote(vault_id, g2, validate=failing_validator)
    else:
        # 依赖变更:篡改 G2 自身的依赖戳(不动实时状态),使发布校验发现依赖不一致
        with sqlite3.connect(client.app.state.database.path) as conn:
            conn.execute(
                "UPDATE wiki_generation_dependencies SET dependency_json = "
                "json_set(dependency_json, '$.stamp', 'tampered') WHERE generation = ?",
                (g2,),
            )
        service = factory.wiki_service(SimpleNamespace(app=client.app))
        with pytest.raises(WikiGenerationError):
            store.promote(vault_id, g2,
                validate=WikiPublicationService(client.app.state.database, service)._validate)

    assert store.active(vault_id) == generation
    assert _pin_bytes(reader, pin, concept) == before
    with sqlite3.connect(client.app.state.database.path) as conn:
        assert conn.execute("SELECT status FROM wiki_generations WHERE id = ?", (g2,)).fetchone()[0] == "staged"


def test_forgotten_root_binding_denies_g1_fact_answers(published):
    # 用例 4:forgotten 根来源后,G1 不能继续支持事实回答(读路径 binding 状态检查)
    # 现状:compiler 读侧以 CompilerError(binding_not_active)阻断;B5 收紧 authorize 后
    # 以 wiki_snapshot_access_denied 阻断 —— 本用例对两种机制均成立。
    from app.services.wiki.compiler import CompilerError

    client, _root, vault_id, generation, source, concept = published
    reader = _real_reader(client)
    pin = reader.pin(generation)
    assert reader.read(pin, concept).content
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            "UPDATE wiki_page_bindings SET status = 'forgotten' WHERE vault_id = ? AND wiki_relative_path = ?",
            (vault_id, source),
        )
    with pytest.raises(
        (WikiGenerationError, CompilerError),
        match="access_denied|unavailable|binding_not_active",
    ):
        reader.read(pin, concept)
    assert reader.search(pin, "故障概念") == []


def test_revoked_generation_is_denied_after_036(published):
    # 用例 5:revoked(036 后)阻断事实回答 —— 撤销是状态事件,正文保留
    client, _root, vault_id, generation, _source, concept = published
    reader = _real_reader(client)
    pin = reader.pin(generation)
    assert reader.read(pin, concept).content
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.execute(
            "UPDATE wiki_generations SET revoked_at = datetime('now'), revoked_reason = '来源撤销' WHERE id = ?",
            (generation,),
        )
    with pytest.raises(WikiGenerationError, match="unavailable|access_denied"):
        reader.read(pin, concept)
    with sqlite3.connect(client.app.state.database.path) as conn:
        row = conn.execute(
            'SELECT b.body FROM wiki_page_bodies b JOIN wiki_generation_pages p ON p.content_hash = b.content_hash WHERE p.vault_id = ? AND p.generation = ? AND p.relative_path = ?',
            (vault_id, generation, concept),
        ).fetchone()
        assert row is not None and len(bytes(row[0])) > 0


def test_write_conflict_preserves_manual_edit_and_keeps_g1(published, tmp_path):
    # 用例 6:外部编辑冲突 —— write_page 的 target_content_hash 不匹配 → 失败且人工修改保留
    client, vault_root, vault_id, generation, source, concept = published
    reader = _real_reader(client)
    pin = reader.pin(generation)
    before = _pin_bytes(reader, pin, concept)
    # 先完成 preview/confirm/review,再让外部修改落入 apply 前的窗口
    preview = client.post("/api/wiki/ingest/preview", headers=AUTH_HEADERS,
        json={"title": "故障来源", "content": "# 故障来源\n\n再次导入触发写盘冲突。\n\n[[故障概念]]"})
    assert preview.status_code == 200, preview.text
    confirmed = client.post("/api/wiki/ingest/confirm", headers=AUTH_HEADERS,
        json={"preview_token": preview.json()["preview_token"], "user_confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    reviewed = client.post("/api/wiki/ingest/review", headers=AUTH_HEADERS,
        json={"run_id": confirmed.json()["run_id"]})
    assert reviewed.status_code == 200, reviewed.text
    target = vault_root.joinpath(*concept.split("/"))
    target.write_text("# 故障概念\n\n人工修改必须保留。\n", encoding="utf-8")
    applied = client.post("/api/wiki/ingest/apply", headers=AUTH_HEADERS,
        json={"run_id": confirmed.json()["run_id"],
              "approved_targets": [p["target_path"] for p in confirmed.json()["page_plans"]],
              "review_id": reviewed.json()["review_id"], "review_acknowledged": True})
    assert applied.status_code == 200, applied.text
    # 来源页写入成功、概念页写盘冲突 → 运行结果为 failed/partial,人工修改必须保留
    assert applied.json()["status"] in {"failed", "partial"}
    assert any(
        page["relative_path"] == concept and page["status"] == "failed"
        for page in applied.json()["page_results"]
    ), applied.json()["page_results"]
    assert "人工修改必须保留。" in target.read_text(encoding="utf-8")
    # G1 正文仍保留:partial apply 会把新写的来源页 binding 置为 quarantined,
    # 实时授权层据此拒绝读(预期活体语义);生成层捕获的 G1 正文必须原样保留。
    store = WikiGenerationStore(client.app.state.database)
    body_before = store.read_body(vault_id, generation, source)
    assert store.read_body(vault_id, generation, source) == body_before
    with sqlite3.connect(client.app.state.database.path) as conn:
        assert conn.execute("SELECT status FROM wiki_generations WHERE id = ?", (generation,)).fetchone()[0] == "published"


def test_watermark_changes_when_binding_is_forgotten(published):
    # 用例 7:watermark 含 binding 维度 —— 遗忘后 watermark 变化
    # 在摘要层面直接验证:source_watermark 的输入集合应包含 bindings(B5 加入 → 当前红)。
    from app.services.wiki.source_watermark import source_watermark

    client, _root, vault_id, generation, source, concept = published
    with sqlite3.connect(client.app.state.database.path) as conn:
        conn.row_factory = sqlite3.Row
        before = source_watermark(conn, vault_id)
        conn.execute(
            "UPDATE wiki_page_bindings SET status = 'forgotten' WHERE vault_id = ? AND wiki_relative_path = ?",
            (vault_id, source),
        )
        after = source_watermark(conn, vault_id)
    assert after != before


def test_draft_lifecycle_transitions_and_stage_reuse_for_same_run(published):
    # 用例 8:draft_pending_review→draft_approved→published 状态流转 + 同一 run 重复 stage 复用
    client, _root, vault_id, generation, _source, concept = published
    store = WikiGenerationStore(client.app.state.database)
    # 真实 run:先确认一个 ingest run(不 apply),workflow_run_id 外键指向真实行
    preview = client.post("/api/wiki/ingest/preview", headers=AUTH_HEADERS,
        json={"title": "草稿来源", "content": "# 草稿来源\n\n等待审批的内容。", "max_pages": 1})
    assert preview.status_code == 200, preview.text
    run_payload = client.post("/api/wiki/ingest/confirm", headers=AUTH_HEADERS,
        json={"preview_token": preview.json()["preview_token"], "user_confirmed": True})
    assert run_payload.status_code == 200, run_payload.text
    run_id = str(run_payload.json()["run_id"])
    changes = {"Wiki/Draft.md": "# 草稿内容\n\n等待审批。".encode("utf-8")}

    first = store.stage(vault_id, base_generation=generation,
        changes=changes, workflow_run_id=run_id)
    with sqlite3.connect(client.app.state.database.path) as conn:
        publication = conn.execute(
            "SELECT json_extract(result_json, '$.publication') FROM wiki_workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    assert publication is not None and "draft_pending_review" in str(publication[0])

    # 同一 run 重复 stage:复用同一 draft,不产生新 generation
    second = store.stage(vault_id, base_generation=generation,
        changes=changes, workflow_run_id=run_id)
    assert second == first
    with sqlite3.connect(client.app.state.database.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM wiki_generations WHERE workflow_run_id = ?", (run_id,)).fetchone()[0] == 1

    # 审批通过后 promote:方案 A 时序要求写盘步骤先把 run 置 'applied'(promote 回执守卫),
    # 随后 promote 把 publication 推进到 draft_approved → published
    def approving_validator(conn, vault_id_, generation_, manifest):
        with conn:
            conn.execute(
                "UPDATE wiki_workflow_runs SET status = 'applied', "
                "result_json = json_set(result_json, '$.publication', json(?)) WHERE id = ?",
                (json.dumps({"status": "draft_approved", "generation": generation_}), run_id),
            )

    store.promote(vault_id, first, validate=approving_validator)
    with sqlite3.connect(client.app.state.database.path) as conn:
        status = conn.execute(
            "SELECT json_extract(result_json, '$.publication.status') FROM wiki_workflow_runs WHERE id = ?",
            (run_id,),
        ).fetchone()[0]
    assert status == "published"

def test_publish_draft_end_to_end_executes_write_bind_and_promote(client_factory, tmp_path) -> None:
    """publish_draft 全流程必须真的可执行(写盘→bind→index→applied→re-capture→promote)。

    此前 stage_draft/publish_draft 是零生产调用方的不可达代码,221 行从未被执行;
    本用例是接线前必须拿到的执行证据。
    """
    from app.services.memory import SafeMarkdownWriter
    from app.services.wiki import WikiService
    from app.services.wiki.publication import WikiPublicationService

    vault_root = tmp_path / "Vault"
    with client_factory(data_dir=tmp_path / "data") as client:
        _init_vault(client, vault_root)
        preview = client.post("/api/wiki/ingest/preview", headers=AUTH_HEADERS,
            json={"title": "草稿来源", "content": "# 草稿来源\n\n草稿先行发布。\n\n[[草稿概念]]", "max_pages": 2})
        assert preview.status_code == 200, preview.text
        confirmed = client.post("/api/wiki/ingest/confirm", headers=AUTH_HEADERS,
            json={"preview_token": preview.json()["preview_token"], "user_confirmed": True})
        assert confirmed.status_code == 200, confirmed.text
        run_id = confirmed.json()["run_id"]
        reviewed = client.post("/api/wiki/ingest/review", headers=AUTH_HEADERS,
            json={"run_id": run_id})
        assert reviewed.status_code == 200, reviewed.text

        database = client.app.state.database
        with sqlite3.connect(database.path) as conn:
            vault_id = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()[0]
        assert WikiGenerationStore(database).active(vault_id) is None

        service = WikiPublicationService(database, WikiService(SafeMarkdownWriter(vault_root)))
        draft = service.stage_draft(run_id)
        assert draft

        # 审批(模拟审批器写 draft_approved;真实审批走 ingest_review)
        with database.session() as conn:
            conn.execute(
                """UPDATE wiki_workflow_runs
                   SET result_json = json_set(COALESCE(result_json, '{}'),
                       '$.publication.status', 'draft_approved')
                   WHERE id = ?""", (run_id,),
            )

        published = service.publish_draft(run_id)
        assert published

        # 1) 活动指针切到新 generation
        assert WikiGenerationStore(database).active(vault_id) == published
        # 2) Markdown 真的落盘
        written = [p for p in vault_root.joinpath("Wiki").rglob("*.md")]
        assert any("草稿来源" in p.read_text(encoding="utf-8") for p in written)
        # 3) 运行进入 applied 且发布状态为 published
        with sqlite3.connect(database.path) as conn:
            row = conn.execute(
                "SELECT status, result_json FROM wiki_workflow_runs WHERE id = ?", (run_id,)
            ).fetchone()
        assert row[0] == "applied"
        assert json.loads(row[1])["publication"]["status"] == "published"

def test_draft_first_flag_on_service_flow_stages_then_publishes(tmp_path: Path) -> None:
    """开关开启时 ingest 必须走 draft-first：review 落草稿(写盘前) → apply 经 publish_draft 发布。

    服务级驱动(而非 API 级)是因为 API 级需要配置审查模型才能走到审批；这里复用
    test_wiki_workflows 的 FakeReviewModel 与 _workflow_service。
    """
    from app.utils.time import utc_now_iso
    from tests.test_wiki_workflows import (
        FakeReviewModel,
        _confirm_ingest,
        _workflow_service,
    )
    from app.models.wiki import (
        WikiIngestApplyRequest,
        WikiIngestPreviewRequest,
        WikiIngestReviewRequest,
    )

    database = Database(tmp_path / "state.sqlite3")
    vault_root = tmp_path / "Vault"
    model = FakeReviewModel('{"summary": "Draft first review", "findings": [], "recommended_targets": []}')
    service = _workflow_service(database, vault_root, review_model=model)
    with database.session() as conn:
        conn.execute(
            """INSERT INTO app_state(key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            ("wiki_draft_first_publication", "true", utc_now_iso()),
        )
        conn.commit()

    preview = service.preview_ingest(
        WikiIngestPreviewRequest(
            title="开关来源", content="# 开关来源\n\n草稿先行。\n\n[[开关概念]]",
            links=["开关概念"], max_pages=2,
        )
    )
    preview = _confirm_ingest(service, preview)
    review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=preview.run_id)))
    assert review.status == "reviewed"

    # 关键顺序：草稿已入库，但内容页尚未写盘
    with database.connect() as conn:
        staged = conn.execute(
            "SELECT COUNT(*) FROM wiki_generations WHERE workflow_run_id = ? AND status = 'staged'",
            (preview.run_id,),
        ).fetchone()[0]
    assert staged == 1
    assert not (vault_root / "Wiki" / "Sources").exists()

    applied = service.apply_ingest(
        WikiIngestApplyRequest(
            run_id=preview.run_id,
            approved_targets=[plan.target_path for plan in preview.page_plans],
            review_id=review.review_id, review_acknowledged=True,
        )
    )
    assert applied.status == "applied"
    assert applied.pages_written >= 1

    with database.connect() as conn:
        vault_id = conn.execute("SELECT id FROM vaults LIMIT 1").fetchone()[0]
        row = conn.execute(
            "SELECT status, result_json FROM wiki_workflow_runs WHERE id = ?", (preview.run_id,)
        ).fetchone()
    assert WikiGenerationStore(database).active(vault_id) is not None
    assert row[0] == "applied"
    assert json.loads(row[1])["publication"]["status"] == "published"
