# Control-Arm Snapshot: qwen-turbo 弱模型对照组快照

Same 16 tasks, same harness, same `--repeat 3` as `../results-snapshot/` — only the model
differs. This arm exists to answer one question the baseline could not: **does the eval
set discriminate at all, or are the tasks trivially passable?**

与 `../results-snapshot/` 同样的 16 个任务、同一套 harness、同样 `--repeat 3`，**只换模型**。
这一臂存在的唯一目的，是回答基线无法回答的问题：**这套评测集究竟有没有区分度，还是任务本身
随便就能过？**

## Provenance 溯源

| 项 | 值 |
|---|---|
| 快照日期 | 2026-09-30 |
| 模型 | `qwen-turbo`（基线是 `deepseek-v4-flash-0731`） |
| 设计 | 16 任务 × 3 次 = **48 次运行** |
| 命令 | `uv run python benchmarks/runner.py --all --repeat 3 --model qwen-turbo --results-dir benchmarks/results-qwen-turbo` |

## Headline：评测集有区分度，之前只是被强模型饱和了

| 指标 | 基线 `deepseek-v4-flash-0731` | 对照 `qwen-turbo` |
|---|---|---|
| 运行通过 | 48/48 | **38/48** |
| **pass@1** | 1.000 | **0.792** |
| **pass^3** | 1.000 | **0.750** |
| 任务全过 | 16/16 | **12/16** |
| 删失运行 | 0 | **2** |

**0.792 正落在有信息量的区间。** 不是 100%（说明不了上限），也不是 0%（说明不了能力），
而是失败集中在可识别的任务子集上——这才是可以去聚类分析的数据。

**所以先前"评测集没有区分度"这个结论是错的**，正确表述是：**评测集在
`deepseek-v4-flash` 这个能力档位上饱和，换到 `qwen-turbo` 档位就分得开。** 任务不是太简单，
是对那个模型太简单。

## 失败是有结构的，不是随机的

| 任务 | 基线 | 对照 | 逐次 (成功, 轮次, 触顶) | cap |
|---|---|---|---|---|
| `three_bugs` | 3/3 | **0/3** | (F,4,–) (F,6,–) (F,6,–) | 30 |
| `multi_step_edit` | 3/3 | **0/3** | (F,3,–) (F,4,–) (F,8,–) | 20 |
| `write_unit_test` | 3/3 | **0/3** | (F,22,**触顶**) (F,13,–) (F,20,**触顶**) | 20 |
| `infer_convention` | 3/3 | **2/3** | (T,5,–) (T,4,–) (F,15,–) | 25 |
| 其余 12 个任务 | 3/3 | 3/3 | — | — |

四个失败任务里三个是最难的（三处独立 bug、多步编辑、写单测），说明**难度排序是有效的**。

## 三件"机制做了但一直没被真实数据检验"的东西，这次全部生效

**① pass^k 的指数衰减第一次真的显现。** 基线 pass^3 = pass@1 = 1.000（全过时两者恒等，
看不出差别）。对照组 **pass^3 = 0.750 < pass@1 = 0.792**，差距来自 `infer_convention` 的 2/3
——一个"**不稳，而非不能**"的任务。这正是 pass^k 要暴露的东西：单次成功率会把它算作 0.667 的
部分功劳，而 pass^3 直接判它不可靠。

**② 删失机制第一次有了真实样本。** 基线删失 0，对照组 **2 次**，都在 `write_unit_test`：
三次失败中 **(22 轮, 触顶)** 和 **(20 轮, 触顶)** 是**删失**——观测被 `max_iterations=20` 截断，
而 **(13 轮, 未触顶)** 是**真实失败**。这两类**不能混进同一个均值**：删失样本本来还要继续烧
token，把它当自然失败会把成本算低。不记录 `caps` 和 `hit_iteration_cap` 就无法做这个区分。

**③ "每成功任务成本"的分母效应第一次可量化。**

| 口径 | 基线 | 对照 |
|---|---|---|
| 总成本 ÷ 任务数（16） | $0.0005 | $0.0236 |
| 总成本 ÷ **全过任务数** | $0.0005 | **$0.0315** |

基线两个口径相同（16/16 全过），对照组差 **33%**。用错分母就会系统性低报成本——这是
SWE-Bench+ 那篇的论点（某方案 $0.24/实例 但 $32.5/成功修复）在本项目自己数据上的复现。

> ⚠️ **成本是名义值，不是真实报价。** `qwen-turbo` 不在 `runner.py` 的 `PRICE_TABLE` 里，
> 落到 `default` 占位价（$1.00/1M）。**跨模型的成本绝对值不可比**；可用的是**同一模型内
> 两个分母之间的 33% 差距**这个结构性结论。

## 一个附带观测

探路阶段用 `qwen3-8b` 跑 `create_file` 时测到 **loop lag 198.7ms**，越过了 100ms 告警线
（基线 16 任务跨任务 max 是 65.1ms）。未做重复验证，仅登记，不作结论。

## 诚实边界

- **弱模型不是越弱越好**：`qwen2.5-1.5b-instruct` 连最简单的 `create_file` 都 0% 通过——
  全 0 和全 1 一样没有信息量。`qwen-turbo` 能落在 0.792 是挑出来的结果，不是随手换的。
- 本快照是 **n=3**。`infer_convention` 的 2/3 到底是 0.667 的真实成功率还是采样噪声，
  n=3 分不开。
- 这一臂**只换了模型**，没有改任务、prompt 或 harness，所以差异可归因到模型能力。

## Regenerate 重新生成

```bash
uv run python benchmarks/runner.py --all --repeat 3 --model qwen-turbo \
  --results-dir benchmarks/results-qwen-turbo
```

`--results-dir` 是必须的：结果文件只按任务名命名，不分目录会**静默覆盖基线**
（这个坑实际踩过，靠 `../results-snapshot/` 才恢复）。
