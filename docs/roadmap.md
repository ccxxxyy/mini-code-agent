# Mini-Code-Agent 后续演进路线图

> 当前版本 v0.2.0，P1-P7 + P8 评测框架已全部完成。
> 本文档收录开发过程中**有意推迟**的增强项——每一项在代码里都预留了升级插槽，
> 按优先级和工作量组织，作为后续版本的开发依据。

## 已完成的差异化方向（positioning.md 方向 1）

- [x] **CC 对照评测框架**（`benchmarks/`）：10 个标准任务、headless runner、自动化验证、Markdown 报告生成。**10/10 通过，总成本 $0.0015**。CC 结果模板已就位，待手动补齐后即可生成对比表格。

---

## 一、v0.3.0 候选：已预留插槽的核心升级（4 项）

这些是开发时明确"先简后繁"的取舍，接口已就位，实现即插即用。

### 1.1 LLM 摘要压缩（升级 SummarizeOldest 策略）✅ 已完成

> 已实现 `LLMSummarizeOldest(CompressionStrategy)`：LLM 语义摘要 + 失败回退提取式 + 防递归（一次性直连调用不经过 AgentLoop）。4 个 MockLLM 单测。作为机制实验 1 的第三个对照臂投入使用（见 `experiments/`）。未接入默认压缩链（向后兼容），显式配置启用。

### 1.2 LLM 记忆提取（升级 MemoryExtractor）

- **现状**：`memory/extraction.py` 用正则匹配 "always/prefer/don't" 等固定句式，覆盖面有限。
- **要做什么**：会话结束时把对话发给 LLM，用结构化 prompt 提取"项目约定/用户偏好/技术事实"三类记忆（JSON 输出）。
- **插槽位置**：`MemoryExtractor.maybe_extract()` 接口不变，替换内部 `_extract_candidates`；去重逻辑可复用；`auto_extract` 配置开关已存在。
- **工作量**：小（~80 行 + 测试）

### 1.3 MCP HTTP Transport

- **现状**：`tools/mcp/transport.py` 只有 `StdioTransport`（子进程），接不了远程 MCP 服务器。
- **要做什么**：新增 `HTTPTransport(MCPTransport)`，用 httpx 实现 MCP Streamable HTTP 传输。
- **插槽位置**：`MCPTransport` ABC（send/close）已定义；`MCPManager.connect_server` 已有 transport 分支判断；`MCPServerConfig.url` 字段已存在。
- **工作量**：中（~150 行 + 测试）

### 1.4 工具并行执行

- **现状**：`core/agent_loop.py` 的 `_act()` 顺序执行多个 tool_calls——有意为之，防止权限确认弹窗交错。
- **要做什么**：先对所有 tool_calls 做权限预检，无需确认的用 `asyncio.gather` 并行执行，需要确认的逐个排队询问。
- **插槽位置**：`_act()` 是独立方法，改造范围封闭；spec.md 第 9.3 节已有并行设计参考。
- **注意点**：并行时 UI 回调（on_tool_start/end）会交错，需要按 call_id 分组渲染。
- **工作量**：中（~100 行改造 + UI 适配 + 测试）

---

## 二、v0.4.0 候选：UI/交互增强（4 项）

### 2.1 /theme 命令切换主题

- **现状**：`ui/themes.py` 已有 default/dark/light 三套 Theme 数据（8 个语义色位），但没有接入渲染——Terminal 和 PROMPT_STYLE 里的颜色还是硬编码。
- **要做什么**：
  1. Terminal/StreamRenderer/PROMPT_STYLE 改为从 Theme 对象取色
  2. 新增 `/theme` 命令：`/theme` 列出主题、`/theme dark` 切换
  3. 选择持久化到 `~/.mini-agent/` 下（AgentConfig.theme 字段已存在）
- **工作量**：中（改色引用面较广，~200 行）

### 2.2 SubAgent 进度实时面板 ✅ 已完成

> 已实现：`ui/board.py` SubAgentBoard（Rich Live + Table，4fps 刷新，transient 收起）+ `SubAgentManager.active_snapshots()` 公开快照接口（agent_id/任务/阶段/工具数/耗时）。`/spawn wait` 和 `/team` 阻塞期间自动显示面板，完成后收起展示结果。7 个新测试，250 个全过。

### 2.3 /team 和 /spawn 命令入口 ✅ 已完成

> 已实现：`/spawn` 完整子命令集（single/parallel/list/wait/cancel/--isolated）+ `/team` 命令（Planner 分解 + 并行 SubAgent + 汇总报告 + --isolated）。Application 装配 SubAgentManager + WorktreeManager。create_for_role 接线完成（Planner 用 planner_profile、Worker 用 worker_profile）。SubAgentSpawn/CompleteEvent 两个新事件。8 个新测试，243 个全过。

### 2.5 强弱模型混编配置化（机制实验结论的产品化）✅ 配置层已完成

> 已实现：`AgentConfig.planner_profile / worker_profile` 字段 + `MINI_AGENT_PLANNER_PROFILE / WORKER_PROFILE` 环境变量 + `ProviderRegistry.create_for_role(config, "planner"|"worker")` 工厂（未配置/profile 不存在时回退主模型）。5 个单测。`.env.example` 已附示例。
> **待 2.3 落地时接线**：`/team` 命令装配 AgentTeam 时改用 `create_for_role` 创建 Planner 和 Worker 的 LLM 即可（各一行）。

