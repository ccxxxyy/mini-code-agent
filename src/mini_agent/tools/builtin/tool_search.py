"""ToolSearch -- LLM searches dispatch-mode MCP tools by keyword.
工具搜索——LLM 按关键词搜索 dispatch 模式的 MCP 工具。"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


class ToolSearchParams(BaseModel):
    """Pydantic model for tool_search parameters."""

    query: str = Field(description="Keyword to search for in tool names and descriptions")


class ToolSearchTool(Tool):
    """Search available dispatch-mode MCP tools by keyword.
    按关键词搜索可用的 dispatch 模式 MCP 工具。"""

    _name = "tool_search"

    category = ToolCategory.READ
    _description = (
        "Search available MCP tools by keyword. "
        "Returns matching tool names, descriptions, and parameter schemas. "
        "Use this to discover tools before calling them with mcp_call."
    )
    params_model = ToolSearchParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        mgr = ctx.mcp_manager
        if mgr is None:
            return self.error_result("", "No MCP manager available")

        query = kwargs["query"]
        matches = mgr.search_tools(query)

        if not matches:
            all_tools = mgr.list_dispatch_tools()
            if all_tools:
                names = ", ".join(t["name"] for t in all_tools[:20])
                return ToolResult(
                    call_id="",
                    name="tool_search",
                    output=f"No tools matching '{query}'. Available: {names}",
                )
            return ToolResult(
                call_id="",
                name="tool_search",
                output="No dispatch-mode MCP tools available.",
            )

        lines: list[str] = [f"Found {len(matches)} tool(s):"]
        for m in matches:
            lines.append(f"\n  server: {m['server']}")
            lines.append(f"  name: {m['name']}")
            lines.append(f"  description: {m['description']}")
            params = m.get("parameters", {})
            if params:
                lines.append(f"  parameters: {json.dumps(params, ensure_ascii=False)}")
        return ToolResult(call_id="", name="tool_search", output="\n".join(lines))
