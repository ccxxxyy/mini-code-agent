"""Slash command framework -- built-in + user-defined commands."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class SlashCommand:
    name: str
    description: str
    handler: Callable[[str, Any], Awaitable[str | None]]
    hidden: bool = False


class SlashCommandRegistry:
    """Registry for slash commands. Handles parsing, dispatch, and listing."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommand] = {}

    def register(self, command: SlashCommand) -> None:
        self._commands[command.name] = command

    def unregister(self, name: str) -> None:
        self._commands.pop(name, None)

    def get(self, name: str) -> SlashCommand | None:
        return self._commands.get(name)

    def list_commands(self) -> list[SlashCommand]:
        return [c for c in self._commands.values() if not c.hidden]

    def is_slash_command(self, text: str) -> bool:
        return text.strip().startswith("/")

    async def execute(self, input_text: str, context: Any = None) -> str | None:
        """Parse and execute a slash command.

        Returns the output string, or None if not a slash command.
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
