"""Shared LLM mocks for tests -- one MockLLM instead of a copy per file.
测试共享的 LLM mock——一份 MockLLM 取代每个文件各复制一份。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta


def text_response(text: str) -> list[StreamChunk]:
    """Script for a plain text answer. 纯文本回答的脚本。"""
    return [StreamChunk(delta=text), StreamChunk(finish_reason="stop")]


def tool_call_response(name: str, args: dict) -> list[StreamChunk]:
    """Script for a single tool call. 单个工具调用的脚本。"""
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="call_1", name=name, arguments_delta=json.dumps(args))
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


class MockLLM(LLMProvider):
    """Scripted mock provider replaying StreamChunk sequences.
    按脚本重放 StreamChunk 序列的 mock provider。

    - scripts: one chunk list per stream() call; the LAST script repeats for
      extra calls. Defaults to a single text answer built from *text*.
      每次 stream() 调用消费一个 chunk 列表，超出后重复最后一个；
      默认用 text 构造单条文本回答。
    - delay: async sleep before each call (concurrency tests). 每次调用前挂起。
    - error: exception raised by stream() instead of yielding. 抛错替代产出。
    - call_count: public counter of stream() invocations. 公开调用计数。
    """

    def __init__(
        self,
        scripts: list[list[StreamChunk]] | None = None,
        *,
        text: str = "Done.",
        delay: float = 0.0,
        error: Exception | None = None,
    ) -> None:
        self._scripts = scripts if scripts is not None else [text_response(text)]
        self._delay = delay
        self._error = error
        self.call_count = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        if self._error is not None:
            raise self._error
        if self._delay:
            await asyncio.sleep(self._delay)
        script = self._scripts[min(self.call_count, len(self._scripts) - 1)]
        self.call_count += 1
        for chunk in script:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000
