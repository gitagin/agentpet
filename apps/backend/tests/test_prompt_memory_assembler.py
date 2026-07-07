from __future__ import annotations

import json
from dataclasses import asdict

from app.agents.immediate_understanding import extract_immediate_understanding
from app.agents.nodes.chat import _message_with_runtime_context
from app.agents.services import AgentRuntimeServices
from app.agents.state import AgentState, SemanticAnalysisResult
from app.models.api import MemoryRecallPermissions, MemorySearchResult
from app.services.prompt_memory_assembler import (
    PROMPT_MEMORY_DROP_REASONS,
    PROMPT_MEMORY_TELEMETRY_SCHEMA,
    PromptMemoryAssembler,
    PromptMemoryAssemblyInput,
    PromptMemoryBudgetConfig,
)
from app.services.prompt_context_types import PromptRecentTurn
from app.services.prompt_profile_provider import PromptProfileItem, PromptProfileSelection


def _result(
    *,
    snippet: str = "Ada prefers concise status updates.",
    permissions: MemoryRecallPermissions | None = None,
    source_scope: str = "personal_memory",
    retrieval_mode: str = "graph_activation",
    memory_kind: str | None = "preference",
    memory_scope: str | None = "global",
    lifecycle_status: str | None = "active",
    risk_tier: str | None = "low",
    fact_id: str | None = "fact-1",
    filtered_reason: str | None = None,
) -> MemorySearchResult:
    return MemorySearchResult(
        note_id=fact_id or "note-1",
        chunk_id="chunk-1",
        relative_path="MemoryGraph/LongTerm",
        title="Structured Long-Term Memory",
        heading="Profile",
        snippet=snippet,
        score=0.9,
        source_scope=source_scope,
        retrieval_mode=retrieval_mode,
        recall_permissions=permissions or MemoryRecallPermissions(can_answer_context=True),
        activation_score=0.82,
        score_breakdown={"query_relevance": 0.2},
        filtered_reason=filtered_reason,
        memory_kind=memory_kind,
        memory_scope=memory_scope,
        lifecycle_status=lifecycle_status,
        risk_tier=risk_tier,
        fact_id=fact_id,
    )


def _assemble(**kwargs):
    payload = PromptMemoryAssemblyInput(user_message="What do you remember about Ada?", **kwargs)
    return PromptMemoryAssembler().assemble(payload)


def _assert_drop_reasons_are_fixed(assembly) -> None:
    for section in assembly.telemetry.sections:
        assert set(section.drop_reasons) <= PROMPT_MEMORY_DROP_REASONS


def _assert_total_dropped_count_matches_sections(assembly) -> None:
    assert assembly.telemetry.total_dropped_count == sum(
        section.dropped_count for section in assembly.telemetry.sections
    )


def test_empty_input_only_generates_current_user_message_section() -> None:
    assembly = PromptMemoryAssembler().assemble(PromptMemoryAssemblyInput(user_message="hello"))

    assert assembly.prompt_text == "hello"
    assert [section.key for section in assembly.sections] == ["current_user_message"]
    assert assembly.recall_sections is None
    assert assembly.telemetry.permission_usage_counts == {
        "style": 0,
        "answer_context": 0,
        "proactive_mention": 0,
        "action_suggestion": 0,
    }


def test_immediate_understanding_enters_current_turn_section() -> None:
    understanding = extract_immediate_understanding("For this turn only, be blunt and review this backend migration.")
    assembly = _assemble(immediate_understanding=understanding)

    section = next(section for section in assembly.sections if section.key == "current_turn_understanding")
    assert "Current-turn understanding" in section.content
    assert "state-only" in section.content
    assert "Current user message:" in assembly.prompt_text


def test_style_only_memory_stays_out_of_answer_context() -> None:
    assembly = _assemble(
        citations=[
            _result(
                snippet="Ada has been under pressure recently.",
                permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=False),
                memory_kind="recent_state",
            )
        ]
    )

    style = next(section for section in assembly.sections if section.key == "style_only")
    assert "low-pressure tone" in style.content
    assert "Ada has been under pressure recently." not in assembly.prompt_text
    assert not any(section.key == "recall_answer_context" for section in assembly.sections)
    assert assembly.telemetry.permission_usage_counts["style"] == 1
    assert assembly.telemetry.permission_usage_counts["answer_context"] == 0


