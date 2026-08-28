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
_ARM_GRACE = 0.3  # drain-only window after start 启动后只排空不判定的观察窗
_SEQUENCE_WINDOW = 0.03  # bytes within this window = escape sequence 序列字节到达窗口


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
    """Watches for Esc keypresses in a background daemon thread.
    Default: two presses within 500ms trigger (streaming interrupt).
    ``double=False``: a single press triggers (board detach).
    在后台守护线程中监听 Esc 按键。默认 500ms 内连按两次触发
    （流式中断）；double=False 时单击即触发（面板转后台）。"""

    def __init__(self, double: bool = True) -> None:
        self._double = double
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
        # Arming grace window: keep draining the buffer for a short period
        # after start. This discards BOTH keys pressed before the watcher
        # armed AND terminal-generated escape sequences emitted right after
        # the prompt hands the console over (real-run: a board detached
        # instantly on every run without any Esc pressed -- stray \x1b noise
        # in the input buffer at startup).
        # 启动观察窗：启动后先持续排空缓冲一小段时间——丢弃启动前按下的
        # 按键与提示符移交控制台瞬间终端产生的转义序列（实测：没按 Esc
        # 面板每次都秒转后台——启动时输入缓冲里有杂散 \x1b）。
        try:
            arm_deadline = time.monotonic() + _ARM_GRACE
            while time.monotonic() < arm_deadline:
                if not self._running:
                    return
                while _kbhit():
                    _getch()
                time.sleep(_POLL_INTERVAL)
        except Exception:
            return
        last_esc = 0.0
        while self._running:
            try:
                if _kbhit():
                    ch = _getch()
                    if ch == "\x1b":
                        # Lone-Esc discrimination: a human Esc press is a
                        # single byte; terminal replies / escape sequences
                        # (\x1b[...) arrive back-to-back. More bytes right
                        # behind the \x1b = sequence noise, discard it.
                        # 孤立 Esc 判别：人按的 Esc 是单字节；终端应答/转义
                        # 序列的后续字节紧随其后——\x1b 后面还有字节就是
                        # 序列噪声，整段丢弃。
                        time.sleep(_SEQUENCE_WINDOW)
                        if _kbhit():
                            while _kbhit():
                                _getch()
                            continue
                        if not self._double:
                            self._triggered = True
                            return
                        now = time.monotonic()
                        if now - last_esc < _DOUBLE_ESC_WINDOW:
                            self._triggered = True
                            return
                        last_esc = now
            except Exception:
                return
            time.sleep(_POLL_INTERVAL)
