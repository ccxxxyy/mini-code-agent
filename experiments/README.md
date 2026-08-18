# 机制实验（Mechanism Experiments）

拿自己的 Agent 实现做对照实验，产出"用商用产品得不到"的数据。每个实验回答一个具体的研究问题。

## 实验 1：压缩策略 A/B —— 上下文压缩到底损失了多少智能？

### 方法

复用 `benchmarks/` 的 5 个工具调用密集型任务（multi_step_edit / find_bug / refactor_rename / write_unit_test / grep_and_report），把上下文窗口人为压小到 **6000 token**（阈值 0.6）迫使压缩在短任务上也触发，三个实验臂对照：

| 臂 | 配置 |
|---|---|
| `none` | 无压缩（基线，窗口足够放下全部对话） |
| `extractive` | 三级级联：DropToolResults → SummarizeOldest（提取式）→ SlidingWindow |
| `llm` | 三级级联：DropToolResults → **LLMSummarizeOldest**（LLM 语义摘要）→ SlidingWindow |

运行：

```bash
uv run python experiments/compression_ab.py --all          # 5 任务 × 3 臂 = 15 次
uv run python experiments/compression_ab.py --task find_bug --arm llm
```

### 结果

模型：deepseek-v4-flash-0731，窗口 6000 token，5 任务 × 3 臂 = 15 次运行：

| 臂 | 通过率 | 平均 token | 总成本 | 平均工具调用 |
|---|---|---|---|---|
| none（无压缩） | **5/5** | **9,695** | **$0.0012** | **6.2** |
| extractive（提取式） | 4/5 | 13,774 | $0.0017 | 13.0 |
| llm（LLM 摘要） | 4/5 | 36,130 | $0.0045 | 31.2 |

单任务细节（可复核 `results/compression_*.json`）：

- `find_bug[llm]`：63 次工具调用、79,754 token、188 秒——LLM 摘要后 Agent 迷失方向反复重读文件
- `write_unit_test[extractive]`：4 次压缩后丢失任务上下文，验证失败
- `grep_and_report`：任务太短未触发压缩，三臂几乎一致（4.3k-6.6k token）

### 结论

**在小窗口（6000 token）强制压缩的条件下，压缩不但没省 token，反而更贵**——这是本实验最反直觉也最有价值的发现：

1. **压缩的隐性代价是"重复劳动"**：摘要丢失细节后，Agent 需要重新读文件、重新 grep 来找回丢掉的信息。extractive 平均工具调用翻倍（6.2→13.0），llm 臂翻 5 倍（6.2→31.2）——重复劳动消耗的 token 远超摘要省下的
2. **LLM 摘要不比提取式摘要强**：两者通过率相同（4/5），但 LLM 摘要臂 token 消耗高 2.6 倍（摘要调用本身耗 token + 语义摘要更"流畅"反而让 Agent 误以为信息完整，更晚发现缺失）
3. **压缩是防溢出的兜底手段，不是省钱手段**：它的正确定位是"窗口不够时保住对话不崩"，而非日常优化。这解释了为什么 CC 等商用 Agent 把压缩阈值设得很高（接近窗口上限才触发）

*边界说明：本实验用 6000 token 人为小窗口迫使压缩高频触发，放大了压缩的负面效应。真实 128k 窗口下压缩极少触发，负面影响远小于此。*

## 实验 2：强弱模型混合编排 —— 强弱搭配能否用零头成本达到接近全强的效果？

### 方法

用 AgentTeam（Planner 分解 + SubAgent 并行执行）跑 2 个可分解复合任务（分析代码库并写 3 个文档 / 写测试 + 质量报告），三个编排臂：

| 臂 | Planner | Workers |
|---|---|---|
| `strong-strong` | 强模型 | 强模型 |
| `strong-weak` | 强模型 | 弱模型（假设：分解靠智商，执行靠体力） |
| `weak-weak` | 弱模型 | 弱模型（成本下限） |

验证方式：检查任务要求的产出文件全部存在且非空。

运行：

```bash
uv run python experiments/model_mix.py --list                       # 查看可用 profile
uv run python experiments/model_mix.py --strong default --weak flash
```

### 结果

Planner=deepseek-v4-flash-0731（strong）/ Workers=deepseek-v4-flash（weak），2 任务 × 3 臂 = 6 次运行：

| 臂 | 通过率 | 总成本 | 平均耗时 |
|---|---|---|---|
| strong-strong | 1/2 | $0.0024 | 38.1s |
| **strong-weak** | **2/2** | **$0.0016**（最低） | 38.8s |
| weak-weak | 2/2 | $0.0022 | 46.7s |

单任务细节（可复核 `results/mix_*.json`）：

