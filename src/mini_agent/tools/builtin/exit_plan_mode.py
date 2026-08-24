"""ExitPlanMode tool — LLM signals plan complete, requests user review.
ExitPlanMode 工具——LLM 表示计划完成、请求用户审阅。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


class ExitPlanModeParams(BaseModel):
    pass


class ExitPlanModeTool(Tool):
    _name = "exit_plan_mode"
    category = ToolCategory.READ
    opens_dialog = True
    _description = (
        "Request to exit plan mode after presenting your plan. The USER "
        "must approve -- plan mode stays active until they do. Only call "
        "this when you are in plan mode and have finished writing your plan."
    )
    params_model = ExitPlanModeParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ref = ctx.agent_loop_ref
        if ref is None:
            return self.error_result("", "exit_plan_mode is not available in this context")
        if not ref.get_plan_mode():
            return self.error_result("", "Not in plan mode. Use /plan on first.")
        # Approval gate: the LLM must NOT be able to lift its own read-only
        # restriction (real-run verified: without this gate it exited plan
        # mode and wrote files in the same batch). No UI -> stay in plan.
        # 审批门：LLM 不能自行解除只读限制（真实运行实测：无此门时它自批
        # 退出并在同一批调用里写了文件）。无 UI 时保持 plan 模式。
        if ctx.ask_user_callback is None:
            return self.error_result(
                "",
                "Plan approval requires an interactive user. Staying in plan mode.",
            )
        answer = await ctx.ask_user_callback(
            "Approve the plan and exit plan mode? 批准计划并退出计划模式？",
            ["yes", "no"],
        )
        if str(answer).strip().lower() not in ("yes", "y", "是", "批准"):
            return ToolResult(
                call_id="",
                name=self._name,
                output=(
                    "User did NOT approve the plan. Still in plan mode (read-only). "
                    "Revise the plan based on their feedback or ask what to change."
                ),
            )
        ref.set_plan_mode(False)
        return ToolResult(
            call_id="",
            name=self._name,
            output="Plan approved by user. Plan mode exited -- you may now execute the plan.",
        )
