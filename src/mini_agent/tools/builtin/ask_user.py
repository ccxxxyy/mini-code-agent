"""AskUser tool — LLM asks the user a structured question.
AskUser 工具——LLM 向用户提结构化问题。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


class AskUserParams(BaseModel):
    question: str = Field(description="The question to ask the user")
    choices: list[str] = Field(
        default_factory=list,
        description="Optional list of choices (empty = free-text input)",
    )


class AskUserTool(Tool):
    _name = "ask_user"
    category = ToolCategory.READ
    opens_dialog = True
    _description = (
        "Ask the user a question and wait for their answer. "
        "Use when you need clarification, a choice between options, "
        "or confirmation beyond yes/no. Only available in the main agent."
    )
    params_model = AskUserParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        question = kwargs["question"]
        choices = kwargs.get("choices") or []
        if ctx.ask_user_callback is None:
            return self.error_result(
                "", "ask_user is only available in the main agent (no UI in sub-agents)"
            )
        try:
            answer = await ctx.ask_user_callback(question, choices or None)
        except Exception as e:
            return self.error_result("", f"ask_user failed: {e}")
        return ToolResult(call_id="", name=self._name, output=answer or "(no answer)")
