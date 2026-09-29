"""Tests for runtime metrics: histograms, loop-lag probe, EventBus collector.
运行时指标测试：直方图、loop lag 探针、EventBus 采集器。
"""

from __future__ import annotations

import asyncio
import time

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.metrics import Histogram, LoopLagProbe, MetricsCollector
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    ContextSummaryDoneEvent,
    LLMResponseEvent,
    PermissionCheckEvent,
    SubAgentCompleteEvent,
    SubAgentSpawnEvent,
    ToolCallEndEvent,
    TurnCompleteEvent,
)
from mini_agent.models.message import Conversation
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool
from tests.mocks import MockLLM, text_response, tool_call_response

# --- Histogram 直方图 ---


def test_percentile_is_nearest_rank_not_interpolated():
    """p95 of 1..20 must be 19 -- an actually observed sample, not 19.05.
    1..20 的 p95 必须是 19（真实观测值），不能插值出 19.05。"""
    h = Histogram("t")
    for v in range(1, 21):
        h.record(float(v))
    assert h.percentile(50) == 10.0
    assert h.percentile(95) == 19.0
    assert h.percentile(99) == 20.0
    # Every percentile must be a value that was actually recorded
    # 每个百分位都必须是真实记录过的值
    for p in (50, 95, 99):
        assert h.percentile(p) in {float(v) for v in range(1, 21)}


def test_percentile_single_sample():
    h = Histogram("t")
    h.record(5.0)
    assert h.percentile(50) == 5.0
    assert h.percentile(99) == 5.0


def test_empty_histogram_returns_none_not_zero():
    """Zero would read as 'instant'; None reads as 'no data'.
    返回 0 会被读成"瞬时完成"，None 才表示"无数据"。"""
    h = Histogram("t")
    assert h.percentile(50) is None
    snap = h.snapshot()
    assert snap["count"] == 0
    assert snap["p50"] is None
    # min/max/mean are omitted entirely when there are no samples
    # 无样本时完全不输出 min/max/mean
    assert "min" not in snap and "max" not in snap and "mean" not in snap


def test_count_and_extremes_stay_exact_after_window_eviction():
    """Percentiles use a sliding window, but count/min/max must cover ALL
    samples -- otherwise an evicted outlier silently disappears.
    百分位用滑动窗口，但 count/min/max 必须覆盖全部样本——否则被淘汰的
    异常值会悄悄消失。"""
    h = Histogram("t", window=3)
    for v in (100.0, 1.0, 2.0, 3.0, 4.0):
        h.record(v)
    snap = h.snapshot()
    assert snap["count"] == 5
    assert snap["window"] == 3
    assert snap["min"] == 1.0
    assert snap["max"] == 100.0  # evicted from the window, still reported
    assert h.count == 5


def test_snapshot_exposes_window_size_so_percentiles_are_interpretable():
    h = Histogram("t", window=2)
    for v in (1.0, 2.0, 3.0):
        h.record(v)
    assert h.snapshot()["window"] == 2


# --- LoopLagProbe 事件循环阻塞探针 ---


async def test_probe_detects_blocking_call():
    """A synchronous sleep on the loop must show up as lag. Deterministic:
    the blocking duration is far above any scheduling noise.
    在事件循环上同步 sleep 必须被记为 lag。确定性：阻塞时长远高于调度噪声。"""
    probe = LoopLagProbe(interval=0.01)
    probe.start()
    await asyncio.sleep(0.05)
    idle_max = probe.histogram.snapshot()["max"]

    time.sleep(0.3)  # block the event loop on purpose 故意阻塞事件循环
    await asyncio.sleep(0.02)  # let the probe wake and record 让探针醒来记录
    blocked_max = probe.histogram.snapshot()["max"]
    await probe.stop()

    assert idle_max < 100, f"idle loop should not lag, got {idle_max}ms"
    assert blocked_max > 200, f"should catch the ~300ms block, got {blocked_max}ms"


async def test_probe_start_is_idempotent():
    probe = LoopLagProbe(interval=0.01)
    probe.start()
    first = probe._task
    probe.start()
    assert probe._task is first
    await probe.stop()


async def test_probe_stop_without_start_is_noop():
    probe = LoopLagProbe()
    await probe.stop()  # must not raise 不得抛异常


# --- MetricsCollector 采集器 ---


