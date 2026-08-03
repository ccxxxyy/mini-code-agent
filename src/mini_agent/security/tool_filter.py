"""Tool filtering based on execution context. 基于执行上下文的工具过滤。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mini_agent.tools.base import Tool


@dataclass
class ToolFilterContext:
    is_subagent: bool = False
    subagent_allowed_tools: list[str] | None = None
    worktree_path: Path | None = None


class ToolFilter:
    """Filters available tools based on context. 根据上下文过滤可用工具。"""

    def filter_for_context(
        self,
        all_tools: list[Tool],
        context: ToolFilterContext,
    ) -> list[Tool]:
        """Return only the tools allowed in the given context.
        只返回在给定上下文中允许使用的工具。"""
        tools = all_tools
        if context.is_subagent and context.subagent_allowed_tools is not None:
            allowed = set(context.subagent_allowed_tools)
            tools = [t for t in tools if t.schema.name in allowed]
        return tools
