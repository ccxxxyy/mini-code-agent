"""MCP tool adapter -- wraps MCP-discovered tools as internal Tool objects.
MCP 工具适配器——把 MCP 发现的工具包装为内部 Tool 对象。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

if TYPE_CHECKING:
    from mini_agent.tools.mcp.client import MCPManager


class MCPToolAdapter(Tool):
    """Wraps an MCP-discovered tool as an internal Tool.
    把 MCP 发现的工具包装为内部 Tool。"""

    # External-process side effects: cannot be verified read-only, so plan
    # mode denies MCP tools. 进程外副作用无法验证只读——plan 模式拒绝。
    category = ToolCategory.EXTERNAL

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
