# 代码质量待做清单

已修复的问题标 ✅，待修复的标 ☐。

## ✅ 已修复

- ✅ `openai_provider.py` `count_tokens` 绕过 `token_counter` 模块（直接 `len//4`）→ 改为调用 `token_counter.count_tokens()`
- ✅ `anthropic_provider.py` `count_tokens` 同上问题 → 同上修复
- ✅ `models/message.py` `__import__("json")` 反模式 → 改为模块顶部 `import json`

## ☐ 中优先级

### ✅ markdown 围栏剥离三处重复
- `memory/extraction.py:140`
- `memory/recall.py:83`
- `memory/consolidation.py:103`

三处都在做同样的 strip ` ```json ... ``` ` 逻辑。✅ 已抽取为 `memory/_utils.py` 的 `strip_json_fence(text) -> str` 函数。

### LLM 流式调用+组装四处重复
- `memory/extraction.py:125` — 提取记忆
- `memory/recall.py:61` — 选择性召回
- `memory/consolidation.py:53` — 语义合并
- `memory/compressor.py:164` — LLM 摘要压缩

四处都是"流式调 LLM → 拼接文本 → 解析 JSON"的相同模式。建议抽取为：
```python
async def llm_json_call(llm, messages, fallback=None) -> dict | None
```

## ☐ 低优先级

### shell 检测逻辑重复
- `app.py:112` 和 `subagent.py:144` 各自 `os.environ.get("SHELL")` 判断 shell 类型
- 建议抽取到 `config/` 或 `utils.py`

### `os.environ` 直接访问绕过 config
- 同上两处直接读环境变量而非通过 ConfigLoader
- 对测试隔离有影响

### 权限检查逻辑内部重复
- `permission.py:156-193`（`check()`）和 `permission.py:266-285`（`_check_rules_only()`）
- 规则匹配遍历逻辑相似，可收敛为一个统一的规则解析器

### 路径 resolve 重复
- `security/sandbox/seatbelt.py:42,45` 和 `security/sandbox/bwrap.py:30,33`
- 沙箱模块各自做 `Path(path).resolve()`，PathGuard 已做过
- 建议从 PathGuard 传入已解析路径，或抽取路径规范化函数

### 静默 except（约 27 处）
- 大部分是有意的 fail-safe（记忆提取/召回/合并失败不阻断主流程）
- 建议为关键路径（hook/autosave）加日志，保留降级但可观测

---

## ☐ 死代码清理（27 处）

27 处死代码分为三类：**真正遗忘应接入的**（6 处）、**设计变更后的残留物**（5 处）、**有意预留的扩展点**（16 处）。

---

### 🔴 真正遗忘、应该接入（6 处）

这些是开发过程中写好但忘记接入的代码，属于 bug 或疏忽，建议优先修复。

| # | 项 | 位置 | 问题分析 | 修复建议 |
|---|---|---|---|---|
| 1 | `LLMResponse.model` | `llm/base.py:51` | 两个 Provider 组装响应时忘了赋值，导致成本归属靠 `agent_loop.model_name` 间接补偿，如果切换模型可能归属错误 | 在 `openai_provider.py` 和 `anthropic_provider.py` 的 `assemble_response` 中设置 `response.model = self._config.model` |
| 2 | `TokenUsage.cache_read_input_tokens` | `llm/base.py:28-29` | Provider 费力解析了 Anthropic/OpenAI 返回的缓存 token 数，但 CostTracker 完全没用这两个字段，缓存命中不影响计费——实际 API 计费中缓存 token 价格不同，不接入会导致成本估算偏高 | CostTracker 读取这两个字段，按供应商的缓存价格折算 |
| 3 | `AgentConfig.enable_plan_mode` | `models/config.py:145` | config.toml 有 `enable_plan_mode` 开关但 `/plan` 命令直接改 `agent_loop.plan_mode`，启动时没读这个配置——用户在 config 里设了 `enable_plan_mode = false` 毫无效果 | `app.py` 初始化时 `agent_loop.plan_mode = config.enable_plan_mode` |
| 4 | `on_thinking_delta` 终端未接入 | `core/agent_loop.py:137` | remote 模式接了，终端模式漏了——DeepSeek R1 等模型的 `reasoning_content` 在终端静默丢弃，用户看不到思考过程 | `app.py` 回调中接入 `on_thinking_delta`，用 dim 样式输出到终端 |
| 5 | `PermissionRequest.matched_rule` | `models/permissions.py:41` | 4 处赋值（`permission.py:168,176,272,278`）但从没被读过，本意应该是审计日志输出匹配的规则方便调试，但 AuditLogger 没取这个字段 | AuditLogger 记录时附上 `matched_rule`，或删掉赋值 |
| 6 | `count_message_tokens()` / `count_messages_tokens()` | `llm/token_counter.py:82,109` | 写了完整的按消息角色（system/user/assistant/tool）分别计 token 的逻辑（含角色标记开销），但 ContextManager 用了 `count_tokens(text)` 简化版，精确版被遗忘。两个函数形成死调用链（109 调 82，无外部调用方） | 要么 ContextManager 改用精确版，要么删掉这两个函数 |