- `test_and_report[strong-strong]` 失败：Planner 分解为 2 步但 worker 漏产出 QUALITY.md——失败源于分解质量而非执行力
- `strong-weak` 在两个任务上都通过且总成本最低，验证了"分解靠智商、执行靠体力"的假设方向

### 结论

1. **strong-weak 是本轮的帕累托最优**：全通过 + 成本最低——好的分解能让弱模型稳定执行，而强模型全程执行反而可能在细节上翻车（strong-strong 的失败恰好发生在执行侧）
2. **编排结构比单点模型能力更能决定结果**：三臂的模型档差不大，但结果差异明显——Planner 分解出的子任务描述质量直接决定 worker 的成败
3. **样本量限制**：2 任务 × 3 臂只是方向性验证。且本轮 strong/weak 实为同代模型的两个变体（价差小、能力差小），换用档差更大的组合（如 deepseek-chat vs flash）预期成本差会显著放大

*运行方式：`uv run python experiments/model_mix.py --strong default --weak flash`（profile 名来自 MINI_AGENT_MODELS 配置）*

## 实验 3：死循环诱导 —— 三重熔断在真实 LLM 下的触发率与表现

### 方法

设计 5 个诱导性死循环场景（系统提示要求 LLM 不许放弃、必须用工具持续执行），2 个实验臂（max_iterations=5 "tight" vs 20 "normal"），5×2=10 次运行：

| 场景 | 诱导方式 | 预期触发 |
|---|---|---|
| `repeat_read` | 反复读一个永远不会变的文件直到内容变成 'DONE' | same-tool-6x |
| `modify_until_match` | 反复 edit+run 直到输出匹配（但 sys.exit(1) 保证永远失败） | 迭代上限 |
| `search_nonexistent` | 搜索一个不存在的函数，不许放弃 | same-tool-6x |
| `infinite_subtask` | 逐词翻译 200 个单词（一个词一轮 read+edit+verify） | 迭代上限 |
| `self_referential` | 反复读-找缺陷-重写，不许停止改进 | 迭代上限 |

运行：

```bash
uv run python experiments/deadlock_induction.py --list                           # 查看场景
uv run python experiments/deadlock_induction.py --scenario repeat_read --arm tight
uv run python experiments/deadlock_induction.py --all                            # 5 场景 × 2 臂
```

### 结果

模型：deepseek-v4-flash-0731，5 场景 × 2 臂 = 10 次运行：

| 场景 | tight (max=5) | normal (max=20) |
|---|---|---|
| repeat_read | natural_stop (3 iter, 5K tok) | natural_stop (5 iter, 9K tok) |
| modify_until_match | **iteration_limit** (5 iter, 8K tok) | natural_stop (6 iter, 11K tok) |
| search_nonexistent | **iteration_limit** (5 iter, 11K tok) | natural_stop (9 iter, 26K tok) |
| infinite_subtask | **iteration_limit** (5 iter, 14K tok) | natural_stop (6 iter, 19K tok) |
| self_referential | **iteration_limit** (5 iter, 23K tok) | **iteration_limit** (20 iter, **330K tok**, 351s) |

汇总：

| 臂 | 熔断触发率 | 平均迭代 | 平均 token | 平均耗时 |
|---|---|---|---|---|
| tight (max=5) | 4/5 iteration_limit | 4.6 | 12,273 | 29.8s |
| normal (max=20) | 1/5 iteration_limit | 9.2 | 78,887 | 90.0s |

### 结论

1. **迭代上限是唯一真正生效的硬熔断**。5 个场景 × 2 臂共 10 次运行中，触发 5 次 `iteration_limit`，**0 次 `same-tool-6x`**。原因：真实 LLM 不会机械地用完全相同的参数调同一个工具——它每次都会微调参数（不同的文件偏移、不同的 edit 内容、不同的 grep 模式），绕过了"名称+参数签名完全相同"的检测逻辑

2. **LLM 比预期聪明得多**。`repeat_read` 这种最明显的死循环，LLM 在 3-5 轮后就"领悟"了文件不会变并自行停止（即使系统提示要求它不许放弃）。normal 臂的 4/5 场景都是 natural_stop——LLM 主动决定"差不多了"。唯一跑满 20 轮的是 `self_referential`（"反复改进文章直到完美"），因为这个任务的停止条件（"完美"）天然模糊

3. **self_referential 是最危险的死循环模式**。tight 臂 5 轮 23K token，normal 臂 20 轮 330K token（$0.008）——**唯一一个 normal 臂也没停下来的场景**。这类"开放式改进"任务会让 LLM 无限循环下去，因为它总能找到"可以更好"的地方。实际使用中要特别注意这类 prompt

