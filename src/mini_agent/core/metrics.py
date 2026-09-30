"""Runtime metrics: latency histograms, event-loop lag probe, EventBus collector.
运行时指标：延迟直方图、事件循环阻塞探针、EventBus 采集器。

Why this exists 为什么需要它:
    An Agent is a non-deterministic system whose production failures are
    mostly *latency* and *cost* failures rather than crashes. Averages hide
    them: one 8s call among nineteen 200ms calls barely moves the mean but
    is exactly what a user notices. So everything here reports percentiles.
    Agent 是非确定性系统，线上故障多是延迟/成本问题而非崩溃。均值会掩盖
    它们：19 次 200ms 里混 1 次 8s，均值几乎不动，但用户感知到的正是那一
    次。所以这里一律报百分位。

Design notes 设计说明:
    - Percentiles come from a bounded sliding window of the most recent
      samples (a memory backstop for long-running sessions); count/sum/
      min/max stay exact over ALL samples ever recorded. A snapshot always
      carries the window size so a percentile is never mistaken for an
      all-time figure.
      百分位基于最近 N 个样本的有界滑动窗口（长会话的内存兜底）；
      count/sum/min/max 对历史全部样本保持精确。快照总是带上窗口样本数，
      避免百分位被误读成全时段数值。
    - Nearest-rank percentile, no interpolation: p95 of 20 samples is the
      19th smallest -- an actually observed value. Interpolation would
      invent a latency that never happened.
      最近秩百分位，不插值：20 个样本的 p95 就是第 19 小的那个真实观测值。
      插值会造出一个从未发生过的延迟。
    - MetricsCollector is a pure EventBus subscriber (same attach/detach
      shape as CostTracker) -- the Agent loop does not know it exists.
      MetricsCollector 是纯 EventBus 订阅者（与 CostTracker 同形），
      Agent 循环完全不知道它的存在。
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Any

from mini_agent.models.events import (
    ContextCompressedEvent,
    ContextSummaryDoneEvent,
    LLMResponseEvent,
    PermissionCheckEvent,
    SubAgentCompleteEvent,
    SubAgentSpawnEvent,
    ToolCallEndEvent,
    TurnCompleteEvent,
)

# Percentiles reported by default. p99 on a few dozen samples is nearly the
# max -- snapshots carry the sample count so that is visible, not hidden.
# 默认上报的百分位。样本仅几十个时 p99 几乎等于最大值——快照带样本数，
# 让这一点可见而非被掩盖。
DEFAULT_PERCENTILES = (50, 95, 99)

# Sliding-window cap for percentile computation. 4096 float samples is well
# under a megabyte and covers far more LLM calls than one session makes.
# 百分位计算的滑动窗口上限。4096 个 float 远小于 1MB，且远超单次会话的
# LLM 调用数。
DEFAULT_WINDOW = 4096

# Event-loop lag probe interval. Shorter catches smaller stalls but produces
# more samples; 100ms matches the common >100ms alert threshold.
# 事件循环探针间隔。越短能抓到越小的卡顿但样本越多；100ms 与业界常用的
# >100ms 告警阈值相匹配。
DEFAULT_PROBE_INTERVAL = 0.1


class Histogram:
    """Latency sample collector with nearest-rank percentiles.
    延迟样本采集器，提供最近秩百分位。
    """

    def __init__(self, name: str, unit: str = "ms", window: int = DEFAULT_WINDOW) -> None:
        self.name = name
        self.unit = unit
        self._window: deque[float] = deque(maxlen=window)
        # Exact over all samples ever seen, not just the window
        # 对历史全部样本精确，不限于窗口内
        self._count = 0
        self._sum = 0.0
        self._min: float | None = None
        self._max: float | None = None

    def record(self, value: float) -> None:
        """Record one sample. 记录一个样本。"""
        self._window.append(value)
        self._count += 1
        self._sum += value
        if self._min is None or value < self._min:
            self._min = value
        if self._max is None or value > self._max:
            self._max = value

    @property
    def count(self) -> int:
        return self._count

    def percentile(self, p: float) -> float | None:
        """Nearest-rank percentile over the current window; None if empty.
        当前窗口的最近秩百分位；无样本返回 None。
        """
        if not self._window:
            return None
        ordered = sorted(self._window)
        # Nearest rank: ceil(p/100 * n), 1-indexed -> clamp into range
        # 最近秩：ceil(p/100 * n)，1 起索引 -> 夹到合法范围
        rank = -(-int(p) * len(ordered) // 100)  # ceil division 向上取整
        idx = min(max(rank - 1, 0), len(ordered) - 1)
        return ordered[idx]

    def snapshot(self, percentiles: tuple[int, ...] = DEFAULT_PERCENTILES) -> dict[str, Any]:
        """JSON-ready summary. `window` exposes how many samples the
        percentiles actually cover. 可直接进 JSON 的摘要。`window` 暴露百分位
        实际覆盖的样本数。
        """
        out: dict[str, Any] = {
            "unit": self.unit,
            "count": self._count,
            "window": len(self._window),
        }
        if self._count:
            out["min"] = round(self._min or 0.0, 1)
            out["max"] = round(self._max or 0.0, 1)
            out["mean"] = round(self._sum / self._count, 1)
        for p in percentiles:
            v = self.percentile(p)
            out[f"p{p}"] = round(v, 1) if v is not None else None
        return out


class LoopLagProbe:
    """Measures asyncio event-loop scheduling delay.
    测量 asyncio 事件循环的调度延迟。

    Mechanism: sleep for a known interval, then compare the elapsed wall
    time against it. The excess is time the loop could not hand control
    back -- i.e. someone ran blocking work on it. This is the single most
    under-monitored metric in Python async services: loop lag can reach
    seconds while HTTP latency still looks healthy, because the stall hits
    every coroutine equally.
    原理：睡一个已知间隔，再比较实际流逝时间，超出部分就是事件循环无法
    交还控制权的时长——即有人在循环上跑了阻塞工作。这是 Python 异步服务
    最容易漏掉的指标：loop lag 可以高达数秒而 HTTP 延迟看起来仍然正常，
    因为卡顿平等地打击每个协程。
    """

    def __init__(
        self,
        histogram: Histogram | None = None,
        interval: float = DEFAULT_PROBE_INTERVAL,
    ) -> None:
        self.interval = interval
        self.histogram = histogram or Histogram("event_loop_lag", unit="ms")
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Begin probing. No-op if already running. 开始探测；已在运行则空操作。"""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop probing and await task teardown. 停止探测并等待任务收尾。"""
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _run(self) -> None:
        while True:
            t0 = time.perf_counter()
            await asyncio.sleep(self.interval)
            # Clamp: clock granularity can make this marginally negative.
            # 夹到非负：时钟粒度可能让这个值略小于 0。
            lag = max(0.0, time.perf_counter() - t0 - self.interval)
            self.histogram.record(lag * 1000)


class MetricsCollector:
    """EventBus subscriber that turns events into latency/quality metrics.
    EventBus 订阅者——把事件转换为延迟/质量指标。

    Covers the five observability layers that matter for an Agent:
    latency (TTFT, tool duration), throughput (loop lag), quality (tool
    success, iteration counts), reliability (permission decisions), and
    context pressure (compression frequency).
    覆盖 Agent 可观测性的五层：延迟（TTFT、工具耗时）、吞吐（loop lag）、
    质量（工具成功率、迭代轮次）、可靠性（权限判定）、上下文压力
    （压缩频率）。
    """

    def __init__(self, probe_loop_lag: bool = True) -> None:
        self.ttft = Histogram("llm_ttft", unit="ms")
        self.stream_duration = Histogram("llm_stream_duration", unit="ms")
        self.tool_duration = Histogram("tool_duration", unit="ms")
        self.compression_duration = Histogram("context_compression", unit="ms")
        self.context_fork_duration = Histogram("context_fork", unit="ms")
        self.iterations = Histogram("turn_iterations", unit="count")
        # Per-tool latency so a slow tool cannot hide behind a fast one
        # 按工具分桶，避免慢工具被快工具掩盖
        self.per_tool: dict[str, Histogram] = {}
        self.tool_calls = 0
        self.tool_errors = 0
        self.turns = 0
        self.llm_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cache_read_tokens = 0
        self.cache_creation_tokens = 0
        # Routine conversation compression (ContextCompressedEvent).
        # 常规对话压缩（ContextCompressedEvent）。
        self.compressions = 0
        # Passes that did NOT reduce tokens -- these open the circuit breaker, so
        # folding them into `compressions` would report a working compressor while
        # the breaker is shutting it off.
        # 未降低 token 的压缩——它们打开熔断器；混进 `compressions` 会在熔断器正在
        # 关停压缩时报告"压缩正常工作"。
        self.compressions_ineffective = 0
        self.compressed_tokens_saved = 0
        # Fork-style summaries taken when a sub-agent inherits context
        # (ContextSummaryDoneEvent). A DIFFERENT thing from the above: it fires
        # once per spawn, not once per compression. Conflating the two was a real
        # bug -- `compressions` used to be wired to this event, so it could never
        # count an actual compression.
        # 子 Agent 继承上下文时的 fork 式摘要（ContextSummaryDoneEvent）。与上面是
        # 两回事：它每次 spawn 触发一次，而非每次压缩一次。混为一谈曾是真 bug——
        # `compressions` 原本接的是这个事件，因此永远数不到一次真正的压缩。
        self.context_forks = 0
        self.subagents_spawned = 0
        self.subagents_failed = 0
        # decision -> count, and reason -> count. `reason` is what separates
        # "policy auto-blocked it" from "the user said no" -- the difference
        # matters because only the latter is a candidate false positive.
        # decision/reason 各自计数。reason 区分"策略自动拦的"和"用户拒的"
        # ——只有后者才可能是误拦。
        self.permission_decisions: dict[str, int] = {}
        self.permission_reasons: dict[str, int] = {}
        self.loop_lag_probe = LoopLagProbe() if probe_loop_lag else None
        # Guards counters against concurrent SubAgent events (same reason
        # CostTracker holds one). 保护计数器不被并发 SubAgent 事件破坏
        # （与 CostTracker 持锁同因）。
        self._lock = asyncio.Lock()

    # --- EventBus wiring 事件总线接线 ---

    def attach(self, bus: Any) -> None:
        bus.on(LLMResponseEvent, self._on_llm_response)
        bus.on(ToolCallEndEvent, self._on_tool_end)
        bus.on(TurnCompleteEvent, self._on_turn_complete)
        bus.on(PermissionCheckEvent, self._on_permission)
        bus.on(ContextCompressedEvent, self._on_compression)
        bus.on(ContextSummaryDoneEvent, self._on_context_fork)
        bus.on(SubAgentSpawnEvent, self._on_subagent_spawn)
        bus.on(SubAgentCompleteEvent, self._on_subagent_complete)

    def detach(self, bus: Any) -> None:
        bus.off(LLMResponseEvent, self._on_llm_response)
        bus.off(ToolCallEndEvent, self._on_tool_end)
        bus.off(TurnCompleteEvent, self._on_turn_complete)
        bus.off(PermissionCheckEvent, self._on_permission)
        bus.off(ContextCompressedEvent, self._on_compression)
        bus.off(ContextSummaryDoneEvent, self._on_context_fork)
        bus.off(SubAgentSpawnEvent, self._on_subagent_spawn)
        bus.off(SubAgentCompleteEvent, self._on_subagent_complete)

    def start_probe(self) -> None:
        """Start the loop-lag probe (needs a running loop).
        启动 loop lag 探针（需要已运行的事件循环）。"""
        if self.loop_lag_probe is not None:
            self.loop_lag_probe.start()

    async def stop_probe(self) -> None:
        if self.loop_lag_probe is not None:
            await self.loop_lag_probe.stop()

    # --- handlers 处理器 ---

    async def _on_llm_response(self, event: LLMResponseEvent) -> None:
        async with self._lock:
            self.llm_calls += 1
            self.prompt_tokens += event.prompt_tokens
            self.completion_tokens += event.completion_tokens
            self.cache_read_tokens += event.cache_read_input_tokens
            self.cache_creation_tokens += event.cache_creation_input_tokens
            # 0 means the stream produced no payload (cancelled / error /
            # non-streaming provider) -- recording it would drag TTFT toward
            # zero and make the metric lie.
            # 0 表示流未产出载荷（取消/出错/非流式 Provider）——记录它会把
            # TTFT 拉向 0，让指标说谎。
            if event.ttft_ms > 0:
                self.ttft.record(event.ttft_ms)
            if event.stream_duration_ms > 0:
                self.stream_duration.record(event.stream_duration_ms)

    async def _on_tool_end(self, event: ToolCallEndEvent) -> None:
        async with self._lock:
            self.tool_calls += 1
            if event.is_error:
                self.tool_errors += 1
            if event.duration_ms > 0:
                self.tool_duration.record(event.duration_ms)
                name = event.tool_name or "(unknown)"
                hist = self.per_tool.get(name)
                if hist is None:
                    hist = Histogram(f"tool_duration.{name}", unit="ms")
                    self.per_tool[name] = hist
                hist.record(event.duration_ms)

    async def _on_turn_complete(self, event: TurnCompleteEvent) -> None:
        async with self._lock:
            self.turns += 1
            if event.iteration_count > 0:
                self.iterations.record(float(event.iteration_count))

    async def _on_permission(self, event: PermissionCheckEvent) -> None:
        async with self._lock:
            decision = event.decision or "(unknown)"
            self.permission_decisions[decision] = self.permission_decisions.get(decision, 0) + 1
            reason = event.reason or "(none)"
            self.permission_reasons[reason] = self.permission_reasons.get(reason, 0) + 1

    async def _on_compression(self, event: ContextCompressedEvent) -> None:
        async with self._lock:
            self.compressions += 1
            if not event.effective:
                self.compressions_ineffective += 1
            saved = event.before_tokens - event.after_tokens
            if saved > 0:
                self.compressed_tokens_saved += saved
            if event.duration_ms > 0:
                self.compression_duration.record(event.duration_ms)

    async def _on_context_fork(self, event: ContextSummaryDoneEvent) -> None:
        async with self._lock:
            self.context_forks += 1
            if event.duration_ms > 0:
                self.context_fork_duration.record(event.duration_ms)

    async def _on_subagent_spawn(self, event: SubAgentSpawnEvent) -> None:
        async with self._lock:
            self.subagents_spawned += 1

    async def _on_subagent_complete(self, event: SubAgentCompleteEvent) -> None:
        async with self._lock:
            if not event.success:
                self.subagents_failed += 1

    # --- reporting 输出 ---

    @property
    def tool_success_rate(self) -> float | None:
        """Fraction of tool calls that did not error; None if no calls.
        未出错的工具调用占比；无调用返回 None。"""
        if self.tool_calls == 0:
            return None
        return (self.tool_calls - self.tool_errors) / self.tool_calls

    def snapshot(self) -> dict[str, Any]:
        """JSON-ready metrics snapshot. 可直接进 JSON 的指标快照。"""
        out: dict[str, Any] = {
            "latency": {
                "llm_ttft": self.ttft.snapshot(),
                "llm_stream_duration": self.stream_duration.snapshot(),
                "tool_duration": self.tool_duration.snapshot(),
            },
            "counters": {
                "llm_calls": self.llm_calls,
                "turns": self.turns,
                "tool_calls": self.tool_calls,
                "tool_errors": self.tool_errors,
                "compressions": self.compressions,
                "compressions_ineffective": self.compressions_ineffective,
                "compressed_tokens_saved": self.compressed_tokens_saved,
                "context_forks": self.context_forks,
                "subagents_spawned": self.subagents_spawned,
                "subagents_failed": self.subagents_failed,
            },
            "tokens": {
                "prompt": self.prompt_tokens,
                "completion": self.completion_tokens,
                "cache_read": self.cache_read_tokens,
                "cache_creation": self.cache_creation_tokens,
            },
            "quality": {
                "tool_success_rate": (
                    round(self.tool_success_rate, 4) if self.tool_success_rate is not None else None
                ),
                "turn_iterations": self.iterations.snapshot(),
            },
            "permissions": {
                "by_decision": dict(self.permission_decisions),
                "by_reason": dict(self.permission_reasons),
            },
        }
        if self.compressions:
            out["latency"]["context_compression"] = self.compression_duration.snapshot()
        if self.context_forks:
            out["latency"]["context_fork"] = self.context_fork_duration.snapshot()
        if self.per_tool:
            out["latency"]["per_tool"] = {
                name: hist.snapshot() for name, hist in sorted(self.per_tool.items())
            }
        if self.loop_lag_probe is not None:
            out["event_loop_lag"] = self.loop_lag_probe.histogram.snapshot()
        return out
