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
| 文件变更汇总 ✅ | P24 实现：轮末显示本轮文件清单（+绿新建/~黄修改/-红删除）+ delete_file 专用工具（第 8 个内置工具，当前 21 个） |
| 上下文感知 ✅ | P25 实现：启动自动注入项目指令文件（AGENT.md/CLAUDE.md/.mini-agent/instructions.md 优先级递减）+ 用户级全局指令 |
| 对话分叉/回滚 ✅ | P26 实现：/undo 轮次回滚 + /fork 深拷贝分叉（差异化能力——CC 服务端历史做不到） |
| 操作级撤销 ✅ | P27 实现：每轮文件快照（默认 5 轮保留可配置/30MB 上限/磁盘存储会话结束清空），/undo 新建删掉/修改还原/删除找回；B15 增强：--code-only/--conv-only 选择性恢复 + undo_keep_turns 容量配置 |
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
| Anthropic Provider 验证 | 流式/tool_use/思考流已经 Anthropic 协议端点真实验证（tech-notes §110）；剩签名密码学校验 + prompt 缓存命中待官方 Claude API key（见 checklist Phase 5/37） |
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
| Anthropic Provider E2E 验证 | 流式/tool_use/思考流已经 Anthropic 协议端点真实验证（tech-notes §110）；签名密码学校验与 prompt 缓存命中仍需官方 Anthropic API key 补验 | ~0.5 小时 |
| CC 对照评测数据补齐 | `benchmarks/` 的 CC 结果模板需手动用 CC 跑 10 个任务记录（可选） | — |

### 已知限制（各文档的"诚实边界"统一收录于此）

**Pane Worker（`/spawn --pane`）：**
- cancel 是尽力而为——停止等待收集，不强杀窗格进程
- wait 超时（900s）后完成的结果成孤儿，可手动查 `~/.mini-agent/workers/<id>.result.json`
- macOS 窗格由 tmux 覆盖，不做 iTerm2 专属后端

**远程/浏览器模式（`--remote`）：**
- 无 TLS 加密（明文 `ws://`），有可选 token 认证（`--remote-token`）但不加密传输
- 会话已持久化（每轮自动保存 + 启动自动恢复本项目最新未关闭会话）；与终端模式的差异：恢复不询问（启动时无客户端可问），正常关闭后重启从新会话开始（可 /session load 手动恢复）
- 浏览器图片仅支持公网 URL（本地文件路径因浏览器安全策略无法加载）
- 所有客户端共享同一会话（无独立会话隔离）

**上下文压缩：**
- bash 命令修改的文件无法被 /undo 恢复（无文件系统快照）
- `aggregate_spill_chars` < 单文件大小的极端参数下，豁免读回计入累计会链式溢写-读回（默认 200K 无此问题）

**Anthropic Provider：**
- 流式/tool_use/思考流已经 Anthropic 协议端点（阿里云 MaaS 网关 + deepseek-v4-pro）真实验证；签名密码学校验与 prompt 缓存命中从未连接官方 Claude API 验证（第三方端点不校验签名、缓存字段不回传）

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

见本文档第六节"已知限制"章节（远程模式：无 TLS / 图片仅公网 URL / 共享会话；会话持久化已接入）。

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

✅ **A1【严重·fail-open】`delete_file` 完全绕过 PathGuard**（已修复）
**原问题**：`_check_permission` 的路由只覆盖 read_file/glob/grep（read）和 write_file/edit_file（write），delete_file 落入 else 分支无条件 GRANTED。与 `would_ask` 含 delete_file 自相矛盾——流式阶段以为会弹窗而延迟，实际直接放行。
**修复**：`agent_loop.py:816` 把 delete_file 加入 write 路由 `("write_file", "edit_file", "delete_file")`，与写/编辑工具走同一 `check_path(write)` 管道。回归测试 `test_delete_file_routes_through_path_check`：LLM 调 `delete_file("~/.ssh/id_rsa")` → PathGuard 拒绝 → tool_result.is_error。spec.md 权限路由图与非写步骤剥离列表同步更新。

✅ **A2【高·危险命令正则可绕过】ask 模式下静默执行**（已修复）
**原问题**：非危险命令在 ask/allow 模式自动放行，任何绕过正则的破坏性命令都不弹窗。确认绕过：`rm --recursive --force foo`/`rm foo -rf`（长选项/标志后置）、`git -C /repo push`（全局选项插在 git 与子命令间）、`chmod -R 777 /`（加 -R）。
**修复**：`security/permission.py` 三类模式加固——rm 容忍长选项与标志后置（`(?:[^\n]*\s)?(?:-[a-z]*[rf]|--recursive|--force)`）；chmod 容忍前置选项与 0777（`(?:-[a-zA-Z]+\s+)*[0-7]*777`）；新增 `_GIT_PREFIX` 常量吞掉 git 全局选项（-c/-C 带值 + attached 形式），7 个 git 危险子命令统一前缀化。新增 `test_dangerous_command_bypass_variants_flagged`（绕过变体须命中）+ `test_dangerous_command_safe_variants_not_flagged`（安全命令零误报，如 `git -C /x status`/`chmod 644`/`rm -i`/`git checkout -b`）。真实运行验证：`chmod -R 777` 与 `git -C . push` 均触发 `dangerous command detected` 确认框。
**诚实边界**：正则黑名单本质不可能穷尽（死循环实验已证 LLM 可变形绕过签名），加固只堵已知常见形态，是减速带非围墙——迭代上限 + 命中后人工确认才是真护栏（已在代码注释与 CHANGELOG 注明）。

✅ **A3【中·fail-open 时序】max_tokens 重试导致重复副作用**（已修复）
**原问题**：`_think` 的 max_tokens 恢复循环在 `finish_reason=="length"` 时取消 `_streaming_tasks` 重试，但流式期间已 eager 提交并**可能已完成**的写/删工具无法回滚——`task.cancel()` 对已完成任务是空操作。截断重试后 LLM 再产出同一工具调用并再次执行 → write_file 双写、delete_file 双删。
**修复**：`agent_loop.py` 流式执行块把 `_WRITE_TOOLS`（write_file/edit_file/delete_file）无条件延迟到 `_act`——它只在 max_tokens 恢复确定最终非截断响应后才执行，从源头消除"eager 已完成但无法回滚"的窗口。回归测试 `test_write_tool_not_double_executed_on_truncation_retry`：截断响应含中途 flush 的 write（内容 A1）+ 重试 write（内容 A2），断言 `execute()` 恰好调用一次 `['A2']`（修复前为 `['A1','A2']` 双执行）。测试用 YieldingMockLLM 在 chunk 间让出事件循环以确定性复现竞态（纯同步 mock 里 eager 任务启动前即被取消、bug 隐身）。
**残留（未纳入本次，honest boundary）**：bash 的带副作用命令（`echo>file`/`mkdir`/`npm install` 等非危险命令）仍 eager 流式执行，截断重试仍可能双跑；危险 bash 已由 would_ask 延迟。彻底解决需延迟所有 bash（牺牲流式延迟收益），A3 按 roadmap 明列的 write_file/delete_file 收口，bash 残留单列备忘。

✅ **A4【中·并发】CostTracker 无锁并发累加**（已修复）
**原问题**：`_on_response` 对 `self.usage[model]` 读-改-写非原子，并行子 Agent 共享同一 EventBus 时可能丢失更新（token/成本少计、预算熔断失准）。
**修复**：`cost_tracker.py` 新增 `self._lock = asyncio.Lock()`，`_on_response` 的整个读-改-写在 `async with self._lock` 内执行（与 AuditLogger 的 `_write_lock` 模式一致）。`end_turn`/`flush_to_ledger` 只在主循环单线程路径调用，不加锁（无并发）。回归测试 `test_concurrent_on_response_no_lost_updates`：200 个事件 `asyncio.gather` 并发发射，断言 prompt/completion/calls 精确等于 200。

✅ **A5【低·安全】remote 模式多项弱点**（已修复可修部分）
**原问题**：4 项弱点——① token 非常量时间比较（时序侧信道）；② token 经 URL query 传递（浏览器历史/日志泄露）；③ ws:// 明文；④ 多 client 广播历史泄露。
**修复**：① `hmac.compare_digest` 替代 `!=`（constant-time，消除时序侧信道）；② 启动输出加安全提醒（token 在 URL、建议 reverse proxy + TLS），纠正"token = 安全"的错误预期。回归测试 `test_token_comparison_uses_constant_time`（源码检查确认 compare_digest 存在）。
**有意保留**：③ TLS 需证书 + 架构变更（建议 reverse proxy，非 agent 职责）；④ 多 client 共享会话是设计意图（roadmap 已知限制已注明"无独立会话隔离"）。

✅ **A6【低·正确性】spill readback 前缀判断可误判**（已修复）
**原问题**：`is_spill_readback` 用 `abs_path.startswith(abs(cache_dir))` 判断读回，字符串前缀匹配会把兄弟目录 `.../cache_evil/x`（cache_dir=`.../cache`）误判为读回而豁免溢写。
**修复**：改用路径成分包含判断——`Path(raw).resolve()`，`resolved == cache_root or cache_root in resolved.parents`（与 PathGuard 的 spill 只读放行 path_guard.py:76-79 同一正确模式）；顺带删除不再使用的 `os` import。回归测试 `test_is_spill_readback_sibling_dir_not_misjudged`：`cache_evil/x` 不命中、真 cache 目录仍命中；移除修复时兄弟目录断言失败。

### B. 真差距

✅ **B1 LLM 可自主调用的流程工具集（核心批次已完成）**
mewcode `mewcode/tools/` 的流程工具：`ask_user.py`（结构化提问）、`exit_plan_mode.py`（计划审批）、`task_create/get/list/stop/update.py`（任务板）、`team_create/team_delete.py`（常驻队友）、`enter_worktree/exit_worktree.py`（工作树）、`load_skill/install_skill.py`（技能）。其中 ask_user/exit_plan_mode/task CRUD/load_skill/install_skill 已在 B1 核心+技能两批次实现；仅 team(依赖常驻队友系统) 和 worktree(使用场景窄) 未做。
**已实现（核心批次 6 + 技能批次 2 = 8 工具）**：核心批次——`ask_user`（结构化提问 + 终端 Rich Panel UI）、`exit_plan_mode`（计划审批闭环）、`task_create`/`task_get`/`task_list`/`task_update`（任务板 CRUD）；技能批次——`load_skill`（激活已安装技能）、`install_skill`（从路径或 git URL 安装技能，不弹权限）。ToolContext 扩展 4 字段（task_store/agent_loop_ref/ask_user_callback/skill_registry），app.py 装配注入。工具总数 12→20。20 个新测试 + 集成测试工具注册断言更新。真实 LLM 验证 task_create 自主调用成功。
**后续批次（未纳入本次）**：worktree 工具（enter/exit）、team 工具（create/delete）。

