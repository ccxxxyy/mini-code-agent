"""MCPCall -- invoke a dispatch-mode MCP tool discovered via tool_search.
MCP 调用——执行通过 tool_search 发现的 dispatch 模式 MCP 工具。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class MCPCallParams(BaseModel):
    """Pydantic model for mcp_call parameters."""

    server: str = Field(description="MCP server name (from tool_search results)")
    tool: str = Field(description="Tool name (from tool_search results)")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Tool arguments as a JSON object",
    )


class MCPCallTool(Tool):
    """Call a dispatch-mode MCP tool discovered via tool_search.
    调用通过 tool_search 发现的 dispatch 模式 MCP 工具。"""

    _name = "mcp_call"
    _description = (
        "Call a dispatch-mode MCP tool by server name and tool name. "
        "Use tool_search first to discover available tools and their parameters."
    )
    params_model = MCPCallParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        mgr = ctx.mcp_manager
        if mgr is None:
            return self.error_result("", "No MCP manager available")

        server = kwargs["server"]
        tool = kwargs["tool"]
        arguments = kwargs.get("arguments", {})

        return await mgr.call_tool(server, tool, arguments)
