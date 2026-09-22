"""A4 两轴接线:写入落库 -> 检索读回 -> 权威排序。

覆盖验收要点:一条**偏好类用户陈述**经完整写入链路后,检索结果上
`content_category == "preference"` 且陈述权威为 `user`。

本文件专门盯住一个曾经失明的分支:偏好声明走的是
`create_relation`(relation 分支),而不是 `create_claim`(claim 分支)。
A4-1 的落库只覆盖了 claim 分支,relation 的 metadata 被归一化为 "{}",
而 kind->category 映射里**只有 PREFERENCE 产出用户权威类**,所以权威轴
对它最主要的存在场景完全不可见。这里用端到端路径把它钉死。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from apps.backend.tests._schema import migrate_db
from app.agents.retrieval.wiki_gate import assessment_input, order_evidence_by_statement_authority
from app.models.api import MemoryRecallPermissions, MemorySearchResult
from app.services.evidence_policy import (
    ProvenanceKind,
    statement_authority,
    statement_authority_of,
    statement_authority_sort_key,
)
from app.services.memory_candidates import MemoryCandidateStore
from app.services.memory_consolidation import MemoryConsolidationService
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.memory_read import GraphMemorySourceAdapter, UnifiedMemorySearchService
from app.services.memory_taxonomy import (
    content_category_for_relation,
    content_category_from_metadata,
    graph_fact_content_category,
)
from app.services.prompt_memory_assembler import PromptMemoryAssembler, PromptMemoryAssemblyInput

PREFERENCE_MESSAGE = "请记得我更喜欢下午开会"
PREFERENCE_QUERY = "下午开会"


def _write_preference(db_path: Path) -> str:
    """走完整写入链路:显式用户偏好 -> 候选 -> 图关系边。返回图事实 id。"""
    graph = MemoryEntityGraphStore(db_path)
    service = MemoryConsolidationService(
        MemoryCandidateStore(db_path),
        entity_graph=graph,
        now_provider=lambda: datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    try:
        # 不传 conversation/message/run id:memory_evidence 对它们有外键约束,
        # 而这些行属于聊天链路,本用例只关心记忆写入链路本身。
        result = service.consolidate(
            user_message=PREFERENCE_MESSAGE,
            assistant_answer="已记住。",
        )
    finally:
        service.close()

    assert result.candidate_count == 1
    candidate = result.items[0].candidate
    assert candidate.memory_kind.value == "preference"
    assert candidate.status.value == "active"
    assert candidate.fact_id, "偏好声明必须被物化为图事实,否则端到端无从谈起"
    return candidate.fact_id


def _stored_fact(db_path: Path, fact_id: str):
    store = MemoryEntityGraphStore(db_path)
    try:
        return store.get(fact_id)
    finally:
        store.close()


def _search_personal_memory(db_path: Path, query: str):
    service = UnifiedMemorySearchService(
        (
            GraphMemorySourceAdapter(
                lambda: MemoryEntityGraphStore(db_path),
                answerable_only=True,
                vault_id=None,
            ),
        )
    )
    return service.search(query=query, top_k=5, mode="fts", source_scope="personal_memory")


def test_preference_statement_relation_branch_end_to_end(tmp_path: Path) -> None:
    """验收要点:偏好类用户陈述经完整链路后,检索结果带 preference 且权威为 user。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    fact_id = _write_preference(db_path)

    # 1) 落库侧:偏好走 relation 分支,metadata 必须带事实范畴(此前恒为 "{}")。
    fact = _stored_fact(db_path, fact_id)
    assert fact.statement_kind == "relation"
    assert fact.relation_type == "prefers"
    assert fact.source_type == "explicit_user"
    stored_metadata = json.loads(fact.metadata_json)
    assert stored_metadata["content_category"] == "preference"
    assert stored_metadata["source_track"] == "explicit_user"

    # 2) 读侧:检索结果把两轴输入都带上。
    response = _search_personal_memory(db_path, PREFERENCE_QUERY)
    assert response.results, "偏好事实应可被个人记忆检索召回"
    result = next(item for item in response.results if item.fact_id == fact_id)
    assert result.content_category == "preference"
    assert result.source_type == "explicit_user"

    # 3) 两轴汇合:权威轴对偏好类用户陈述判为 user。
    assert statement_authority_of(result.source_type, result.content_category) == "user"
    assert statement_authority(
        ProvenanceKind.USER_STATEMENT, result.content_category
    ) == "user"


