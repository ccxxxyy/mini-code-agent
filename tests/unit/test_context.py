"""Tests for context manager and compression. 上下文管理器与压缩的测试。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.memory.compressor import (
    MIN_KEEP_MESSAGES,
    Compressor,
    DropToolResults,
    LLMSummarizeOldest,
    SlidingWindow,
    SummarizeOldest,
    _compute_keep_split,
    _extract_summary,
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
    # Tool result in the summarizable prefix (outside the keep window)
    # 工具结果位于可摘要前缀（保留窗口之外）
    conv.messages = [make_tool_msg(output="x" * 1000, token_count=3000)] + [
        make_msg(token_count=3000) for _ in range(10)
    ]
    await strategy.compress(conv, 10_000)
    assert conv.messages[0].compressed
    assert len(conv.messages[0].tool_result.output) < 1000


async def test_drop_tool_results_skips_short():
    strategy = DropToolResults()
    conv = Conversation()
    msg = make_tool_msg(output="short", token_count=5)
    conv.messages = [msg] + [make_msg(token_count=3000) for _ in range(10)]
    await strategy.compress(conv, 10_000)
    assert not msg.compressed


async def test_drop_tool_results_spares_keep_window():
    """Tool results the model is actively using (inside the keep window) are
    never truncated -- truncating them makes the model perceive broken tools
    and spiral into re-reads (real-terminal verified).
    保留窗口内（模型正在使用）的工具结果绝不截断——截了模型会以为工具坏了，
    陷入重读螺旋（真实终端实测）。"""
    strategy = DropToolResults()
    conv = Conversation()
    old_tool = make_tool_msg(output="a" * 1000, token_count=3000)
    recent_tool = make_tool_msg(output="b" * 1000, token_count=3000)
    conv.messages = (
        [old_tool]
        + [make_msg(token_count=3000) for _ in range(10)]
        + [make_msg(role=Role.ASSISTANT, content="reading", token_count=100), recent_tool]
    )
    await strategy.compress(conv, 10_000)
    assert old_tool.compressed  # prefix: truncated 前缀：截断
    assert not recent_tool.compressed  # keep window: untouched 保留窗口：不动
    assert recent_tool.tool_result.output == "b" * 1000


# --- SummarizeOldest ---


async def test_summarize_oldest():
    strategy = SummarizeOldest()
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=10))

    await strategy.compress(conv, 50_000)
    # 20 msgs × 10 tokens = 200 total < KEEP_RECENT_TOKENS (10K),
    # _compute_keep_split 全保留 → split=0 → 无可摘要内容。
    # 需要更高的 token_count 才能触发切分：
    conv2 = Conversation()
    for i in range(20):
        conv2.messages.append(make_msg(content=f"message {i}", token_count=3000))
    await strategy.compress(conv2, 50_000)
    assert conv2.messages[0].role == Role.SYSTEM
    assert conv2.messages[0].compressed
    assert "[Compressed" in conv2.messages[0].content
    # Kept messages should be token-driven, not fixed at 6
    # 保留的消息数由 token 驱动，不是固定 6 条
    kept = len(conv2.messages) - 1  # minus summary 减去摘要
    assert kept >= MIN_KEEP_MESSAGES


async def test_summarize_oldest_too_few():
    strategy = SummarizeOldest()
    conv = Conversation()
    conv.messages = [make_msg(token_count=10) for _ in range(MIN_KEEP_MESSAGES)]
    original_count = len(conv.messages)
    await strategy.compress(conv, 50_000)
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
    # Use 3000 tokens/msg so total (60K) exceeds KEEP_RECENT_TOKENS (10K)
    # 每条 3000 token，总计 60K 超过 KEEP_RECENT_TOKENS (10K) 触发切分
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=3000))

    await strategy.compress(conv, 50_000)
    assert conv.messages[0].role == Role.SYSTEM
    assert conv.messages[0].compressed
    assert "LLM summary" in conv.messages[0].content
    assert "Goal: fix bug" in conv.messages[0].content
    assert llm.call_count == 1
    kept = len(conv.messages) - 1  # minus summary 减去摘要
    assert kept >= MIN_KEEP_MESSAGES


async def test_llm_summarize_falls_back_on_error():
    llm = SummaryMockLLM(fail=True)
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=3000))

    await strategy.compress(conv, 50_000)
    # Fallback to extractive digest, chain not broken 回退到抽取式摘要，压缩链不中断
    assert conv.messages[0].role == Role.SYSTEM
    assert "[Compressed conversation history" in conv.messages[0].content
    assert "message 0" in conv.messages[0].content


async def test_llm_summarize_falls_back_on_empty():
    llm = SummaryMockLLM(summary="")
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=3000))

    await strategy.compress(conv, 50_000)
    assert "message 0" in conv.messages[0].content  # extractive fallback 回退到抽取式摘要


async def test_llm_summarize_too_few():
    llm = SummaryMockLLM()
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    conv.messages = [make_msg(token_count=10) for _ in range(MIN_KEEP_MESSAGES)]
    await strategy.compress(conv, 50_000)
    assert len(conv.messages) == MIN_KEEP_MESSAGES
    assert llm.call_count == 0  # no LLM call when nothing to summarize 无可摘要时不调 LLM


# --- Structured summary prompt (_extract_summary) 结构化摘要提取 ---


def test_extract_summary_strips_analysis():
    """Only the <summary> block content is kept. 只保留 <summary> 块内容。"""
    output = "<analysis>chain of thought here</analysis>\n<summary>1. Goal: fix bug</summary>"
    assert _extract_summary(output) == "1. Goal: fix bug"


def test_extract_summary_no_tags_returns_all():
    """Model ignored the format: full output is still usable. 无标签时回退完整输出。"""
    assert _extract_summary("  plain summary text  ") == "plain summary text"


def test_extract_summary_analysis_only_strips_scratchpad():
    """Truncated mid-analysis: scratchpad never leaks. analysis 中途截断时草稿不泄漏。"""
    assert _extract_summary("<analysis>partial thoughts") == ""
    assert _extract_summary("<analysis>done</analysis> leftover") == "leftover"


def test_extractive_digest_strips_recovery_attachment():
    """The recovery attachment baked onto a prior summary is stripped before
    re-digesting -- 17K chars of file dumps drown the planted conventions
    (real-terminal verified). The attachment is re-injected after every
    compression, so nothing is lost.
    旧摘要上的恢复附件在进 digest 前剥离——文件转储会淹没约定（真实终端实测）；
    附件每次压缩后重新注入，剥离无损失。"""
    from mini_agent.memory.compressor import _extractive_digest

    summary = Message(
        role=Role.SYSTEM,
        content=(
            "[Compressed conversation history]\n[user] 记住：约定 X 很重要\n\n"
            "[User's most recent request before compression:\n继续分析]\n\n"
            "[Files already read this session: a.py]\n\n"
            "[File contents from before compression:]\n--- a.py ---\n" + "code " * 2000
        ),
        compressed=True,
    )
    digest = _extractive_digest([summary])
    assert "约定 X 很重要" in digest  # 历史保留
    assert "code code" not in digest  # 附件剥离
    assert "[Files already read" not in digest


async def test_llm_summarize_retries_before_fallback():
    """A transient failure recovers on retry -- no extractive fallback.
    偶发失败重试后恢复，不落抽取式回退。"""

    class FlakyLLM(SummaryMockLLM):
        def __init__(self) -> None:
            super().__init__(summary="<summary>Recovered fine.</summary>")
            self.fails_left = 1

        async def stream(self, messages, tools=None, **kwargs):
            self.call_count += 1
            if self.fails_left > 0:
                self.fails_left -= 1
                raise ConnectionError("transient")
            yield StreamChunk(delta=self._summary)

    llm = FlakyLLM()
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"m{i}", token_count=3000))
    await strategy.compress(conv, 50_000)
    assert "Recovered fine." in conv.messages[0].content  # LLM 路径，非回退
    assert llm.call_count == 2  # 失败 1 次 + 重试成功 1 次


def test_extractive_digest_preserves_prior_summary():
    """A previous compression summary passes through the digest whole -- the
    300-char cap on it would compound detail loss across re-compressions.
    旧压缩摘要整条进入 digest，不受 300 字符截断——防二次压缩细节损失复利叠加。"""
    from mini_agent.memory.compressor import _extractive_digest

    summary = Message(
        role=Role.SYSTEM,
        content="[Compressed conversation history (LLM summary)]\n" + "detail " * 100,
        compressed=True,
    )
    normal = make_msg(content="x" * 500)
    digest = _extractive_digest([summary, normal])
    assert summary.content in digest  # 完整保留（> 300 字符）
    assert "x" * 301 not in digest  # 普通消息仍截断


def test_extract_summary_salvages_unclosed_block():
    """Truncated mid-summary (reasoning models burn the output budget): the
    partial summary is salvaged -- still beats the extractive digest.
    summary 中途截断（推理模型烧光输出预算）：抢救部分摘要，仍好于抽取式。"""
    out = "<analysis>brief</analysis>\n<summary>1. Goal: fix login bug\n2. Files: log"
    assert _extract_summary(out) == "1. Goal: fix login bug\n2. Files: log"


async def test_llm_summarize_uses_extracted_summary():
    """The injected message contains the <summary> content, not the analysis.
    注入对话的摘要只含 <summary> 内容，不含 analysis 草稿。"""
    llm = SummaryMockLLM(
        summary="<analysis>secret scratchpad</analysis><summary>Goal: refactor auth.</summary>"
    )
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=3000))

    await strategy.compress(conv, 50_000)
    assert "Goal: refactor auth." in conv.messages[0].content
    assert "secret scratchpad" not in conv.messages[0].content


async def test_llm_summarize_empty_summary_block_falls_back():
    """Empty <summary></summary> triggers extractive fallback. 空 summary 块触发抽取式回退。"""
    llm = SummaryMockLLM(summary="<analysis>thoughts</analysis><summary>  </summary>")
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"message {i}", token_count=3000))

    await strategy.compress(conv, 50_000)
    assert "message 0" in conv.messages[0].content  # extractive fallback
    assert "thoughts" not in conv.messages[0].content


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


async def test_sliding_window_keeps_summary_anchor():
    """The compression summary at the head must survive tail-based truncation
    -- it carries the entire compressed history (full-pipeline verified:
    SlidingWindow deleted exactly the summary the LLM call just produced).
    头部的压缩摘要必须在尾部截断中存活——它承载全部压缩历史。"""
    strategy = SlidingWindow()
    conv = Conversation()
    summary = Message(role=Role.SYSTEM, content="[Compressed] plants here", compressed=True)
    summary.token_count = 50
    conv.messages = [summary] + [make_msg(content=f"m{i}", token_count=200) for i in range(10)]
    # budget 500: fits only ~2 tail messages -- summary would be dropped without the anchor
    await strategy.compress(conv, 500)
    assert conv.messages[0] is summary  # 摘要锚点存活且在最前
    assert any(m.role == Role.USER for m in conv.messages[1:]) or len(conv.messages) > 1


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
    # Use 3000 tokens/msg so total exceeds KEEP_RECENT_TOKENS (10K),
    # forcing a split that lands near the tool pair.
    # 每条 3000 token 使总量超过 10K，迫使切分点落在工具对附近。
    conv.messages = (
        [make_msg(content=f"m{i}", token_count=3000) for i in range(12)]
        + [
            make_call_msg(token_count=3000),
            make_tool_msg(token_count=3000),
            make_tool_msg(token_count=3000),
        ]
        + [make_msg(content=f"t{i}", token_count=3000) for i in range(5)]
    )
    await strategy.compress(conv, 50_000)

    assert conv.messages[0].role == Role.SYSTEM  # summary 摘要
    # Tool pair must not be split: if a TOOL result is kept, its
    # preceding ASSISTANT tool_calls must also be kept.
    # 工具对不能被拆分：TOOL result 保留时其前置 ASSISTANT tool_calls 也必须保留。
    for idx, msg in enumerate(conv.messages):
        if msg.role == Role.TOOL:
            assert idx > 0
            assert any(
                conv.messages[j].role == Role.ASSISTANT and conv.messages[j].tool_calls
                for j in range(idx)
            )


async def test_summarize_oldest_alignment_reaches_start():
    # Everything before the naive split is one giant tool pair: nothing
    # summarizable remains, so compression is a no-op.
    # 切分点之前全是一个工具对：没有可摘要的内容，压缩应为空操作。
    strategy = SummarizeOldest()
    conv = Conversation()
    # Use enough msgs (>MIN_KEEP_MESSAGES) but make them all a tool pair
    # 消息数超过 MIN_KEEP_MESSAGES 但全是工具对
    conv.messages = [make_call_msg(token_count=3000)] + [
        make_tool_msg(token_count=3000) for _ in range(7)
    ]
    await strategy.compress(conv, 50_000)
    assert len(conv.messages) == 8  # unchanged 未变
    assert not any(m.compressed for m in conv.messages)


async def test_llm_summarize_aligns_tool_pair():
    llm = SummaryMockLLM()
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    conv.messages = (
        [make_msg(content=f"m{i}", token_count=3000) for i in range(12)]
        + [
            make_call_msg(token_count=3000),
            make_tool_msg(token_count=3000),
            make_tool_msg(token_count=3000),
        ]
        + [make_msg(content=f"t{i}", token_count=3000) for i in range(5)]
    )
    await strategy.compress(conv, 50_000)

    # Tool pair must be intact 工具对必须完整
    for idx, msg in enumerate(conv.messages):
        if msg.role == Role.TOOL:
            assert any(
                conv.messages[j].role == Role.ASSISTANT and conv.messages[j].tool_calls
                for j in range(idx)
            )


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
    config = MemoryConfig(
        context_window=200,
        compression_threshold=0.5,
        compress_max_failures=3,
        hard_compression_threshold=100.0,
    )
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
    config = MemoryConfig(
        context_window=200,
        compression_threshold=0.5,
        compress_max_failures=3,
        hard_compression_threshold=100.0,
    )
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    # Short content: with the summary anchor (P71) the digest survives
    # SlidingWindow, so at this degenerate 200-token window a 100-char-per-msg
    # digest would outweigh the savings and read as "ineffective".
    # 短内容：摘要锚点（P71）让 digest 在 SlidingWindow 后存活，200 token 的
    # 极端窗口下 100 字符/条的 digest 会抵消节省量、被判"无效"。
    for _ in range(20):
        conv.messages.append(make_msg(content="hi", token_count=25))

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

    config = MemoryConfig(
        context_window=200,
        compression_threshold=0.5,
        compress_max_failures=3,
        hard_compression_threshold=100.0,
    )
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


# --- Hard compression threshold bypasses breaker 硬阈值绕过熔断器 ---


async def test_hard_threshold_bypasses_breaker():
    # context_window=1000, 6×100=600 tokens → usage_ratio=0.6 (above soft 0.5, below hard 0.9)
    config = MemoryConfig(
        context_window=1000,
        compression_threshold=0.5,
        hard_compression_threshold=0.9,
        compress_max_failures=3,
    )
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(6):
        conv.messages.append(make_msg(token_count=100))

    # Trip the breaker with 3 ineffective attempts
    for _ in range(3):
        await cm.check_and_compress(conv)
    assert cm._compress_failures == 3

    # Soft threshold: breaker blocks
    assert await cm.check_and_compress(conv) is False

    # Push above hard threshold (6×100 + 4×100 = 1000 → ratio=1.0 >= 0.9)
    for _ in range(4):
        conv.messages.append(make_msg(token_count=100))

    # Hard threshold bypasses breaker
    result = await cm.check_and_compress(conv)
    assert result is True


async def test_soft_threshold_still_blocked_by_breaker():
    # 6×100=600 tokens, context_window=1000 → usage_ratio=0.6 (above soft 0.5, below hard 0.9)
    config = MemoryConfig(
        context_window=1000,
        compression_threshold=0.5,
        hard_compression_threshold=0.9,
        compress_max_failures=3,
    )
    cm = ContextManager(config)
    cm.set_compressor(NoOpCompressor())

    conv = Conversation()
    for _ in range(6):
        conv.messages.append(make_msg(token_count=100))

    for _ in range(3):
        await cm.check_and_compress(conv)
    assert cm._compress_failures == 3

    cm.update_total(conv)
    assert cm.usage_ratio < 0.9
    assert await cm.check_and_compress(conv) is False


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


def test_inject_read_files_budget_scales_with_window():
    """Recovery file contents scale with the window: at a small window the
    absolute 5x5000-token attachment would exceed the entire window (observed
    at window=20K: a 54K-char summary message pinned context at 112%).
    恢复附件预算随窗口缩放：小窗口下绝对值附件会超过整个窗口。"""
    big = "x" * 40_000  # ~10K tokens before truncation
    small_cm = ContextManager(MemoryConfig(context_window=8000))
    large_cm = ContextManager(MemoryConfig(context_window=128_000))
    for cm in (small_cm, large_cm):
        cm.record_file_read("a.py", big)
        cm.record_file_read("b.py", big)
    small_conv = Conversation()
    small_conv.messages.append(Message(role=Role.SYSTEM, content="s", compressed=True))
    large_conv = Conversation()
    large_conv.messages.append(Message(role=Role.SYSTEM, content="s", compressed=True))
    small_cm._inject_read_files(small_conv)
    large_cm._inject_read_files(large_conv)
    small_len = len(small_conv.messages[0].content)
    large_len = len(large_conv.messages[0].content)
    # 8K 窗口预算 2000 tokens vs 128K 窗口 25000 tokens——附件显著更小
    assert small_len < large_len / 2
    assert "--- a.py ---" in small_conv.messages[0].content  # 内容仍存在，只是截短


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


# --- Token-driven keep window (_compute_keep_split) token 驱动保留窗口 ---


def test_keep_split_short_messages_keeps_all():
    """20 messages × 10 tokens = 200 total < KEEP_RECENT_TOKENS (10K),
    so all messages are kept (split=0). Old fixed-6 would have only kept 6.
    20 条 × 10 token = 200 < 10K，全保留。旧固定 6 条只保留 6 条。"""
    msgs = [make_msg(token_count=10) for _ in range(20)]
    split = _compute_keep_split(msgs, 200_000)
    # keep all — not enough tokens to warrant summarization
    # 全保留——token 不足不值得摘要
    assert split == 0


def test_keep_split_long_messages_keeps_fewer():
    """Messages at 8K tokens each — should keep 5, hitting both
    KEEP_RECENT_TOKENS (10K) and MIN_KEEP_MESSAGES (5).
    每条 8K token，保留 5 条（双条件满足后停止）。"""
    msgs = [make_msg(token_count=8000) for _ in range(20)]
    split = _compute_keep_split(msgs, 200_000)
    kept = len(msgs) - split
    assert kept == MIN_KEEP_MESSAGES  # 5 × 8K = 40K = KEEP_MAX_TOKENS 双条件满足停止
    assert split > 0


def test_keep_split_hits_hard_cap():
    """Messages so large that KEEP_MAX_TOKENS (40K) is hit before
    MIN_KEEP_MESSAGES can be reached.
    单条太大，硬顶 40K 在消息数达到最低要求前就命中。"""
    msgs = [make_msg(token_count=15000) for _ in range(10)]
    split = _compute_keep_split(msgs, 200_000)
    kept = len(msgs) - split
    # 15K per msg: 2 msgs = 30K (under 40K cap), 3 msgs = 45K (over cap)
    # 每条 15K：2 条 = 30K（未超 40K），3 条 = 45K（超了）
    assert kept == 2
    assert split == 8


def test_keep_split_minimum_messages():
    """Exactly MIN_KEEP_MESSAGES messages — nothing to summarize.
    恰好 MIN_KEEP_MESSAGES 条——无可摘要内容。"""
    msgs = [make_msg(token_count=100) for _ in range(MIN_KEEP_MESSAGES)]
    split = _compute_keep_split(msgs, 200_000)
    assert split == 0


def test_keep_split_fewer_than_minimum():
    """Fewer than MIN_KEEP_MESSAGES messages — nothing to summarize.
    少于 MIN_KEEP_MESSAGES 条——无可摘要内容。"""
    msgs = [make_msg(token_count=100) for _ in range(3)]
    split = _compute_keep_split(msgs, 200_000)
    assert split == 0


def test_keep_split_meets_both_thresholds():
    """Stop as soon as both count >= MIN_KEEP_MESSAGES AND
    tokens >= KEEP_RECENT_TOKENS are satisfied.
    双条件同时满足时立即停止。"""
    # 2500 tokens/msg × 5 msgs = 12500 >= 10K, count=5 >= 5 → stop
    # 2500 × 5 = 12500 ≥ 10K，条数 5 ≥ 5 → 停止
    msgs = [make_msg(token_count=2500) for _ in range(15)]
    split = _compute_keep_split(msgs, 200_000)
    kept = len(msgs) - split
    assert kept == MIN_KEEP_MESSAGES
    assert split == 10


def test_keep_split_scales_to_small_target():
    """target=7500 (window=10K × 75%): floor scales to 3750, cap to 7500 --
    summarization stays viable instead of always overshooting the target.
    小窗口下下限缩放为 target//2、硬顶缩放为 target，摘要级不再必然超标。"""
    msgs = [make_msg(token_count=1000) for _ in range(20)]
    split = _compute_keep_split(msgs, 7500)
    kept = len(msgs) - split
    assert kept == MIN_KEEP_MESSAGES  # 5 × 1000 = 5000 >= 3750 floor, count met
    assert kept * 1000 <= 7500  # kept tokens fit within the target 保留量在目标内


