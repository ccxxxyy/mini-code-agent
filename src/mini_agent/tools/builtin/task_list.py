"""TaskList tool — LLM lists all tasks on the board (B1).
TaskList 工具——LLM 列出任务板上所有任务（B1）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class TaskListParams(BaseModel):
    pass


class TaskListTool(Tool):
    _name = "task_list"
    _description = "List all tasks on the persistent task board."
    params_model = TaskListParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.task_store is None:
            return self.error_result("", "Task store not available")
        tasks = ctx.task_store.load()
        if not tasks:
            return ToolResult(call_id="", name=self._name, output="No tasks.")
        lines = []
        for t in tasks:
            prefix = ctx.task_store.min_unique_prefix(t.id)
            status_icon = {"pending": "☐", "in_progress": "▶", "completed": "✓", "failed": "✗"}.get(
                t.status, "?"
            )
            dep = f" (blocked by {', '.join(t.blocked_by)})" if t.blocked_by else ""
            lines.append(f"  {status_icon} [{prefix}] {t.description}{dep}")
        return ToolResult(call_id="", name=self._name, output="\n".join(lines))
