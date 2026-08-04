"""Tests for /spawn and /team slash commands. /spawn 和 /team 命令测试。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.subagent import SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import SubAgentCompleteEvent, SubAgentSpawnEvent
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    def __init__(self, text: str = "Done.", delay: float = 0.0):
        self._text = text
        self._delay = delay

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if self._delay:
            await asyncio.sleep(self._delay)
        yield StreamChunk(delta=self._text)
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_manager(tmp_path, text="Done.", delay=0.0) -> tuple[SubAgentManager, EventBus]:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    mgr = SubAgentManager(
        llm=MockLLM(text, delay=delay),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=bus,
        working_dir=tmp_path,
    )
    return mgr, bus


# --- /spawn basic ---


async def test_spawn_single(tmp_path):
    mgr, _ = make_manager(tmp_path)
    agent_id = await mgr.spawn("say hello")
    assert agent_id
    result = await mgr.wait(agent_id)
    assert result.success
    assert "Done." in result.output


async def test_spawn_parallel(tmp_path):
    mgr, _ = make_manager(tmp_path, delay=0.05)
    ids = await mgr.spawn_parallel(["task1", "task2", "task3"])
    assert len(ids) == 3
    results = await mgr.wait_all()
    assert len(results) == 3
    assert all(r.success for r in results)


async def test_spawn_list_and_cancel(tmp_path):
    mgr, _ = make_manager(tmp_path, delay=5.0)
    aid = await mgr.spawn("slow task")
    active = mgr.list_active()
    assert aid in active
    phase = mgr.get_status(aid)
    assert phase is not None
    mgr.cancel_all()
    # cancel_all only signals cancel, agent is still in _active until waited
    # cancel_all 只发信号，agent 仍在 _active 中直到被 wait
    assert aid in mgr.list_active()


# --- SubAgent events ---


async def test_spawn_emits_event(tmp_path):
    mgr, bus = make_manager(tmp_path)
    events: list[SubAgentSpawnEvent] = []

    async def on_spawn(e: SubAgentSpawnEvent) -> None:
        events.append(e)

    bus.on(SubAgentSpawnEvent, on_spawn)
    aid = await mgr.spawn("hello")
    assert len(events) == 1
    assert events[0].agent_id == aid
    assert events[0].task == "hello"


async def test_wait_emits_complete_event(tmp_path):
    mgr, bus = make_manager(tmp_path)
    events: list[SubAgentCompleteEvent] = []

    async def on_complete(e: SubAgentCompleteEvent) -> None:
        events.append(e)

    bus.on(SubAgentCompleteEvent, on_complete)
    aid = await mgr.spawn("hello")
    await mgr.wait(aid)
    assert len(events) == 1
    assert events[0].agent_id == aid
    assert events[0].success is True


# --- /spawn command handler ---


async def test_spawn_command_no_args(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    handler = _make_spawn(app)
    result = await handler("", None)
    assert "Usage" in result


async def test_spawn_command_list_empty(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    handler = _make_spawn(app)
    result = await handler("list", None)
    assert "No active" in result


# --- /team command handler ---


async def test_team_command_no_args(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_team

    app = _make_mock_app(tmp_path)
    handler = _make_team(app)
    result = await handler("", None)
    assert "Usage" in result


# --- helpers ---


def _make_mock_app(tmp_path):
    """Minimal mock app with SubAgentManager for command tests."""

    class MockApp:
        pass

    app = MockApp()
    app.config = AgentConfig()
    mgr, bus = make_manager(tmp_path)
    app.subagent_manager = mgr
    app.event_bus = bus
    return app