- **依据**：机制实验 2 验证 strong-weak 编排是帕累托最优——强 Planner + 弱 Worker 全通过且成本最低，见 `experiments/README.md`。

### 2.4 双 Esc 中断流式输出

- **现状**：LLM 输出过程中只能 Ctrl+C（会连整个程序一起打断的风险）。
- **要做什么**：流式期间监听按键，双击 Esc 调 `agent_loop.cancel()` 优雅中断当前轮，回到输入框。
- **工作量**：小（~50 行，prompt_toolkit 键盘监听）

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

### 3.1 TOML 配置文件支持

- **现状**：配置只有 .env + 环境变量 + CLI 三层；spec 设计的项目级/用户级 TOML 配置（`.mini-agent/config.toml`）未实现。
- **要做什么**：ConfigLoader 增加 TOML 解析层（Python 3.11 自带 tomllib，零依赖），优先级插在 env 之下：defaults → user toml → project toml → .env → env → CLI。
- **插槽位置**：`_apply_cli` 的 dict 覆盖机制可复用；spec.md 第 13.3 节有完整格式设计。
- **工作量**：中（~150 行 + 测试）

### 3.2 PRE_LLM / SESSION_END Hook 接线

- **现状**：HookStage 枚举定义了 7 个阶段，但只有 PRE_TOOL / POST_TOOL 真正接进了执行流。
- **要做什么**：
  1. PRE_LLM：LLM 调用前触发——可用于注入相关记忆（搜索 PersistentMemory 把相关条目附到 system prompt）
  2. SESSION_END：会话结束触发——自动执行 MemoryExtractor.maybe_extract + SessionStore.save
- **插槽位置**：HookManager.run 已支持任意 stage；agent_loop._think 和 app.run 的 finally 是接线点。
- **工作量**：小（~60 行）

### 3.3 会话自动保存

- **现状**：会话要手动 `/session save`；意外退出（崩溃/断电）对话就丢了。
- **要做什么**：每轮对话结束后自动 save（节流：距上次保存 >30s 才写）；启动时检测最近未正常关闭的会话并提示恢复。
- **工作量**：小（~80 行）

### 3.4 上下文溢写（Context Overflow 兜底）

- **现状**：压缩后仍超窗口时只是继续发送，可能被 API 拒绝。
- **要做什么**：发送前用 count_messages_tokens 预检，超限时强制走 SlidingWindow 截到安全水位，并向用户显示警告。
- **插槽位置**：ContextManager.tokens_remaining 已有；agent_loop._think 是接线点。
- **工作量**：小（~50 行）

---

## 四、v1.0.0 里程碑：稳定与生态（远期）

| 项 | 说明 |
|---|---|
| 接口冻结 | Tool / LLMProvider / HookFn / CompressionStrategy ABC 定稿，承诺向后兼容 |
| 覆盖率门禁 | CI 加 pytest-cov，核心模块 ≥80% 覆盖率作为合并条件 |
| PyPI 发布 | `pip install mini-code-agent` 直接安装，不再需要克隆源码 |
| 插件生态 | plugin_loader 完善：第三方 pip 包可注册工具/命令/技能 |
| Streaming 中间态 | 工具调用参数流式显示（现在要等 JSON 组装完才显示工具行） |
| Windows 终端适配 | CMD/PowerShell/Windows Terminal 的颜色与按键差异全面测试 |

---

## 五、差异化方向（来自 positioning.md，与上面技术项正交）

| 方向 | 状态 | 说明 |
|---|---|---|
| CC 对照评测 | ✅ 已完成 | benchmarks/ 框架 + 10/10 数据 |
| 机制透明度演示 | ✅ 已完成 | /trace 命令实时展示 ReAct 内部状态（阶段/权限判定+依据/工具耗时/LLM 元信息） |
| 垂直场景定制 | ✅ 已完成 | `/explain` 教学模式（TeachRenderer 确定性面板 + Skill 辅助）+ `/audit` 合规审计（EventBus JSONL）+ offline-ollama 内网 Skill |
| 机制实验 | ✅ 已完成 | `experiments/` 压缩策略 A/B（none/extractive/llm 三臂）+ 强弱模型混合编排（三臂），数据见 experiments/README.md |
| 开源社区 | 待做 | PyPI 发布 + README 英文化 + "the readable agent" 定位 |

## 六、优先级建议

如果按"用户可感知价值 / 工作量"排序，建议实施顺序：

1. ~~2.3 /spawn + /team 命令~~（✅ 已完成）
2. ~~2.5 强弱模型混编配置化~~（✅ 配置层 + /team 接线已完成）
3. ~~2.2 SubAgent 进度面板~~（✅ 已完成）
4. ~~2.6 LLM 自主派生 SubAgent~~（✅ 已完成）
5. **3.3 会话自动保存**（防数据丢失，用户安全感）
6. **2.1 /theme 命令**（三套主题已画好，就差接线）
7. **1.4 工具并行**（复杂任务提速）
8. 其余按需推进

> 1.1 LLM 摘要压缩已在 P11 完成（且实验数据显示默认不开启是正确的）。

---

*本文档随版本迭代更新。完成一项后请把该项移入 tasks.md 对应阶段并打勾。*