✅ **B2 read-before-edit 强制（FileStateCache）**（已完成）
**问题**：edit/write 可基于陈旧内容盲目修改——从未读过、或读后被外部改过的文件。
**实现**：新增 `tools/file_state_cache.py` `FileStateCache`（会话级 {绝对路径: mtime_ns} 缓存，两道门：① 必须读过 ② 读后 mtime 未变）。read_file 成功后 `record`；edit_file 编辑前 `check`、写后 `update`；write_file 仅对**已存在文件**要求先读（新建豁免），写后 `update`；delete_file 不纳入（删除无需先读内容）。ToolContext 加 `file_state` 字段，主 Agent 与每个 SubAgent 各持独立缓存。`file_state=None` 时门禁失效（向后兼容）。10 个新测试。真实 LLM 验证：直接 edit 被拦 → LLM 自主改为先 read 再 edit。**可配置**：`[tools] enforce_read_before_edit`（默认 true）控制主 Agent 与所有 SubAgent 的装配，false 关闭门禁；+5 个接线测试。

✅ **B3 自定义 Agent 类型（.md 声明式定义）**（已完成）
**问题**：4 种 agent 类型硬编码在 `core/agent_types.py`，用户无法定义新类型或覆盖内置类型。
**实现**：新增 `core/agent_type_loader.py`（`parse_agent_md` + `load_agent_types`）：从 `~/.mini-agent/agents/` 和 `./.mini-agent/agents/` 扫描 `*.md` 文件，YAML frontmatter（`name`/`description`/`allowed_tools`/`max_iterations`）+ body 作为 system_prompt 模板（支持 `{working_dir}/{platform}/{shell}/{iteration_budget}` 占位符）。`agent_types.py` 新增 `register_agent_type()` setter；`AgentConfig` 新增 `agent_dirs` 字段；app.py 启动时调用 loader。优先级：项目 > 用户 > 内置（同名覆盖）。`spawn_agents` 工具 schema 动态列举所有已注册类型。12 个新测试。内置 4 种保持硬编码（安装后无 .md 也可用）。

✅ **B3.1 /spawn + /trace 提示符被淹没**（已完成）
**问题**：`/spawn`（非阻塞）+ `/trace on` 同时开启时，子 agent 的 trace 日志异步输出到终端（共享 EventBus → 共享 Rich Console），和主终端的 `>` 输入提示符混在同一行，用户看不清提示符、以为程序卡住。
**修复**：`PromptSession` 创建时加 `patch_stdout=True`（prompt_toolkit 内置机制）。prompt 活跃期间所有 stdout 写入自动打印到 prompt 上方，prompt 行自动重绘。一行改动。

✅ **B3.2 权限确认弹窗输入行被并发输出淹没**
**问题**（B4.1 终端验证中实测暴露）：工具并行执行时，一个工具触发权限确认弹窗（`allow? [y/a/n] > ` 等待输入），另一个并行工具完成时的 trace 行直接打进确认输入行——用户看不到输入位置。B3.1 的 `patch_stdout` 只包裹了主输入框（`get_user_input` 的 `prompt_async`），`terminal.confirm()` 的输入路径未覆盖。
**✅ 已修复**：`Terminal` 新增 `_prompt_protected(session, message)` 辅助方法——`prompt_async` 外包 `patch_stdout(raw=True)`，等输入期间并发输出重定向到提示行上方、输入行自动重绘；stdout proxy 建不出来时（无控制台环境）退回裸 prompt 不破坏原有语义。三个临时 PromptSession 输入路径（`confirm`/`ask_yes_no`/`ask_structured`）统一接入。4 个新测试（三路径 patch_stdout 包裹验证 + proxy 不可用兜底），1066→1070。

✅ **B4 后台子代理 + 完成通知**（已完成）
**问题**：LLM 的 `spawn_agents` 工具阻塞等待全部子 agent 完成（spawn_agents.py `wait_all`），期间不能做其他工作——comparison 6.2 自认的限制。
**实现**：`spawn_agents` 工具新增 `background: bool` 参数（默认 false 保持阻塞行为）。`true` 时走 `SubAgentManager.spawn_background()`：spawn 后立即返回 agent ids，每个 agent 由 notifier 协程 `_notify_on_complete` 等待，完成时经 **mailbox** 向 'main' 投递含结果的通知（截断 4000 字符），自动投递即时送达（B4.3 解除了空闲滞留限制——`terminal.interrupt_input()` 中断输入等待，`_handle_background_delivery()` 自动 drain 并处理）——复用现有跨 Agent 消息通道，零新增注入机制。`/spawn --background` 命令行也可直接后台派发。`SubAgentCompleteEvent` 加 `background` 字段，app.py 订阅后终端提示完成。5 个新测试。fork 对话上下文的 worker 后续由 B4.1 实现（摘要式）。

✅ **B4.1 摘要式上下文 fork（fork-with-summary worker）**（已完成）
**问题**：SubAgent 空白上下文（刻意设计：便宜/可并行/可预测），但"和主 agent 讨论半天需求后派 worker 按讨论去做"的场景下，task 文本装不下讨论内容，子 agent 不知道之前聊了什么。mewcode `agents/fork.py` 用全量继承解决，但全量太贵（并行 N 个 = N 倍历史 token）且有"fork 后主对话继续变化"的一致性问题。
**实现**：摘要式 fork——`memory/compressor.py` 新增公开函数 `summarize_conversation(llm, messages)`（复用 P67 的 `_extractive_digest` + `LLMSummarizeOldest._summarize` 9 节结构化摘要，LLM 失败回退提取式 digest——fork 绝不因摘要失败而失败）。摘要即冻结快照（回避一致性问题），成本 ≈ 一次摘要调用（≪ 全量历史 × N）。两个入口：`spawn_agents` 工具的 `inherit_context: bool` 参数（LLM 自主）+ `/spawn --fork`（用户命令）；摘要经 `SubAgentManager.build_context_summary()`（worker LLM）生成，`spawn/spawn_parallel/spawn_background` 透传 `context_summary`，注入子 agent system prompt 的 `[Inherited context ...]` 段。6 个新测试。诚实边界：`spawn_pane`（跨进程 WorkerSpec 协议）与 `/team` 未纳入。

✅ **B4.2 fork 摘要生成阻塞且不可观测**（已完成）
**问题**（B4.1 终端验证中实测暴露）：`inherit_context=true` 时摘要生成（一次完整 LLM 调用）阻塞在 `spawn_agents.execute` 内部——实测对话稍长时耗时 46-54 秒，期间终端零输出、用户以为卡住。两个具体伤害：① `background=true + inherit_context=true` 组合下"立即返回"承诺打折（实测 spawn_agents done 53938ms）；② 摘要调用走 `complete()` 直调不经 AgentLoop，不发任何 trace 事件——`/trace on` 也看不到。
**✅ 已修复**：① 可观测性：`build_context_summary()` 前后发射 `ContextSummaryStartEvent`/`ContextSummaryDoneEvent`，app.py 订阅显示终端提示（"Summarizing conversation for context fork..." / "Context summary ready (Xs, N chars)"），TraceRenderer 订阅显示 `ctx` trace 行——用户不再以为卡死，`/trace on` 可见。② 非阻塞：`background=true + inherit_context=true` 时摘要+spawn 整体放进 `asyncio.create_task`，`execute()` 立即返回；消息列表浅拷贝防竞态，task 引用存 `_notify_tasks` 防 GC。3 个新测试，1060→1063。

✅ **B4.3 后台 agent 完成后结果自动投递**
**问题**（B4.2 终端验证实测暴露）：`background=true` 派发的子 agent 完成后,结果写入 mailbox 但需等用户下一次输入才被消费。
**✅ 已修复**：`SubAgentCompleteEvent` 订阅者设置 `asyncio.Event` 并调用 `terminal.interrupt_input()` 中断输入等待，主循环将 `get_user_input()` 与该 event 做竞争——event 先触发时返回 `_BG_INTERRUPT` 哨兵。TTY 路径用 `prompt_session.app.exit(_BG_INTERRUPT)` 保存并恢复用户部分输入，非 TTY 路径用 `asyncio.wait(FIRST_COMPLETED)` 竞争 `input()` executor 与 event。主循环收到 `_BG_INTERRUPT` 后调 `_handle_background_delivery()` 注入合成消息、运行 `agent_loop.run()` 处理 mailbox 结果。新增 `Mailbox.has_pending()` 无锁只读查询。提示文案改为 "processing result..."。3 个新测试。

✅ **B5 权限模式矩阵**
**问题**：mewcode `permissions/modes.py` 有 default/acceptEdits/plan/bypassPermissions 四模式 × 工具类别决策矩阵。mini 有 plan 模式和 sandbox_auto_allow，但无 acceptEdits/bypass 等价物。
**✅ 已实现**：`PermissionMode` 枚举（`models/permissions.py`）：`default`（危险命令/项目外路径询问，原行为）/ `accept-edits`（写文件免确认，危险命令仍询问，项目外读仍询问）/ `plan`（写拒绝——权限层第三重锁，loop 的 schema 过滤和 act 拦截之外）/ `bypass`（除 deny 规则和敏感路径外全部免确认）。**安全底线不被任何模式穿透**：显式 deny 规则、敏感路径（~/.ssh、.env 等）和敏感文件命令（`type .env` 类）在所有模式下拒绝/确认（规则先于模式判定）。矩阵嵌入 `PermissionManager` 命令/路径两条管道 + `would_ask()` 同步更新（流式延迟判定一致）。运行时 `/mode [名称]` 切换（bypass 附警告，plan 切换同步系统提示词）；`/plan on|off` 和 `exit_plan_mode` 工具经 `Application.set_permission_mode()` 与矩阵联动。配置 `[security] approval_mode` 设启动模式（非法值告警回退 default；`enable_plan_mode=true` 兼容等价 plan）。
**终端实测暴露两洞并当场修复**（详见 tech-notes §95.4）：① bypass 短路曾排在敏感文件命令检查之前——`read_file .env` 被拦后 LLM 换 `type .env` 泄漏了 API key；修复后敏感文件命令在所有模式下弹确认。② `exit_plan_mode` 曾无条件退出——LLM 自批计划后同批调用直接写文件；修复后加用户审批门（yes/no，拒绝保持 plan，无 UI 拒绝退出），流式执行延迟该工具防弹窗交错。22 个新测试，1070→1092。
**完整性复查补三块**（详见 tech-notes §95.6）：① plan 只读覆盖 bash 通道——`WRITE_COMMAND_PATTERNS`（文件重定向 + mkdir/copy/move/del 等写形态命令）plan 下直接拒绝，`>nul`/`>/dev/null`/`2>&1` 丢弃型重定向不误伤（实测 LLM 曾计划 `echo HELLO> a.txt` 绕锁）；② plan 下 spawn_agents 禁用——in-process 子 agent 不带 PermissionManager（P82 只接了 pane worker），任何派生都是只读逃逸口（后由 B5.1 权限栈传播改为有门放行）；③ 可观测性——`PermissionModeChangedEvent`（trace `mode` 行）+ `/status` 显示当前模式 + 底部工具栏始终显示 `mode: xxx`（初版仅非 default 显示，实测配置回退场景看不出当前模式，改为始终显示）。6 个新测试，1092→1098。另：权限拒绝消息带原因——`_denied_message()` 拼入 `last_decision_reason` + 可读提示（实测光秃 Permission denied 让 LLM 烧 5 万 token 排查不存在的配置）。
**引号误伤修正 + cmd /c 补漏**（详见 tech-notes §95.7）：写形态匹配前剥离成对引号段（`findstr ">" f` 等只读命令不再误拒，不成对引号宁可误拦）；剥离会让 `cmd /c "echo x > f"` 逃逸——顺带发现 `cmd /c` 内联执行不在危险清单（Windows 版 sh -c），补进后 27→28 条，引号内重定向经确认兜底。3 个新测试，1098→1101。

