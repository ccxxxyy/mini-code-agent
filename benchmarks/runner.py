"""Headless benchmark runner -- run tasks without TUI, collect metrics.
无 TUI 的评测运行器——程序化运行任务并采集指标。

Usage 用法:
    uv run python benchmarks/runner.py --task fix_syntax_error
    uv run python benchmarks/runner.py --all
    uv run python benchmarks/runner.py --all --model deepseek-chat
    uv run python benchmarks/runner.py --all --repeat 5     # pass^k 可靠性

Reliability metrics 可靠性指标:
    A single 100% run says almost nothing -- an agent with pass@1 = 90%
    still fails at least once in 8 attempts 57% of the time. With
    --repeat k the runner reports:
      pass@1  mean per-run success rate 单次运行成功率均值
      pass^k  fraction of tasks that succeeded in ALL k runs 全部 k 次都成功的任务占比
      rho^k   pass^k / pass@1, consistency ratio (1.0 = fully stable) 一致性比
    单次 100% 几乎不说明问题——pass@1=90% 的 Agent 跑 8 次至少失败一次的
    概率是 57%。故引入重复运行与 pass^k。

Caps 上限:
    Every result records the caps in force (max_iterations, verify timeout).
    Without them an average cost/iteration count cannot be interpreted --
    runs killed by a cap are censored samples, not natural completions.
    每条结果都记录生效的上限。不记录上限则平均成本/轮次无法解读——被上限
    掐掉的运行是删失样本，不是自然完成。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# Add project src to path 将项目 src 加入路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.metrics import MetricsCollector
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import ToolCallEndEvent
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS

BENCHMARKS_DIR = Path(__file__).resolve().parent
TASKS_DIR = BENCHMARKS_DIR / "tasks"
WORKSPACES_DIR = BENCHMARKS_DIR / "workspaces"
RESULTS_DIR = BENCHMARKS_DIR / "results"

BENCHMARK_SYSTEM_PROMPT = """You are a coding agent being evaluated on a benchmark task.
Working directory: {working_dir}

