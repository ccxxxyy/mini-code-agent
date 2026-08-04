"""Strong/weak model mixed orchestration experiment.
强弱模型混合编排对照实验。

Research question 研究问题:
    Can strong-planner + weak-workers achieve near-strong quality at
    a fraction of the cost?
    强弱搭配能否用零头成本达到接近全强模型的效果？

Arms 实验臂:
    strong-strong: planner and workers both use the strong model
    strong-weak:   strong planner, weak workers (the hypothesis)
    weak-weak:     everything on the weak model (cost floor)

Usage 用法:
    uv run python experiments/model_mix.py --list
    uv run python experiments/model_mix.py --strong smart --weak fast
    uv run python experiments/model_mix.py --strong smart --weak fast --arm strong-weak
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.runner import WORKSPACES_DIR, estimate_cost

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.planner import Planner
from mini_agent.core.subagent import SubAgentManager
from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.models.config import AgentConfig, LLMConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS

RESULTS_DIR = Path(__file__).resolve().parent / "results"

ARMS = ["strong-strong", "strong-weak", "weak-weak"]

# Decomposable compound tasks running on a copied benchmark workspace.
# 可分解的复合任务，在拷贝的 benchmark workspace 上运行。
COMPOUND_TASKS: list[dict[str, Any]] = [
    {
        "name": "analyze_and_document",
        "workspace": "multi_step_edit",
        "prompt": (
            "Analyze this Python project and produce three documentation files:\n"
            "1. ARCHITECTURE.md — what modules exist and how they relate\n"
            "2. FILES.md — a list of every source file with a one-line description\n"
            "3. IMPROVEMENTS.md — three concrete improvement suggestions\n"
            "Each file must be non-empty markdown."
        ),
        "verify_files": ["ARCHITECTURE.md", "FILES.md", "IMPROVEMENTS.md"],
    },
    {
        "name": "test_and_report",
        "workspace": "write_unit_test",
        "prompt": (
            "Do two things for this Python project:\n"
            "1. Write unit tests for the code in a file named test_generated.py\n"
            "2. Write QUALITY.md summarizing code quality issues you found\n"
            "Both files must be non-empty."
        ),
        "verify_files": ["test_generated.py", "QUALITY.md"],
    },
]


def make_provider(profile: LLMConfig):
    return ProviderRegistry.create(profile)


async def run_arm(
    task: dict[str, Any],
    arm: str,
    strong: LLMConfig,
    weak: LLMConfig,
    config: AgentConfig,
) -> dict[str, Any]:
    """Run one compound task under one orchestration arm.
    在一个编排臂下运行一个复合任务。"""
    planner_cfg = strong if arm.startswith("strong") else weak
    worker_cfg = weak if arm.endswith("weak") else strong

    workspace_src = WORKSPACES_DIR / task["workspace"]
    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"mix_{arm}_") as tmp:
        work_dir = Path(tmp)
        shutil.copytree(workspace_src, work_dir, dirs_exist_ok=True)

        event_bus = EventBus()
        registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            registry.register(tool_class())

        planner_llm = make_provider(planner_cfg)
        worker_llm = make_provider(worker_cfg)

        planner = Planner(planner_llm, max_steps=4)
        manager = SubAgentManager(
            llm=worker_llm,
            tool_registry=registry,
            config=config,
            event_bus=event_bus,
            working_dir=work_dir,
        )
        team = AgentTeam(
            TeamConfig(
                name=f"exp-{arm}",
                members=[TeamMember(name="worker", role="generalist")],
            ),
            planner,
            manager,
        )

        start_time = time.monotonic()
        try:
            report = await team.start(task["prompt"], timeout=300)
            team_success = report.success
            worker_tokens = sum(r.tokens_used for r in report.results)
            steps = len(report.plan.steps)
            error = ""
        except Exception as e:
            team_success = False
            worker_tokens = 0
            steps = 0
            error = str(e)
        elapsed = time.monotonic() - start_time

        # Planner tokens: rough estimate from its prompt+response (planner has
        # no usage tracking; estimate via count_tokens on the plan text)
        # Planner token 粗估：Planner 无 usage 跟踪，按计划文本估算
        planner_tokens = 800  # 分解调用的典型开销（prompt ~500 + response ~300）

        # File-existence verification 文件存在性验证
        missing = [f for f in task["verify_files"] if not (work_dir / f).is_file()]
        empty = [
            f
            for f in task["verify_files"]
            if (work_dir / f).is_file() and (work_dir / f).stat().st_size == 0
        ]
        success = not missing and not empty

        planner_cost = estimate_cost(planner_tokens, planner_cfg.model)
        worker_cost = estimate_cost(worker_tokens, worker_cfg.model)

        result = {
            "experiment": "model_mix",
            "task": task["name"],
            "arm": arm,
            "planner_model": planner_cfg.model,
            "worker_model": worker_cfg.model,
            "success": success,
            "team_reported_success": team_success,
            "plan_steps": steps,
            "planner_tokens_est": planner_tokens,
            "worker_tokens": worker_tokens,
            "total_cost_usd": round(planner_cost + worker_cost, 6),
            "missing_files": missing,
            "empty_files": empty,
            "elapsed_seconds": round(elapsed, 1),
            "error": error,
        }

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        (RESULTS_DIR / f"mix_{arm}_{task['name']}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return result


def print_result(r: dict[str, Any]) -> None:
    status = "PASS" if r.get("success") else "FAIL"
    print(
        f"  [{status}] {r['task']:22s} arm={r['arm']:14s} "
        f"steps={r.get('plan_steps', 0)} worker_tokens={r.get('worker_tokens', 0):>6d} "
        f"cost=${r.get('total_cost_usd', 0):.4f} time={r.get('elapsed_seconds', 0)}s"
    )
    if r.get("missing_files"):
        print(f"         missing: {r['missing_files']}")
    if r.get("error"):
        print(f"         error: {r['error'][:100]}")


def print_summary(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 70)
    print(f"{'Arm':<16} {'Pass':<8} {'Total cost':<14} {'Avg time':<10}")
    print("-" * 70)
    for arm in ARMS:
        arm_results = [r for r in results if r.get("arm") == arm]
        if not arm_results:
            continue
        passed = sum(1 for r in arm_results if r.get("success"))
        total_cost = sum(r.get("total_cost_usd", 0) for r in arm_results)
        avg_time = sum(r.get("elapsed_seconds", 0) for r in arm_results) / len(arm_results)
        print(f"{arm:<16} {passed}/{len(arm_results):<6} ${total_cost:<13.4f} {avg_time:<10.1f}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Strong/Weak Model Mix Experiment")
    parser.add_argument("--strong", type=str, help="Strong model profile name")
    parser.add_argument("--weak", type=str, help="Weak model profile name")
    parser.add_argument("--arm", type=str, choices=ARMS, help="Run only one arm")
    parser.add_argument("--list", action="store_true", help="List arms, tasks, profiles")
    args = parser.parse_args()

    config = ConfigLoader.load()

    if args.list:
        print("Arms:", ", ".join(ARMS))
        print("Tasks:", ", ".join(t["name"] for t in COMPOUND_TASKS))
        print("Profiles:", ", ".join(config.llm_profiles) or "(none configured)")
        return

    profiles = config.llm_profiles
    if len(profiles) < 2 and not (args.strong and args.weak):
        print("Need at least 2 profiles in MINI_AGENT_MODELS, or pass --strong/--weak")
        print("Available:", ", ".join(profiles) or "(none)")
        return

    names = list(profiles)
    strong_name = args.strong or names[0]
    weak_name = args.weak or names[1]
    strong = profiles[strong_name]
    weak = profiles[weak_name]

    arms = [args.arm] if args.arm else ARMS
    print(f"Strong: {strong.model} | Weak: {weak.model}")
    total_runs = len(COMPOUND_TASKS) * len(arms)
    print(f"Tasks: {len(COMPOUND_TASKS)} x Arms: {len(arms)} = {total_runs} runs\n")

    results = []
    for task in COMPOUND_TASKS:
        for arm in arms:
            print(f"Running: {task['name']} [{arm}]...")
            result = await run_arm(task, arm, strong, weak, config)
            print_result(result)
            results.append(result)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())