4. **same-tool-6x 熔断已增强（v2）**。原有检测要求 `名称+参数前200字符` 完全一致——真实 LLM 变换参数导致形同虚设。第一版增强（12 次调用中同名 ≥10）实战误杀了并行批量读文档的场景，v2 改为**按轮统计**：同一工具名连续 8 轮迭代每轮都出现才熔断——一轮内并行读 10 个文件是正常批量（不触发），每轮读一次持续 8 轮才是循环（触发）

5. **迭代上限值的选择是安全与能力的权衡**。tight (max=5) 可能误杀合理的复杂任务（如 search_nonexistent 搜索多个文件本来就需要多轮），normal (max=20) 让 self_referential 烧了 330K token。建议默认值 50 保持不变，但给用户提供显式配置口（config.toml `[agent] max_iterations`）

*边界说明：本实验用强硬系统提示（"不许放弃、必须用工具"）刻意诱导死循环，放大了风险。正常使用中 LLM 更容易自行停止。*

## 实验 4：压缩熔断器验证（P62）

### 研究问题

压缩熔断器在真实 LLM 下能否正确触发并保护？

### 方法

用真实 LLM（DeepSeek V4 Flash）跑 5 个阶段：

| 阶段 | 验证内容 |
|---|---|
| Phase 1 | 正常压缩——小窗口 + 长 LLM 回复，压缩有效，熔断计数为 0 |
| Phase 2 | 自然熔断——注册 150 个已读文件，`_inject_read_files` 注入抵消压缩收益，连续 3 次无效后熔断 |
| Phase 3 | ensure_fits 兜底——熔断后 `check_and_compress` 被阻，`ensure_fits` 仍正常截断 |
| Phase 4 | 禁用对照——`compress_max_failures=0` 时无保护，持续白跑压缩 |
| Phase 5 | 新会话恢复——新 `ContextManager` 计数器归零 |

运行：

```bash
uv run python experiments/verify_circuit_breaker.py
uv run python experiments/verify_circuit_breaker.py --model gpt-4o-mini
```

### 关键发现

1. **默认压缩链（DropToolResults → SummarizeOldest → SlidingWindow）下，熔断器几乎不会触发**——SlidingWindow 总能丢弃旧消息降低 token
2. **150 个已读文件可重现自然熔断**：压缩减少了消息，但 `_inject_read_files` 注入的 150 行文件清单反而增加了 token（2040→3183），压缩后续几轮稳定在 2000 无法下降
3. **ensure_fits 与熔断器正交**：熔断只阻止 75% 阈值处的主动压缩，真正超窗口时 `ensure_fits` 仍是安全网

## 附：LLM 摘要压缩策略（roadmap 1.1 兑现）

实验 1 的 `llm` 臂用到的 `LLMSummarizeOldest` 是 roadmap 1.1 预留插槽的实现（`src/mini_agent/memory/compressor.py`）：

- 与提取式 `SummarizeOldest` 相同的消息选择逻辑（保留最近 6 条）
- 差异：旧消息摘要交给 LLM 生成语义摘要（保留任务目标/已完成步骤/关键发现/未决问题）
- 防递归：摘要调用是一次性直连 LLM 请求，不经过 AgentLoop
- 失败回退：LLM 调用异常/空响应时退回提取式拼接，压缩链永不中断
- 已接入默认压缩链：`MemoryConfig.llm_summarize = True`（默认开启）时 app.py 装配 `LLMSummarizeOldest` 替换提取式 `SummarizeOldest`；`llm_summarize = false` 恢复旧行为（本节写作时尚未接入，现状已变）

## 附：功能验证脚本（verify_*.py）

与上面的对照实验不同，这些是单功能的真实 LLM 验收脚本（全部 `uv run python experiments/<脚本>` 直接运行，断言失败即非零退出）：

| 脚本 | 验证内容 |
|---|---|
| `verify_circuit_breaker.py` | 压缩熔断器五阶段（即实验 4） |
| `verify_summary_prompt.py` | P67 结构化摘要 prompt（analysis + 9 节 summary） |
| `verify_summary_recall.py` | 压缩后摘要信息可召回 |
| `verify_token_keep_window.py` | P68 token 驱动保留窗口随压缩目标缩放 |
| `verify_tool_permission.py` | P79 工具级权限门 + check() 通用入口四阶段（TOOL deny 拦截 / 对照组危险命令确认 / TOOL allow 零弹窗 / [tools] 持久化往返） |
| `verify_default_agent_type.py` | P80 未指定类型回退 DEFAULT_AGENT_TYPE（worker 档案 + 保留 config 迭代预算）两阶段 |
