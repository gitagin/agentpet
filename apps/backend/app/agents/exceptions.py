class AgentError(Exception):
    code = "agent_error"


class AgentToolTimeoutError(AgentError):
    code = "agent_tool_timeout"

    def __init__(self, tool_name: str, timeout_seconds: int | float) -> None:
        super().__init__(f"Tool '{tool_name}' timed out after {timeout_seconds:g}s")
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds


class ActionLifecycleUnavailableError(AgentError):
    code = "action_lifecycle_unavailable"