✅ **B5.1 工具类别税制 + 子 agent 权限栈传播**
**问题**（B5 完整性复查发现）：① 权限矩阵的"工具类别"轴只覆盖 bash + 文件路径两类——`_check_permission` 的 else 分支 `unrestricted_tool` 直接放行，`install_skill`（写磁盘）、MCP 工具（外部副作用）在 plan 模式下不受限；现存多份独立工具列表未统一（`_WRITE_TOOLS`×2、`_check_permission` 路由列表、`would_ask` 列表、schema 过滤）。② in-process 子 agent 完全没有权限门——`SubAgentManager.spawn()` 不传 permission_manager（P82 只给 pane worker 接了权限栈），子 agent 的 bash 可跑任何命令零检查。
**✅ 已实现**：① `ToolCategory` 枚举（read/write/execute/external，`models/permissions.py`）声明在每个 Tool 类上，未声明的插件工具默认 EXTERNAL（保守）；矩阵新单元：plan×WRITE 拒绝（覆盖无路径参数的 `install_skill`）、plan×EXTERNAL 拒绝（MCP 外部副作用无法验证只读）、bypass×EXTERNAL 显式放行；`task_*` 归 READ（任务板是规划笔记本，plan 禁它等于禁规划本身——有意决策）；agent_loop 的 schema 过滤/流式延迟/act 拦截/权限路由 + team.py 写工具剥离（原本地清单漏了 delete_file 的漂移顺带修复）全部改为类别驱动，`_WRITE_TOOLS`×2 删除；**类别门用 `pm.mode` 而非 loop 标志**——子 agent 的 loop 标志是 False 但传播来的权限栈带着父级模式，传播正是在此生效。② `ChildPermissionManager`（`PermissionManager.child_view()`）：共享父级规则表/会话授权/写文件集（引用共享，`/allow` `/deny` 实时生效），`mode` 是委托父级的 property（`/mode` 即时影响运行中子 agent），confirm 恒 None——需弹窗处安全拒绝（`no_ui:default_deny`），并发弹窗交错问题就此消解；`spawn()` 为每个子 agent 创建独立子视图（trace 上下文不互相覆盖）。**联动**：B5 的"plan 禁 spawn"封条改为有门放行/无门禁用——子 agent 携带 PLAN 模式（写在权限层被拒），plan 模式恢复派研究 agent 的能力。`_READ_ONLY_TOOLS`（agent_types）保留——它是类型档案的可用性白名单，与权限判定是不同轴，强行合并会混淆两种语义。17 个新测试，1101→1118。
**终端实测补一修**：`ask_user` 弹窗被流式渲染淹没（弹窗出现时 LLM 流未结束、提示符被 trace 行冲掉）——流式 eager 判定漏了它。Tool ABC 加 `opens_dialog` 声明属性（ask_user/exit_plan_mode），流式延迟按属性判定不再按名字特判。2 个新测试，1118→1120。
**传播实测补两修**（详见 tech-notes §96.5）：① 子 agent 绕路熔断——`no_ui:default_deny` 纳入确认拒绝熔断计数（实测子 agent 被拒后连试 9 个工具找绕路；策略拒绝仍中性，主会话不受影响）；② 规则来源进拒绝理由——`rule:ping* [/deny session rule, not persisted]`（实测主 agent 为溯源一条内存中的会话规则烧了 34 万 token）。4 个新测试，1120→1124。
**复验补两修**（详见 tech-notes §96.6）：① 规则来源的方括号格式撞 Rich 标记致 trace 崩溃——改圆括号 + trace 动态字段全转义；② **deny 规则被写后执行真实绕过**——子 agent 写 `run_ping.bat` 裸文件名执行成功（正则只认 ./x、cmd /c、解释器形态），`is_executing_written_script` 新增段首 token 检查 + call/start 形态，读取写过的文件不误触发。3 个新测试，1124→1127。
**复验再补一修**（详见 tech-notes §96.7）：子 agent 熔断报告带拒绝原因 + 遗留文件清单——实测报告只有"Stopped early"时主 agent 盲目重派同样的子 agent、留下两个孤儿 .bat；现在报告明示原因和"重派会撞同一拒绝"，并列出本次创建的文件（不自动删——可能是合法半成品，清理是父级/用户的判断）。1 个新测试，1127→1128。
**复验又一修**：报告曾只带熔断"最后一击"（no_ui）而丢了根因（rule:ping*）——主 agent 误诊为缺确认 UI。`AgentState.denial_reasons` 累积本轮全部去重拒绝原因，报告列全序列根因在前；复验后再补：rule 拒绝附带"对会话内所有 agent 生效"事实与可照抄的移除命令——占位符写法实测被错代入成 `/deny remove ping ping*`，现在从拒绝理由内嵌的 scope（格式改为 `rule:<scope>:<pattern>`）完整构造。同轮复验还暴露真实洞：`cmd /c "ping x"` 绕过 `ping*` deny 规则仅靠危险命令确认层兜底（交互会话用户可能没注意确认框里包着被拒命令）——deny 匹配现解包 cmd /c、powershell -Command、sh -c 包装前缀并抹引号后逐 `&;|` 段匹配；allow 规则不解包（扩大 deny 收紧、扩大 allow 放松）。5 个新测试，1128→1133。
**遗留（诚实边界）**：① 子 agent 无 confirm 回调意味着危险命令一律拒绝而非询问——想让子 agent 的危险操作也能人工放行需要串行化的跨 loop 确认队列（弹窗归属、挂起超时、background 完成时用户不在场等交互问题），技术可行但暂无场景不做。② deny 规则的解包匹配是纵深防御而非围墙——解包 3 层、wrapper 清单有限（cmd /c、cmd /k、powershell -Command、sh -c），`p^ing` 转义/环境变量间接调用/base64 编码等深度混淆在规则层原理性无法穷尽（完备识别等价于静态分析任意 shell 程序）；安全保证靠分层：混淆载体本身（cmd /c、powershell -e、for /f 等）在危险命令清单里必弹确认，OS 沙箱是最终围墙。新混淆形态实测暴露一个补一个。

✅ **B6 指令文件 @-include**
mewcode `memory/instructions.py` 支持 `@./path @~/path` 递归引用（深度 5）。mini `memory/project_context.py` 只读单文件、8000 字符截断，无引用语法。
**✅ 已实现**：`project_context.py` 的 `_expand_includes` 递归展开 @-include 指令（整行 `@./path` 或 `@~/path`），相对路径随被引用文件的目录解析（非项目根），最大深度 5（`ContextConfig.max_include_depth`，0 禁用），循环引用与文件缺失生成注释标记温和降级，展开后整体受 `max_chars` 截断。行内 `@./` 不误触。用户级指令同样支持。10 个新测试，1133→1143。

✅ **B7 远程模式 SessionStore 接入**
mewcode `remote.py` 接入 SessionManager（持久会话）；mini `remote/server.py` 零 SessionStore 引用，重启丢失会话（roadmap 已知限制已承认）。工作量：小-中。
**✅ 已实现**：远程模式复用终端模式的全套持久化基础设施（`session_store`/`_autosave`/`_adopt_session` 在 Application 上已存在且 UI 无关，只需接线）。四个接线点（`remote/server.py`）：① 启动时 `cleanup_stale` + 自动恢复本项目最新未关闭会话（`_find_crashed_session` 助手从 `_maybe_restore_session` 提取、两模式共用过滤逻辑；远程不询问——启动时无客户端可问，终端保持询问式）；② 每轮 turn 结束 `_autosave(force=True)`（硬杀不丢最后一轮）；③ 斜杠命令后节流保存；④ 服务器退出 finally 标记 `closed_cleanly=True` 并保存。附带修复既有盲区：`/session load`/`/fork` 换会话后浏览器不知情——现广播新 WS 事件 `history_reset`（web_ui 清空聊天区）并对所有客户端重放历史。诚实边界：恢复不询问与终端语义不同；正常关闭后重启从新会话开始（手动 /session load 可恢复）。复验补修：新增 `/session new` 安全另起（裸 /clear 不换会话 ID、自动保存会覆盖盘上旧历史——终端既有坑，本次文档化）；修复采用无边界会话继承上一会话已读文件缓存与技能状态的既有陈旧状态 bug（`ContextManager.reset_state()`）。13 个新测试，1166→1179。真实验证双通道全过：WS 脚本取证（硬杀恢复 + /session new 落盘）+ 用户终端日常动作四场景（远程关窗口/Ctrl+C、终端关窗口/exit）与 /session new 全流程人工确认。详见 tech-notes §102。

✅ **B8 恢复附件含 skill 调用记录**
mewcode 压缩恢复附件含 skill 调用记录（`record_skill_invocation/snapshot_skills`），mini `memory/context.py` 无 skill 相关恢复。
**✅ 已实现**：`SkillRegistry` 记录保序去重的激活历史（`_invocations`，deactivate 不抹除——是调用记录不是当前状态）；`ContextManager.set_skill_provider()` 回调注入技能状态（memory 层不 import extensions 层，保持依赖方向）；压缩恢复附件新增技能行——激活中的标注 "do NOT re-activate"（prompt 在 system prompt 中存活、不被压缩，丢的是激活历史），已停用的单列历史行；`compact_boundary` 持久化 `skill_invocations`/`active_skills`，`adopt_boundary` 暂存、app 层经 `restore_state()` 写回 registry（不重注入 prompt——恢复的 system_prompt 已含，重走 activate 会重复拼接）。会话恢复后 `is_active`/`deactivate`/`match_triggers`/`reload` 全部恢复正常。**复验补修**：终端复验发现手动 /compact 绕过 `check_and_compress` 直接调 compressor——恢复附件与全部边界字段（已读文件/用户请求/技能状态）都不写（既有缺陷，本次暴露）。`check_and_compress` 加 `force` 参数，/compact 改走同一管道；连锁收益：空对话+激活技能时 force 也能建边界持久化技能状态。**边界**：自动压缩仅在阈值触发，未经历任何压缩（也未手动 /compact）的会话恢复时激活集合仍丢（prompt 本身在序列化的 system_prompt 中存活）；完整会话级持久化属 /session 存档格式扩展，另行考虑。12 个新测试，1143→1155。

✅ **B9 模糊确认不算授权（system prompt 守则，已实现）**
**问题**（终端验证中实测暴露）：用户明确说"先不要动手，我们只是讨论"，agent 盘点后主动问"确认 A 还是 B，确认后动手"；用户下一句以"对，另外提醒：改完要跑测试"开头（附和分析 + 继续讨论），agent 把"对"解读为方案授权，直接修改了 6 处文件。"只讨论"的强约束未被显式解除前，模糊的"对/嗯/好"不应视为动手授权。
**✅ 已实现**：`app.py` SYSTEM_PROMPT Guidelines 列表新增 `IMPORTANT:` 规则——用户明确表示只讨论时约束持续有效，直到用户给出显式动手指令（"开始动手"/"执行"/"go ahead"/"make the changes"），模糊确认（"对"/"嗯"/"好"/"right"/"ok"/"yes"）只确认理解不解除约束，不确定时主动问"现在可以动手了吗？"。中英文关键词示例嵌入 prompt（与 git commit 守则同级别 `IMPORTANT:` 风格）。诚实边界：prompt 守则是提示非强制——LLM 仍可能违反（尤其模型能力较弱时），但实测暴露问题的场景中加守则后命中率显著提高。详见 tech-notes §105。

