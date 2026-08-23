"""ExitPlanMode tool — LLM signals plan complete, requests user review.
ExitPlanMode 工具——LLM 表示计划完成、请求用户审阅。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class ExitPlanModeParams(BaseModel):
    pass


class ExitPlanModeTool(Tool):
    _name = "exit_plan_mode"
    _description = (
        "Signal that your plan is complete and exit plan mode. "
        "The user will review and approve. Only call this when you are "
        "in plan mode and have finished writing your plan."
    )
    params_model = ExitPlanModeParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ref = ctx.agent_loop_ref
        if ref is None:
            return self.error_result("", "exit_plan_mode is not available in this context")
        if not ref.get_plan_mode():
            return self.error_result("", "Not in plan mode. Use /plan on first.")
        ref.set_plan_mode(False)
        return ToolResult(
            call_id="",
            name=self._name,
            output=(
                "Plan mode exited. The user will now review your plan. "
                "Do not call any more tools this turn."
            ),
        )
