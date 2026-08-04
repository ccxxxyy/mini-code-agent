"""Teaching mode renderer -- deterministic tool explanations (for /explain).
教学模式渲染器——确定性工具解释（用于 /explain）。

A pure EventBus subscriber: prints teaching annotations before each tool call.
纯 EventBus 订阅者：在每次工具调用前打印教学注释。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

from mini_agent.models.events import (
    ToolCallStartEvent,
    TurnCompleteEvent,
)

if TYPE_CHECKING:
    from mini_agent.events.bus import EventBus

_TOOL_TEACH: dict[str, tuple[str, str]] = {
    "read_file": (
        "Read a file's content to understand its structure before modifying or answering.",
        "file_path=target file; offset/limit=read a slice of large files",
    ),
    "write_file": (
        "Create or overwrite a file. Use when the entire file content is known.",
        "file_path=destination; content=full file body",
    ),
    "edit_file": (
        "Surgically replace a specific string in a file without rewriting the whole file.",
        "file_path=target; old_string=exact text to find; new_string=replacement",
    ),
    "bash": (
        "Run a shell command for tasks tools can't do: install, compile, git, test, etc.",
        "command=the shell command; timeout=max seconds to wait",
    ),
    "glob": (
        "Find files by name pattern. Faster than bash find/dir and cross-platform.",
        "pattern=glob pattern (e.g. **/*.py); path=search root directory",
    ),
    "grep": (
        "Search file contents by regex. Use when you know WHAT to find but not WHERE.",
        "pattern=regex to match; path=search scope; include=file filter",
    ),
}

_DEFAULT_TEACH = (
    "Execute this tool to accomplish the current subtask.",
    "(see tool schema for parameter details)",
)


class TeachRenderer:
    """Prints teaching annotations before tool calls when enabled.
    启用时在工具调用前打印教学注释。"""

    def __init__(self, console: Console) -> None:
        self._console = console
        self.enabled: bool = False
        self._turn_tool_count: int = 0

    def attach(self, bus: EventBus) -> None:
        bus.on(ToolCallStartEvent, self._on_tool_start)
        bus.on(TurnCompleteEvent, self._on_turn_complete)

    def detach(self, bus: EventBus) -> None:
        bus.off(ToolCallStartEvent, self._on_tool_start)
        bus.off(TurnCompleteEvent, self._on_turn_complete)

    async def _on_tool_start(self, e: ToolCallStartEvent) -> None:
        if not self.enabled:
            return
        self._turn_tool_count += 1
        why, params = _TOOL_TEACH.get(e.tool_name, _DEFAULT_TEACH)
        args_str = ", ".join(f"{k}={str(v)[:50]}" for k, v in list(e.arguments.items())[:4])
        body = (
            f"[bold]Why this tool[/bold]: {why}\n"
            f"[bold]Args[/bold]: {args_str}\n"
            f"[bold]Params guide[/bold]: {params}"
        )
        self._console.print(
            Panel(body, title=f"[#6c71c4]Teach: {e.tool_name}[/#6c71c4]", border_style="dim"),
        )

    async def _on_turn_complete(self, e: TurnCompleteEvent) -> None:
        if not self.enabled:
            return
        if self._turn_tool_count > 0:
            self._console.print(
                f"  [dim]teach: {self._turn_tool_count} tool(s) explained this turn[/dim]"
            )
        self._turn_tool_count = 0