✅ **B9.1 空白上下文子 agent 的幻觉编造（SubAgent prompt 守则，已实现）**
**问题**（终端验证场景 1b 实测暴露）：无 fork 的子 agent 收到"总结我们讨论的方案"类任务（引用了它不知道的上下文）时，不承认不知道，而是**自信编造**了完整方案——含虚构的实现细节和不存在的文件名（`bash_tool.py`，实际是 `builtin/bash.py`），`Tools: 0` 纯凭空生成。
**✅ 已实现**：`core/subagent.py` SubAgent 初始化时根据 context_summary 有无条件注入——无继承上下文时追加 `[IMPORTANT: You have NOT been given any context about the parent conversation...]` 提示，明确要求如实说明并 NEVER fabricate。有 context_summary 时不触发（已有真实摘要）。注入点在 agent 类型 prompt 之后，覆盖所有类型（含自定义 .md 类型），与 roadmap 方向建议的逐类型修改相比更全面且维护成本更低。诚实边界：同 B9——prompt 守则是提示非强制。详见 tech-notes §105。

✅ **B10 零代码声明式 hook 增强（自定义动作 + 条件表达式引擎，已实现）**
**来源**：C2 修正时诚实降级了 mini 侧论证暴露的真实差距——mini 的"EventBus 订阅者覆盖观察类扩展"只半成立：能力可达但需写 Python（EventBus 订阅者或 listener_dirs 插件），mewcode 是零代码 YAML 配置。
**已实现**：分两块——① 自定义动作：`action = "command"`（命中时执行 shell 命令，仅受显式 DENY 规则约束不弹交互确认；PRE_TOOL 非零返回码阻止工具执行，POST_TOOL 火后不管；stdout 通过终端通知显示）与 `action = "notify"`（终端通知行，观察类零代码化）。模板变量 `$TOOL_NAME`/`$TOOL_ARGS.<key>`/`$TOOL_ARGS`(JSON)/`$EVENT`/`$RESULT`/`$RESULT_ERROR` 可在命令和消息中展开。② 条件表达式引擎：`condition = "tool == 'bash' and args.command =~ 'git push'"` 字符串字段，`hook_conditions.py` 独立模块实现解析器（`==`/`!=`/`=~`/`~=` 四运算符 + `and`/`or` 组合，不可混用），可用字段 `tool` 和 `args.<key>`。condition 设置时优先于固定字段（tool/arg/contains/regex），非法表达式温和降级跳过规则不崩配置加载。新增 `event = "post_tool"` 支持工具执行后触发。58 个新测试（30 条件引擎 + 28 hook 增强），1259 个全过。详见 tech-notes §109。

✅ **B11 `-p` 非交互一次性模式 + NDJSON 事件流输出（已实现）**
**来源**：全模块面对照扫描发现的完全缺失项。mewcode `__main__.py` 支持 `-p "任务"` 一次性执行后退出 + `--output-format stream-json` 输出 NDJSON 事件流（assistant/thinking/tool_use/tool_result/usage/turn_complete/result/error/compact/retry 十种事件）；mini CLI 只有交互 TUI / --remote / --worker 三种形态，**无法被脚本、CI、管道调用**。
**方案**：cli.py 新增 `-p <prompt>` 与 `--output-format {text,stream-json}`；text 模式复用 AgentLoop 回调收集最终文本打印退出；stream-json 模式把 on_stream_delta/on_thinking_delta/on_tool_start/on_tool_end/usage 等回调映射为 NDJSON 行（复用远程模式 `_ws_send` 的事件命名以保持两个机器接口一致）。权限：非交互无确认 UI，走 fail-safe 拒绝（与子 agent 无门语义一致），文档明示"需要确认的操作在 -p 模式一律拒绝，可配 --mode accept-edits 放宽"。
**验证要点**：`mini -p "1+1"` 输出答案退出码 0 / stream-json 每行合法 JSON 且事件序完整 / 危险命令被拒不挂起 / 与交互模式共存不回归。工作量：中。
**✅ 已实现**：新模块 `headless.py`（`run_headless(app, prompt, output_format) -> exit_code`）+ cli.py `-p/--prompt` 与 `--output-format {text,stream-json}` 参数。接线仿远程模式：AgentLoop 回调整体替换（text 静默只捕获最终文本 / stream-json 映射为远程协议同名事件 user_message/turn_start/stream_*/thinking_delta/tool_call/tool_result/turn_end/error/info/file_changes）；`permission_manager._confirm = None` 走现成 `no_ui:default_deny` 失败安全；stdout 纯净性——CLI 层 `redirect_stdout(sys.stderr)` 包住构造与运行，结果写 `sys.__stdout__`。生命周期最小路径：prepare → MCP 连接 → 手工回合（@file 展开 + UserMessageEvent + 自持异常拿退出码，不复用会吞异常的 _handle_turn）→ MCP 断开。诚实边界：需确认操作一律拒绝（熔断早停、被拒工具不产生 tool_result 事件）、一次性会话不落盘（防 CI 每跑留档）、不跑 SESSION hooks/记忆提取。8 个新测试（参数解析 2 / text 模式 / NDJSON 合法性与事件序 / 工具事件 / 危险命令拒绝不挂起 / LLM 异常退出码 1 / 会话不落盘），1193→1201。真实 LLM 双模式验证 PASS（text 输出 "2" 退出码 0；stream-json 32 行全合法 JSON 含 thinking_delta 事件序完整）。详见 tech-notes §108。

✅ **B12 发送侧 extended thinking 控制（已实现）**
**来源**：对照扫描发现 mini 只**被动解析**思考流（reasoning_content/thinking_delta 渲染），从不在请求侧开启——对 Anthropic 官方 extended thinking 模型等于功能不可用（DeepSeek 类自动吐 reasoning_content 的不受影响）。mewcode：provider 配置 `thinking: true`；自适应 budget（opus/sonnet≥4.6 传 `budget_tokens: 0`，其余 max_output_tokens−1 下限 1024）；思考块带签名在对话中往返。
**方案**：`LLMConfig` 新增 `thinking: bool = False`（或按 profile 配置）；anthropic_provider 请求体加 `thinking: {type: "enabled", budget_tokens: ...}` 自适应逻辑；思考块签名往返（Anthropic 要求 assistant 消息回传 thinking 块）；OpenAI Responses reasoning 参数同理。
**验证要点**：开启后真实 Anthropic 请求含 thinking 参数且思考流渲染 / 关闭默认行为不变 / 签名往返多轮不 400。工作量：小-中。
**✅ 已实现**：`LLMConfig.thinking: bool = False`，TOML `[llm] thinking = true` / `MINI_AGENT_THINKING` / 按 profile `MODEL_<名称>_THINKING` 三途径开启。anthropic_provider 自适应 budget（正则版本检测带负向前瞻防日期段误判，≥4.6 → 0，其余 max(1024, max_tokens−1) 且触下限时抬 max_tokens）；`signature_delta` 解析 → `StreamChunk/LLMResponse.thinking_signature` → `metadata["thinking_signature"]`；`_split_system` 带签名 thinking 块回传（三道闸：仅开启时/无签名不回传/排在 tool_use 前）。修复 `to_api_messages()` 不输出 metadata 的死代码（Responses reasoning 回传实际拿不到数据），openai_provider 发送前剥除。Responses 加 `reasoning: {effort, summary: auto}`（effort 经 `extra.reasoning_effort` 配置，默认 medium）。顺带修复真实验证暴露的三 provider SSE `data:` 无空格事件全丢 bug + Anthropic 双认证头（x-api-key + Bearer）。16 个新测试（含 7 个 MockTransport 请求体取证），1259→1275。真实 LLM 验证：DashScope Anthropic 兼容端点 thinking 请求被接受、工具调用 e2e 退出码 0、默认关闭回归 PASS；阿里云 MaaS 网关 Anthropic 协议端点（deepseek-v4-pro）真实思考流输出 + 多轮无 400；本地 mock e2e（experiments/verify_thinking_e2e.py 4/4）验签名往返全链路。仅剩官方 API 的签名密码学校验待补验。详见 tech-notes §110。

✅ **B13 记忆子系统体验增强（后台整固节律 + 并行 recall 预取，已实现）**
**来源**：对照扫描的两处程度差距。① 整固：mini 是阈值(20 条)触发/手动 `/memory consolidate`；mewcode autoDream 在 ≥24h 且 ≥5 会话后**后台** fork 子 agent 合并去重（锁文件 + 失败回滚），用户无感。② recall：mini 的 LLM recall（P52）串行在注入路径上；mewcode 的 LLM 选择器与主 LLM 调用**并行预取**（8s 超时，工具执行后非阻塞注入）——recall 延迟成本归零。
**方案**：① `MemoryConsolidator` 加时间+会话数双门槛的启动后台任务模式（复用现有合并逻辑，加锁与回滚）；② recall 改 `asyncio.create_task` 与主调用并行，超时放弃本轮注入。
**验证要点**：整固只在双门槛满足时触发且失败可回滚 / 并行 recall 不增加首 token 延迟 / 超时降级无 recall 不报错。工作量：中。
**✅ 已实现**：① `consolidation.py` 新增 `ConsolidationScheduler`——per-scope（用户级/项目级）双门槛（距上次 ≥`consolidate_min_hours` 默认 24h 且新会话 ≥`consolidate_min_sessions` 默认 5 个），状态记"尝试"而非"成功"（无可合并也记录，防每次启动重烧 LLM）；锁文件独占创建 + 10 分钟过期接管（初版 1h，真实验证后调低）；保存前 `.bak` 备份、失败回滚复原；`app.run()` 启动 `create_task` 后台执行、退出取消，合并逻辑零新增复用 P53。② `recall.py` 新增 `RecallPrefetcher`——首次 poll 发射任务立即放行（首 token 零阻塞），后续轮 await 残余（通常 0s），整体 8s 超时/失败降级头部截断；`_adopt_session` 换会话重置。**中途设计修正**：初版纯跳过语义（未完成返回 None）被真实验证打回——flash 快模型 round 1 约 1s 结束、round 2 时 recall 还没完成，两轮回合注不上；修正为 mewcode 语义"首轮放行、后续 await"。**连锁修复潜伏缺陷**：agent_loop 在 PRE_LLM hook 前快照 api_messages——hook 的 system_prompt 注入（含 P52 以来的旧串行 recall！）从未进过当轮请求，修复为 hook 后变化则重建。25 个新测试，1276→1301。真实 LLM 验证 7/7 ALL PASS（experiments/verify_memory_cadence.py：真实合并 6→4 / 重跑 gated / 锁 held / 注错回滚复原 / 首 poll 0.0s 对照串行 1.6s / 超时降级 / -p 端到端模型按注入记忆答出埋点虚构名）。诚实边界：>阈值时本回合首次 LLM 调用无记忆（无工具单轮回合整轮拿不到，第二次调用起保证）；后台整固终端与 remote 均启动（复验补接，公共方法两模式共用），headless 设计上不跑。详见 tech-notes §111。

