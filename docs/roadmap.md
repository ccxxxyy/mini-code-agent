# Mini-Code-Agent 后续演进路线图

> 当前版本 v1.0.0，P1-P57。
> 本文档收录开发过程中**有意推迟**的增强项——每一项在代码里都预留了升级插槽，
> 按优先级和工作量组织，作为后续版本的开发依据。

## 已完成的差异化方向（positioning.md 方向 1）

- [x] **CC 对照评测框架**（`benchmarks/`）：10 个标准任务、headless runner、自动化验证、Markdown 报告生成。**10/10 通过，总成本 $0.0015**。CC 结果模板已就位，待手动补齐后即可生成对比表格。

---

## 一、v0.3.0 候选：已预留插槽的核心升级（4 项）

这些是开发时明确"先简后繁"的取舍，接口已就位，实现即插即用。

### 1.1 LLM 摘要压缩（升级 SummarizeOldest 策略）✅ 已完成

> 已实现 `LLMSummarizeOldest(CompressionStrategy)`：LLM 语义摘要 + 失败回退提取式 + 防递归（一次性直连调用不经过 AgentLoop）。4 个 MockLLM 单测。作为机制实验 1 的第三个对照臂投入使用（见 `experiments/`）。未接入默认压缩链（向后兼容），显式配置启用。

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

> 已实现：三套主题（default/dark/light）全面接入 6 个 UI 文件（terminal/input_handler/trace/teach/board/confirm），`/theme` 列出/切换/持久化（`~/.mini-agent/.theme`），运行时切换即时生效（prompt session 重建 + 共享 theme 引用）。7 个新测试，276 个全过。
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
| 插件生态（有意延后） | plugin_loader 完善：第三方 pip 包可注册工具/命令/技能——见"明确不做"：没有用户基础前是过早投资 |
| Streaming 中间态 ✅ | P23 实现：on_tool_call_assembling 回调 + Diff 预览（整行背景色 diff） |
| 文件变更汇总 ✅ | P24 实现：轮末显示本轮文件清单（+绿新建/~黄修改/-红删除）+ delete_file 专用工具（第 8 个内置工具） |
| 上下文感知 ✅ | P25 实现：启动自动注入项目指令文件（AGENT.md/CLAUDE.md/.mini-agent/instructions.md 优先级递减）+ 用户级全局指令 |
| 对话分叉/回滚 ✅ | P26 实现：/undo 轮次回滚 + /fork 深拷贝分叉（差异化能力——CC 服务端历史做不到） |
| 操作级撤销 ✅ | P27 实现：每轮文件快照（5 轮保留/30MB 上限/磁盘存储会话结束清空），/undo 新建删掉/修改还原/删除找回 |
| 工具链录制/回放 ✅ | P28 实现：EventBus 订阅式录制 + _execute_single_tool 安全等价回放（权限/hook/快照全走） |
| 成本仪表盘 ✅ | P29 实现：LLMResponseEvent 扩展 + CostTracker 订阅者（第 5 个）+ [cost] 配置计价 + 预算 80/100 警告 |
| 持久化任务系统 ✅ | P32 实现（S12 补全）：TaskStore 磁盘持久 + /todo 命令 + blockedBy 依赖追踪 + 解锁提示 |
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

## 七、剩余待办清单（P36 后的完整盘点）

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

### 明确不做（有意决策，非遗漏）

| 项 | 理由 |
|---|---|
| 插件生态（plugin_loader） | 没有用户基础前是过早投资——生态建设需要先有用户 |
| S14 Cron 定时调度 | 终端交互工具用 OS 的 cron/Task Scheduler 更合适 |
| MCP SSE 长连接 | POST 请求-响应已覆盖全部工具功能，ABC 留有 SSETransport 扩展位 |
| bash 文件变更跟踪 | 需要文件系统快照对比，成本远超收益（undo/汇总的已知盲区） |

## 六、优先级建议

如果按"用户可感知价值 / 工作量"排序，建议实施顺序：

1. ~~2.3 /spawn + /team 命令~~（✅ 已完成）
2. ~~2.5 强弱模型混编配置化~~（✅ 配置层 + /team 接线已完成）
3. ~~2.2 SubAgent 进度面板~~（✅ 已完成）
4. ~~2.6 LLM 自主派生 SubAgent~~（✅ 已完成）
5. ~~3.3 会话自动保存~~（✅ 已完成）
6. ~~2.1 /theme 命令~~（✅ 已完成）
7. ~~1.4 工具并行~~（✅ 已完成）
8. 其余按需推进

> 1.1 LLM 摘要压缩已在 P11 完成（且实验数据显示默认不开启是正确的）。

---

*本文档随版本迭代更新。完成一项后请把该项移入 tasks.md 对应阶段并打勾。*