"""Tests for tool result spill-to-disk and post-compression recovery.
工具结果溢写与压缩后恢复的测试。"""

from pathlib import Path

import pytest

from mini_agent.memory.context import ContextManager
from mini_agent.memory.tool_result_cache import ToolResultCache
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role, ToolResult

pytestmark = pytest.mark.asyncio


def make_result(
    output: str, name: str = "read_file", is_error: bool = False, call_id: str = "c1"
) -> ToolResult:
    return ToolResult(call_id=call_id, name=name, output=output, is_error=is_error)


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


# --- Aggregate budget (spill_batch) + supporting mechanisms ---
# 聚合预算与三个配套机制


async def test_preview_chars_is_2000(tmp_path: Path):
    from mini_agent.memory.tool_result_cache import PREVIEW_CHARS

    assert PREVIEW_CHARS == 2_000
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000)
    spilled = cache.maybe_spill(make_result("p" * 60_000))
    assert spilled.output.startswith("p" * 2_000)
    assert not spilled.output.startswith("p" * 2_001)


async def test_force_spill_bypasses_threshold(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000)
    r = make_result("f" * 10_000)
    assert cache.maybe_spill(r) is r  # under threshold, normal path no-op
    spilled = cache.maybe_spill(r, force=True)
    assert spilled is not r
    assert "output too large for conversation" in spilled.output


async def test_force_spill_exempts_small_results(tmp_path: Path):
    # Results no longer than the preview: spilling cannot reclaim space
    # 不长于预览的结果——溢写换不回空间
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000)
    r = make_result("s" * 1_500)
    assert cache.maybe_spill(r, force=True) is r
    assert not (tmp_path / "cache").exists()


async def test_is_spill_readback(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache = ToolResultCache(cache_dir, threshold_chars=100)
    inside = str(cache_dir / "result_abc.txt")
    outside = str(tmp_path / "other.txt")
    assert cache.is_spill_readback("read_file", {"file_path": inside})
    assert not cache.is_spill_readback("read_file", {"file_path": outside})
    assert not cache.is_spill_readback("bash", {"command": f"cat {inside}"})
    assert not cache.is_spill_readback("read_file", {})
    assert not cache.is_spill_readback("read_file", {"file_path": 42})


async def test_is_spill_readback_sibling_dir_not_misjudged(tmp_path: Path):
    """A sibling dir sharing the cache_dir name prefix must NOT match.
    与 cache_dir 同名前缀的兄弟目录不能被误判为读回。

    Old code used str.startswith(abs(cache_dir)); ".../cache_evil/x" starts
    with ".../cache" as a string, so it was wrongly exempted from spilling.
    Path-component containment fixes this.
    旧代码用 str.startswith，".../cache_evil/x" 字符串上以 ".../cache" 开头
    被误豁免；按路径成分包含判断修复此问题。"""
    cache_dir = tmp_path / "cache"
    cache = ToolResultCache(cache_dir, threshold_chars=100)

    sibling = str(tmp_path / "cache_evil" / "x.txt")
    assert not cache.is_spill_readback("read_file", {"file_path": sibling})

    # the real cache dir still matches (regression guard) 真缓存目录仍命中
    inside = str(cache_dir / "result_abc.txt")
    assert cache.is_spill_readback("read_file", {"file_path": inside})


async def test_spill_batch_under_budget_unchanged(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=10_000)
    results = [make_result("a" * 4_000, call_id="c1"), make_result("b" * 4_000, call_id="c2")]
    out = cache.spill_batch(results)
    assert out == results
    assert not (tmp_path / "cache").exists()


async def test_spill_batch_spills_largest_first(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=10_000)
    results = [
        make_result("small " * 100, call_id="c1"),  # 600 chars
        make_result("L" * 30_000, call_id="c2"),  # largest
        make_result("m" * 3_000, call_id="c3"),
    ]
    out = cache.spill_batch(results)
    # Order preserved; only the largest spilled (enough to fit budget)
    # 顺序不变；只溢写最大的一条即回到预算内
    assert out[0] is results[0]
    assert "output too large for conversation" in out[1].output
    assert "spilled_path" in out[1].metadata
    assert out[2] is results[2]


async def test_spill_batch_respects_exempt_ids(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=10_000)
    results = [
        make_result("L" * 30_000, call_id="readback"),
        make_result("m" * 8_000, call_id="c2"),
    ]
    out = cache.spill_batch(results, exempt_ids={"readback"})
    assert out[0] is results[0]  # exempt untouched 豁免项不动
    assert "output too large for conversation" in out[1].output


async def test_spill_batch_skips_errors_and_already_spilled(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=1_000)
    err = make_result("e" * 20_000, is_error=True, call_id="c1")
    already = cache.maybe_spill(make_result("z" * 60_000, call_id="c2"))
    assert "spilled_path" in already.metadata
    out = cache.spill_batch([err, already])
    assert out[0] is err
    assert out[1] is already


async def test_spill_batch_accumulates_across_iterations(tmp_path: Path):
    # Batch alone fits, but the turn's cumulative total pushes it over
    # 单批不超，但本轮累计后超预算
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=10_000)
    results = [make_result("a" * 6_000, call_id="c1")]
    assert cache.spill_batch(results) == results  # no accumulation: fits
    out = cache.spill_batch(results, already_used=8_000)
    assert "output too large for conversation" in out[0].output