✅ **B14 MCP native 延迟加载模式（Anthropic defer_loading）**
**来源**：对照扫描。mewcode MCP 三模式：eager / **native**（Anthropic 官方端点用 `defer_loading` 字段 + `anthropic-beta` tool-search header，模型原生按需搜索工具）/ dispatch；mini 只有 eager/dispatch——dispatch 是自建等效实现，对 Anthropic 官方端点没用上原生能力（原生模式无需自建 tool_search/mcp_call 中转、token 效率更高）。
**方案**：`[mcp]` 配置 `loading = "native"` 第三选项；anthropic_provider 工具序列化时对 defer 工具加 `defer_loading: true` 并附 beta header；非 Anthropic 端点自动回退 dispatch。
**验证要点**：native 模式请求体含 defer 字段与 header / 非 Anthropic 端点回退 / eager 与 dispatch 回归。工作量：小-中。
已实现：`MCPServerConfig.loading = "native"` 第三选项——MCP 工具注册到 ToolRegistry 但带 `defer_loading: true`，Anthropic 服务端隐藏 schema 直到模型调 `tool_search` 返回 `tool_reference` 块展开。`AnthropicProvider` 自动附加 `anthropic-beta: advanced-tool-use-2025-11-20` header。非 Anthropic 端点 / 第三方网关自动降级为 dispatch。`_adjust_mcp_meta_tools()` 按生效模式动态注册/注销 `tool_search` 和 `mcp_call`。26 个新测试，1327 个全过。

✅ **B15 /undo 检查点增强（选择性恢复 + 快照容量）**
**来源**：对照扫描的程度差距。mini `/undo [N]`：文件快照仅保留最近 5 轮、恢复只有"对话+文件一起回滚"一种；mewcode `/rewind`：每轮末快照、上限 100 个、恢复时**三选**（代码+对话 / 仅对话 / 仅代码）。"仅对话"场景真实存在（改动是对的但对话跑偏）；"仅代码"同理（讨论有价值但改动要扔）。
**方案**：`FileSnapshotStore` 的 KEEP_TURNS 提为配置（默认仍 5，可调大）；`/undo` 加 `--code-only` / `--conv-only` 参数（默认双回滚不变）。
**验证要点**：三种恢复各自生效 / 默认行为回归 / 快照容量配置生效。工作量：小-中。
已实现：`/undo [N] [--code-only | --conv-only]` 三选恢复——默认双回滚不变；`--code-only` 仅恢复文件（对话与轮次计数不动，讨论有价值但改动要扔）；`--conv-only` 仅回滚对话（文件保持现状并丢弃对应快照 `discard_turns()`，改动是对的但对话跑偏）。快照容量 `[memory] undo_keep_turns` 配置化（默认仍 5）。7 个新测试，1327→1334 全过。真实 LLM 三模式验证：`--code-only` 后文件删、对话在；`--conv-only` 后文件在、对话删；默认双回滚回归。终端实测补强：`/undo N` 覆盖超出保留窗口的轮次时明确警告（该部分文件改动未恢复），不再静默跳过；+3 测试 →1337。详见 tech-notes §113。

✅ **B16 交互 UX 小项包（对照扫描收集）**
四个独立小项，可拆散实施：① **可折叠工具调用块**——只读工具（read_file/glob/grep）每轮 ≥2 次时自动折叠为一行摘要"✓ Done (N tool uses · Xs)"（mini 已有 ╭─╰─ 连线但不折叠；此项在 comparison 早有候选记录）；② **shift+tab 循环权限模式**（default→accept-edits→plan→bypass，替代输 /mode 全名）；③ **确认弹窗 "a"(always) 直接写永久规则**——mini 目前是会话级授权、持久要手动 /allow --save，mewcode 弹窗第三选项即写规则文件（需评估：静默写盘 vs 显式保存的安全取舍，可折中为写盘前提示一行）；④ **Esc 单击把运行中子 agent 转后台**（当前双 Esc 是取消整轮）。
**评估**：全部非必需，按使用痛感排优先级：①>②>③>④。工作量：各自小。
已实现：① Terminal 内 Rich Live（transient）只读工具组——≥2 条全成功折叠为 `✓ Done (N tool uses · Xs)`，单条/出错按原格式展开，弹窗/流式/错误等边界统一 `flush_tool_group()` 收束；② prompt_toolkit `s-tab` 绑定循环四模式，plan 提示词注入/移除集中到 `set_permission_mode`（/mode、/plan、循环、exit_plan 四入口共用）；③ 采用"a 后追问一行"折中——按 a 再问 `save permanently? [y/N]` 默认否，y 才写项目 permissions.toml（与 /allow --save 同文件同格式），其余 "always" 消费处把新值安全降级；④ 进度面板 detachable 模式单击 Esc 转后台——**刻意不 cancel 等待任务**（`wait()` 内 `asyncio.wait_for` 会级联杀死 agent 本体），改为 `adopt_pending_wait()` 接管既有任务并复用后台投递链（完成提示 + mailbox 自动投递）。用户实测后增补两项：折叠可配置（顶级 `collapse_tool_calls`，按用户要求默认 false 不折叠、显式 true 开启）；转后台后可**重新附着**——空提示符按 Esc（自动提交 /spawn wait）或手动输命令，面板回来、结果直取，后台投递被取消防双投递，可反复切换；EscWatcher 双层防误触——启动观察窗 300ms 持续排空 + 孤立 Esc 判别（ 后紧跟字节 = 终端转义序列，丢弃），实测修复"没按 Esc 面板每次秒转后台"；斜杠命令结束后立即处理收件箱投递（修 re-attach 竞态下结果延迟显示）；interrupt_input 仅 prompt 运行中生效（修输入行残留 /spawn wait）。17 个新测试，1337→1354 全过。真实 LLM 验证：折叠一行如实出现、危险命令 a→y 落盘且重启免弹窗、/spawn --wait 回归正常；shift+tab、Esc 转后台、空提示符 Esc 重附、防误触与残留修复均经用户真实终端实测通过；已知边界（面板期间打字丢弃 / 观察窗 300ms / Esc 半秒消歧延迟 / Esc 后立即打字先触发重附）记录于 commands-guide 与 tech-notes；绑定层与命令后投递分支测试补齐、遗留 flaky 耗时测试加固，1337→1363 全过。详见 tech-notes §114。

✅ **B17 SyntheticOutput 结构化输出工具**
**来源**：全模块面对照扫描的完全缺失项。mewcode 的 `SyntheticOutput` 工具（tools/synthetic_output.py，68 行）让子 agent 以机器可读的结构化 JSON 返回结果（schema 约束），父方/调用方无需从自然语言报告里解析字段——服务于"子 agent 产出要被程序消费"的场景（如 verify agent 返回 {pass: bool, failures: [...]}）。mini 子 agent 只有自然语言报告 + 正则提取 deliverables 的启发式。
**方案**：新增 `synthetic_output` 内置工具（READ 类别）：接受任意 JSON 参数原样存入 SubAgentResult 的结构化字段；`_format_agent_result` 与后台投递消息附带该 JSON 块；agent_types 的 verify prompt 引导使用。
**验证要点**：子 agent 调用后父方拿到结构化字段 / 不调用时行为不变 / JSON 透传不被转述改写。工作量：小。
已实现：`SyntheticOutputTool`（READ 类别，additionalProperties schema）接受任意 JSON kwargs 原样返回；`SubAgentResult.structured_output` 新字段由 `_extract_structured_output()` 从对话的最后一次 synthetic_output 工具调用中提取；`_format_agent_result` 和 `_deliver_result` 附带 JSON 代码块；verify prompt 强制要求调用 synthetic_output（"you MUST call ... This is mandatory"，初版建议措辞 LLM 会跳过，加强后实测生效）；`_READ_ONLY_TOOLS` 包含 synthetic_output 供 explore/plan/verify 类型使用；pane worker 结果序列化同步。12 个新测试，1375 个全过。真实 LLM 验证：verify agent 调用 synthetic_output 返回 `{"pass": "true"}` + PASS verdict、worker agent 读 pyproject.toml 返回 `{"project_name": "mini-code-agent", "found": "true"}` 原样透传、`--wait` 前台路径 `Structured output:` + JSON 代码块格式正确、不调用时行为不变。

✅ **B18 worktree 重型目录软链**
**来源**：全模块面对照扫描的程度差距。mewcode worktree/setup.py 在创建 worktree 时把重型目录（默认 node_modules/.venv/vendor，可配 `symlink_directories`）从主工作区**软链**进 worktree——避免每个隔离 agent 重装依赖/复制巨型目录，创建秒级完成且不多占磁盘。mini 的 worktree 隔离（/spawn --isolated）每个 worktree 是干净 checkout，Python 项目里子 agent 要么没有 .venv 可用、要么依赖重建。
**方案**：`SecurityConfig` 新增 `worktree_symlink_dirs: list[str] = [".venv", "node_modules", "vendor"]`；WorktreeManager 创建后对存在于主工作区的目录建符号链接（Windows 用 junction 回退，无权限时警告降级不失败）；文档明示风险——软链目录是共享可写的，并行 agent 同时写依赖目录仍会冲突（典型场景只读使用，可接受）。
**验证要点**：worktree 内 .venv 可用 / Windows junction 生效或温和降级 / 配置为空列表禁用 / 删除 worktree 不误删主工作区真身。工作量：小-中。
已实现：`SecurityConfig.worktree_symlink_dirs` 可配字段（默认 `[".venv", "node_modules", "vendor"]`，空列表禁用）；`WorktreeManager` 构造函数接受 `symlink_dirs` 参数，app.py 从 config 注入；`_link_dependency_dirs` 用可配列表替换硬编码 `_LINK_DIRS`，Windows 符号链接失败时回退 junction（`mklink /J`），非 Windows 温和降级不失败；新增 `_unlink_dependency_dirs` 在 `remove()` 前断开所有链接——防止 `git worktree remove` 递归删除时跟随链接误删主仓库真身（Windows 实测确认此问题存在）；`config.toml.example` 新增字段说明。4 个新集成测试（自定义列表 / 空列表禁用 / 删除保留原始 / 默认回归），1379 个全过。真实 LLM 验证（Windows）：worktree 内 `.venv` 为 Junction 确认回退生效 / `worktree_symlink_dirs = []` 后无 `.venv` 确认禁用 / 注释恢复后 junction 回来确认默认值回归 / 主仓库 `.venv/Scripts/` 全程完好确认删除安全。

### C. 文档过时

✅ **C1 远程认证 mini 反超但文档未反映（已修正）**
`--remote-token`（server.py 8 处）让 mini 有 token 认证，mewcode `remote.py` grep 无任何 TLS/token/auth。但 comparison doc 及 roadmap 已知限制仍把"无 TLS"列为劣势——应改为"mini 有 token 认证但无 TLS 加密；mewcode 两者皆无"。
**✅ 已修正**（实施前对 mewcode 源码复验：remote.py 的 4 处 token 命中均为 LLM token 计数非认证，结论成立）：comparison 5.2 局限行改为"无 TLS 加密但有 token 认证，认证维度 mini 反超（mewcode 两者皆无）"；roadmap 已知限制行补对比参照。

