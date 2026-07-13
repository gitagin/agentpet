from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from app.agents.registry import AgentRegistry
from app.agents.state import AgentInvocationResult, NegotiationState
from app.models.enums import AgentId


async def run_agent(
    agent_id: AgentId,
    input_query: str,
    state: NegotiationState,
    registry: AgentRegistry,
    *,
    timeout_seconds: float | None = None,
) -> AgentInvocationResult:
    start = time.monotonic()
    tool_calls: list[str] = []
    try:
        handler = registry.get_handler(agent_id)
        raw_output = handler(input_query, state)
        if timeout_seconds is not None:
            output = await asyncio.wait_for(
                _resolve_handler_output(raw_output),
                timeout=max(float(timeout_seconds), 0.001),
            )
        else:
            output = await _resolve_handler_output(raw_output)
        if not isinstance(output, dict):
            output = {"result": output}
        confidence = output.get("confidence")
        if confidence is None:
            confidence = 0.6 if output.get("results") else 0.0
        tool_calls = list(output.get("tool_calls", [])) if isinstance(output.get("tool_calls"), list) else []
    except (TimeoutError, asyncio.TimeoutError):
        timeout = max(float(timeout_seconds or 0.001), 0.001)
        output = {
            "error": f"Agent '{agent_id.value}' timed out after {timeout:g}s",
            "error_code": "agent_timeout",
        }
        confidence = 0.0
    except Exception as exc:
        output = {"error": str(exc), "error_code": "agent_invocation_failed"}
        confidence = 0.0

    latency_ms = max(1, int((time.monotonic() - start) * 1000))
    return AgentInvocationResult(
        agent_id=agent_id,
        round=state.round,
        input_query=input_query,
        output=output,
        confidence=confidence,
        latency_ms=latency_ms,
        tool_calls=tool_calls,
    )


async def _resolve_handler_output(raw_output: Any) -> Any:
    return await raw_output if inspect.isawaitable(raw_output) else raw_output
