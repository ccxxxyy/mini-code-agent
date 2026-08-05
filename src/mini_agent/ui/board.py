"""SubAgent progress board -- live table of active sub-agents.
SubAgent 进度面板——活跃 SubAgent 的实时表格。

Shown while /spawn wait and /team block on background agents; collapses
automatically when the awaited work finishes.
在 /spawn wait 和 /team 阻塞等待后台 agent 期间显示；等待结束后自动收起。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.live import Live
from rich.table import Table

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from mini_agent.core.subagent import SubAgentManager

_PHASE_COLORS = {
    "idle": "dim",
    "thinking": "#6c71c4",
    "tool_calling": "blue",
    "observing": "cyan",
    "responding": "green",
    "error": "red",
    "terminated": "green",
}

_REFRESH_INTERVAL = 0.25


class SubAgentBoard:
    """Live progress table for active sub-agents. 活跃 SubAgent 的实时进度表。"""

    def __init__(self, console: Console, manager: SubAgentManager) -> None:
        self._console = console
        self._manager = manager

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
        table = Table(
            title="SubAgent Progress",
            title_style="bold #6c71c4",
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

        for s in snapshots:
            color = _PHASE_COLORS.get(s.phase, "white")
            task_preview = s.task if len(s.task) <= 44 else s.task[:41] + "..."
            table.add_row(
                s.agent_id,
                task_preview,
                f"[{color}]{s.phase}[/{color}]",
                str(s.tool_calls),
                f"{s.elapsed_seconds:.1f}s",
            )
        return table