def test_preference_relation_metadata_is_not_silently_empty(tmp_path: Path) -> None:
    """直接盯住回归:relation 分支的 metadata 不能再被归一化成空对象。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    fact_id = _write_preference(db_path)
    fact = _stored_fact(db_path, fact_id)
    assert fact.metadata_json.strip() not in {"", "{}"}


def test_claim_branch_still_carries_content_category(tmp_path: Path) -> None:
    """非偏好(claim 分支)不能被本次改动弄丢 A4-1 已落地的范畴。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    graph = MemoryEntityGraphStore(db_path)
    service = MemoryConsolidationService(
        MemoryCandidateStore(db_path),
        entity_graph=graph,
        now_provider=lambda: datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc),
    )
    try:
        result = service.consolidate(
            user_message="请记住我的项目代号是 Atlas。",
            assistant_answer="已记住。",
        )
    finally:
        service.close()

    candidate = result.items[0].candidate
    assert candidate.fact_id
    fact = _stored_fact(db_path, candidate.fact_id)
    assert fact.statement_kind == "claim"
    assert json.loads(fact.metadata_json)["content_category"] == "fact"


def test_create_relation_without_metadata_stays_empty_object(tmp_path: Path) -> None:
    """缺省行为不变:不传 metadata 的既有调用方仍然得到 "{}"(不是 "null")。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db_path)
    try:
        self_entity = store.ensure_self()
        target = store.create_entity(entity_type="preference", canonical_name="下午开会")
        fact = store.create_relation(
            relation_type="prefers",
            subject_entity_id=self_entity.id,
            object_entity_id=target.id,
            source_text="无 metadata 的调用方",
        )
    finally:
        store.close()
    assert json.loads(fact.metadata_json) == {}


def test_create_relation_metadata_round_trips_through_upsert(tmp_path: Path) -> None:
    """新增的 metadata 参数必须真的落到行上,而不是只存在于调用栈里。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db_path)
    try:
        self_entity = store.ensure_self()
        target = store.create_entity(entity_type="preference", canonical_name="早起")
        fact = store.create_relation(
            relation_type="prefers",
            subject_entity_id=self_entity.id,
            object_entity_id=target.id,
            source_text="请记得我更喜欢早起",
            source_type="explicit_user",
            metadata={"content_category": "preference"},
        )
    finally:
        store.close()
    assert json.loads(fact.metadata_json)["content_category"] == "preference"
    assert fact.source_type == "explicit_user"


def test_content_category_from_metadata_is_conservative() -> None:
    """读侧不知道范畴时必须返回 None,不能凭空断言为 fact。"""
    assert content_category_from_metadata('{"content_category": "preference"}') == "preference"
    assert content_category_from_metadata({"content_category": " Preference "}) == "Preference"
    assert content_category_from_metadata("{}") is None
    assert content_category_from_metadata("") is None
    assert content_category_from_metadata(None) is None
    assert content_category_from_metadata("not json") is None
    assert content_category_from_metadata("[1, 2]") is None
    assert content_category_from_metadata('{"content_category": "   "}') is None


def _result(
    *,
    snippet: str,
    source_type: str | None,
    content_category: str | None,
    relative_path: str = "Memory/Item",
) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=snippet,
        chunk_id=snippet,
        relative_path=relative_path,
        title=snippet,
        snippet=snippet,
        score=0.9,
        source_scope="personal_memory",
        retrieval_mode="graph_activation",
        recall_permissions=MemoryRecallPermissions(can_answer_context=True),
        lifecycle_status="active",
        risk_tier="low",
        fact_id=snippet,
        source_type=source_type,
        content_category=content_category,
    )


