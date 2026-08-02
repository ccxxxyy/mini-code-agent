"""Streaming output renderer using Rich."""

from __future__ import annotations

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown


class StreamRenderer:
    """Renders streaming LLM output in real-time with Markdown formatting."""

    def __init__(self, console: Console) -> None:
        self._console = console
        self._buffer = ""
        self._live: Live | None = None

    def start(self) -> None:
        self._buffer = ""
        self._live = Live(
            "",
            console=self._console,
            refresh_per_second=15,
            vertical_overflow="visible",
        )
        self._live.start()

    def feed(self, delta: str) -> None:
        self._buffer += delta
        if self._live:
            self._live.update(Markdown(self._buffer))

    def finish(self) -> str:
        if self._live:
            self._live.update(Markdown(self._buffer))
            self._live.stop()
            self._live = None
        result = self._buffer
        self._buffer = ""
        return result
