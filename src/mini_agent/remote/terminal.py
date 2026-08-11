"""Remote terminal adapter for browser mode (P57).
浏览器模式的远程终端适配器。

Wraps the real Terminal to intercept calls and send them to WebSocket.
包装真实 Terminal，截获调用并通过 WebSocket 发送。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mini_agent.ui.terminal import Terminal


class RemoteTerminalAdapter:
    """Wraps a Terminal to forward certain calls to WebSocket sender.
    包装 Terminal，将某些调用转发给 WebSocket 发送器。"""

    def __init__(self, terminal: Terminal, send_func: Any) -> None:
        self._terminal = terminal
        self._send_func = send_func  # asyncio.ensure_future(self._send(...))

    def __getattr__(self, name: str) -> Any:
        """Forward all attribute access to wrapped terminal.
        所有属性访问都转发给包装的 terminal。"""
        return getattr(self._terminal, name)

    def show_info(self, message: str) -> None:
        """Show info message in browser instead of terminal.
        在浏览器中显示信息而不是终端。"""
        # Send to browser via WebSocket
        try:
            self._send_func("info", message=message)
        except Exception:
            pass
        # Also log to terminal as fallback
        self._terminal.show_info(message)

    def show_error(self, message: str) -> None:
        """Show error message in browser instead of terminal.
        在浏览器中显示错误而不是终端。"""
        try:
            self._send_func("error", message=message)
        except Exception:
            pass
        self._terminal.show_error(message)

    def show_file_changes(self, changes: dict[str, str]) -> None:
        """Show file changes in browser instead of terminal.
        在浏览器中显示文件变更而不是终端。"""
        if not changes:
            return
        # Format for display
        display_items = []
        for path, change_type in changes.items():
            if change_type == "created":
                display_items.append(f"+ {path}")
            elif change_type == "modified":
                display_items.append(f"~ {path}")
            elif change_type == "deleted":
                display_items.append(f"- {path}")
        if display_items:
            try:
                self._send_func("file_changes", items=display_items)
            except Exception:
                pass
        self._terminal.show_file_changes(changes)
