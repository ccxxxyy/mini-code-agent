"""Headless benchmark runner -- run tasks without TUI, collect metrics.
无 TUI 的评测运行器——程序化运行任务并采集指标。

Usage 用法:
    uv run python benchmarks/runner.py --task fix_syntax_error
    uv run python benchmarks/runner.py --all
    uv run python benchmarks/runner.py --all --model deepseek-chat
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
                timeout=30,
            )
            success = verify_result.returncode == 0
            verify_output = (verify_result.stdout + verify_result.stderr).strip()[:300]
        except subprocess.TimeoutExpired:
            success = False
            verify_output = "Verification timed out"

        result = {
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
        }

        # Save result 保存结果
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result_path = RESULTS_DIR / f"mini_{task_name}.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


def print_result(result: dict[str, Any]) -> None:
    """Pretty-print a single task result. 格式化输出单个任务结果。"""
    status = "PASS" if result.get("success") else "FAIL"
    name = result.get("task", "?")
    tokens = result.get("tokens", 0)
    cost = result.get("cost_usd", 0)
    tools = result.get("tool_calls", 0)
    elapsed = result.get("elapsed_seconds", 0)
    print(f"  [{status}] {name:25s} tokens={tokens:>6d}  cost=${cost:.4f}  tools={tools}  time={elapsed}s")
    if not result.get("success") and result.get("verify_output"):
        print(f"         verify: {result['verify_output'][:100]}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Mini-Code-Agent Benchmark Runner")
    parser.add_argument("--task", type=str, help="Run a specific task by name")
    parser.add_argument("--all", action="store_true", help="Run all tasks")
    parser.add_argument("--model", type=str, help="Override model name")
    parser.add_argument("--list", action="store_true", help="List available tasks")
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

    print(f"Model: {config.llm.model} ({config.llm.provider})")
    print(f"Tasks: {len(tasks_to_run)}")
    print()

    results = []
    for task_name in tasks_to_run:
        print(f"Running: {task_name}...")
        result = await run_task(task_name, config)
        print_result(result)
        results.append(result)
        print()

    # Summary 汇总
    passed = sum(1 for r in results if r.get("success"))
    total_tokens = sum(r.get("tokens", 0) for r in results)
    total_cost = sum(r.get("cost_usd", 0) for r in results)
    total_tools = sum(r.get("tool_calls", 0) for r in results)
    print("=" * 60)
    print(f"Results: {passed}/{len(results)} passed")
    print(f"Total tokens: {total_tokens}")
    print(f"Total cost: ${total_cost:.4f}")
    print(f"Total tool calls: {total_tools}")


if __name__ == "__main__":
    asyncio.run(main())
