"""Main TUI application -- Rich for rendering, Prompt Toolkit for input."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from mini_agent.ui.input_handler import create_prompt_session
from mini_agent.ui.renderer import StreamRenderer


class Terminal:
    """Terminal user interface for the agent."""

    def __init__(self) -> None:
        self.console = Console()
        self.renderer = StreamRenderer(self.console)
        self._prompt_session = None

    def show_welcome(self) -> None:
        title = Text("Mini-Code-Agent v0.1.0", style="bold cyan")
        self.console.print(
            Panel(title, subtitle="Type your message. Ctrl+C to exit.", border_style="dim")
        )
        self.console.print()

    def _ensure_prompt_session(self):
        if self._prompt_session is None:
            self._prompt_session = create_prompt_session()

    async def get_user_input(self) -> str:
        self._ensure_prompt_session()
        return await self._prompt_session.prompt_async("> ")

    def start_stream(self) -> None:
        self.renderer.start()

    def feed_stream(self, delta: str) -> None:
        self.renderer.feed(delta)

    def finish_stream(self) -> str:
        return self.renderer.finish()

    def show_error(self, error: str) -> None:
        self.console.print(f"[bold red]Error:[/bold red] {error}")

    def show_info(self, message: str) -> None:
        self.console.print(f"[dim]{message}[/dim]")

    def show_tool_call(self, name: str, args: dict) -> None:
        arg_preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
        self.console.print(
            f"  [bold yellow]⚙ {name}[/bold yellow][dim]({arg_preview})[/dim]",
            highlight=False,
        )

    def show_tool_result(self, name: str, output: str, is_error: bool = False) -> None:
        if is_error:
            preview = output[:300] + "..." if len(output) > 300 else output
            self.console.print(f"  [red]✗ {preview}[/red]", highlight=False)
        else:
            lines = output.count("\n") + 1
            chars = len(output)
            self.console.print(
                f"  [green]✓[/green] [dim]{lines} lines, {chars} chars[/dim]",
                highlight=False,
            )

    @staticmethod
    def _truncate_value(value: object, max_len: int = 60) -> str:
        s = repr(value)
        return s[:max_len] + "..." if len(s) > max_len else s
