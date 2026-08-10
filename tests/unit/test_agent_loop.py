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
from mini_agent.tools.builtin import EditFileTool, ReadFileTool, WriteFileTool

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


async def test_same_tool_every_iteration_guard(tool_context):
    # Same tool called once per iteration for many rounds = a real loop
    # 同一工具每轮调一次持续多轮 = 真死循环
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
    assert loop.state.iteration <= 9  # guard fires after 8 consecutive rounds


async def test_batch_parallel_reads_not_killed(tool_context):
    # Many read_file calls within FEW iterations = normal batch work,
    # must NOT trigger the loop guard (real-world false positive fix)
    # 少数几轮内并行大量 read_file = 正常批量工作，不能误杀（实战误杀修复）
    import json as _json

    from mini_agent.llm.base import StreamChunk, ToolCallDelta

    files = []
    for i in range(10):
        f = tool_context.working_dir / f"b{i}.txt"
        f.write_text(f"data{i}", encoding="utf-8")
        files.append(f)

    def multi_tool_response(paths):
        deltas = [
            ToolCallDelta(
                index=j,
                id=f"call_{j}",
                name="read_file",
                arguments_delta=_json.dumps({"file_path": str(p)}),
            )
            for j, p in enumerate(paths)
        ]
        return [
            StreamChunk(tool_call_deltas=deltas),
            StreamChunk(finish_reason="tool_calls"),
        ]

    # 3 iterations x parallel reads, then a final answer -- like reading
    # all project docs 三轮并行读 + 最终回答——类似"读所有文档"场景
    scripts = [
        multi_tool_response(files[0:4]),
        multi_tool_response(files[4:8]),
        multi_tool_response(files[8:10]),
        text_response("Here is the summary of all files."),
    ]
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    loop = AgentLoop(
        llm=MockLLM(scripts),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(max_agent_iterations=20),
        tool_context=tool_context,
    )
    conv = Conversation()
    result = await loop.run(conv)

    assert not loop.stopped_early
    assert "summary" in result


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


# --- max_tokens recovery (P44) max_tokens 恢复 ---


class KwargsMockLLM(MockLLM):
    """MockLLM that records the kwargs of each stream() call.
    记录每次 stream() 调用 kwargs 的 MockLLM。"""

    def __init__(self, scripts):
        super().__init__(scripts)
        self.calls: list[dict] = []

    async def stream(self, messages, tools=None, **kwargs):
        self.calls.append(kwargs)
        async for chunk in super().stream(messages, tools, **kwargs):
            yield chunk


def truncated_response(text: str) -> list[StreamChunk]:
    return [StreamChunk(delta=text), StreamChunk(finish_reason="length")]


async def test_max_tokens_recovery_retries_with_doubled_limit(tool_context):
    # 第 1 次截断 → 翻倍重试成功
    llm = KwargsMockLLM([truncated_response("partial"), text_response("full answer")])
    loop = AgentLoop(
        llm=llm,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=tool_context,
    )
    conv = Conversation()
    result = await loop.run(conv)

    assert result == "full answer"
    assert len(llm.calls) == 2
    assert "max_tokens" not in llm.calls[0]  # 首次用 provider 默认
    assert llm.calls[1]["max_tokens"] == AgentConfig().llm.max_tokens * 2  # 翻倍


async def test_max_tokens_recovery_gives_up_after_retries(tool_context):
    # 全部截断：3 次重试后保留最后一次结果
    llm = KwargsMockLLM([truncated_response("still cut off")])
    loop = AgentLoop(
        llm=llm,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=tool_context,
    )
    conv = Conversation()
    result = await loop.run(conv)

    assert result == "still cut off"  # 保留截断结果而非丢弃
    assert len(llm.calls) == 1 + AgentLoop.MAX_TOKENS_RETRIES  # 1 原始 + 3 重试
    base = AgentConfig().llm.max_tokens
    assert llm.calls[1]["max_tokens"] == base * 2
    assert llm.calls[2]["max_tokens"] == base * 4
    assert llm.calls[3]["max_tokens"] == base * 8


async def test_no_retry_on_normal_finish(tool_context):
    # 正常结束不重试
    llm = KwargsMockLLM([text_response("ok")])
    loop = AgentLoop(
        llm=llm,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=tool_context,
    )
    conv = Conversation()
    await loop.run(conv)
    assert len(llm.calls) == 1


# --- Plan mode (P49) ---


def test_plan_mode_hides_write_schemas(tool_context):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(EditFileTool())
    loop = make_loop([text_response("ok")], tool_context, registry=registry)

    loop.plan_mode = False
    schemas_normal = loop._tools.get_schemas()
    names_normal = {s["function"]["name"] for s in schemas_normal}
    assert "write_file" in names_normal
    assert "edit_file" in names_normal

    loop.plan_mode = True
    from mini_agent.core.agent_loop import _WRITE_TOOLS

    filtered = [s for s in loop._tools.get_schemas() if s["function"]["name"] not in _WRITE_TOOLS]
    names_filtered = {s["function"]["name"] for s in filtered}
    assert "write_file" not in names_filtered
    assert "edit_file" not in names_filtered
    assert "read_file" in names_filtered


async def test_plan_mode_blocks_write_tool_call(tool_context):
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    scripts = [
        tool_call_response("write_file", {"file_path": "x.txt", "content": "bad"}),
        text_response("denied"),
    ]
    loop = make_loop(scripts, tool_context, registry=registry)
    loop.plan_mode = True
    conv = Conversation()
    await loop.run(conv)
    tool_msgs = [m for m in conv.messages if m.tool_result is not None]
    assert any("Permission denied" in m.tool_result.output for m in tool_msgs)


async def test_plan_mode_off_allows_write(tool_context):
    target = tool_context.working_dir / "new.txt"
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    scripts = [
        tool_call_response("write_file", {"file_path": str(target), "content": "hello"}),
        text_response("done"),
    ]
    loop = make_loop(scripts, tool_context, registry=registry)
    loop.plan_mode = False
    conv = Conversation()
    await loop.run(conv)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "hello"