---

### 🟡 设计变更后的残留物（5 处）

这些代码在早期设计中有用途，后来方案改了但旧代码没清理。建议删除以减少混淆。

| # | 项 | 位置 | 历史原因 |
|---|---|---|---|
| 1 | `LLMStreamChunkEvent` | `models/events.py:38` | 最初打算流式事件走 EventBus（订阅者处理渲染），后来改成直接回调（`on_stream_delta`）更高效，事件类留着没删 |
| 2 | `LLMErrorEvent` | `models/events.py:55` | 同上，LLM 错误最终走 `try/except` 异常链不走事件总线，事件类成为残留 |
| 3 | `ToolFilter` + `ToolFilterContext` | `security/tool_filter.py` | 早期设计的工具过滤方案（按上下文动态过滤），后来 SubAgent 用 `registry.unregister()` + `clone()` 替代，整个模块成为死代码 |
| 4 | `AgentState.pending_tool_calls` | `core/agent_state.py:28` | 早期设计用于跟踪待执行工具，后来流式执行改用 `_streaming_tasks` dict 管理，旧字段没删 |
| 5 | 5 个异常类 | `core/errors.py:4-29` | 早期定义了 `AgentError/LLMError/ToolError/MaxIterationsError/UserCancelledError` 异常体系，实际开发中全用 `Exception` + `ToolResult(is_error=True)` 替代，异常类从未迁移使用 |

---

### 🟢 有意预留的扩展点（16 处）

这些是公开 API 表面，当前无调用方但为外部消费者或未来功能预留。除非要精简代码量，否则建议保留。

| # | 项 | 位置 | 预留用途 |
|---|---|---|---|
| 1 | `EventBus.on_any()` | `events/bus.py:25` | 全局事件监听——外部插件可监听所有事件做统计/调试 |
| 2 | `ToolRegistry.filter()` | `tools/base.py:212` | 按 allow/deny 列表过滤工具——未来权限系统可能用 |
| 3 | `PermissionManager.add_rule()` | `security/permission.py:94` | 运行时动态添加权限规则——未来 UI 或 API 可能用 |
| 4 | `ProviderRegistry.list_providers()` | `llm/registry.py:27` | 列出所有已注册 Provider——`/model` 命令增强时可能用 |
| 5 | `Conversation.slice_window()` | `models/message.py:105` | 按 token 窗口截取消息——ContextManager 替代了但方法本身有独立价值 |
| 6 | `Plan.is_complete` | `core/planner.py:74` | 检查计划是否完成——AgentTeam 用自己的逻辑但外部调用者可能需要 |
| 7 | `HookAction.CONFIRM` | `tools/hooks.py:32` | Hook 返回"需要用户确认"——未来交互式 hook 可能用 |
| 8 | `PermissionDecision.PENDING` | `models/permissions.py:24` | 异步权限判定的中间状态 |
| 9 | `PermissionScope.TOOL` | `models/permissions.py:16` | 工具级权限控制（当前只有 COMMAND 和 PATH） |
| 10 | `DEFAULT_AGENT_TYPE` | `core/agent_types.py:128` | 默认 Agent 类型常量——应在 `SubAgent.__init__` 中引用但实际用了 `None` |
| 11 | `SessionMetadata.tags` | `models/session.py:22` | 会话标签——未来 `/session` 增强时可能用 |
| 12 | `UserMessageEvent.is_slash_command` | `models/events.py:24` | 标记斜杠命令事件——审计/统计可能用 |
| 13 | `LLMRequestEvent.estimated_tokens` | `models/events.py:34` | 预估 token 数——CostTracker 预警可能用 |
| 14 | `PermissionRequest.tool_name` | `models/permissions.py:39` | 触发权限请求的工具名——审计可能用 |
| 15 | `PermissionManager.check()` | `security/permission.py:156` | 通用权限检查入口——当前只被 `check_path` 内部调用，但外部消费者可能直接用 |
| 16 | `Conversation.slice_window()` | `models/message.py:105` | 同 #5（重复列出待确认是否与 ContextManager 有重叠可合并） |

