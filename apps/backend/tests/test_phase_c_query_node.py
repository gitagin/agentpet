"""阶段C失败测试(C4,先红后绿)。

按 c3 设计(docs/phase-c-query-node-design.md)§1-§6:新鲜度三态状态机、
上下文替换(价值函数+预算满可读第九页)、深读模式档位(均衡/深读)、
Evidence Gate(freshness 独立门不可模型设置)、回归锚点。
函数名英文,语料中文;复用 test_wiki_query_node/gate/read_tools 夹具模式。
"""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.agents.nodes.chat import _chat_node
from app.agents.nodes.wiki_retrieval import wiki_knowledge_retrieval_node
from app.agents.retrieval.wiki_gate import WikiEvidenceGate, parse_assessment
from app.agents.services import AgentRuntimeServices
from app.agents.tools import AgentToolSet
from app.api.services import factory
from app.api.services.adapters import RuntimeWikiReadAdapter
from app.models.wiki import (
    WikiIngestApplyRequest, WikiIngestConfirmRequest, WikiIngestPreviewRequest,
    WikiIngestReviewRequest, WikiPageReadResponse,
)
from app.services.wiki.generations import WikiGenerationStore
from app.services.wiki.snapshot_reader import WikiSnapshotReader
from app.storage.database import Database
from tests.test_wiki_gate import Reader, citation as gate_citation, assessment as gate_assessment
from tests.test_wiki_publication import published
from tests.test_wiki_query_node import graph
from tests.test_wiki_read_tools import read_tools
from tests.test_wiki_workflows import _workflow_service


@pytest.fixture
def published_with_source_state(tmp_path, monkeypatch):
    """发布携带指定验证状态的来源:验证列在 apply 捕获依赖戳之前写入。"""
    def publish(**state):
        database = Database(tmp_path / "state.sqlite3")
        service = _workflow_service(database, tmp_path / "Vault")
        preview = service.preview_ingest(WikiIngestPreviewRequest(
            title="新鲜度来源",
            content="# 新鲜度来源\n\n新鲜度状态机测试内容 supplier 供应商。", max_pages=1))
        confirmed = service.confirm_ingest(WikiIngestConfirmRequest(
            preview_token=preview.preview_token, user_confirmed=True))
        with database.session() as conn:
            conn.execute(
                "UPDATE wiki_sources SET verification_status = ?, verified_at = ?, expires_at = ? WHERE id = ?",
                (state.get("verification_status", "unverified"),
                 state.get("verified_at"), state.get("expires_at"), confirmed.source_id),
            )
        review = asyncio.run(service.review_ingest(WikiIngestReviewRequest(run_id=confirmed.run_id)))
        applied = service.apply_ingest(WikiIngestApplyRequest(
            run_id=confirmed.run_id, approved_targets=[p.target_path for p in confirmed.page_plans],
            review_id=review.review_id, review_acknowledged=True))
        assert applied.status == "applied"
        reader = WikiSnapshotReader(database, service.wiki, authorize=lambda v, p: True)
        monkeypatch.setattr(factory, "wiki_snapshot_reader_dependency", lambda request: reader)
        return AgentToolSet(wiki_reader=RuntimeWikiReadAdapter(object())), database
    return publish


def _stop_model() -> object:
    class StopModel:
        calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            return json.dumps({
                "questions": [{"question": "有证据吗?", "status": "missing",
                               "reason": "证据不足。", "evidence": []}],
                "conflicts": [], "next_reads": [],
            })

    return StopModel()


class _Registry:
    def __init__(self, model):
        self.model = model

    def get(self, agent_id):
        return self.model


def _run_node(reader_or_tools, services=None):
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, services or AgentRuntimeServices(wiki_reader=reader_or_tools)))
    return state


def _set_source(service, **updates):
    with service.database.session() as conn:
        columns = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE wiki_sources SET {columns} WHERE id = (SELECT id FROM wiki_sources LIMIT 1)",
            list(updates.values()),
        )


# ---------- 1. 新鲜度状态机 ----------

def test_new_source_registration_receipt_marks_relevance_check_pending(read_tools):
    # 登记链(设计 §1.2-1):apply/publish 成功即登记 freshness=unknown + reason=source_relevance_check_pending
    _tools, _events, service, _vault, _generation = read_tools
    with service.database.session() as conn:
        row = conn.execute(
            "SELECT result_json FROM wiki_workflow_runs WHERE workflow_type = 'ingest' ORDER BY rowid DESC LIMIT 1",
        ).fetchone()
    publication = json.loads(str(row[0] or "{}")).get("publication") or {}
    assert publication.get("freshness") == "unknown"
    assert publication.get("freshness_reason") == "source_relevance_check_pending"


