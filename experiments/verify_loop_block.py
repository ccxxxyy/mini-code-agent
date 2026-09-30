"""Quantify the event-loop blocking caused by synchronous file I/O in async tools.
量化 async 工具里同步文件 I/O 造成的事件循环阻塞。

Research question 研究问题:
    A directory scan that runs synchronously inside an `async def` freezes the single
    event loop for the whole scan. How long, and what does moving it to a thread cost?
    在 `async def` 里同步跑目录扫描会冻结整个事件循环。冻结多久？下放线程的代价是多少？

Method 方法:
    Two arms over the SAME fixture tree, in the same process:
      - "blocking"  -- `asyncio.to_thread` is monkeypatched to call the target directly,
                       so `GrepTool._scan` runs ON the event loop (simulates pre-fix).
      - "threaded"  -- the real `asyncio.to_thread`, i.e. current shipping behaviour.
    A heartbeat probe coroutine sleeps at a fixed interval and records how late it
    actually wakes up; the largest gap is the loop's worst blocked stretch.

    同一进程内、同一份 fixture 上跑两臂：
      - "blocking"：把 `asyncio.to_thread` 打桩为直接调用，让 `_scan` 跑在事件循环上（模拟修复前）
      - "threaded"：真实的 `asyncio.to_thread`，即当前线上行为
    心跳探针协程按固定间隔 sleep 并记录实际醒来的迟到量，最大间隔即事件循环最长阻塞时段。

    Why a monkeypatch and not a git checkout of the old commit: the two arms must run in
    one process on one fixture, otherwise disk cache state and machine load differ
    between measurements and the comparison is worthless.
    为什么用打桩而不是 checkout 旧 commit：两臂必须同进程、同 fixture，否则磁盘缓存状态和
    机器负载在两次测量间不同，对比就没有意义。

Usage 用法:
    uv run python experiments/verify_loop_block.py
    uv run python experiments/verify_loop_block.py --files 3000 --file-kb 23
    uv run python experiments/verify_loop_block.py --keep-fixture   # reuse across runs
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mini_agent.events.bus import EventBus  # noqa: E402
from mini_agent.models.config import AgentConfig  # noqa: E402
from mini_agent.models.session import Session  # noqa: E402
from mini_agent.tools.base import ToolContext  # noqa: E402
from mini_agent.tools.builtin.grep import GrepTool  # noqa: E402

EXPERIMENTS_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = EXPERIMENTS_DIR / ".fixture_loop_block"
RESULTS_DIR = EXPERIMENTS_DIR / "results"

# Heartbeat cadence. Small enough that a sub-100ms block is still visible, large enough
# that the probe itself doesn't dominate the loop.
# 心跳间隔。小到能看见 100ms 以下的阻塞，大到探针自身不会占满事件循环。
PROBE_INTERVAL_S = 0.005

# The pattern must miss almost everywhere, so the cost measured is the scan itself
# (walk + read every file) rather than match formatting.
# 这个 pattern 必须几乎不命中，让测到的成本是扫描本身（遍历+读全部文件）而非匹配格式化。
SEARCH_PATTERN = r"zzz_needle_never_present_zzz"


class HeartbeatProbe:
    """Sleep-drift watchdog: measures how late the loop gets back to this coroutine.
    sleep 漂移看门狗：测量事件循环多晚才回到这个协程。

    Reports the max gap between consecutive wake-ups. With an idle loop that is
    ~PROBE_INTERVAL_S; while the loop is blocked no wake-up happens at all, so the gap
    spanning the blocked stretch equals the block duration.
    报告相邻两次醒来的最大间隔。空闲时约等于 PROBE_INTERVAL_S；阻塞期间根本不会醒来，
    所以跨越阻塞段的那个间隔就等于阻塞时长。
    """

    def __init__(self, interval_s: float = PROBE_INTERVAL_S) -> None:
        self.interval_s = interval_s
        self.gaps_ms: list[float] = []
        self._task: asyncio.Task[None] | None = None
        self._stop = False

    async def _run(self) -> None:
        last = time.perf_counter()
        while not self._stop:
            await asyncio.sleep(self.interval_s)
            now = time.perf_counter()
            self.gaps_ms.append((now - last) * 1000.0)
            last = now

    def start(self) -> None:
        self._stop = False
        self.gaps_ms.clear()
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        self._stop = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def summary(self) -> dict[str, float | int]:
        if not self.gaps_ms:
            return {"samples": 0}
        ordered = sorted(self.gaps_ms)
        return {
            "samples": len(ordered),
            "max_ms": round(ordered[-1], 1),
            "p99_ms": round(ordered[min(int(len(ordered) * 0.99), len(ordered) - 1)], 1),
            "p50_ms": round(statistics.median(ordered), 1),
        }


def build_fixture(root: Path, n_files: int, file_kb: int) -> dict[str, Any]:
    """Create n_files text files of ~file_kb each, spread over 100-file subdirs.
    造 n_files 个约 file_kb 大小的文本文件，按每目录 100 个分散到子目录。
    """
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    # A line long enough that regex scanning has real work per line.
    # 行要足够长，让正则逐行扫描有真实工作量。
    line = ("def handler(request, response):  # filler payload for scan cost " * 2) + "\n"
    lines_per_file = max(1, (file_kb * 1024) // len(line))
    body = line * lines_per_file

    total_bytes = 0
    for i in range(n_files):
        sub = root / f"pkg_{i // 100:03d}"
        sub.mkdir(exist_ok=True)
        f = sub / f"mod_{i:05d}.py"
        f.write_text(body, encoding="utf-8")
        total_bytes += len(body)

    return {
        "files": n_files,
        "bytes": total_bytes,
        "mb": round(total_bytes / 1024 / 1024, 1),
        "dirs": (n_files + 99) // 100,
    }


async def run_arm(arm: str, ctx: ToolContext, target: Path) -> dict[str, Any]:
    """Run one grep scan with the probe attached. arm in {"blocking", "threaded"}.
    挂着探针跑一次 grep 扫描。arm 取 {"blocking", "threaded"}。
    """
    tool = GrepTool()
    probe = HeartbeatProbe()

    real_to_thread = asyncio.to_thread

    async def direct_call(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Degrade to_thread to a synchronous in-loop call -- the pre-fix behaviour.
        把 to_thread 退化为循环内同步直调——修复前的行为。
        """
        return fn(*args, **kwargs)

    if arm == "blocking":
        asyncio.to_thread = direct_call  # type: ignore[assignment]

    try:
        probe.start()
        # Let the probe settle so the first gap isn't startup noise.
        # 先让探针稳定，避免首个间隔混入启动噪声。
        await asyncio.sleep(0.1)
        probe.gaps_ms.clear()

        t0 = time.perf_counter()
        result = await tool.execute(ctx, pattern=SEARCH_PATTERN, path=str(target))
        scan_ms = (time.perf_counter() - t0) * 1000.0

        await asyncio.sleep(0.05)
        await probe.stop()
    finally:
        asyncio.to_thread = real_to_thread  # type: ignore[assignment]

    return {
        "arm": arm,
        "scan_ms": round(scan_ms, 1),
        "heartbeat": probe.summary(),
        "tool_error": bool(getattr(result, "is_error", False)),
    }