---

## ☐ 文档与仓库卫生

以下问题来自 `analysis-shortcomings.md` 的逐条验证，已确认为真实问题。

### spec.md 与现状脱节（已验证）
- ~~`docs/spec.md` 自修正写"8 个内置工具"~~ ✅ 已修正为 10
- spec.md 目录树列了不存在的 `extensions/plugin_loader.py`
- spec.md 目录树写"6 core tools"——属历史设计文档，已有 disclaimer 说明
- **建议**：统一更新 spec.md 中的工具数量为 10，删除不存在的文件引用，或在文件头明确标注"本文档已归档，不再维护"

### .gitignore 遗漏（已验证）
以下产物目录/文件存在于仓库根目录但未被 .gitignore 覆盖：
- `.coverage` — **已被 git 追踪**（`git ls-files` 可见），应加入 .gitignore 并 `git rm --cached`
- `.pytest_cache/` — 未在 .gitignore 中
- `.ruff_cache/` — 未在 .gitignore 中
- `htmlcov/` — 未在 .gitignore 中
- `experiments/results/` 下的 JSON 文件 — **已被 git 追踪**，应由 .gitignore 排除（benchmarks/results/ 已正确排除，experiments/results/ 漏了）

**建议**：在 .gitignore 追加：
```
.coverage
.pytest_cache/
.ruff_cache/
htmlcov/
experiments/results/
```
然后 `git rm --cached .coverage` 清除已追踪的文件。

### Anthropic Provider 从未 E2E 验证（已验证）
- `docs/checklist.md` 和 `docs/roadmap.md` 均自认 Anthropic Provider"代码就绪但从未连接真实 Claude API"
- 单元测试有 14+ 个（mock 数据），但无真实 API 调用验证
- thinking blocks、prompt caching、tool_use 三项核心功能均未实测
- **建议**：获取 Anthropic API key 后做一次端到端验证（streaming + tool_use + thinking blocks + token counting），记录结果到 checklist

---

## ☐ 上下文管理增强

对照 `D:\PythonProjects\mewcode-python\mewcode\context\manager.py` 及 `agent.py` 逐项对比。

### ✅ ② LLM 摘要压缩接入 已修复

`MemoryConfig.llm_summarize = True`（默认开启）：`app.py` 装配 Compressor 时用 `LLMSummarizeOldest(self._llm)` 替换 `SummarizeOldest`。LLM 调用失败自动回退到抽取式摘要（已内置）。`llm_summarize = false` 恢复旧行为。2 个测试覆盖。

修复两个问题：
- **压缩检查移到 LLM 调用前**：原来只在 OBSERVE 阶段（工具结果追加后）检查压缩，纯对话场景（无工具调用）永远不触发压缩。移到 `_think()` 的 `ensure_fits` 之前，每次 LLM 调用前先尝试 LLM 摘要压缩，不够再用 SlidingWindow 兜底。
- **压缩摘要前缀加明确指令**：压缩后 LLM 不信任摘要，去磁盘翻会话文件导致大量无效工具调用和权限弹窗。在摘要前缀中加 "this is the authoritative record of earlier conversation. Do NOT search session files or disk to recover history"。

### ✅ ③ 压缩熔断器 已修复

`ContextManager` 内置熔断器：连续 N 次压缩无效（token 未减少）后跳过后续压缩。`MemoryConfig.compress_max_failures = 3`（0 = 禁用）。成功压缩自动重置计数。3 个测试覆盖。

### ✅ ① 聚合工具结果预算（含三个配套机制）已修复（P64.1）

