# Mini-Code-Agent 后续演进路线图

> 当前版本 v1.1.0，P1-P83。
> 本文档收录开发过程中**有意推迟**的增强项——每一项在代码里都预留了升级插槽，
> 按优先级和工作量组织，作为后续版本的开发依据。

## 已完成的差异化方向（positioning.md 方向 1）

- [x] **CC 对照评测框架**（`benchmarks/`）：10 个标准任务、headless runner、自动化验证、Markdown 报告生成。**10/10 通过，总成本 $0.0015**。CC 结果模板已就位，待手动补齐后即可生成对比表格。

---

## 一、v0.3.0 候选：已预留插槽的核心升级（4 项）

这些是开发时明确"先简后繁"的取舍，接口已就位，实现即插即用。

### 1.1 LLM 摘要压缩（升级 SummarizeOldest 策略）✅ 已完成

> 已实现 `LLMSummarizeOldest(CompressionStrategy)`：LLM 语义摘要 + 失败回退提取式 + 防递归（一次性直连调用不经过 AgentLoop）。4 个 MockLLM 单测。作为机制实验 1 的第三个对照臂投入使用（见 `experiments/`）。P64.2 已改为默认启用（`llm_summarize=True`），`app.py` 装配时自动替换 Stage 2。

### 1.2 LLM 记忆提取（升级 MemoryExtractor）✅ 已完成

> P30 实现：regex → LLM 结构化提取（EXTRACTION_PROMPT + JSON 解析 + 词重叠去重 60%），SESSION_END hook 修复。9 个新测试，391 个全过。

### 1.3 MCP HTTP Transport ✅ 已完成

> P31 实现：HTTPTransport（httpx POST JSON-RPC）+ MCPManager http 分支 + app.py 启动接线/退出断连。5 个新测试，396 个全过。

### 1.4 工具并行执行 ✅ 已完成

> 已实现：`_act()` 两阶段——Phase 1 串行权限预检（确认弹窗不交错）→ Phase 2 全部 GRANTED 的工具 `asyncio.gather` 并行执行。单工具走快速路径不 gather。AuditLogger 三个 handler 加 `asyncio.Lock` 保护 hash chain。5 个新测试（并行计时/单工具/未知工具/取消/顺序保持），281 个全过。
- **工作量**：中（~100 行改造 + UI 适配 + 测试）
> **P38 进一步升级为流式工具执行**：工具调用在 LLM 流式响应期间组装完成即执行（IncrementalAssembler + would_ask 权限预判），实测提前 400-550ms。`streaming_tool_execution` 可关闭回退。

---

## 二、v0.4.0 候选：UI/交互增强（4 项）

### 2.1 /theme 命令切换主题 ✅ 已完成

> 已实现：三套主题（default/dark/light）全面接入 6 个 UI 文件（terminal/input_handler/trace/teach/board/themes），`/theme` 列出/切换/持久化（`~/.mini-agent/.theme`），运行时切换即时生效（prompt session 重建 + 共享 theme 引用）。7 个新测试，276 个全过。
- **工作量**：中（改色引用面较广，~200 行）

### 2.2 SubAgent 进度实时面板 ✅ 已完成

> 已实现：`ui/board.py` SubAgentBoard（Rich Live + Table，4fps 刷新，transient 收起）+ `SubAgentManager.active_snapshots()` 公开快照接口（agent_id/任务/阶段/工具数/耗时）。`/spawn wait` 和 `/team` 阻塞期间自动显示面板，完成后收起展示结果。7 个新测试，250 个全过。

### 2.3 /team 和 /spawn 命令入口 ✅ 已完成

> 已实现：`/spawn` 完整子命令集（single/parallel/list/wait/cancel/--isolated）+ `/team` 命令（Planner 分解 + 并行 SubAgent + 汇总报告 + --isolated）。Application 装配 SubAgentManager + WorktreeManager。create_for_role 接线完成（Planner 用 planner_profile、Worker 用 worker_profile）。SubAgentSpawn/CompleteEvent 两个新事件。8 个新测试，243 个全过。

### 2.5 强弱模型混编配置化（机制实验结论的产品化）✅ 配置层已完成

> 已实现：`AgentConfig.planner_profile / worker_profile` 字段 + `MINI_AGENT_PLANNER_PROFILE / WORKER_PROFILE` 环境变量 + `ProviderRegistry.create_for_role(config, "planner"|"worker")` 工厂（未配置/profile 不存在时回退主模型）。5 个单测。`.env.example` 已附示例。
> **待 2.3 落地时接线**：`/team` 命令装配 AgentTeam 时改用 `create_for_role` 创建 Planner 和 Worker 的 LLM 即可（各一行）。

- **依据**：机制实验 2 验证 strong-weak 编排是帕累托最优——强 Planner + 弱 Worker 全通过且成本最低，见 `experiments/README.md`。

### 2.4 双 Esc 中断流式输出 ✅ 已完成

> 已实现：`ui/esc_watcher.py` 守护线程 + `_think` 循环 cancelled 检查。流式期间后台线程轮询 stdin 检测双 Esc（500ms 窗口），触发 `cancel()` → 下一个 chunk 处 break → 部分响应保留在 conversation → 回到输入框。Windows msvcrt + Unix select 跨平台兼容，无 TTY 时静默不可用。5 个新测试，286 个全过。

### 2.6 LLM 自主派生 SubAgent（spawn 作为工具）✅ 已完成