def test_statement_authority_sort_key_ranks_user_first_and_unknown_last() -> None:
    user = _result(snippet="u", source_type="explicit_user", content_category="preference")
    mixed = _result(snippet="m", source_type="explicit_user", content_category="fact")
    external = _result(snippet="e", source_type="wiki", content_category="fact")
    unknown = _result(snippet="?", source_type=None, content_category=None)

    assert statement_authority_sort_key(user) == 0
    assert statement_authority_sort_key(mixed) == 1
    assert statement_authority_sort_key(external) == 2
    # 来源性质缺失时 statement_authority 保守返回 external(既有契约),
    # 所以「未知」与「外部」同档——**未知永远不会被排进用户权威档**。
    assert statement_authority_sort_key(unknown) == 2
    # 只有真正无法识别的权威取值才落到最后一档。
    from app.services.evidence_policy import statement_authority_order

    assert statement_authority_order("not_checked") == 3
    assert statement_authority_order(None) == 3


def test_assembler_orders_user_authority_before_external() -> None:
    """组装层落点:外部来源排在用户权威类之后,且同档位保持原有次序。"""
    external = _result(
        snippet="external-wiki",
        source_type="wiki",
        content_category="fact",
        relative_path="Wiki/Suppliers",
    )
    user = _result(
        snippet="user-preference",
        source_type="explicit_user",
        content_category="preference",
        relative_path="Memory/Preference",
    )
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message="我更喜欢什么时候开会?",
            citations=(external, user),
        )
    )
    lines = assembly.recall_sections.answer_context_lines
    assert lines == (
        "- source=Memory/Preference: user-preference",
        "- source=Wiki/Suppliers: external-wiki",
    )


def test_assembler_ordering_does_not_reorder_within_one_authority_tier() -> None:
    """排序必须稳定:同档位保持调用方给出的检索分数序,不得打乱相关性。"""
    first = _result(snippet="first", source_type="wiki", content_category="fact")
    second = _result(snippet="second", source_type="wiki", content_category="fact")
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(user_message="供应商资料", citations=(first, second))
    )
    assert assembly.recall_sections.answer_context_lines == (
        "- source=Memory/Item: first",
        "- source=Memory/Item: second",
    )


def test_gate_orders_evidence_by_statement_authority() -> None:
    """证据门落点:交给模型的证据列表按权威排序,集合本身不变。"""
    external = _result(
        snippet="external-wiki",
        source_type="wiki",
        content_category="fact",
        relative_path="Wiki/Suppliers",
    )
    user = _result(
        snippet="user-preference",
        source_type="explicit_user",
        content_category="preference",
        relative_path="Memory/Preference",
    )
    ordered = order_evidence_by_statement_authority([external, user])
    assert [item.relative_path for item in ordered] == ["Memory/Preference", "Wiki/Suppliers"]
    assert sorted(item.relative_path for item in ordered) == sorted(
        item.relative_path for item in (external, user)
    )

    payload = json.loads(
        assessment_input("我更喜欢什么时候开会?", [external, user], {"Memory/Preference", "Wiki/Suppliers"})
    )
    assert [item["path"] for item in payload["evidence"]] == [
        "Memory/Preference",
        "Wiki/Suppliers",
    ]


# ---------------------------------------------------------------------------
# 旧行处置(t8):create_relation 的 metadata 修复只对新增行生效,
# 修复前落库的偏好关系边 metadata 恒为 "{}" ⇒ 旧库的权威轴仍失明。
# 这里把「旧行」**如实构造**出来(把 metadata 抹回 "{}",其余字段不动),
# 再断言读侧能无歧义重建,而不是靠猜。
# ---------------------------------------------------------------------------


