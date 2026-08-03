"""MCP tool adapter -- wraps MCP-discovered tools as internal Tool objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

if TYPE_CHECKING:
    from mini_agent.tools.mcp.client import MCPManager


class MCPToolAdapter(Tool):
    """Wraps an MCP-discovered tool as an internal Tool."""

    def __init__(
        self,
        server_name: str,
        tool_info: dict[str, Any],
        manager: MCPManager,
    ) -> None:
        self._server_name = server_name
        self._tool_info = tool_info
        self._manager = manager
        self._name = f"mcp_{server_name}_{tool_info.get('name', 'unknown')}"

    @property
    def schema(self) -> ToolSchema:
        info = self._tool_info
        input_schema = info.get("inputSchema", {})
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        parameters = []
        for prop_name, prop_info in properties.items():
            parameters.append(
                ToolParameter(
                    name=prop_name,
                    type=prop_info.get("type", "string"),
                    description=prop_info.get("description", ""),
                    required=prop_name in required,
                )
            )

        return ToolSchema(
            name=self._name,
            description=info.get("description", ""),
            parameters=parameters,
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        original_name = self._tool_info.get("name", "")
        return await self._manager.call_tool(self._server_name, original_name, kwargs)
