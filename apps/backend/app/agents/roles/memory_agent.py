from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.chat_model import RoleAgentFactory, create_tool_role_agent

from ..contracts import AgentResultEnvelope, AgentToolId, IndependentAgentRoleId
from ..prompts.system import role_system_prompt


ROLE_ID = IndependentAgentRoleId.MEMORY
ALLOWED_TOOLS = (
    AgentToolId.SEARCH_ACTIVE_MEMORY.value,
    AgentToolId.SEARCH_DIARY_OBJECTS.value,
    AgentToolId.SEARCH_DAILY_CHAT.value,
    AgentToolId.SEARCH_SQLITE_GRAPH.value,
)


def build_role_agent(
    *,
    model: Any,
    tools: Sequence[Any],
    agent_factory: RoleAgentFactory | None = None,
) -> Any:
    return create_tool_role_agent(
        model=model,
        system_prompt=role_system_prompt(ROLE_ID),
        tools=tools,
        allowed_tool_names=ALLOWED_TOOLS,
        output_schema=AgentResultEnvelope,
        agent_factory=agent_factory,
    )
