"""Streaming output renderer using Rich. 使用 Rich 的流式输出渲染器。"""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown

_TAIL_LINES = 15


def _tick_info(line: str) -> tuple[int, str]:
    s = line.strip()
    ticks = len(s) - len(s.lstrip("`"))
    if ticks < 3:
        return 0, ""
    return ticks, s[ticks:].strip()


def _stack_step(stack: list[tuple[int, str]], line: str) -> None:
    """围栏栈状态转移。LLM 常输出同长度嵌套围栏（外层 ``` 包住 ```bash 块），
    这在 CommonMark 中非法且会提前断开外层。按嵌套意图解释：
    带语言标识 = 开启（可嵌套），纯反引号 = 关闭最内层。"""
    ticks, info = _tick_info(line)
    if not ticks:
        return
    if stack and not info and ticks >= stack[-1][0]:
        stack.pop()
    elif not stack or info:
        stack.append((ticks, info))


class StreamRenderer:
    """Renders streaming LLM output with progressive commit.
    逐段提交式流式渲染：已完成的段落永久打印固化，Live 区只渲染正在生成的尾段，
    避免内容超过终端高度时 Live 无法擦除屏外行导致的重复打印。"""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._buffer = ""
        self._full = ""
        self._live: Live | None = None

    def start(self) -> None:
        self._buffer = ""
        self._full = ""
        self._live = Live("", console=self._console, refresh_per_second=15)
        self._live.start()

    def feed(self, delta: str) -> None:
        self._buffer += delta
        self._full += delta
        if not self._live:
            return
        committed, tail = self._split_committed(self._buffer)
        if committed.strip():
            # Live 运行期间 console.print 会输出到 Live 区上方并固化到滚动区
            self._console.print(Markdown(self._normalize(committed)))
            self._console.print()
            self._buffer = tail
        self._live.update(self._render_tail(self._buffer))

    def finish(self) -> str:
        if self._live:
            self._live.update("")
            self._live.stop()
            self._live = None
        if self._buffer.strip():
            self._console.print(Markdown(self._normalize(self._buffer)))
        result = self._full
        self._buffer = ""
        self._full = ""
        return result

    @staticmethod
    def _normalize(text: str) -> str:
        """把非法的同长度嵌套围栏修成合法 CommonMark：
        外层围栏升级为比所有内层更长的反引号，整个引用保持在一个代码块内。"""
        lines = text.split("\n")

        def parse() -> list[dict]:
            stack: list[dict] = []
            roots: list[dict] = []
            for i, line in enumerate(lines):
                ticks, info = _tick_info(line)
                if not ticks:
                    continue
                if stack and not info and ticks >= stack[-1]["ticks"]:
                    node = stack.pop()
                    node["close"] = i
                    (stack[-1]["kids"] if stack else roots).append(node)
                elif not stack or info:
                    stack.append(
                        {"open": i, "close": None, "ticks": ticks, "lang": info, "kids": []}
                    )
            while stack:  # 未闭合围栏（流式尾段常见）
                node = stack.pop()
                (stack[-1]["kids"] if stack else roots).append(node)
            return roots

        def rewrite(node: dict) -> int:
            req = node["ticks"]
            for kid in node["kids"]:
                req = max(req, rewrite(kid) + 1)
            if req != node["ticks"]:
                lines[node["open"]] = "`" * req + node["lang"]
                if node["close"] is not None:
                    lines[node["close"]] = "`" * req
            return req

        for root in parse():
            rewrite(root)
        return "\n".join(lines)

    @staticmethod
    def _split_committed(text: str) -> tuple[str, str]:
        """在代码围栏之外的最后一个空行处切分：之前的内容可安全固化。"""
        lines = text.split("\n")
        stack: list[tuple[int, str]] = []
        last_safe = -1
        for i, line in enumerate(lines[:-1]):  # 最后一行可能不完整，不参与判定
            outside = not stack
            _stack_step(stack, line)
            if not line.strip() and outside:
                last_safe = i
        if last_safe <= 0:
            return "", text
        return "\n".join(lines[:last_safe]), "\n".join(lines[last_safe + 1 :])

    @classmethod
    def _render_tail(cls, tail: str) -> Markdown:
        """尾段超长时只渲染最后 N 行，防止 Live 区超过终端高度。"""
        lines = tail.split("\n")
        if len(lines) <= _TAIL_LINES:
            return Markdown(cls._normalize(tail))
        stack: list[tuple[int, str]] = []
        for line in lines[:-_TAIL_LINES]:
            _stack_step(stack, line)
        visible = "\n".join(lines[-_TAIL_LINES:])
        if stack:
            ticks, lang = stack[-1]
            visible = f"{'`' * ticks}{lang}\n{visible}"
        return Markdown(cls._normalize(visible))