def test_keep_split_never_empties_tail():
    """A single message bigger than the scaled cap: still keep one message --
    summarizing away the entire tail would erase the task in progress.
    单条超过缩放后的硬顶时也至少保留 1 条，不能把尾部全摘要掉。"""
    msgs = [make_msg(token_count=3000) for _ in range(10)]
    split = _compute_keep_split(msgs, 100)
    assert split == len(msgs) - 1  # keeps exactly the newest message


def test_keep_split_large_target_unchanged():
    """With a large target the absolute constants govern -- behavior identical
    to the pre-scaling implementation.
    大目标下仍由绝对常量决定，与缩放前行为一致。"""
    msgs = [make_msg(token_count=8000) for _ in range(20)]
    assert _compute_keep_split(msgs, 200_000) == _compute_keep_split(msgs, 96_000)


async def test_llm_summarize_small_target_fits_budget():
    """End-to-end at a small target: kept tokens stay within the target so the
    cascade can actually reach it (window=10K pathology fix).
    小目标端到端：保留量在目标内，级联真正可达标。"""
    llm = SummaryMockLLM(summary="<summary>Goal: small window.</summary>")
    strategy = LLMSummarizeOldest(llm)
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"m{i}", token_count=1000))

    await strategy.compress(conv, 7500)
    assert "Goal: small window." in conv.messages[0].content
    kept_tokens = sum(m.token_count for m in conv.messages[1:])
    assert kept_tokens <= 7500


async def test_summarize_oldest_keeps_all_when_tokens_low():
    """When all messages combined are below KEEP_RECENT_TOKENS,
    SummarizeOldest should be a no-op (nothing to summarize).
    所有消息总 token 低于 KEEP_RECENT_TOKENS 时，SummarizeOldest 应空操作。"""
    strategy = SummarizeOldest()
    conv = Conversation()
    for i in range(20):
        conv.messages.append(make_msg(content=f"m{i}", token_count=10))
    await strategy.compress(conv, 50_000)
    assert len(conv.messages) == 20
    assert not any(m.compressed for m in conv.messages)
