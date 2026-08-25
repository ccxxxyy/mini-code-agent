"""SubAgent progress board -- live table of active sub-agents.
SubAgent 进度面板——活跃 SubAgent 的实时表格。

Shown while /spawn --wait, /spawn wait and /team block on running agents;
collapses automatically when the awaited work finishes.
在 /spawn --wait、/spawn wait 和 /team 阻塞等待 agent 期间显示；
等待结束后自动收起。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.live import Live
from rich.table import Table

from mini_agent.ui.themes import Theme, get_theme

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from mini_agent.core.subagent import SubAgentManager

_REFRESH_INTERVAL = 0.25


def _phase_colors(theme: Theme) -> dict[str, str]:
    return {
        "idle": theme.dim,
        "thinking": theme.primary,
        "tool_calling": "blue",
        "observing": "cyan",
        "responding": theme.success,
        "error": theme.error,
        "terminated": theme.success,
    }


class SubAgentBoard:
    """Live progress table for active sub-agents. 活跃 SubAgent 的实时进度表。"""

    def __init__(
        self, console: Console, manager: SubAgentManager, theme: Theme | None = None
    ) -> None:
        self._console = console
        self._manager = manager
        self._theme = theme or get_theme("default")

    async def run_while(self, awaitable: Awaitable[Any]) -> Any:
        """Display the board while `awaitable` runs; return its result.
        在 awaitable 运行期间显示面板，结束后收起并返回其结果。

        Exceptions from the awaitable propagate after the board closes.
        awaitable 的异常在面板关闭后原样抛出。
        """
        task = asyncio.ensure_future(awaitable)
        live = Live("", console=self._console, refresh_per_second=4, transient=True)
        live.start()
        try:
            while not task.done():
                live.update(self._render())
                await asyncio.sleep(_REFRESH_INTERVAL)
        finally:
            live.update("")
            live.stop()
        return await task

    def _render(self) -> Table:
        p = self._theme.primary
        table = Table(
            title="SubAgent Progress",
            title_style=f"bold {p}",
            border_style="dim",
            expand=False,
        )
        table.add_column("Agent", style="bold", width=10)
        table.add_column("Task", max_width=44)
        table.add_column("Phase", width=14)
        table.add_column("Tools", justify="right", width=6)
        table.add_column("Time", justify="right", width=8)

        snapshots = self._manager.active_snapshots()
        if not snapshots:
            table.add_row("-", "[dim]collecting results...[/dim]", "-", "-", "-")
            return table

        colors = _phase_colors(self._theme)
        for s in snapshots:
            color = colors.get(s.phase, "white")
            task_preview = s.task if len(s.task) <= 44 else s.task[:41] + "..."
            table.add_row(
                s.agent_id,
                task_preview,
                f"[{color}]{s.phase}[/{color}]",
                str(s.tool_calls),
                f"{s.elapsed_seconds:.1f}s",
            )
        return table
