"""LoadSkill tool — LLM activates an installed skill into the conversation (B1).
LoadSkill 工具——LLM 把已安装的技能激活到当前对话中（B1）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class LoadSkillParams(BaseModel):
    name: str = Field(description="Name of the skill to activate")


class LoadSkillTool(Tool):
    _name = "load_skill"
    _description = (
        "Activate an installed skill by name. The skill's prompt is injected "
        "into the system prompt. Use /skill list to see available skills."
    )
    params_model = LoadSkillParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        sr = ctx.skill_registry
        if sr is None:
            return self.error_result("", "Skill registry not available")
        name = kwargs["name"]
        skill = sr.get(name)
        if skill is None:
            available = ", ".join(s.name for s in sr.list_skills()) or "(none)"
            return self.error_result("", f"Skill not found: {name}. Available: {available}")
        if sr.is_active(name):
            return ToolResult(
                call_id="",
                name=self._name,
                output=f"Skill '{name}' is already active.",
            )
        ok = sr.activate(name, ctx.session.conversation)
        if not ok:
            return self.error_result("", f"Failed to activate skill: {name}")
        desc = skill.description or "(no description)"
        return ToolResult(
            call_id="",
            name=self._name,
            output=f"Skill '{name}' activated: {desc}",
        )