def _erase_metadata_to_simulate_legacy_row(db_path: Path, fact_id: str) -> None:
    """把一行打回修复前的样子:metadata 清成 "{}",其余列一律不碰。"""
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE memory_graph_facts SET metadata_json = '{}' WHERE id = ?", (fact_id,)
        )


def test_legacy_preference_relation_row_is_reconstructed_end_to_end(tmp_path: Path) -> None:
    """旧行(metadata={})经读侧重建后,检索结果仍给出 preference 且权威为 user。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    fact_id = _write_preference(db_path)
    _erase_metadata_to_simulate_legacy_row(db_path, fact_id)

    legacy = _stored_fact(db_path, fact_id)
    # 前提:这确实是「修复前」的行 —— metadata 里读不到范畴,只认 metadata 的读法必然失明。
    assert json.loads(legacy.metadata_json) == {}
    assert content_category_from_metadata(legacy.metadata_json) is None

    response = _search_personal_memory(db_path, PREFERENCE_QUERY)
    result = next(item for item in response.results if item.fact_id == fact_id)
    assert result.content_category == "preference"
    assert result.source_type == "explicit_user"
    assert statement_authority_of(result.source_type, result.content_category) == "user"


def test_reconstruction_does_not_override_a_recorded_value(tmp_path: Path) -> None:
    """边界:metadata 里**已经写了**值就以它为准,重建不得覆盖。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    fact_id = _write_preference(db_path)
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE memory_graph_facts SET metadata_json = ? WHERE id = ?",
            (json.dumps({"content_category": "event"}), fact_id),
        )
    fact = _stored_fact(db_path, fact_id)
    assert fact.relation_type == "prefers"
    assert graph_fact_content_category(fact) == "event"


def test_non_prefers_relation_is_not_reconstructed(tmp_path: Path) -> None:
    """边界:非 prefers 的 relation 行**不得**被重建 —— 宁可失明,不许猜测。"""
    db_path = migrate_db(tmp_path / "state.sqlite3")
    store = MemoryEntityGraphStore(db_path)
    try:
        self_entity = store.ensure_self()
        target = store.create_entity(entity_type="preference", canonical_name="早起")
        fact = store.create_relation(
            relation_type="avoids",
            subject_entity_id=self_entity.id,
            object_entity_id=target.id,
            source_text="我回避早起",
            source_type="explicit_user",
        )
    finally:
        store.close()

    assert json.loads(fact.metadata_json) == {}
    assert content_category_for_relation("avoids") is None
    assert graph_fact_content_category(fact) is None
    # 权威轴因此保守降级为 mixed,而不是被抬成 user。
    assert statement_authority_of(fact.source_type, graph_fact_content_category(fact)) == "mixed"


def test_content_category_for_relation_is_case_and_space_insensitive() -> None:
    assert content_category_for_relation("prefers") == "preference"
    assert content_category_for_relation("  Prefers  ") == "preference"
    assert content_category_for_relation("PREFERS") == "preference"
    assert content_category_for_relation(None) is None
    assert content_category_for_relation("") is None
    assert content_category_for_relation("works_on") is None


def test_graph_fact_content_category_prefers_metadata_then_relation() -> None:
    """优先级明确:metadata 有值用它;没有才回退到关系类型;两者都无 → None。"""
    class _Fact:
        def __init__(self, metadata_json: str, relation_type: str | None) -> None:
            self.metadata_json = metadata_json
            self.relation_type = relation_type

    assert graph_fact_content_category(_Fact('{"content_category":"fact"}', "prefers")) == "fact"
    assert graph_fact_content_category(_Fact("{}", "prefers")) == "preference"
    assert graph_fact_content_category(_Fact("{}", "works_on")) is None
    assert graph_fact_content_category(_Fact("{}", None)) is None
    assert graph_fact_content_category(_Fact("not json", "prefers")) == "preference"
