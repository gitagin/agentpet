from __future__ import annotations

from typing import Any

from app.models.enums import AgentId

from ..events import AgentTokenEvent
from ..events_helpers import _agent_state, _emit_tool_results, _events, _record_node_error
from ..runtime_helpers import _chunk_text, _task_title
from ..services import AgentRuntimeServices, ToolCallingChatModelProtocol
from ..state import AgentState
from ..tools import AgentToolResult, AgentToolSet
from ..prompts.system import _task_confirmation_prompt, _task_confirmation_system_prompt

# 从 graph_runtime.py 迁移，原函数名：_fallback_create_task, _optional_task_reply, _task_node


async def _fallback_create_task(
    services: AgentRuntimeServices,
    state: AgentState,
) -> tuple[str, list[AgentToolResult]]:
    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(
        tasks=services.tasks,
        observer=tool_results.append,
    )
    await observed_toolset.create_task(
        title=_task_title(state.user_message),
        source_text=state.user_message,
    )
    return "我已创建任务。", tool_results


async def _optional_task_reply(
    services: AgentRuntimeServices,
    state: AgentState,
    fallback_response: str,
) -> str:
    try:
        chat_model = _model_for_task(services)
        if chat_model is None:
            return fallback_response
        if isinstance(chat_model, ToolCallingChatModelProtocol):
            result = await chat_model.complete_with_tools(
                user_message=_task_confirmation_prompt(state),
                system_prompt=_task_confirmation_system_prompt(),
                tools=(),
            )
            return result.text
        return await chat_model.complete(
            user_message=_task_confirmation_prompt(state),
            system_prompt=_task_confirmation_system_prompt(),
        )
    except Exception:
        return fallback_response


async def _task_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        response, tool_results = await _fallback_create_task(services, state)
        _emit_tool_results(graph_state, tool_results)
        response = await _optional_task_reply(services, state, response)
        state.response_text = response
        for chunk in _chunk_text(response):
            _events(graph_state).append(
                AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
            )
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


def _model_for_task(services: AgentRuntimeServices):
    if services.model_registry is not None:
        return services.model_registry.get(AgentId.ACTION_AGENT)
    return None