> 已实现：`spawn_agents` 工具注册到 ToolRegistry，LLM 在 ReAct 循环中可自主派生 SubAgent 并行执行任务。ToolContext 注入 SubAgentManager，递归防护双保险（SubAgent clone 时 unregister + ToolContext.subagent_manager=None），system prompt 补使用指引。5 个新测试，262 个全过。
- **要做什么**：
  1. `SpawnAgentTool(Tool)` — 新工具注册进 ToolRegistry，schema 含 `tasks: list[str]`（并行任务列表）和可选 `isolated: bool`。execute 调 `subagent_manager.spawn_parallel + wait_all`，结果汇总为 ToolResult 回传 LLM
  2. system prompt 补一条使用指引：多个独立子任务时可用 spawn_agents 并行处理
  3. 进度显示降级方案：工具执行发生在 ReAct 循环内，紧邻 StreamRenderer 的流式 Live——SubAgentBoard 的 Live 会撞车（Rich 同一 Console 仅允许一个 Live）。两个选项：
     - 简单：ACT 阶段不开面板，改用普通打印行（spawn 时打一行、每个完成时打一行）——零冲突
     - 完整：把面板整合进 StreamRenderer 的 Live 区（单 Live 复合布局），改动大，参考 CC 的做法
- **插槽位置**：Tool ABC + ToolRegistry 注册即可；SubAgentManager 全部可复用；ToolContext 已携带 event_bus 但需要能访问 subagent_manager（可通过 ToolContext.config 或新增字段注入）。
- **注意点**：递归防护——SubAgent 内部的 ToolRegistry 是克隆的，必须把 spawn_agents 从克隆表中过滤掉，否则子代理再派生子代理会失控；工具执行有超时（复用 wait_all timeout）。
- **工作量**：中（工具 ~60 行 + 注入改造 ~30 行 + 进度打印 ~20 行 + 测试）

---

## 三、v0.5.0 候选：工程深化（4 项）

### 3.1 TOML 配置文件支持 ✅ 已完成

> 已实现：`ConfigLoader._load_toml()` + `_merge()` 深度合并 + `_merge_mcp()` MCP 服务器处理。优先级栈：defaults → user `~/.mini-agent/config.toml` → project `.mini-agent/config.toml` → .env → env → profiles → CLI。`_apply_cli` 泛化支持所有子配置（不限于 llm.*）。`config.toml.example` 示例。6 个新测试，298 个全过。

### 3.2 PRE_LLM / SESSION_END Hook 接线 ✅ 已完成

> 已实现：PRE_LLM 在 _think() LLM 调用前触发（含 BLOCK 能力阻止调用），SESSION_END 在 run() finally 触发。两个内置 hook：PRE_LLM 自动注入 PersistentMemory 记忆到 system prompt，SESSION_END 自动调 MemoryExtractor 提取偏好（auto_extract 配置首次生效）。4 个新测试，290 个全过。

### 3.3 会话自动保存 ✅ 已完成

> 已实现：每轮对话/斜杠命令后自动保存（30s 节流 + force 绕过），`SessionMetadata.closed_cleanly` 标志（正常退出 finally 翻 True，硬杀进程留 False 即崩溃信号），启动时检测同目录最近崩溃会话并 ask_yes_no 提示恢复（拒绝则标记已关闭不再重复询问）。顺带修复 `/session load` 的 ToolContext 过期引用缺陷（统一走 `_adopt_session`）。7 个新测试，269 个全过。

### 3.4 上下文溢写（Context Overflow 兜底）✅ 已完成

> 已实现：`ContextManager.ensure_fits(conversation, max_tokens)` 最终兜底——超窗口时强制 SlidingWindow 截断到 85% 水位。`_think()` 在 LLM 调用前预检，截断后重建 api_messages。2 个新测试，292 个全过。

---

## 四、v1.0.0 里程碑：稳定与生态（远期）

| 项 | 说明 |
|---|---|
| 接口冻结 ✅ | Tool / LLMProvider / HookFn / CompressionStrategy ABC 定稿（CHANGELOG.md），v1.0.0 语义版本承诺向后兼容 |
| 覆盖率门禁 ✅ | pytest-cov 80.36%（排除 TTY/MCP 层后），fail_under=80 作为 CI 合并条件 |
| PyPI 发布 ✅ | P33 实现 + 已成功发布：pip install mini-code-agent 可用 |
| 插件生态 ✅ | P83 实现：`extensions/plugin_loader.py` 四钩子契约（register/register_tools/commands/skills）+ 双通道发现（`mini_agent.plugins` entry point + `plugin_dirs` 本地文件），`/plugins` 命令展示 |
| Streaming 中间态 ✅ | P23 实现：on_tool_call_assembling 回调 + Diff 预览（整行背景色 diff） |
| 文件变更汇总 ✅ | P24 实现：轮末显示本轮文件清单（+绿新建/~黄修改/-红删除）+ delete_file 专用工具（第 8 个内置工具，当前 12 个） |
| 上下文感知 ✅ | P25 实现：启动自动注入项目指令文件（AGENT.md/CLAUDE.md/.mini-agent/instructions.md 优先级递减）+ 用户级全局指令 |
| 对话分叉/回滚 ✅ | P26 实现：/undo 轮次回滚 + /fork 深拷贝分叉（差异化能力——CC 服务端历史做不到） |
| 操作级撤销 ✅ | P27 实现：每轮文件快照（5 轮保留/30MB 上限/磁盘存储会话结束清空），/undo 新建删掉/修改还原/删除找回 |
| 工具链录制/回放 ✅ | P28 实现：EventBus 订阅式录制 + _execute_single_tool 安全等价回放（权限/hook/快照全走） |
| 成本仪表盘 ✅ | P29 实现：LLMResponseEvent 扩展 + CostTracker 订阅者（第 5 个）+ [cost] 配置计价 + 预算 80/100 警告 |
| 持久化任务系统 ✅ | P32 实现（S12 补全）：TaskStore 磁盘持久 + /todo 命令 + blockedBy 依赖追踪 + 解锁提示；P74 歧义前缀检测 + 最短唯一前缀显示 |
| Windows 终端适配 ✅ | P34 实现：UTF-8 stdio 加固 + 物理行感知流式渲染 + EscWatcher join + ask_yes_no 兜底 + emoji 降级；P34.3 实战补修：bash GBK 三级解码 + git 命令 human-in-the-loop 硬闸门 + mintty 秒退/代理字符崩溃修复 + terminal-guide.md 终端指南 |

