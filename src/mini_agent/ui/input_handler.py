"""Input handling with Prompt Toolkit -- slash command auto-completion.
基于 Prompt Toolkit 的输入处理——斜杠命令自动补全。"""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

PROMPT_STYLE = Style.from_dict(
    {
        # Input prompt
        "prompt": "bold #6c71c4",
        # Completion menu 补全菜单
        "completion-menu": "bg:#1a1a2e #e0e0e0",
        "completion-menu.completion": "bg:#1a1a2e #c0c0c0",
        "completion-menu.completion.current": "bg:#3d5afe #ffffff bold",
        "completion-menu.meta.completion": "bg:#1a1a2e #888888 italic",
        "completion-menu.meta.completion.current": "bg:#3d5afe #cccccc italic",
        # Scrollbar
        "scrollbar.background": "bg:#1a1a2e",
        "scrollbar.button": "bg:#3d5afe",
    }
)


class SlashCommandCompleter(Completer):
    """Auto-complete slash commands when input starts with '/'.
    当输入以 '/' 开头时自动补全斜杠命令。"""

    def __init__(self, commands: list[tuple[str, str]] | None = None) -> None:
        self._commands: list[tuple[str, str]] = commands or []

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self._commands = commands

    def get_completions(self, document: Document, complete_event):
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


def create_prompt_session(
    completer: SlashCommandCompleter | None = None,
) -> PromptSession:
    """Create a Prompt Toolkit session with multi-line support and completion.
    创建一个支持多行输入和补全的 Prompt Toolkit session。"""
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    @bindings.add("backspace")
    def _backspace_with_complete(event):
        buf: Buffer = event.current_buffer
        buf.delete_before_cursor(1)
        text = buf.text.lstrip()
        if text.startswith("/"):
            buf.start_completion()

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        multiline=False,
        key_bindings=bindings,
        completer=completer,
        complete_while_typing=True,
        style=PROMPT_STYLE,
        message=HTML("<prompt>&gt; </prompt>"),
        reserve_space_for_menu=12,
    )
    return session