✅ **C2 hook 动作类型"四种"失实（已修正）**
comparison doc 7.2 称 mewcode hook 有 command/prompt/http/agent 四种动作。核实 `hooks/executors.py`：**agent executor 是 stub（"not yet implemented"）**，实际三种可用。应改为"三种可用 + agent 未实现"。同时 mini 的"EventBus listener_dirs 覆盖观察类"论证**半成立**：能力可达但需写 Python，mewcode 是零代码 YAML 配置 + 条件表达式引擎（`conditions.py`，==/!=/=~/~= + and/or）——若要补齐零代码声明式 hook 是一个可选方向。
**✅ 已修正**（实施前复验 stub 属实）：comparison 7.2 改为"三种可用 + agent stub"，并加"诚实说明"段承认 EventBus 论证半成立、零代码声明式 hook 列为可选方向。

✅ **C3 团队文件数过时（已修正）**
doc 0.1 节"mewcode 13 文件 vs mini 3 文件"过时：mewcode teams/ 实为 15 文件 2069 行；mini 多 Agent 相关约 7 文件（mailbox/team/spawn_backends/worker/subagent/task_store/agent_types）。
**✅ 已修正**（实施前重新实测）：mewcode teams/ 15 文件 2069 行确认；mini 实为 **8 文件 2055 行**（原清单漏 agent_type_loader）——两者体量已持平，comparison 0.1 改为按实测数字陈述并指出差异在组织方式（常驻队友 vs 一次性 worker）而非体量。

### D. 后续工作中自查发现的缺陷

✅ **D1【UI·中】思考流（reasoning_content）渲染碎行（已修复）**
`ui/terminal.py:203-206` 的 `feed_thinking` 用 `console.print(delta, end="", style="dim italic", highlight=False)` 逐 token 输出模型思考流。Rich 的 `console.print` 不跨调用记录光标列位，每个小片段（如 `.txt`/`).`/`32).`）当独立渲染单元按 `console.width` 各自换行——短碎片落在宽度边界附近时片段间被插入换行，正文前出现一长串断续碎行。
触发条件：仅推理模型吐 `reasoning_content` 时经 `on_thinking_delta → feed_thinking` 触发（普通模型无思考流，故时有时无，非稳定复现）。主回答流走 `StreamRenderer`（Live+Markdown 缓冲，renderer.py）不受影响。
修复方案（首选 `soft_wrap=True`）：给该 print 加 `soft_wrap=True`。这不是绕过而是对准病灶——它直接关闭 Rich 的内部词折行与裁剪，"每个片段各自按宽度折行"的机制被移除，折行交给终端并保持真实光标列位；同时保留 Rich 的 dim italic 样式/主题/Windows ANSI 使能。一行修复、低风险、无功能牺牲。
备选（非必需，更重且不更彻底）：① 仿主流做 thinking 缓冲按行 flush——解决同一症状却引入缓冲状态与额外 bug 面，仅当需要对思考流做 Markdown/Live 渲染才值得；② 裸写 `console.file.write` + 手动 ANSI——完全脱离 Rich 但丢样式整合、需自理 legacy Windows ANSI，跨平台更脆，是退步。
诚实边界：soft_wrap 后超宽思考文本由终端硬折行（不按词），但思考流是 dim 辅助信息，可读性足够。工作量：小（一行 + 真实推理模型运行验证碎行消失）。验证要点：改完必须对着会吐 `reasoning_content` 的模型真实跑一轮肉眼确认碎行消失（reasoning 里本就有的 \n 是真内容、不归此修复管）。
**✅ 已修复（真因与上方分析不同，详见 tech-notes §100）**：首选方案 `soft_wrap=True` 实施后**真实推理模型运行验证失败**——碎行仍在（回答前出现 `.`/`11` 等孤立碎片各自成行）。真实终端的主机制不是宽度折行，而是 **Live 拦截**：agent_loop 在第一个 thinking chunk 就触发 `on_stream_start` → `StreamRenderer.start()` 启动 Live，之后 `feed_thinking` 的每次 `console.print` 被 Live 拦截为独立行块（`end=""` 失效），且每个碎片后跟 Live 刷新的 `\r\x1b[2K`（回车+整行擦除）——碎片被擦除/打断，只剩零星碎片幸存各自成行。上方分析的宽度折行机制只在无 Live 路径存在（次要），单测用文件控制台（Live 拦截不生效）所以没抓住。**最终修复**：Live 延迟到第一个正文 delta（`feed_stream`）才启动，思考期间直连顺序写入（soft_wrap 保留，管无 Live 路径的折行）；正文开始前收尾思考行。`force_terminal=True` 的 ANSI 级验证：旧行为每碎片后跟 `\r\x1b[2K`，新行为思考文本连续完整。4 个新测试（Live 延迟启动+无擦除码 / 思考仅无正文收尾 / 超宽无折行 / 自带换行保留），1158→1162。

✅ **D2【行为·高】危险命令被拒后 agent 自主找绕过路径，而非停下求助**
现象（A2 真实验证时实测）：用户让删 `/tmp/a2test`，agent 连续被拒 4 条危险命令（`rm --recursive --force`→`rmdir /S /Q`→`cmd /c rmdir`→`del /Q && rmdir`，正则全部正确命中并弹窗、用户全拒），但 agent 没有停下，而是继续自主换方式,第 12 轮用 `python -c "shutil.rmtree(...)"`（不匹配任何危险正则）**GRANTED 并真的删除了目录**——共 13 轮、烧 97k tokens。
根因：拒绝一条命令的语义是"这条不行"，agent 据此重构等价命令重试；黑名单只认命令签名，语义等价的未列命令（python shutil / os.remove / 移动到临时目录等）畅通无阻。这是 A2「诚实边界」（黑名单不可穷尽）在行为层的放大——**绕过之所以得逞，本质是"被拒后继续找路"的行为，而非正则不够全**。比 A2 正则加固更本质。
候选方案（需设计，未定）：① 连续 N 次危险命令被拒后，agent 停止本目标并回问用户（把"反复被拒"当作强信号）；② 把用户的 DENY 记为会话级软意图（"用户不想删这个目标"），后续语义相近操作预警或直接挡；③ 工具层面：破坏性操作（rm/rmdir/del/shutil.rmtree/移动删除等）归一化为"删除意图"识别，而非逐命令签名——但这又回到不可穷尽问题，治标。
诚实边界：完全防住语义绕过在架构上不可能（同 A2）；本条目目标是"降低被拒后无意义绕过的概率 + 及早把决定权交回用户"，不是"堵死所有绕过"。工作量：中（行为策略设计 + agent_loop 集成 + 真实验证）。

**已修复——采用方案 ①（连续被拒熔断）**：
- **范围**：熔断统计**任何确认框被用户拒绝**——危险命令确认、项目外路径确认、hook（`[[hooks]] action=confirm`）确认。以权限判定 reason `user_confirm:no` + hook 确认被拒为准。自动策略拒绝**不计数**——敏感路径拒绝（`path_guard:sensitive`）、显式 deny 规则、无 UI 默认拒绝仍只是跳过该次调用、任务继续（那是策略在拦，不是用户在说"别做"）。初版只统计危险命令被拒（靠 `last_check_was_dangerous` peek 属性识别，该属性已随扩展移除）。
- **计数**：`AgentState` 加 `consecutive_confirm_denials`（每轮 run() 重建自动重置）。`agent_loop._check_permission` 里确认框 DENIED→+1、确认框 GRANTED→归零；未弹确认的调用中性（被拒之间的只读分析不重置）。
- **熔断**：`_should_continue` 加守卫，被拒 ≥ `max_consecutive_denials`（默认 1，拒一次即停）时设 `stop_reason="confirm_denied"` 停循环（复用现有 `stopped_early` 熔断机制，零新机制）。
- **回问用户**：run() 熔断分支按 stop_reason 定制 final_content（中文回问"继续找绕过不是你想要的，请告诉我如何处理"）；`app.py` 按 stop_reason 显示区别于迭代上限的提示。
- **配置**：`AgentConfig.max_consecutive_denials = 1`（用户拒绝确认框通常就是"别做"，首次被拒即停、把决定权交回用户；调大可给被拒后修正重试的空间），config.toml.example 加说明。
- **测试**：4 个新测试（熔断触发 / 放行重置计数 / 未弹确认的调用中性 / 计数属性），全量 1059 passed。
- **真实验证**：复现 D2 事故脚本（rm→rmdir→del→python -c shutil.rmtree），确认第 3 次被拒后 agent 停下（iterations=3），第 4 步 python 内联解释器绕过从未执行（验证时默认阈值为 3；现默认阈值 1、`stop_reason="confirm_denied"`，首次被拒即停，且项目外路径确认与 hook 确认被拒同样触发）。
- **与 D3 的关系**：D3 执行层（内联解释器正则 + 写后执行检测 + 沙箱）让绕过路径也弹确认；D2 行为层让连续被拒后停下。两者叠加才构成完整防线——D2 在阈值内仍可能发生少量绕过尝试，D3 兜住这些尝试的执行。

✅ **D3【安全·高】内联解释器执行绕过命令黑名单 + Windows 无 OS 沙箱底线**
现象（A2 真实验证时两次实测）：
- 删目录场景：4 条危险命令（rm/rmdir/del 各形态）全被 A2 正则正确拦下并被用户拒绝后，agent 用 `python -c "import shutil; shutil.rmtree(...)"` → GRANTED（mode:ask）→ 目录真被删。
- 删文件场景：`delete_file` 工具走 PathGuard 弹"write access outside project directory"被用户拒绝后（A1 修复正确工作），agent 用 `python -c "import os; os.remove(...)"` → GRANTED → 文件真被删。
根因（执行层，区别于 D2 行为层）：**bash 工具能运行任意解释器**，`python -c "..."`/`node -e`/`perl -e`/`ruby -e`/`sh -c "..."` 引号内是任意代码，命令签名正则**看不进去**。用户拒的是某个具体动作（delete_file 工具、rm 命令），agent 换成"运行一段恰好完成同样效果的解释器代码"，签名匹配彻底失效。这是 A2「黑名单不可穷尽」在**执行层**的体现——与 D2（行为层：被拒后继续找路）互补，两者叠加才构成完整绕过链。
**平台缺口（关键）**：唯一真正气密的防护是 OS 沙箱（`security/sandbox/` bwrap+seatbelt，内核级只读 rootfs + 可写白名单，与命令文本无关）——但**只有 Linux/macOS 后端，Windows 无对应实现**。故 Windows 上命令签名是唯一防线，而它对内联解释器无效 = **Windows 上破坏性操作实际无底线防护**。这是本条目最严重的部分。
**✅ 已修复**：
- **① 内联解释器黑名单**：`DANGEROUS_COMMAND_PATTERNS` 新增 7 条模式（`python -c`/`node -e`/`perl -e`/`ruby -e`/`sh -c`/`bash -c`/`powershell`/`pwsh`），19→26 条，命中即弹确认。
- **② Windows 沙箱**：新增 `sandbox/windows.py` WindowsSandbox（管理员 Low Integrity 内核级 / 非管理员无文件保护、不打启动警告），`create_sandbox()` Windows 不再返回 None。
- **③ 安全边界文档**：config-guide 中英文版分平台标注（Linux/macOS 内核级 vs Windows 路径级 vs 无沙箱），三平台适用。
- **④ 写后执行检测**：`record_written_file()` 追踪本会话写过的文件，`is_executing_written_script()` 检测 `python script.py`/`cmd /c script.bat` 等执行写过的脚本时弹确认（堵住"先写 .py 再执行"绕过）。`would_ask()` 同步更新防流式抢跑。
- **⑤ sandbox 默认开启**：`SecurityConfig.sandbox` 默认值 `False` → `True`，三平台默认有沙箱保护。
- **⑥ `/tmp` 跨平台修正**：`app.py` 的 `allow_write` 从硬编码 `/tmp` 改为 `tempfile.gettempdir()`。
- **⑦ Windows 沙箱**：管理员运行时用 Low Integrity 进程（内核级，`_low_integrity.py` helper 通过 ctypes 降低 token 完整性），等同 bwrap/seatbelt；非管理员无文件保护、不打启动警告（attrib 已禁用——会阻断 agent 自身文件写入；限制仅 config-guide 文档说明）。
- **⑧ Linux unshare 后备**：`create_sandbox()` 在 Linux 上 bwrap 不可用时自动降级到 `unshare --mount --map-root-user`（util-linux 预装），不再需要用户手动装 bwrap。
- **⑨ 启动警告**：sandbox=true 且后端真正不可用时（如 Linux 既无 bwrap 也无 unshare），启动提示明确告知用户沙箱未生效，不再静默跳过。Windows 非管理员不再打启动警告（每次启动的噪音已移除，无文件保护的限制改为仅在 config-guide 文档化）。
- **⑩ deny_write Low Integrity 修复**：`_wrap_low_integrity` 现在对 deny_write 路径显式设回 Medium 完整性，防止 allow_write 目录内的 deny 子路径被一并降级。
- **测试**：全量 1055 passed（含 97 权限+沙箱测试），1 skipped，ruff clean。