---

## 五、差异化方向（来自 positioning.md，与上面技术项正交）

| 方向 | 状态 | 说明 |
|---|---|---|
| CC 对照评测 | ✅ 已完成 | benchmarks/ 框架 + 10/10 数据 |
| 机制透明度演示 | ✅ 已完成 | /trace 命令实时展示 ReAct 内部状态（阶段/权限判定+依据/工具耗时/LLM 元信息） |
| 垂直场景定制 | ✅ 已完成 | `/explain` 教学模式（TeachRenderer 确定性面板 + Skill 辅助）+ `/audit` 合规审计（EventBus JSONL）+ offline-ollama 内网 Skill |
| 机制实验 | ✅ 已完成 | `experiments/` 压缩策略 A/B（none/extractive/llm 三臂）+ 强弱模型混合编排（三臂），数据见 experiments/README.md |
| 开源社区 | ✅ 已完成 | PyPI 已发布（pip install mini-code-agent）+ README 英文化 + "the readable agent" 定位 |

---

## 六、剩余待办清单（P36 后的完整盘点）

### 待用户手动操作（代码侧已就绪）

| 项 | 操作 |
|---|---|
| Anthropic Provider 验证 | 代码就绪（P37 已加 prompt 缓存三处标记）但从未连接真实 Claude API——待有 API key 时验证 4 项 + 缓存命中（见 checklist Phase 5/37） |
| CC 对照评测数据补齐 | benchmarks/ 的 CC 结果模板需手动用 CC 跑 10 个任务记录（可选） |

### 待做实验

| 项 | 说明 | 工作量 |
|---|---|---|
| ✅ **死循环诱导实验** | 5 场景 × 2 臂实测：迭代上限是唯一可靠硬熔断，same-tool-6x 在真实 LLM 下从未触发（LLM 每次微调参数绕过签名检测）。详见 experiments/README.md 实验 3 | 已完成 |
| ✅ **压缩-重读膨胀根治** | P36 双层修复：①>50K 工具结果溢写磁盘只留预览（源头减量，SubAgent 同样受保护）；②压缩后在摘要注入"已读文件清单"（断重读循环）。详见 tech-notes §36 | 已完成 |

### 待做（可实现，按需推进）

| 项 | 说明 | 工作量 |
|---|---|---|
| ✅ 插件生态（plugin_loader） | 第三方 pip 包（`mini_agent.plugins` entry point）/ 本地 `.py` 文件（`plugin_dirs`）注册工具/命令/技能；四钩子契约、三层异常隔离、`disabled_plugins` 禁用、`/plugins` 展示。详见 tech-notes §83 | 已完成 |
| Anthropic Provider E2E 验证 | 代码就绪（含 P37 prompt 缓存），注册 Anthropic Console 获取 API key 即可验证流式/tool_use/thinking/token 计数 | ~2 小时 |
| CC 对照评测数据补齐 | `benchmarks/` 的 CC 结果模板需手动用 CC 跑 10 个任务记录（可选） | — |

### 已知限制（各文档的"诚实边界"统一收录于此）

**Pane Worker（`/spawn --pane`）：**
- cancel 是尽力而为——停止等待收集，不强杀窗格进程
- wait 超时（900s）后完成的结果成孤儿，可手动查 `~/.mini-agent/workers/<id>.result.json`
- macOS 窗格由 tmux 覆盖，不做 iTerm2 专属后端

**远程/浏览器模式（`--remote`）：**
- 无 TLS（明文 `ws://`），可选 token 认证（`--remote-token`）但不加密传输
- 服务器重启后丢失会话（远程模式未接入 SessionStore）
- 浏览器图片仅支持公网 URL（本地文件路径因浏览器安全策略无法加载）
- 所有客户端共享同一会话（无独立会话隔离）

**上下文压缩：**
- bash 命令修改的文件无法被 /undo 恢复（无文件系统快照）
- `aggregate_spill_chars` < 单文件大小的极端参数下，豁免读回计入累计会链式溢写-读回（默认 200K 无此问题）

**Anthropic Provider：**
- 代码就绪含 prompt 缓存，但从未连接真实 Claude API 进行 E2E 验证

### 明确不做（有意决策，非遗漏）

| 项 | 理由 |
|---|---|
| S14 Cron 定时调度 | 终端交互工具用 OS 的 cron/Task Scheduler 更合适 |
| bash 文件变更跟踪 | 需要文件系统快照对比，成本远超收益（undo/汇总的已知盲区） |

## 七、优先级建议

如果按"用户可感知价值 / 工作量"排序，建议实施顺序：

