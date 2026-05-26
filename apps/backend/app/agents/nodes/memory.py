from __future__ import annotations

from typing import Any

from app.models.enums import AgentId
from app.services.memory_policy import evaluate_memory_content

from ..events import AgentMemoryProposalEvent, AgentTokenEvent
from ..events_helpers import _agent_state, _emit_tool_results, _events, _record_node_error
from ..prompts.system import _memory_system_prompt
from ..runtime_helpers import _chunk_text, _strip_memory_command
from ..services import AgentRuntimeServices
from ..state import AgentState
from ..tools import (
    DEFAULT_MEMORY_TARGET_PATH,
    AgentToolName,
    AgentToolResult,
    AgentToolSet,
    SensitiveMemoryRejectedError,
)
from ..retrieval.router import _automation_enabled

# 从 graph_runtime.py 迁移，原函数名：_fallback_memory_proposal, _memory_node


async def _fallback_memory_proposal(
    services: AgentRuntimeServices,
    state: AgentState,
) -> tuple[str, list[AgentToolResult]]:
    tool_results: list[AgentToolResult] = []
    observed_toolset = AgentToolSet(
        memory=services.memory,
        observer=tool_results.append,
    )
    await observed_toolset.propose_memory(
        content=_strip_memory_command(state.user_message),
        target_path=DEFAULT_MEMORY_TARGET_PATH,
        source_message_id=state.message_id,
    )
    return "我已创建一条待确认的记忆提案，请审核后再写入。", tool_results


async def _memory_node(
    graph_state: dict[str, Any],
    services: AgentRuntimeServices,
    toolset: AgentToolSet,
    run_model_agent_with_tools,
    has_tool_result,
) -> dict[str, Any]:
    try:
        state = _agent_state(graph_state)
        if _automation_enabled(services, "auto_long_term_memory"):
            content = _strip_memory_command(state.user_message)
            policy = evaluate_memory_content(content)
            if not policy.allowed:
                raise SensitiveMemoryRejectedError(policy.reason)
            response = "我会把这条内容放进后台自动整理流程；如果判断为高风险内容，会先向你确认。"
            state.response_text = response
            _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=response))
            return graph_state

        chat_model = _model_for_memory(services)
        if chat_model is not None:
            response, tool_results = await run_model_agent_with_tools(
                agent_id=AgentId.MEMORY_PROPOSAL_AGENT,
                state=state,
                tools=(AgentToolName.PROPOSE_MEMORY,),
                system_prompt=_memory_system_prompt(),
            )
            _emit_tool_results(graph_state, tool_results)
            if not has_tool_result(tool_results, "propose_memory"):
                fallback_response, fallback_results = await _fallback_memory_proposal(services, state)
                _emit_tool_results(graph_state, fallback_results)
                response = fallback_response
            state.response_text = response
            for chunk in _chunk_text(response):
                _events(graph_state).append(
                    AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                )
            return graph_state

        content = _strip_memory_command(state.user_message)
        memory_tool = toolset.propose_memory_tool()
        proposal = await memory_tool.ainvoke(
            {
                "content": content,
                "target_path": DEFAULT_MEMORY_TARGET_PATH,
                "source_message_id": state.message_id,
            }
        )
        state.proposal_id = proposal.proposal_id
        response = "我已创建一条待确认的记忆提案，请审核后再写入。"
        state.response_text = response
        _events(graph_state).append(
            AgentMemoryProposalEvent(
                agent_run_id=state.agent_run_id,
                proposal_id=proposal.proposal_id,
                status=proposal.status,
                target_path=DEFAULT_MEMORY_TARGET_PATH,
            )
        )
        _events(graph_state).append(AgentTokenEvent(agent_run_id=state.agent_run_id, text=response))
        return graph_state
    except Exception as exc:
        return _record_node_error(graph_state, exc)


def _model_for_memory(services: AgentRuntimeServices):
    if services.model_registry is not None:
        return services.model_registry.get(AgentId.MEMORY_PROPOSAL_AGENT)
    return None
