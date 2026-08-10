# Mini-Code-Agent 能力对照表

> 本文档逐条对照项目最初的 18 项需求（12 项核心功能 + 6 大技术层面），
> 说明每一项的实现位置、实现方式与验证证据。
> 当前版本 v1.0.0，544 个测试全部通过。

---

## 第一部分：12 项核心功能

### ✅ 1. 类 Claude Code 的终端交互体验

**要求**：基于 LLM 流式响应 + 多轮对话，边想边输出，整个对话过程和 Claude Code 一致。

**实现**：
- 流式渲染：`ui/renderer.py` — Rich Live 组件 15fps 实时渲染 Markdown（代码高亮/粗体），逐 token"边想边输出"
- 多轮对话：`models/message.py` 的 Conversation 全量重放历史，LLM 记住上下文
- 交互细节：`>` 提示符、输入 `/` 弹出命令下拉菜单（上下键选择/Tab 补全/删字符重新过滤）、输入历史跨会话保留（↑ 键翻历史）、底部工具栏实时显示当前 LLM、工具调用 `╭─ ╰─` 连线展示、每轮 token 用量统计
- 启动体验：`mini` 一个单词全局启动（同 `claude`）

**验证**：真实 API 流式验证；终端交互全部手工验证过

---

### ✅ 2. 六个核心编程工具

**要求**：至少 ReadFile, WriteFile, EditFile, Bash, Glob, Grep 六个工具，覆盖高频场景。

**实现**（`tools/builtin/`，全部实现 Tool ABC）：

| 工具 | 能力 |
|---|---|
| read_file | 带行号读取，offset/limit 大文件分页，超大文件拒绝 |
| write_file | 写入/覆盖，自动创建父目录 |
| edit_file | 精确字符串替换，唯一匹配约束防误改，replace_all 批量 |
| bash | 跑命令，超时熔断，exit code 标注，Win/Unix 双平台 |
| glob | 文件名模式匹配，按修改时间排序，跳过噪音目录 |
| grep | 正则内容搜索（关键词搜索），include 文件过滤，context 上下文行 |

**验证**：24 个工具单测 + 真实 API E2E（Agent 自主读 README、grep 搜 TODO）

---

### ✅ 3. 自主任务循环（Agent Loop / ReAct）

**要求**：Agent 能自己拆任务、调用工具、看结果、再决策。

**实现**（`core/agent_loop.py`）：
- ReAct 循环：THINK（LLM 流式生成）→ 有 tool_calls 则 ACT（执行工具）→ OBSERVE（结果写回对话）→ 回到 THINK，直到 LLM 给出最终回答
- 自主性本质：工具结果作为 TOOL 消息进入对话，LLM 看到结果自然继续推理——循环不含任务逻辑，所有决策由 LLM 做出
- 熔断保护：max_iterations 上限（50）、用户取消、双层死循环检测（同签名连续 6 次 + 同工具名连续 8 轮每轮出现——P35 实验后升级 v2，不误杀批量并行）

**验证**：8 个 MockLLM 单测覆盖完整链路；真实 API 验证 Agent 自主多步执行（一次任务里自主 glob→read→回答）

---

### ✅ 4. MCP 协议接入

**要求**：无缝挂载任意符合 MCP 规范的外部工具服务（GitHub、Slack、数据库、12306 等）。

**实现**（`tools/mcp/`）：
- `transport.py`：StdioTransport — 启动 MCP 服务器子进程，JSON-RPC 2.0 通信
- `client.py`：MCPManager — 标准握手（initialize → initialized → tools/list）、多服务器管理、工具调用代理
- `adapter.py`：MCPToolAdapter — MCP 工具的 inputSchema 自动转为内部 ToolSchema，以 `mcp_{server}_` 前缀注册进同一个 ToolRegistry
- 无缝的含义：适配后的 MCP 工具和内置工具走完全相同的调用管道——权限检查、Hook 链、错误处理自动生效

**验证**：7 个单测（FakeMCPManager 模拟服务器）

---

### ✅ 5. Skill 技能包系统

**要求**：把 prompt+工具+资源打包成可装载的技能包，持续拓展能力。