`ToolResultCache.spill_batch(results, already_used, exempt_ids)`：本轮累计工具结果字符超 `MemoryConfig.aggregate_spill_chars = 200_000`（0 = 禁用）时，按 output 长度降序强制溢写至预算内。三个配套机制全部落地：1a `is_spill_readback` 读回豁免（agent_loop 单条与聚合两层都检查）、1b `PREVIEW_CHARS` 500→2000、1c 不长于预览的结果豁免。`turn_result_chars` 在 run() 内跨迭代累计。溢写占位文案补溢写文件路径供 offset/limit 精读。13 个测试覆盖，真实 LLM 验证（DeepSeek）：聚合触发溢写、上下文有界、LLM 预览后自主精读收敛、读回不重溢写。交互式 E2E 验证（会话 JSON 审计）6 验证点达成；配套修复溢写缓存只读放行 + confirm() 提示符污染。诚实边界：aggregate < 单文件大小的极端参数下豁免读回计入累计会链式溢写-读回，默认 200K 无此问题（详见 tech-notes §64）。

**原问题**（已解决）：`maybe_spill()` 按单条 50K 阈值溢写。10 个并行工具各返回 49K 字符（未触发单条阈值），一轮塞入 ~500K 字符撑爆上下文。

**三个配套机制**（缺任一聚合溢写都会出问题，均已实现）：

| # | 配套机制 | mewcode | mini 实现 | 为什么必须 |
|---|---|---|---|---|
| 1a | **反重溢写保护** | `is_spill_readback`：工具结果的文件路径在溢写目录内时豁免溢写 | ✅ `ToolResultCache.is_spill_readback()`，agent_loop 单条与聚合两层都检查 | LLM 读回溢写文件 → 结果又被溢写 → 再读回 → 死循环 |
| 1b | **预览大小** | `PREVIEW_CHARS = 2_000` 字符 | ✅ 500→2000（以 `min(PREVIEW_CHARS, threshold)` 封顶） | 500 字符太短，LLM 信息不足无法判断是否需要重读，直接放弃用 bash 绕过 |
| 1c | **小结果豁免** | `< PREVIEW_CHARS` 的结果不溢写 | ✅ `maybe_spill` 中不长于预览的结果一律豁免（含 force 路径） | 预览比原文还大时溢写没意义（反而变大） |

**实现位置**（每条结果独立成消息故改为跨迭代累计）：
- `memory/tool_result_cache.py`：`PREVIEW_CHARS` 2000；`spill_batch(results, already_used, exempt_ids)`；`maybe_spill(force=)`；`is_spill_readback()`
- `core/agent_loop.py`：`_run_tool_pipeline()` 溢写前检查 `is_spill_readback`；OBSERVE 阶段调 `spill_batch`，`turn_result_chars` 跨迭代累计
- `models/config.py`：`aggregate_spill_chars: int = 200_000`（0 = 禁用）
- `security/path_guard.py`：溢写缓存目录只读自动放行（读回闭环不弹权限框）

### ☐ ④ 压缩双阈值（硬阈值绕过熔断器）

**问题**：mini 的熔断器开启后**所有**压缩都被阻断，包括上下文即将溢出的紧急情况。

**mewcode 实现**（`context/manager.py` `auto_compact`）：
- 软阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - AUTO_COMPACT_SAFETY_MARGIN(13K)` → 正常压缩，受熔断器控制
- 硬阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - MANUAL_COMPACT_SAFETY_MARGIN(3K)` → **强制压缩，绕过熔断器**
- 效果：200K 窗口下，167K 触发软压缩，177K 触发硬压缩

**mini 现状**：单阈值 `context_window × compression_threshold`（默认 75%），熔断器开启后只有 `ensure_fits`（粗暴 SlidingWindow 截断）兜底。

**修复位置**：
- `memory/context.py`：`check_and_compress()` 区分软硬阈值，硬阈值时跳过熔断器检查

### ☐ ⑤ token 驱动的保留窗口（替代固定 6 条消息）

**问题**：`SummarizeOldest.KEEP_RECENT = 6` 固定保留最近 6 条消息。6 条短消息可能只有 1K token（浪费空间），6 条长消息可能有 40K token（保留太多）。

**mewcode 实现**（`context/manager.py` keep-recent 窗口）：
- 从尾部反向扫描，累计 token 数
- 停止条件：累计 ≥ `KEEP_RECENT_TOKENS(10K)` **且** 消息数 ≥ `MIN_KEEP_MESSAGES(5)`
- 硬顶：不超过 `KEEP_MAX_TOKENS(40K)`
- 工具对对齐：keep 边界不切断 tool_use/tool_result 配对

**mini 现状**：固定 `KEEP_RECENT = 6` 条消息，有工具对对齐但无 token 感知。

