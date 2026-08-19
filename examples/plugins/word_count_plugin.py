"""Example plugin demoing all three specific hooks (P83).
示例插件——演示三个专用钩子（P83）。

Install either way 两种安装方式:

1. Local file 本地文件: copy this file into ``./.mini-agent/plugins/`` (or
   ``~/.mini-agent/plugins/``) and restart the agent.
   复制本文件到插件目录后重启 Agent。
2. pip package pip 包: put the same hooks in your package module and declare
   在你的包模块里写同样的钩子并声明::

       [project.entry-points."mini_agent.plugins"]
       word_count = "my_pkg.plugin"

Verify with ``/plugins``, ``/tools`` (word_count), ``/greet``, ``/skill list``
(haiku-mode). 用这些命令验证加载效果。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.extensions.skills import Skill, SkillRegistry
from mini_agent.extensions.slash_commands import SlashCommand, SlashCommandRegistry
from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolRegistry


class WordCountParams(BaseModel):
    text: str = Field(description="Text to count words and characters in")


class WordCountTool(Tool):
    _name = "word_count"
    _description = "Count words, characters, and lines in the given text."
    params_model = WordCountParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        text = kwargs["text"]
        words = len(text.split())
        chars = len(text)
        lines = text.count("\n") + 1 if text else 0
        return ToolResult(
            call_id="",
            name="word_count",
            output=f"words={words} chars={chars} lines={lines}",
        )


def register_tools(registry: ToolRegistry) -> None:
    registry.register(WordCountTool())


def register_commands(registry: SlashCommandRegistry) -> None:
    async def greet(args: str, ctx: Any) -> str:
        target = args.strip() or "world"
        return f"Hello, {target}! (from word_count_plugin)"

    registry.register(
        SlashCommand(
            name="greet",
            description="Say hello (usage: /greet [name]) -- example plugin command",
            handler=greet,
        )
    )


def register_skills(registry: SkillRegistry) -> None:
    registry.register(
        Skill(
            name="haiku-mode",
            description="Answer in haiku form -- example plugin skill",
            prompt="When this skill is active, phrase every answer as a 5-7-5 haiku.",
            trigger_patterns=["haiku"],
        )
    )
