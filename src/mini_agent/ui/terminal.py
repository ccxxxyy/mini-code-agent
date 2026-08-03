"""Main TUI application -- Rich for rendering, Prompt Toolkit for input.
主 TUI 应用——Rich 负责渲染，Prompt Toolkit 负责输入。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from mini_agent.ui.input_handler import SlashCommandCompleter, create_prompt_session
from mini_agent.ui.renderer import StreamRenderer


class Terminal:
    """Terminal user interface for the agent. Agent 的终端用户界面。"""

    def __init__(self) -> None:
        self.console = Console()
        self.renderer = StreamRenderer(self.console)
        self._completer = SlashCommandCompleter()
        self._prompt_session = None
        self._toolbar_provider = None

    def show_welcome(self, llm_info: str = "") -> None:
        self.console.print()
        from mini_agent import __version__

        header = f"  [bold #6c71c4]Mini-Code-Agent[/bold #6c71c4] [dim]v{__version__}[/dim]"
        if llm_info:
            header += f" [dim]|[/dim] [#6c71c4]{llm_info}[/#6c71c4]"
        self.console.print(header)
        self.console.print(
            "  [dim]Type your message to chat. /help for commands. Ctrl+C to exit.[/dim]"
        )
        self.console.print()

    def set_slash_commands(self, commands: list[tuple[str, str]]) -> None:
        """Update the slash command list for auto-completion. 更新用于自动补全的斜杠命令列表。"""
        self._completer.set_commands(commands)

    def set_toolbar_provider(self, provider) -> None:
        """Set a callable that returns the bottom toolbar text (e.g. model name).
        设置返回底部工具栏文本的回调（例如模型名）。
        """
        self._toolbar_provider = provider

    def _ensure_prompt_session(self) -> None:
        if self._prompt_session is None:
            self._prompt_session = create_prompt_session(
                completer=self._completer,
                toolbar_provider=self._toolbar_provider,
            )

    async def get_user_input(self) -> str:
        self._ensure_prompt_session()
        return await self._prompt_session.prompt_async()

    async def confirm(self, prompt: str) -> bool | str:
        """Ask user for confirmation.

        Returns True (allow once), False (deny), or "always" (allow for session).
        返回 True（允许一次）、False（拒绝）或 "always"（本 session 内始终允许）。
        """
        self.console.print()
        self.console.print(
            Panel(
                f"[bold yellow]{prompt}[/bold yellow]\n\n"
                f"[dim]y = allow once  /  a = always allow (this session)  /  n = deny[/dim]",
                title="[red]Confirmation Required[/red]",
                border_style="yellow",
                expand=False,
            )
        )
        self._ensure_prompt_session()
        while True:
            answer = (await self._prompt_session.prompt_async("allow? [y/a/n] > ")).strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("a", "always"):
                return "always"
            if answer in ("n", "no"):
                return False

    def start_stream(self) -> None:
        self.console.print()
        self.renderer.start()

    def feed_stream(self, delta: str) -> None:
        self.renderer.feed(delta)

    def finish_stream(self) -> str:
        result = self.renderer.finish()
        self.console.print()
        return result

    def show_error(self, error: str) -> None:
        self.console.print(f"  [bold red]✗[/bold red] {error}")
        self.console.print()

    def show_info(self, message: str) -> None:
        self.console.print(f"  [dim]{message}[/dim]")

    def show_tool_call(self, name: str, args: dict) -> None:
        arg_preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
        self.console.print(
            f"\n  [dim]╭─[/dim] [bold #6c71c4]{name}[/bold #6c71c4] [dim]{arg_preview}[/dim]",
            highlight=False,
        )

    def show_tool_result(self, name: str, output: str, is_error: bool = False) -> None:
        if is_error:
            preview = output[:300] + "..." if len(output) > 300 else output
            self.console.print(f"  [dim]╰─[/dim] [red]✗ {preview}[/red]", highlight=False)
        else:
            lines = output.count("\n") + 1
            chars = len(output)
            self.console.print(
                f"  [dim]╰─[/dim] [green]✓[/green] [dim]{lines} lines, {chars} chars[/dim]",
                highlight=False,
            )

    @staticmethod
    def _truncate_value(value: object, max_len: int = 60) -> str:
        s = repr(value)
        return s[:max_len] + "..." if len(s) > max_len else s