**实现**（`extensions/skills.py`）：
- 技能包 = 目录 + SKILL.md（YAML front-matter 声明 name/triggers/tools + Markdown 正文作为 prompt）
- 装载：`load_all()` 扫描技能目录自动发现
- 激活：prompt 以带标记形式注入 system prompt；停用时精确移除，可逆可叠加
- 触发：用户消息含触发词时自动匹配建议
- 内置技能包：`skills/code_review/`（代码审查）、`skills/init_project/`（项目脚手架）、`skills/teach-mode/`（教学模式辅助）、`skills/offline-ollama/`（内网离线）
- 界面入口：`/skill` 列出、`/skill activate <名称>` 激活

**验证**：8 个单测（解析/激活/停用/触发/容错）

---

### ✅ 6. Slash Command 命令框架

**要求**：内置 + 用户自定义的斜杠命令，常用操作一键触发。

**实现**（`extensions/slash_commands.py` + `builtin_commands.py`）：
- 框架：SlashCommandRegistry — 注册/分发/列表，斜杠输入优先于 LLM 对话（本地操作零 token）
- 15 个内置命令：/help /clear /status /model /compact /memory /session /tools /skill /trace /explain /audit /spawn /team /exit
- 自定义：`registry.register(SlashCommand(name=..., handler=...))` 一行注册
- 体验：输入 `/` 弹出下拉补全菜单（透明背景、实时过滤、上下键选择）

**验证**：7 个单测 + E2E 装配测试验证命令齐全

---

### ✅ 7. Hook 生命周期钩子

**要求**：危险命令会问你，敏感目录会拦截，Agent 有能力但不会失控。

**实现**（`tools/hooks.py` + `security/`）：
- Hook 框架：7 个生命周期阶段（PRE_TOOL/POST_TOOL/PRE_LLM/POST_LLM/SESSION_START/END/USER_INPUT）× 4 种裁决（CONTINUE/BLOCK/MODIFY/CONFIRM），优先级链 + 否决短路
- 危险命令确认：13 条正则（rm -rf/sudo/force push/curl|sh/format 等）命中即弹窗，y/a/n 三选（允许一次/本会话总是/拒绝）
- 敏感目录拦截：~/.ssh、~/.aws、~/.gnupg 硬拒绝；.env/密钥/证书文件即使在项目内也拦截
- 三级路径策略：项目内自动放行 / 敏感硬拒绝 / 项目外询问
- fail-safe：无 UI 时默认拒绝
- 执行管道：每次工具调用走 PermissionCheck → PRE_TOOL Hook → execute → POST_TOOL Hook
- 已激活的生命周期 Hook：PRE_LLM（LLM 调用前，含 BLOCK 能力 + 自动记忆注入）、SESSION_END（退出时自动提取偏好）、PRE_TOOL/POST_TOOL（工具执行前后）

**验证**：35 个安全测试（含危险命令三态、敏感文件拦截、Hook 阻止与观察）

---

### ✅ 8. 上下文压缩 + Token 管理

**要求**：对话变长后自动压缩历史，省 token 又不丢关键信息。

**实现**（`memory/context.py` + `compressor.py` + `llm/token_counter.py`）：
- Token 管理：tiktoken 精确计数（可选依赖，缺失时 CJK 感知估算——CJK 1 token/字 + 其余 chars/4，P43）+ API usage 锚点（对话总量直接用 API 返回的权威计数，只对新消息估算，误差不累积，P43）+ LRU 缓存 + 每轮界面显示用量（`tokens: xxx this turn / xxx total`）
- 自动压缩：ContextManager 每轮 OBSERVE 后检查，达到窗口 75% 触发；ensure_fits 溢出兜底使用 API 探测的真实窗口值（P42）
- 三级压缩级联（保留关键信息的关键设计）：
  1. DropToolResults — 先压最冗余的工具输出（保留调用结构）
  2. SummarizeOldest — 摘要旧消息，最近 6 条不动（当前工作上下文完整保留）
  3. SlidingWindow — 滑动窗口兜底
- 手动入口：`/compact` 命令

**验证**：12 个单测；实测 30 条消息 250% 超载压缩到 <50%

---

### ✅ 9. 跨会话记忆系统

**要求**：项目级 + 用户级记忆，多次会话之间持续积累理解。

**实现**（`memory/persistent.py` + `extraction.py` + `session_store.py`）：
- 双层存储：项目级 `.mini-agent/memory.json`（项目约定）+ 用户级 `~/.mini-agent/memory/`（跨项目偏好）
- 自动提取：MemoryExtractor 从对话中提取 "always/prefer/don't" 类偏好，自动去重入库
- 手动管理：`/memory add <内容>` 添加、`/memory` 查看
- 会话持久化：`/session save/list/load/delete` — 完整对话（含工具调用）JSON 序列化，重启后恢复继续

