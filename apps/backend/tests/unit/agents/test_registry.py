from __future__ import annotations

from app.agents.registry import AgentCapability, AgentRegistry, default_agent_registry
from app.models.enums import AgentId


def test_default_registry_contains_all_agent_ids() -> None:
    capabilities = default_agent_registry.all_capabilities()

    assert {capability.agent_id for capability in capabilities} == {
        AgentId.CHAT_AGENT,
        AgentId.SEMANTIC_ANALYSIS_AGENT,
        AgentId.RETRIEVAL_AGENT,
        AgentId.ACTION_AGENT,
        AgentId.REFLECTION_AGENT,
    }


def test_describe_for_orchestrator_contains_all_agents() -> None:
    description = default_agent_registry.describe_for_orchestrator()

    assert description
    for agent_id in {
        AgentId.CHAT_AGENT,
        AgentId.SEMANTIC_ANALYSIS_AGENT,
        AgentId.RETRIEVAL_AGENT,
        AgentId.ACTION_AGENT,
        AgentId.REFLECTION_AGENT,
    }:
        assert f"## {agent_id.value}" in description


def test_registry_returns_registered_handler_and_capability() -> None:
    registry = AgentRegistry()

    def handler() -> str:
        return "ok"

    capability = AgentCapability(
        agent_id=AgentId.RETRIEVAL_AGENT,
        description="检索用户记忆库，支持全文和语义搜索。",
        input_schema="搜索关键词字符串。",
        output_schema="相关记忆列表。",
        typical_latency_ms=800,
        can_retry=True,
        max_retries=1,
    )

    registry.register(capability, handler)

    assert registry.get_handler(AgentId.RETRIEVAL_AGENT) is handler
    assert registry.get_capability(AgentId.RETRIEVAL_AGENT) == capability
    assert registry.get_handler(AgentId.RETRIEVAL_AGENT)() == "ok"
