"""Tool system foundation: Tool ABC, ToolRegistry, ToolContext.
工具系统基础：Tool 抽象基类、ToolRegistry、ToolContext。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolResult
from mini_agent.models.session import Session

if TYPE_CHECKING:
    from mini_agent.core.subagent import SubAgentManager


@dataclass
class ToolParameter:
    """Schema for a single tool parameter. 单个工具参数的 schema。"""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolSchema:
    """JSON Schema-like description of a tool. 工具的类 JSON Schema 描述。"""

    name: str
    description: str
    parameters: list[ToolParameter]

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format. 转换为 OpenAI function calling 格式。"""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass
class ToolContext:
    """Context passed to every tool execution. 传递给每次工具执行的上下文。"""

    working_dir: Path
    session: Session
    event_bus: EventBus
    config: AgentConfig
    subagent_manager: SubAgentManager | None = None


class Tool(ABC):
    """Base class for all tools (builtin + MCP-adapted).
    所有工具的基类（内置工具 + MCP 适配工具）。"""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema for LLM registration. 返回用于 LLM 注册的工具 schema。"""
        ...

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments. Returns result.
        使用给定参数执行工具。返回执行结果。"""
        ...

    def validate_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against schema. Fills defaults, raises ValueError.
        根据 schema 校验参数。填充默认值，校验失败时抛出 ValueError。"""
        schema = self.schema
        validated: dict[str, Any] = {}
        for p in schema.parameters:
            if p.name in kwargs:
                validated[p.name] = kwargs[p.name]
            elif p.required:
                raise ValueError(f"Missing required parameter '{p.name}' for tool '{schema.name}'")
            elif p.default is not None:
                validated[p.name] = p.default
        return validated

    def error_result(self, call_id: str, message: str) -> ToolResult:
        """Helper to build an error ToolResult. 构建错误 ToolResult 的辅助方法。"""
        return ToolResult(
            call_id=call_id,
            name=self.schema.name,
            output=message,
            is_error=True,
        )


class ToolRegistry:
    """Central registry of all available tools. 所有可用工具的中央 registry。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.schema.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return all tool schemas in OpenAI function calling format.
        以 OpenAI function calling 格式返回所有工具 schema。"""
        return [t.schema.to_json_schema() for t in self._tools.values()]

    def clone(self) -> ToolRegistry:
        """Create an independent copy (for sub-agents). 创建独立副本（供子 Agent 使用）。"""
        new = ToolRegistry()
        new._tools = dict(self._tools)
        return new

    def filter(
        self,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> list[Tool]:
        tools = self.list_tools()
        if allowed is not None:
            tools = [t for t in tools if t.schema.name in allowed]
        if denied:
            tools = [t for t in tools if t.schema.name not in denied]
        return tools