**验证**：15 个单测（CRUD/搜索/提取/去重/序列化往返）

---

### ✅ 10. SubAgent 子任务分发

**要求**：把任务委派给独立的子 Agent 并行执行，复杂任务速度拉满。

**实现**（`core/subagent.py`）：
- SubAgent：复用 AgentLoop，每个子 Agent 拥有独立对话上下文 + 克隆的工具注册表（可白名单限制）+ 独立工作目录
- SubAgentManager：spawn（asyncio.create_task 后台启动）/ spawn_parallel（批量并发）/ wait_all（gather 收集）/ cancel / timeout 超时取消
- 失败即数据：子 Agent 异常转 SubAgentResult(success=False)，不炸编排

**验证**：8 个单测含并行计时断言（3 个 0.1s Agent 并行 <0.35s）；真实 API E2E：2 个 Agent 并行读不同文件 2.3 秒各自正确报告

---

### ✅ 11. Git Worktree 并行隔离

**要求**：多个 Agent 同时改代码自动放进不同 Git 工作树，互相不打架。

**实现**（`security/worktree.py`）：
- WorktreeManager：create（新分支+工作树到 `.mini-agent/worktrees/`）/ remove（脏树保护，未提交变更拒绝删除）/ list / status / merge_back（--no-ff 合并 + 冲突检测 + 自动 abort 保持仓库干净）
- 自动接入：`SubAgentManager.spawn(isolation="worktree")` 自动创建工作树并把子 Agent 的 working_dir 切进去——多个 Agent 的文件修改天然隔离
- TeamConfig.isolation="worktree" 让整个团队每个成员各占一棵工作树

**验证**：6 个真实 git 仓库集成测试（创建/脏树保护/合并/冲突）

---

### ✅ 12. Agent Teams 多 Agent 团队

**要求**：组建长期协作的 Agent 团队，处理跨多个领域的大型项目。

**实现**（`core/team.py` + `core/planner.py`）：
- TeamMember：名称 + 角色（backend/frontend/tester...）+ 工具白名单
- Planner：LLM 结构化任务分解（JSON 输出，三级解析容错）
- AgentTeam 编排（Orchestrator 策略）：分解大任务 → 按角色匹配成员 → 并行 spawn（可 worktree 隔离）→ wait_all 收集 → TeamRunReport 汇总（每步状态+输出摘要）；`--coordinator` 模式 Planner 纯调度（prompt 强化 + max_steps 放宽 + 扫描加深，P45）

**验证**：5+6 个单测；真实 API E2E：Planner 分解调研任务 → 2 角色成员并行执行 → 汇总 success=True

---

## 第二部分：6 大技术层面

### ✅ 层面 1：基础对话能力

| 要求点 | 实现 |
|---|---|
| System Prompt 工程 | `app.py` SYSTEM_PROMPT — 动态注入工作目录/平台/shell/当前模型名，平台感知命令指引，工具使用准则 |
| LLM API | httpx 直连（不依赖厂商 SDK），OpenAI 兼容 + Anthropic 双 Provider，注册表工厂模式，`/model` 多模型热切换，上下文窗口 API 自动探测（P42：GET /models/{model} 递归提取，失败回退内置表） |
| 流式响应 | SSE 逐行解析 → StreamChunk 统一抽象 → Rich Live 实时渲染；截断恢复——finish_reason="length" 自动翻倍 max_tokens 重试最多 3 次（P44） |
| 多轮对话 | Conversation 全量重放，工具调用配对协议（tool_calls ↔ tool_call_id） |
| 对话管理器 | Conversation 类：append / to_api_messages / slice_window / token 累计 |

### ✅ 层面 2：Agent 核心机制

| 要求点 | 实现 |
|---|---|
| Function Calling | OpenAI tool_calls 格式（碎片化 delta 增量组装）+ Anthropic tool_use 格式（双向转换） |
| Tools 工具系统 | Tool ABC（schema + execute 双成员）+ ToolRegistry（注册/克隆/过滤）+ 参数校验 |
| ReAct 范式 | think → act → observe 循环，失败即数据（错误回传 LLM 自纠错） |
| Agent Loop 主循环 | `core/agent_loop.py` 状态机（8 个 AgentPhase），三重熔断护栏 |
| 事件流 | `events/bus.py` 异步发布订阅 EventBus，14 种类型化事件贯穿全部组件 |

