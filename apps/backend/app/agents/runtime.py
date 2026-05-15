from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Any, AsyncIterator

from app.models.api import (
    MemoryProposalActionResponse,
    MemoryProposalCreateRequest,
    MemorySearchResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    WikiPageResponse,
    WikiPageWriteRequest,
)
from app.models.enums import AgentId, AgentIntent, AgentRunStatus, MemoryProposalType
from app.services.chat_model import AgentModelRegistry
from app.services.memory_policy import evaluate_memory_content

from .events import (
    AgentCitationEvent,
    AgentContinuitySignalEvent,
    AgentDoneEvent,
    AgentErrorEvent,
    AgentEventBase,
    AgentMemoryProposalEvent,
    AgentStatusEvent,
    AgentTaskEvent,
    AgentTokenEvent,
    AgentWikiProposalEvent,
)
from .intent import route_intent
from .services import (
    ChatModelServiceProtocol,
    MemoryProposalServiceProtocol,
    RetrievalServiceProtocol,
    TaskServiceProtocol,
    ContinuityServiceProtocol,
    WikiServiceProtocol,
    WikiWorkflowServiceProtocol,
)
from .state import AgentState


DEFAULT_MEMORY_TARGET_PATH = "Inbox/Pending Memories.md"


class ModelInvocationFailedError(Exception):
    code = "model_invocation_failed"

    def __init__(self) -> None:
        super().__init__("模型调用失败，请检查模型服务地址、模型名称和 API 密钥。")


@dataclass(slots=True)
class AgentRuntimeServices:
    retrieval: RetrievalServiceProtocol | None = None
    memory: MemoryProposalServiceProtocol | None = None
    tasks: TaskServiceProtocol | None = None
    wiki: WikiServiceProtocol | None = None
    wiki_workflow: WikiWorkflowServiceProtocol | None = None
    continuity: ContinuityServiceProtocol | None = None
    chat_model: ChatModelServiceProtocol | None = None
    model_registry: AgentModelRegistry | None = None