**修复位置**：
- `memory/compressor.py`：`SummarizeOldest` 和 `LLMSummarizeOldest` 的 keep 计算从固定消息数改为 token 驱动

### ☐ ⑥ 摘要 prompt 结构化

**问题**：mini 的 `_SUMMARY_PROMPT` 只列 4 条通用指令，摘要质量不稳定。

**mewcode 实现**（`context/manager.py` `SUMMARY_PROMPT`）：
- 要求输出 `<analysis>` + `<summary>` 两个 XML 块
- analysis 覆盖 9 个维度：主请求、技术概念、涉及文件/代码、错误/修复、问题解决步骤、所有用户消息、待做任务、当前工作进展、可选下一步
- summary 要求简洁、保留所有关键信息

**mini 现状**：`_SUMMARY_PROMPT` 只要求 4 条（目标/步骤/文件/未解决），无结构化输出格式。

**修复位置**：
- `memory/compressor.py`：重写 `_SUMMARY_PROMPT`，参考 mewcode 的结构化 prompt

### ☐ ⑦ 摘要重试

**问题**：LLM 摘要调用偶发网络错误时直接回退到抽取式截断，丢失语义摘要。

**mewcode 实现**：最多重试 3 次；如果摘要 prompt 本身太长，丢弃最旧 20% 的消息后重试。

**mini 现状**：`LLMSummarizeOldest._summarize()` 失败直接 `except Exception` 回退。

**修复位置**：
- `memory/compressor.py`：`LLMSummarizeOldest._summarize()` 加重试循环；prompt 超长时截断输入

### ⑧ 压缩后重注入环境上下文和记忆 — 不适用（架构差异）

mewcode 把记忆注入到 `history`（消息列表）里作为 `user` 消息，压缩 `replace_history()` 后需要重注入。mini 把记忆注入到 `system_prompt`（独立字段），压缩只操作 `messages` 不动 `system_prompt`，记忆天然免疫压缩，不需要重注入。

### ☐ ⑨ 最小前缀检查

**问题**：可摘要部分（keep 窗口之前的消息）很少时，压缩开销大于收益。

**mewcode 实现**：可摘要前缀 < `MIN_SUMMARIZE_PREFIX_TOKENS(2K)` token 时跳过压缩。

**mini 现状**：只检查消息数（`len(msgs) <= KEEP_RECENT`），不检查 token 量。

**修复位置**：
- `memory/compressor.py`：`SummarizeOldest` / `LLMSummarizeOldest` 的 `compress()` 增加前缀 token 量检查

---

## ✅ 远程/浏览器模式待做（P57）

### 仍存在的已知局限
- ~~单客户端~~ ✅ 已完成（`self._clients: set` 广播，多标签页同步输出）
- ~~无认证~~ ✅ 已完成（`--remote-token` 可选 token 认证，WS+HTTP 双通道验证）。仍无 TLS（明文 `ws://`）
- ~~浏览器刷新丢失会话~~ ✅ 已完成（`_replay_history()` 回放对话历史，服务器重启仍丢失）
- ~~Markdown 不支持图片~~ ✅ 已支持（`![alt](url)` → `<img>`，仅公网 URL 可加载）

### 建议改进优先级
1. ~~刷新时重放历史~~ ✅ 已完成（`_replay_history()`）
2. ~~链接渲染~~ ✅ 已完成（`[text](url)` + 裸 URL 自动识别 + 图片）
3. ~~简单 token 认证~~ ✅ 已完成（`--remote-token`，WS 首条消息验证 + HTTP 端点验证）
4. ~~多客户端支持~~ ✅ 已完成（`self._clients: set` 广播，断连自动清理）

✅ 已完成（textarea + Shift+Enter + auto-grow） **多行输入**
- 当前：`<input>` 单行输入框，无法粘贴多行代码
- mewcode：`<textarea>` + Shift+Enter 换行 + 自动高度调整
- 改动：`web_ui.py` 将 `<input>` 换成 `<textarea>`，JS 监听 Shift+Enter 换行、Enter 发送，CSS `resize: none` + `auto-grow`

✅ 已完成（details/summary，默认展开） **工具调用折叠**
- 当前：工具调用和结果作为平铺暗灰色文本，多工具调用时页面很长
- mewcode：工具调用块可展开/收起，默认收起只显示工具名+耗时
- 改动：`web_ui.py` 用 `<details><summary>` 包装工具调用和结果，默认收起