Complete the task using the available tools. Be efficient — use as few tool calls as possible.
Do NOT ask questions. Make reasonable decisions and act."""

# Verification subprocess cap. Recorded into every result so a timeout-driven
# failure is never mistaken for a wrong answer.
# 验证子进程上限。写进每条结果，避免超时失败被误读为答错。
VERIFY_TIMEOUT_SECONDS = 30

# DeepSeek pricing (per 1M tokens) DeepSeek 定价（每百万 token）
PRICE_TABLE: dict[str, dict[str, float]] = {
    "default": {"input": 0.50, "output": 1.50},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-v4-flash": {"input": 0.01, "output": 0.04},
    "deepseek-v4-flash-0731": {"input": 0.01, "output": 0.04},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}


def load_task(name: str) -> dict[str, Any]:
    """Load a task definition from YAML. 从 YAML 加载任务定义。"""
    import yaml  # noqa: delayed import

    path = TASKS_DIR / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Task not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_task_simple(name: str) -> dict[str, Any]:
    """Fallback YAML parser without PyYAML dependency.
    不依赖 PyYAML 的简单 YAML 解析（兜底）。
    """
    path = TASKS_DIR / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Task not found: {path}")
    data: dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        # Only strip matching outer quotes 只剥匹配的外层引号对
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value.isdigit():
            value = int(value)
        data[key.strip()] = value
    return data


def list_tasks() -> list[str]:
    """List all available task names. 列出所有可用任务名。"""
    return sorted(p.stem for p in TASKS_DIR.glob("*.yaml"))


def estimate_cost(tokens: int, model: str) -> float:
    """Estimate USD cost for given token count and model.
    估算给定 token 数和模型的美元成本。
    """
    prices = PRICE_TABLE.get(model, PRICE_TABLE["default"])
    avg_price = (prices["input"] + prices["output"]) / 2
    return tokens * avg_price / 1_000_000


async def run_task(task_name: str, config: AgentConfig) -> dict[str, Any]:
    """Run a single benchmark task headlessly. Returns result dict.
    以 headless 方式运行单个评测任务，返回结果字典。

    Does NOT write to disk -- run_task_repeated owns persistence so that a
    k-run aggregate is written once instead of k times.
    不落盘——由 run_task_repeated 负责持久化，使 k 次运行只写一份聚合。
    """
    try:
        task = load_task(task_name)
    except ImportError:
        task = load_task_simple(task_name)

    workspace_src = WORKSPACES_DIR / task["workspace"]
    if not workspace_src.is_dir():
        return {"task": task_name, "error": f"Workspace not found: {workspace_src}"}

    # Copy workspace to temp dir so original fixtures stay clean
    # 复制 workspace 到临时目录，保持原始 fixture 不变
    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"bench_{task_name}_") as tmp:
        work_dir = Path(tmp)
        shutil.copytree(workspace_src, work_dir, dirs_exist_ok=True)

        # Build headless agent 构建无头 Agent
        event_bus = EventBus()
        llm = ProviderRegistry.create(config.llm)
        registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            registry.register(tool_class())

        tool_context = ToolContext(
            working_dir=work_dir,
            session=Session(),
            event_bus=event_bus,
            config=config,
        )
        agent_loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            event_bus=event_bus,
            config=config,
            tool_context=tool_context,
        )
        max_iter = int(task.get("max_iterations", 20))
        agent_loop._state.max_iterations = max_iter

        # Track tool calls 跟踪工具调用
        tool_calls: list[str] = []

        async def on_tool_end(event: ToolCallEndEvent) -> None:
            tool_calls.append(event.tool_name)

        event_bus.on(ToolCallEndEvent, on_tool_end)

        # Latency/quality instrumentation: a pure EventBus subscriber, so the
        # agent loop is unaware of it. The loop-lag probe runs concurrently
        # with the task and reports how long the event loop was ever blocked.
        # 延迟/质量埋点：纯 EventBus 订阅者，Agent 循环不知其存在。
        # loop lag 探针与任务并发运行，报告事件循环被阻塞的最长时间。
        metrics = MetricsCollector()
        metrics.attach(event_bus)
        metrics.start_probe()

        # Run agent 运行 Agent
        conversation = Conversation(
            system_prompt=BENCHMARK_SYSTEM_PROMPT.format(working_dir=work_dir)
        )
        conversation.append(Message(role=Role.USER, content=task["prompt"]))

        start_time = time.monotonic()
        try:
            output = await agent_loop.run(conversation)
        except Exception as e:
            output = f"Agent error: {e}"
        elapsed = time.monotonic() - start_time
        await metrics.stop_probe()
        metrics.detach(event_bus)

        tokens = agent_loop.last_turn_tokens
        iterations = agent_loop.state.iteration

        # Verify 验证
        verify_cmd = task.get("verify_command", "echo OK")
        verify_cmd = verify_cmd.replace("{workspace}", str(work_dir))
        try:
            verify_result = subprocess.run(
                verify_cmd,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=VERIFY_TIMEOUT_SECONDS,
            )
            success = verify_result.returncode == 0
            verify_output = (verify_result.stdout + verify_result.stderr).strip()[:300]
        except subprocess.TimeoutExpired:
            success = False
            verify_output = "Verification timed out"

        # Censoring flag: a run that burned its whole iteration budget did not
        # "fail on the merits", it was cut off. Averages that mix the two are
        # meaningless. 删失标记：耗尽迭代预算的运行不是"实力不济"而是被掐断，
        # 把两者混进均值毫无意义。
        hit_iteration_cap = iterations >= max_iter

        return {
            "task": task_name,
            "agent": "mini",
            "model": config.llm.model,
            "category": task.get("category", ""),
            "success": success,
            "tokens": tokens,
            "cost_usd": round(estimate_cost(tokens, config.llm.model), 6),
            "tool_calls": len(tool_calls),
            "tool_names": tool_calls,
            "iterations": iterations,
            "elapsed_seconds": round(elapsed, 1),
            "output": output[:500] if output else "",
            "verify_output": verify_output,
            "hit_iteration_cap": hit_iteration_cap,
            "caps": {
                "max_iterations": max_iter,
                "verify_timeout_seconds": VERIFY_TIMEOUT_SECONDS,
            },
            "metrics": metrics.snapshot(),
        }


def _median(values: list[float]) -> float:
    """Median; 0.0 for empty. Used instead of mean so one runaway run cannot
    skew a task's headline numbers. 中位数（空则 0.0）。用中位数而非均值，
    避免单次失控运行带偏该任务的主指标。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


