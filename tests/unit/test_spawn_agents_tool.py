"""Tests for SpawnAgentsTool (LLM autonomous sub-agent dispatch).
SpawnAgentsTool（LLM 自主派生子代理）测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.subagent import SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import SpawnAgentsTool
from mini_agent.tools.builtin.read_file import ReadFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    def __init__(self, text: str = "Done.", fail: bool = False):
        self._text = text
        self._fail = fail

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if self._fail:
            raise ConnectionError("boom")
        yield StreamChunk(delta=self._text)
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_ctx(tmp_path, with_manager: bool = True, fail: bool = False) -> ToolContext:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    mgr = None
    if with_manager:
        mgr = SubAgentManager(
            llm=MockLLM(fail=fail),
            tool_registry=registry,
            config=AgentConfig(),
            event_bus=bus,
            working_dir=tmp_path,
        )
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=bus,
        config=AgentConfig(),
        subagent_manager=mgr,
    )


async def test_spawn_agents_basic(tmp_path):
    ctx = make_ctx(tmp_path)
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["task one", "task two"])
    assert not result.is_error
    assert "2/2 succeeded" in result.output
    assert "task one" in result.output
    assert "task two" in result.output


async def test_spawn_agents_no_manager(tmp_path):
    ctx = make_ctx(tmp_path, with_manager=False)
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["something"])
    assert result.is_error
    assert "not available" in result.output


async def test_spawn_agents_empty_tasks(tmp_path):
    ctx = make_ctx(tmp_path)
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=[])
    assert result.is_error
    assert "No tasks" in result.output


async def test_spawn_agents_partial_failure(tmp_path):
    ctx = make_ctx(tmp_path, fail=True)
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["will fail"])
    assert "0/1 succeeded" in result.output
    assert "FAILED" in result.output


async def test_spawn_agents_not_in_subagent_clone(tmp_path):
    """SubAgent's cloned registry must NOT contain spawn_agents.
    SubAgent 克隆的 registry 不得包含 spawn_agents。"""
    from mini_agent.core.subagent import SubAgent

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(SpawnAgentsTool())

    agent = SubAgent(
        task="test",
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    # The internal loop's registry should not have spawn_agents
    # 内部循环的 registry 不应包含 spawn_agents
    tools = agent._loop._tools
    assert tools.get("spawn_agents") is None
    assert tools.get("read_file") is not None


# --- context summary observability + non-blocking background ---


async def test_build_context_summary_emits_events(tmp_path):
    """build_context_summary must emit Start/Done events with timing."""
    from mini_agent.models.events import ContextSummaryDoneEvent, ContextSummaryStartEvent
    from mini_agent.models.message import Message, Role

    ctx = make_ctx(tmp_path)
    mgr = ctx.subagent_manager
    events: list = []

    async def _collect_start(e: ContextSummaryStartEvent) -> None:
        events.append(("start", e))

    async def _collect_done(e: ContextSummaryDoneEvent) -> None:
        events.append(("done", e))

    mgr._event_bus.on(ContextSummaryStartEvent, _collect_start)
    mgr._event_bus.on(ContextSummaryDoneEvent, _collect_done)

    msgs = [Message(role=Role.USER, content="hello")]
    summary = await mgr.build_context_summary(msgs)

    assert len(events) == 2
    assert events[0][0] == "start"
    assert events[1][0] == "done"
    done_event = events[1][1]
    assert done_event.duration_ms >= 0
    assert done_event.char_count == len(summary)


async def test_background_inherit_context_returns_immediately(tmp_path):
    """background=True + inherit_context=True should return instantly,
    deferring summary+spawn to a background task."""
    import asyncio

    from mini_agent.models.message import Conversation, Message, Role

    ctx = make_ctx(tmp_path)
    ctx.session.conversation = Conversation()
    ctx.session.conversation.append(Message(role=Role.USER, content="discuss plan"))

    tool = SpawnAgentsTool()
    result = await tool.execute(
        ctx,
        tasks=["summarize discussion"],
        background=True,
        inherit_context=True,
    )
    assert not result.is_error
    assert "background" in result.output.lower()
    assert "context fork" in result.output.lower()
    await asyncio.sleep(0.3)


async def test_trace_renderer_ctx_summary(tmp_path):
    """TraceRenderer must render context summary events."""
    from unittest.mock import MagicMock

    from mini_agent.models.events import ContextSummaryDoneEvent, ContextSummaryStartEvent
    from mini_agent.ui.trace import TraceRenderer

    console = MagicMock()
    renderer = TraceRenderer(console)
    renderer.enabled = True

    bus = EventBus()
    renderer.attach(bus)

    await bus.emit(ContextSummaryStartEvent())
    await bus.emit(ContextSummaryDoneEvent(duration_ms=1234.5, char_count=500))

    assert console.print.call_count == 2
    calls = [str(c) for c in console.print.call_args_list]
    assert any("summarizing" in c for c in calls)
    assert any("summary ready" in c for c in calls)

    renderer.detach(bus)


# --- plan mode blocks spawning (read-only escape via ungated sub-agents) ---
# plan 模式禁止派生（子 agent 不经权限门，任何派生都是只读逃逸口）


async def test_spawn_agents_denied_in_plan_mode(tmp_path):
    import types

    ctx = make_ctx(tmp_path)
    ctx.agent_loop_ref = types.SimpleNamespace(
        get_plan_mode=lambda: True,
        set_plan_mode=lambda v: None,
    )
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["do research"])
    assert result.is_error
    assert "Plan mode is read-only" in result.output


async def test_spawn_agents_allowed_outside_plan_mode(tmp_path):
    import types

    ctx = make_ctx(tmp_path)
    ctx.agent_loop_ref = types.SimpleNamespace(
        get_plan_mode=lambda: False,
        set_plan_mode=lambda v: None,
    )
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["say done"])
    assert not result.is_error