def test_answer_context_memory_enters_answer_section() -> None:
    assembly = _assemble(citations=[_result(snippet="Ada prefers concise updates.")])

    answer = next(section for section in assembly.sections if section.key == "recall_answer_context")
    assert "Answer context (may be used as answer evidence):" in answer.content
    assert "Ada prefers concise updates." in assembly.prompt_text
    assert assembly.telemetry.permission_usage_counts["answer_context"] == 1


def test_action_and_proactive_permissions_get_separate_sections() -> None:
    permissions = MemoryRecallPermissions(
        can_answer_context=True,
        can_proactively_mention=True,
        can_suggest_action=True,
    )
    assembly = _assemble(citations=[_result(snippet="Ada is preparing project Atlas.", permissions=permissions)])

    assert next(section for section in assembly.sections if section.key == "proactive_mentions")
    assert next(section for section in assembly.sections if section.key == "action_suggestions")
    assert assembly.telemetry.permission_usage_counts["proactive_mention"] == 1
    assert assembly.telemetry.permission_usage_counts["action_suggestion"] == 1


def test_sensitive_and_inactive_results_do_not_enter_prompt_sections() -> None:
    citations = [
        _result(snippet="sensitive credential detail", memory_scope="sensitive", risk_tier="high"),
        _result(snippet="forgotten preference", lifecycle_status="forgotten", fact_id="fact-forgotten"),
        _result(snippet="rejected preference", lifecycle_status="rejected", fact_id="fact-rejected"),
        _result(snippet="superseded preference", lifecycle_status="superseded", fact_id="fact-superseded"),
    ]

    assembly = _assemble(citations=citations)

    assert "sensitive credential detail" not in assembly.prompt_text
    assert "forgotten preference" not in assembly.prompt_text
    assert "rejected preference" not in assembly.prompt_text
    assert "superseded preference" not in assembly.prompt_text
    assert not any(section.key == "recall_answer_context" for section in assembly.sections)
    assert assembly.telemetry.filtered_count == 4


def test_expired_recent_state_is_not_promoted_to_stable_or_answer_facts() -> None:
    assembly = _assemble(
        citations=[
            _result(
                snippet="project alpha is blocked",
                permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=True),
                memory_kind="recent_state",
                memory_scope="temporary",
                filtered_reason="expired_recent_state",
            )
        ]
    )

    assert "project alpha is blocked" not in assembly.prompt_text
    assert not any(section.key == "stable_profile" for section in assembly.sections)
    assert not any(section.key == "recall_answer_context" for section in assembly.sections)


def test_diary_snippets_are_classified_as_episodic_memory() -> None:
    assembly = _assemble(
        citations=[
            _result(
                snippet="Ada felt focused after a refactor review.",
                source_scope="diary_objects",
                retrieval_mode="diary_object",
                fact_id=None,
            )
        ]
    )

    episodic = next(section for section in assembly.sections if section.key == "episodic_memory")
    assert "Ada felt focused after a refactor review." in episodic.content
    assert "Ada felt focused after a refactor review." in assembly.prompt_text


def test_graph_fact_memory_is_classified_as_activated_fact() -> None:
    assembly = _assemble(citations=[_result(snippet="Ada prefers tests before refactors.", fact_id="fact-tests")])

    activated = next(section for section in assembly.sections if section.key == "activated_facts")
    assert "Ada prefers tests before refactors." in activated.content
    assert "Ada prefers tests before refactors." in assembly.prompt_text


def test_budget_clips_oversized_sections_and_records_drop_reason() -> None:
    long_tail = " ".join(f"detail-{index}" for index in range(60))
    assembler = PromptMemoryAssembler(
        PromptMemoryBudgetConfig(
            recall_answer_context_chars=90,
        )
    )
    assembly = assembler.assemble(
        PromptMemoryAssemblyInput(
            user_message="What do you remember about Ada?",
            citations=[_result(snippet=f"Ada prefers concise updates. {long_tail}")],
        )
    )

    answer = next(section for section in assembly.sections if section.key == "recall_answer_context")
    assert answer.dropped_count == 1
    assert "char_budget_exceeded" in answer.drop_reasons
    assert answer.used_chars <= answer.char_budget
    assert "detail-59" not in assembly.prompt_text
    metric = next(section for section in assembly.telemetry.sections if section.key == "recall_answer_context")
    assert metric.dropped_count == 1
    assert metric.drop_reasons == ("char_budget_exceeded",)
    _assert_drop_reasons_are_fixed(assembly)
    _assert_total_dropped_count_matches_sections(assembly)