1. ~~2.3 /spawn + /team 命令~~（✅ 已完成）
2. ~~2.5 强弱模型混编配置化~~（✅ 配置层 + /team 接线已完成）
3. ~~2.2 SubAgent 进度面板~~（✅ 已完成）
4. ~~2.6 LLM 自主派生 SubAgent~~（✅ 已完成）
5. ~~3.3 会话自动保存~~（✅ 已完成）
6. ~~2.1 /theme 命令~~（✅ 已完成）
7. ~~1.4 工具并行~~（✅ 已完成）
8. 其余按需推进

> 1.1 LLM 摘要压缩已在 P11 完成，P64.2 改为默认启用（`llm_summarize=True`）。

---

## 八、代码质量清单（由 todo-code-quality.md 并入）

代码审查发现的问题跟踪——死代码清理、重复逻辑抽取、扩展点接入。

### ✅ 已修复

- ✅ `openai_provider.py` `count_tokens` 绕过 `token_counter` 模块（直接 `len//4`）→ 改为调用 `token_counter.count_tokens()`
- ✅ `anthropic_provider.py` `count_tokens` 同上问题 → 同上修复
- ✅ `models/message.py` `__import__("json")` 反模式 → 改为模块顶部 `import json`

### ✅ 中优先级

#### ✅ markdown 围栏剥离三处重复
- `memory/extraction.py:140`
- `memory/recall.py:83`
- `memory/consolidation.py:103`

三处都在做同样的 strip ` ```json ... ``` ` 逻辑。✅ 已抽取为 `memory/_utils.py` 的 `strip_json_fence(text) -> str` 函数。

#### ✅ LLM 流式调用+组装五处重复
- `memory/extraction.py` — 提取记忆
- `memory/recall.py` — 选择性召回
- `memory/consolidation.py` — 语义合并
- `memory/compressor.py` — LLM 摘要压缩（`_summarize`）
- `core/planner.py` — 任务分解

五处"流式调 LLM → 收集 chunk → 组装响应"的重复模式。✅ 已抽取：`assemble_response()` 从 `openai_provider.py` 移至 `llm/base.py`（provider 无关），新增独立函数 `complete(llm, messages, ...)` 一次调用完成流式收集+组装。五处调用点均已简化为 `await complete(self._llm, messages)`。

### ✅ 低优先级

#### ✅ shell 检测逻辑重复
- `app.py` 和 `core/subagent.py` 各自 `os.environ.get("SHELL")` 判断 shell 类型
- ✅ 已抽取为 `config/environment.py` 的 `detect_shell() -> str`，两处调用点改为 `detect_shell()`

#### ✅ `os.environ` 直接访问绕过 config
- 同上两处直接读环境变量而非通过 ConfigLoader，对测试隔离有影响
- ✅ 随 shell 检测抽取一并解决：两处调用点不再直接读 `os.environ`，环境读取收敛到 `config/environment.py` 单点，测试可 monkeypatch `detect_shell` 隔离

#### ✅ 权限检查逻辑内部重复
- `permission.py:156-193`（`check()`）和 `permission.py:266-285`（`_check_rules_only()`）
- ✅ `check()` 改为先调 `_check_rules_only()`，匹配则直接返回，否则走默认模式。消除了 DENY→ALLOW→session grants 的重复遍历

#### ✅ 路径 resolve 重复
- `security/sandbox/seatbelt.py:42,45` 和 `security/sandbox/bwrap.py:30,33`
- ✅ 抽取为 `security/sandbox/__init__.py` 的 `resolve_path(path) -> str`，两处调用点改为 `resolve_path(path)`

#### ✅ 静默 except（约 35 处）
- 大部分是有意的 fail-safe（记忆提取/召回/合并失败不阻断主流程）
- ✅ 14 个文件共 35 处静默 except 加入 `logger.warning`（hook 触发失败等关键路径，10 处）或 `logger.debug`（I/O 与解析降级，25 处），均带 `exc_info=True`。原有降级行为不变

---

### ✅ 死代码清理（27 处）

27 处死代码分为三类：**真正遗忘应接入的**（6 处，✅ 已全部修复）、**设计变更后的残留物**（5 处，✅ 已全部删除）、**有意预留的扩展点**（16 处）。

---

#### ✅ 真正遗忘、应该接入（6 处）已全部修复

| # | 项 | 修复内容 |
|---|---|---|
| 1 | `LLMResponse.model` | `_stream_once()` 中 `assemble_response` 后设置 `response.model = self.model_name` |
| 2 | `TokenUsage.cache_read_input_tokens` | `LLMResponseEvent` 新增缓存字段，`CostTracker` 按 `cache_read`/`cache_creation` 差异化定价（pricing 支持 `cache_read`、`cache_creation` 键，未配则退回 input 价） |
| 3 | `AgentConfig.enable_plan_mode` | `app.py` 初始化时 `agent_loop.plan_mode = config.enable_plan_mode`；默认值改为 `False`（用户需显式开启） |
| 4 | `on_thinking_delta` 终端接入 | `Terminal.feed_thinking()` + `app.py` 回调：dim italic 样式输出思考过程 |
| 5 | `PermissionRequest.matched_rule` | `PermissionManager.last_matched_rule` → `PermissionCheckEvent.matched_rule` → `AuditLogger` 记录 |
| 6 | `count_message_tokens()` / `count_messages_tokens()` | `ContextManager.count_message()` 改用 per-tool-call +3 开销精确计数；删除 `token_counter.py` 中的死函数 |

