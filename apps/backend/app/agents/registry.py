from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.models.enums import AgentId


AgentHandler = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AgentCapability:
    agent_id: AgentId
    description: str
    input_schema: str
    output_schema: str
    typical_latency_ms: int
    can_retry: bool
    max_retries: int


class AgentRegistry:
    def __init__(self) -> None:
        self._capabilities: dict[AgentId, AgentCapability] = {}
        self._handlers: dict[AgentId, AgentHandler] = {}

    def register(self, capability: AgentCapability, handler: AgentHandler) -> None:
        self._capabilities[capability.agent_id] = capability
        self._handlers[capability.agent_id] = handler

    def get_handler(self, agent_id: AgentId) -> AgentHandler:
        return self._handlers[agent_id]

    def get_capability(self, agent_id: AgentId) -> AgentCapability:
        return self._capabilities[agent_id]

    def all_capabilities(self) -> tuple[AgentCapability, ...]:
        return tuple(self._capabilities.values())

    def describe_for_orchestrator(self) -> str:
        sections: list[str] = []
        for capability in self._capabilities.values():
            retry_policy = "可重试" if capability.can_retry else "不建议重试"
            sections.append(
                "\n".join(
                    [
                        f"## {capability.agent_id.value}",
                        f"功能：{capability.description}",
                        f"输入：{capability.input_schema}",
                        f"输出：{capability.output_schema}",
                        f"典型延迟：{capability.typical_latency_ms}ms",
                        f"重试：{retry_policy}，最多 {capability.max_retries} 次",
                    ]
                )
            )
        return "\n\n".join(sections)


def _unbound_agent_handler(*args, **kwargs) -> None:
    raise NotImplementedError("Agent handler is not bound in the default registry.")


def create_default_agent_registry() -> AgentRegistry:
    registry = AgentRegistry()
    for capability in DEFAULT_AGENT_CAPABILITIES:
        registry.register(capability, _unbound_agent_handler)
    return registry


DEFAULT_AGENT_CAPABILITIES: tuple[AgentCapability, ...] = (
    AgentCapability(
        agent_id=AgentId.CHAT_AGENT,
        description="处理通用对话、直接回答用户问题，并在需要时协调记忆检索或 Vault 维护工具。",
        input_schema="用户当前消息、会话上下文和可选检索线索。",
        output_schema="自然语言回复、引用信息和可选工具执行结果。",
        typical_latency_ms=1200,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.SEMANTIC_ANALYSIS_AGENT,
        description="分析用户意图、判断是否需要上下文，并选择个人记忆、日常聊天或知识库等检索范围。",
        input_schema="用户原始消息和简要会话上下文。",
        output_schema="检索需求、检索范围、推荐查询词、回答风格和置信度。",
        typical_latency_ms=500,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.DIARY_MEMORY_EXTRACTOR_AGENT,
        description="从日常对话中提取适合沉淀为日记对象或长期记忆的候选信息。",
        input_schema="一段对话文本、来源消息和时间上下文。",
        output_schema="候选记忆条目、分类、证据和置信度。",
        typical_latency_ms=900,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.MEMORY_RETRIEVAL_AGENT,
        description="检索用户个人长期记忆，回答偏好、身份、关系和持续状态相关问题。",
        input_schema="检索关键词或问题、top_k 和个人记忆检索范围。",
        output_schema="相关记忆片段、来源路径、摘要和相关度。",
        typical_latency_ms=800,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.KNOWLEDGE_RETRIEVAL_AGENT,
        description="检索用户 Vault/Markdown 知识库，回答资料、文档和归档内容相关问题。",
        input_schema="知识库检索问题、top_k 和可选来源范围。",
        output_schema="相关知识片段、引用路径、摘要和相关度。",
        typical_latency_ms=900,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.WIKI_MANAGER_AGENT,
        description="规划 Vault 维护、查询归档、综合页面和 lint 报告，并在安全路径下管理 Wiki 页面。",
        input_schema="维护目标、待整理内容、引用、标签和目标路径约束。",
        output_schema="待确认的维护提案、Markdown 预览、lint 结果或页面管理结果。",
        typical_latency_ms=1500,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.MEMORY_PROPOSAL_AGENT,
        description="创建需要用户确认的长期记忆提案，确保敏感内容不会直接写入知识库。",
        input_schema="候选记忆内容、目标路径和来源消息 ID。",
        output_schema="记忆提案 ID、状态和待用户确认的内容。",
        typical_latency_ms=700,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.CONTINUITY_AGENT,
        description="维护连续性信号，识别开放话题、情绪能量、关系状态和身份相关长期脉络。",
        input_schema="会话摘要、近期消息和已有连续性状态。",
        output_schema="连续性提案、状态键、证据和置信度。",
        typical_latency_ms=900,
        can_retry=True,
        max_retries=1,
    ),
    AgentCapability(
        agent_id=AgentId.TASK_AGENT,
        description="识别并创建本地任务、提醒和待办事项，处理截止时间与提醒时间。",
        input_schema="用户任务描述、时间表达、时区和来源文本。",
        output_schema="任务 ID、提醒 ID、创建状态和面向用户的确认文本。",
        typical_latency_ms=700,
        can_retry=True,
        max_retries=1,
    ),
)


default_agent_registry = create_default_agent_registry()