def test_telemetry_records_section_counts_chars_and_permission_counts() -> None:
    assembly = _assemble(
        citations=[
            _result(
                snippet="Ada dislikes preachy answers.",
                permissions=MemoryRecallPermissions(can_style_response=True, can_answer_context=True),
            )
        ]
    )

    by_key = {section.key: section for section in assembly.telemetry.sections}
    metric_payload = asdict(by_key["style_only"])
    assert set(metric_payload) == {"key", "item_count", "used_chars", "char_budget", "dropped_count", "drop_reasons"}
    assert assembly.telemetry.schema == PROMPT_MEMORY_TELEMETRY_SCHEMA
    assert by_key["style_only"].item_count == 1
    assert by_key["recall_answer_context"].used_chars > 0
    assert assembly.telemetry.total_used_chars >= by_key["current_user_message"].used_chars
    assert assembly.telemetry.total_dropped_count == 0
    assert assembly.telemetry.permission_usage_counts == {
        "style": 1,
        "answer_context": 1,
        "proactive_mention": 0,
        "action_suggestion": 0,
    }
    assert not hasattr(by_key["style_only"], "content")
    _assert_drop_reasons_are_fixed(assembly)
    _assert_total_dropped_count_matches_sections(assembly)


def test_telemetry_does_not_include_raw_prompt_content_or_internal_terms() -> None:
    raw_user_message = (
        "Please inspect source_text source_excerpt target_id memory_candidates raw_evidence evidence_id evidence: "
        "agent_run_id message_id conversation_id source_message_id source_conversation_id "
        "Authorization Bearer token candidate:raw fact:raw FTS vector lifecycle_status "
        "C:\\Users\\Alice\\Vault\\Secret.md USER_RAW_SENTINEL"
    )
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message=raw_user_message,
            citations=[
                _result(
                    snippet=(
                        "SNIPPET_RAW_SENTINEL source_text source_excerpt raw_evidence evidence_id "
                        "agent_run_id message_id conversation_id Authorization Bearer token candidate:raw fact:raw"
                    ),
                    permissions=MemoryRecallPermissions(can_answer_context=True),
                    source_scope="personal_memory",
                    retrieval_mode="fts",
                    fact_id=None,
                ).model_copy(update={"relative_path": "C:\\Users\\Alice\\Vault\\Secret.md"})
            ],
        )
    )

    telemetry_text = json.dumps(asdict(assembly.telemetry), ensure_ascii=False)
    assert "USER_RAW_SENTINEL" not in telemetry_text
    assert "SNIPPET_RAW_SENTINEL" not in telemetry_text
    assert "C:\\Users\\Alice" not in telemetry_text
    assert telemetry_text not in assembly.prompt_text
    assert telemetry_text.lower() not in raw_user_message.lower()
    assert telemetry_text.lower() not in (
        "source_text source_excerpt target_id memory_candidates raw_evidence evidence_id evidence: "
        "agent_run_id message_id conversation_id source_message_id source_conversation_id "
        "authorization bearer token candidate: fact: fts vector lifecycle_status"
    )
    assert not _contains_forbidden_prompt_detail(telemetry_text)
    _assert_drop_reasons_are_fixed(assembly)
    _assert_total_dropped_count_matches_sections(assembly)


def test_current_user_message_is_not_clipped_by_budget() -> None:
    sentinel = "TAIL_SENTINEL_DO_NOT_CLIP"
    long_message = "review this log\n" + ("x" * 13_500) + sentinel
    assembly = PromptMemoryAssembler().assemble(PromptMemoryAssemblyInput(user_message=long_message))

    assert assembly.prompt_text.endswith(sentinel)
    current = next(section for section in assembly.sections if section.key == "current_user_message")
    metric = next(section for section in assembly.telemetry.sections if section.key == "current_user_message")
    assert current.dropped_count == 0
    assert metric.dropped_count == 0
    assert current.used_chars == len(long_message)
    assert metric.used_chars == len(long_message)
    _assert_total_dropped_count_matches_sections(assembly)