**D3 已知遗留（31 项）**：

代码层（15 项）：
1. ✅ **Windows 非管理员 attrib 已禁用**：attrib 会阻断 agent 自身文件写入，`activate()`/`deactivate()` 已改为空操作。非管理员模式无文件保护、不打启动警告（限制仅 config-guide 文档说明）。**D2 缓解**：连续被拒熔断断了"反复试直到绕过"的链，缩小攻击面；但执行层的 OS 限制（无进程级隔离）D2 无法消除——一条不触发危险正则/非写后执行的破坏性命令仍会静默放行执行。完全解决只有管理员 Low Integrity 或 Windows 非管理员进程级沙箱原语（不存在）。
2. ✅ **`./script.py` 路径解析**：已修。`working_dir` 传入 `is_executing_written_script`，相对路径用 bash 的工作目录解析而非 Python CWD。验证：`./exploit.py` 在正确 CWD 下返回 True。
3. ✅ **`_ps_escape` 特殊字符**：已修。转义 `` ` ``→` `` `` `、`$`→`` `$ ``、`"`→`` `" ``。验证：`$PATH` 原样输出不被 PowerShell 展开；`test_ps_escape_special_chars` passed。
4. ✅ **`would_ask` Path.resolve()**：Python 3.11 的 `resolve()` 对不存在的路径不做 stat（仅字符串规范化），已有 `try/except` 兜底。无需代码修改。
5. ✅ **helper `--` 参数解析**：`args.index("--")` 取第一个 `--`，后续 `--` 保留在命令内。逻辑正确。验证：`test_low_integrity_helper_parses_double_dash` passed。
6. ✅ **子 Agent 共享写文件追踪**：已修。`shared_written_files` 指向主 Agent 的 `_session_written_files`（同一对象），`is_executing_written_script` 查两个集合的并集。验证：主 Agent 写的文件子 Agent 检测返回 True。
7. ✅ **attrib 已完全禁用**：attrib 会阻断 agent 自身文件写入（input_history/session/memory），`activate()`/`deactivate()` 改为空操作。非管理员模式不做任何文件保护、不打启动警告（限制仅 config-guide 文档说明）。`_SENSITIVE_HOME_DIRS` 保留（.ssh/.aws/.gnupg/.config/.kube，不含 .mini-agent）但不再使用。
8. ⬚ **Windows 主目录外路径**：Low Integrity 模式下这些路径默认 Medium 子进程写不了（已 E2E 验证）。非管理员模式无文件保护（同 #1）。D2 行为层缓解但不消除——同 #1 的执行层 OS 限制。
9. ✅ **`working_dir` 赋值**：已修。`app.py` 在 PermissionManager 构造后立即赋值 `pm.working_dir = working_dir`。验证：Application 构建后 `working_dir` 为当前目录而非 None。
10. ✅ **`python - < file`**：已修。正则从 `-(c\b|$)` 改为 `-(c\b|(\s|<|$))`，匹配 `-` 后跟空格或 `<`。验证：`python - < malicious.py` 返回 `is_dangerous=True`。
11. ✅ **`python -m module`**：已修。新增 `_PYTHON_M_RE`，`is_executing_written_script` 末尾检查 `-m module_name` 是否对应 agent 写过的 `module_name.py`。验证：`python -m evil_mod`（agent 写了 `evil_mod.py`）被检测。
12. ✅ **每条命令经 PowerShell 延迟**：已修。attrib 模式已完全禁用（activate/deactivate 为空操作），`wrap()` 直接返回原命令零开销。非管理员模式无任何沙箱开销。
13. ✅ **`_collect_deny_paths` 包含 AppData**：已修（同 #7）。改为 `_SENSITIVE_HOME_DIRS` 列表，不扫 AppData。验证：deny 路径不含 AppData。
14. ✅ **GBK 编码**：无需代码修改。helper 的 subprocess 透传 stdout/stderr，最外层 BashTool 的 `_decode_console_bytes`（bash.py:102-103）统一处理 GBK。
15. ✅ **CHANGELOG 测试数量**：已修。更新为 23 个新测试（6 权限 + 17 沙箱），全量 1055 passed。

验证层（10 项）：
16. ✅ **管理员下 `icacls /setintegritylevel` 已验证**：管理员终端实测 `/setintegritylevel "(OI)(CI)L"` 和 `/setintegritylevel "(OI)(CI)M"` 均返回 0（成功），降级和恢复都可用。
17. **unshare 需要 unprivileged user namespaces**：`unshare --map-root-user` 需要内核启用 `kernel.unprivileged_userns_clone=1`，部分 Linux 发行版（如旧版 Debian）默认关着，命令会报 `Operation not permitted`。
18. **namespace 里 `mount -o remount,ro /` 取决于内核版本**：部分内核版本或安全策略（如 AppArmor/SELinux 限制）下可能不生效。
19. **unshare/bwrap 没在真实 Linux 上测过**：在 Windows 上编写，测试只验证命令字符串格式，没验证实际隔离效果。
20. **macOS seatbelt 没在真实 macOS 上测过**：同上，只验证字符串格式。
21. **netsh 防火墙网络限制验证失败并已移除**：管理员实测 `program=%ComSpec%` 只阻断 cmd.exe 自身出站，子进程不受限制。netsh/firewall 代码已完全移除，网络隔离不属于 D3 范围。
22. ✅**整个 D3 没做真实 LLM 运行验证**：没有启动 agent 让 LLM 真的尝试 `python -c` 绕过并验证弹确认框。
23. ✅ **deny_write Low Integrity 已验证**：管理员终端实测 `mode: low_integrity`，deny_write 路径内文件未被覆盖（`content: 'PROTECTED'`）。
24. ✅**`record_written_file` 没有集成测试**：agent_loop 里的调用没验证过在完整 agent 流程中真的会触发写后执行检测。
25. ✅**四个沙箱后端行为不一致**：bwrap/seatbelt/unshare/windows 各有不同的失败模式和边界情况，没有统一的集成测试验证它们提供相同的安全保证。

文档层（4 项）：
26. ✅ **文档已同步**：15 个文档更新（config-guide 中英文、spec、agent-architecture、capabilities、comparison-mewcode、comparison-config-cc、positioning、output-guide 中英文、README 双语、CHANGELOG、tech-notes、roadmap），7 个无需改。
27. ✅ **spec.md 目录树已更新**：`windows.py`、`_low_integrity.py`、`unshare.py` 已加入。
28. ✅ **README 测试数/文件数已更新**：1055 passed、112 源码文件。
29. ✅ **comparison-config-cc.md 已更新**：sandbox 默认 true + 三平台描述。

不属于 D3（2 项）：
30. ✅ **D2 行为层已实现**：任何确认框被拒后 agent 停下回问用户（危险命令/项目外路径/hook 确认；默认阈值 1，拒一次即停，`max_consecutive_denials` 可调大；自动策略拒绝如敏感路径/deny 规则不计数），不再找绕过路径。详见 D2 条目完成记录 + tech-notes §89。D2 断了 D3 事故"反复试直到绕过"的链，但两者是不同层——D2 管行为（要不要继续试），管不了执行层（某条命令能不能真写文件）。Windows 非管理员的执行层 OS 限制（#1/#8）D2 无法消除，只能缩小攻击面。
31. ✅ **全量测试已通过**：1059 passed, 1 skipped。

✅ **D4【中·时序】带副作用的 bash 命令截断重试不再双执行（A3 残留已修复）**
**原问题**：A3 已把 WRITE 类工具延迟到 `_act` 消除双执行，但 bash（ToolCategory.EXECUTE）未纳入——非危险的带副作用 bash（`mkdir`、`npm install`、`git add` 等）仍在流式期间 eager 执行，截断重试后同样可能双跑。
**✅ 已修复**：方案 ② 跨 attempt 结果缓存——截断重试时把已完成的 eager 任务结果按 `(name, args_json)` 签名缓存（`_eager_completed`），重试产出相同签名的工具调用时复用缓存结果创建已完成 Future，`_act` 直接 await 返回不重跑。不需要判断命令是否有副作用（不可穷尽），不牺牲流式延迟收益（只读 bash 仍即时执行），对 WRITE 类工具无影响（category gate 在缓存检查之前拦截）。缓存生命周期限于单次 `_think()` 调用。3 个新测试，1155→1158。

✅ **D5【UX·低】on/off 模式命令无参数时行为不一致且不直觉（已修复）**
4 个 on/off 模式命令的无参数行为各不相同（`extensions/builtin_commands.py`），且都不是用户最直觉的"显示当前状态"：
- `/plan`：无参数 = **无条件打开**（`sub in ("", "on")`），而非 toggle 也非显示状态。验证时暴露：exit_plan_mode 工具关闭 plan 模式后，用户输 `/plan` 想查状态却又打开了
- `/trace`：无参数 = **toggle**（`not app.trace_renderer.enabled`）
- `/explain`：无参数 = **toggle**（`not tr.enabled`）
- `/audit`：无参数 = **toggle**（`not al.enabled`）
**✅ 已修复**：统一为**无参数 = 只显示当前状态不改变**，`on`/`off` 显式切换。4 个 handler 的 `else` 分支（`/plan` 的 `""` 分支）从 toggle/无条件开启改为只返回状态字符串。`/plan` 新增状态显示（`Plan mode: **ON** (read-only)` / `**OFF**`）。description 去掉 "Toggle" 改为 "no args = show status"。4 个新测试，1162→1166。

✅ **D6【安全·高】bash 通道读敏感文件绕过 read_file 拦截（泄漏 API key）**
D2 真实验证时发现：`read_file` 正确拒了 `.env`（敏感文件），agent 立刻改用 `type D:\...\.env`（bash 通道）成功打印、**泄漏真实 API key**。与 D3 同源——bash 绕过工具层保护——但方向是读泄密。根因：敏感文件保护 `PathGuard.is_sensitive_file` 只在 read_file/write_file/delete_file 工具层，bash 命令管道从不查路径，`type`/`cat`/`Get-Content`/`more .env` 作普通命令被 auto-grant。
修复：permission.py 新增 `command_references_sensitive_file()`，token 化命令、命中 `SENSITIVE_FILE_PATTERNS`（复用 path_guard 同一份模式）即路由到确认（reason=`sensitive_file_command`）。用确认而非静默拒绝——可见且拒绝时触发 D2 熔断停目标（静默 auto-deny 不触发 D2，agent 会像 A2 换法子重试）。2 个新测试，1058→1060。详见 tech-notes §90。
**诚实边界**：减速带非围墙，同 D3 黑名单——变量展开（`$SECRET`）、通配、base64/echo 拼接、间接读取等混淆仍可逃逸。真正堵死读泄漏需 OS 沙箱读 ACL（Windows Low Integrity 不限制读 Medium 对象，读保护做不到），架构上同 #1/#8 不可完全消除。本条目把常见明显形态从"静默放行"提升到"弹确认+可熔断"。

✅ **D7【UX·低】用户输入在终端里不够显眼,与 trace/工具/回答输出混在一起难以区分**
**问题**（B4.2 终端验证实测暴露）：用户在 `>` 提示符后输入文字、回车确认后,prompt_toolkit 的输入行留在原地（默认样式,无颜色/无加粗），后面紧接着 trace 行（dim）、工具输出（`╭─ tool ...`）、LLM 流式回答——回看终端滚动历史时很难快速定位"哪些是我打的话、哪些是 agent 的输出"。
**现有视觉元素**：输入区上方有一条 dim 横线（`terminal.py:106` `'─' * console.width`），trace 的 `user` 行（`trace.py:_on_user_message`）用 dim 引号包裹用户文字（但开 `/trace` 才可见，且本身也是 dim），两者都不够醒目。

**✅ 已修复**：三件套——① Theme 新增 `user_input` 亮浅蓝字段（default `#5fd7ff`/dark `#7dcfff`/light 白底可读蓝 `#0969da`；不复用 warning——`#f39c12` 黑底偏暗且语义不同）；② `create_prompt_style()` 根样式 `bold {theme.user_input}`——输入文字打字时和回车后均为 bold 亮浅蓝；③ `get_user_input()` 输入行上下各一条 `user_input` 色横线（上边线输入前打，下边线输入确认后打，`_BG_INTERRUPT` 中断时不打下边线）。菜单/工具栏/滚动条均 noinherit 不受根样式影响。非 TTY 朴素 input() 路径不经过 prompt_toolkit，保留上下横线。

