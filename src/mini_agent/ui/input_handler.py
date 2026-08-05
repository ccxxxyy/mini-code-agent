"""Input handling with Prompt Toolkit -- slash command auto-completion.
基于 Prompt Toolkit 的输入处理——斜杠命令自动补全。"""

from __future__ import annotations

from collections.abc import Iterator

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from mini_agent.ui.themes import Theme, get_theme


def create_prompt_style(theme: Theme | None = None) -> Style:
    """Build prompt_toolkit Style from a Theme. 从 Theme 构建 prompt_toolkit 样式。"""
    t = theme or get_theme("default")
    return Style.from_dict(
        {
            "prompt": f"bold {t.primary}",
            "completion-menu": "noinherit",
            "completion-menu.completion": f"noinherit {t.dim}",
            "completion-menu.completion.current": f"noinherit {t.primary} bold reverse",
            "completion-menu.meta.completion": f"noinherit {t.dim} italic",
            "completion-menu.meta.completion.current": f"noinherit {t.primary} italic reverse",
            "scrollbar.background": "noinherit",
            "scrollbar.button": f"noinherit {t.dim}",
            "bottom-toolbar": f"noinherit {t.dim}",
            "toolbar": f"noinherit {t.dim}",
        }
    )


class SlashCommandCompleter(Completer):
    """Auto-complete slash commands when input starts with '/'.
    当输入以 '/' 开头时自动补全斜杠命令。"""

    def __init__(self, commands: list[tuple[str, str]] | None = None) -> None:
        self._commands: list[tuple[str, str]] = commands or []

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self._commands = commands

    def get_completions(self, document: Document, complete_event) -> Iterator[Completion]:
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return

        typed = text[1:]
        for name, description in self._commands:
            if name.startswith(typed):
                yield Completion(
                    text="/" + name,
                    start_position=-len(text),
                    display=f"/{name}",
                    display_meta=description,
                )


def _make_history() -> FileHistory | InMemoryHistory:
    """File-backed history (persists across sessions); falls back to memory.
    基于文件的输入历史（跨会话保留）；失败时退回内存历史。
    """
    from pathlib import Path

    try:
        history_dir = Path.home() / ".mini-agent"
        history_dir.mkdir(parents=True, exist_ok=True)
        return FileHistory(str(history_dir / "input_history"))
    except OSError:
        return InMemoryHistory()


def create_prompt_session(
    completer: SlashCommandCompleter | None = None,
    toolbar_provider=None,
    theme: Theme | None = None,
) -> PromptSession:
    """Create a Prompt Toolkit session with multi-line support and completion.
    创建一个支持多行输入和补全的 Prompt Toolkit session。

    toolbar_provider: optional callable returning the bottom toolbar text
    (shown under the input line, e.g. current model name).
    toolbar_provider：可选的回调，返回输入框下方工具栏的文本
    （例如当前模型名）。
    """
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    def _retrigger_completion(buf: Buffer) -> None:
        """补全菜单只在文本变化时自动刷新，退格/光标移动后需手动重新触发。"""
        if buf.text.lstrip().startswith("/") and buf.cursor_position > 0:
            buf.start_completion()

    @bindings.add("backspace")
    def _backspace_with_complete(event) -> None:
        buf: Buffer = event.current_buffer
        buf.delete_before_cursor(1)
        _retrigger_completion(buf)

    @bindings.add("left")
    def _left_with_complete(event) -> None:
        buf: Buffer = event.current_buffer
        buf.cursor_position = max(0, buf.cursor_position - 1)
        _retrigger_completion(buf)

    @bindings.add("right")
    def _right_with_complete(event) -> None:
        buf: Buffer = event.current_buffer
        buf.cursor_position = min(len(buf.text), buf.cursor_position + 1)
        _retrigger_completion(buf)

    def _toolbar() -> HTML | None:
        if toolbar_provider is None:
            return None
        return HTML(f"<toolbar> {toolbar_provider()} </toolbar>")

    session: PromptSession = PromptSession(
        history=_make_history(),
        multiline=False,
        key_bindings=bindings,
        completer=completer,
        complete_while_typing=True,
        style=create_prompt_style(theme),
        message=HTML("<prompt>&gt; </prompt>"),
        reserve_space_for_menu=18,
        bottom_toolbar=_toolbar if toolbar_provider else None,
    )
    return session