async def test_collector_records_ttft_and_tokens():
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(
        LLMResponseEvent(
            prompt_tokens=100,
            completion_tokens=20,
            cache_read_input_tokens=5,
            ttft_ms=250.0,
            stream_duration_ms=1200.0,
        )
    )
    assert mc.llm_calls == 1
    assert mc.prompt_tokens == 100
    assert mc.completion_tokens == 20
    assert mc.cache_read_tokens == 5
    assert mc.ttft.count == 1
    assert mc.ttft.percentile(50) == 250.0
    assert mc.stream_duration.percentile(50) == 1200.0


async def test_zero_ttft_is_not_recorded():
    """ttft_ms == 0 means the stream produced no payload (cancelled / error).
    Recording it would drag the percentile toward zero and make the metric lie.
    ttft_ms == 0 表示流未产出载荷（取消/出错），记录它会把百分位拉向 0。"""
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(LLMResponseEvent(ttft_ms=400.0, stream_duration_ms=900.0))
    await bus.emit(LLMResponseEvent(ttft_ms=0, stream_duration_ms=0))
    assert mc.llm_calls == 2, "the call itself still counts 调用本身仍计数"
    assert mc.ttft.count == 1, "but the zero sample must not pollute latency"
    assert mc.ttft.percentile(50) == 400.0


async def test_collector_tool_success_rate_and_per_tool_split():
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(ToolCallEndEvent(tool_name="read_file", duration_ms=10.0))
    await bus.emit(ToolCallEndEvent(tool_name="read_file", duration_ms=30.0))
    await bus.emit(ToolCallEndEvent(tool_name="bash", duration_ms=500.0, is_error=True))
    assert mc.tool_calls == 3
    assert mc.tool_errors == 1
    assert mc.tool_success_rate == 2 / 3
    # Per-tool split keeps a slow tool from hiding behind a fast one
    # 按工具分桶，避免慢工具被快工具掩盖
    assert mc.per_tool["bash"].percentile(50) == 500.0
    assert mc.per_tool["read_file"].count == 2


async def test_tool_success_rate_is_none_with_no_calls():
    mc = MetricsCollector(probe_loop_lag=False)
    assert mc.tool_success_rate is None
    assert mc.snapshot()["quality"]["tool_success_rate"] is None


async def test_collector_counts_turns_permissions_compression_subagents():
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(TurnCompleteEvent(iteration_count=4))
    await bus.emit(TurnCompleteEvent(iteration_count=6))
    await bus.emit(PermissionCheckEvent(decision="granted", reason="rule"))
    await bus.emit(PermissionCheckEvent(decision="denied", reason="user_confirm"))
    await bus.emit(PermissionCheckEvent(decision="denied", reason="user_confirm"))
    await bus.emit(ContextSummaryDoneEvent(duration_ms=48000.0))
    await bus.emit(SubAgentSpawnEvent(agent_id="a1"))
    await bus.emit(SubAgentCompleteEvent(agent_id="a1", success=False))

    assert mc.turns == 2
    assert mc.iterations.percentile(50) == 4.0
    assert mc.permission_decisions == {"granted": 1, "denied": 2}
    # `reason` separates policy blocks from user refusals -- only the latter
    # are candidate false positives. reason 区分策略拦截与用户拒绝。
    assert mc.permission_reasons["user_confirm"] == 2
    assert mc.compressions == 1
    assert mc.compression_duration.percentile(50) == 48000.0
    assert mc.subagents_spawned == 1
    assert mc.subagents_failed == 1


async def test_detach_stops_collecting():
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(ToolCallEndEvent(tool_name="x", duration_ms=1.0))
    mc.detach(bus)
    await bus.emit(ToolCallEndEvent(tool_name="x", duration_ms=1.0))
    assert mc.tool_calls == 1


async def test_snapshot_is_json_serializable_and_has_expected_sections():
    import json

    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await bus.emit(LLMResponseEvent(ttft_ms=120.0, stream_duration_ms=800.0))
    await bus.emit(ToolCallEndEvent(tool_name="grep", duration_ms=42.0))
    await bus.emit(TurnCompleteEvent(iteration_count=3))
    snap = mc.snapshot()

    assert set(snap) >= {"latency", "counters", "tokens", "quality", "permissions"}
    assert snap["latency"]["llm_ttft"]["p50"] == 120.0
    assert snap["latency"]["per_tool"]["grep"]["p50"] == 42.0
    assert snap["counters"]["llm_calls"] == 1
    assert snap["quality"]["turn_iterations"]["p50"] == 3.0
    # Must survive a round-trip into the benchmark result JSON
    # 必须能进评测结果 JSON
    json.dumps(snap)


