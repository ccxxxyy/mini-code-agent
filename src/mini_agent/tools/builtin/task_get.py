"""TaskGet tool — LLM retrieves a task by ID or prefix (B1).
TaskGet 工具——LLM 按 ID 或前缀查询任务（B1）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class TaskGetParams(BaseModel):
    task_id: str = Field(description="Task ID or unique prefix")


class TaskGetTool(Tool):
    _name = "task_get"
    _description = "Get details of a specific task by its ID or prefix."
    params_model = TaskGetParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.task_store is None:
            return self.error_result("", "Task store not available")
        task = ctx.task_store.get(kwargs["task_id"])
        if task is None:
            return self.error_result("", f"Task not found: {kwargs['task_id']}")
        lines = [
            f"ID: {task.id}",
            f"Description: {task.description}",
            f"Status: {task.status}",
            f"Blocked by: {', '.join(task.blocked_by) or '(none)'}",
            f"Tags: {', '.join(task.tags) or '(none)'}",
            f"Created: {task.created_at}",
        ]
        return ToolResult(call_id="", name=self._name, output="\n".join(lines))
