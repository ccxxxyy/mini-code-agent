"""Reusable UI components."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.spinner import Spinner
from rich.status import Status
from rich.text import Text


def make_spinner(message: str) -> Spinner:
    """Create a spinner with a status message."""
    return Spinner("dots", text=Text(message, style="dim"))


def make_status(console: Console, message: str) -> Status:
    """Create a live status indicator (use as context manager)."""
    return console.status(f"[dim]{message}[/dim]", spinner="dots")


def tool_call_panel(name: str, args: dict) -> Panel:
    """Render a tool call as a bordered panel."""
    lines = [f"[bold]{name}[/bold]"]
    for k, v in args.items():
        s = repr(v)
        if len(s) > 80:
            s = s[:80] + "..."
        lines.append(f"  [dim]{k}[/dim] = {s}")
    return Panel("\n".join(lines), border_style="yellow", expand=False)
