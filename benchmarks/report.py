"""Report generator -- read results and produce Markdown comparison table.
报告生成器——读取结果文件并生成 Markdown 对比表格。

Usage 用法:
    uv run python benchmarks/report.py
    uv run python benchmarks/report.py --output benchmarks/README.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

BENCHMARKS_DIR = Path(__file__).resolve().parent
RESULTS_DIR = BENCHMARKS_DIR / "results"
CC_RESULTS_DIR = BENCHMARKS_DIR / "cc_results"


def load_mini_results() -> list[dict[str, Any]]:
    """Load all mini agent results from JSON files.
    从 JSON 文件加载所有 mini agent 结果。
    """
    results = []
    for f in sorted(RESULTS_DIR.glob("mini_*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    return results


def load_cc_results() -> dict[str, dict[str, Any]]:
    """Load CC results from YAML files (simple parser).
    从 YAML 文件加载 CC 结果（简单解析器）。
    """
    cc: dict[str, dict[str, Any]] = {}
    for f in sorted(CC_RESULTS_DIR.glob("*.yaml")):
        data: dict[str, Any] = {}
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.strip().strip("\"'")
            if value.lower() == "true":
                value = True
            elif value.lower() == "false":
                value = False
            elif value.replace(".", "").isdigit():
                value = float(value) if "." in str(value) else int(value)
            data[key.strip()] = value
        if "task" in data:
            cc[data["task"]] = data
    return cc


def generate_report(mini: list[dict], cc: dict[str, dict]) -> str:
    """Generate Markdown comparison table.
    生成 Markdown 对比表格。
    """
    lines: list[str] = []
    lines.append("# Benchmark Results 评测结果\n")
    lines.append("")

    if mini:
        model = mini[0].get("model", "unknown")
        lines.append(f"**Mini Agent Model**: {model}\n")
        lines.append("")

    # Table header 表头
    has_cc = bool(cc)
    if has_cc:
        lines.append(
            "| Task | Category | Mini | CC | Mini Tokens | CC Tokens "
            "| Mini Cost | CC Cost | Mini Tools | Time |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
    else:
        lines.append(
            "| Task | Category | Result | Runs | Tokens | Cost | Tools "
            "| Iterations | Time | TTFT p95 |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|---|")

    # Rows 行
    total_mini_tokens = 0
    total_mini_cost = 0.0
    total_mini_tools = 0
    mini_pass = 0
    cc_pass = 0

    for r in mini:
        name = r.get("task", "?")
        category = r.get("category", "")
        m_ok = "✅" if r.get("success") else "❌"
        m_tokens = r.get("tokens", 0)
        m_cost = r.get("cost_usd", 0)
        m_tools = r.get("tool_calls", 0)
        m_iters = r.get("iterations", 0)
        m_time = f"{r.get('elapsed_seconds', 0)}s"

        total_mini_tokens += m_tokens
        total_mini_cost += m_cost
        total_mini_tools += m_tools
        if r.get("success"):
            mini_pass += 1

        if has_cc:
            cr = cc.get(name, {})
            c_ok = "✅" if cr.get("success") else ("❌" if cr else "-")
            c_tokens = cr.get("tokens", "-")
            c_cost = f"${cr.get('cost_usd', 0):.4f}" if cr.get("cost_usd") else "-"
            if cr.get("success"):
                cc_pass += 1
            lines.append(
                f"| {name} | {category} | {m_ok} | {c_ok} "
                f"| {m_tokens} | {c_tokens} "
                f"| ${m_cost:.4f} | {c_cost} "
                f"| {m_tools} | {m_time} |"
            )
        else:
            repeat = int(r.get("repeat", 1))
            runs = f"{r.get('successes', 1 if r.get('success') else 0)}/{repeat}"
            ttft = ((r.get("metrics") or {}).get("latency") or {}).get("llm_ttft") or {}
            p95 = f"{ttft['p95']:.0f}ms" if ttft.get("p95") is not None else "-"
            lines.append(
                f"| {name} | {category} | {m_ok} | {runs} "
                f"| {m_tokens} | ${m_cost:.4f} "
                f"| {m_tools} | {m_iters} | {m_time} | {p95} |"
            )

    # Summary row 汇总行
    n = len(mini) or 1
    lines.append("")
    lines.append("## Summary 汇总\n")
    repeats = [int(r.get("repeat", 1)) for r in mini]
    k = max(repeats) if repeats else 1
    label = "passed all runs" if k > 1 else "pass rate"
    lines.append(f"- **Mini {label}**: {mini_pass}/{len(mini)}")
    lines.append(f"- **Total tokens**: {total_mini_tokens}")
    lines.append(f"- **Total cost**: ${total_mini_cost:.4f}")
    lines.append(f"- **Avg tokens/task**: {total_mini_tokens // n}")
    lines.append(f"- **Avg cost/task**: ${total_mini_cost / n:.4f}")
    # Cost per SOLVED task -- a cheap agent that fails is not cheap
    # 每个"解决了的"任务的成本——便宜但做不成的 Agent 并不便宜
    if mini_pass:
        lines.append(f"- **Cost per solved task**: ${total_mini_cost / mini_pass:.4f}")
    lines.append(f"- **Total tool calls**: {total_mini_tools}")

    # Reliability 可靠性
    scored = [r for r in mini if "pass_at_1" in r]
    if scored and k > 1:
        pass_at_1 = sum(float(r["pass_at_1"]) for r in scored) / len(scored)
        pass_k = sum(1 for r in scored if r.get("all_pass")) / len(scored)
        censored = sum(int(r.get("censored_runs", 0)) for r in scored)
        lines.append("")
        lines.append(f"### Reliability 可靠性 (k={k}, {len(scored) * k} runs)\n")
        lines.append(f"- **pass@1**: {pass_at_1:.3f} — mean per-run success rate 单次成功率均值")
        lines.append(f"- **pass^{k}**: {pass_k:.3f} — solved in EVERY run 每次都成功的任务占比")
        if pass_at_1:
            lines.append(
                f"- **rho^{k}**: {pass_k / pass_at_1:.3f} — consistency "
                "(1.0 = fully stable) 一致性比"
            )
        lines.append(
            f"- **Censored runs**: {censored} — hit the iteration cap; "
            "censored samples, not failures on the merits 触顶删失样本，非实力失败"
        )

    # Latency 延迟
    ttfts = [((r.get("metrics") or {}).get("latency") or {}).get("llm_ttft") or {} for r in mini]
    lags = [(r.get("metrics") or {}).get("event_loop_lag") or {} for r in mini]
    ttft_max = [t["max"] for t in ttfts if t.get("max") is not None]
    lag_max = [lg["max"] for lg in lags if lg.get("max") is not None]
    if ttft_max or lag_max:
        lines.append("")
        lines.append("### Latency 延迟（worst across tasks 跨任务最差）\n")
        if ttft_max:
            lines.append(f"- **TTFT max**: {max(ttft_max):.0f}ms")
        if lag_max:
            lines.append(
                f"- **Event-loop lag max**: {max(lag_max):.1f}ms "
                "(>100ms means the loop was blocked >100ms 即事件循环被阻塞)"
            )

    if has_cc:
        total_cc_tokens = sum(cc[r["task"]].get("tokens", 0) for r in mini if r["task"] in cc)
        total_cc_cost = sum(cc[r["task"]].get("cost_usd", 0) for r in mini if r["task"] in cc)
        # Own heading: without it these bullets land under the Latency
        # section above. 独立标题：否则这些条目会落到上面的 Latency 节里。
        lines.append("")
        lines.append("### Claude Code 对照\n")
        lines.append(f"- **CC pass rate**: {cc_pass}/{len(cc)}")
        lines.append(f"- **CC total tokens**: {total_cc_tokens}")
        lines.append(f"- **CC total cost**: ${total_cc_cost:.4f}")
        if total_cc_cost > 0:
            ratio = total_cc_cost / max(total_mini_cost, 0.0001)
            lines.append(f"- **Cost ratio (CC/Mini)**: {ratio:.1f}x")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate benchmark report")
    parser.add_argument(
        "--output", type=str, default=None, help="Write report to file (default: stdout)"
    )
    args = parser.parse_args()

    mini = load_mini_results()
    cc = load_cc_results()

    if not mini:
        print("No results found. Run benchmarks/runner.py first.")
        sys.exit(1)

    report = generate_report(mini, cc)

    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"Report written to {args.output}")
    else:
        print(report)


if __name__ == "__main__":
    main()
