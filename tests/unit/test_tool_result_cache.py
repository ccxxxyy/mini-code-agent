"""Tests for tool result spill-to-disk and post-compression recovery.
工具结果溢写与压缩后恢复的测试。"""

from pathlib import Path

import pytest

from mini_agent.memory.context import ContextManager
from mini_agent.memory.tool_result_cache import ToolResultCache
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role, ToolResult

pytestmark = pytest.mark.asyncio


def make_result(output: str, name: str = "read_file", is_error: bool = False) -> ToolResult:
    return ToolResult(call_id="c1", name=name, output=output, is_error=is_error)


# --- ToolResultCache ---


async def test_small_result_unchanged(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=100)
    r = make_result("short output")
    assert cache.maybe_spill(r) is r
    assert not (tmp_path / "cache").exists()  # nothing written


async def test_large_result_spilled(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=100)
    big = "x" * 500 + "\nline2\nline3"
    r = make_result(big)
    spilled = cache.maybe_spill(r)

    assert spilled is not r
    assert len(spilled.output) < len(big)
    assert "output too large for conversation" in spilled.output
    assert spilled.output.startswith("x" * 100)  # preview kept
    # Full content on disk 完整内容在磁盘上
    path = Path(spilled.metadata["spilled_path"])
    assert path.is_file()
    assert path.read_text(encoding="utf-8") == big
    assert spilled.metadata["full_chars"] == len(big)


async def test_error_result_never_spilled(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=10)
    r = make_result("e" * 100, is_error=True)
    assert cache.maybe_spill(r) is r


async def test_threshold_zero_disables(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=0)
    assert not cache.enabled
    r = make_result("y" * 10_000)
    assert cache.maybe_spill(r) is r


async def test_cleanup_removes_dir(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache = ToolResultCache(cache_dir, threshold_chars=10)
    cache.maybe_spill(make_result("z" * 100))
    assert cache_dir.exists()
    cache.cleanup()
    assert not cache_dir.exists()


# --- ContextManager read-file tracking ---


async def test_record_file_read_dedup_ordered():
    cm = ContextManager(MemoryConfig())
    cm.record_file_read("a.py")
    cm.record_file_read("b.md")
    cm.record_file_read("a.py")  # duplicate
    assert cm.read_files == ["a.py", "b.md"]


async def test_compression_injects_read_files():
    from mini_agent.memory.compressor import Compressor

    cm = ContextManager(MemoryConfig(context_window=200, compression_threshold=0.5))
    cm.set_compressor(Compressor())
    cm.record_file_read("spec.md")
    cm.record_file_read("tasks.md")

    conv = Conversation(system_prompt="sys")
    for i in range(20):
        conv.append(Message(role=Role.USER, content=f"msg {i}", token_count=25))

    compressed = await cm.check_and_compress(conv)
    assert compressed

    joined = "\n".join(m.content or "" for m in conv.messages)
    assert "[Files already read this session" in joined
    assert "spec.md" in joined
    assert "tasks.md" in joined


async def test_second_compression_replaces_stale_note():
    from mini_agent.memory.compressor import Compressor

    cm = ContextManager(MemoryConfig(context_window=200, compression_threshold=0.5))
    cm.set_compressor(Compressor())
    cm.record_file_read("first.py")

    conv = Conversation(system_prompt="sys")
    for i in range(20):
        conv.append(Message(role=Role.USER, content=f"msg {i}", token_count=25))
    await cm.check_and_compress(conv)

    # New file read, second compression 新读一个文件后二次压缩
    cm.record_file_read("second.py")
    for i in range(20):
        conv.append(Message(role=Role.USER, content=f"more {i}", token_count=25))
    await cm.check_and_compress(conv)

    joined = "\n".join(m.content or "" for m in conv.messages)
    assert "second.py" in joined
    # Note appears exactly once (stale one replaced) 清单只出现一次（旧的被替换）
    assert joined.count("[Files already read this session") == 1


async def test_no_read_files_no_note():
    from mini_agent.memory.compressor import Compressor

    cm = ContextManager(MemoryConfig(context_window=200, compression_threshold=0.5))
    cm.set_compressor(Compressor())

    conv = Conversation(system_prompt="sys")
    for i in range(20):
        conv.append(Message(role=Role.USER, content=f"msg {i}", token_count=25))
    await cm.check_and_compress(conv)

    joined = "\n".join(m.content or "" for m in conv.messages)
    assert "[Files already read this session" not in joined


# --- AgentLoop integration ---


async def test_agent_loop_spills_large_tool_output(tmp_path: Path):
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext, ToolRegistry
    from mini_agent.tools.builtin import ReadFileTool
    from tests.unit.test_agent_loop import (
        MockLLM,
        text_response,
        tool_call_response,
    )

    work = tmp_path / "work"
    work.mkdir()
    big_file = work / "big.txt"
    big_file.write_text("A" * 300 + "\n", encoding="utf-8")

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    ctx = ToolContext(
        working_dir=work, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    loop = AgentLoop(
        llm=MockLLM(
            [
                tool_call_response("read_file", {"file_path": str(big_file)}),
                text_response("done"),
            ]
        ),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=ctx,
    )
    loop.result_cache = ToolResultCache(tmp_path / "cache", threshold_chars=100)

    conv = Conversation()
    await loop.run(conv)

    tool_msgs = [m for m in conv.messages if m.tool_result]
    assert len(tool_msgs) == 1
    assert "output too large for conversation" in tool_msgs[0].tool_result.output
    assert "spilled_path" in tool_msgs[0].tool_result.metadata