async def main_async(args: argparse.Namespace) -> int:
    reuse = args.keep_fixture and FIXTURE_DIR.exists()
    if reuse:
        existing = sum(1 for _ in FIXTURE_DIR.rglob("*.py"))
        fixture = {"files": existing, "reused": True}
        print(f"Reusing fixture: {existing} files at {FIXTURE_DIR}")
    else:
        print(f"Building fixture: {args.files} files x ~{args.file_kb}KB ...")
        t0 = time.perf_counter()
        fixture = build_fixture(FIXTURE_DIR, args.files, args.file_kb)
        print(
            f"  {fixture['files']} files / {fixture['mb']}MB / {fixture['dirs']} dirs "
            f"in {time.perf_counter() - t0:.1f}s"
        )

    ctx = ToolContext(
        working_dir=FIXTURE_DIR,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )

    # Warm the OS page cache so arm order doesn't decide the winner.
    # 先预热操作系统页缓存，避免两臂顺序决定结果。
    print("Warming page cache ...")
    await GrepTool().execute(ctx, pattern=SEARCH_PATTERN, path=str(FIXTURE_DIR))

    # Alternate the arms across repeats. A single measurement of each arm is exactly how
    # a page-cache artefact gets mistaken for a real cost, so report medians and ranges.
    # 两臂交替重复。每臂只测一次正是把页缓存假象误当真实代价的成因，故报中位数和区间。
    runs: list[dict[str, Any]] = []
    for i in range(args.repeat):
        for arm in ("blocking", "threaded"):
            print(f"Repeat {i + 1}/{args.repeat}, arm: {arm} ...")
            r = await run_arm(arm, ctx, FIXTURE_DIR)
            r["repeat"] = i + 1
            runs.append(r)

    def series(arm: str, key: str) -> list[float]:
        if key == "lag":
            return [float(r["heartbeat"].get("max_ms", 0.0)) for r in runs if r["arm"] == arm]
        return [float(r["scan_ms"]) for r in runs if r["arm"] == arm]

    def stats(vals: list[float]) -> dict[str, float]:
        return {
            "median": round(statistics.median(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }

    b_scan, t_scan = stats(series("blocking", "scan")), stats(series("threaded", "scan"))
    b_lag, t_lag = stats(series("blocking", "lag")), stats(series("threaded", "lag"))
    scan_delta_pct = (t_scan["median"] - b_scan["median"]) / b_scan["median"] * 100
    lag_delta_pct = (
        (t_lag["median"] - b_lag["median"]) / b_lag["median"] * 100 if b_lag["median"] else 0.0
    )

    # Per-repeat scan deltas -- the spread is what tells you whether the median means
    # anything. 逐次的扫描耗时差值——区间宽度决定中位数有没有意义。
    per_repeat_scan_delta = [
        round(
            (series("threaded", "scan")[i] - series("blocking", "scan")[i])
            / series("blocking", "scan")[i]
            * 100,
            1,
        )
        for i in range(args.repeat)
    ]

    report: dict[str, Any] = {
        "fixture": fixture,
        "probe_interval_ms": PROBE_INTERVAL_S * 1000,
        "repeat": args.repeat,
        "runs": runs,
        "aggregate": {
            "blocking": {"scan_ms": b_scan, "loop_block_max_ms": b_lag},
            "threaded": {"scan_ms": t_scan, "loop_block_max_ms": t_lag},
        },
        "delta_of_medians": {
            "scan_pct": round(scan_delta_pct, 1),
            "loop_block_pct": round(lag_delta_pct, 1),
        },
        "per_repeat_scan_delta_pct": per_repeat_scan_delta,
        "platform": sys.platform,
        "python": sys.version.split()[0],
    }

    print()
    print("=" * 78)
    print(
        f"Fixture: {fixture.get('files')} files"
        + (f" / {fixture['mb']}MB" if "mb" in fixture else "")
        + f"   |   repeats: {args.repeat}"
    )
    header = f"{'arm':10s} {'scan median':>14s} {'scan range':>18s} "
    header += f"{'loop block med':>16s} {'range':>16s}"
    print(header)
    for arm, sc, lg in (("blocking", b_scan, b_lag), ("threaded", t_scan, t_lag)):
        scan_range = f"{sc['min']:.0f}-{sc['max']:.0f}ms"
        lag_range = f"{lg['min']:.0f}-{lg['max']:.0f}ms"
        print(
            f"{arm:10s} {sc['median']:>12.1f}ms {scan_range:>18s} "
            f"{lg['median']:>14.1f}ms {lag_range:>16s}"
        )
    print("-" * 78)
    print(
        f"Worst event-loop block (median of {args.repeat}): "
        f"{b_lag['median']:.1f}ms -> {t_lag['median']:.1f}ms  ({lag_delta_pct:+.1f}%)"
    )
    print(
        f"Scan time (median of {args.repeat}): {scan_delta_pct:+.1f}%   "
        f"per-repeat deltas: {per_repeat_scan_delta}"
    )
    print("=" * 78)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "verify_loop_block.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")

    if not args.keep_fixture and not reuse:
        shutil.rmtree(FIXTURE_DIR, ignore_errors=True)
        print(f"Removed fixture {FIXTURE_DIR}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", type=int, default=3000, help="fixture file count")
    parser.add_argument("--file-kb", type=int, default=23, help="approx KB per file")
    parser.add_argument(
        "--repeat", type=int, default=5, help="alternating repeats per arm (default 5)"
    )
    parser.add_argument(
        "--keep-fixture",
        action="store_true",
        help="keep (and reuse) the fixture tree between runs",
    )
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
