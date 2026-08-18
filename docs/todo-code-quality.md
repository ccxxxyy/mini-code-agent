# 代码质量待做清单

已修复的问题标 ✅，待修复的标 ☐。

## ✅ 已修复

- ✅ `openai_provider.py` `count_tokens` 绕过 `token_counter` 模块（直接 `len//4`）→ 改为调用 `token_counter.count_tokens()`
- ✅ `anthropic_provider.py` `count_tokens` 同上问题 → 同上修复
- ✅ `models/message.py` `__import__("json")` 反模式 → 改为模块顶部 `import json`

## ✅ 中优先级

### ✅ markdown 围栏剥离三处重复
- `memory/extraction.py:140`
- `memory/recall.py:83`
- `memory/consolidation.py:103`

三处都在做同样的 strip ` ```json ... ``` ` 逻辑。✅ 已抽取为 `memory/_utils.py` 的 `strip_json_fence(text) -> str` 函数。

### ✅ LLM 流式调用+组装五处重复
- `memory/extraction.py` — 提取记忆
- `memory/recall.py` — 选择性召回
- `memory/consolidation.py` — 语义合并
- `memory/compressor.py` — LLM 摘要压缩（`_summarize`）
- `core/planner.py` — 任务分解

五处"流式调 LLM → 收集 chunk → 组装响应"的重复模式。✅ 已抽取：`assemble_response()` 从 `openai_provider.py` 移至 `llm/base.py`（provider 无关），新增独立函数 `complete(llm, messages, ...)` 一次调用完成流式收集+组装。五处调用点均已简化为 `await complete(self._llm, messages)`。

## ✅ 低优先级

### ✅ shell 检测逻辑重复
- `app.py` 和 `core/subagent.py` 各自 `os.environ.get("SHELL")` 判断 shell 类型
- ✅ 已抽取为 `config/environment.py` 的 `detect_shell() -> str`，两处调用点改为 `detect_shell()`

### ✅ `os.environ` 直接访问绕过 config
- 同上两处直接读环境变量而非通过 ConfigLoader，对测试隔离有影响
- ✅ 随 shell 检测抽取一并解决：两处调用点不再直接读 `os.environ`，环境读取收敛到 `config/environment.py` 单点，测试可 monkeypatch `detect_shell` 隔离

### ✅ 权限检查逻辑内部重复
- `permission.py:156-193`（`check()`）和 `permission.py:266-285`（`_check_rules_only()`）
- ✅ `check()` 改为先调 `_check_rules_only()`，匹配则直接返回，否则走默认模式。消除了 DENY→ALLOW→session grants 的重复遍历

### ✅ 路径 resolve 重复
- `security/sandbox/seatbelt.py:42,45` 和 `security/sandbox/bwrap.py:30,33`
- ✅ 抽取为 `security/sandbox/__init__.py` 的 `resolve_path(path) -> str`，两处调用点改为 `resolve_path(path)`

### ✅ 静默 except（约 35 处）
- 大部分是有意的 fail-safe（记忆提取/召回/合并失败不阻断主流程）
- ✅ 14 个文件共 35 处静默 except 加入 `logger.warning`（hook 触发失败等关键路径，10 处）或 `logger.debug`（I/O 与解析降级，25 处），均带 `exc_info=True`。原有降级行为不变

---

## ✅ 死代码清理（27 处）

27 处死代码分为三类：**真正遗忘应接入的**（6 处，✅ 已全部修复）、**设计变更后的残留物**（5 处，✅ 已全部删除）、**有意预留的扩展点**（16 处）。

---

### ✅ 真正遗忘、应该接入（6 处）已全部修复

| # | 项 | 修复内容 |
|---|---|---|
| 1 | `LLMResponse.model` | `_stream_once()` 中 `assemble_response` 后设置 `response.model = self.model_name` |
| 2 | `TokenUsage.cache_read_input_tokens` | `LLMResponseEvent` 新增缓存字段，`CostTracker` 按 `cache_read`/`cache_creation` 差异化定价（pricing 支持 `cache_read`、`cache_creation` 键，未配则退回 input 价） |
| 3 | `AgentConfig.enable_plan_mode` | `app.py` 初始化时 `agent_loop.plan_mode = config.enable_plan_mode`；默认值改为 `False`（用户需显式开启） |
| 4 | `on_thinking_delta` 终端接入 | `Terminal.feed_thinking()` + `app.py` 回调：dim italic 样式输出思考过程 |
| 5 | `PermissionRequest.matched_rule` | `PermissionManager.last_matched_rule` → `PermissionCheckEvent.matched_rule` → `AuditLogger` 记录 |
| 6 | `count_message_tokens()` / `count_messages_tokens()` | `ContextManager.count_message()` 改用 per-tool-call +3 开销精确计数；删除 `token_counter.py` 中的死函数 |

