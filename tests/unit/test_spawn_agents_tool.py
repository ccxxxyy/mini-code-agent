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
