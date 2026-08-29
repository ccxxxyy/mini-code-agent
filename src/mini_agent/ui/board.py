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

# Sentinel returned by run_while when the user detached with Esc; the still-
# pending wait task is stashed on ``board.pending_task``.
# run_while 的哨兵返回值——用户按 Esc 转后台；未完成的等待任务
# 存放在 board.pending_task。
BOARD_DETACHED = object()


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
        self,
        console: Console,
        manager: SubAgentManager,
        theme: Theme | None = None,
        refresh_interval: float = _REFRESH_INTERVAL,
    ) -> None:
        self._console = console
        self._manager = manager
        self._theme = theme or get_theme("default")
        self._refresh_interval = refresh_interval
        self.pending_task: asyncio.Task | None = None
        self._detachable = False

    async def run_while(self, awaitable: Awaitable[Any], detachable: bool = False) -> Any:
        """Display the board while `awaitable` runs; return its result.
        在 awaitable 运行期间显示面板，结束后收起并返回其结果。

        Exceptions from the awaitable propagate after the board closes.
        awaitable 的异常在面板关闭后原样抛出。

        detachable=True: a single Esc press detaches -- the board closes and
        BOARD_DETACHED is returned, with the STILL-RUNNING wait task stashed
        on ``self.pending_task``. The task is deliberately NOT cancelled:
        ``SubAgentManager.wait`` wraps the agent in ``asyncio.wait_for``,
        so cancelling the outer wait would kill the agent itself.
        detachable=True：单击 Esc 转后台——面板收起返回 BOARD_DETACHED，
        仍在运行的等待任务存入 pending_task。刻意不 cancel 该任务：
        wait 内部是 wait_for 包装，cancel 外层会级联杀死 agent 本体。
        """
        from mini_agent.ui.esc_watcher import EscWatcher

        self._detachable = detachable
        task = asyncio.ensure_future(awaitable)
        watcher = EscWatcher(double=False) if detachable else None
        if watcher is not None:
            watcher.start()
        live = Live("", console=self._console, refresh_per_second=4, transient=True)
        live.start()
        try:
            while not task.done():
                if watcher is not None and watcher.triggered:
                    self.pending_task = task
                    return BOARD_DETACHED
                live.update(self._render())
                await asyncio.sleep(self._refresh_interval)
        finally:
            live.update("")
            live.stop()
            if watcher is not None:
                watcher.stop()
        return await task

    def _render(self) -> Table:
        p = self._theme.primary
        table = Table(
            title="SubAgent Progress",
            title_style=f"bold {p}",
            caption="Esc = move to background (Esc again at the prompt = re-attach)"
            if self._detachable
            else None,
            caption_style="dim",
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