class AgentToolRuntimeBase:
    def __init__(self, services: AgentRuntimeServices | None = None) -> None:
        self.services = services or AgentRuntimeServices()

    async def run(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        state.route = route_intent(state.user_message)
        yield AgentStatusEvent(
            agent_run_id=state.agent_run_id,
            status=state.status,
            intent=state.route.intent,
            message=state.route.reason,
        )

        try:
            if state.route.intent == AgentIntent.SEARCH_MEMORY:
                async for event in self._run_search_memory(state):
                    yield event
            elif state.route.intent == AgentIntent.PROPOSE_MEMORY:
                async for event in self._run_propose_memory(state):
                    yield event
            elif state.route.intent == AgentIntent.MANAGE_WIKI:
                async for event in self._run_manage_wiki(state):
                    yield event
            elif state.route.intent == AgentIntent.CREATE_TASK:
                async for event in self._run_create_task(state):
                    yield event
            else:
                async for event in self._run_chat(state):
                    yield event

            state.status = AgentRunStatus.SUCCESS
            yield AgentDoneEvent(
                agent_run_id=state.agent_run_id,
                intent=state.route.intent,
                text=state.response_text,
            )
        except Exception as exc:
            state.status = AgentRunStatus.FAILED
            state.error_code = getattr(exc, "code", exc.__class__.__name__)
            state.error_message = str(exc)
            yield AgentErrorEvent(
                agent_run_id=state.agent_run_id,
                code=state.error_code,
                message=state.error_message,
            )

    async def _run_chat(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        chat_model = self._model_for(AgentId.CHAT_AGENT)
        signal = _continuity_signal(self.services.continuity)
        if signal is not None:
            yield _continuity_signal_event(state.agent_run_id, signal)
        if chat_model is not None:
            try:
                response = await _maybe_await(
                    chat_model.complete(
                        user_message=_message_with_continuity_context(
                            state.user_message,
                            _continuity_presence_context_block(self.services.continuity),
                        ),
                        system_prompt=_chat_system_prompt(),
                    )
                )
            except Exception as exc:
                if hasattr(exc, "code"):
                    raise
                raise ModelInvocationFailedError()
            else:
                state.response_text = response
                for chunk in _chunk_text(response):
                    yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=chunk)
                return

        response = "我可以帮你聊天、搜索记忆、创建待确认记忆提案，以及记录任务。"
        state.response_text = response
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)

    def _model_for(self, agent_id: AgentId) -> ChatModelServiceProtocol | None:
        if self.services.model_registry is not None:
            return self.services.model_registry.get(agent_id)
        return self.services.chat_model

    async def _run_search_memory(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        if self.services.retrieval is None:
            response = "记忆搜索暂不可用。"
            state.response_text = response
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
            return

        query = _strip_search_command(state.user_message)
        results = await _maybe_await(self.services.retrieval.search(query, top_k=5, mode="fts"))
        search_response = _coerce_search_response(results)
        state.citations = search_response.results

        if not state.citations:
            response = "我已经搜索了记忆，但没有找到匹配的笔记。"
            state.response_text = response
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
            return

        lines = ["我找到了以下记忆匹配："]
        for result in state.citations:
            lines.append(f"- {result.relative_path}: {result.snippet}")
            yield AgentCitationEvent(agent_run_id=state.agent_run_id, citation=result)

        state.response_text = "\n".join(lines)
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=state.response_text)

    async def _run_propose_memory(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        if self.services.memory is None:
            response = "记忆提案功能暂不可用。"
            state.response_text = response
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
            return

        content = _strip_memory_command(state.user_message)
        policy = evaluate_memory_content(content)
        if not policy.allowed:
            raise SensitiveMemoryRejectedError(policy.reason)

        request = MemoryProposalCreateRequest(
            type=MemoryProposalType.FACT,
            content=content,
            target_path=DEFAULT_MEMORY_TARGET_PATH,
            source_message_id=state.message_id,
        )
        proposal = await _maybe_await(self.services.memory.create_proposal(request))
        proposal_response = _coerce_memory_response(proposal)
        state.proposal_id = proposal_response.proposal_id

        response = "我已创建一条待确认的记忆提案，请审核后再写入。"
        state.response_text = response
        yield AgentMemoryProposalEvent(
            agent_run_id=state.agent_run_id,
            proposal_id=proposal_response.proposal_id,
            status=proposal_response.status,
            target_path=request.target_path,
        )
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)

    async def _run_create_task(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        if self.services.tasks is None:
            response = "任务创建功能暂不可用。"
            state.response_text = response
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
            return

        request = TaskCreateRequest(
            title=_task_title(state.user_message),
            source_text=state.user_message,
        )
        task = await _maybe_await(self.services.tasks.create(request))
        task_response = _coerce_task_response(task)
        state.task_id = task_response.task_id
        state.reminder_id = task_response.reminder_id

        response = "我已创建任务。"
        state.response_text = response
        yield AgentTaskEvent(
            agent_run_id=state.agent_run_id,
            task_id=task_response.task_id,
            status=task_response.status,
            reminder_id=task_response.reminder_id,
            title=task_response.metadata.get("title") or request.title,
            reminder_status=task_response.metadata.get("reminder_status") or None,
            remind_at=task_response.metadata.get("remind_at") or None,
            timezone=task_response.metadata.get("timezone") or None,
            timezone_label=task_response.metadata.get("timezone_label") or None,
        )
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)

    async def _run_manage_wiki(self, state: AgentState) -> AsyncIterator[AgentEventBase]:
        if self.services.wiki_workflow is None:
            response = "Vault 维护智能体暂时不可用。"
            state.response_text = response
            yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)
            return

        from app.models.api import WikiIngestPreviewRequest, WikiIngestReviewRequest

        title = _wiki_title(state.user_message)
        preview = await _maybe_await(
            self.services.wiki_workflow.preview_ingest(
                WikiIngestPreviewRequest(
                    title=title,
                    content=_strip_wiki_command(state.user_message),
                    source_type="agent_chat",
                    tags=["agent-chat", "wiki-proposal"],
                    max_pages=5,
                )
            )
        )
        review = await _maybe_await(
            self.services.wiki_workflow.review_ingest(
                WikiIngestReviewRequest(run_id=preview.run_id)
            )
        )
        state.proposal_id = preview.run_id
        yield AgentWikiProposalEvent(
            agent_run_id=state.agent_run_id,
            status=preview.status,
            title=title,
            run_id=preview.run_id,
            source_id=preview.source_id,
            source_hash=preview.source_hash,
            review_id=review.review_id,
            review_status=review.status,
            summary=preview.summary,
            review_summary=review.summary,
            target_paths=[plan.target_path for plan in preview.page_plans],
            recommended_targets=review.recommended_targets,
            findings=[finding.model_dump(mode="json") for finding in review.findings],
            source_message_id=state.message_id,
        )
        targets = review.recommended_targets or [plan.target_path for plan in preview.page_plans]
        response = (
            f"已拟好 Vault 写入计划：{preview.run_id}。"
            f"建议目标 {len(targets)} 个；确认后才会写入 Markdown。"
        )
        state.response_text = response
        yield AgentTokenEvent(agent_run_id=state.agent_run_id, text=response)