async def run_task_repeated(
    task_name: str,
    config: AgentConfig,
    repeat: int = 1,
    results_dir: Path | None = None,
) -> dict[str, Any]:
    """Run one task `repeat` times and persist a single aggregate result.
    运行同一任务 repeat 次，落盘一份聚合结果。

    Headline scalars (success / tokens / iterations / elapsed) stay at the
    top level so existing report.py keeps working. With repeat == 1 the
    output is identical in shape to the old single-run format.
    主指标标量保持在顶层，使既有 report.py 继续可用；repeat == 1 时输出
    形状与旧单次格式一致。

    `success` at top level means "succeeded in ALL runs" -- the strict
    reading, matching pass^k. A task that passes 3 of 5 times is not a
    task the agent can do reliably.
    顶层 `success` 表示"全部 k 次都成功"——严格读法，与 pass^k 一致。
    5 次过 3 次的任务不算 Agent 能可靠完成。
    """
    runs: list[dict[str, Any]] = []
    for _i in range(max(1, repeat)):
        runs.append(await run_task(task_name, config))

    # An errored run (missing workspace etc.) has no usable fields
    # 出错的运行（workspace 缺失等）没有可用字段
    if any("error" in r for r in runs):
        return runs[0]

    successes = sum(1 for r in runs if r.get("success"))
    n = len(runs)
    representative = next((r for r in runs if r.get("success")), runs[0])

    aggregate: dict[str, Any] = {
        **representative,
        # Medians across runs 跨运行取中位数
        "tokens": int(_median([float(r.get("tokens", 0)) for r in runs])),
        "cost_usd": round(_median([float(r.get("cost_usd", 0.0)) for r in runs]), 6),
        "tool_calls": int(_median([float(r.get("tool_calls", 0)) for r in runs])),
        "iterations": int(_median([float(r.get("iterations", 0)) for r in runs])),
        "elapsed_seconds": round(_median([float(r.get("elapsed_seconds", 0.0)) for r in runs]), 1),
        # Strict success: all runs passed 严格成功：全部通过
        "success": successes == n,
        "repeat": n,
        "successes": successes,
        # Per-run success rate for this task 该任务的单次成功率
        "pass_at_1": round(successes / n, 4),
        "all_pass": successes == n,
        "censored_runs": sum(1 for r in runs if r.get("hit_iteration_cap")),
        "runs": [
            {
                "success": r.get("success"),
                "tokens": r.get("tokens"),
                "iterations": r.get("iterations"),
                "elapsed_seconds": r.get("elapsed_seconds"),
                "hit_iteration_cap": r.get("hit_iteration_cap"),
                "tool_calls": r.get("tool_calls"),
            }
            for r in runs
        ],
    }

    # Results are keyed by task name only, so a second model's run would silently
    # overwrite the first one's. That is how a control-arm experiment destroys its own
    # baseline -- keep each model in its own directory.
    # 结果文件只按任务名命名，所以跑第二个模型会静默覆盖第一个——对照组实验就是这样
    # 毁掉自己基线的。每个模型用各自的目录。
    out_dir = results_dir or RESULTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"mini_{task_name}.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return aggregate