---

### ✅ 设计变更后的残留物（5 处）已全部删除

| # | 项 | 处理 |
|---|---|---|
| 1 | `LLMStreamChunkEvent` | ✅ 从 `models/events.py` 和 `events/types.py` 删除 |
| 2 | `LLMErrorEvent` | ✅ 从 `models/events.py` 和 `events/types.py` 删除 |
| 3 | `ToolFilter` + `ToolFilterContext` | ✅ 删除 `security/tool_filter.py` 整个文件，从 `security/__init__.py` 移除导出 |
| 4 | `AgentState.pending_tool_calls` | ✅ 从 `core/agent_state.py` 删除字段，移除不再需要的 `ToolCall` 导入 |
| 5 | 5 个异常类 | ✅ 删除 `core/errors.py` 整个文件，从 `core/__init__.py` 移除导入和导出 |

---

### 🟢 有意预留的扩展点（15 处；#1/#2/#3/#4/#6/#7/#8/#9/#10/#11/#12/#13/#14/#15 已接入，#5 删除）


| # | 项 | 位置 | 预留用途 |
|---|---|---|---|
| 1 | `EventBus.on_any()` | `events/bus.py:29` | ✅ 已接入：新增 `extensions/event_listeners.py`，从 `listener_dirs` 配置目录加载 *.py 插件（`register(bus)` 或 `on_event(event)` 契约），app 启动时注册为全局监听；`emit` 同时改为记录 handler 异常日志，并补充 `off_any()` |
| 2 | `ToolRegistry.filter()` | `tools/base.py:212` | ✅ 已接入：`AgentTeam.start()` 非写文件步骤 + `SubAgent.__init__` 工具过滤均通过 `filter()` |
| 3 | `PermissionManager.add_rule()` | `security/permission.py:94` | ✅ 已接入：增强为带验证/去重/事件发射的完整方法；新增 `remove_rule()` 和 `list_rules()`；`/allow` `/deny` 斜杠命令运行时动态管理权限规则；`_load_rules_from_config` 和 `load_rule_files` 统一走 `add_rule()`；新增 `PermissionRuleAddedEvent` / `PermissionRuleRemovedEvent` 事件 |
| 4 | `ProviderRegistry.list_providers()` | `llm/registry.py:27` | ✅ 已接入：`/model` 无参数时显示可用 Provider 列表 |
| 5 | `Conversation.slice_window()` | ~~`models/message.py`~~ | ✅ 已删除（P81）：属"设计变更后的残留物"而非健康预留——被 ContextManager/Compressor 完全取代；且自身语义有坑（`token_count or 0` 使未计数消息按零成本通过，预算失效）并会切断 tool_use/tool_result 配对（严格 API 400，压缩链路已为此类 bug 修过 P71 等多阶段）；修好再接入等于重抄 `_compute_keep_split`。零生产调用方，连同单测删除 |
| 6 | `Plan.is_complete` | `core/planner.py:74` | ✅ 已接入：`AgentTeam.start()` 用 `while not plan.is_complete` 替代手动 pending 列表 |
| 7 | `HookAction.CONFIRM` | `tools/hooks.py:32` | ✅ 已接入：`[[hooks]]` 规则新增 `action = "confirm"`，命中弹 y/a/n 确认框（a = 本会话同规则不再问）；裁决在 `agent_loop._resolve_hook_confirm`（app 注入 terminal.confirm，无 UI 安全拒绝），拒绝回传 `Denied by user: <reason>`；流式执行经 `HookManager.would_confirm` 预判延迟到 _act，弹窗加锁防并行交错 |
| 8 | `PermissionDecision.PENDING` | `models/permissions.py:24` | ✅ 已接入：三部分——① pane worker 跨进程审批通道（`security/remote_confirm.py` `RemoteConfirm` 回调写 `~/.mini-agent/workers/<id>.perm-request.json` 记 PENDING 后轮询决策文件，超时 120s 安全拒绝；`worker.py` 搭建完整权限栈 `PathGuard`+`PermissionManager`+`RemoteConfirm`；`SubAgent` 新增 `permission_manager` 参数传入 `AgentLoop`；`SubAgentManager._collect_pane_result()` 轮询权限请求并通过父进程 `confirm_callback` 中转决策；`app.py` 传 `terminal.confirm` 给 `SubAgentManager`）；② remote/Web 断连排队（`server.py`：`_pending_prompts` 跟踪请求文本，最后客户端断开启动 `_disconnect_timeout` 120s 后安全拒绝，重连时 `_replay_pending_confirms` 重发待处理请求）；③ 事件可观测（`permission.py._ask_user()` 在 `await confirm` 前发射 `PermissionCheckEvent(decision="pending", reason="awaiting_user")`，`trace.py` 用 `theme.warning` 色显示 `PENDING (awaiting user)`） |
| 9 | `PermissionScope.TOOL` | `models/permissions.py:16` | ✅ 已接入（P79）：`PermissionManager.check_tool()` 工具级门——显式 TOOL 规则 DENY 直接拦截工具、ALLOW 整体信任（跳过命令/路径资源检查）、无匹配返回 None 落回资源级检查；`agent_loop._check_permission()` 对所有工具调用先过工具门；`/allow` `/deny` 支持 `tool` scope；permissions.toml 新增 `[tools]` 节（load/save 均支持）；`would_ask` 工具级规则直接判定不弹窗 |
| 10 | `DEFAULT_AGENT_TYPE` | `core/agent_types.py:128` | ✅ 已接入（P80）：`SubAgent.__init__` 未指定类型时回退 `get_agent_type(DEFAULT_AGENT_TYPE)`（worker），删除与 `_WORKER_PROMPT` 重复的内联 `SUBAGENT_SYSTEM_PROMPT`；未显式选类型时保留 `config.max_agent_iterations`（用户可配值优先，不被 worker 的 50 静默覆盖），显式选类型仍采纳类型完整档案 |
| 11 | `SessionMetadata.tags` | `models/session.py:22` | ✅ 已接入：`/session tag`/`untag`/`tags` 子命令 + `/session list --tag` 按标签过滤 |
| 12 | `UserMessageEvent.is_slash_command` | `models/events.py:24` | ✅ 已接入：斜杠命令分支 emit 事件设 `is_slash_command=True`，AuditLogger 记录 + TraceRenderer 显示 |
| 13 | `LLMRequestEvent.estimated_tokens` | `models/events.py:34` | ✅ 已接入：`agent_loop._think()` 从 ContextManager 填入预估 token，TraceRenderer 显示 |
| 14 | `PermissionRequest.tool_name` | `models/permissions.py:39` | ✅ 已接入：`check_path()` 新增 `tool_name` 参数，`agent_loop._check_permission()` 传入 `tc.name` |
| 15 | `PermissionManager.check()` | `security/permission.py` | ✅ 已接入（P79）：重构为真正的通用检查入口——按 `request.scope` 分发到 COMMAND（危险模式确认管道）/ PATH（DENY 规则→PathGuard→通用管道，operation 从 context 解析）/ TOOL（通用管道），任意消费者构造 `PermissionRequest` 一次调用即得正确判定；原通用逻辑抽为 `_check_generic()`，`check_path`/`check_command` 复用同一批内部管道无递归 |
---