---

#### ✅ 设计变更后的残留物（5 处）已全部删除

| # | 项 | 处理 |
|---|---|---|
| 1 | `LLMStreamChunkEvent` | ✅ 从 `models/events.py` 和 `events/types.py` 删除 |
| 2 | `LLMErrorEvent` | ✅ 从 `models/events.py` 和 `events/types.py` 删除 |
| 3 | `ToolFilter` + `ToolFilterContext` | ✅ 删除 `security/tool_filter.py` 整个文件，从 `security/__init__.py` 移除导出 |
| 4 | `AgentState.pending_tool_calls` | ✅ 从 `core/agent_state.py` 删除字段，移除不再需要的 `ToolCall` 导入 |
| 5 | 5 个异常类 | ✅ 删除 `core/errors.py` 整个文件，从 `core/__init__.py` 移除导入和导出 |

---

#### 🟢 有意预留的扩展点（15 处；#1/#2/#3/#4/#6/#7/#8/#9/#10/#11/#12/#13/#14/#15 已接入，#5 删除）


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

###  ✅ 文档与仓库卫生

以下问题来自 `analysis-shortcomings.md` 的逐条验证，已确认为真实问题。

#### ✅ spec.md 与现状脱节（已验证）
- ~~`docs/spec.md` 自修正写"8 个内置工具"~~ ✅ 已修正为 12
- ✅ spec.md 目录树已删除不存在的 `config/schema.py`、`core/errors.py`、`security/tool_filter.py`
- spec.md 目录树写"6 core tools"——属历史设计文档，已有 disclaimer 说明

#### ✅ .gitignore 遗漏（已验证）
- `.coverage` / `htmlcov/` — ✅ 已在 .gitignore 中（原有）
- `.pytest_cache/` — ✅ 已追加到 .gitignore
- `.ruff_cache/` — ✅ 已追加到 .gitignore
- `experiments/results/` — ✅ 已追加到 .gitignore，已 `git rm --cached` 清除 31 个已追踪的 JSON 文件

---

### ✅ 上下文管理增强

对照 `D:\PythonProjects\mewcode-python\mewcode\context\manager.py` 及 `agent.py` 逐项对比。

#### ✅ ① 聚合工具结果预算（含三个配套机制）已修复（P64.1）

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

#### ✅ ② LLM 摘要压缩接入 已修复

`MemoryConfig.llm_summarize = True`（默认开启）：`app.py` 装配 Compressor 时用 `LLMSummarizeOldest(self._llm)` 替换 `SummarizeOldest`。LLM 调用失败自动回退到抽取式摘要（已内置）。`llm_summarize = false` 恢复旧行为。2 个测试覆盖。

修复两个问题：
- **压缩检查移到 LLM 调用前**：原来只在 OBSERVE 阶段（工具结果追加后）检查压缩，纯对话场景（无工具调用）永远不触发压缩。移到 `_think()` 的 `ensure_fits` 之前，每次 LLM 调用前先尝试 LLM 摘要压缩，不够再用 SlidingWindow 兜底。
- **压缩摘要前缀加明确指令**：压缩后 LLM 不信任摘要，去磁盘翻会话文件导致大量无效工具调用和权限弹窗。在摘要前缀中加 "this is the authoritative record of earlier conversation. Do NOT search session files or disk to recover history"。

#### ✅ ③ 压缩熔断器 已修复

`ContextManager` 内置熔断器：连续 N 次压缩无效（token 未减少）后跳过后续压缩。`MemoryConfig.compress_max_failures = 3`（0 = 禁用）。成功压缩自动重置计数。3 个测试覆盖。

#### ✅ ④ 压缩双阈值（硬阈值绕过熔断器）已修复（P65）

**问题**：mini 的熔断器开启后**所有**压缩都被阻断，包括上下文即将溢出的紧急情况。

