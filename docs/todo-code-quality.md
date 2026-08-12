# 代码质量待做清单

已修复的问题标 ✅，待修复的标 ☐。

## ✅ 已修复

- ✅ `openai_provider.py` `count_tokens` 绕过 `token_counter` 模块（直接 `len//4`）→ 改为调用 `token_counter.count_tokens()`
- ✅ `anthropic_provider.py` `count_tokens` 同上问题 → 同上修复
- ✅ `models/message.py` `__import__("json")` 反模式 → 改为模块顶部 `import json`

## ☐ 中优先级

### markdown 围栏剥离三处重复
- `memory/extraction.py:140`
- `memory/recall.py:83`
- `memory/consolidation.py:103`

三处都在做同样的 strip ` ```json ... ``` ` 逻辑。建议抽取为 `memory/_utils.py` 的 `strip_json_fence(text) -> str` 函数。

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
- `docs/spec.md` 自修正写"8 个内置工具"，实际已 10 个（漏了 `tool_search` 和 `mcp_call`）
- spec.md 目录树列了不存在的 `extensions/plugin_loader.py`
- spec.md 目录树写"6 core tools"与自修正的"8"也矛盾
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

## ☐ 上下文管理增强（已验证的真实缺陷）

以下三项来自 mewcode 对比分析，经代码验证确认为 mini 的真实缺陷。

### ① 聚合工具结果预算（真实缺陷，高优先级）

**问题**：`_act()` 并行执行多个工具后，逐条追加结果到对话，无聚合大小检查。`ToolResultCache.maybe_spill()` 按单条 50K 阈值溢写——10 个并行工具各返回 49K 字符（未触发单条阈值），一轮塞入 ~500K 字符直接撑爆上下文。

**位置**：
- `core/agent_loop.py:254-261` — `_act()` 返回结果后逐条 `conversation.append`，无总量检查
- `memory/tool_result_cache.py:41` — `len(output) <= self._threshold` 仅按单条判断
- `models/config.py:67` — `spill_threshold_chars = 50_000` 仅单条阈值

**修复建议**：在 `run()` 的 OBSERVE 阶段（追加结果前），计算本轮所有结果的总字符数。超过聚合阈值（如 200K）时，从最大的结果开始逐条溢写磁盘，直到总量降到阈值内。溢写回读的结果（`is_spilled_readback` 标记）豁免溢写。

```python
# agent_loop.py OBSERVE 阶段，追加结果前
total = sum(len(r.output) for r in results)
if total > AGGREGATE_BUDGET:
    sorted_results = sorted(results, key=lambda r: len(r.output), reverse=True)
    for r in sorted_results:
        if total <= AGGREGATE_BUDGET:
            break
        if self.result_cache and not getattr(r, 'is_readback', False):
            old_len = len(r.output)
            r = self.result_cache.maybe_spill(r, force=True)
            total -= (old_len - len(r.output))
```

### ② LLM 摘要压缩接入（已有代码未接入）

**问题**：默认压缩链用 `SummarizeOldest`（每条截 300 字符的抽取式摘要，丢语义），`LLMSummarizeOldest`（真正的 LLM 摘要）**已写好但未接入**，只在 `experiments/compression_ab.py` 实验中使用。

**位置**：
- `memory/compressor.py:64-88` — `SummarizeOldest`（生产环境在用，300 字符截断）
- `memory/compressor.py:128-171` — `LLMSummarizeOldest`（已实现，未接入，失败时自动回退到抽取式）
- `app.py:206` — `Compressor()` 默认用 `SummarizeOldest`，未传入 LLM

**修复建议**：在 `app.py` 装配时把 LLM 实例传给 Compressor，让压缩链用 `LLMSummarizeOldest`（已内置失败回退，不会阻断主流程）：

```python
# app.py 中
compressor = Compressor(strategies=[
    DropToolResults(),
    LLMSummarizeOldest(llm=self.llm_provider),  # 替换 SummarizeOldest
    SlidingWindow(),
])
```

注：mewcode 还在压缩后注入"文件内容快照"（截断后的文件内容），mini 只注入路径列表。内容快照 token 开销大，路径列表已足够防重读，按需评估是否值得。

### ③ 压缩熔断器（真实缺陷，中优先级）

**问题**：`check_and_compress()` 无失败计数、无冷却机制。压缩失败（如 LLM 不可用）后不记录，下一轮 `usage_ratio >= 0.75` 仍满足，再次触发压缩——每轮都尝试、每轮都失败、白烧 token（尤其启用 `LLMSummarizeOldest` 后）。

**位置**：
- `memory/context.py:132-149` — `check_and_compress()` 无 try/except、无失败计数、压缩后不验证是否真的降了 token
- 对比：`ensure_fits()`（`context.py:178-189`）是硬兜底但不在压缩链中

**修复建议**：加失败计数器 + 连续 N 次失败后跳过（冷却）：

