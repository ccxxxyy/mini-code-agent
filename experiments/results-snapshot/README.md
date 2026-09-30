# Compression A/B Snapshot 压缩策略对照实验快照

Raw results from one committed run of `experiments/compression_ab.py`. Committed for the
same reason as `benchmarks/results-snapshot/`: re-running costs real LLM calls and, because
generation is non-deterministic, produces different numbers.

`experiments/compression_ab.py` 一次运行的原始结果。提交理由同 `benchmarks/results-snapshot/`：
重跑需真实 LLM 调用、生成非确定性、数字不可复现。

（`experiments/verify_loop_block.py` 的结果**不**快照——那个实验不调 LLM、无花费、1 分钟可跑完，
脚本本身即凭证。只有"重跑要花钱且结果不可复现"的产物才需要留档。）

## Provenance 溯源

| 项 | 值 |
|---|---|
| 快照日期 | 2026-09-30 |
| 模型 | `deepseek-v4-flash-0731`（与 `benchmarks/` 同一模型，可比） |
| 设计 | 5 任务 × 3 臂 × 3 次重复 = **45 次运行** |
| 强制上下文窗口 | 6,000 token（阈值 0.6）——真实窗口 128k 下这些短任务永不触发压缩 |
| 三臂 | `none`（不压缩）/ `extractive`（`DropToolResults` + `SummarizeOldest` + `SlidingWindow`）/ `llm`（`DropToolResults` + `LLMSummarizeOldest` + `SlidingWindow`） |
| 总花费 | $0.025 |

## Headline 结论

**1. 成功率零区分度：45/45 全过，三臂各 15/15。** 在这个任务规模上，压缩不会把任务做坏——所以
**成功率这一列不承载任何信息**，必须看 token。

**2. 只有 2/5 个任务的 token 差值可分辨。** 判据是**轮次是否跨重复恒定**：

| 任务 | `none` 臂轮次 | 测量 | extractive | llm |
|---|---|---|---|---|
| `find_bug` | [4,4,4] 恒定 | ✅ 可分辨 | **+5.6%** | **+4.2%** |
| `multi_step_edit` | [5,5,5] 恒定 | ✅ 可分辨 | **+7.0%** | **+8.1%** |
| `grep_and_report` | [4,5,6] 抖动 | ❌ 被淹没 | (−21.4%) | (−18.4%) |
| `refactor_rename` | [5,5,6] 抖动 | ❌ 被淹没 | (+1.7%) | (+1.8%) |
| `write_unit_test` | [6,6,10] 抖动 | ❌ 被淹没 | (+7.2%) | (−40.9%) |

**在两个干净任务上，两种压缩都一致地更贵（+4.2% ~ +8.1%）。** 机理：每次运行只触发约 1 次压缩
（`compressed_messages` 中位恒为 1），摘要自身的 token 成本没有足够的后续轮次去摊薄。

**这为"压缩比是错的指标"提供了实测数据**——正确指标是**完成任务的总 token 数（含摘要自身消耗）**，
而按这个口径，此处的压缩是净亏的。

**3. 污染层的方差来源已定位：Agent 轮次的不确定性，不是压缩。**
全 45 次每轮平均约 **4,313 token**，轮次中位 5。`write_unit_test [none]` 偶发跑到 10 轮
（三次为 [6,6,10]，token [26816, 31381, 59760]，格内极差 **32,944 = 中位的 105%**），
一次多跑 4 轮就多烧 17k+ token，而压缩效应只有 1k 量级。**格内极差 > 臂间差值 ⇒ 不可下结论。**

**4. 聚合头条数字不可报。** 脚本聚合表给出 `llm −14.0%`，但同一臂的符号跨任务变号
（extractive −21.4%~+7.2%，llm −40.9%~+8.1%），脚本自己打印了告警：

```
[!] arm 'llm' token delta changes sign across tasks (-40.9% .. +8.1%)
    -- the aggregate median is not a summary of a single effect.
```

**符号不一致的中位数不是任何单一效应的摘要。**

## Open hypothesis 待验证假设（n=3 不足以支持，勿当结论）

在 `write_unit_test` 和 `grep_and_report` 上，压缩臂的轮次**严格更低且更稳**：

| 任务 | none 轮次 | extractive | llm |
|---|---|---|---|
| `grep_and_report` | [4,5,6] | [4,4,4] | [4,4,4] |
| `write_unit_test` | [6,6,10] | [4,7,11] | [4,4,6] |

`write_unit_test` 的 llm 臂即便**去掉 `none` 臂那次 10 轮离群**后仍低 36.3%，所以这不是离群假象。
两个互斥解释，本实验分不开：
- **压缩确实有益**——丢掉陈旧工具结果减少了干扰，Agent 更快收敛
- **任务验证太弱**——压缩臂工具调用数也下降（7→6、6→4），做的事更少却仍然通过，说明
  `verify_command` 没能检出信息损失

要分开需要：提高 n、并给任务加**能检出"少做了事"的断言**。

## Known artefact 已知实现问题

`llm` 臂运行时观测到压缩熔断器触发：

```
Compression circuit breaker open: 3 consecutive ineffective attempts,
skipping further compression this session.
```

在 6,000 token 的极小窗口下，LLM 摘要连续三次未能有效降低 token 数即触发熔断，后续压缩被跳过。
这意味着 `llm` 臂在部分运行里**实际退化成了近似 `none` 臂**，会把臂间差值向 0 压缩。
真实窗口（128k）下不会这么快触发。**这是本实验操纵强度弱的第二个原因。**

## Files 文件

- `compression_ab_combined.json` — 全 15 格聚合 + 每格 `runs[]` 逐次明细（推荐从这个读）
- `compression_<arm>_<task>.json` — 逐格结果

## Regenerate 重新生成

```bash
uv run python experiments/compression_ab.py --all --repeat 3
```