##  ✅ 文档与仓库卫生

以下问题来自 `analysis-shortcomings.md` 的逐条验证，已确认为真实问题。

### ✅ spec.md 与现状脱节（已验证）
- ~~`docs/spec.md` 自修正写"8 个内置工具"~~ ✅ 已修正为 10
- ✅ spec.md 目录树已删除不存在的 `extensions/plugin_loader.py`、`config/schema.py`、`core/errors.py`、`security/tool_filter.py`
- spec.md 目录树写"6 core tools"——属历史设计文档，已有 disclaimer 说明

### ✅ .gitignore 遗漏（已验证）
- `.coverage` / `htmlcov/` — ✅ 已在 .gitignore 中（原有）
- `.pytest_cache/` — ✅ 已追加到 .gitignore
- `.ruff_cache/` — ✅ 已追加到 .gitignore
- `experiments/results/` — ✅ 已追加到 .gitignore，已 `git rm --cached` 清除 31 个已追踪的 JSON 文件

---

## ✅ 上下文管理增强

对照 `D:\PythonProjects\mewcode-python\mewcode\context\manager.py` 及 `agent.py` 逐项对比。

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

### ✅ ② LLM 摘要压缩接入 已修复

`MemoryConfig.llm_summarize = True`（默认开启）：`app.py` 装配 Compressor 时用 `LLMSummarizeOldest(self._llm)` 替换 `SummarizeOldest`。LLM 调用失败自动回退到抽取式摘要（已内置）。`llm_summarize = false` 恢复旧行为。2 个测试覆盖。

