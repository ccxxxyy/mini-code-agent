"""Tests for context manager and compression. 上下文管理器与压缩的测试。"""

import pytest

from mini_agent.memory.compressor import Compressor, DropToolResults, SlidingWindow, SummarizeOldest
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role, ToolResult

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