✅ 已完成（turn_end 附带 tokens） **Token 用量显示**
- 当前：浏览器不显示 token 用量（只在终端显示）
- mewcode：状态栏显示 input/output token 数
- 改动：`server.py` 在 `turn_end` 事件中附带 `tokens` 字段（从 `agent_loop.last_turn_tokens` 读取），`web_ui.py` 在 turn 结束后显示

✅ 已完成（tool_result 附带 elapsed） **工具耗时显示**
- 当前：`tool_result` 事件不含耗时
- mewcode：每个工具结果附带 `elapsed` 秒数
- 改动：`agent_loop.py` `_execute_single_tool` 已有 `duration_ms`（在 `ToolCallEndEvent` 中），将其传到 `on_tool_end` 回调 → `server.py` 附到 `tool_result` 事件 → `web_ui.py` 显示

✅ 已完成（服务端发送 commands 事件，按字母排序） **动态命令列表**
- 当前：`web_ui.py` 硬编码 18 个命令到 JS 的 `CMDS` 数组
- mewcode：服务端连接时发送完整命令注册表，前端动态构建菜单
- 改动：`server.py` 连接时从 `self._app.slash_commands` 读取所有命令名+描述，发送 `commands` 事件 → `web_ui.py` 收到后替换硬编码列表

✅ 已完成（渲染为折叠块） **`<think>` 标签解析**
- 当前：只处理 `thinking_delta` 事件（DeepSeek R1 的 `reasoning_content`）
- mewcode：前端还解析助手文本中的 `<think>...</think>` XML 标签，渲染为折叠块
- 改动：`web_ui.py` 的 `renderMd()` 或 `stream_text` 处理中检测 `<think>` 标签，渲染为 `<details class="thinking">`

✅ 已完成（18 个 CSS 变量） **CSS 变量主题**
- 当前：所有色值硬编码（`#1e1e2e`、`#89b4fa` 等散落各处）
- mewcode：`:root` 定义 CSS 变量，切换主题只需修改变量
- 改动：`web_ui.py` 将所有色值抽成 CSS 变量，预留 light mode

✅ 已完成（10 秒心跳） **应用层 ping/pong**
- 当前：无心跳机制，依赖 websockets 库底层 ping
- mewcode：每 10 秒发 `ping`，前端回 `pong`
- 改动：`server.py` 启动后台任务定时 `_ws_send("ping")`，`web_ui.py` 收到后回 `pong`

✅ 已完成（iterations + elapsed + tokens） **turn 完成摘要**
- 当前：`turn_end` 不携带数据
- mewcode：`loop_complete` 携带 `totalTurns` + `elapsed` 秒数
- 改动：`server.py` 在 `turn_end` 中附带迭代数和耗时

✅ 已完成（"Reconnecting..." 替代 "Disconnected"） **重连状态优化**
- 当前：断连后显示"Disconnected"，重连后切回"Connected"，有闪烁
- mewcode：显示"Reconnecting..."，重连成功后才切回"Connected"
- 改动：`web_ui.py` `ws.onclose` 中显示"Reconnecting..."替代"Disconnected"

✅ 已完成（full_text 参数） **`stream_end` 携带完整文本**
- 当前：`stream_end` 无数据，前端依赖增量拼接的 `streamBuf`
- mewcode：`stream_end` 携带完整累积文本，前端可用于最终渲染修正
- 改动：`agent_loop.py` `on_stream_end` 回调增加 `full_text` 参数

### 追加修复
- ✅ 单端口合并：HTTP + WS 共用同一端口（process_request 拦截 GET / 返回 HTML，/ws 走 WS 升级）
- ✅ 多客户端回放修复：`_replay_history` 改为只发给当前重连客户端，不再广播
- ✅ 用户消息多客户端同步：广播 `user_message` 事件，发送端去重
- ✅ 段落换行：CSS `white-space: pre-line` + `\n\n` 替换为 div 间距块
- ✅ 滚动锁定：用户上滑后 `userScrolled` 标志禁止自动滚底，turn 结束重置
- ✅ 标题间距：h1-h4 加 margin-top/bottom
- ✅ 输入框透明滚动条
- ✅ Cancel/Permission 改走 WS 消息（去掉 HTTP POST 端点）
- ✅ 主题切换：深色（Catppuccin Mocha）+ 浅色（Catppuccin Latte），header 按钮 + localStorage 持久化 + `/theme light|dark` 命令联动
