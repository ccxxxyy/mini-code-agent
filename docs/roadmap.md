# Mini-Code-Agent 后续演进路线图

> 当前版本 v0.2.0，七个开发阶段（P1-P7）已全部完成。
> 本文档收录开发过程中**有意推迟**的增强项——每一项在代码里都预留了升级插槽，
> 按优先级和工作量组织，作为后续版本的开发依据。

---

## 一、v0.3.0 候选：已预留插槽的核心升级（4 项）

这些是开发时明确"先简后繁"的取舍，接口已就位，实现即插即用。

### 1.1 LLM 摘要压缩（升级 SummarizeOldest 策略）

- **现状**：`memory/compressor.py` 的 Stage 2 用提取式摘要——把旧消息按"角色+前300字符"机械拼接，不调 LLM。
- **要做什么**：新增 `LLMSummarizeOldest(CompressionStrategy)`，把待压缩消息发给 LLM 生成语义摘要，保留推理脉络而非文本碎片。
- **插槽位置**：`CompressionStrategy` ABC 已定义，`Compressor(strategies=[...])` 支持自定义策略列表，写好类替换进去即可。
- **注意点**：摘要调用本身消耗 token；防递归（压缩期间不能再触发压缩）；测试用 MockLLM。
- **工作量**：小（~100 行 + 测试）

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

### 2.2 SubAgent 进度实时面板

- **现状**：SubAgent 在后台跑时终端没有任何显示，只能等 wait_all 返回。`SubAgentManager.list_active()` / `get_status()` 查询接口已就位。
- **要做什么**：用 Rich 的 Live + Table 做实时面板——每个活跃 SubAgent 一行（agent_id / 任务摘要 / 当前阶段 / 已调工具数 / 耗时），每秒刷新，全部完成后收起。
- **插槽位置**：AgentPhase 状态机已有（IDLE/THINKING/TOOL_CALLING/...），EventBus 的 SubAgent 事件可订阅。
- **工作量**：中（~150 行）

### 2.3 /team 和 /spawn 命令入口

- **现状**：SubAgent 和 AgentTeam 的能力只能通过 Python 代码调用，终端对话里没有入口。
- **要做什么**：
  1. `/spawn <任务>` — 派生单个后台 SubAgent，配合 2.2 的面板显示进度
  2. `/spawn -p <任务1> | <任务2>` — 并行派生多个
  3. `/team <大任务>` — 走 Planner 分解 + AgentTeam 编排的完整流程
  4. worktree 隔离加 `--isolated` 参数
- **插槽位置**：SlashCommandRegistry.register 直接注册；SubAgentManager/AgentTeam/Planner 全部可复用。
- **工作量**：中（~200 行 + 测试）

### 2.4 双 Esc 中断流式输出

- **现状**：LLM 输出过程中只能 Ctrl+C（会连整个程序一起打断的风险）。
- **要做什么**：流式期间监听按键，双击 Esc 调 `agent_loop.cancel()` 优雅中断当前轮，回到输入框。
- **工作量**：小（~50 行，prompt_toolkit 键盘监听）

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

## 五、优先级建议

如果按"用户可感知价值 / 工作量"排序，建议实施顺序：

1. **2.3 /spawn + /team 命令**（多 Agent 能力终于有入口，演示效果最好）
2. **2.2 SubAgent 进度面板**（配合 2.3，可见即可信）
3. **1.1 LLM 摘要压缩**（长对话质量的实质提升）
4. **3.3 会话自动保存**（防数据丢失，用户安全感）
5. **2.1 /theme 命令**（三套主题已画好，就差接线）
6. **1.4 工具并行**（复杂任务提速）
7. 其余按需推进

---

*本文档随版本迭代更新。完成一项后请把该项移入 tasks.md 对应阶段并打勾。*