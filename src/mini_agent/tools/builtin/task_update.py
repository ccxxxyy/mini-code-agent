"""TaskUpdate tool — LLM updates a task's status or description (B1).
TaskUpdate 工具——LLM 更新任务状态或描述（B1）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext

_VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}


class TaskUpdateParams(BaseModel):
    task_id: str = Field(description="Task ID or unique prefix")
    status: str | None = Field(
        default=None, description="New status (pending/in_progress/completed/failed)"
    )
    description: str | None = Field(default=None, description="New description")


class TaskUpdateTool(Tool):
    _name = "task_update"
    _description = (
        "Update a task's status or description. "
        "Valid statuses: pending, in_progress, completed, failed."
    )
    params_model = TaskUpdateParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.task_store is None:
            return self.error_result("", "Task store not available")
        task_id = kwargs["task_id"]
        status = kwargs.get("status")
        description = kwargs.get("description")
        if status is not None and status not in _VALID_STATUSES:
            return self.error_result(
                "", f"Invalid status '{status}'. Valid: {', '.join(sorted(_VALID_STATUSES))}"
            )
        updates: dict[str, Any] = {}
        if status is not None:
            updates["status"] = status
        if description is not None:
            updates["description"] = description
        if not updates:
            return self.error_result("", "Nothing to update (provide status or description)")
        task = ctx.task_store.update(task_id, **updates)
        if task is None:
            return self.error_result("", f"Task not found: {task_id}")
        result = f"Updated {task.id}: status={task.status}"
        if task.description:
            result += f", description={task.description[:80]}"
        unblocked = ctx.task_store.find_unblocked_by(task.id)
        if unblocked:
            result += f"\nUnblocked: {', '.join(t.id for t in unblocked)}"
        return ToolResult(call_id="", name=self._name, output=result)