```python
class ContextManager:
    def __init__(self, ...):
        ...
        self._compress_failures: int = 0
        self._max_compress_failures: int = 3

    async def check_and_compress(self, conversation):
        self.update_total(conversation)
        if not self.needs_compression:
            return False
        if self._compress_failures >= self._max_compress_failures:
            return False  # 熔断：连续失败过多，跳过
        if self._compressor is None:
            return False
        old_total = self._total_tokens
        target = int(self._max_tokens * 0.5)
        await self._compressor.compress(conversation, target)
        self._inject_read_files(conversation)
        self.update_total(conversation)
        if self._total_tokens >= old_total:
            self._compress_failures += 1  # 没效果，计失败
        else:
            self._compress_failures = 0  # 有效果，重置
        return True
```

---

## ☐ 远程/浏览器模式待做（P57 相关）

以下问题与本任务（Remote/Browser mode #113）直接相关。

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

### 与 mewcode 对比后的增强待做（按价值排序）

以下功能 mewcode 已实现但 mini 尚未支持，经代码对比验证。

#### 高价值

☐ **多行输入**
- 当前：`<input>` 单行输入框，无法粘贴多行代码
- mewcode：`<textarea>` + Shift+Enter 换行 + 自动高度调整
- 改动：`web_ui.py` 将 `<input>` 换成 `<textarea>`，JS 监听 Shift+Enter 换行、Enter 发送，CSS `resize: none` + `auto-grow`

☐ **工具调用折叠**
- 当前：工具调用和结果作为平铺暗灰色文本，多工具调用时页面很长
- mewcode：工具调用块可展开/收起，默认收起只显示工具名+耗时
- 改动：`web_ui.py` 用 `<details><summary>` 包装工具调用和结果，默认收起

☐ **Token 用量显示**
- 当前：浏览器不显示 token 用量（只在终端显示）
- mewcode：状态栏显示 input/output token 数
- 改动：`server.py` 在 `turn_end` 事件中附带 `tokens` 字段（从 `agent_loop.last_turn_tokens` 读取），`web_ui.py` 在 turn 结束后显示

#### 中价值

☐ **工具耗时显示**
- 当前：`tool_result` 事件不含耗时
- mewcode：每个工具结果附带 `elapsed` 秒数
- 改动：`agent_loop.py` `_execute_single_tool` 已有 `duration_ms`（在 `ToolCallEndEvent` 中），将其传到 `on_tool_end` 回调 → `server.py` 附到 `tool_result` 事件 → `web_ui.py` 显示

☐ **动态命令列表**
- 当前：`web_ui.py` 硬编码 18 个命令到 JS 的 `CMDS` 数组
- mewcode：服务端连接时发送完整命令注册表，前端动态构建菜单
- 改动：`server.py` 连接时从 `self._app.slash_commands` 读取所有命令名+描述，发送 `commands` 事件 → `web_ui.py` 收到后替换硬编码列表

☐ **`<think>` 标签解析**
- 当前：只处理 `thinking_delta` 事件（DeepSeek R1 的 `reasoning_content`）
- mewcode：前端还解析助手文本中的 `<think>...</think>` XML 标签，渲染为折叠块
- 改动：`web_ui.py` 的 `renderMd()` 或 `stream_text` 处理中检测 `<think>` 标签，渲染为 `<details class="thinking">`

#### 低价值

☐ **CSS 变量主题**
- 当前：所有色值硬编码（`#1e1e2e`、`#89b4fa` 等散落各处）
- mewcode：`:root` 定义 CSS 变量，切换主题只需修改变量
- 改动：`web_ui.py` 将所有色值抽成 CSS 变量，预留 light mode

☐ **应用层 ping/pong**
- 当前：无心跳机制，依赖 websockets 库底层 ping
- mewcode：每 10 秒发 `ping`，前端回 `pong`
- 改动：`server.py` 启动后台任务定时 `_ws_send("ping")`，`web_ui.py` 收到后回 `pong`

☐ **turn 完成摘要**
- 当前：`turn_end` 不携带数据
- mewcode：`loop_complete` 携带 `totalTurns` + `elapsed` 秒数
- 改动：`server.py` 在 `turn_end` 中附带迭代数和耗时

☐ **重连状态优化**
- 当前：断连后显示"Disconnected"，重连后切回"Connected"，有闪烁
- mewcode：显示"Reconnecting..."，重连成功后才切回"Connected"
- 改动：`web_ui.py` `ws.onclose` 中显示"Reconnecting..."替代"Disconnected"

☐ **`stream_end` 携带完整文本**
- 当前：`stream_end` 无数据，前端依赖增量拼接的 `streamBuf`
- mewcode：`stream_end` 携带完整累积文本，前端可用于最终渲染修正
- 改动：`agent_loop.py` `on_stream_end` 回调增加 `full_text` 参数
