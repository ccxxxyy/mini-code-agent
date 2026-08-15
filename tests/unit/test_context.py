"""Tests for context manager and compression. 上下文管理器与压缩的测试。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.memory.compressor import (
    Compressor,
    DropToolResults,
    LLMSummarizeOldest,
    SlidingWindow,
    SummarizeOldest,
)
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult

pytestmark = pytest.mark.asyncio


def make_msg(role=Role.USER, content="x" * 100, token_count=25) -> Message:
    msg = Message(role=role, content=content)
    msg.token_count = token_count
    return msg


def make_tool_msg(output="y" * 500, token_count=125) -> Message:
    msg = Message(
        role=Role.TOOL,
        tool_result=ToolResult(call_id="c1", name="read_file", output=output),
    )
    msg.token_count = token_count
    return msg


# --- ContextManager ---


def test_count_message_caches():
    config = MemoryConfig(context_window=1000)
    cm = ContextManager(config)
    msg = Message(role=Role.USER, content="hello world")
    count1 = cm.count_message(msg)
    count2 = cm.count_message(msg)
    assert count1 == count2
    assert msg.token_count is not None


def test_update_total():
    config = MemoryConfig(context_window=1000)
    cm = ContextManager(config)
    conv = Conversation(system_prompt="sys")
    conv.messages = [make_msg(token_count=100), make_msg(token_count=100)]
    total = cm.update_total(conv)
    # 200 message tokens + system prompt tokens 消息 token 加 system prompt token
    assert total > 200


def test_usage_ratio():
    config = MemoryConfig(context_window=1000)
    cm = ContextManager(config)
    cm._total_tokens = 750
    assert cm.usage_ratio == 0.75
    assert cm.tokens_remaining == 250


def test_needs_compression_at_threshold():
    config = MemoryConfig(context_window=1000, compression_threshold=0.75)
    cm = ContextManager(config)
    cm._total_tokens = 750
    assert cm.needs_compression
    cm._total_tokens = 749
    assert not cm.needs_compression


async def test_check_and_compress_below_threshold():
    config = MemoryConfig(context_window=10000, compression_threshold=0.75)
    cm = ContextManager(config)
    conv = Conversation()
    conv.messages = [make_msg(token_count=10)]
    compressed = await cm.check_and_compress(conv)
    assert not compressed


async def test_check_and_compress_above_threshold():
    config = MemoryConfig(context_window=200, compression_threshold=0.5)
    cm = ContextManager(config)
    compressor = Compressor()
    cm.set_compressor(compressor)

    conv = Conversation()
    for _ in range(20):
        conv.messages.append(make_msg(token_count=25))

    compressed = await cm.check_and_compress(conv)
    assert compressed
    assert len(conv.messages) < 20


# --- DropToolResults ---


async def test_drop_tool_results():
    strategy = DropToolResults()
    conv = Conversation()
    conv.messages = [
        make_tool_msg(output="x" * 1000, token_count=250),
        make_msg(token_count=10),
    ]
    await strategy.compress(conv, 100)
    assert conv.messages[0].compressed
    assert len(conv.messages[0].tool_result.output) < 1000


async def test_drop_tool_results_skips_short():
    strategy = DropToolResults()
    conv = Conversation()
    msg = make_tool_msg(output="short", token_count=5)
    conv.messages = [msg]
    await strategy.compress(conv, 100)
    assert not msg.compressed


# --- SummarizeOldest ---


async def test_summarize_oldest():
    strategy = SummarizeOldest()
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=10))

    await strategy.compress(conv, 100)
    # Should have 1 summary + KEEP_RECENT messages
    assert len(conv.messages) == 1 + SummarizeOldest.KEEP_RECENT
    assert conv.messages[0].role == Role.SYSTEM
    assert conv.messages[0].compressed
    assert "[Compressed" in conv.messages[0].content


async def test_summarize_oldest_too_few():
    strategy = SummarizeOldest()
    conv = Conversation()
    conv.messages = [make_msg(token_count=10) for _ in range(3)]
    original_count = len(conv.messages)
    await strategy.compress(conv, 100)
    assert len(conv.messages) == original_count  # not enough to summarize


# --- LLMSummarizeOldest ---


class SummaryMockLLM(LLMProvider):
    """Mock LLM that returns a fixed summary or raises. 返回固定摘要或抛异常的 Mock。"""

    def __init__(self, summary: str = "Semantic summary.", fail: bool = False) -> None:
        self._summary = summary
        self._fail = fail
        self.call_count = 0

    async def stream(
        self, messages: list[dict[str, Any]], tools=None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]:
        self.call_count += 1
        if self._fail:
            raise ConnectionError("network down")
        yield StreamChunk(delta=self._summary)

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


async def test_llm_summarize_oldest():
    llm = SummaryMockLLM(summary="Goal: fix bug. Done: read 3 files.")
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=10))

    await strategy.compress(conv, 100)
    assert len(conv.messages) == 1 + LLMSummarizeOldest.KEEP_RECENT
    assert conv.messages[0].role == Role.SYSTEM
    assert conv.messages[0].compressed
    assert "LLM summary" in conv.messages[0].content
    assert "Goal: fix bug" in conv.messages[0].content
    assert llm.call_count == 1


async def test_llm_summarize_falls_back_on_error():
    llm = SummaryMockLLM(fail=True)
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=10))

    await strategy.compress(conv, 100)
    # Fallback to extractive digest, chain not broken 回退到抽取式摘要，压缩链不中断
    assert len(conv.messages) == 1 + LLMSummarizeOldest.KEEP_RECENT
    assert "[Compressed conversation history" in conv.messages[0].content
    assert "message 0" in conv.messages[0].content


async def test_llm_summarize_falls_back_on_empty():
    llm = SummaryMockLLM(summary="")
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=10))

    await strategy.compress(conv, 100)
    assert "message 0" in conv.messages[0].content  # extractive fallback


async def test_llm_summarize_too_few():
    llm = SummaryMockLLM()
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    conv.messages = [make_msg(token_count=10) for _ in range(3)]
    await strategy.compress(conv, 100)
    assert len(conv.messages) == 3
    assert llm.call_count == 0  # no LLM call when nothing to summarize


# --- SlidingWindow ---


async def test_sliding_window():
    strategy = SlidingWindow()
    conv = Conversation(system_prompt="sys")
    for i in range(50):
        conv.messages.append(make_msg(content=f"msg {i}", token_count=100))

    await strategy.compress(conv, 500)
    assert len(conv.messages) < 50
    # Most recent messages should be kept
    assert "msg 49" in conv.messages[-1].content


async def test_sliding_window_keeps_latest_user_message():
    # One user question followed by many huge tool results: the question
    # must survive truncation (task anchor), or the LLM forgets the task
    # 一个用户提问 + 大量工具结果：提问必须在截断后存活（任务锚点）
    strategy = SlidingWindow()
    conv = Conversation(system_prompt="sys")
    conv.messages.append(make_msg(role=Role.USER, content="explain all docs", token_count=10))
    for _ in range(30):
        conv.messages.append(make_tool_msg(token_count=200))

    await strategy.compress(conv, 800)

    user_msgs = [m for m in conv.messages if m.role == Role.USER]
    assert len(user_msgs) == 1
    assert user_msgs[0].content == "explain all docs"
    assert conv.messages[0].role == Role.USER  # anchored at the front 锚定在最前


# --- Full Compressor cascade --- 完整的 Compressor 级联


async def test_compressor_cascade():
    compressor = Compressor()
    conv = Conversation(system_prompt="sys")
    for i in range(30):
        conv.messages.append(make_msg(content=f"msg {i}", token_count=50))
        conv.messages.append(make_tool_msg(output="x" * 500, token_count=100))

    await compressor.compress(conv, 500)
    total = sum(m.token_count or 25 for m in conv.messages)
    assert total <= 500 or len(conv.messages) < 60


# --- ensure_fits overflow guard 溢出兜底 ---


async def test_ensure_fits_no_truncation():
    config = MemoryConfig(context_window=10000)
    cm = ContextManager(config)
    conv = Conversation(system_prompt="sys")
    conv.messages = [make_msg(token_count=10) for _ in range(5)]

    truncated = await cm.ensure_fits(conv, 10000)
    assert not truncated
    assert len(conv.messages) == 5


async def test_ensure_fits_truncates():
    config = MemoryConfig(context_window=200)
    cm = ContextManager(config)
    conv = Conversation(system_prompt="sys")
    for i in range(50):
        conv.messages.append(make_msg(content=f"msg {i}", token_count=50))

    truncated = await cm.ensure_fits(conv, 200)
    assert truncated
    assert len(conv.messages) < 50
    assert cm.total_tokens <= 200


# --- Tool-pair alignment (9.2b) 工具对对齐 ---


def make_call_msg(call_id="c1", token_count=25) -> Message:
    msg = Message(
        role=Role.ASSISTANT,
        tool_calls=[ToolCall(id=call_id, name="read_file", arguments={})],
    )
    msg.token_count = token_count
    return msg


async def test_summarize_oldest_aligns_tool_pair():
    # Split index lands on a tool result: the boundary must back up to
    # include the assistant tool_calls message, or the API returns 400.
    # 切分点落在 tool result 上：边界必须回退到包含 assistant 的
    # tool_calls 消息，否则 API 返回 400。
    strategy = SummarizeOldest()
    conv = Conversation()
    conv.messages = (
        [make_msg(content=f"m{i}", token_count=10) for i in range(12)]
        + [make_call_msg(), make_tool_msg(token_count=10), make_tool_msg(token_count=10)]
        + [make_msg(content=f"t{i}", token_count=10) for i in range(5)]
    )
    # naive split = len - 6 = 14, which is the second tool result
    await strategy.compress(conv, 100)

    assert conv.messages[0].role == Role.SYSTEM  # summary
    assert conv.messages[1].role == Role.ASSISTANT
    assert conv.messages[1].tool_calls  # pair head kept intact 配对头部完整保留
    assert conv.messages[2].role == Role.TOOL
    assert conv.messages[3].role == Role.TOOL


async def test_summarize_oldest_alignment_reaches_start():
    # Everything before the naive split is one giant tool pair: nothing
    # summarizable remains, so compression is a no-op.
    # 切分点之前全是一个工具对：没有可摘要的内容，压缩应为空操作。
    strategy = SummarizeOldest()
    conv = Conversation()
    conv.messages = [make_call_msg()] + [make_tool_msg(token_count=10) for _ in range(7)]
    await strategy.compress(conv, 100)
    assert len(conv.messages) == 8  # unchanged
    assert not any(m.compressed for m in conv.messages)


async def test_llm_summarize_aligns_tool_pair():
    llm = SummaryMockLLM()
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    conv.messages = (
        [make_msg(content=f"m{i}", token_count=10) for i in range(12)]
        + [make_call_msg(), make_tool_msg(token_count=10), make_tool_msg(token_count=10)]
        + [make_msg(content=f"t{i}", token_count=10) for i in range(5)]
    )
    await strategy.compress(conv, 100)

    assert conv.messages[1].role == Role.ASSISTANT
    assert conv.messages[1].tool_calls


async def test_sliding_window_drops_orphan_tool_results():
    # Token cut lands mid tool-pair: the orphaned tool results (whose
    # tool_use was dropped) must not survive.
    # token 切分落在工具对中间：孤儿 tool result（tool_use 已被丢弃）不能存活。
    strategy = SlidingWindow()
    conv = Conversation()
    conv.messages = [
        make_msg(role=Role.USER, content="do it", token_count=10),
        make_call_msg(token_count=100),
        make_tool_msg(token_count=10),
        make_tool_msg(token_count=10),
        make_msg(role=Role.ASSISTANT, content="done", token_count=10),
    ]
    # budget 35: fits [tool, tool, assistant] but not the tool_calls message
    await strategy.compress(conv, 35)

    assert all(m.role != Role.TOOL for m in conv.messages)
    assert conv.messages[-1].content == "done"
    assert conv.messages[0].role == Role.USER  # task anchor still applies


# --- Compression circuit breaker (9.2c) 压缩熔断器 ---


class NoOpCompressor:
    """Compressor that does nothing -- simulates ineffective compression."""

    async def compress(self, conversation, target_tokens):
        pass


async def test_circuit_breaker_trips_after_max_failures():
    config = MemoryConfig(context_window=200, compression_threshold=0.5, compress_max_failures=3)
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(20):
        conv.messages.append(make_msg(token_count=25))

    for i in range(3):
        result = await cm.check_and_compress(conv)
        assert result is True
    assert cm._compress_failures == 3

    result = await cm.check_and_compress(conv)
    assert result is False


async def test_circuit_breaker_resets_on_success():
    config = MemoryConfig(context_window=200, compression_threshold=0.5, compress_max_failures=3)
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(20):
        conv.messages.append(make_msg(token_count=25))

    await cm.check_and_compress(conv)
    await cm.check_and_compress(conv)
    assert cm._compress_failures == 2

    cm.set_compressor(Compressor())
    await cm.check_and_compress(conv)
    assert cm._compress_failures == 0


async def test_circuit_breaker_warns_only_once(caplog):
    # check_and_compress runs twice per iteration -- repeated WARNING floods
    # the console 每轮迭代检查两次，重复 WARNING 会刷屏
    import logging

    config = MemoryConfig(context_window=200, compression_threshold=0.5, compress_max_failures=3)
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(20):
        conv.messages.append(make_msg(token_count=25))

    for _ in range(3):
        await cm.check_and_compress(conv)

    with caplog.at_level(logging.WARNING, logger="mini_agent.memory.context"):
        for _ in range(5):
            assert await cm.check_and_compress(conv) is False
    warnings = [r for r in caplog.records if "circuit breaker open" in r.message]
    assert len(warnings) == 1


async def test_circuit_breaker_disabled_when_zero():
    config = MemoryConfig(context_window=200, compression_threshold=0.5, compress_max_failures=0)
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(20):
        conv.messages.append(make_msg(token_count=25))

    for _ in range(10):
        result = await cm.check_and_compress(conv)
        assert result is True


# --- File content in compression recovery (9.2a) 压缩恢复附件含文件内容 ---


def test_record_file_read_with_content():
    cm = ContextManager(MemoryConfig(context_window=10000))
    cm.record_file_read("foo.py", "x" * 100_000)
    assert cm._read_files["foo.py"] is not None
    from mini_agent.llm.token_counter import count_tokens

    assert count_tokens(cm._read_files["foo.py"].removesuffix("\n... (truncated)")) <= 5000


def test_record_file_read_without_content_does_not_overwrite():
    cm = ContextManager(MemoryConfig(context_window=10000))
    cm.record_file_read("foo.py", "original content")
    cm.record_file_read("foo.py")
    assert cm._read_files["foo.py"] == "original content"


def test_record_file_read_with_new_content_overwrites():
    cm = ContextManager(MemoryConfig(context_window=10000))
    cm.record_file_read("foo.py", "old")
    cm.record_file_read("foo.py", "new")
    assert cm._read_files["foo.py"] == "new"


def test_inject_read_files_includes_content():
    cm = ContextManager(MemoryConfig(context_window=10000))
    cm.record_file_read("a.py", "print('hello')")
    cm.record_file_read("b.py", "import os")
    conv = Conversation()
    conv.messages.append(Message(role=Role.SYSTEM, content="summary", compressed=True))
    cm._inject_read_files(conv)
    text = conv.messages[0].content
    assert "--- a.py ---" in text
    assert "print('hello')" in text
    assert "--- b.py ---" in text
    assert "import os" in text


def test_inject_read_files_limits_to_5_files():
    cm = ContextManager(MemoryConfig(context_window=10000))
    for i in range(8):
        cm.record_file_read(f"f{i}.py", f"content{i}")
    conv = Conversation()
    conv.messages.append(Message(role=Role.SYSTEM, content="summary", compressed=True))
    cm._inject_read_files(conv)
    text = conv.messages[0].content
    # All 8 paths listed
    for i in range(8):
        assert f"f{i}.py" in text
    # Only last 5 file contents included
    assert "--- f3.py ---" in text
    assert "--- f7.py ---" in text
    assert "--- f2.py ---" not in text


def test_compact_boundary_stores_file_contents():
    cm = ContextManager(MemoryConfig(context_window=10000))
    cm.record_file_read("a.py", "aaa")
    cm.record_file_read("b.py", "bbb")
    conv = Conversation()
    conv.compact_boundary = {"summary": "s", "timestamp": "t"}
    # Simulate what check_and_compress does
    conv.compact_boundary["read_files"] = list(cm._read_files)
    file_contents = {p: c for p, c in list(cm._read_files.items())[-5:] if c is not None}
    if file_contents:
        conv.compact_boundary["file_contents"] = file_contents
    assert conv.compact_boundary["file_contents"] == {"a.py": "aaa", "b.py": "bbb"}


def test_adopt_boundary_restores_file_contents():
    cm = ContextManager(MemoryConfig(context_window=10000))
    conv = Conversation()
    conv.compact_boundary = {
        "summary": "s",
        "timestamp": "t",
        "read_files": ["a.py", "b.py"],
        "file_contents": {"a.py": "aaa"},
    }
    cm.adopt_boundary(conv)
    assert cm._read_files["a.py"] == "aaa"
    assert cm._read_files["b.py"] is None


def test_adopt_boundary_backward_compat_no_file_contents():
    cm = ContextManager(MemoryConfig(context_window=10000))
    conv = Conversation()
    conv.compact_boundary = {
        "summary": "s",
        "timestamp": "t",
        "read_files": ["a.py", "b.py"],
    }
    cm.adopt_boundary(conv)
    assert cm._read_files["a.py"] is None
    assert cm._read_files["b.py"] is None


# --- Last user request recovery 用户请求恢复 ---


async def test_compression_preserves_last_user_request():
    cm = ContextManager(MemoryConfig(context_window=2000, compression_threshold=0.5))
    cm.set_compressor(Compressor())

    conv = Conversation()
    for i in range(30):
        conv.messages.append(make_msg(role=Role.USER, content=f"task {i}", token_count=40))
        conv.messages.append(make_msg(role=Role.ASSISTANT, content=f"done {i}", token_count=40))

    compressed = await cm.check_and_compress(conv)
    assert compressed

    # The summary should contain the last user request
    summary_msg = None
    for msg in conv.messages:
        if msg.compressed and msg.role == Role.SYSTEM:
            summary_msg = msg
            break
    assert summary_msg is not None
    assert "[User's most recent request" in summary_msg.content
    assert "task 29" in summary_msg.content


async def test_last_user_request_in_boundary():
    cm = ContextManager(MemoryConfig(context_window=2000, compression_threshold=0.5))
    cm.set_compressor(Compressor())

    conv = Conversation()
    for i in range(30):
        conv.messages.append(make_msg(role=Role.USER, content=f"do thing {i}", token_count=40))
        conv.messages.append(make_msg(role=Role.ASSISTANT, content=f"ok {i}", token_count=40))

    await cm.check_and_compress(conv)
    assert conv.compact_boundary is not None
    assert conv.compact_boundary["last_user_request"] == "do thing 29"


def test_adopt_boundary_restores_last_user_request():
    cm = ContextManager(MemoryConfig(context_window=10000))
    conv = Conversation()
    conv.compact_boundary = {
        "summary": "s",
        "timestamp": "t",
        "read_files": [],
        "last_user_request": "fix the bug in auth.py",
    }
    cm.adopt_boundary(conv)
    assert cm._last_user_request == "fix the bug in auth.py"


def test_adopt_boundary_backward_compat_no_user_request():
    cm = ContextManager(MemoryConfig(context_window=10000))
    conv = Conversation()
    conv.compact_boundary = {"summary": "s", "timestamp": "t", "read_files": []}
    cm.adopt_boundary(conv)
    assert cm._last_user_request == ""


# --- LLM summarize config ---


def test_llm_summarize_config_default():
    """Default MemoryConfig enables LLM summarize."""
    cfg = MemoryConfig()
    assert cfg.llm_summarize is True


def test_llm_summarize_config_false():
    """llm_summarize=False uses extractive SummarizeOldest."""
    assert MemoryConfig(llm_summarize=False).llm_summarize is False
    compressor = Compressor()
    strategies = compressor._strategies
    assert any(isinstance(s, SummarizeOldest) for s in strategies)
    assert not any(isinstance(s, LLMSummarizeOldest) for s in strategies)
