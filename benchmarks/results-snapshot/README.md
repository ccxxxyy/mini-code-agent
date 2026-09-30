# Benchmark Results Snapshot 评测结果快照

Raw per-task JSON from one committed benchmark run, kept here so the evidence is
reviewable without re-running the suite (a re-run costs real LLM calls and, because
generation is non-deterministic, produces different numbers).

本目录是一次评测运行的逐任务原始 JSON。提交它的原因是：重跑需要真实 LLM 调用，
且生成非确定性、数字不可复现，所以证据必须留档而不是"随时重跑"。

`benchmarks/results/` (the live output directory) stays git-ignored so re-runs don't
dirty the working tree. This snapshot is the committed copy.

`benchmarks/results/`（运行时输出目录）保持 git-ignored，避免重跑污染工作区；
本目录是提交版副本。

## Provenance 溯源

| 项 | 值 |
|---|---|
| 快照日期 Snapshot date | 2026-09-30 |
| 提交 Commit | `ed7e855` (branch `dev`) |
| 模型 Model | `deepseek-v4-flash-0731` |
| 任务数 Tasks | 16 |
| 每任务重复 Repeats per task | 3 (`--repeat 3`) |
| 总运行数 Total runs | 48 |
| 平台 Platform | win32, Python 3.11.15, pytest 9.1.1 |

## How success is decided 成功如何判定

Not an LLM score. Each task ships a pytest assertion; the task counts as solved only
when that suite passes after the agent's edits. The raw pytest output is stored in the
`verify_output` field of every JSON, so the judgement is auditable.

不是 LLM 打分。每个任务自带 pytest 断言，只有 Agent 改完后测试通过才算成功。
每个 JSON 的 `verify_output` 字段存有 pytest 原始输出，判定过程可审计。

`benchmarks/validate_tasks.py` separately proves each task is *discriminative* — that it
fails before the fix and passes after. Without that check a 100% pass rate could just
mean the tasks were already green.

`benchmarks/validate_tasks.py` 另行证明每个任务**有区分力**——未修改时必失败、修复后必通过。
没有这一步，100% 通过率可能只是因为任务本身就是绿的。

## Fields worth reading 值得看的字段

| 字段 | 含义 |
|---|---|
| `runs[]` | Per-repeat detail 逐次明细（success / tokens / iterations / elapsed / hit_iteration_cap） |
| `tool_names` | Full tool-call sequence 完整工具调用序列 |
| `verify_output` | Raw pytest output 判定用的 pytest 原始输出 |
| `caps` | Limits in force 生效上限（`max_iterations` 20/25/30 按任务难度分档，`verify_timeout_seconds` 30） |
| `censored_runs` | Runs that hit the iteration cap 触顶删失的运行数（本轮全部为 0） |
| `metrics` | Full percentile snapshot 全量百分位快照（TTFT / stream duration / per-tool latency / event-loop lag） |
| `pass_at_1`, `all_pass` | Reliability 可靠性（pass@1 / pass^k） |

## Aggregates 聚合

- 48/48 runs succeeded; **pass@1 = 1.000, pass^3 = 1.000, rho^3 = 1.000**
- **Censored runs = 0** — no task exhausted its iteration budget, so the averages carry
  no censoring bias 无任务耗尽迭代预算，故均值无删失偏差
- Iterations actually used: 2–9 (median 4) against caps of 20–30 — large headroom
  实际用到 2–9 轮（中位 4），上限 20–30，余量很大
- Tokens: **334,985 over the 16 representative runs** / **974,714 over all 48 runs**
  — two different denominators, do not conflate 两个分母不同，不要混用
- Cost: $0.008374 over the 16 representative runs, $0.000523 per task

## Honest limitation 诚实边界

**48/48 means the metric is saturated at this model's capability tier** — it does NOT
mean the tasks are trivial. Six structurally harder tasks were added on purpose
(cross-file root cause, stacked discounts, 724-line file navigation, convention
inference, three independent bugs, implementation inferred from tests) and all six
passed 3/3, so raising difficulty did not help. A metric only carries information in the
95–99% band; 100% says "this setup works", not "here is the capability ceiling".

**48/48 说明指标在这个模型的能力档位上饱和了**——**不**说明任务过于简单。专门新增的 6 个
结构性更难的任务全部 3/3 通过，所以加难度这条路没走通。只有落在 95–99% 区间的指标才有
信息量；100% 只说明"这个模式能用"，不说明能力上限在哪。

> ⚠️ **This paragraph originally read "this suite has no discriminating power left".
> That conclusion was wrong** — it rested on a single model. A weak-model control arm
> (`../results-snapshot-qwen-turbo/`, same 16 tasks, same harness, same `--repeat 3`,
> only `qwen-turbo` instead) scored **pass@1 = 0.792 / pass^3 = 0.750 / 2 censored runs**
> with failures concentrated in four tasks, three of which are the hardest by design.
> **The suite does discriminate; it was the metric that had saturated.** See
> `docs/tech-notes.md` §137.
>
> ⚠️ **本段原先写的是「这套评测集已经没有区分度」，那个结论是错的**——它只基于一个模型。
> 弱模型对照组（`../results-snapshot-qwen-turbo/`，同样 16 任务、同一 harness、同样
> `--repeat 3`，只把模型换成 `qwen-turbo`）跑出 **pass@1 = 0.792 / pass^3 = 0.750 /
> 2 次删失**，失败集中在四个任务、其中三个是设计时难度最高的。**评测集是分得开的，
> 饱和的是指标。** 详见 `docs/tech-notes.md` §137。

Next steps: raise task scale to real-repository level (the weak-model control arm is done).
下一步：把任务提升到真实仓库级别（弱模型对照组已完成）。

## Regenerate 重新生成

```bash
uv run python benchmarks/runner.py --all --repeat 3
uv run python benchmarks/report.py --output benchmarks/README.md
```
