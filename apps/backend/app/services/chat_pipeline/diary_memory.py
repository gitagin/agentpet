from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.agents.events import AgentActionEvent
from app.agents.state import AgentState
from app.services.agent_actions import AutomationPolicy

if TYPE_CHECKING:
    from app.api.wiring import AppContext

logger = logging.getLogger(__name__)


def diary_memory_service(context: AppContext) -> Any:
    from app.api.wiring import diary_memory_service as factory

    return factory(context)


def action_lifecycle(context: AppContext) -> Any:
    from app.api.wiring import production_action_lifecycle

    return production_action_lifecycle(context)


async def archive_structured_diary_memory(
    *,
    context: AppContext,
    state: AgentState,
    assistant_message_id: str,
    assistant_answer: str,
    daily_result: Any | None,
    automation,
    policy: AutomationPolicy,
    raise_errors: bool = False,
) -> tuple[tuple[str, ...], list[AgentActionEvent]]:
    from app.api.services.adapters import _execute_registered_action

    from . import agent_action_event

    if not automation.auto_structured_memory:
        return (), []
    if not state.user_message.strip() or not assistant_answer.strip():
        return (), []

    daily_entry = getattr(daily_result, "entry", None)
    occurred_at = getattr(daily_entry, "created_at", None) or _message_created_at(
        context,
        assistant_message_id,
    )
    markdown_path = getattr(daily_entry, "markdown_path", None)

    try:
        outcome = await _execute_registered_action(
            context,
            action_lifecycle=action_lifecycle(context),
            action_type="diary.structured_memory",
            target_ref=f"intent:post-reply/structured-diary/{state.agent_run_id}",
            parameters={
                "conversation_id": state.conversation_id,
                "user_message_id": state.message_id,
                "assistant_message_id": assistant_message_id,
                "agent_run_id": state.agent_run_id,
                "user_question": state.user_message,
                "assistant_answer": assistant_answer,
                "occurred_at": occurred_at,
                "markdown_path": markdown_path,
            },
            expected_effect="从这次对话提取结构化日记记忆。",
            source_message_id=state.message_id,
            source_run_id=state.agent_run_id,
            source_conversation_id=state.conversation_id,
            reversible=False,
        )
        if outcome.receipt.status != "verified":
            raise RuntimeError(outcome.receipt.safe_error_code or "structured_diary_not_verified")
        object_ids = tuple(str(item) for item in outcome.receipt.result.get("object_ids") or ())
        if not object_ids:
            # 这一轮模型抽出了零个对象:动作已完成但零效果,按跳过处理。
            # 不是失败 —— 否则一次正常的"没内容可记"就会把整条回复后流水线标红。
            return (), []
        return object_ids, [agent_action_event(state.agent_run_id, outcome.action)]
    except Exception as exc:
        if raise_errors:
            raise
        logger.warning(
            "Structured diary memory archive skipped for agent_run_id=%s: %s",
            state.agent_run_id,
            exc,
        )
        return (), []


def _message_created_at(context: AppContext, assistant_message_id: str) -> str:
    from app.api.wiring import database

    try:
        with database(context).session() as conn:
            row = conn.execute(
                "SELECT created_at FROM messages WHERE id = ?",
                (assistant_message_id,),
            ).fetchone()
        if row is not None and row[0]:
            return str(row[0])
    except Exception:
        logger.debug("Assistant message timestamp lookup failed", exc_info=True)
    # Test doubles may not expose a message table.  A fixed fallback keeps
    # the lifecycle key stable across retries instead of using wall-clock time.
    return "1970-01-01T00:00:00Z"
