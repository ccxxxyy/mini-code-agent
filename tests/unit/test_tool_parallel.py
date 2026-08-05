"""Tests for parallel tool execution in _act(). 工具并行执行测试。"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolCall
from mini_agent.models.session import Session
from mini_agent.tools.base import (
    Tool,
    ToolContext,
    ToolParameter,
    ToolRegistry,
    ToolResult,
    ToolSchema,
)

pytestmark = pytest.mark.asyncio


class SlowTool(Tool):
    """A tool that sleeps for a configurable duration. 一个可配置延时的工具。"""

    def __init__(self, delay: float = 0.1):
        self._delay = delay

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="slow_tool",
            description="Sleeps then returns OK",
            parameters=[ToolParameter(name="tag", type="string", description="label")],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        await asyncio.sleep(self._delay)
        return ToolResult(call_id="", name="slow_tool", output=f"done:{kwargs.get('tag', '')}")


class InstantTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="instant_tool",
            description="Returns immediately",
            parameters=[],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(call_id="", name="instant_tool", output="instant")


class MockLLM(LLMProvider):
    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="done")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_loop(tmp_path, tools: list[Tool]) -> AgentLoop:
    registry = ToolRegistry()
    for t in tools:
        registry.register(t)
    ctx = ToolContext(
        working_dir=tmp_path, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    return AgentLoop(
        llm=MockLLM(),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=ctx,
    )


def make_tc(name: str, args: dict | None = None, call_id: str = "") -> ToolCall:
    return ToolCall(id=call_id or name, name=name, arguments=args or {})


async def test_parallel_faster_than_serial(tmp_path):
    loop = make_loop(tmp_path, [SlowTool(delay=0.1)])
    calls = [make_tc("slow_tool", {"tag": str(i)}, f"c{i}") for i in range(3)]
    start = time.monotonic()
    results = await loop._act(calls)
    elapsed = time.monotonic() - start
    assert len(results) == 3
    assert all(not r.is_error for r in results)
    assert elapsed < 0.25  # parallel ~0.1s, serial would be ~0.3s


async def test_single_tool_no_change(tmp_path):
    loop = make_loop(tmp_path, [InstantTool()])
    results = await loop._act([make_tc("instant_tool")])
    assert len(results) == 1
    assert results[0].output == "instant"


async def test_unknown_tool_returns_error(tmp_path):
    loop = make_loop(tmp_path, [])
    results = await loop._act([make_tc("nonexistent")])
    assert results[0].is_error
    assert "Unknown tool" in results[0].output


async def test_cancelled_returns_error(tmp_path):
    loop = make_loop(tmp_path, [SlowTool()])
    loop.cancel()
    results = await loop._act([make_tc("slow_tool", {"tag": "x"})])
    assert results[0].is_error
    assert "Cancelled" in results[0].output


async def test_results_preserve_order(tmp_path):
    loop = make_loop(tmp_path, [SlowTool(delay=0.05), InstantTool()])
    calls = [
        make_tc("slow_tool", {"tag": "first"}, "c0"),
        make_tc("instant_tool", call_id="c1"),
        make_tc("slow_tool", {"tag": "third"}, "c2"),
    ]
    results = await loop._act(calls)
    assert results[0].output == "done:first"
    assert results[1].output == "instant"
    assert results[2].output == "done:third"