修复两个问题：
- **压缩检查移到 LLM 调用前**：原来只在 OBSERVE 阶段（工具结果追加后）检查压缩，纯对话场景（无工具调用）永远不触发压缩。移到 `_think()` 的 `ensure_fits` 之前，每次 LLM 调用前先尝试 LLM 摘要压缩，不够再用 SlidingWindow 兜底。
- **压缩摘要前缀加明确指令**：压缩后 LLM 不信任摘要，去磁盘翻会话文件导致大量无效工具调用和权限弹窗。在摘要前缀中加 "this is the authoritative record of earlier conversation. Do NOT search session files or disk to recover history"。

### ✅ ③ 压缩熔断器 已修复

`ContextManager` 内置熔断器：连续 N 次压缩无效（token 未减少）后跳过后续压缩。`MemoryConfig.compress_max_failures = 3`（0 = 禁用）。成功压缩自动重置计数。3 个测试覆盖。

### ✅ ④ 压缩双阈值（硬阈值绕过熔断器）已修复（P65）

**问题**：mini 的熔断器开启后**所有**压缩都被阻断，包括上下文即将溢出的紧急情况。

**mewcode 实现**（`context/manager.py` `auto_compact`）：
- 软阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - AUTO_COMPACT_SAFETY_MARGIN(13K)` → 正常压缩，受熔断器控制
- 硬阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - MANUAL_COMPACT_SAFETY_MARGIN(3K)` → **强制压缩，绕过熔断器**
- 效果：200K 窗口下，167K 触发软压缩，177K 触发硬压缩

**已实现**（P65）：`MemoryConfig.hard_compression_threshold = 0.90` 独立配置。`check_and_compress()` 熔断器检查加 `and not self.needs_hard_compression`：软阈值被熔断器阻断时，硬阈值仍走完整三级级联。

### ✅ ⑤ token 驱动的保留窗口（替代固定 6 条消息）已修复

**问题**：`SummarizeOldest.KEEP_RECENT = 6` 固定保留最近 6 条消息。6 条短消息可能只有 1K token（浪费空间），6 条长消息可能有 40K token（保留太多）。

**mewcode 实现**（`context/manager.py` keep-recent 窗口）：
- 从尾部反向扫描，累计 token 数
- 停止条件：累计 ≥ `KEEP_RECENT_TOKENS(10K)` **且** 消息数 ≥ `MIN_KEEP_MESSAGES(5)`
- 硬顶：不超过 `KEEP_MAX_TOKENS(40K)`
- 工具对对齐：keep 边界不切断 tool_use/tool_result 配对

**已实现**：`_compute_keep_split()` 替代固定 `KEEP_RECENT = 6`，`SummarizeOldest` 和 `LLMSummarizeOldest` 均使用 token 驱动的保留窗口。常量 `KEEP_RECENT_TOKENS=10K` / `MIN_KEEP_MESSAGES=5` / `KEEP_MAX_TOKENS=40K`（⑩/P68 起为绝对上限，实际随压缩目标缩放）。7 个新测试覆盖短消息全保留 / 长消息少保留 / 硬顶 / 最少消息数 / 双阈值停止。

### ✅ ⑥ 摘要 prompt 结构化 已修复（P67）

**问题**：mini 的 `_SUMMARY_PROMPT` 只列 4 条通用指令，摘要质量不稳定。

**mewcode 实现**（`context/manager.py` `SUMMARY_PROMPT`）：
- 要求输出 `<analysis>` + `<summary>` 两个 XML 块
- analysis 覆盖 9 个维度：主请求、技术概念、涉及文件/代码、错误/修复、问题解决步骤、所有用户消息、待做任务、当前工作进展、可选下一步
- summary 要求简洁、保留所有关键信息

