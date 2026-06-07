from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from app.models.enums import AgentId


AGENT_IDS: tuple[AgentId, ...] = (
    AgentId.CHAT_AGENT,
    AgentId.SEMANTIC_ANALYSIS_AGENT,
    AgentId.DIARY_MEMORY_EXTRACTOR_AGENT,
    AgentId.MEMORY_RETRIEVAL_AGENT,
    AgentId.KNOWLEDGE_RETRIEVAL_AGENT,
    AgentId.WIKI_MANAGER_AGENT,
    AgentId.MEMORY_PROPOSAL_AGENT,
    AgentId.CONTINUITY_AGENT,
    AgentId.TASK_AGENT,
)


class ChatModelError(Exception):
    """Raised when the configured LangChain model cannot produce a usable response."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "model_invocation_failed",
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or message


class AgentModelNotConfiguredError(ChatModelError):
    def __init__(self, agent_id: AgentId | str) -> None:
        normalized = AgentId(agent_id)
        super().__init__(
            "Agent 模型未配置，请先配置模型服务和 API Key。",
            code="agent_model_not_configured",
            detail=f"agent_id={normalized.value}",
        )
        self.agent_id = normalized


@runtime_checkable
class ChatModelClientProtocol(Protocol):
    def complete(self, *, user_message: str, system_prompt: str | None = None) -> str: ...


@runtime_checkable
class StreamingChatModelClientProtocol(ChatModelClientProtocol, Protocol):
    def stream_complete(self, *, user_message: str, system_prompt: str | None = None) -> AsyncIterator[str]: ...


ModelFactory = Callable[..., Any]
AgentFactory = Callable[[Any, str | None, Sequence[Any]], Any]


@dataclass(frozen=True, slots=True)
class ChatModelRunResult:
    text: str
    raw_result: Any


@dataclass(frozen=True, slots=True)
class AgentModelRegistry:
    clients: Mapping[AgentId, ChatModelClientProtocol]

    def get(self, agent_id: AgentId | str) -> ChatModelClientProtocol:
        normalized = AgentId(agent_id)
        client = self.clients.get(normalized)
        if client is None:
            raise AgentModelNotConfiguredError(normalized)
        return client


@dataclass(slots=True)
class LangChainGraphChatClient:
    """LangChain v1 agent wrapper.

    `langchain.agents.create_agent` runs on top of LangGraph, so this keeps the
    project on the LangChain/LangGraph path while exposing the existing small
    `complete(...)` boundary to the v0.1 runtime.
    """

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float = 30.0
    model_factory: ModelFactory | None = None
    agent_factory: AgentFactory | None = None

    async def complete(self, *, user_message: str, system_prompt: str | None = None) -> str:
        result = await self.complete_with_tools(
            user_message=user_message,
            system_prompt=system_prompt,
            tools=(),
        )
        return result.text

    async def stream_complete(self, *, user_message: str, system_prompt: str | None = None) -> AsyncIterator[str]:
        saw_text = False
        try:
            async for chunk in self._stream_model(
                user_message=user_message,
                system_prompt=system_prompt,
            ):
                text = _extract_stream_text(chunk)
                if not text:
                    continue
                saw_text = True
                yield text
        except ImportError as exc:
            raise ChatModelError(
                "LangChain dependency is not installed.",
                code="dependency_missing",
            ) from exc
        except TimeoutError as exc:
            raise classify_chat_model_exception(exc) from exc
        except Exception as exc:
            raise classify_chat_model_exception(exc) from exc

        if not saw_text:
            raise ChatModelError(
                "Model returned an empty response.",
                code="empty_response",
            )

    async def complete_with_tools(
        self,
        *,
        user_message: str,
        system_prompt: str | None = None,
        tools: Sequence[Any] = (),
    ) -> ChatModelRunResult:
        try:
            result = await asyncio.wait_for(
                self._invoke_agent(
                    user_message=user_message,
                    system_prompt=system_prompt,
                    tools=tools,
                ),
                timeout=max(self.timeout_seconds, 0.001),
            )
        except ImportError as exc:
            raise ChatModelError(
                "LangChain 依赖未安装，请先安装后端依赖。",
                code="dependency_missing",
            ) from exc
        except TimeoutError as exc:
            raise classify_chat_model_exception(exc) from exc
        except Exception as exc:
            raise classify_chat_model_exception(exc) from exc

        return ChatModelRunResult(text=_extract_text(result), raw_result=result)

    async def _invoke_agent(
        self,
        *,
        user_message: str,
        system_prompt: str | None,
        tools: Sequence[Any],
    ) -> Any:
        agent = self._create_agent(system_prompt, tools)
        payload = {"messages": [{"role": "user", "content": user_message}]}
        if hasattr(agent, "ainvoke"):
            return await agent.ainvoke(payload)
        return await asyncio.to_thread(agent.invoke, payload)

    async def _stream_model(
        self,
        *,
        user_message: str,
        system_prompt: str | None,
    ) -> AsyncIterator[Any]:
        model = self._create_model(streaming=True)
        messages: list[tuple[str, str]] = []
        if system_prompt:
            messages.append(("system", system_prompt))
        messages.append(("user", user_message))

        if hasattr(model, "astream"):
            stream = model.astream(messages)
            iterator = stream.__aiter__()
            deadline = asyncio.get_running_loop().time() + max(self.timeout_seconds, 0.001)
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError("chat model streaming timed out")
                try:
                    yield await asyncio.wait_for(iterator.__anext__(), timeout=remaining)
                except StopAsyncIteration:
                    return

        if hasattr(model, "invoke"):
            yield await asyncio.wait_for(
                asyncio.to_thread(model.invoke, messages),
                timeout=max(self.timeout_seconds, 0.001),
            )
            return

        yield await self.complete(user_message=user_message, system_prompt=system_prompt)

    def _create_agent(self, system_prompt: str | None, tools: Sequence[Any]) -> Any:
        model = self._create_model()
        factory = self.agent_factory or _default_agent_factory
        return factory(model, system_prompt, tools)

    def _create_model(self, *, streaming: bool = False) -> Any:
        factory = self.model_factory or _default_model_factory
        try:
            return factory(self, streaming=streaming)
        except TypeError as exc:
            if "streaming" not in str(exc):
                raise
            return factory(self)


def _default_model_factory(client: LangChainGraphChatClient, *, streaming: bool = False) -> Any:
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        api_key=client.api_key,
        base_url=client.base_url.rstrip("/"),
        model=client.model,
        timeout=client.timeout_seconds,
        streaming=streaming,
    )


def _default_agent_factory(model: Any, system_prompt: str | None, tools: Sequence[Any]) -> Any:
    from langchain.agents import create_agent

    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
    )


def _extract_text(result: Any) -> str:
    content = _extract_content(result)
    text = _coerce_content_to_text(content).strip()
    if not text:
        raise ChatModelError(
            "模型服务返回了空回复。",
            code="empty_response",
        )
    return text


def _extract_content(result: Any) -> Any:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list) and messages:
            for message in reversed(messages):
                content = _message_content(message)
                try:
                    if _coerce_content_to_text(content).strip():
                        return content
                except ChatModelError:
                    continue
            return _message_content(messages[-1])
        if "content" in result:
            return result["content"]
    return _message_content(result)


def _message_content(message: Any) -> Any:
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _coerce_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "".join(parts)
    raise ChatModelError(
        "模型服务响应格式无法转换为文本。",
        code="invalid_response",
    )


def _extract_stream_text(chunk: Any) -> str:
    if isinstance(chunk, tuple) and chunk:
        chunk = chunk[0]
    if isinstance(chunk, str):
        return chunk
    try:
        return _coerce_content_to_text(_message_content(chunk))
    except ChatModelError:
        return ""


def classify_chat_model_exception(exc: Exception) -> ChatModelError:
    """Convert provider/library exceptions into stable user-facing errors."""

    status_code = _extract_status_code(exc)
    text = _exception_chain_text(exc)
    lowered = text.lower()
    detail = _safe_exception_detail(text)

    if status_code in {401, 403} or "unauthorized" in lowered or "invalid api key" in lowered:
        return ChatModelError(
            "模型鉴权失败，请检查 API 密钥。",
            code="authentication_failed",
            detail=detail,
        )
    if _looks_like_unsupported_model(lowered):
        return ChatModelError(
            "模型名称不被当前服务支持，请检查模型名称。",
            code="unsupported_model",
            detail=detail,
        )
    if status_code == 429 or "rate limit" in lowered:
        return ChatModelError(
            "模型服务限流，请稍后重试。",
            code="rate_limited",
            detail=detail,
        )
    if status_code and 400 <= status_code < 500:
        return ChatModelError(
            "模型请求参数被服务拒绝，请检查服务地址和模型名称。",
            code="provider_bad_request",
            detail=detail,
        )
    if _looks_like_timeout(exc, lowered):
        return ChatModelError(
            "模型服务请求超时，请检查网络或服务地址。",
            code="provider_timeout",
            detail=detail,
        )
    if _looks_like_network_error(exc, lowered):
        return ChatModelError(
            "无法连接模型服务，请检查服务地址和网络。",
            code="provider_unreachable",
            detail=detail,
        )

    return ChatModelError(
        "模型调用失败，请检查模型服务地址、模型名称和 API 密钥。",
        code="model_invocation_failed",
        detail=detail,
    )


def _extract_status_code(exc: Exception) -> int | None:
    current: BaseException | None = exc
    while current is not None:
        status_code = getattr(current, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(current, "response", None)
        response_status = getattr(response, "status_code", None)
        if isinstance(response_status, int):
            return response_status
        current = current.__cause__ or current.__context__
    return None


def _exception_chain_text(exc: Exception) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(f"{current.__class__.__name__}: {current}")
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


def _safe_exception_detail(text: str) -> str:
    compact = " ".join(text.split())
    compact = _redact_secret_like_text(compact)
    if len(compact) > 400:
        return f"{compact[:400]}..."
    return compact


def _redact_secret_like_text(text: str) -> str:
    redacted = re.sub(r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}", r"\1[REDACTED]", text)
    redacted = re.sub(r"\b(?:sk|tp)-[A-Za-z0-9._~+/=-]{12,}\b", "[REDACTED]", redacted)
    return redacted


def _looks_like_unsupported_model(lowered: str) -> bool:
    model_signals = (
        "not supported model",
        "model_not_found",
        "model not found",
        "unsupported model",
        "invalid model",
        "does not exist",
    )
    return any(signal in lowered for signal in model_signals)


def _looks_like_timeout(exc: Exception, lowered: str) -> bool:
    if "timeout" in lowered or "timed out" in lowered:
        return True
    return any("timeout" in item.__class__.__name__.lower() for item in _exception_chain(exc))


def _looks_like_network_error(exc: Exception, lowered: str) -> bool:
    network_signals = (
        "connection error",
        "connecterror",
        "connect error",
        "name or service not known",
        "nodename nor servname",
        "failed to establish",
        "network is unreachable",
        "connection refused",
        "getaddrinfo",
    )
    if any(signal in lowered for signal in network_signals):
        return True
    return any(
        item.__class__.__name__.lower()
        in {"connectionerror", "connecterror", "networkerror", "httpconnectionerror"}
        for item in _exception_chain(exc)
    )


def _exception_chain(exc: Exception) -> list[BaseException]:
    items: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None:
        items.append(current)
        current = current.__cause__ or current.__context__
    return items