def test_empty_recent_turns_keep_prompt_equivalent() -> None:
    base = PromptMemoryAssembler().assemble(PromptMemoryAssemblyInput(user_message="hello"))
    with_empty_recent = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(user_message="hello", recent_turns=())
    )

    assert with_empty_recent.prompt_text == base.prompt_text
    assert [section.key for section in with_empty_recent.sections] == [section.key for section in base.sections]


def test_recent_turns_enter_prompt_without_telemetry_content() -> None:
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message="continue",
            recent_turns=(
                PromptRecentTurn(role="user", content="RECENT_USER_SENTINEL"),
                PromptRecentTurn(role="assistant", content="RECENT_ASSISTANT_SENTINEL"),
            ),
        )
    )

    assert "[Recent conversation]" in assembly.prompt_text
    assert "- 用户：RECENT_USER_SENTINEL" in assembly.prompt_text
    assert "- 我：RECENT_ASSISTANT_SENTINEL" in assembly.prompt_text
    assert "Do not treat it as long-term memory." in assembly.prompt_text
    assert assembly.prompt_text.index("[Recent conversation]") < assembly.prompt_text.index("Current user message:")

    recent = next(section for section in assembly.sections if section.key == "recent_turns")
    metric = next(section for section in assembly.telemetry.sections if section.key == "recent_turns")
    telemetry_text = json.dumps(asdict(assembly.telemetry), ensure_ascii=False)
    assert recent.item_count == 2
    assert metric.item_count == 2
    assert not hasattr(metric, "content")
    assert "RECENT_USER_SENTINEL" not in telemetry_text
    assert "RECENT_ASSISTANT_SENTINEL" not in telemetry_text


def test_recent_turns_budget_keeps_newer_messages_and_drops_whole_old_items() -> None:
    assembler = PromptMemoryAssembler(
        PromptMemoryBudgetConfig(
            recent_turns_chars=165,
            recent_turn_chars=60,
        )
    )
    assembly = assembler.assemble(
        PromptMemoryAssemblyInput(
            user_message="continue",
            recent_turns=(
                PromptRecentTurn(role="user", content="OLDER_SENTINEL should drop"),
                PromptRecentTurn(role="assistant", content="MIDDLE_SENTINEL should drop if needed"),
                PromptRecentTurn(role="user", content="NEWER_SENTINEL"),
                PromptRecentTurn(role="assistant", content="NEWEST_SENTINEL"),
                PromptRecentTurn(role="user", content="TOO_LONG_SENTINEL " + ("x" * 80)),
            ),
        )
    )

    assert "NEWER_SENTINEL" in assembly.prompt_text
    assert "NEWEST_SENTINEL" in assembly.prompt_text
    assert "OLDER_SENTINEL" not in assembly.prompt_text
    assert "TOO_LONG_SENTINEL" not in assembly.prompt_text
    recent = next(section for section in assembly.sections if section.key == "recent_turns")
    metric = next(section for section in assembly.telemetry.sections if section.key == "recent_turns")
    assert recent.dropped_count >= 2
    assert "recent_turn_too_long" in recent.drop_reasons
    assert "recent_turns_char_budget_exceeded" in recent.drop_reasons
    assert metric.dropped_count == recent.dropped_count
    assert set(metric.drop_reasons) == {"recent_turn_too_long", "recent_turns_char_budget_exceeded"}
    assert assembly.telemetry.total_dropped_count >= 2
    _assert_drop_reasons_are_fixed(assembly)
    _assert_total_dropped_count_matches_sections(assembly)


