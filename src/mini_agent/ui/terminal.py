"""Main TUI application -- Rich for rendering, Prompt Toolkit for input.
主 TUI 应用——Rich 负责渲染，Prompt Toolkit 负责输入。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme as RichTheme

from mini_agent.ui.input_handler import SlashCommandCompleter, create_prompt_session
from mini_agent.ui.renderer import StreamRenderer
from mini_agent.ui.themes import Theme, get_theme


def _markdown_styles(theme: Theme) -> RichTheme:
    """Override Rich's default markdown colors (purple headings are hard to
    read on dark terminals) with theme-aware colors.
    覆盖 Rich 默认的 markdown 配色（紫色标题在深色终端很难看），改用主题色。"""
    h = theme.heading or theme.success
    return RichTheme(
        {
            "markdown.h1": f"bold {h}",
            "markdown.h2": f"bold {h}",
            "markdown.h3": f"bold {h}",
            "markdown.h4": f"bold {h}",
            "markdown.h1.border": theme.dim,
            "markdown.item.bullet": theme.warning,
            "markdown.item.number": theme.warning,
            "markdown.hr": theme.dim,
            "markdown.link": f"underline {theme.primary}",
            "markdown.link_url": f"underline {theme.dim}",
        }
    )


class Terminal:
    """Terminal user interface for the agent. Agent 的终端用户界面。"""

    def __init__(self, theme: Theme | None = None) -> None:
        self.theme = theme or get_theme("default")
        self.console = Console(theme=_markdown_styles(self.theme))
        self.renderer = StreamRenderer(self.console)
        self._completer = SlashCommandCompleter()
        self._prompt_session = None
        self._toolbar_provider = None

    def set_theme(self, theme: Theme) -> None:
        """Switch theme, including the console's markdown styles.
        切换主题——包括 Console 的 markdown 配色（标题/列表颜色）。"""
        self.theme = theme
        self.console.push_theme(_markdown_styles(theme))
        self._prompt_session = None  # rebuilt with new prompt style 用新样式重建

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
        # Top rule marking the input area (bottom toolbar is the lower bound)
        # 输入区上边界线（下边界由底部工具栏承担）
        self.console.print(f"[{self.theme.dim}]{'─' * self.console.width}[/{self.theme.dim}]")
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
        """Plain yes/no using a temporary prompt (does not pollute the main session).
        使用临时提示的朴素是/否（不污染主输入 session 的默认 message）。"""
        from prompt_toolkit import PromptSession as _PS

        tmp = _PS()
        while True:
            answer = (await tmp.prompt_async(f"{prompt} [y/n] > ")).strip().lower()
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

    def show_tool_result(
        self, name: str, output: str, is_error: bool = False, metadata: dict | None = None
    ) -> None:
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
            # Diff preview for edit_file edit_file 的 diff 预览
            if metadata and metadata.get("diff"):
                self._render_diff(metadata["diff"])

    def _render_diff(self, diff_text: str) -> None:
        """Render a colored unified diff with full-width background.
        渲染整行背景色高亮的彩色 unified diff。"""
        from rich.text import Text

        lines = diff_text.splitlines()
        body = [ln for ln in lines if not ln.startswith(("---", "+++", "@@"))]
        if not body:
            return

        w = self.console.width
        removed: list[str] = []
        added: list[str] = []

        def flush() -> None:
            # Standard color names work on all terminals (truecolor hex may
            # silently fail on legacy Windows consoles)
            # 标准色名全终端兼容（truecolor 十六进制在旧 Windows 控制台可能无效）
            for r in removed:
                t = Text(f"  - {r[1:]}")
                t.pad_right(max(0, w - t.cell_len))
                t.stylize("white on dark_red")
                self.console.print(t, highlight=False)
            removed.clear()
            for a in added:
                t = Text(f"  + {a[1:]}")
                t.pad_right(max(0, w - t.cell_len))
                t.stylize("white on dark_green")
                self.console.print(t, highlight=False)
            added.clear()

        for line in body:
            if line.startswith("-"):
                if added:
                    flush()
                removed.append(line)
            elif line.startswith("+"):
                added.append(line)
            else:
                flush()
                self.console.print(f"    [dim] {line}[/dim]", highlight=False)
        flush()

    def show_file_changes(self, changes: list[tuple[str, str]]) -> None:
        """Show files created/modified/deleted this turn.
        显示本轮新建/修改/删除的文件。"""
        if not changes:
            return
        self.console.print()
        self.console.print("  [dim]files changed this turn:[/dim]")
        for change_type, path in changes:
            if change_type == "created":
                mark, color = "+", self.theme.success
            elif change_type == "deleted":
                mark, color = "-", self.theme.error
            else:
                mark, color = "~", self.theme.warning
            self.console.print(f"    [{color}]{mark} {path}[/{color}]", highlight=False)

    @staticmethod
    def _truncate_value(value, max_len: int = 60) -> str:
        s = str(value)
        return s[:max_len] + "..." if len(s) > max_len else s