**已实现**：`_SUMMARY_PROMPT` 重写为 `<analysis>`（时间线梳理 + 自查）+ `<summary>`（9 节结构化输出）；新增 `_extract_summary()` 只把 `<summary>` 块注入对话（analysis 草稿不进上下文），无标签回退完整输出、只有 analysis（截断）时剥离草稿触发抽取式回退。mini 适配：prompt 明确"近期消息已原样保留，摘要只替换旧历史"；不需要 mewcode 的 "Do NOT call tools" 警告（`_summarize()` 直连不带工具）。真实 LLM E2E 验证 9 节摘要完整、无草稿泄漏。5 个新测试。详见 tech-notes §67。

### ✅ ⑦ 摘要重试（P72 偶发重试 + P73 超长收缩重试）已修复

**问题**：LLM 摘要调用偶发网络错误时直接回退到抽取式截断，丢失语义摘要。

**mewcode 实现**：最多重试 3 次；如果摘要 prompt 本身太长，丢弃最旧 20% 的消息后重试。

**已实现**：
- P72：`SUMMARY_RETRIES=2`，偶发失败先重试再落抽取式，重试/穷尽有 WARNING 日志
- P73：`_is_prompt_too_long()`（400/413 一律算 + 错误消息关键词兜底）识别超长后，丢弃最旧 20% 可摘要消息（头部旧压缩摘要绝不丢——它是更早历史的唯一记录）并把字符 cap 缩 20% 后重试；`MAX_SHRINKS=3`，与偶发重试预算独立；穷尽后立即回退，不用相同的超长请求烧偶发预算（真实运行实测：相同请求重试必然相同失败）。真实 API 全管道验证：6.2M 字符 → 真 400 → 2 轮收缩 → 3.98M 字符成功产出 9 节摘要，埋点约定存活。详见 tech-notes §73。

### ⑧ 压缩后重注入环境上下文和记忆 — 不适用（架构差异）

mewcode 把记忆注入到 `history`（消息列表）里作为 `user` 消息，压缩 `replace_history()` 后需要重注入。mini 把记忆注入到 `system_prompt`（独立字段），压缩只操作 `messages` 不动 `system_prompt`，记忆天然免疫压缩，不需要重注入。

### ✅ ⑨ 最小前缀检查 已修复

**问题**：可摘要部分（keep 窗口之前的消息）很少时，压缩开销大于收益。

**mewcode 实现**：可摘要前缀 < `MIN_SUMMARIZE_PREFIX_TOKENS(2K)` token 时跳过压缩。

**已实现**：`memory/compressor.py` 新增 `MIN_SUMMARIZE_PREFIX_TOKENS = 2000` 常量 + `_prefix_tokens()` 辅助函数。`SummarizeOldest` 和 `LLMSummarizeOldest` 的 `compress()` 在 split 计算后、实际摘要前检查前缀 token 量，不足 2K 时跳过——与 mewcode 行为对齐。1 个新测试覆盖。

### ✅ ⑩ 保留窗口按压缩目标缩放（P68）已修复

**问题**：⑤ 的 `KEEP_RECENT_TOKENS=10K` / `KEEP_MAX_TOKENS=40K` 是绝对常量。窗口 ≤ 13K 时保留下限不小于压缩目标（75% × 窗口），摘要级数学上永远达不到目标，压缩全部退化为 SlidingWindow 硬截断 + 硬阈值每轮空转。P67 终端窗口验证（context_window=10000）实测暴露：单轮 80 次迭代烧 1M token 才被迭代上限刹住。

**已实现**：`_compute_keep_split(msgs, target_tokens)` 增加 target 参数——保留下限 `min(10K, target//2)`、硬顶 `min(40K, target)` 随目标缩放；`keep_count==0` 时兜底保留 1 条尾部消息。大窗口行为完全不变（min 取的仍是绝对值）。真实 LLM 验证：target=7500 时压缩后 7008 ≤ 7500 达标、结构化摘要存活。4 个新测试。详见 tech-notes §68。


### ✅ ⑪ P67 验收期间连带修复的压缩链路缺陷（P69/P70/P71）已修复

九轮真实终端无污染埋点验证暴露并当场修复，详见 tech-notes §69-§71：
- **P69** DropToolResults 截断模型工作集 → 重读死循环（36 迭代→4）：Stage 1 只处理可摘要前缀
- **P70** 恢复附件预算不随窗口缩放（54K 字符附件钉死小窗口）+ 嵌套摘要 prompt 缺前传指令
- **P71** SlidingWindow 删除刚生成的摘要（有任务锚点无摘要锚点）：新增摘要锚点
---

## ✅ 远程/浏览器模式（P57）

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