def reliability_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate pass@1 / pass^k / consistency ratio across tasks.
    跨任务聚合 pass@1 / pass^k / 一致性比。

    pass^k here is the fraction of TASKS solved in every one of the k runs,
    which is the quantity that decays exponentially with k -- an agent at
    pass@1 = 0.9 lands near 0.9^k when failures are independent.
    此处 pass^k 是"每一次运行都成功的任务占比"，它随 k 指数衰减——失败独立
    时 pass@1=0.9 的 Agent 会趋近 0.9^k。
    """
    scored = [r for r in results if "pass_at_1" in r]
    if not scored:
        return {}
    k = max(int(r.get("repeat", 1)) for r in scored)
    pass_at_1 = sum(float(r["pass_at_1"]) for r in scored) / len(scored)
    pass_k = sum(1 for r in scored if r.get("all_pass")) / len(scored)
    return {
        "k": k,
        "tasks": len(scored),
        "pass_at_1": round(pass_at_1, 4),
        "pass_pow_k": round(pass_k, 4),
        # 1.0 = every task the agent can do at all, it does every time
        # 1.0 = 凡是能做的任务每次都能做成
        "consistency_ratio": round(pass_k / pass_at_1, 4) if pass_at_1 else None,
        "censored_runs": sum(int(r.get("censored_runs", 0)) for r in scored),
    }


def print_result(result: dict[str, Any]) -> None:
    """Pretty-print a single task result. 格式化输出单个任务结果。"""
    status = "PASS" if result.get("success") else "FAIL"
    name = result.get("task", "?")
    tokens = result.get("tokens", 0)
    cost = result.get("cost_usd", 0)
    tools = result.get("tool_calls", 0)
    elapsed = result.get("elapsed_seconds", 0)
    repeat = int(result.get("repeat", 1))
    rate = f"  {result.get('successes', 0)}/{repeat}" if repeat > 1 else ""
    print(
        f"  [{status}]{rate} {name:25s} tokens={tokens:>6d}  "
        f"cost=${cost:.4f}  tools={tools}  time={elapsed}s"
    )

    metrics = result.get("metrics") or {}
    ttft = (metrics.get("latency") or {}).get("llm_ttft") or {}
    lag = metrics.get("event_loop_lag") or {}
    if ttft.get("count"):
        print(
            f"         ttft p50/p95={ttft.get('p50')}/{ttft.get('p95')}ms "
            f"(n={ttft['count']})   loop_lag max={lag.get('max')}ms"
        )
    if result.get("censored_runs"):
        print(f"         censored (hit iteration cap): {result['censored_runs']}/{repeat}")
    if not result.get("success") and result.get("verify_output"):
        print(f"         verify: {result['verify_output'][:100]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Mini-Code-Agent Benchmark Runner")
    parser.add_argument("--task", type=str, help="Run a specific task by name")
    parser.add_argument("--all", action="store_true", help="Run all tasks")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--list", action="store_true", help="List available tasks")
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="K",
        help="Run each task K times to compute pass@1 / pass^k (default 1)",
    )
    parser.add_argument(
        "--results-dir",
        type=str,
        default=None,
        metavar="DIR",
        help=(
            "Where to write result JSON (default benchmarks/results). Use a separate "
            "directory per model -- results are keyed by task name only, so a second "
            "model would otherwise overwrite the first one's baseline."
        ),
    )
    args = parser.parse_args()

    if args.list:
        for name in list_tasks():
            print(f"  {name}")
        return

    config = ConfigLoader.load()
    if args.model:
        config.llm.model = args.model

    if args.task:
        tasks_to_run = [args.task]
    elif args.all:
        tasks_to_run = list_tasks()
    else:
        parser.print_help()
        return

    repeat = max(1, args.repeat)
    results_dir = Path(args.results_dir) if args.results_dir else RESULTS_DIR
    print(f"Model: {config.llm.model} ({config.llm.provider})")
    print(f"Tasks: {len(tasks_to_run)}   Repeat: {repeat}")
    print(f"Results dir: {results_dir}")
    print()

    results = []
    for task_name in tasks_to_run:
        print(f"Running: {task_name}...")
        result = await run_task_repeated(task_name, config, repeat=repeat, results_dir=results_dir)
        print_result(result)
        results.append(result)
        print()

    # Summary 汇总
    passed = sum(1 for r in results if r.get("success"))
    total_tokens = sum(r.get("tokens", 0) for r in results)
    total_cost = sum(r.get("cost_usd", 0) for r in results)
    total_tools = sum(r.get("tool_calls", 0) for r in results)
    print("=" * 60)
    label = "passed all runs" if repeat > 1 else "passed"
    print(f"Results: {passed}/{len(results)} {label}")
    print(f"Total tokens: {total_tokens}")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Total tool calls: {total_tools}")

    # Effectiveness-aware cost: cost per SOLVED task is the number that
    # actually matters -- a cheap agent that fails is not cheap.
    # 有效性感知成本：每个"解决了的"任务的成本才是真指标——便宜但做不成
    # 的 Agent 并不便宜。
    if passed:
        print(f"Cost per solved task: ${total_cost / passed:.4f}")
    else:
        print("Cost per solved task: n/a (nothing solved)")

    rel = reliability_summary(results)
    if rel:
        print()
        print(f"Reliability (k={rel['k']}, {rel['tasks']} tasks)")
        print(f"  pass@1 : {rel['pass_at_1']:.3f}   mean per-run success rate")
        print(f"  pass^k : {rel['pass_pow_k']:.3f}   solved in EVERY run")
        if rel.get("consistency_ratio") is not None:
            print(f"  rho^k  : {rel['consistency_ratio']:.3f}   1.0 = fully stable")
        if rel["censored_runs"]:
            print(f"  censored: {rel['censored_runs']} run(s) hit the iteration cap")

    # Aggregate latency across tasks 跨任务聚合延迟
    ttfts = [((r.get("metrics") or {}).get("latency") or {}).get("llm_ttft") or {} for r in results]
    lags = [(r.get("metrics") or {}).get("event_loop_lag") or {} for r in results]
    ttft_maxes = [t["max"] for t in ttfts if t.get("max") is not None]
    lag_maxes = [lg["max"] for lg in lags if lg.get("max") is not None]
    if ttft_maxes or lag_maxes:
        print()
        print("Latency (worst across tasks)")
        if ttft_maxes:
            print(f"  TTFT max      : {max(ttft_maxes):.1f}ms")
        if lag_maxes:
            print(f"  loop lag max  : {max(lag_maxes):.1f}ms   (>100ms = loop was blocked)")


if __name__ == "__main__":
    asyncio.run(main())
