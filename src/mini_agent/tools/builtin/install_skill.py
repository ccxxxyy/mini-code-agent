"""InstallSkill tool — LLM installs a skill from a path or git URL.
InstallSkill 工具——LLM 从路径或 git URL 安装技能。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


class InstallSkillParams(BaseModel):
    source: str = Field(description="Local directory path or git URL to install the skill from")


class InstallSkillTool(Tool):
    _name = "install_skill"
    category = ToolCategory.WRITE
    _description = (
        "Install a skill from a local path or git URL into the user's "
        "skill directory (~/.mini-agent/skills/). The source must contain "
        "a valid SKILL.md file."
    )
    params_model = InstallSkillParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        sr = ctx.skill_registry
        if sr is None:
            return self.error_result("", "Skill registry not available")
        source = kwargs["source"]
        target_dir = Path.home() / ".mini-agent" / "skills"
        try:
            name = await sr.install(source, target_dir)
        except ValueError as e:
            return self.error_result("", str(e))
        except Exception as e:
            return self.error_result("", f"Install failed: {e}")
        return ToolResult(
            call_id="",
            name=self._name,
            output=f"Skill '{name}' installed to {target_dir}.",
        )
