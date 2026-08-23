"""Input handling with Prompt Toolkit -- slash command + @file auto-completion.
基于 Prompt Toolkit 的输入处理——斜杠命令 + @文件自动补全。"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion, merge_completers
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from mini_agent.ui.themes import Theme, get_theme

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea", ".vscode", ".mypy_cache"}
_AT_REF_RE = re.compile(r"@([\w./_\-\\]+(?:\.[\w]+)*)")
MAX_AT_REF_BYTES = 10_240


def create_prompt_style(theme: Theme | None = None) -> Style:
    """Build prompt_toolkit Style from a Theme. 从 Theme 构建 prompt_toolkit 样式。"""
    t = theme or get_theme("default")
    return Style.from_dict(
        {
            # Root style: typed input text is bold bright-orange, so the line
            # the user typed stays visually distinct in scrollback --
            # menu/toolbar/scrollbar all declare noinherit and are unaffected.
            # 根样式：输入文字 bold + 亮橙色，回车后输入行在滚动历史中
            # 醒目可辨——菜单/工具栏/滚动条均 noinherit 不受影响。
            "": f"bold {t.user_input}",
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

    @property
    def command_count(self) -> int:
        return len(self._commands)

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


class FileRefCompleter(Completer):
    """Auto-complete file paths after '@' for inline file references.
    在 '@' 后自动补全文件路径，支持内联文件引用。"""

    def __init__(self, working_dir: Path | None = None) -> None:
        self._working_dir = working_dir

    def set_working_dir(self, working_dir: Path) -> None:
        self._working_dir = working_dir

    def get_completions(self, document: Document, complete_event) -> Iterator[Completion]:
        if self._working_dir is None:
            return
        text = document.text_before_cursor
        at_idx = text.rfind("@")
        if at_idx < 0:
            return
        after = text[at_idx + 1 :]
        if " " in after or "\n" in after:
            return

        if "/" in after or "\\" in after:
            dir_part = os.path.dirname(after)
            name_prefix = os.path.basename(after).lower()
            scan_dir = self._working_dir / dir_part
        else:
            dir_part = ""
            name_prefix = after.lower()
            scan_dir = self._working_dir

        if not scan_dir.is_dir():
            return
        try:
            entries = sorted(os.listdir(scan_dir))
        except OSError:
            return

        for entry in entries:
            if entry in _SKIP_DIRS or entry.startswith("."):
                continue
            if not entry.lower().startswith(name_prefix):
                continue
            rel = os.path.join(dir_part, entry) if dir_part else entry
            is_dir = (scan_dir / entry).is_dir()
            display = f"{rel}/" if is_dir else rel
            yield Completion(
                text="@" + display,
                start_position=-(len(after) + 1),
                display=f"@{display}",
                display_meta="dir" if is_dir else "",
            )


def expand_at_refs(text: str, working_dir: Path) -> str:
    """Expand @filepath references to inline file content.
    展开 @文件路径 引用为内联文件内容。"""
    if "@" not in text:
        return text

    def _replace(m: re.Match) -> str:
        rel = m.group(1)
        full = working_dir / rel
        if not full.is_file():
            return m.group(0)
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
            if len(content) > MAX_AT_REF_BYTES:
                content = content[:MAX_AT_REF_BYTES] + "\n... (truncated)"
            return f"[File: {rel}]\n```\n{content}\n```"
        except Exception:
            return m.group(0)

    return _AT_REF_RE.sub(_replace, text)


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
    working_dir: Path | None = None,
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
        t = buf.text.lstrip()
        if (t.startswith("/") or "@" in t) and buf.cursor_position > 0:
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

    # Reserve enough rows for the FULL command menu so no entry is cut off.
    # +4: bottom toolbar row + input row + margins eat into the reserved space.
    # 为完整命令菜单预留足够行数，不截断任何条目。+4 容纳工具栏/输入行/边距。
    menu_rows = 18
    if completer is not None and completer.command_count > 0:
        menu_rows = min(completer.command_count + 4, 32)

    # Only reserve menu space (which scrolls the conversation up) while the
    # input actually starts with '/'. Normal typing keeps the layout compact.
    # 只在输入以 '/' 开头时才预留菜单空间（预留会把会话顶上去）——
    # 普通输入保持紧凑布局，不留大片空白。
    from prompt_toolkit.application import get_app
    from prompt_toolkit.filters import Condition

    @Condition
    def _completion_active() -> bool:
        try:
            buf_text = get_app().current_buffer.text.lstrip()
            return buf_text.startswith("/") or "@" in buf_text
        except Exception:
            return False

    merged = completer
    if working_dir is not None:
        file_completer = FileRefCompleter(working_dir)
        if completer is not None:
            merged = merge_completers([completer, file_completer])
        else:
            merged = file_completer

    session: PromptSession = PromptSession(
        history=_make_history(),
        multiline=False,
        key_bindings=bindings,
        completer=merged,
        complete_while_typing=_completion_active,
        style=create_prompt_style(theme),
        message=HTML("<prompt>&gt; </prompt>"),
        reserve_space_for_menu=menu_rows,
        bottom_toolbar=_toolbar if toolbar_provider else None,
    )
    _raise_menu_height_cap(session, menu_rows)
    return session


def _raise_menu_height_cap(session: PromptSession, menu_rows: int) -> None:
    """prompt_toolkit's CompletionsMenu has a hard-coded max_height=16 inside
    PromptSession's layout -- reserve_space_for_menu alone cannot exceed it.
    Walk the layout and lift the cap on the completions-menu window.
    prompt_toolkit 的 CompletionsMenu 在 PromptSession 布局里写死 max_height=16，
    单靠 reserve_space_for_menu 突破不了。遍历布局找到补全菜单窗口改掉上限。
    """
    try:
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.menus import CompletionsMenuControl

        for window in session.app.layout.find_all_windows():
            if isinstance(window.content, CompletionsMenuControl):
                window.height = Dimension(min=1, max=menu_rows)
    except Exception:
        pass  # layout internals changed in a future version -- keep default 布局内部变了就保持默认