async def test_spill_batch_aggregate_zero_disables(tmp_path: Path):
    cache = ToolResultCache(tmp_path / "cache", threshold_chars=50_000, aggregate_chars=0)
    results = [make_result("a" * 500_000, call_id="c1")]
    assert cache.spill_batch(results) == results


async def test_memory_config_default():
    assert MemoryConfig().aggregate_spill_chars == 200_000


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
    from tests.mocks import (
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


async def test_agent_loop_aggregate_budget_spills_parallel_results(tmp_path: Path):
    # Each result under the single-result threshold, together over the
    # aggregate budget -> largest force-spilled at OBSERVE
    # 每条都不超单条阈值，合计超聚合预算 -> OBSERVE 阶段强制溢写最大的
    import json as _json

    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.events.bus import EventBus
    from mini_agent.llm.base import StreamChunk, ToolCallDelta
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext, ToolRegistry
    from mini_agent.tools.builtin import ReadFileTool
    from tests.mocks import MockLLM, text_response

    work = tmp_path / "work"
    work.mkdir()
    big = work / "big.txt"
    big.write_text("B" * 30_000, encoding="utf-8")
    small = work / "small.txt"
    small.write_text("s" * 600, encoding="utf-8")

    multi_call = [
        StreamChunk(
            tool_call_deltas=[
                ToolCallDelta(
                    index=i,
                    id=f"call_{i}",
                    name="read_file",
                    arguments_delta=_json.dumps({"file_path": str(p)}),
                )
                for i, p in enumerate([big, small])
            ]
        ),
        StreamChunk(finish_reason="tool_calls"),
    ]
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    ctx = ToolContext(
        working_dir=work, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    loop = AgentLoop(
        llm=MockLLM([multi_call, text_response("done")]),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=ctx,
    )
    loop.result_cache = ToolResultCache(
        tmp_path / "cache", threshold_chars=50_000, aggregate_chars=10_000
    )

    conv = Conversation()
    await loop.run(conv)

    tool_msgs = [m for m in conv.messages if m.tool_result]
    assert len(tool_msgs) == 2
    by_size = sorted(tool_msgs, key=lambda m: m.tool_result.metadata.get("full_chars", 0))
    assert "output too large for conversation" in by_size[-1].tool_result.output
    assert "spilled_path" in by_size[-1].tool_result.metadata
    assert "output too large" not in by_size[0].tool_result.output


async def test_agent_loop_spill_readback_not_respilled(tmp_path: Path):
    # Reading back a spill file must not spill again (infinite loop guard)
    # 读回溢写文件不得再次溢写（防死循环）
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext, ToolRegistry
    from mini_agent.tools.builtin import ReadFileTool
    from tests.mocks import MockLLM, text_response, tool_call_response

    work = tmp_path / "work"
    work.mkdir()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    spill_file = cache_dir / "result_abc.txt"
    spill_file.write_text("R" * 5_000, encoding="utf-8")

    registry = ToolRegistry()
    registry.register(ReadFileTool())
    ctx = ToolContext(
        working_dir=work, session=Session(), event_bus=EventBus(), config=AgentConfig()
    )
    loop = AgentLoop(
        llm=MockLLM(
            [tool_call_response("read_file", {"file_path": str(spill_file)}), text_response("ok")]
        ),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=ctx,
    )
    # Threshold tiny + aggregate tiny: both layers would spill without the exemption
    # 阈值和聚合预算都设很小——没有豁免的话两层都会溢写
    loop.result_cache = ToolResultCache(cache_dir, threshold_chars=100, aggregate_chars=1_000)

    conv = Conversation()
    await loop.run(conv)

    tool_msgs = [m for m in conv.messages if m.tool_result]
    assert len(tool_msgs) == 1
    assert "output too large" not in tool_msgs[0].tool_result.output
    assert "spilled_path" not in tool_msgs[0].tool_result.metadata
