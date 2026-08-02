"""Tool system foundation: Tool ABC, ToolRegistry, ToolContext."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolResult
from mini_agent.models.session import Session


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolSchema:
    """JSON Schema-like description of a tool."""

    name: str
    description: str
    parameters: list[ToolParameter]

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
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
    """Context passed to every tool execution."""

    working_dir: Path
    session: Session
    event_bus: EventBus
    config: AgentConfig


class Tool(ABC):
    """Base class for all tools (builtin + MCP-adapted)."""

    @property
    @abstractmethod
    def schema(self) -> ToolSchema:
        """Return the tool's schema for LLM registration."""
        ...

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments. Returns result."""
        ...

    def validate_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against schema. Fills defaults, raises ValueError."""
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
        """Helper to build an error ToolResult."""
        return ToolResult(
            call_id=call_id,
            name=self.schema.name,
            output=message,
            is_error=True,
        )


class ToolRegistry:
    """Central registry of all available tools."""

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
        """Return all tool schemas in OpenAI function calling format."""
        return [t.schema.to_json_schema() for t in self._tools.values()]

    def clone(self) -> ToolRegistry:
        """Create an independent copy (for sub-agents)."""
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