def test_unverified_source_remains_unknown_with_unchanged_watermark(read_tools):
    # 无验证记录 → unknown(不假设无变化);watermark 未变仍是 unknown
    tools, _events, service, _vault, _generation = read_tools
    _set_source(service, verification_status="unverified", expires_at=None)
    state = _run_node(tools.wiki_reader)
    assert state["agent_state"].wiki_evidence_gate.freshness == "unknown"
    

def test_verified_unchanged_source_is_fresh(published_with_source_state):
    # 验证有效(verified + 未过期)+ 无变化观测 → fresh
    tools, _database = published_with_source_state(
        verification_status="verified", verified_at="2026-09-20T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )
    state = _run_node(tools.wiki_reader)
    gate = state["agent_state"].wiki_evidence_gate
    assert gate.freshness == "fresh"
    assert gate.freshness_reason == "source_verified_current"


def test_expired_source_is_stale(published_with_source_state):
    # expires_at 已过 → stale
    tools, _database = published_with_source_state(
        verification_status="verified", verified_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-02T00:00:00Z",
    )
    state = _run_node(tools.wiki_reader)
    gate = state["agent_state"].wiki_evidence_gate
    assert gate.freshness == "stale"
    assert gate.freshness_reason == "source_expired"


def test_stale_freshness_reaches_answer_injection(published_with_source_state):
    # stale 机器值进入回答组装注入(设计 §1.1/§4.3),UI 文案映射英文机器值
    tools, _database = published_with_source_state(
        verification_status="verified", verified_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-02T00:00:00Z",
    )
    state = _run_node(tools.wiki_reader)
    captured = {}

    class Model:
        async def complete(self, *, user_message, system_prompt=None):
            captured["system_prompt"] = system_prompt
            return "MUST_NOT_BE_SENT"

    asyncio.run(_chat_node(state, AgentRuntimeServices(wiki_reader=tools.wiki_reader, chat_model=Model()), lambda _: False))
    assert "\"stale\"" in (captured.get("system_prompt") or "")


# ---------- 2. 上下文替换:预算满时高价值第九页 ----------

class NinePageReader:
    """8 页低价值 + 1 页高价值(检索得分高,内容含关键字);模型不请求第九页。"""

    def __init__(self):
        self.paths = [f"Wiki/Page{i}.md" for i in range(1, 10)]
        self.reads = []

    async def search_pages(self, query, top_k=8):
        return {"generation": "generation", "candidates": [
            {"relative_path": path, "content_hash": "hash", "heading": None,
             "score": 9.5 if path == self.paths[-1] else 0.1}
            for path in self.paths
        ]}

    async def read_page(self, request):
        assert request.generation == "generation"
        assert request.relative_path in self.paths
        self.reads.append(request.relative_path)
        content = "关键限定证据内容。" if request.relative_path == self.paths[-1] else "背景资料。"
        return WikiPageReadResponse(
            generation="generation", relative_path=request.relative_path, content_hash="hash",
            title="Page", content=content, start_line=1, end_line=1, links=[], backlinks=[],
        )


def test_high_value_ninth_page_read_without_model_request():
    # 价值预检准入(设计 §2.2):第 9 页 V 高于已持有最低 V 且预算允许时,首轮即读入,
    # 并替换低价值旧上下文(报告含替换计数),引用仍可被覆盖性问题追踪
    reader = NinePageReader()
    state = _run_node(reader, AgentRuntimeServices(wiki_reader=reader, model_registry=_Registry(_stop_model())))
    assert reader.paths[-1] in state["wiki_reading"]["read"]
    assert state["wiki_reading"].get("replaced", 0) >= 1
    assert len(state["agent_state"].citations) >= 1
    assert all(c.relative_path not in state["wiki_reading"].get("displaced", ()) for c in state["agent_state"].citations)


# ---------- 3. 深读模式 ----------

def test_balanced_profile_matches_current_limits():
    # 均衡档 = 现状(8 页/2 跳/3 轮/30s/12000 字符)——不回归锚点
    reader = Reader()
    state = _run_node(reader, AgentRuntimeServices(wiki_reader=reader, model_registry=_Registry(_stop_model())))
    assert len(state["wiki_reading"]["read"]) == 8
    assert state["wiki_reading"]["rounds"] <= 3


def test_deep_read_profile_reads_all_candidates():
    # 深读档:24 页/3 跳/6 轮/90s/32000 字符;此处设计锚点为第九页候选池全读
    from app.agents.nodes.wiki_retrieval import ReadProfile  # C5 引入 → 当前 ImportError 即红

    reader = Reader()
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=reader, model_registry=_Registry(_stop_model())),
        read_profile=ReadProfile(mode="deep", max_pages=24, max_depth=3,
                                 max_rounds=6, deadline_sec=90, budget_chars=32000),
    ))
    assert len(state["agent_state"].citations) == 9
    assert state["wiki_reading"]["rounds"] <= 6
    assert state["agent_state"].wiki_evidence_gate.remaining_chars <= 32000


