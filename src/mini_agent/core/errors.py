"""Core exception hierarchy."""


class AgentError(Exception):
    """Base exception for all agent errors."""


class LLMError(AgentError):
    """LLM API call failed."""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ToolError(AgentError):
    """Tool execution failed."""

    def __init__(self, message: str, tool_name: str = "") -> None:
        super().__init__(message)
        self.tool_name = tool_name


class MaxIterationsError(AgentError):
    """Agent loop hit the iteration limit."""


class UserCancelledError(AgentError):
    """User cancelled the running operation."""
