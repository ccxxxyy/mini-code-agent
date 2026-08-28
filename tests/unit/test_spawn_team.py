"""Tests for /spawn and /team slash commands. /spawn 和 /team 命令测试。"""

from __future__ import annotations

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
from tests.mocks import MockLLM

pytestmark = pytest.mark.asyncio


def make_manager(tmp_path, text="Done.", delay=0.0) -> tuple[SubAgentManager, EventBus]:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    bus = EventBus()
    mgr = SubAgentManager(
        llm=MockLLM(text=text, delay=delay),
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


# --- Circuit breaker = failure 熔断即失败 ---


class LoopingLLM(LLMProvider):
    """Always emits a tool call -- forces the iteration limit breaker.
    永远发出工具调用——强制触发迭代上限熔断。"""

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        import json as _json

        from mini_agent.llm.base import ToolCallDelta

        yield StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(
                    index=0,
                    id="c1",
                    name="read_file",
                    arguments_delta=_json.dumps({"file_path": "nonexistent.txt"}),
                )
            ]
        )
        yield StreamChunk(finish_reason="tool_calls")

    def count_tokens(self, text: str) -> int:
        return 0

    @property
    def context_window(self) -> int:
        return 128_000


async def test_stopped_early_marks_failure(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    config = AgentConfig()
    config.max_agent_iterations = 3  # small limit 小上限快速触发
    mgr = SubAgentManager(
        llm=LoopingLLM(),
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    aid = await mgr.spawn("loop forever")
    result = await mgr.wait(aid, timeout=10)
    assert not result.success
    assert "Stopped early" in (result.error or "")


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


# --- background-by-default 默认后台自动投递 ---


async def test_spawn_default_is_background(tmp_path):
    """No-flag spawn goes through spawn_background (auto-delivery).
    无 flag 派发走 spawn_background（自动投递）。"""
    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    handler = _make_spawn(app)
    result = await handler("say hello", None)

    assert "auto-delivered" in result
    # The background watcher is registered 后台通知 watcher 已注册
    mgr = app.subagent_manager
    assert len(mgr._background_ids) == 1
    await mgr.wait_all(timeout=10)


async def test_spawn_parallel_default_is_background(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    handler = _make_spawn(app)
    result = await handler("-p task one | task two", None)

    assert "auto-delivered" in result
    assert len(app.subagent_manager._background_ids) == 2
    await app.subagent_manager.wait_all(timeout=10)


async def test_spawn_background_flag_is_noop_alias(tmp_path):
    """--background must not error and behaves like the default.
    --background 是 no-op 别名：不报错，行为与默认一致。"""
    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    handler = _make_spawn(app)
    result = await handler("--background say hello", None)

    assert "auto-delivered" in result
    assert len(app.subagent_manager._background_ids) == 1
    await app.subagent_manager.wait_all(timeout=10)


async def test_spawn_wait_flag_still_blocks(tmp_path):
    """--wait remains the blocking opt-in path (returns the formatted result).
    --wait 仍是阻塞式 opt-in（直接返回格式化结果）。"""
    from types import SimpleNamespace

    from mini_agent.extensions.builtin_commands import _make_spawn

    app = _make_mock_app(tmp_path)
    app.terminal = SimpleNamespace(console=None, theme=None)
    handler = _make_spawn(app)
    result = await handler("--wait say hello", None)

    # Blocking path returns the agent's result inline, not a dispatch notice
    # 阻塞路径直接内联返回结果，而非派发提示
    assert "auto-delivered" not in result
    assert "Done." in result
    assert app.subagent_manager._background_ids == set()


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
