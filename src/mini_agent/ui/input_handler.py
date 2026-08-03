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

PROMPT_STYLE = Style.from_dict(
    {
        # Input prompt
        "prompt": "bold #6c71c4",
        # Completion menu: transparent background (inherit terminal)
        # 补全菜单：透明背景（继承终端背景色）
        "completion-menu": "noinherit",
        "completion-menu.completion": "noinherit #c0c0c0",
        "completion-menu.completion.current": "noinherit #ffffff bold reverse",
        "completion-menu.meta.completion": "noinherit #888888 italic",
        "completion-menu.meta.completion.current": "noinherit #cccccc italic reverse",
        # Scrollbar: minimal 极简滚动条
        "scrollbar.background": "noinherit",
        "scrollbar.button": "noinherit #555555",
        # Bottom toolbar: dim text, transparent background
        # 底部工具栏：暗色文字，透明背景
        "bottom-toolbar": "noinherit #666666",
        "toolbar": "noinherit #666666",
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

    @bindings.add("backspace")
    def _backspace_with_complete(event) -> None:
        buf: Buffer = event.current_buffer
        buf.delete_before_cursor(1)
        text = buf.text.lstrip()
        if text.startswith("/"):
            buf.start_completion()

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
        style=PROMPT_STYLE,
        message=HTML("<prompt>&gt; </prompt>"),
        reserve_space_for_menu=12,
        bottom_toolbar=_toolbar if toolbar_provider else None,
    )
    return session
