"""The same turn must not be injected as history *and* evidence.

A live failure motivated this: a question about topic B ("给我墨墨相关酒馆卡
的所有链接") was answered from the transcripts of topic A.  Part of the cause was
that the immediately preceding turn reached the model twice -- once in
[Recent conversation], and again as a chat-diary citation, where it reads like a
source ("刚才那条黑色修士的卡").
"""

from __future__ import annotations

from app.agents.events_helpers import (
    MIN_RECENT_TURN_ECHO_CHARS,
    _echoes_recent_turn,
    _emit_tool_results,
)
from app.agents.state import AgentState
from app.agents.tools import AgentToolResult
from app.models.api import MemoryRecallPermissions, MemorySearchResponse, MemorySearchResult
from app.services.prompt_context_types import PromptRecentTurn

DIARY_OTHER_TOPIC = "Memories/Daily/2026/09/第2周_09-08至09-14/星期日/2026-09-13.md"
KNOWLEDGE_PATH = "酒馆/卡.md"

BLACK_MONK_ANSWER = "## 20:22:11 - 用户问题：给我黑色修士酒馆卡的链接 - 桌宠回答：我翻到资料库里有张叫「[黑色]修士」的酒馆卡"
LINK_LIST = "23. [[墨墨]的乡村故事 -露出前传](https://discord.com/channels/1134557553011998840/1410118579411619891)"


def _memory_result(*, path: str, snippet: str, scope: str = "daily_chat") -> MemorySearchResult:
    return MemorySearchResult(
        note_id="note-1",
        chunk_id="chunk-1",
        relative_path=path,
        title="标题",
        heading="20:22:11",
        snippet=snippet,
        score=0.9,
        source_scope=scope,
        retrieval_mode="fts",
        recall_permissions=MemoryRecallPermissions(can_answer_context=True),
        lifecycle_status="active",
        risk_tier="low",
    )


def test_recent_turn_echo_is_recognised() -> None:
    citation = _memory_result(path=DIARY_OTHER_TOPIC, snippet=BLACK_MONK_ANSWER)

    assert _echoes_recent_turn(citation, (PromptRecentTurn(role="user", content="给我黑色修士酒馆卡的链接"),)) is True
    assert _echoes_recent_turn(citation, ()) is False


def test_short_greetings_are_not_treated_as_duplicates() -> None:
    # "hi" 这类短寒暄到处都是,拿去判重会把正常证据也删掉。
    citation = _memory_result(path=DIARY_OTHER_TOPIC, snippet="## 20:00:25 - 用户问题：hi - 桌宠回答：我在呀。")

    assert len("hi") < MIN_RECENT_TURN_ECHO_CHARS
    assert _echoes_recent_turn(citation, (PromptRecentTurn(role="user", content="hi"),)) is False


def test_empty_snippet_is_never_a_duplicate() -> None:
    citation = _memory_result(path=DIARY_OTHER_TOPIC, snippet="   ")

    assert _echoes_recent_turn(citation, (PromptRecentTurn(role="user", content="给我黑色修士酒馆卡的链接"),)) is False


def test_same_turn_is_not_injected_as_history_and_evidence_at_once() -> None:
    # 端到端:上一轮问答已经作为 recent_turns 进入提示词,就不该再以日记引用的
    # 身份回来一次;同批里的知识库条目必须保留。
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-current",
        agent_run_id="run-current",
        user_message="给我墨墨相关酒馆卡的所有链接",
    )
    state.recent_turns = [PromptRecentTurn(role="user", content="给我黑色修士酒馆卡的链接")]
    graph_state: dict[str, object] = {"agent_state": state, "events": []}

    _emit_tool_results(
        graph_state,
        [
            AgentToolResult(
                name="search_memory",
                value=MemorySearchResponse(
                    results=[
                        _memory_result(path=DIARY_OTHER_TOPIC, snippet=BLACK_MONK_ANSWER),
                        _memory_result(path=KNOWLEDGE_PATH, snippet=LINK_LIST, scope="knowledge_base"),
                    ]
                ),
            )
        ],
    )

    assert [citation.relative_path for citation in state.citations] == [KNOWLEDGE_PATH]


def test_older_diary_records_are_still_usable_as_evidence() -> None:
    # 只剔除"当前会话最近几轮"的重复:A 不碰更早的日记记录,记忆回响不受影响。
    state = AgentState(
        conversation_id="conversation-1",
        message_id="message-current",
        agent_run_id="run-current",
        user_message="我们之前在聊什么酒馆卡？",
    )
    state.recent_turns = [PromptRecentTurn(role="user", content="今天天气怎么样")]
    graph_state: dict[str, object] = {"agent_state": state, "events": []}

    _emit_tool_results(
        graph_state,
        [
            AgentToolResult(
                name="search_memory",
                value=MemorySearchResponse(
                    results=[_memory_result(path=DIARY_OTHER_TOPIC, snippet=BLACK_MONK_ANSWER)]
                ),
            )
        ],
    )

    assert [citation.relative_path for citation in state.citations] == [DIARY_OTHER_TOPIC]