async def test_snapshot_omits_loop_lag_when_probe_disabled():
    mc = MetricsCollector(probe_loop_lag=False)
    assert "event_loop_lag" not in mc.snapshot()
    mc2 = MetricsCollector(probe_loop_lag=True)
    assert "event_loop_lag" in mc2.snapshot()


async def test_concurrent_events_are_not_lost():
    """Concurrent SubAgent events hit the same counters; the lock must keep
    every increment. 并发子 Agent 事件打同一批计数器，锁必须保住每次自增。"""
    bus = EventBus()
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(bus)
    await asyncio.gather(
        *(bus.emit(ToolCallEndEvent(tool_name="t", duration_ms=1.0)) for _ in range(50))
    )
    assert mc.tool_calls == 50
    assert mc.tool_duration.count == 50


# --- TTFT instrumentation in the agent loop Agent 循环里的 TTFT 埋点 ---


def _loop_with(llm, tool_context):
    return AgentLoop(
        llm=llm,
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=tool_context,
    )


async def _capture_response_event(loop) -> LLMResponseEvent:
    captured: list[LLMResponseEvent] = []

    async def grab(event: LLMResponseEvent) -> None:
        captured.append(event)

    loop._event_bus.on(LLMResponseEvent, grab)
    await loop.run(Conversation())
    assert captured, "no LLMResponseEvent emitted"
    return captured[0]


async def test_ttft_measures_delay_before_first_payload(tool_context):
    """A provider that stalls 50ms before its first chunk must report a
    TTFT of at least 50ms. 首 chunk 前挂起 50ms 的 Provider，TTFT 必须 >= 50ms。"""
    loop = _loop_with(MockLLM(delay=0.05, text="hi"), tool_context)
    event = await _capture_response_event(loop)
    assert event.ttft_ms >= 50.0, f"expected >=50ms, got {event.ttft_ms}"


async def test_ttft_never_exceeds_stream_duration(tool_context):
    """Invariant: first token cannot arrive after the stream ended.
    不变量：首 token 不可能晚于整个流结束。"""
    loop = _loop_with(MockLLM(delay=0.02, text="hello"), tool_context)
    event = await _capture_response_event(loop)
    assert 0 < event.ttft_ms <= event.stream_duration_ms


async def test_payloadless_stream_reports_zero_ttft(tool_context):
    """A stream carrying only finish_reason has no token, so TTFT must stay
    0 rather than timing the empty frame -- this is what makes the metric
    time-to-first-TOKEN instead of time-to-first-HTTP-frame.
    只带 finish_reason 的流没有 token，TTFT 必须保持 0 而不是给空帧计时——
    这正是该指标衡量"首 token"而非"首个 HTTP 帧"的关键。"""
    loop = _loop_with(
        MockLLM([[StreamChunk(), StreamChunk(finish_reason="stop")]], delay=0.02),
        tool_context,
    )
    event = await _capture_response_event(loop)
    assert event.ttft_ms == 0, f"empty frames must not stop the clock, got {event.ttft_ms}"
    assert event.stream_duration_ms > 0, "the stream still took wall time"


async def test_tool_call_deltas_count_as_first_payload(tool_context):
    """A tool-calling turn emits no text, but the tool_call delta IS the
    first token -- TTFT must be measured, not left at 0.
    纯工具调用轮次没有正文，但 tool_call 增量就是首 token——TTFT 必须被测到。"""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    loop = AgentLoop(
        llm=MockLLM(
            [
                tool_call_response("read_file", {"file_path": "nope.txt"}),
                text_response("done"),
            ],
            delay=0.02,
        ),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=tool_context,
    )
    event = await _capture_response_event(loop)
    assert event.ttft_ms > 0, "tool_call_deltas must stop the TTFT clock"


async def test_collector_consumes_loop_ttft_end_to_end(tool_context):
    """Full pipeline: agent loop emits -> collector aggregates -> snapshot.
    全管道：Agent 循环发射 -> 采集器聚合 -> 快照。"""
    loop = _loop_with(MockLLM(delay=0.03, text="ok"), tool_context)
    mc = MetricsCollector(probe_loop_lag=False)
    mc.attach(loop._event_bus)
    await loop.run(Conversation())
    snap = mc.snapshot()
    assert snap["counters"]["llm_calls"] >= 1
    assert snap["latency"]["llm_ttft"]["count"] >= 1
    assert snap["latency"]["llm_ttft"]["p50"] >= 30.0
