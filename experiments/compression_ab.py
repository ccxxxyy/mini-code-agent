"""Compression strategy A/B experiment -- none vs extractive vs LLM summary.
压缩策略 A/B 对照实验——不压缩 vs 提取式摘要 vs LLM 摘要。

Research question 研究问题:
    How much intelligence does context compression cost?
    上下文压缩到底损失了多少智能？（任务成功率 × token 成本）

Usage 用法:
    uv run python experiments/compression_ab.py --list
    uv run python experiments/compression_ab.py --task multi_step_edit
    uv run python experiments/compression_ab.py --all
    uv run python experiments/compression_ab.py --all --arm llm
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


def print_result(r: dict[str, Any]) -> None:
    status = "PASS" if r.get("success") else "FAIL"
    print(
        f"  [{status}] {r['task']:20s} arm={r['arm']:10s} tokens={r.get('tokens', 0):>6d} "
        f"cost=${r.get('cost_usd', 0):.4f} tools={r.get('tool_calls', 0)} "
        f"compressed={r.get('compressed_messages', 0)} time={r.get('elapsed_seconds', 0)}s"
    )


def print_summary(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 70)
    print(f"{'Arm':<12} {'Pass':<8} {'Avg tokens':<12} {'Total cost':<12} {'Avg tools':<10}")
    print("-" * 70)
    for arm in ARMS:
        arm_results = [r for r in results if r.get("arm") == arm and "error" not in r]
        if not arm_results:
            continue
        passed = sum(1 for r in arm_results if r.get("success"))
        avg_tokens = sum(r.get("tokens", 0) for r in arm_results) / len(arm_results)
        total_cost = sum(r.get("cost_usd", 0) for r in arm_results)
        avg_tools = sum(r.get("tool_calls", 0) for r in arm_results) / len(arm_results)
        print(
            f"{arm:<12} {passed}/{len(arm_results):<6} {avg_tokens:<12.0f} "
            f"${total_cost:<11.4f} {avg_tools:<10.1f}"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Compression A/B Experiment")
    parser.add_argument("--task", type=str, help="Run a specific task")
    parser.add_argument("--all", action="store_true", help="Run default task set")
    parser.add_argument("--arm", type=str, choices=ARMS, help="Run only one arm")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--list", action="store_true", help="List tasks and arms")
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
    print(f"Tasks: {len(tasks)} x Arms: {len(arms)} = {len(tasks) * len(arms)} runs\n")

    results = []
    for task_name in tasks:
        for arm in arms:
            print(f"Running: {task_name} [{arm}]...")
            result = await run_arm(task_name, arm, config)
            print_result(result)
            results.append(result)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
