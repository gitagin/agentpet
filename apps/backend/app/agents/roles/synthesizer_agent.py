from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services.chat_model import StructuredRoleAgent, create_structured_role_agent

from ..contracts import AgentResultEnvelope, IndependentAgentRoleId
from ..prompts.system import role_system_prompt


ROLE_ID = IndependentAgentRoleId.SYNTHESIZER


def build_role_agent(*, model: Any, tools: Sequence[Any] = ()) -> StructuredRoleAgent:
    if tools:
        raise ValueError("synthesizer does not allow tools")
    return create_structured_role_agent(
        model=model,
        system_prompt=role_system_prompt(ROLE_ID),
        output_schema=AgentResultEnvelope,
    )