class SensitiveMemoryRejectedError(Exception):
    code = "sensitive_memory_rejected"

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or "sensitive_content"
        super().__init__("疑似密钥或凭据的敏感内容不能保存为长期记忆。")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _chat_system_prompt() -> str:
    return (
        "你是住在用户桌面上的中文桌宠伙伴，不是文档查询助手。"
        "默认用自然、温和、简洁的中文陪用户聊天、解释、追问、给建议，可以有一点轻松的桌宠语气。"
        "知识库只是你的“记忆本”能力：只有用户明确要求查本地知识库、笔记、记忆、文档、之前记录，"
        "或问题显然依赖用户私有资料时，才使用或引用检索上下文。"
        "如果没有检索上下文，就按一般对话正常回答；不要先声明要搜索，也不要把普通问题变成检索任务。"
        "如果用户明确查记忆但没有找到资料，要坦诚说明没有翻到，不要编造用户记忆；可以继续追问背景，"
        "也可以说明自己能先按一般经验陪用户分析。"
        "用户明确要求保存长期信息时才创建记忆提案；明确要求待办、计划或提醒时才创建任务。"
        "不要声称已经写入记忆或创建任务，除非工具事件已经完成。"
    )


def _continuity_context_block(continuity: ContinuityServiceProtocol | None) -> str:
    if continuity is None:
        return ""
    try:
        return continuity.context_block()
    except Exception:
        return ""


def _continuity_presence_context_block(continuity: ContinuityServiceProtocol | None) -> str:
    if continuity is None:
        return ""
    try:
        if hasattr(continuity, "presence_context_block"):
            return continuity.presence_context_block()
        return continuity.context_block()
    except Exception:
        return ""


def _continuity_signal(continuity: ContinuityServiceProtocol | None) -> object | None:
    if continuity is None:
        return None
    try:
        if hasattr(continuity, "presence_signal"):
            return continuity.presence_signal()
    except Exception:
        return None
    return None


def _continuity_signal_event(agent_run_id: str, signal: object) -> AgentContinuitySignalEvent:
    return AgentContinuitySignalEvent(
        agent_run_id=agent_run_id,
        kind=str(getattr(signal, "kind", "relationship")),
        title=str(getattr(signal, "title", "连续性在场")),
        summary=str(getattr(signal, "summary", "")),
        intensity=str(getattr(signal, "intensity", "medium")),
        display_hint=str(getattr(signal, "display_hint", "")),
        source_state_keys=list(getattr(signal, "source_state_keys", ())),
    )


