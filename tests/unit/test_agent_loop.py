"""Tests for the ReAct agent loop with a mock LLM provider.
使用 mock LLM provider 测试 ReAct Agent 循环。
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.agent_state import AgentPhase
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk, ToolCallDelta
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import Conversation, Role
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool

pytestmark = pytest.mark.asyncio


class MockLLM(LLMProvider):
    """Mock provider that replays scripted responses. 按脚本重放响应的 mock provider。"""

    def __init__(self, scripts: list[list[StreamChunk]]) -> None:
        self._scripts = scripts
        self._call_count = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
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


def tool_call_response(name: str, arguments: dict) -> list[StreamChunk]:
    return [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(
                    index=0,
                    id="call_1",
                    name=name,
                    arguments_delta=json.dumps(arguments),
                )
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]


def make_loop(scripts, tool_context, registry=None):
    config = AgentConfig()
    if registry is None:
        registry = ToolRegistry()
        registry.register(ReadFileTool())
    return AgentLoop(
        llm=MockLLM(scripts),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=tool_context,
    )


async def test_direct_answer_no_tools(tool_context):
    loop = make_loop([text_response("Hello!")], tool_context)
    conv = Conversation()
    result = await loop.run(conv)

    assert result == "Hello!"
    assert loop.state.phase == AgentPhase.IDLE
    assert len(conv.messages) == 1
    assert conv.messages[0].role == Role.ASSISTANT


async def test_tool_call_then_answer(tool_context):
    f = tool_context.working_dir / "data.txt"
    f.write_text("secret content", encoding="utf-8")

    scripts = [
        tool_call_response("read_file", {"file_path": str(f)}),
        text_response("The file contains: secret content"),
    ]
    loop = make_loop(scripts, tool_context)
    conv = Conversation()
    result = await loop.run(conv)

    assert "secret content" in result
    # assistant(tool_call) + tool(result) + assistant(answer)
    # assistant（工具调用）+ tool（结果）+ assistant（回答）
    assert len(conv.messages) == 3
    assert conv.messages[0].tool_calls[0].name == "read_file"
    assert conv.messages[1].role == Role.TOOL
    assert "secret content" in conv.messages[1].tool_result.output


async def test_unknown_tool_returns_error(tool_context):
    scripts = [
        tool_call_response("nonexistent_tool", {}),
        text_response("done"),
    ]
    loop = make_loop(scripts, tool_context)
    conv = Conversation()
    await loop.run(conv)

    tool_msg = conv.messages[1]
    assert tool_msg.tool_result.is_error
    assert "Unknown tool" in tool_msg.tool_result.output


async def test_invalid_args_returns_error(tool_context):
    # read_file requires file_path, send empty args
    # read_file 需要 file_path 参数，这里发送空参数
    scripts = [
        tool_call_response("read_file", {}),
        text_response("done"),
    ]
    loop = make_loop(scripts, tool_context)
    conv = Conversation()
    await loop.run(conv)

    tool_msg = conv.messages[1]
    assert tool_msg.tool_result.is_error
    assert "file_path" in tool_msg.tool_result.output


async def test_infinite_loop_guard(tool_context):
    f = tool_context.working_dir / "x.txt"
    f.write_text("data", encoding="utf-8")

    # LLM keeps calling the same tool forever LLM 一直重复调用同一个工具
    scripts = [tool_call_response("read_file", {"file_path": str(f)})]
    loop = make_loop(scripts, tool_context)
    conv = Conversation()
    await loop.run(conv)

    # Guard kicks in after 6 identical consecutive calls 连续 6 次相同调用后保护机制生效
    read_calls = [m for m in conv.messages if m.tool_calls]
    assert len(read_calls) <= 7


async def test_same_tool_name_dominance_guard(tool_context):
    files = []
    for i in range(15):
        f = tool_context.working_dir / f"f{i}.txt"
        f.write_text(f"data{i}", encoding="utf-8")
        files.append(f)

    config = AgentConfig(max_agent_iterations=20)
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    scripts = [tool_call_response("read_file", {"file_path": str(f)}) for f in files]
    loop = AgentLoop(
        llm=MockLLM(scripts),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=tool_context,
    )
    conv = Conversation()
    await loop.run(conv)

    assert loop.stopped_early
    assert loop.state.iteration <= 14


async def test_max_iterations_guard(tool_context):
    f = tool_context.working_dir / "x.txt"
    f.write_text("data", encoding="utf-8")

    config = AgentConfig(max_agent_iterations=3)
    registry = ToolRegistry()
    registry.register(ReadFileTool())

    # Alternate between two tools to bypass the same-tool guard
    # 在两个工具之间交替调用以绕过同一工具的保护机制
    scripts = [tool_call_response("read_file", {"file_path": str(f)})]
    loop = AgentLoop(
        llm=MockLLM(scripts),
        tool_registry=registry,
        event_bus=EventBus(),
        config=config,
        tool_context=tool_context,
    )
    conv = Conversation()
    await loop.run(conv)

    assert loop.state.iteration <= 3


async def test_stream_callbacks(tool_context):
    deltas = []
    loop = make_loop([text_response("streamed text")], tool_context)
    loop.on_stream_delta = deltas.append
    conv = Conversation()
    await loop.run(conv)

    assert "".join(deltas) == "streamed text"


async def test_tool_callbacks(tool_context):
    f = tool_context.working_dir / "cb.txt"
    f.write_text("x", encoding="utf-8")

    started = []
    ended = []
    scripts = [
        tool_call_response("read_file", {"file_path": str(f)}),
        text_response("done"),
    ]
    loop = make_loop(scripts, tool_context)
    loop.on_tool_start = lambda tc: started.append(tc.name)
    loop.on_tool_end = lambda tr: ended.append(tr.name)
    conv = Conversation()
    await loop.run(conv)

    assert started == ["read_file"]
    assert ended == ["read_file"]
