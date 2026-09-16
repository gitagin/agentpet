from __future__ import annotations

import asyncio

import pytest

from app.services.chat_model import (
    ChatModelError,
    LangChainGraphChatClient,
    _default_model_factory,
    _openai_auth_kwargs,
    classify_chat_model_exception,
)


class FakeAIMessage:
    def __init__(self, content):
        self.content = content


class FakeAgent:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def ainvoke(self, payload):
        self.calls.append(payload)
        return self.result


class FailingAgent:
    async def ainvoke(self, payload):
        raise RuntimeError("provider down")


class AuthFailingAgent:
    async def ainvoke(self, payload):
        class AuthError(Exception):
            status_code = 401

        raise AuthError("invalid api key")


class HangingAgent:
    async def ainvoke(self, payload):
        await asyncio.sleep(10)
        return {"messages": [FakeAIMessage("too late")]}


class FakeStreamingModel:
    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = []

    async def astream(self, messages):
        self.calls.append(messages)
        for chunk in self.chunks:
            yield FakeAIMessage(chunk)


class PacedStreamingModel:
    def __init__(self, delays):
        self.delays = delays

    async def astream(self, messages):
        for delay in self.delays:
            await asyncio.sleep(delay)
            yield FakeAIMessage("字")


def test_langchain_graph_client_uses_create_agent_boundary() -> None:
    captured = {}
    fake_agent = FakeAgent(
        {"messages": [FakeAIMessage("模型回复内容")]}
    )

    def fake_model_factory(client: LangChainGraphChatClient):
        captured["api_key"] = client.api_key
        captured["base_url"] = client.base_url
        captured["model"] = client.model
        captured["timeout_seconds"] = client.timeout_seconds
        return "fake-model"

    def fake_agent_factory(model, system_prompt, tools):
        captured["agent_model"] = model
        captured["system_prompt"] = system_prompt
        captured["tools"] = list(tools)
        return fake_agent

    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1/",
        model="demo-model",
        timeout_seconds=12,
        model_factory=fake_model_factory,
        agent_factory=fake_agent_factory,
    )

    result = asyncio.run(
        async_complete(client, user_message="你好", system_prompt="使用中文回答。")
    )

    assert result == "模型回复内容"
    assert captured == {
        "api_key": "sk-test",
        "base_url": "https://example.test/v1/",
        "model": "demo-model",
        "timeout_seconds": 12,
        "agent_model": "fake-model",
        "system_prompt": "使用中文回答。",
        "tools": [],
    }
    assert fake_agent.calls == [{"messages": [{"role": "user", "content": "你好"}]}]


def test_langchain_graph_client_streams_model_chunks_without_agent_boundary() -> None:
    model = FakeStreamingModel(["你", "好"])
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: model,
    )

    chunks = asyncio.run(async_collect_stream(client, user_message="hello", system_prompt="system prompt"))

    assert chunks == ["你", "好"]
    assert model.calls == [[("system", "system prompt"), ("user", "hello")]]


def test_langchain_graph_client_extracts_content_blocks() -> None:
    fake_agent = FakeAgent(
        {"messages": [FakeAIMessage([{"type": "text", "text": "第一段"}, {"content": "第二段"}])]}
    )
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: fake_agent,
    )

    result = asyncio.run(async_complete(client, user_message="你好"))

    assert result == "第一段第二段"


def test_langchain_graph_client_uses_last_non_empty_message() -> None:
    fake_agent = FakeAgent(
        {"messages": [FakeAIMessage("tool-backed answer"), FakeAIMessage("   ")]}
    )
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: fake_agent,
    )

    result = asyncio.run(async_complete(client, user_message="hello"))

    assert result == "tool-backed answer"


def test_langchain_graph_client_passes_tools_to_create_agent() -> None:
    captured = {}
    fake_agent = FakeAgent({"messages": [FakeAIMessage("已调用工具")]})
    fake_tools = [object(), object()]

    def fake_agent_factory(model, system_prompt, tools):
        captured["tools"] = list(tools)
        return fake_agent

    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=fake_agent_factory,
    )

    result = asyncio.run(
        client.complete_with_tools(
            user_message="你好",
            system_prompt="使用工具。",
            tools=fake_tools,
        )
    )

    assert result.text == "已调用工具"
    assert result.raw_result == {"messages": [fake_agent.result["messages"][0]]}
    assert captured["tools"] == fake_tools


