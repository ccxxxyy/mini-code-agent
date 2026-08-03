"""Core exception hierarchy. 核心异常层次结构。"""


class AgentError(Exception):
    """Base exception for all agent errors. 所有 Agent 错误的基类异常。"""


class LLMError(AgentError):
    """LLM API call failed. LLM API 调用失败。"""

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ToolError(AgentError):
    """Tool execution failed. 工具执行失败。"""

    def __init__(self, message: str, tool_name: str = "") -> None:
        super().__init__(message)
        self.tool_name = tool_name


class MaxIterationsError(AgentError):
    """Agent loop hit the iteration limit. Agent 循环达到迭代次数上限。"""


class UserCancelledError(AgentError):
    """User cancelled the running operation. 用户取消了正在运行的操作。"""
