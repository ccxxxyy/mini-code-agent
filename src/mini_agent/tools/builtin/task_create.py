"""TaskCreate tool — LLM creates a task on the persistent task board.
TaskCreate 工具——LLM 在持久化任务板上创建任务。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class TaskCreateParams(BaseModel):
    description: str = Field(description="Task description")
    blocked_by: list[str] = Field(
        default_factory=list,
        description="IDs of tasks that must complete before this one can start",
    )


class TaskCreateTool(Tool):
    _name = "task_create"
    _description = (
        "Create a new task on the persistent task board. "
        "Returns the task ID. Use task_list to see all tasks."
    )
    params_model = TaskCreateParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        if ctx.task_store is None:
            return self.error_result("", "Task store not available")
        from mini_agent.core.task_store import TaskRecord

        task = TaskRecord(
            description=kwargs["description"], blocked_by=kwargs.get("blocked_by", [])
        )
        ctx.task_store.add(task)
        return ToolResult(
            call_id="",
            name=self._name,
            output=f"Created task {task.id}: {task.description}",
        )
