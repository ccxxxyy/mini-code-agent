"""Compression strategy A/B experiment -- none vs extractive vs LLM summary.
压缩策略 A/B 对照实验——不压缩 vs 提取式摘要 vs LLM 摘要。

Research question 研究问题:
    How much intelligence does context compression cost?
    上下文压缩到底损失了多少智能？（任务成功率 × token 成本）

Usage 用法:
    uv run python experiments/compression_ab.py --list
    uv run python experiments/compression_ab.py --task multi_step_edit
    uv run python experiments/compression_ab.py --all --repeat 3
    uv run python experiments/compression_ab.py --all --arm llm

Reading the output 怎么读输出:
    Only trust a cell's token delta when its iteration count is CONSTANT across repeats.
    One extra agent iteration costs ~4.3k tokens here, which dwarfs the ~1k compression
    effect -- so a cell whose within-cell spread exceeds the between-arm delta says
    nothing. The summary prints a warning when an arm's delta changes sign across tasks,
    because a median over disagreeing signs is not a summary of a single effect.
    只有当某格的轮次跨重复恒定时，它的 token 差值才可信。此处 Agent 多跑一轮约 4.3k token，
    远大于 1k 量级的压缩效应——格内极差超过臂间差值的格子不能下结论。若某臂差值跨任务变号，
    汇总会打印告警，因为符号不一致的中位数不是单一效应的摘要。

Findings 已有结论: 见 experiments/results-snapshot/README.md 与 docs/tech-notes.md §135
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.runner import (
    BENCHMARK_SYSTEM_PROMPT,
    WORKSPACES_DIR,
    estimate_cost,
    load_task,
    load_task_simple,
)

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import (
    Compressor,
    DropToolResults,
    LLMSummarizeOldest,
    SlidingWindow,
    SummarizeOldest,
)
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import AgentConfig, MemoryConfig
from mini_agent.models.events import ToolCallEndEvent
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Small window to force compression on short benchmark tasks
# 小窗口，让 benchmark 短任务也能触发压缩
EXPERIMENT_CONTEXT_WINDOW = 6_000
EXPERIMENT_THRESHOLD = 0.6

# Tool-call-heavy tasks where compression actually kicks in
# 工具调用多、压缩真正会触发的任务
DEFAULT_TASKS = [
    "multi_step_edit",
    "find_bug",
    "refactor_rename",
    "write_unit_test",
    "grep_and_report",
]

ARMS = ["none", "extractive", "llm"]


def build_context_manager(arm: str, llm) -> ContextManager | None:
    """Build the context manager for an experiment arm. 为实验臂构建上下文管理器。"""
    if arm == "none":
        return None
    memory_config = MemoryConfig(
        context_window=EXPERIMENT_CONTEXT_WINDOW,
        compression_threshold=EXPERIMENT_THRESHOLD,
    )
    cm = ContextManager(memory_config)
    if arm == "extractive":
        strategies = [DropToolResults(), SummarizeOldest(), SlidingWindow()]
    elif arm == "llm":
        strategies = [DropToolResults(), LLMSummarizeOldest(llm), SlidingWindow()]
    else:
        raise ValueError(f"Unknown arm: {arm}")
    cm.set_compressor(Compressor(strategies))
    return cm


async def run_arm(task_name: str, arm: str, config: AgentConfig) -> dict[str, Any]:
    """Run one task under one experiment arm. 在一个实验臂下运行一个任务。"""
    try:
        task = load_task(task_name)
    except ImportError:
        task = load_task_simple(task_name)

    workspace_src = WORKSPACES_DIR / task["workspace"]
    if not workspace_src.is_dir():
        return {"task": task_name, "arm": arm, "error": f"Workspace not found: {workspace_src}"}

    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"exp_{arm}_{task_name}_") as tmp:
        work_dir = Path(tmp)
        shutil.copytree(workspace_src, work_dir, dirs_exist_ok=True)

        event_bus = EventBus()
        llm = ProviderRegistry.create(config.llm)
        registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            registry.register(tool_class())

        tool_context = ToolContext(
            working_dir=work_dir, session=Session(), event_bus=event_bus, config=config
        )
        context_manager = build_context_manager(arm, llm)
        agent_loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            event_bus=event_bus,
            config=config,
            tool_context=tool_context,
            context_manager=context_manager,
        )
        agent_loop._state.max_iterations = int(task.get("max_iterations", 20))

        tool_calls: list[str] = []

        async def on_tool_end(event: ToolCallEndEvent) -> None:
            tool_calls.append(event.tool_name)

        event_bus.on(ToolCallEndEvent, on_tool_end)

        conversation = Conversation(
            system_prompt=BENCHMARK_SYSTEM_PROMPT.format(working_dir=work_dir)
        )
        conversation.append(Message(role=Role.USER, content=task["prompt"]))

        # Count compressions by watching message compressed flags after run
        # 运行后通过 compressed 标记统计压缩次数
        start_time = time.monotonic()
        try:
            output = await agent_loop.run(conversation)
        except Exception as e:
            output = f"Agent error: {e}"
        elapsed = time.monotonic() - start_time

        compressed_msgs = sum(1 for m in conversation.messages if m.compressed)

        verify_cmd = task.get("verify_command", "echo OK").replace("{workspace}", str(work_dir))
        try:
            verify_result = subprocess.run(
                verify_cmd,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=30,
            )
            success = verify_result.returncode == 0
            verify_output = (verify_result.stdout + verify_result.stderr).strip()[:300]
        except subprocess.TimeoutExpired:
            success = False
            verify_output = "Verification timed out"

        tokens = agent_loop.last_turn_tokens
        result = {
            "experiment": "compression_ab",
            "task": task_name,
            "arm": arm,
            "model": config.llm.model,
            "success": success,
            "tokens": tokens,
            "cost_usd": round(estimate_cost(tokens, config.llm.model), 6),
            "tool_calls": len(tool_calls),
            "iterations": agent_loop.state.iteration,
            "compressed_messages": compressed_msgs,
            "final_message_count": len(conversation.messages),
            "elapsed_seconds": round(elapsed, 1),
            "output": (output or "")[:300],
            "verify_output": verify_output,
        }

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"compression_{arm}_{task_name}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


async def run_cell(task_name: str, arm: str, config: AgentConfig, repeat: int) -> dict[str, Any]:
    """Run one (task, arm) cell `repeat` times and aggregate.
    把一个 (任务, 臂) 格子跑 repeat 次并聚合。

    A single run per cell cannot separate a real effect from run-to-run variance -- with
    n=1 the token delta of an arm flipped sign across tasks. Report medians AND ranges so
    the reader can see whether the median means anything.
    每格只跑一次无法把真实效应和运行间波动分开——n=1 时同一臂的 token 差值在不同任务上会变号。
    故同时报中位数与区间，让读者自己判断中位数有没有意义。
    """
    runs: list[dict[str, Any]] = []
    for i in range(repeat):
        r = await run_arm(task_name, arm, config)
        if "error" in r:
            return r
        r["repeat_index"] = i + 1
        runs.append(r)

    def agg(key: str) -> dict[str, float]:
        vals = [float(r[key]) for r in runs]
        return {
            "median": round(statistics.median(vals), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }

    successes = sum(1 for r in runs if r["success"])
    aggregate: dict[str, Any] = {
        "experiment": "compression_ab",
        "task": task_name,
        "arm": arm,
        "model": config.llm.model,
        "repeat": repeat,
        "successes": successes,
        "pass_at_1": round(successes / repeat, 3),
        "all_pass": successes == repeat,
        "tokens": agg("tokens"),
        "tool_calls": agg("tool_calls"),
        "iterations": agg("iterations"),
        "compressed_messages": agg("compressed_messages"),
        "elapsed_seconds": agg("elapsed_seconds"),
        "cost_usd_total": round(sum(r["cost_usd"] for r in runs), 6),
        "runs": [
            {
                k: r[k]
                for k in (
                    "repeat_index",
                    "success",
                    "tokens",
                    "tool_calls",
                    "iterations",
                    "compressed_messages",
                    "elapsed_seconds",
                )
            }
            for r in runs
        ],
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"compression_{arm}_{task_name}.json").write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return aggregate


def print_result(r: dict[str, Any]) -> None:
    if "error" in r:
        print(f"  [ERROR] {r['task']} arm={r['arm']}: {r['error']}")
        return
    tok, tools = r["tokens"], r["tool_calls"]
    comp = r["compressed_messages"]
    print(
        f"  [{r['successes']}/{r['repeat']}] {r['task']:20s} arm={r['arm']:10s} "
        f"tokens={tok['median']:>7.0f} ({tok['min']:.0f}-{tok['max']:.0f}) "
        f"tools={tools['median']:.1f} compressed={comp['median']:.1f} "
        f"cost=${r['cost_usd_total']:.4f}"
    )


def print_summary(results: list[dict[str, Any]]) -> None:
    ok = [r for r in results if "error" not in r]
    if not ok:
        return
    base = {r["task"]: r["tokens"]["median"] for r in ok if r["arm"] == "none"}

    print("\n" + "=" * 96)
    print("PER-ARM AGGREGATE 各臂聚合")
    print("-" * 96)
    hdr = f"{'Arm':<12} {'Runs pass':<11} {'Median tokens':<15} "
    hdr += f"{'vs none':<10} {'Median tools':<14} {'Total cost':<12}"
    print(hdr)
    for arm in ARMS:
        rs = [r for r in ok if r["arm"] == arm]
        if not rs:
            continue
        passed = sum(r["successes"] for r in rs)
        total = sum(r["repeat"] for r in rs)
        med_tok = statistics.median([r["tokens"]["median"] for r in rs])
        med_tools = statistics.median([r["tool_calls"]["median"] for r in rs])
        cost = sum(r["cost_usd_total"] for r in rs)
        if arm == "none" or not base:
            delta = "--"
        else:
            base_med = statistics.median([base[r["task"]] for r in rs if r["task"] in base])
            delta = f"{(med_tok - base_med) / base_med * 100:+.1f}%"
        print(
            f"{arm:<12} {f'{passed}/{total}':<11} {med_tok:<15.0f} "
            f"{delta:<10} {med_tools:<14.1f} ${cost:<11.4f}"
        )

    # Per-task deltas. If an arm's sign flips across tasks, the aggregate median is not a
    # summary of anything -- say so rather than reporting the median alone.
    # 逐任务差值。若同一臂的符号跨任务变号，聚合中位数就不是任何东西的摘要——要说出来。
    print("\n" + "=" * 96)
    print("PER-TASK TOKEN DELTA vs none 逐任务 token 差值（相对不压缩）")
    print("-" * 96)
    print(f"{'Task':<22} {'none (min-max)':<22} {'extractive':<22} {'llm':<22}")
    for task in sorted({r["task"] for r in ok}):
        cells = []
        for arm in ARMS:
            r = next((x for x in ok if x["task"] == task and x["arm"] == arm), None)
            if r is None:
                cells.append("--")
                continue
            t = r["tokens"]
            if arm == "none":
                cells.append(f"{t['median']:.0f} ({t['min']:.0f}-{t['max']:.0f})")
            else:
                d = (t["median"] - base[task]) / base[task] * 100 if task in base else 0.0
                cells.append(f"{d:+.1f}% ({t['min']:.0f}-{t['max']:.0f})")
        print(f"{task:<22} {cells[0]:<22} {cells[1]:<22} {cells[2]:<22}")

    for arm in ("extractive", "llm"):
        ds = [
            (r["tokens"]["median"] - base[r["task"]]) / base[r["task"]] * 100
            for r in ok
            if r["arm"] == arm and r["task"] in base
        ]
        if ds and min(ds) < 0 < max(ds):
            print(
                f"\n[!] arm '{arm}' token delta changes sign across tasks "
                f"({min(ds):+.1f}% .. {max(ds):+.1f}%) -- the aggregate median is not a "
                f"summary of a single effect. 符号跨任务变号，聚合中位数不代表单一效应。"
            )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compression A/B Experiment")
    parser.add_argument("--task", type=str, help="Run a specific task")
    parser.add_argument("--all", action="store_true", help="Run default task set")
    parser.add_argument("--arm", type=str, choices=ARMS, help="Run only one arm")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--list", action="store_true", help="List tasks and arms")
    parser.add_argument(
        "--repeat", type=int, default=3, help="runs per (task, arm) cell (default 3)"
    )
    args = parser.parse_args()

    if args.list:
        print("Arms:", ", ".join(ARMS))
        print("Default tasks:", ", ".join(DEFAULT_TASKS))
        return

    config = ConfigLoader.load()
    if args.model:
        config.llm.model = args.model

    tasks = [args.task] if args.task else (DEFAULT_TASKS if args.all else None)
    if not tasks:
        parser.print_help()
        return
    arms = [args.arm] if args.arm else ARMS

    print(f"Model: {config.llm.model} | Window: {EXPERIMENT_CONTEXT_WINDOW} tokens")
    print(
        f"Tasks: {len(tasks)} x Arms: {len(arms)} x Repeat: {args.repeat} "
        f"= {len(tasks) * len(arms) * args.repeat} runs\n"
    )

    results = []
    for task_name in tasks:
        for arm in arms:
            print(f"Running: {task_name} [{arm}] x{args.repeat} ...")
            result = await run_cell(task_name, arm, config, args.repeat)
            print_result(result)
            results.append(result)

    print_summary(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    combined = RESULTS_DIR / "compression_ab_combined.json"
    combined.write_text(
        json.dumps(
            {
                "experiment": "compression_ab",
                "model": config.llm.model,
                "context_window": EXPERIMENT_CONTEXT_WINDOW,
                "compression_threshold": EXPERIMENT_THRESHOLD,
                "repeat": args.repeat,
                "cells": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nWrote {combined}")


if __name__ == "__main__":
    asyncio.run(main())
