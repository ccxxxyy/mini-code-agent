"""Tests for SubAgent dispatch with mock LLM. 使用 mock LLM 测试 SubAgent 调度。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_types import get_agent_type
from mini_agent.core.subagent import SubAgent, SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool, WriteFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    """Replays a fixed script for every sub-agent. 为每个 SubAgent 重放固定脚本。"""

    def __init__(self, scripts: list[list[StreamChunk]], delay: float = 0.0):
        self._scripts = scripts
        self._delay = delay
        self._call_count = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        if self._delay:
            await asyncio.sleep(self._delay)
        script = self._scripts[min(self._call_count, len(self._scripts) - 1)]
        self._call_count += 1
        for chunk in script:
            yield chunk

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def text_response(text: str) -> list[StreamChunk]:
    return [StreamChunk(delta=text), StreamChunk(finish_reason="stop")]


def tool_call_response(name: str, args: dict) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(index=0, id="c1", name=name, arguments_delta=json.dumps(args))
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


def make_manager(scripts, tmp_path, delay=0.0):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    return SubAgentManager(
        llm=MockLLM(scripts, delay=delay),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )


async def test_subagent_completes_task(tmp_path):
    mgr = make_manager([text_response("Task done: created the file")], tmp_path)
    agent_id = await mgr.spawn("do something simple")
    result = await mgr.wait(agent_id)

    assert result.success
    assert "Task done" in result.output
    assert result.agent_id == agent_id


async def test_subagent_uses_tools(tmp_path):
    f = tmp_path / "data.txt"
    f.write_text("hello", encoding="utf-8")

    scripts = [
        tool_call_response("read_file", {"file_path": str(f)}),
        text_response("File contains: hello"),
    ]
    mgr = make_manager(scripts, tmp_path)
    agent_id = await mgr.spawn("read the data file")
    result = await mgr.wait(agent_id)

    assert result.success
    assert result.tool_calls_made == 1


async def test_spawn_parallel(tmp_path):
    mgr = make_manager([text_response("done")], tmp_path, delay=0.05)
    ids = await mgr.spawn_parallel(["task 1", "task 2", "task 3"])
    assert len(ids) == 3
    assert len(mgr.list_active()) == 3

    results = await mgr.wait_all(ids)
    assert len(results) == 3
    assert all(r.success for r in results)
    assert len(mgr.list_active()) == 0


async def test_parallel_faster_than_serial(tmp_path):
    """3 agents with 0.1s LLM delay should finish in ~0.1s, not ~0.3s.
    3 个带 0.1 秒 LLM 延迟的 Agent 应在约 0.1 秒内完成，而不是约 0.3 秒。"""
    import time

    mgr = make_manager([text_response("ok")], tmp_path, delay=0.1)
    start = time.monotonic()
    ids = await mgr.spawn_parallel(["a", "b", "c"])
    await mgr.wait_all(ids)
    elapsed = time.monotonic() - start

    # parallel: ~0.1s; serial would be ~0.3s+ 并行约 0.1 秒；串行则需约 0.3 秒以上
    assert elapsed < 0.35


async def test_wait_unknown_agent(tmp_path):
    mgr = make_manager([text_response("x")], tmp_path)
    result = await mgr.wait("nonexistent")
    assert not result.success
    assert "Unknown agent" in result.error


async def test_timeout(tmp_path):
    mgr = make_manager([text_response("slow")], tmp_path, delay=5.0)
    agent_id = await mgr.spawn("slow task")
    result = await mgr.wait(agent_id, timeout=0.2)
    assert not result.success
    assert "Timed out" in result.error


async def test_allowed_tools_filter(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="test",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
    )
    # The sub-agent's internal registry should only have read_file
    # SubAgent 的内部注册表应只包含 read_file
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("write_file") is None


async def test_subagent_isolated_registry(tmp_path):
    """Sub-agent's registry is a clone -- modifications don't affect parent.
    SubAgent 的注册表是克隆的——修改不会影响父级。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    SubAgent(
        task="t",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
    )
    # Parent registry untouched 父级注册表未受影响
    assert registry.get("write_file") is not None


# --- Agent type integration (P48) ---


async def test_subagent_with_explore_type(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="explore the codebase",
        llm=MockLLM([text_response("found it")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("explore"),
    )
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("write_file") is None
    assert "read-only" in agent._conversation.system_prompt.lower()


async def test_subagent_type_intersects_with_caller_tools(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="test",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        allowed_tools=["read_file"],
        agent_type=get_agent_type("explore"),
    )
    assert agent._loop._tools.get("read_file") is not None
    assert agent._loop._tools.get("glob") is None


async def test_subagent_type_overrides_max_iterations(tmp_path):
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    agent = SubAgent(
        task="verify something",
        llm=MockLLM([text_response("PASS")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("verify"),
    )
    assert "20" in agent._conversation.system_prompt


async def test_spawn_parallel_with_agent_type(tmp_path):
    mgr = make_manager([text_response("found it")], tmp_path)
    ids = await mgr.spawn_parallel(["search A", "search B"], agent_type="explore")
    assert len(ids) == 2
    results = await mgr.wait_all(ids)
    assert all(r.success for r in results)


# --- DEFAULT_AGENT_TYPE fallback (extension point #10) ---
# --- 默认 Agent 类型回退（拓展点 #10） ---


async def test_untyped_subagent_uses_default_type(tmp_path):
    """No agent_type -> the DEFAULT_AGENT_TYPE (worker) profile applies.
    未指定类型 -> 采用 DEFAULT_AGENT_TYPE（worker）档案。"""
    from mini_agent.core.agent_types import DEFAULT_AGENT_TYPE

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())

    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    worker = get_agent_type(DEFAULT_AGENT_TYPE)
    # Same prompt template as the default type (formatted with runtime values)
    # 与默认类型同一提示词模板（用运行时值格式化）
    head = worker.system_prompt.split("{", 1)[0]
    assert agent._conversation.system_prompt.startswith(head)
    # worker keeps all tools 保留全部工具
    assert agent._loop._tools.get("write_file") is not None


async def test_untyped_subagent_keeps_config_iterations(tmp_path):
    """Untyped spawn keeps config.max_agent_iterations, NOT the worker
    type's 50 -- the config is user-tunable and must win when no type is
    explicitly requested. 未指定类型时保留 config 的迭代预算而非 worker 的
    50——用户可配值优先。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    config = AgentConfig()
    config.max_agent_iterations = 7
    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert agent._loop._config.max_agent_iterations == 7
    assert "7" in agent._conversation.system_prompt  # iteration_budget 注入


async def test_typed_subagent_still_overrides_iterations(tmp_path):
    """Explicit type opt-in adopts the type's budget (worker = 50).
    显式选类型仍采纳类型预算（worker = 50）。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    config = AgentConfig()
    config.max_agent_iterations = 7
    agent = SubAgent(
        task="do something",
        llm=MockLLM([text_response("ok")]),
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=tmp_path,
        agent_type=get_agent_type("worker"),
    )
    assert agent._loop._config.max_agent_iterations == 50