### ✅ 层面 3：能力拓展协议

| 要求点 | 实现 |
|---|---|
| MCP 协议 | JSON-RPC 握手 + 工具发现 + Adapter 透明挂载（见核心功能 4） |
| Skill 技能包 | SKILL.md 装载/激活/触发（见核心功能 5） |
| Slash Command | 11 内置 + 自定义注册 + 下拉补全（见核心功能 6） |
| Hook 生命周期钩子 | 7 阶段 × 4 裁决 + 优先级链 + 短路（见核心功能 7） |

### ✅ 层面 4：工程化功能

| 要求点 | 实现 |
|---|---|
| 权限防御 | 评估顺序 DENY→ALLOW→Session→Default；13 条危险命令正则；三级路径策略；fail-safe 默认拒绝 |
| 上下文压缩 | 三级级联（75% 阈值自动 + /compact 手动） |
| token 管理 | tiktoken/CJK 感知估算双路径 + API usage 锚点（P43）+ LRU 缓存 + 每轮界面显示 |
| 上下文溢写 | 压缩不达标时 SlidingWindow 强制截断兜底 |
| 跨会话记忆 | 项目级 + 用户级双层 JSON 存储 + 关键词/标签搜索 |
| 会话持久化 | SessionStore 完整序列化（含 ToolCall/ToolResult），/session 全套命令 |
| 记忆提取 | MemoryExtractor 从对话自动提取偏好/约定/约束，去重入库 |

### ✅ 层面 5：多 Agent 协作

| 要求点 | 实现 |
|---|---|
| SubAgent 子任务分发 | asyncio 真并行（E2E 计时验证），独立上下文/工具表/工作目录 |
| Git Worktree 并行隔离 | spawn(isolation="worktree") 自动建树，脏树保护，合并回主分支 |
| Agent Teams 团队协作 | Planner 分解 + 角色匹配 + 并行编排 + 报告汇总 |

### ✅ 层面 6：Spec 开发模式 + CLAUDE 项目指令

| 要求点 | 实现 |
|---|---|
| spec.md | `docs/spec.md` — 15 章完整架构规格（目录结构/分层架构/数据模型/模块接口/数据流/状态机/安全模型/开发阶段） |
| tasks.md | `docs/tasks.md` — P1-P7 全部任务清单，逐项打勾并附验证依据 |
| checklist.md | `docs/checklist.md` — 每阶段验收检查清单，全部核查通过 |
| CLAUDE.md | 项目根目录 — 常用命令/架构要点/代码规范的项目指令 |
| 附加文档 | `docs/tech-notes.md`（技术原理与选型）、`docs/roadmap.md`（演进路线）、本文档（能力对照） |

---

## 第三部分：总体质量证据

