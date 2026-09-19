from __future__ import annotations

from typing import Any

from app.models.enums import AgentRunStatus

from ..events import AgentDoneEvent
from ..events_helpers import _agent_state, _append_status, _events

# 从 graph_runtime.py 迁移，原函数名：_finish_node


async def _finish_node(graph_state: dict[str, Any]) -> dict[str, Any]:
    state = _agent_state(graph_state)
    if not graph_state.get("failed"):
        state.status = AgentRunStatus.SUCCESS
        _append_status(graph_state, "回复已完成，后台保存聊天记忆。", stage="background_memory")
        _events(graph_state).append(
            AgentDoneEvent(
                agent_run_id=state.agent_run_id,
                intent=state.route.intent,
                text=state.response_text,
                answer_basis=state.answer_basis,
            )
        )
    return graph_state