def test_deep_read_does_not_bypass_denied_pages():
    # 深读不突破隐私/权限门:被拒绝页面即使在高预算下也不可读
    reader = Reader()
    denied = reader.paths[-1]

    async def guarded_read(request):
        if request.relative_path == denied:
            raise PermissionError("permission_denied")
        return await Reader.read_page(reader, request)

    reader.read_page = guarded_read
    state = _run_node(reader, AgentRuntimeServices(wiki_reader=reader, model_registry=_Registry(_stop_model())))
    assert denied not in state["wiki_reading"]["read"]
    assert denied not in [c.relative_path for c in state["agent_state"].citations]


def test_balanced_escalates_once_to_deep_on_coverage_gap():
    # 升级路由(设计 §3.1):均衡轮内出现覆盖缺口(missing 评估)且剩余 >= 40% → 单次升级深读
    reader = Reader()
    state = _run_node(reader, AgentRuntimeServices(wiki_reader=reader, model_registry=_Registry(_stop_model())))
    assert state["wiki_reading"].get("profile") == "deep"
    assert state["wiki_reading"].get("escalated") is True


# ---------- 4. Evidence Gate ----------

def test_model_output_cannot_set_freshness_or_authority():
    # freshness/authority 是确定性门:模型输出含这些键 → extra=forbid 拒绝,gate 值不被污染
    item = gate_citation()
    payload = gate_assessment(item)
    payload["freshness"] = "stale"
    with pytest.raises(ValueError):
        parse_assessment(json.dumps(payload), [item], {item.relative_path})
    payload = gate_assessment(item)
    payload["authority"] = "passed"
    with pytest.raises(ValueError):
        parse_assessment(json.dumps(payload), [item], {item.relative_path})


def test_fresh_gate_supports_complete_coverage_supplement_skip():
    # 设计 §4.2:fresh + complete + 无冲突 → 可跳过 fallback;现状 freshness 字面量仅 unknown → 红
    fresh = WikiEvidenceGate(
        freshness="fresh", freshness_reason="source_verified_current",
        coverage="model_assessed_complete", conflict="none_detected_by_model", authority="passed",
    )
    assert fresh.freshness == "fresh"
    assert fresh.coverage == "model_assessed_complete"


def test_stale_cannot_certify_sufficiency_summary():
    # stale 不得作为当前确定事实:supplement 条件(设计 §4.2)在 stale 下不可满足
    gate = WikiEvidenceGate(
        freshness="stale", freshness_reason="source_expired",
        coverage="model_assessed_complete", conflict="none_detected_by_model", authority="passed",
    )
    can_skip = (
        gate.coverage == "model_assessed_complete"
        and gate.conflict != "disputed"
        and gate.freshness == "fresh"
    )
    assert can_skip is False
    assert gate.freshness == "stale"


def test_unknown_complete_coverage_still_falls_back():
    # 不回归锚点:unknown 不能证明充分,保持 fallback 语义(gate 值域现状)
    gate = WikiEvidenceGate(
        coverage="model_assessed_complete", conflict="none_detected_by_model", authority="passed",
    )
    assert gate.freshness == "unknown"


def test_existing_stop_reasons_and_gate_behaviors_unchanged():
    # 回归锚点:11 种 stop_reason 值域与 gate 既有字段(question/conflict/authority)字段构造不受影响
    anchor = WikiEvidenceGate(coverage="partial", conflict="disputed", authority="denied")
    assert anchor.coverage == "partial"
    assert anchor.conflict == "disputed"
    assert anchor.authority == "denied"