✅ **D8【存储·低】崩溃/硬杀会话永久积累——加默认 40 天启动清理（已修复）**
现状：`SessionStore.cleanup_stale()` 只删"已正常关闭 + 超龄"的会话，`closed_cleanly=False` 的一律跳过（崩溃恢复候选不能删）。但恢复只取本项目**最新**一个崩溃会话——非最新的崩溃会话、以及再也不启动的项目的崩溃会话**永久留盘**（`~/.mini-agent/sessions/`），只能 `/session delete` 或手动删文件。远程模式会话持久化接入后暴露此积累风险（终端模式既有行为，非新引入）。
**已修复**：`MemoryConfig` 新增 `crashed_session_cleanup_days: int = 40`（0 = 永久保留）；`cleanup_stale()` 增加 `crashed_max_age_days` 参数——`closed_cleanly=False` 且超过 40 天的也删除（比正常 30 天更宽松：崩溃会话有恢复价值多留 10 天）。清理在崩溃恢复检测之前执行——40 天前的崩溃会话直接清掉不进恢复候选。`config.toml.example` 补 `[memory]` 两个清理配置的文档。app.py 和 remote/server.py 两个调用点同步传入新参数。3 个新测试（超龄崩溃被删/40 天内保留/0 禁用/正常 30 天不受影响），1179→1182。详见 tech-notes §103。

✅ **D9【UX·低】/session list 无分页无条数限制——上百会话整屏刷过（已修复）**
现状（远程会话持久化真实验证实测暴露）：`/session list` 把 `list_sessions()` 的全部结果逐行输出——实测 159 个会话（6.8MB）一次刷 159 行，把之前的终端内容全部顶出屏幕；用户实际只关心最近几个。远程模式浏览器里同样一大坨。`--tag` 过滤是唯一的收窄手段，但没打过标签的会话无法过滤。
方案：默认只显示**最近 20 条**（list 已按 last_active 降序，直接切片即可）；尾行提示总数与查看方式：`共 159 个会话，显示最近 20 个 —— /session list --all 查看全部`；新增 `--all` 参数显示全部；`--tag` 过滤后同样默认截断 20 条（过滤+截断组合）。数字 20 定为常量（如 `_SESSION_LIST_LIMIT`），不进配置——没有配置价值，`--all` 已是出口。
验证要点：>20 个会话默认只显示 20 行+尾行提示 / `--all` 显示全部 / ≤20 个不显示尾行提示 / `--tag` 与 `--all` 组合正常。工作量：小（一个切片+一行提示+参数解析）。
**✅ 已修复**：`_SESSION_LIST_LIMIT = 20` 模块常量（不进配置，`--all` 已是出口）；list 参数解析改 token 扫描（`--all` / `--page N` / `--tag <name>`，任意顺序组合）；**真分页**：`--page N` 显示第 (N-1)*20+1 ~ N*20 条，尾行双语提示 `Page N/M (总数) —— --page N+1 下一页 / --all 全部`（末页无下一页提示），页码超范围报错并提示总页数，`--all` 优先于 `--page`。7 个新测试（>20 截断+尾行 / --all 全量无尾行 / ≤20 无尾行 / --tag 组合 / --page 2 末页 / 页码超范围 / --all 优先），1182→1189。详见 tech-notes §104。

- **Textual TUI**：mewcode 仍用 textual>=2.1；mini "Rich+ptk 补体验、不迁移" 成立
- **图片多模态**：mewcode 并无真多模态（MCP ImageContent 仅字符串化 `[image: mime]`，tool_wrapper.py:76）——非差距
- **多客户端会话隔离**：mewcode 同样单 agent 广播（remote.py:91）无隔离——非差距
- **常驻队友 transcript 恢复**：mewcode `teams/transcript.py` 独有；mini 一次性 worker 适配论证基本成立，若走向常驻队友需重评估。**论证增援**（深挖实测）：transcript.py 的 save/load 在 mewcode 全库**没有任何调用方**——队友跨重启持久化只是脚手架未接线；且 Windows 强制 in-process 后端（窗格能力反而 mini 的 wt 支持更完整）——常驻体系的成熟度低于对照文档此前的预估

✅ **D10【UX·中】/spawn 默认改为后台模式（自动投递，已实现）**
现状：`/spawn <task>` 默认是前台模式——子 agent 跑完结果静悄悄存到文件，用户需手动 `/spawn wait` 取。后台模式 `/spawn --background <task>` 已实现完整的自动投递（子 agent 完成后中断用户输入等待、自动弹出结果），但需显式加 `--background` 参数。两者功能实质重叠：前台模式除了"需要手动 wait"之外无任何额外价值——它是后台投递实现前的权宜设计，投递做好后没把默认行为跟着改。
方案：把 `/spawn <task>`（无 flag）的默认行为改为后台模式（等同于现在的 `--background`）——跑完自动投递，不需要 wait。保留 `--wait` 参数用于"我就等这一个结果、阻塞到完成"的少数场景（语义反转：现在 --background 是 opt-in，改后 --wait 是 opt-in）。`--background` 参数保留为 no-op 别名（向后兼容，不报错）。
影响面：`extensions/builtin_commands.py` _make_spawn handler 的默认分支、`core/subagent.py` SubAgentManager.spawn 调用方式、app.py 的 `_run_agent_and_report` 接线。涉及真实 LLM 验证（spawn 后不输 wait、结果是否自动弹出）。工作量：小-中。
**✅ 已实现**：改动只需 `_make_spawn` 一个函数——单任务与 `-p` 并行的默认分支统一改调 `spawn_background`（原 background 专用分支合并删除；`spawn_background` 签名本就支持 isolation/agent_type/context_summary 透传，subagent.py 零改动）；`--background` 解析保留但变 no-op（向后兼容）；`--wait` 保持阻塞式 opt-in（进度面板+内联完整格式化结果）；`--pane` 与 `wait`/`list`/`cancel` 子命令不变（wait 仍服务 pane 收集与手动阻塞）。usage 文本与注册 description 同步。诚实边界：后台投递结果经 LLM 转述且 4000 字符截断，`--wait` 返回未截断的完整格式化输出（8000 字符 cap）——需要完整结果时用 `--wait`。4 个新测试（默认走 spawn_background / -p 默认后台 / --background no-op / --wait 阻塞回归），1189→1193。详见 tech-notes §106。

☐ **D11【安全·中】远程模式 TLS 支持（原生 wss 或反代方案文档化）**
**来源**：C1 修正（远程认证对比）时明确暴露的自身短板——认证维度 mini 反超 mewcode，但传输加密两者皆缺，且这对 mini 是**认证有效性问题**：token 在明文 `ws://` 信道传输，公网场景下嗅探者拿到 token 即可绕过认证——认证的价值被明文传输打了折扣。
**对比参照**（复验 mewcode `remote.py` + `__main__.py` 实测）：mewcode 远程模式无 TLS、无认证、默认绑定 `0.0.0.0:18888` 且 CLI 不可改——三重叠加下局域网任何设备可无认证完全控制 agent；mini 默认 localhost/可配 host/可选 token，仅缺 TLS 一项。
**现状**：唯一缓解是 server.py 启动横幅的文字警告（"公网暴露请加反代 + TLS，如 nginx + Let's Encrypt"），没有可操作的配置指引，也没有原生 TLS 选项。
**方案**（二选一或先轻后重）：
① **轻（推荐先做）**：反代方案正式文档化——config-guide 双语新增"远程模式公网部署"一节：nginx/caddy 的 wss 反代配置示例（含 WebSocket upgrade 头）、证书获取（Let's Encrypt/自签）、`--host 127.0.0.1` 只监听本机让反代做入口、token 与 TLS 组合使用说明。零代码，纯文档。
② **重（可选后做）**：原生 TLS——`--tls-cert <pem> --tls-key <pem>` CLI 参数，`websockets.serve(ssl=ssl_context)`，浏览器端 `wss://` 自适应。工作量小-中，但证书管理（获取/续期/路径）成为用户负担，且自签证书浏览器告警的引导成本高——反代方案已是业界标准，原生 TLS 的增量价值有限。
**评估**：内网/本机场景（当前主要用途）token 认证已够、无 TLS 可接受；公网场景是真实缺口。优先级中——被公网部署需求触发时再做②，①可随时做。验证要点（做①时）：按文档配置 nginx 反代后浏览器经 wss 正常对话 + token 认证生效；（做②时）：wss 连接 + 证书校验 + ws 明文模式回归。

---

*本文档随版本迭代更新。完成一项后请把该项移入 tasks.md 对应阶段并打勾。*