def test_openai_auth_kwargs_uses_api_key_header_for_xiaomi_mimo() -> None:
    kwargs = _openai_auth_kwargs(
        api_key="mimo-secret-value",
        base_url="https://token-plan-sgp.xiaomimimo.com/v1/",
    )

    assert kwargs == {
        "api_key": "mimo-secret-value",
        "default_headers": {"api-key": "mimo-secret-value", "Authorization": ""},
    }


def test_openai_auth_kwargs_keeps_bearer_for_other_openai_compatible_hosts() -> None:
    kwargs = _openai_auth_kwargs(
        api_key="deepseek-secret-value",
        base_url="https://api.deepseek.com/v1",
    )

    assert kwargs == {"api_key": "deepseek-secret-value"}


def test_default_model_factory_removes_bearer_for_xiaomi_mimo_host() -> None:
    pytest.importorskip("langchain_openai")
    client = LangChainGraphChatClient(
        api_key="mimo-secret-value",
        base_url="https://api.xiaomimimo.com/v1/",
        model="mimo-v2.5-pro",
    )

    model = _default_model_factory(client)
    headers = model.root_client.default_headers

    assert headers["api-key"] == "mimo-secret-value"
    assert headers.get("Authorization", "") == ""


def test_default_model_factory_keeps_bearer_for_deepseek_host() -> None:
    pytest.importorskip("langchain_openai")
    client = LangChainGraphChatClient(
        api_key="deepseek-secret-value",
        base_url="https://api.deepseek.com/v1/",
        model="deepseek-v4-pro",
    )

    model = _default_model_factory(client)
    headers = model.root_client.auth_headers

    assert headers["Authorization"] == "Bearer deepseek-secret-value"
    assert "api-key" not in headers


def test_xiaomi_mimo_auth_failure_retries_with_bearer_scheme() -> None:
    attempts = []

    def fake_model_factory(client: LangChainGraphChatClient, *, streaming: bool = False):
        attempts.append(client.auth_scheme)
        return client.auth_scheme or "api-key"

    def fake_agent_factory(model, _system_prompt, _tools):
        if model == "api-key":
            return AuthFailingAgent()
        return FakeAgent({"messages": [FakeAIMessage("OK")]})

    client = LangChainGraphChatClient(
        api_key="mimo-secret-value",
        base_url="https://api.xiaomimimo.com/v1/",
        model="mimo-v2.5-pro",
        model_factory=fake_model_factory,
        agent_factory=fake_agent_factory,
    )

    result = asyncio.run(async_complete(client, user_message="hello"))

    assert result == "OK"
    assert attempts == [None, "bearer"]


def test_langchain_graph_client_wraps_agent_errors() -> None:
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: FailingAgent(),
    )

    with pytest.raises(ChatModelError, match="模型调用失败"):
        asyncio.run(async_complete(client, user_message="你好"))


def test_langchain_graph_client_times_out_hanging_agent() -> None:
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        timeout_seconds=0.01,
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: HangingAgent(),
    )

    with pytest.raises(ChatModelError) as exc_info:
        asyncio.run(async_complete(client, user_message="你好"))

    assert exc_info.value.code == "provider_timeout"
    assert "超时" in str(exc_info.value)


def test_chat_model_error_classifies_unsupported_model() -> None:
    class BadRequestError(Exception):
        status_code = 400

    error = classify_chat_model_exception(BadRequestError("Not supported model MiMo-v2.5"))

    assert error.code == "unsupported_model"
    assert "模型名称" in str(error)


def test_chat_model_error_classifies_authentication_failure() -> None:
    class AuthError(Exception):
        status_code = 401

    error = classify_chat_model_exception(AuthError("invalid api key"))

    assert error.code == "authentication_failed"
    assert "API 密钥" in str(error)