def _message_with_continuity_context(user_message: str, continuity_block: str) -> str:
    if not continuity_block.strip():
        return user_message
    return (
        f"{continuity_block.strip()}\n\n"
        f"Current user message:\n{user_message}"
    )


def _chunk_text(text: str, size: int = 80) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _coerce_search_response(value: Any) -> MemorySearchResponse:
    if isinstance(value, MemorySearchResponse):
        return value
    if isinstance(value, dict):
        return MemorySearchResponse.model_validate(value)
    return MemorySearchResponse(results=list(value))


def _coerce_memory_response(value: Any) -> MemoryProposalActionResponse:
    if isinstance(value, MemoryProposalActionResponse):
        return value
    return MemoryProposalActionResponse.model_validate(value)


def _coerce_task_response(value: Any) -> TaskCreateResponse:
    if isinstance(value, TaskCreateResponse):
        return value
    return TaskCreateResponse.model_validate(value)


def _coerce_wiki_response(value: Any) -> WikiPageResponse:
    if isinstance(value, WikiPageResponse):
        return value
    return WikiPageResponse.model_validate(value)


def _strip_memory_command(message: str) -> str:
    prefixes = (
        "remember this:",
        "remember that:",
        "remember:",
        "please remember",
        "save this memory:",
        "记住：",
        "记住:",
        "记住",
        "记得：",
        "记得:",
        "记得",
        "保存记忆：",
        "保存记忆:",
        "加入记忆：",
        "加入记忆:",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped


def _strip_search_command(message: str) -> str:
    prefixes = (
        "search memory for",
        "search memories for",
        "find in memory",
        "lookup memory",
        "recall",
        "搜索记忆：",
        "搜索记忆:",
        "搜索记忆",
        "查找记忆：",
        "查找记忆:",
        "查找记忆",
        "检索记忆：",
        "检索记忆:",
        "检索记忆",
        "回忆",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped


def _task_title(message: str) -> str:
    title = message.strip()
    delayed_reminder = re.match(
        r"^(?:\d{1,2}|[零〇一二两三四五六七八九十]{1,4})\s*(?:秒钟|秒|分钟|小时)\s*后\s*(?:提醒我|提醒)\s*(?P<title>.+)$",
        title,
        flags=re.IGNORECASE,
    )
    if delayed_reminder is not None:
        title = delayed_reminder.group("title").strip(" :：")
        return title or message.strip()
    for prefix in (
        "remind me to",
        "reminder:",
        "todo:",
        "task:",
        "提醒我：",
        "提醒我:",
        "提醒我",
        "提醒：",
        "提醒:",
        "提醒",
        "待办：",
        "待办:",
        "任务：",
        "任务:",
    ):
        if title.lower().startswith(prefix):
            title = title[len(prefix) :].strip(" :：")
            break
    return title or message.strip()


def _wiki_title(message: str) -> str:
    content = _strip_wiki_command(message)
    first_line = next((line.strip(" #") for line in content.splitlines() if line.strip()), "")
    if ":" in first_line:
        first_line = first_line.split(":", 1)[0].strip()
    if "：" in first_line:
        first_line = first_line.split("：", 1)[0].strip()
    return first_line[:60] or "Knowledge Note"


def _strip_wiki_command(message: str) -> str:
    prefixes = (
        "add to wiki:",
        "update wiki:",
        "create wiki page:",
        "save to knowledge base:",
        "archive to wiki:",
        "organize into wiki:",
        "写入wiki：",
        "写入wiki:",
        "更新wiki：",
        "更新wiki:",
        "整理到wiki：",
        "整理到wiki:",
        "保存到知识库：",
        "保存到知识库:",
        "归档到知识库：",
        "归档到知识库:",
        "创建wiki页面：",
        "创建wiki页面:",
    )
    stripped = message.strip()
    lowered = stripped.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix.lower()):
            return stripped[len(prefix) :].strip(" :：") or stripped
    return stripped