| 维度 | 数据 |
|---|---|
| 源文件 | 77 个 Python 文件，五层架构（交互/引擎/工具/记忆/安全）+ EventBus 解耦 |
| 测试 | 544 个测试全部通过（约 56 秒，零网络依赖），单元 25 文件 + 集成 2 文件 |
| 工具 | 8 个内置工具（read_file / write_file / edit_file / delete_file / bash / glob / grep / spawn_agents），LLM 自主决定使用 |
| CI | GitHub Actions 三个 Job（Lint / Test 双 Python 版本 / Build）全绿 |
| E2E | 真实 LLM API 验证：自主工具调用、并行 SubAgent、Team 编排、流式渲染、/trace 全链路 |
| 评测 | 10 个标准编程任务 **10/10 通过**，总成本 $0.0015，详见 `benchmarks/README.md` |
| 机制透明 | `/trace` 命令实时展示 ReAct 内部状态（阶段/权限判定+依据/工具耗时/LLM 元信息）——商用 Agent 给不了的白盒能力 |
| 垂直场景 | `/explain` 教学模式（TeachRenderer 确定性面板 + Skill 辅助）+ `/audit` 合规审计（哈希链防篡改 JSONL + `/audit verify` 完整性校验）+ offline-ollama 内网离线 Skill——"因为拥有源码所以能做"的三个活证据 |
| 机制实验 | `experiments/` 三项：① 压缩策略 A/B（发现：压缩的隐性代价是重复劳动，工具调用翻 2-5 倍）；② 强弱模型混编（发现：strong-weak 帕累托最优）；③ 死循环诱导（发现：迭代上限是唯一可靠硬熔断，same-tool-6x 在真实 LLM 下从未触发→已升级 v2 按轮检测并实战修正误杀）——从"做了个项目"到"做了研究" |
| 流式中断 | 双 Esc 优雅中断流式输出（守护线程 + cancelled 标志），不用 Ctrl+C 冒险杀进程 |
| 长记忆自动化 | PRE_LLM hook 自动注入记忆 + SESSION_END hook 自动提取偏好——用户无感知的跨会话记忆 |
| 溢出兜底 | 发送前 token 预检（P20）+ 超限强制 SlidingWindow 截断——三级压缩走完仍超窗时的最终防线，杜绝 API 400 |
| TOML 配置 | 用户级 + 项目级 `config.toml`（P21），Python 3.11 tomllib 零依赖，七层优先级栈（spec.md 13.3 设计的完整落地） |
| Diff 预览 | edit_file 成功后整行背景色彩色 diff（P23）——删除行深红底、新增行深绿底，一眼看出改了什么 |
| Streaming 中间态 | LLM 生成工具调用参数时立即显示工具名（P23）——不再等 JSON 组装完才冒出工具行 |
| 文件变更汇总 | 轮次结束显示本轮新建（+绿）/修改（~黄）/删除（-红）的文件清单（P24）——多文件操作一目了然 |
| 上下文感知 | 启动自动注入 AGENT.md/CLAUDE.md/instructions.md 项目指令 + 用户级全局指令（P25）——LLM 无需读文件即知项目约定 |
| 对话分叉/回滚 | `/undo` 回滚 N 轮 + `/fork` 分叉新会话原线保留（P26）——CC 无此能力（服务端历史不可操作），本地自持有 Conversation 的差异化优势；P27 进一步支持操作级撤销（undo 连文件一起恢复） |
| 工具链录制/回放 | `/record` 录制工具调用序列 + `/replay` 零 LLM 确定性重放（P28）——例行操作录一次永久复用，CC 无此能力 |
| 成本仪表盘 | `/cost` 按模型分账 input/output 计价 + 会话预算警告（P29）——按量付费用户的刚需，CC 订阅制无此功能 |
| LLM 记忆提取 | MemoryExtractor 从 regex 升级为 LLM 结构化提取（P30）——理解语义不依赖关键词，覆盖率质变 |
| MCP HTTP Transport | HTTPTransport 远程 MCP 服务器连接 + app 启动自动发现（P31）——P5 预留的 MCP 架构终于接通，支持 headers 认证 |
| 持久化任务系统 | `/todo` 命令 + TaskStore 磁盘持久 + blockedBy 依赖追踪（P32）——S12 补全，S01-S20 覆盖 19/20 |
| PyPI 发布 | `pip install mini-code-agent` 一行安装（P33）——元数据补全 + MIT LICENSE + tag 触发自动发布 workflow |
| Windows 终端适配 | UTF-8 加固/流式防重影/按键防吞/无控制台兜底/emoji 降级（P34）——CMD/PowerShell/Windows Terminal 全兼容；P34.3 补修 bash GBK 解码、git 命令确认闸门、Git Bash（mintty）降级运行与代理字符清洗，各终端指南见 terminal-guide.md |
| 注释 | 全部英文注释附中文翻译（约 336 条） |

## 如实说明：有意简化（历史记录，多数已升级）

以下为 mini 早期实现的合理取舍，**不影响需求达成**。带 ✅ 的已在后续阶段升级：

1. 默认压缩链 Stage 2 用提取式摘要（LLM 摘要 `LLMSummarizeOldest` 已实现但需显式配置——压缩本身耗 token，默认不开启）
2. ✅ 记忆提取已从正则升级为 LLM 结构化提取（P30）
3. ✅ MCP HTTP transport 已实现（P31，含 headers 认证）
4. ✅ 多个 tool_calls 已改为权限预检串行 + 执行并行（P17，asyncio.gather + 审计锁）；P38 进一步升级为流式执行（组装完成即跑，不等流结束）

---

**结论：18 项需求（12 项核心功能 + 6 大技术层面）全部正确实现，每项均有代码位置、实现方式与测试证据支撑。**