def test_recent_turns_with_retrieval_keep_legacy_chinese_prompt_shape() -> None:
    sentinel = "TAIL_SENTINEL_DO_NOT_CLIP"
    long_user_message = "What do you remember about Ada?\n" + ("x" * 13_000) + sentinel
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message=long_user_message,
            citations=[
                _result(snippet="FIRST_RECENT_RETRIEVAL_SENTINEL", fact_id="fact-first"),
                _result(snippet="SECOND_RECENT_RETRIEVAL_SENTINEL", fact_id="fact-second"),
            ],
            recent_turns=(
                PromptRecentTurn(role="user", content="RECENT_CONTEXT_SENTINEL"),
            ),
        ),
    )

    prompt = assembly.prompt_text
    assert "用户问题：" in prompt
    assert "上下文范围：" in prompt
    assert "回答风格：" in prompt
    assert "已检索到的上下文片段：" in prompt
    assert "Answer context (may be used as answer evidence):" in prompt
    assert "[Recent conversation]" in prompt
    assert "Use only for local continuity in this conversation. Do not treat it as long-term memory." in prompt
    assert "Context scope" not in prompt
    assert "Retrieved context sections" not in prompt
    assert "Current user message" not in prompt
    assert sentinel in prompt
    assert prompt.index("用户问题：") < prompt.index("上下文范围：")
    assert prompt.index("上下文范围：") < prompt.index("已检索到的上下文片段：")
    assert prompt.index("已检索到的上下文片段：") < prompt.index("Answer context (may be used as answer evidence):")
    assert prompt.index("FIRST_RECENT_RETRIEVAL_SENTINEL") < prompt.index("SECOND_RECENT_RETRIEVAL_SENTINEL")
    assert prompt.index("SECOND_RECENT_RETRIEVAL_SENTINEL") < prompt.index("[Recent conversation]")
    telemetry_text = json.dumps(asdict(assembly.telemetry), ensure_ascii=False)
    assert "RECENT_CONTEXT_SENTINEL" not in telemetry_text
    assert "FIRST_RECENT_RETRIEVAL_SENTINEL" not in telemetry_text


def test_empty_stable_profile_keeps_prompt_equivalent() -> None:
    base = PromptMemoryAssembler().assemble(PromptMemoryAssemblyInput(user_message="hello"))
    with_empty_profile = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(user_message="hello", stable_profile_items=())
    )

    assert with_empty_profile.prompt_text == base.prompt_text
    assert [section.key for section in with_empty_profile.sections] == [section.key for section in base.sections]
    assert not any(section.key == "stable_profile" for section in with_empty_profile.telemetry.sections)
    _assert_total_dropped_count_matches_sections(with_empty_profile)


def test_stable_profile_over_budget_telemetry_is_safe() -> None:
    sentinel = "STABLE_PROFILE_RAW_SENTINEL"
    assembly = PromptMemoryAssembler(PromptMemoryBudgetConfig(stable_profile_chars=80)).assemble(
        PromptMemoryAssemblyInput(
            user_message="hello",
            stable_profile_items=(
                PromptProfileItem(
                    summary=sentinel + ("x" * 240),
                    category="preferences",
                    permission_group="style_profile",
                    confidence=0.95,
                    importance=0.9,
                ),
            ),
        )
    )

    telemetry_text = json.dumps(asdict(assembly.telemetry), ensure_ascii=False)
    metric = next(section for section in assembly.telemetry.sections if section.key == "stable_profile")
    assert metric.dropped_count == 1
    assert metric.drop_reasons == ("char_budget_exceeded",)
    assert sentinel not in telemetry_text
    _assert_drop_reasons_are_fixed(assembly)
    _assert_total_dropped_count_matches_sections(assembly)


def test_stable_profile_enters_prompt_with_conservative_permission_labels() -> None:
    understanding = extract_immediate_understanding("For this turn only, answer plainly.")
    assembly = PromptMemoryAssembler().assemble(
        PromptMemoryAssemblyInput(
            user_message="How should you answer me?",
            immediate_understanding=understanding,
            citations=[_result(snippet="Ada prefers concise status updates.")],
            stable_profile_items=(
                PromptProfileItem(
                    summary="用户偏好先给结论。",
                    category="preferences",
                    permission_group="style_profile",
                    confidence=0.9,
                    importance=0.8,
                ),
                PromptProfileItem(
                    summary="不要主动提及私人关系。",
                    category="boundaries",
                    permission_group="boundary_profile",
                    confidence=0.95,
                    importance=0.9,
                ),
            ),
        )
    )

    prompt = assembly.prompt_text
    assert "[Stable user preferences and boundaries]" in prompt
    assert "回答偏好（只用于调整语气，不作为事实依据）：用户偏好先给结论。" in prompt
    assert "回答边界（请遵守，但不要主动提及）：不要主动提及私人关系。" in prompt
    assert prompt.index("Current-turn understanding") < prompt.index("[Stable user preferences and boundaries]")
    assert prompt.index("[Stable user preferences and boundaries]") < prompt.index("Answer context (may be used as answer evidence):")
    stable = next(section for section in assembly.sections if section.key == "stable_profile")
    assert stable.item_count == 2
    metric = next(section for section in assembly.telemetry.sections if section.key == "stable_profile")
    assert not hasattr(metric, "content")