def test_chat_model_error_distinguishes_quota_exhaustion_from_rate_limit() -> None:
    class ProviderError(Exception):
        status_code = 429

    quota_error = classify_chat_model_exception(
        ProviderError("insufficient_quota: credit_balance_exhausted")
    )
    rate_error = classify_chat_model_exception(ProviderError("rate limit reached for requests"))

    assert quota_error.code == "quota_exhausted"
    assert rate_error.code == "rate_limited"


def test_chat_model_error_redacts_secret_like_details() -> None:
    error = classify_chat_model_exception(RuntimeError("provider echoed tp-secretvalue1234567890"))

    assert "tp-secretvalue" not in error.detail
    assert "[REDACTED]" in error.detail


class FlakyThenSuccessAgent:
    """第一次抛限流，第二次成功——验证通用退避重试。"""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, payload):
        self.calls += 1
        if self.calls == 1:
            class RateLimitError(Exception):
                status_code = 429

            raise RateLimitError("rate limit reached")
        return {"messages": [FakeAIMessage("recovered answer")]}


def test_langchain_graph_client_retries_rate_limited_once() -> None:
    fake_agent = FlakyThenSuccessAgent()
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: fake_agent,
    )

    text = asyncio.run(async_complete(client, user_message="你好"))

    assert text == "recovered answer"
    assert fake_agent.calls == 2


class AlwaysRateLimitedAgent:
    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, payload):
        self.calls += 1

        class RateLimitError(Exception):
            status_code = 429

        raise RateLimitError("rate limit reached")


def test_langchain_graph_client_gives_up_after_retry_budget() -> None:
    fake_agent = AlwaysRateLimitedAgent()
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: fake_agent,
    )

    with pytest.raises(ChatModelError, match="限流"):
        asyncio.run(async_complete(client, user_message="你好"))

    # 默认 tuning_chat_retry_attempts=1：首次调用 + 1 次重试。
    assert fake_agent.calls == 2


def test_langchain_graph_client_rejects_empty_response() -> None:
    fake_agent = FakeAgent({"messages": [FakeAIMessage("   ")]})
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        model_factory=lambda _client: "fake-model",
        agent_factory=lambda _model, _prompt, _tools: fake_agent,
    )

    with pytest.raises(ChatModelError, match="空回复"):
        asyncio.run(async_complete(client, user_message="你好"))


async def async_complete(
    client: LangChainGraphChatClient,
    *,
    user_message: str,
    system_prompt: str | None = None,
) -> str:
    return await client.complete(user_message=user_message, system_prompt=system_prompt)


def test_langchain_graph_client_stream_uses_inactivity_budget_not_total_duration() -> None:
    # 每个 token 间隔 0.02s，总时长 0.10s 超过 timeout 0.05s：
    # 旧的全流截止逻辑会在 0.05s 处掐断，新的间隔预算应收全 5 个 token。
    model = PacedStreamingModel([0.02] * 5)
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        timeout_seconds=0.05,
        model_factory=lambda _client: model,
    )

    chunks = asyncio.run(async_collect_stream(client, user_message="hello"))

    assert chunks == ["字"] * 5


def test_langchain_graph_client_stream_times_out_when_tokens_stall() -> None:
    # 第一个 token 到达后停顿 0.12s > timeout 0.05s：按不活动预算报超时。
    model = PacedStreamingModel([0.01, 0.12])
    client = LangChainGraphChatClient(
        api_key="sk-test",
        base_url="https://example.test/v1",
        model="demo-model",
        timeout_seconds=0.05,
        model_factory=lambda _client: model,
    )

    with pytest.raises(ChatModelError) as exc_info:
        asyncio.run(async_collect_stream(client, user_message="hello"))

    assert exc_info.value.code == "provider_timeout"


async def async_collect_stream(
    client: LangChainGraphChatClient,
    *,
    user_message: str,
    system_prompt: str | None = None,
) -> list[str]:
    return [chunk async for chunk in client.stream_complete(user_message=user_message, system_prompt=system_prompt)]
