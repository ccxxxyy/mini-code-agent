"""Main TUI application -- Rich for rendering, Prompt Toolkit for input.
主 TUI 应用——Rich 负责渲染，Prompt Toolkit 负责输入。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.theme import Theme as RichTheme

from mini_agent.ui.input_handler import SlashCommandCompleter, create_prompt_session
from mini_agent.ui.renderer import StreamRenderer
from mini_agent.ui.themes import Theme, get_theme

_BG_INTERRUPT = object()

# Read-only tools whose call/result line pairs collapse into a one-line
# summary when >=2 run in the same round (heavy read bursts flood the screen).
# 只读工具——同一轮 >=2 次时调用/结果行对折叠为一行摘要（密集读刷屏）。
_COLLAPSIBLE_TOOLS = frozenset({"read_file", "glob", "grep"})


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
        self._prompt_session: Any = None
        self._toolbar_provider = None
        self._mode_cycler = None
        self._esc_command_provider = None
        self._working_dir: Path | None = None
        self._bg_interrupt_event: asyncio.Event | None = None
        self._saved_buffer_text: str = ""
        self._pending_input_task: asyncio.Task[Any] | asyncio.Future[Any] | None = None
        self._live_started = False
        self._thinking_written = False
        # Collapsible read-only tool group (Rich Live, transient); the flag
        # mirrors config `collapse_tool_calls` (app wires it at startup;
        # default OFF -- full per-call lines).
        # 可折叠只读工具组（Rich Live，transient 擦除）；开关镜像配置
        # `collapse_tool_calls`（app 启动时接线；默认关闭——逐条完整显示）。
        self.collapse_tool_calls: bool = False
        self._ro_live: Any = None
        self._ro_entries: list[dict] = []
        self._ro_start: float = 0.0
        self._ro_last_done: float = 0.0

    def set_working_dir(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._prompt_session = None  # force rebuild with new dir 重建以使用新目录

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

    def set_mode_cycler(self, cycler) -> None:
        """Callable invoked by shift+tab to cycle the permission mode.
        shift+tab 触发的权限模式循环回调。"""
        self._mode_cycler = cycler
        self._prompt_session = None  # rebuild with the binding 重建以带上绑定

    def set_esc_command_provider(self, provider) -> None:
        """Callable consulted when Esc is pressed at an empty prompt --
        returns a command string to submit (e.g. "/spawn wait" re-attach)
        or None/"" for no action.
        空提示符按 Esc 时咨询的回调——返回要提交的命令
        （如 "/spawn wait" 重新附着），None/"" 表示不动作。"""
        self._esc_command_provider = provider
        self._prompt_session = None  # rebuild with the binding 重建以带上绑定

    def _ensure_prompt_session(self) -> None:
        if self._prompt_session is None:
            self._prompt_session = create_prompt_session(
                completer=self._completer,
                toolbar_provider=self._toolbar_provider,
                theme=self.theme,
                working_dir=self._working_dir,
                mode_cycler=self._mode_cycler,
                esc_command_provider=self._esc_command_provider,
            )

    @staticmethod
    def _stdin_is_console() -> bool:
        """False when stdin is a pipe (Git Bash mintty, redirects) --
        prompt_toolkit gets instant EOF there and the app would exit at once.
        stdin 是管道时（Git Bash mintty/重定向）返回 False——
        prompt_toolkit 在这种环境下立即 EOF，程序会秒退。"""
        import sys

        try:
            return sys.stdin.isatty()
        except Exception:
            return False

    def interrupt_input(self) -> None:
        """Signal get_user_input() to return early for background result processing.
        通知 get_user_input() 提前返回以处理后台 agent 结果。"""
        if self._bg_interrupt_event is not None:
            self._bg_interrupt_event.set()
        if self._prompt_session is not None:
            try:
                app = self._prompt_session.app
                # Only when the prompt is actually running: between prompts
                # the buffer still holds the LAST SUBMITTED text (e.g.
                # "/spawn wait"), and saving it would pre-fill the next
                # prompt with a stale leftover (real-run: "/spawn wait"
                # reappeared in the input line after every re-attach).
                # 仅在 prompt 正在运行时处理：两次 prompt 之间缓冲区还留着
                # 上一次提交的文本（如 "/spawn wait"），存下来会把残留预填
                # 进下一次输入行（实测：每次 re-attach 后输入行都残留
                # "/spawn wait"）。
                if app.is_running:
                    self._saved_buffer_text = app.current_buffer.text
                    app.exit(result=_BG_INTERRUPT)
            except Exception:
                pass

    def _input_rule(self) -> None:
        """Bright rule framing the user input line: one printed above
        before the prompt, one below after input is confirmed.
        用户输入行的亮色边界线：输入前打上边线，确认后打下边线。"""
        u = self.theme.user_input
        self.console.print(f"[{u}]{'─' * self.console.width}[/{u}]")

    async def get_user_input(self) -> str | object:
        """Wait for user input, or return ``_BG_INTERRUPT`` if a background
        agent completes while waiting.
        等待用户输入；若等待期间后台 agent 完成则返回 _BG_INTERRUPT。"""
        # Top rule marking the input area (bottom toolbar is the lower bound)
        # 输入区上边界线（下边界在输入确认后补上）
        self._input_rule()

        self._bg_interrupt_event = asyncio.Event()

        if not self._stdin_is_console():
            # Non-TTY: race input() executor against bg interrupt event
            # 非 TTY：input() 线程与后台中断事件竞争
            if self._pending_input_task is not None and self._pending_input_task.done():
                task = self._pending_input_task
                self._pending_input_task = None
                self._bg_interrupt_event = None
                self._input_rule()
                return task.result()

            input_task = self._pending_input_task or asyncio.ensure_future(
                asyncio.get_event_loop().run_in_executor(None, input, "> ")
            )
            self._pending_input_task = None
            event_task = asyncio.ensure_future(self._bg_interrupt_event.wait())
            done, _pending = await asyncio.wait(
                {input_task, event_task}, return_when=asyncio.FIRST_COMPLETED
            )
            if event_task in done:
                self._pending_input_task = input_task
                self._bg_interrupt_event = None
                return _BG_INTERRUPT
            event_task.cancel()
            self._bg_interrupt_event = None
            self._input_rule()
            return input_task.result()

        # TTY: prompt_toolkit path
        self._ensure_prompt_session()
        assert self._prompt_session is not None
        from prompt_toolkit.patch_stdout import patch_stdout

        default = self._saved_buffer_text
        self._saved_buffer_text = ""
        with patch_stdout(raw=True):
            result = await self._prompt_session.prompt_async(default=default)
        self._bg_interrupt_event = None
        if result is _BG_INTERRUPT:
            return _BG_INTERRUPT
        self._input_rule()
        return result

    @staticmethod
    async def _prompt_protected(session, message: str) -> str:
        """prompt_async wrapped in patch_stdout so concurrent output (trace
        lines from parallel tools) reroutes above the prompt instead of
        printing into the input line. Falls back to a bare prompt when the
        stdout proxy cannot be built (environments without a console).
        prompt_async 外包 patch_stdout——等输入期间并行工具的 trace 行
        重定向到提示行上方而非打进输入行；无控制台环境建不出 proxy 时
        退回裸 prompt。"""
        from prompt_toolkit.patch_stdout import patch_stdout

        try:
            ctx = patch_stdout(raw=True)
            ctx.__enter__()
        except Exception:
            ctx = None
        try:
            return await session.prompt_async(message)
        finally:
            if ctx is not None:
                ctx.__exit__(None, None, None)

    _SAVE_FOLLOWUP = "save permanently (project permissions.toml)? [y/N] > "

    async def confirm(self, prompt: str, offer_persist: bool = False) -> bool | str:
        """Ask user for confirmation.
        Returns True (allow once), False (deny), "always" (allow for session),
        or "always-save" (allow + persist a rule to permissions.toml).
        offer_persist=True (permission-manager dialogs only): after "a" a
        one-line follow-up asks whether to persist -- default is No, so
        nothing is written to disk without an explicit yes. Other consumers
        (CONFIRM hooks, sub-agent pane protocol) have no persistence
        semantics, so they never see the follow-up.
        Note: denying a dangerous command stops the whole goal at once (the
        loop's dangerous-denial breaker, threshold 1) -- no need to deny again.
        返回 True（允许一次）、False（拒绝）、"always"（本会话总是允许）、
        "always-save"（允许并持久化规则到 permissions.toml）。
        offer_persist=True（仅权限管理器弹窗）：按 a 后追问一行是否持久化
        ——默认否，不显式确认绝不写盘；其他消费方（CONFIRM hook、子 agent
        pane 协议）无持久化语义，不出现追问。
        注意：拒绝一条危险命令会一次性停止整个目标（循环的危险命令熔断，
        阈值 1）——不必再逐条拒绝。
        """
        self.flush_tool_group()
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
        # Temporary session: passing a message to the shared main session's
        # prompt_async() would become its new DEFAULT -- every later main
        # prompt would show "allow? [y/a/n] >".
        # 临时 session：给主输入 session 的 prompt_async() 传 message 会成为
        # 其新默认值——之后主提示符会一直显示 "allow? [y/a/n] >"。
        from prompt_toolkit import PromptSession as _PS

        def _plain_confirm() -> bool | str:
            try:
                answer = input("allow? [y/a/n] > ").strip().lower()
            except EOFError:
                return False  # non-interactive: safe default 无交互时安全默认拒绝
            if answer in ("a", "always"):
                if not offer_persist:
                    return "always"
                try:
                    save = input(self._SAVE_FOLLOWUP).strip().lower()
                except EOFError:
                    return "always"
                return "always-save" if save in ("y", "yes") else "always"
            return answer in ("y", "yes")

        try:
            tmp: Any = _PS()
        except Exception:
            return _plain_confirm()

        async def _ask_save() -> bool | str:
            if not offer_persist:
                return "always"
            try:
                save = (await self._prompt_protected(tmp, self._SAVE_FOLLOWUP)).strip().lower()
            except Exception:
                return "always"
            return "always-save" if save in ("y", "yes") else "always"

        while True:
            try:
                answer = (await self._prompt_protected(tmp, "allow? [y/a/n] > ")).strip().lower()
            except Exception:
                return _plain_confirm()
            if answer in ("y", "yes"):
                return True
            if answer in ("a", "always"):
                return await _ask_save()
            if answer in ("n", "no"):
                return False

    async def ask_yes_no(self, prompt: str) -> bool:
        """Plain yes/no using a temporary prompt (does not pollute the main session).
        使用临时提示的朴素是/否（不污染主输入 session 的默认 message）。"""
        self.flush_tool_group()
        from prompt_toolkit import PromptSession as _PS

        def _plain_input() -> bool:
            # Fallback for terminals prompt_toolkit cannot drive (Git Bash
            # mintty pipes stdin, so PromptSession may construct fine but
            # hit instant EOF on read).
            # prompt_toolkit 无法驱动的终端兜底（Git Bash 的 mintty 管道化
            # stdin——PromptSession 构造成功但读取立即 EOF）。
            try:
                answer = input(f"{prompt} [y/n] > ").strip().lower()
            except EOFError:
                return False  # non-interactive: safe default 无交互时安全默认拒绝
            return answer in ("y", "yes")

        try:
            tmp: Any = _PS()
        except Exception:
            return _plain_input()

        while True:
            try:
                answer = (await self._prompt_protected(tmp, f"{prompt} [y/n] > ")).strip().lower()
            except Exception:
                return _plain_input()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no", ""):
                return False

    async def ask_structured(self, question: str, choices: list[str] | None = None) -> str:
        """Structured question for the ask_user tool.
        ask_user 工具用的结构化提问。有 choices 时显示编号选项,
        无 choices 时自由文本输入。"""
        self.flush_tool_group()
        from prompt_toolkit import PromptSession as _PS
        from rich.panel import Panel

        lines = [f"[bold]{question}[/bold]"]
        if choices:
            for i, c in enumerate(choices, 1):
                lines.append(f"  {i}. {c}")
            lines.append("")
            lines.append("[dim]Enter the number or type your answer[/dim]")
        p = self.theme.primary
        self.console.print(Panel("\n".join(lines), border_style=p, title="Question from Agent"))

        def _plain() -> str:
            try:
                return input("> ").strip()
            except EOFError:
                return ""

        try:
            tmp: Any = _PS()
            raw = (await self._prompt_protected(tmp, "> ")).strip()
        except Exception:
            raw = _plain()

        if choices and raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        return raw

    def start_stream(self) -> None:
        # Live start is deferred to the first ANSWER delta (feed_stream):
        # thinking deltas arrive first, and console.print during an active
        # Live is intercepted -- each print becomes its own line block above
        # the Live area, end="" is lost, every tiny delta lands on its own
        # line (the fragmented-lines bug). No Live during thinking = direct
        # sequential writes, the terminal tracks the real cursor column.
        # Live 延迟到第一个正文 delta（feed_stream）才启动：thinking 先到，
        # 而 Live 活跃期间 console.print 会被拦截——每次 print 成为 Live 区
        # 上方的独立行块，end="" 失效，每个小增量各自成行（碎行 bug）。
        # 思考期间无 Live = 直连顺序写入，终端保持真实光标列位。
        self.flush_tool_group()
        self.console.print()
        self._live_started = False
        self._thinking_written = False

    def feed_stream(self, delta: str) -> None:
        if not self._live_started:
            self._live_started = True
            if self._thinking_written:
                # End the dangling thinking line + blank separator before answer
                # 收尾思考行 + 空行分隔，再开始正文
                self.console.print("\n")
            self.renderer.start()
        self.renderer.feed(delta)

    def feed_thinking(self, delta: str) -> None:
        """Write thinking delta directly in dim style -- no Live is active
        during thinking (see start_stream). soft_wrap=True keeps Rich from
        word-wrapping each tiny delta as an independent render unit against
        console.width; line-breaking is left to the terminal. Trade-off:
        over-wide thinking text hard-wraps at the terminal edge.
        思考增量以 dim 样式直连写入——思考期间无 Live（见 start_stream）。
        soft_wrap=True 防止 Rich 把每个小增量当独立渲染单元按宽度折行，
        折行交给终端。代价：超宽思考文本按终端边缘硬折行。"""
        self._thinking_written = True
        self.console.print(delta, end="", style="dim italic", highlight=False, soft_wrap=True)

    def finish_stream(self) -> str:
        result = self.renderer.finish()
        self.console.print()
        return result

    def show_error(self, error: str) -> None:
        self.flush_tool_group()
        self.console.print(f"  [bold {self.theme.error}]✗[/bold {self.theme.error}] {error}")
        self.console.print()

    def show_info(self, message: str) -> None:
        self.console.print(f"  [dim]{message}[/dim]")

    def show_tool_call(self, name: str, args: dict) -> None:
        if self.collapse_tool_calls and name in _COLLAPSIBLE_TOOLS:
            self._ro_add(name, args)
            return
        self.flush_tool_group()
        arg_preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
        self._print_tool_call_line(name, arg_preview)

    def show_tool_result(
        self, name: str, output: str, is_error: bool = False, metadata: dict | None = None
    ) -> None:
        if is_error:
            # Errors must stay on screen: expand the group (call lines
            # reprinted), then print the error line normally.
            # 错误必须留在屏上：展开组（补打调用行）后按原样打错误行。
            self.flush_tool_group()
            preview = output[:300] + "..." if len(output) > 300 else output
            e = self.theme.error
            self.console.print(f"  [dim]╰─[/dim] [{e}]✗ {preview}[/{e}]", highlight=False)
            return
        if name in _COLLAPSIBLE_TOOLS and self._ro_result(name, output):
            return
        self._print_tool_ok_line(output.count("\n") + 1, len(output))
        # Diff preview for edit_file edit_file 的 diff 预览
        if metadata and metadata.get("diff"):
            self._render_diff(metadata["diff"])

    def _print_tool_call_line(self, name: str, arg_preview: str) -> None:
        p = self.theme.primary
        self.console.print(
            f"\n  [dim]╭─[/dim] [bold {p}]{name}[/bold {p}] [dim]{arg_preview}[/dim]",
            highlight=False,
        )

    def _print_tool_ok_line(self, lines: int, chars: int) -> None:
        s = self.theme.success
        self.console.print(
            f"  [dim]╰─[/dim] [{s}]✓[/{s}] [dim]{lines} lines, {chars} chars[/dim]",
            highlight=False,
        )

    # --- Collapsible read-only tool group 可折叠只读工具组 ---

    def _ro_add(self, name: str, args: dict) -> None:
        """Add a read-only tool call to the live group (starting it if needed).
        把一次只读工具调用加入实时组（组不存在则启动）。"""
        import time as _time

        from rich.live import Live

        if self._ro_live is None:
            live = Live("", console=self.console, refresh_per_second=8, transient=True)
            try:
                live.start()
            except Exception:
                # Live unavailable (nested live / odd console): print normally
                # Live 不可用（嵌套 live/特殊控制台）：退回普通打印
                arg_preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
                self._print_tool_call_line(name, arg_preview)
                return
            self._ro_live = live
            self._ro_entries = []
            self._ro_start = _time.monotonic()
            self._ro_last_done = self._ro_start
        preview = ", ".join(f"{k}={self._truncate_value(v)}" for k, v in args.items())
        self._ro_entries.append(
            {"name": name, "preview": preview, "done": False, "lines": 0, "chars": 0}
        )
        self._ro_refresh()

    def _ro_result(self, name: str, output: str) -> bool:
        """Record a result inside the live group. False = no pending entry
        (group already flushed) -- caller prints the normal result line.
        在实时组内记录结果。False = 无待完成条目（组已被 flush），
        调用方按普通结果行打印。"""
        import time as _time

        if self._ro_live is None:
            return False
        for entry in self._ro_entries:
            if entry["name"] == name and not entry["done"]:
                entry["done"] = True
                entry["lines"] = output.count("\n") + 1
                entry["chars"] = len(output)
                self._ro_last_done = _time.monotonic()
                self._ro_refresh()
                return True
        return False

    def _ro_refresh(self) -> None:
        if self._ro_live is None:
            return
        from rich.text import Text

        p, s = self.theme.primary, self.theme.success
        rows = []
        for e in self._ro_entries:
            mark = f" [{s}]✓[/{s}]" if e["done"] else ""
            rows.append(f"  [dim]╭─[/dim] [{p}]{e['name']}[/{p}] [dim]{e['preview']}[/dim]{mark}")
        self._ro_live.update(Text.from_markup("\n".join(rows)))

    def flush_tool_group(self) -> None:
        """Finalize the read-only group: >=2 fully-done calls collapse into a
        one-line summary; otherwise reprint the buffered lines in the normal
        format (pending entries get their result line later via
        show_tool_result, which falls through once the group is gone).
        收束只读组：>=2 条且全部完成折叠为一行摘要；否则按普通格式补打
        缓冲行（未完成条目的结果行稍后经 show_tool_result 正常补上）。"""
        if self._ro_live is None:
            return
        live, entries = self._ro_live, self._ro_entries
        self._ro_live = None
        self._ro_entries = []
        live.update("")
        live.stop()
        done_count = sum(1 for e in entries if e["done"])
        if len(entries) >= 2 and done_count == len(entries):
            elapsed = self._ro_last_done - self._ro_start
            s = self.theme.success
            self.console.print(
                f"\n  [{s}]✓[/{s}] [dim]Done ({len(entries)} tool uses · {elapsed:.1f}s)[/dim]",
                highlight=False,
            )
            return
        for e in entries:
            self._print_tool_call_line(e["name"], e["preview"])
            if e["done"]:
                self._print_tool_ok_line(e["lines"], e["chars"])

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