def test_chat_wrapper_uses_prompt_profile_provider_when_available() -> None:
    class Provider:
        def select(self, **_kwargs):
            return PromptProfileSelection(
                items=(
                    PromptProfileItem(
                        summary="用户偏好简短回答。",
                        category="preferences",
                        permission_group="style_profile",
                        confidence=0.9,
                        importance=0.8,
                    ),
                )
            )

    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="What do you remember about Ada?",
        semantic_analysis=SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="Ada"),
        citations=[_result(snippet="Ada prefers concise status updates.")],
    )

    prompt = _message_with_runtime_context(
        AgentRuntimeServices(prompt_profile_provider=Provider()),
        state,
    )

    assert "[Stable user preferences and boundaries]" in prompt
    assert "用户偏好简短回答。" in prompt
    assert "Answer context (may be used as answer evidence):" in prompt


def test_chat_wrapper_degrades_safely_when_prompt_profile_provider_fails() -> None:
    class FailingProvider:
        def select(self, **_kwargs):
            raise RuntimeError("provider failed")

    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="What do you remember about Ada?",
        semantic_analysis=SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="Ada"),
        citations=[_result(snippet="Ada prefers concise status updates.")],
    )

    prompt = _message_with_runtime_context(
        AgentRuntimeServices(prompt_profile_provider=FailingProvider()),
        state,
    )

    assert "[Stable user preferences and boundaries]" not in prompt
    assert "Answer context (may be used as answer evidence):" in prompt
    assert "Ada prefers concise status updates." in prompt


def test_multi_citation_order_and_key_prompt_fragments_stay_stable() -> None:
    assembly = _assemble(
        citations=[
            _result(snippet="FIRST_ORDER_SENTINEL", fact_id="fact-first"),
            _result(snippet="SECOND_ORDER_SENTINEL", fact_id="fact-second"),
        ]
    )

    prompt = assembly.prompt_text
    assert prompt.index("用户问题：") < prompt.index("上下文范围：")
    assert prompt.index("上下文范围：") < prompt.index("回答风格：")
    assert prompt.index("回答风格：") < prompt.index("已检索到的上下文片段：")
    assert prompt.index("已检索到的上下文片段：") < prompt.index("Answer context (may be used as answer evidence):")
    assert prompt.index("FIRST_ORDER_SENTINEL") < prompt.index("SECOND_ORDER_SENTINEL")
    assert prompt.index("SECOND_ORDER_SENTINEL") < prompt.index("请以本地长期记忆陪伴体的口吻")


def test_chat_wrapper_keeps_existing_prompt_shape_and_usage_recording() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.records = []

        def record_usage(self, **kwargs) -> None:
            self.records.append(kwargs)

    recorder = Recorder()
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-1",
        agent_run_id="run-1",
        user_message="What do you remember about Ada?",
        semantic_analysis=SemanticAnalysisResult(needs_context=True, source_scope="personal_memory", query="Ada"),
        citations=[_result(snippet="Ada prefers concise status updates.")],
    )

    prompt = _message_with_runtime_context(
        AgentRuntimeServices(memory_activation_recorder=recorder),
        state,
    )

    assert "用户问题：What do you remember about Ada?" in prompt
    assert "已检索到的上下文片段：" in prompt
    assert "Answer context (may be used as answer evidence):" in prompt
    assert "只在记忆能直接帮助当前问题时自然带入" in prompt
    assert recorder.records[0]["used_for_answer_context"] is True


def _contains_forbidden_prompt_detail(value: str) -> bool:
    lowered = value.casefold()
    forbidden = (
        "source_text",
        "source_excerpt",
        "target_id",
        "memory_candidates",
        "raw_evidence",
        "evidence_id",
        "evidence:",
        "agent_run_id",
        "message_id",
        "conversation_id",
        "source_message_id",
        "source_conversation_id",
        "authorization",
        "bearer",
        "token",
        "candidate:",
        "fact:",
        "fts",
        "vector",
        "lifecycle_status",
    )
    return any(item in lowered for item in forbidden)
