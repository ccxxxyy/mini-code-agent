"""Slash command framework -- built-in + user-defined commands.
斜杠命令框架——内置命令 + 用户自定义命令。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

# Handlers prefix their result with this sentinel to request Markdown
# rendering (agent reports with headers/tables). Plain-text outputs
# (/status, /cost aligned layouts) stay verbatim -- Markdown would
# collapse their newlines and spacing.
# 处理函数在结果前加此哨兵请求 Markdown 渲染（带标题/表格的 agent
# 报告）；纯文本对齐版式（/status /cost）保持原样——Markdown 会折叠
# 其换行与空格。
MARKDOWN_RESULT = "\x00md\x00"


@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[[str, Any], Awaitable[str | None]]
    hidden: bool = False


class SlashCommandRegistry:
    """Registry for slash commands. Handles parsing, dispatch, and listing.
    斜杠命令注册表。负责解析、分发和列出命令。"""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name] = command

    def unregister(self, name: str) -> None:
        self._commands.pop(name, None)

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name)

    def names(self) -> set[str]:
        """All registered command names, hidden included (plugin loader diffing).
        全部已注册命令名，含隐藏命令（供插件加载器差分快照）。"""
        return set(self._commands)

    def list_commands(self) -> list[SlashCommand]:
        """Visible commands, alphabetically sorted -- feeds /help, the
        unknown-command hint and the `/` dropdown completer.
        可见命令按字母排序——供 /help、未知命令提示、`/` 下拉补全共用。"""
        return sorted(
            (c for c in self._commands.values() if not c.hidden),
            key=lambda c: c.name,
        )

    def is_slash_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    async def execute(self, input_text: str, context: Any = None) -> str | None:
        """Parse and execute a slash command.
        解析并执行一条斜杠命令。

        Returns the output string, or None if not a slash command.
        返回输出字符串；如果不是斜杠命令则返回 None。
        """
        text = input_text.strip()
        if not text.startswith("/"):
            return None

        parts = text[1:].split(maxsplit=1)
        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        command = self._commands.get(name)
        if command is None:
            available = ", ".join(f"/{c.name}" for c in self.list_commands())
            return f"Unknown command: /{name}\nAvailable: {available}"

        return await command.handler(args, context)
