"""Double-Esc keypress watcher for interrupting streaming output.
双 Esc 按键监听器——用于中断流式输出。

Runs a daemon thread that polls stdin for Esc keypresses while the LLM
is streaming. Two Esc presses within 500ms sets an asyncio.Event that
the streaming loop checks to break early.
在 LLM 流式输出期间运行一个守护线程轮询 stdin 检测 Esc 按键。
500ms 内连按两次 Esc 触发 asyncio.Event，流式循环检测到后提前退出。
"""

from __future__ import annotations

import sys
import time
from threading import Thread

_DOUBLE_ESC_WINDOW = 0.5  # seconds between two Esc presses 两次 Esc 之间的秒数
_POLL_INTERVAL = 0.05  # 50ms polling interval 轮询间隔


def _is_tty() -> bool:
    try:
        return sys.stdin.isatty()
    except Exception:
        return False


if sys.platform == "win32":
    import msvcrt

    def _kbhit() -> bool:
        return bool(msvcrt.kbhit())

    def _getch() -> str:
        b = msvcrt.getch()
        if b in (b"\x00", b"\xe0"):
            msvcrt.getch()  # consume extended key second byte
            return ""
        return b.decode("utf-8", errors="replace")
else:

    def _kbhit() -> bool:
        import select

        r, _, _ = select.select([sys.stdin], [], [], 0)
        return bool(r)

    def _getch() -> str:
        return sys.stdin.read(1)


class EscWatcher:
    """Watches for double-Esc keypresses in a background daemon thread.
    在后台守护线程中监听双 Esc 按键。"""

    def __init__(self) -> None:
        self._triggered = False
        self._thread: Thread | None = None
        self._running = False

    def start(self) -> None:
        """Begin watching stdin (call when streaming starts).
        开始监听 stdin（流式开始时调用）。"""
        self._triggered = False
        if not _is_tty():
            return
        self._running = True
        self._thread = Thread(target=self._poll, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop watching (call when streaming ends).
        停止监听（流式结束时调用）。"""
        self._running = False
        if self._thread is not None:
            # Wait for the poll loop to exit so a lingering _getch() cannot
            # swallow the user's next keystroke after streaming ends.
            # 等轮询循环退出——防止残留的 _getch() 吞掉流式结束后用户的下一个按键。
            self._thread.join(timeout=0.2)
            self._thread = None

    @property
    def triggered(self) -> bool:
        return self._triggered

    def _poll(self) -> None:
        last_esc = 0.0
        while self._running:
            try:
                if _kbhit():
                    ch = _getch()
                    if ch == "\x1b":
                        now = time.monotonic()
                        if now - last_esc < _DOUBLE_ESC_WINDOW:
                            self._triggered = True
                            return
                        last_esc = now
            except Exception:
                return
            time.sleep(_POLL_INTERVAL)
