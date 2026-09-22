"""候选相关性分数(score)与价值函数口径的语义测试。

`score` 的约定:bm25 分支为 `-bm25`(越大越相关),LIKE 兜底分支为 **0.0**。
**0.0 是真实取值,不是缺省** —— 历史写法 `float(value or 1.0)` 会把 LIKE 兜底命中与
无词法证据的候选抬成满分,使其与真实低分命中无法区分。

「未知相关性」(图扩展邻居页没有词法候选分)**显式**表达为 `None`,由命名策略
`_UNKNOWN_RELEVANCE_VALUE` 统一处理,不在调用点凭空发明一个分数。

价值函数口径:准入(min_held)与置换(挑最低价值者)**共用** `_held_value`
(设计 §2.2 的 V = relevance × freshness × coverage)。
"""

from __future__ import annotations

import asyncio
import json

from app.agents.nodes.wiki_retrieval import (
    _UNKNOWN_RELEVANCE_VALUE,
    _candidate_score,
    _citation_value,
    _held_value,
    wiki_knowledge_retrieval_node,
)
from app.agents.retrieval.wiki_gate import WikiEvidenceGate
from app.agents.services import AgentRuntimeServices
from app.models.wiki import WikiPageReadResponse
from tests.test_wiki_query_node import graph


class ScorelessReader:
    """既有桩读器形态:候选**不带** score 键(默认值路径)。"""

    def __init__(self, count=8):
        self.paths = [f"Wiki/Page{i}.md" for i in range(1, count + 1)]

    async def search_pages(self, query, top_k=8):
        return {"generation": "generation", "candidates": [
            {"relative_path": path, "content_hash": "hash", "heading": None} for path in self.paths
        ]}

    async def read_page(self, request):
        return WikiPageReadResponse(
            generation="generation", relative_path=request.relative_path, content_hash="hash",
            title="Page", content=f"内容 {request.relative_path}", start_line=1, end_line=1,
            links=[], backlinks=[],
        )


def test_zero_score_is_a_real_value_not_a_missing_default():
    assert _candidate_score(0.0) == 0.0
    assert _candidate_score(0) == 0.0
    assert _candidate_score(3.25) == 3.25
    # 只有键缺失/None 才回落到中性默认
    assert _candidate_score(None) == 1.0


def test_citation_value_does_not_lift_a_zero_score():
    # LIKE 兜底命中 score=0.0 ⇒ 价值为 0,不得被抬成满分
    assert _citation_value(0.0, "fresh", "model_assessed_complete") == 0.0
    assert _citation_value(None, "fresh", "model_assessed_complete") == 1.0
    assert _citation_value(2.0, "fresh", "model_assessed_complete") == 2.0
    # 既有回归锚点:正分候选的价值仍严格为正
    assert _citation_value(1.0, "fresh", "model_assessed_complete") > 0.0


def test_candidates_without_a_score_key_keep_the_historical_default():
    reader = ScorelessReader()
    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(state, AgentRuntimeServices(wiki_reader=reader)))
    assert len(state["wiki_reading"]["read"]) == 8
    assert state["wiki_reading"]["stop_reason"] == "assessment_unavailable"


def test_unknown_relevance_is_named_policy_not_a_fabricated_score():
    # 「未知」与「真实 0.0」必须可区分:前者走命名策略,后者就是 0.0
    assert _candidate_score(None) == _UNKNOWN_RELEVANCE_VALUE
    assert _candidate_score(0.0) == 0.0
    assert _UNKNOWN_RELEVANCE_VALUE != 0.0


def test_displacement_and_admission_share_the_same_value_function():
    """置换必须与准入同源(三因子),否则会出现「用 A 页的价值做决策却踢掉 B 页」。"""
    gate = WikiEvidenceGate()
    held = {"low_score_stale": 5.0, "high_score_fresh": 2.0}
    freshness = {"low_score_stale": ("stale", ""), "high_score_fresh": ("fresh", "")}

    # 旧口径:只看原始 score ⇒ 会挑走 high_score_fresh(但它更新鲜,不该先被置换)
    assert min(held, key=lambda path: held[path]) == "high_score_fresh"
    # 新口径:与准入同源的三因子价值 ⇒ 挑走 low_score_stale
    assert min(
        held, key=lambda path: _held_value(held, path, freshness, gate),
    ) == "low_score_stale"


def test_unknown_relevance_pages_are_recorded_and_not_fabricated():
    """图扩展邻居页没有词法候选分:记 None(可区分)并在报告里显式登记。"""

    class LinkedReader(ScorelessReader):
        async def search_pages(self, query, top_k=8):
            result = await super().search_pages(query, top_k)
            result["candidates"] = result["candidates"][:1]  # 只有第一页是检索候选
            return result

        async def read_page(self, request):
            page = await super().read_page(request)
            index = self.paths.index(request.relative_path)
            page.links = [self.paths[index + 1]]
            return page

    reader = LinkedReader()

    class Model:
        calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            return json.dumps({
                "questions": [{"question": "Next condition?", "status": "missing",
                               "reason": "Need more evidence.", "evidence": []}],
                "conflicts": [],
                "next_reads": [{"relative_path": reader.paths[self.calls], "reason": "Follow link."}],
            })

    class Registry:
        def get(self, agent_id):
            return Model()

    state = graph()
    asyncio.run(wiki_knowledge_retrieval_node(
        state, AgentRuntimeServices(wiki_reader=reader, model_registry=Registry()),
    ))
    report = state["wiki_reading"]
    # 第一页来自候选列表(有登记值);后两页经 links 图扩展发现,没有词法分
    assert report["read"][:1] == reader.paths[:1]
    unknown = report.get("unknown_relevance") or []
    assert unknown, "图扩展邻居页必须被登记为「未知相关性」"
    assert reader.paths[0] not in unknown
    assert set(unknown) <= set(report["read"])