**mewcode 实现**（`context/manager.py` `auto_compact`）：
- 软阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - AUTO_COMPACT_SAFETY_MARGIN(13K)` → 正常压缩，受熔断器控制
- 硬阈值：`context_window - SUMMARY_OUTPUT_RESERVE(20K) - MANUAL_COMPACT_SAFETY_MARGIN(3K)` → **强制压缩，绕过熔断器**
- 效果：200K 窗口下，167K 触发软压缩，177K 触发硬压缩

**已实现**（P65）：`MemoryConfig.hard_compression_threshold = 0.90` 独立配置。`check_and_compress()` 熔断器检查加 `and not self.needs_hard_compression`：软阈值被熔断器阻断时，硬阈值仍走完整三级级联。

#### ✅ ⑤ token 驱动的保留窗口（替代固定 6 条消息）已修复

**问题**：`SummarizeOldest.KEEP_RECENT = 6` 固定保留最近 6 条消息。6 条短消息可能只有 1K token（浪费空间），6 条长消息可能有 40K token（保留太多）。

**mewcode 实现**（`context/manager.py` keep-recent 窗口）：
- 从尾部反向扫描，累计 token 数
- 停止条件：累计 ≥ `KEEP_RECENT_TOKENS(10K)` **且** 消息数 ≥ `MIN_KEEP_MESSAGES(5)`
- 硬顶：不超过 `KEEP_MAX_TOKENS(40K)`
- 工具对对齐：keep 边界不切断 tool_use/tool_result 配对

**已实现**：`_compute_keep_split()` 替代固定 `KEEP_RECENT = 6`，`SummarizeOldest` 和 `LLMSummarizeOldest` 均使用 token 驱动的保留窗口。常量 `KEEP_RECENT_TOKENS=10K` / `MIN_KEEP_MESSAGES=5` / `KEEP_MAX_TOKENS=40K`（⑩/P68 起为绝对上限，实际随压缩目标缩放）。7 个新测试覆盖短消息全保留 / 长消息少保留 / 硬顶 / 最少消息数 / 双阈值停止。

#### ✅ ⑥ 摘要 prompt 结构化 已修复（P67）

**问题**：mini 的 `_SUMMARY_PROMPT` 只列 4 条通用指令，摘要质量不稳定。

**mewcode 实现**（`context/manager.py` `SUMMARY_PROMPT`）：
- 要求输出 `<analysis>` + `<summary>` 两个 XML 块
- analysis 覆盖 9 个维度：主请求、技术概念、涉及文件/代码、错误/修复、问题解决步骤、所有用户消息、待做任务、当前工作进展、可选下一步
- summary 要求简洁、保留所有关键信息

**已实现**：`_SUMMARY_PROMPT` 重写为 `<analysis>`（时间线梳理 + 自查）+ `<summary>`（9 节结构化输出）；新增 `_extract_summary()` 只把 `<summary>` 块注入对话（analysis 草稿不进上下文），无标签回退完整输出、只有 analysis（截断）时剥离草稿触发抽取式回退。mini 适配：prompt 明确"近期消息已原样保留，摘要只替换旧历史"；不需要 mewcode 的 "Do NOT call tools" 警告（`_summarize()` 直连不带工具）。真实 LLM E2E 验证 9 节摘要完整、无草稿泄漏。5 个新测试。详见 tech-notes §67。

#### ✅ ⑦ 摘要重试（P72 偶发重试 + P73 超长收缩重试）已修复

**问题**：LLM 摘要调用偶发网络错误时直接回退到抽取式截断，丢失语义摘要。

**mewcode 实现**：最多重试 3 次；如果摘要 prompt 本身太长，丢弃最旧 20% 的消息后重试。

**已实现**：
- P72：`SUMMARY_RETRIES=2`，偶发失败先重试再落抽取式，重试/穷尽有 WARNING 日志
- P73：`_is_prompt_too_long()`（400/413 一律算 + 错误消息关键词兜底）识别超长后，丢弃最旧 20% 可摘要消息（头部旧压缩摘要绝不丢——它是更早历史的唯一记录）并把字符 cap 缩 20% 后重试；`MAX_SHRINKS=3`，与偶发重试预算独立；穷尽后立即回退，不用相同的超长请求烧偶发预算（真实运行实测：相同请求重试必然相同失败）。真实 API 全管道验证：6.2M 字符 → 真 400 → 2 轮收缩 → 3.98M 字符成功产出 9 节摘要，埋点约定存活。详见 tech-notes §73。

#### ⑧ 压缩后重注入环境上下文和记忆 — 不适用（架构差异）

mewcode 把记忆注入到 `history`（消息列表）里作为 `user` 消息，压缩 `replace_history()` 后需要重注入。mini 把记忆注入到 `system_prompt`（独立字段），压缩只操作 `messages` 不动 `system_prompt`，记忆天然免疫压缩，不需要重注入。

#### ✅ ⑨ 最小前缀检查 已修复

**问题**：可摘要部分（keep 窗口之前的消息）很少时，压缩开销大于收益。

**mewcode 实现**：可摘要前缀 < `MIN_SUMMARIZE_PREFIX_TOKENS(2K)` token 时跳过压缩。

**已实现**：`memory/compressor.py` 新增 `MIN_SUMMARIZE_PREFIX_TOKENS = 2000` 常量 + `_prefix_tokens()` 辅助函数。`SummarizeOldest` 和 `LLMSummarizeOldest` 的 `compress()` 在 split 计算后、实际摘要前检查前缀 token 量，不足 2K 时跳过——与 mewcode 行为对齐。1 个新测试覆盖。

#### ✅ ⑩ 保留窗口按压缩目标缩放（P68）已修复

**问题**：⑤ 的 `KEEP_RECENT_TOKENS=10K` / `KEEP_MAX_TOKENS=40K` 是绝对常量。窗口 ≤ 13K 时保留下限不小于压缩目标（75% × 窗口），摘要级数学上永远达不到目标，压缩全部退化为 SlidingWindow 硬截断 + 硬阈值每轮空转。P67 终端窗口验证（context_window=10000）实测暴露：单轮 80 次迭代烧 1M token 才被迭代上限刹住。

**已实现**：`_compute_keep_split(msgs, target_tokens)` 增加 target 参数——保留下限 `min(10K, target//2)`、硬顶 `min(40K, target)` 随目标缩放；`keep_count==0` 时兜底保留 1 条尾部消息。大窗口行为完全不变（min 取的仍是绝对值）。真实 LLM 验证：target=7500 时压缩后 7008 ≤ 7500 达标、结构化摘要存活。4 个新测试。详见 tech-notes §68。


#### ✅ ⑪ P67 验收期间连带修复的压缩链路缺陷（P69/P70/P71）已修复

九轮真实终端无污染埋点验证暴露并当场修复，详见 tech-notes §69-§71：
- **P69** DropToolResults 截断模型工作集 → 重读死循环（36 迭代→4）：Stage 1 只处理可摘要前缀
- **P70** 恢复附件预算不随窗口缩放（54K 字符附件钉死小窗口）+ 嵌套摘要 prompt 缺前传指令
- **P71** SlidingWindow 删除刚生成的摘要（有任务锚点无摘要锚点）：新增摘要锚点
---

### ✅ 远程/浏览器模式（P57）

#### 仍存在的已知局限

见本文档第六节"已知限制"章节（远程模式：无 TLS / 服务器重启丢失 / 图片仅公网 URL / 共享会话）。

#### 建议改进优先级
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

#### 追加修复
- ✅ 单端口合并：HTTP + WS 共用同一端口（process_request 拦截 GET / 返回 HTML，/ws 走 WS 升级）
- ✅ 多客户端回放修复：`_replay_history` 改为只发给当前重连客户端，不再广播
- ✅ 用户消息多客户端同步：广播 `user_message` 事件，发送端去重
- ✅ 段落换行：CSS `white-space: pre-line` + `\n\n` 替换为 div 间距块
- ✅ 滚动锁定：用户上滑后 `userScrolled` 标志禁止自动滚底，turn 结束重置
- ✅ 标题间距：h1-h4 加 margin-top/bottom
- ✅ 输入框透明滚动条
- ✅ Cancel/Permission 改走 WS 消息（去掉 HTTP POST 端点）
- ✅ 主题切换：深色（Catppuccin Mocha）+ 浅色（Catppuccin Latte），header 按钮 + localStorage 持久化 + `/theme light|dark` 命令联动

---

## 九、最新审计

### A. 缺陷/漏洞

☐ **A1【严重·fail-open】`delete_file` 完全绕过 PathGuard**
`core/agent_loop.py:787-829` 的 `_check_permission` 只把 read_file/glob/grep 路由到 read 检查、write_file/edit_file 路由到 write 检查，**delete_file 落入 else 分支（:827-829 `unrestricted_tool`）无条件 GRANTED**。工具接受任意 file_path（相对路径解析到 working_dir，delete_file.py:31-33）。自相矛盾：`security/permission.py:452` 的 `would_ask` 包含 delete_file → 流式阶段（agent_loop.py:491-494）以为会弹窗而延迟到 `_act`，但 `_act`→`_check_permission` 实际无条件放行。
失败场景：LLM 调 `delete_file("~/.ssh/id_rsa")` 或任意项目外路径，PathGuard 的敏感文件/denied_paths（config.py:41 默认拒绝 ~/.ssh）**完全不生效**，无提示直接删除。写/读受保护、删除不受，是最危险的不一致。
测试盲区：`tests/unit/test_permissions.py:495,521` 只测显式 TOOL 规则 deny delete_file，从未测"无规则时 delete_file 对项目外路径是否走 check_path"。
修复：把 delete_file 加入 write 路由分支（与 write_file/edit_file 同）+ 补测试。工作量：小（一行路由 + 测试）。

☐ **A2【高·危险命令正则可绕过】ask 模式下静默执行**
`security/permission.py:33-53` 的 19 条正则 + `_check_command_request`（:374-403）：非危险命令在 ask/allow 模式一律自动放行（:403），任何绕过正则的破坏性命令都不弹窗。已确认绕过：
- `rm --recursive --force foo`：`\brm\s+(-[a-z]*[rf][a-z]*\s+)`（:34）要求 `-` 后紧跟 `[rf]`，长选项 `--recursive` 不匹配
- `git -C /repo push`：`\bgit\s+push\b`（:40）要求 git 后紧跟 push，插入 `-C path` 绕过；`git -C x commit/reset` 同理
- `chmod -R 777 /`：`\bchmod\s+777\b`（:46）要求 chmod 后紧跟 777，加 `-R` 绕过
- `rm foo -rf`（标志后置）同样不匹配
（`bash -c "rm -rf /"`、`;`/`&&` 链、反引号因正则扫描整串仍会命中，非漏洞。）
测试盲区：test_permissions.py 无这些变体用例。工作量：小（正则加固 + 变体测试）。

☐ **A3【中·fail-open 时序】max_tokens 重试导致重复副作用**
`core/agent_loop.py:423-435`：`_think` 的 max_tokens 恢复循环在 `finish_reason=="length"` 时取消 `_streaming_tasks` 重试，但流式期间已提交并**可能已完成**的写/删工具（:497 create_task）无法回滚——`task.cancel()` 对已完成任务无效。截断重试后 LLM 再次产出同一工具调用并再次执行。
失败场景：write_file 在流截断前已落盘 → 重试后再写一次；delete_file 则第二次删除（已删→报错噪音）。非破坏性时幂等，带副作用时重复。工作量：中。

☐ **A4【中·并发】CostTracker 无锁并发累加**
`core/cost_tracker.py:57-75` `_on_response` 对 `self.usage[model]` 读-改-写；并行子 Agent 共享同一 bus 时 `rec["prompt"] += ...` 非原子。对比 AuditLogger 有 `_write_lock`（audit.py:82）保护哈希链，CostTracker 无等价保护。
失败场景：多子 Agent 并行回包，token/成本少计，预算熔断失准。属统计正确性，非安全。工作量：小（加锁）。

☐ **A5【低·安全】remote 模式多项弱点**
`remote/server.py:141` `msg.get("token") != self._token` 用 `!=` 直接比较（时序侧信道，localhost 影响小）；token 经 URL query 传递（:76）会进浏览器历史/日志；`ws://` 明文；`_ws_send`（:119）向所有 client 广播，多 client 时会话历史互相泄露。（`_process_http` :91-110 仅静态返回 HTML，无路径遍历，已确认安全。）工作量：小-中。

☐ **A6【低·正确性】spill readback 前缀判断可误判**
`memory/tool_result_cache.py:74-75` 用 `abs_path.startswith(abs(cache_dir))` 判断读回。若存在兄弟目录 `results_evil`（cache_dir=`.../results`），`.../results_evil/x` 会被误判为读回而豁免溢写。非安全问题。（PathGuard 的 spill 只读放行 path_guard.py:76-79 用 `cache_root in resolved.parents`，正确无此问题。）修复：改用 parents 判断或加分隔符。工作量：小。

### B. 真差距

☐ **B1 LLM 可自主调用的流程工具集（最大差距）**
mewcode `mewcode/tools/` 有 mini 完全没有的工具：`ask_user.py`（结构化提问 text/radio/select/checkbox + askuser_dialog）、`exit_plan_mode.py`（LLM 完成计划后主动请求审批 + plan_dialog）、`task_create/get/list/stop/update.py`（任务板暴露给 LLM）、`team_create/team_delete.py`、`enter_worktree/exit_worktree.py`、`load_skill/install_skill.py`。mini 的 12 个内置工具中，plan/worktree/skill/task 都只有斜杠命令入口（用户驱动），LLM 不能自主发起；`/plan` 是手动开关，无"计划完成→审批→自动退出"闭环。工作量：中（每工具 100-200 行）。

☐ **B2 read-before-edit 强制（FileStateCache）**
mewcode `tools/file_state_cache.py`：编辑前必须先读 + mtime_ns 未变两道门，防编辑陈旧/被外部改过的文件。mini 全库无对应机制。小成本高安全收益。工作量：小（~80 行 + 集成）。

☐ **B3 自定义 Agent 类型（.md 声明式定义）**
mewcode `agents/loader.py + parser.py` 从 `.mewcode/agents/*.md` 和 `~/.mewcode/agents/` 加载用户自定义 agent（内置 4 种也是 .md）。mini `core/agent_types.py` 是 4 种硬编码 frozen dataclass，无用户扩展路径。工作量：小-中（~200 行）。

☐ **B4 后台子代理 + 完成通知**
mewcode `agents/task_manager.py`（BackgroundTask 异步跑 + ProgressInfo）+ `agents/notification.py`（完成后注入通知）+ `agents/fork.py`（fork 当前对话上下文的 worker）。mini 的 spawn_agents 阻塞等待（comparison doc 6.2 自认的限制至今成立）。工作量：中。

☐ **B5 权限模式矩阵**
mewcode `permissions/modes.py`：default/acceptEdits/plan/bypassPermissions 四模式 × 工具类别决策矩阵。mini 有 plan 模式和 sandbox_auto_allow，但无 acceptEdits/bypass 等价物。工作量：小。

☐ **B6 指令文件 @-include**
mewcode `memory/instructions.py` 支持 `@./path @~/path` 递归引用（深度 5）。mini `memory/project_context.py` 只读单文件、8000 字符截断，无引用语法。工作量：小。

☐ **B7 远程模式 SessionStore 接入**
mewcode `remote.py` 接入 SessionManager（持久会话）；mini `remote/server.py` 零 SessionStore 引用，重启丢失会话（roadmap 已知限制已承认）。工作量：小-中。

☐ **B8 恢复附件含 skill 调用记录（微小差距）**
mewcode 压缩恢复附件含 skill 调用记录（`record_skill_invocation/snapshot_skills`），mini `memory/context.py` 无 skill 相关恢复。工作量：小。

### C. 文档过时

☐ **C1 远程认证 mini 反超但文档未反映**
`--remote-token`（server.py 8 处）让 mini 有 token 认证，mewcode `remote.py` grep 无任何 TLS/token/auth。但 comparison doc 及 roadmap 已知限制仍把"无 TLS"列为劣势——应改为"mini 有 token 认证但无 TLS 加密；mewcode 两者皆无"。

☐ **C2 hook 动作类型"四种"失实**
comparison doc 7.2 称 mewcode hook 有 command/prompt/http/agent 四种动作。核实 `hooks/executors.py`：**agent executor 是 stub（"not yet implemented"）**，实际三种可用。应改为"三种可用 + agent 未实现"。同时 mini 的"EventBus listener_dirs 覆盖观察类"论证**半成立**：能力可达但需写 Python，mewcode 是零代码 YAML 配置 + 条件表达式引擎（`conditions.py`，==/!=/=~/~= + and/or）——若要补齐零代码声明式 hook 是一个可选方向。

☐ **C3 团队文件数过时**
doc 0.1 节"mewcode 13 文件 vs mini 3 文件"过时：mewcode teams/ 实为 15 文件 2069 行；mini 多 Agent 相关约 7 文件（mailbox/team/spawn_backends/worker/subagent/task_store/agent_types）。

### 有意不做（论证仍成立，不列为待办，仅备忘）

- **Textual TUI**：mewcode 仍用 textual>=2.1；mini "Rich+ptk 补体验、不迁移" 成立
- **图片多模态**：mewcode 并无真多模态（MCP ImageContent 仅字符串化 `[image: mime]`，tool_wrapper.py:76）——非差距
- **多客户端会话隔离**：mewcode 同样单 agent 广播（remote.py:91）无隔离——非差距
- **常驻队友 transcript 恢复**：mewcode `teams/transcript.py` 独有；mini 一次性 worker 适配论证基本成立，若走向常驻队友需重评估

---

*本文档随版本迭代更新。完成一项后请把该项移入 tasks.md 对应阶段并打勾。*