"""Main TUI application -- Rich for rendering, Prompt Toolkit for input.
主 TUI 应用——Rich 负责渲染，Prompt Toolkit 负责输入。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel

from mini_agent.ui.input_handler import SlashCommandCompleter, create_prompt_session
from mini_agent.ui.renderer import StreamRenderer
from mini_agent.ui.themes import Theme, get_theme


class Terminal:
    """Terminal user interface for the agent. Agent 的终端用户界面。"""

    def __init__(self, theme: Theme | None = None) -> None:
        self.theme = theme or get_theme("default")
        self.console = Console()
        self.renderer = StreamRenderer(self.console)
        self._completer = SlashCommandCompleter()
        self._prompt_session = None
        self._toolbar_provider = None

    def show_welcome(self, llm_info: str = "") -> None:
        self.console.print()
        from mini_agent import __version__

        p = self.theme.primary
        header = f"  [bold {p}]Mini-Code-Agent[/bold {p}] [dim]v{__version__}[/dim]"
        if llm_info:
            header += f" [dim]|[/dim] [{p}]{llm_info}[/{p}]"
        self.console.print(header)
        self.console.print(
            "  [dim]Type your message to chat. /help for commands. Ctrl+C to exit.[/dim]"
        )
        self.console.print()

    def set_slash_commands(self, commands: list[tuple[str, str]]) -> None:
        self._completer.set_commands(commands)

    def set_toolbar_provider(self, provider) -> None:
        self._toolbar_provider = provider

    def _ensure_prompt_session(self) -> None:
        if self._prompt_session is None:
            self._prompt_session = create_prompt_session(
                completer=self._completer,
                toolbar_provider=self._toolbar_provider,
                theme=self.theme,
            )

    async def get_user_input(self) -> str:
        self._ensure_prompt_session()
        return await self._prompt_session.prompt_async()

    async def confirm(self, prompt: str) -> bool | str:
        """Ask user for confirmation.
        Returns True (allow once), False (deny), or "always" (allow for session).
        """
        w = self.theme.warning
        e = self.theme.error
        self.console.print()
        self.console.print(
            Panel(
                f"[bold {w}]{prompt}[/bold {w}]\n\n"
                f"[dim]y = allow once  /  a = always allow (this session)  /  n = deny[/dim]",
                title=f"[{e}]Confirmation Required[/{e}]",
                border_style=w,
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

    async def ask_yes_no(self, prompt: str) -> bool:
        self._ensure_prompt_session()
        while True:
            answer = (await self._prompt_session.prompt_async(f"{prompt} [y/n] > ")).strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no", ""):
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
        self.console.print(f"  [bold {self.theme.error}]✗[/bold {self.theme.error}] {error}")
        self.console.print()

    def show_info(self, message: str) -> None:
        self.console.print(f"  [dim]{message}[/dim]")

    def show_tool_call(self, name: str, args: dict) -> None:
        p = self.theme.primary
        arg_preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
        self.console.print(
            f"\n  [dim]╭─[/dim] [bold {p}]{name}[/bold {p}] [dim]{arg_preview}[/dim]",
            highlight=False,
        )

    def show_tool_result(self, name: str, output: str, is_error: bool = False) -> None:
        if is_error:
            preview = output[:300] + "..." if len(output) > 300 else output
            e = self.theme.error
            self.console.print(f"  [dim]╰─[/dim] [{e}]✗ {preview}[/{e}]", highlight=False)
        else:
            lines = output.count("\n") + 1
            chars = len(output)
            s = self.theme.success
            self.console.print(
                f"  [dim]╰─[/dim] [{s}]✓[/{s}] [dim]{lines} lines, {chars} chars[/dim]",
                highlight=False,
            )

    @staticmethod
    def _truncate_value(value, max_len: int = 60) -> str:
        s = str(value)
        return s[:max_len] + "..." if len(s) > max_len else s
