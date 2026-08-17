# Mini-Code-Agent 开发任务清单

## Phase 1: 基础对话 (P1)

### P1.1 项目初始化
- [x] 创建 `pyproject.toml`（uv, 入口 mini-agent, 依赖 rich/prompt_toolkit/httpx）
- [x] 创建 `.python-version` (3.11)
- [x] 创建 `src/mini_agent/__init__.py` + `__main__.py`
- [x] 创建 `CLAUDE.md` 项目指令
- [x] `uv sync` 验证依赖安装

### P1.2 核心数据模型
- [x] `models/message.py` — Role, ToolCall, ToolResult, Message, Conversation
- [x] `models/events.py` — Event 基类 + UserMessageEvent, LLMStreamChunkEvent, LLMResponseEvent
- [x] `models/config.py` — LLMConfig, ToolConfig, MCPConfig, MemoryConfig, SecurityConfig, AgentConfig
- [x] `models/session.py` — Session, SessionMetadata

### P1.3 事件系统
- [x] `events/bus.py` — EventBus (async pub/sub, on/off/emit/on_any)
- [x] `events/types.py` — 辅助导出

### P1.4 配置系统
- [x] `config/defaults.py` — 内置默认配置值
- [x] `config/loader.py` — 分层配置加载 (defaults → .env → env → CLI)

### P1.5 LLM Provider
- [x] `llm/base.py` — LLMProvider ABC, StreamChunk, ToolCallDelta, TokenUsage, LLMResponse
- [x] `llm/openai_provider.py` — OpenAI 兼容 Provider (httpx, 流式, tool_calls 解析)
- [x] `llm/registry.py` — ProviderRegistry (register/create)
- [x] `llm/token_counter.py` — 基础 token 计数 (tiktoken 可选, 无则 chars/4 估算)

### P1.6 TUI 基础
- [x] `ui/terminal.py` — Terminal 类 (Rich Console + Prompt Toolkit input)
- [x] `ui/renderer.py` — 流式文本渲染 (Markdown 渲染)
- [x] `ui/input_handler.py` — 基础输入处理 (多行, 历史)

### P1.7 应用编排
- [x] `cli.py` — CLI 入口 (argparse: --model, --provider, --api-key, --base-url)
- [x] `app.py` — Application 编排器 (装配 EventBus + LLM + Terminal + AgentLoop)

### P1.8 验证
- [x] `uv run mini-agent` 可启动终端 (--version 验证通过)
- [x] 输入消息后 LLM 流式响应 (真实 API 流式验证通过)
- [x] 多轮对话上下文保持 (Conversation.to_api_messages 携带全部历史)

---

## Phase 2: 工具系统 + Agent Loop (P2)

### P2.1 工具基础设施
- [x] `tools/base.py` — Tool ABC, ToolParameter, ToolSchema, ToolContext, ToolRegistry

### P2.2 六个核心工具
- [x] `tools/builtin/read_file.py` — ReadFileTool (路径, offset, limit, 行号输出)
- [x] `tools/builtin/write_file.py` — WriteFileTool (路径, 内容, 自动建父目录)
- [x] `tools/builtin/edit_file.py` — EditFileTool (路径, old_text, new_text, replace_all)
- [x] `tools/builtin/bash.py` — BashTool (命令, timeout, working_dir, Win/Unix 兼容)
- [x] `tools/builtin/glob_tool.py` — GlobTool (pattern, path, 按修改时间排序)
- [x] `tools/builtin/grep.py` — GrepTool (pattern, path, include 过滤)

### P2.3 Agent 核心
- [x] `core/agent_state.py` — AgentPhase, AgentState (PlanStep 推迟到 P6 Plan 模式)
- [x] `core/errors.py` — 异常体系 (AgentError, ToolError, LLMError, MaxIterations, UserCancelled)
- [x] `core/agent_loop.py` — ReAct AgentLoop (_think, _act, _should_continue, cancel, 死循环检测)

### P2.4 TUI 扩展
- [x] `ui/terminal.py` 扩展 — 工具调用渲染 (名称+参数), 结果展示
- [x] `ui/components.py` — Spinner, Status, ToolCallPanel (PermissionPrompt 属 P3)

### P2.5 验证
- [x] "读取 README 并总结" → 自主调用 ReadFile → 处理 → 回答 (真实 API E2E 验证通过)
- [x] "查找包含 TODO 的文件" → Grep 工具 → 列出结果 (真实 API E2E 验证通过)
- [x] 多步工具链正常执行 (think → tool → observe → think → answer, MockLLM 单测覆盖)

---

## Phase 3: 安全 + Hook (P3)

### P3.1 权限系统
- [x] `models/permissions.py` — PermissionLevel, PermissionScope, PermissionRule, PermissionRequest, PermissionDecision
- [x] `security/permission.py` — PermissionManager (check, check_path, check_command, grant_session, 危险命令正则检测)
- [x] `security/path_guard.py` — PathGuard (敏感目录拒绝, 项目目录允许, 其余 ask, 敏感文件模式含 .env/密钥)
- [x] `security/tool_filter.py` — ToolFilter (上下文过滤)

### P3.2 Hook 系统
- [x] `tools/hooks.py` — HookStage, HookContext, HookAction, HookResult, HookFn, HookManager (优先级+短路)
- [x] 内置防护: 危险命令确认 (PermissionManager 正则), 敏感文件保护 (PathGuard 模式)
- [x] Agent Loop 集成安全管道 (PermissionCheck → PRE_TOOL → execute → POST_TOOL)

### P3.3 TUI 权限交互
- [x] `ui/terminal.py` 扩展 — confirm() 确认弹窗 (y/n 交互)

### P3.4 验证
- [x] bash 执行危险命令 → 触发确认 (rm -rf 单测: 无UI拒绝/用户批准执行/用户拒绝阻止)
- [x] 尝试读取 `~/.ssh/id_rsa` → 拒绝 (PathGuard 单测)
- [x] 正常读写项目内文件 → 自动允许 (AgentLoop 集成测试)
- [x] 附加: .env 敏感文件拦截, PRE_TOOL Hook 阻止, POST_TOOL Hook 观察 (集成测试覆盖)

---

## Phase 4: 记忆 + 上下文管理 (P4)

### P4.1 Token 管理
- [x] `llm/token_counter.py` 完善 — per-message 计数 + 工具调用开销估算（tiktoken 可选）

### P4.2 上下文管理
- [x] `memory/context.py` — ContextManager (count_message, update_total, check_and_compress, usage_ratio, tokens_remaining, needs_compression)
- [x] `memory/compressor.py` — CompressionStrategy ABC + 三级策略 (DropToolResults: 截断长输出, SummarizeOldest: 提取式摘要, SlidingWindow: 滑动窗口兜底) + Compressor 级联

### P4.3 会话持久化
- [x] `memory/session_store.py` — SessionStore (save, load, list_sessions, delete — JSON 序列化/反序列化含 ToolCall/ToolResult)

### P4.4 跨会话记忆
- [x] `memory/persistent.py` — PersistentMemory (项目级 `.mini-agent/memory.json` + 用户级 `~/.mini-agent/memory/`, CRUD, 关键词+标签搜索)
- [x] `memory/extraction.py` — MemoryExtractor (正则模式提取偏好/约束/惯例, 去重, 自动存储到对应层级)

### P4.5 验证
- [x] 上下文压缩: 阈值触发 → 三级级联压缩 → 消息数减少 (单测 test_context.py 12 个)
- [x] 会话持久化: save/load 完整往返含 tool_calls + tool_results (单测 test_session_store.py 6 个)
- [x] 跨会话记忆: 项目+用户 CRUD, 搜索, 提取, 去重 (单测 test_persistent_memory.py 9 个)
- [x] AgentLoop 集成: 每轮 OBSERVE 阶段自动 check_and_compress
- [x] 110 个测试全过, lint/format/build CI 通过

---

## Phase 5: 扩展协议 (P5)

### P5.1 Slash Commands
- [x] `extensions/slash_commands.py` — SlashCommand, SlashCommandRegistry (解析/分发/列表)
- [x] `extensions/builtin_commands.py` — 内置命令: /help /clear /status /model /compact /memory /session /tools /skill /quit /exit
- [x] App 集成: 斜杠命令优先于 Agent 对话分发

### P5.2 Skill 系统
- [x] `extensions/skills.py` — Skill, SkillRegistry (SKILL.md 解析, 激活/停用, trigger 匹配)
- [x] 内置技能包: `skills/code_review/SKILL.md`, `skills/init_project/SKILL.md`
- [x] `/skill` 命令: list / activate / deactivate

### P5.3 MCP 协议
- [x] `tools/mcp/transport.py` — StdioTransport (stdio JSON-RPC 通信)
- [x] `tools/mcp/client.py` — MCPManager (connect, disconnect, call_tool, discover, 多服务器管理)
- [x] `tools/mcp/adapter.py` — MCPToolAdapter (MCP 工具 → 内部 Tool 接口, 自动 schema 转换)

### P5.4 第二个 LLM Provider
- [x] `llm/anthropic_provider.py` — Claude Messages API (SSE 流式, tool_use 格式, system 分离, 工具格式转换)
- [x] 注册到 ProviderRegistry, `--provider anthropic` 即可切换

### P5.5 验证
- [x] `/help` 列出所有可用命令 (7 个单测覆盖框架)
- [x] `/skill` 列出/激活/停用技能 (8 个单测覆盖解析/触发/激活/停用)
- [x] MCP 适配器 schema 转换 + 执行 + 注册 (7 个单测覆盖, FakeMCPManager 模拟)
- [x] 131 个测试全过, lint/format/build CI 通过

---

## Phase 6: 多 Agent (P6)

### P6.1 Worktree 隔离
- [x] `security/worktree.py` — WorktreeManager (create, remove, list, status, merge_back, 未提交变更保护, 冲突检测+abort)

### P6.2 SubAgent
- [x] `core/subagent.py` — SubAgent (独立 AgentLoop + 克隆 ToolRegistry + 可选 worktree + 工具白名单), SubAgentResult, SubAgentManager (spawn, spawn_parallel, wait, wait_all, cancel, timeout)

### P6.3 Plan 模式
- [x] `core/planner.py` — Planner.decompose (LLM 结构化分解, JSON 解析容错: markdown 围栏/字符串数组/无效 JSON 兜底, max_steps 限制)

### P6.4 Agent Teams
- [x] `core/team.py` — TeamMember, TeamConfig, AgentTeam (start: 分解→角色匹配→并行 spawn→收集, stop), TeamRunReport (summary)

### P6.5 TUI 多 Agent 监控
- [x] SubAgentManager.list_active / get_status 提供状态查询接口 (完整状态面板推迟到 P7 UI 打磨)

### P6.6 验证
- [x] 并行 SubAgent: 2 个真实 API Agent 并行读不同文件, 2.3s 完成 (E2E 验证)
- [x] Agent Team 协调: Planner 真实分解任务 → 2 角色成员并行执行 → 报告汇总 success=True (E2E 验证)
- [x] Worktree: create/list/status/remove/merge_back 集成测试 (真实 git 仓库, 6 个测试)
- [x] 156 个测试全过, lint/format/build CI 通过

---

## Phase 7: 打磨 (P7)

### P7.1 测试
- [x] 单元测试: agent_loop, tools, llm_providers(新增23个: 双Provider解析层/碎片组装/格式转换), memory, permissions, events, config, models — 17 个单测文件
- [x] 集成测试: agent_e2e(新增: 完整App装配冒烟), worktree(真实git仓库), mcp(FakeManager), session_persistence(单测覆盖)

### P7.2 错误处理
- [x] LLM API 错误友好提示 (_friendly_error: 401/402/429/5xx/连接失败/超时 → 中文可操作提示)
- [x] 启动时缺 API key 检查 (cli.py 给出三种配置方式指引后退出)
- [x] 既有兜底: 工具异常→ToolResult, 流JSON解析失败→空字典, session文件损坏→None

### P7.3 性能优化
- [x] token 计数 LRU 缓存 (maxsize=4096, >50K 字符跳过缓存防内存膨胀; 压缩检查反复重算 system prompt 的场景收益最大)
- [x] 流式渲染已是增量模式 (Rich Live 15fps, P1 已优化)

### P7.4 UI 打磨
- [x] `ui/themes.py` — 主题系统 (default/dark/light 三套配色, Theme dataclass)
- [x] `ui/components.py` — Spinner/Status/ToolCallPanel (P2 已建)
- [x] `ui/input_handler.py` 完善 — 输入历史持久化到 ~/.mini-agent/input_history (跨会话上下键), 斜杠命令自动补全 (P5 已建)
- [x] 183 个测试全过, lint/format/build CI 通过

---

## Phase 8: 评测框架 (P8)

### P8.1 评测基础设施
- [x] `benchmarks/runner.py` — headless 执行器（程序化调 AgentLoop，采集 token/cost/tools/time）
- [x] `benchmarks/report.py` — 结果汇总生成器（JSON + YAML → Markdown 对比表格）
- [x] `benchmarks/tasks/*.yaml` × 10 — 任务定义（bugfix 2 / feature 3 / test 1 / refactor 1 / search 2 / 跨文件 1）
- [x] `benchmarks/workspaces/*/` — 每个任务的 fixture 文件（含 bug 代码、待通过测试等）
- [x] `benchmarks/cc_results/_template.yaml` — CC 手动结果模板

### P8.2 评测结果
- [x] 10/10 全部通过（100% 完成率）
- [x] 总 token: 62,040 / 总成本: $0.0015 / 平均 6,204 token 每任务
- [x] 平均 4 次工具调用 / 6.2 秒每任务
- [x] 结果写入 benchmarks/README.md + 项目 README.md

---

## Phase 9: 机制透明度 /trace (P9)

### P9.1 事件补齐
- [x] PermissionCheckEvent 新增（tool_name/scope/resource/decision/reason）
- [x] PermissionManager.last_decision_reason 判定溯源（rule/session_grant/mode/user_confirm/dangerous/path_guard 全路径）
- [x] AgentLoop 补发 LLMRequestEvent/LLMResponseEvent（激活既有"死"事件）+ PermissionCheckEvent

### P9.2 TraceRenderer + 命令
- [x] `ui/trace.py` — 纯 EventBus 订阅者，订阅 7 种事件，enabled 开关，暗色 trace 行渲染
- [x] `/trace [on|off]` 命令注册 + app.py 装配

### P9.3 验证
- [x] 10 个新测试（trace 渲染 9 + 权限事件 1），193 个测试全过
- [x] 真实 API E2E：trace 完整展示 ReAct 循环（阶段切换→llm 请求/响应→权限判定→工具耗时→轮次汇总）

---

## Phase 10: 垂直场景定制 (P10)

### P10.1 教学模式
- [x] `ui/teach.py` — TeachRenderer 类，EventBus 订阅者，工具调用前确定性打印教学面板（6 个工具专属文案 + 默认兜底）
- [x] `skills/teach-mode/SKILL.md` — 辅助 Skill，注入教学指令让 LLM 输出推理解释（与 TeachRenderer 互补）
- [x] `/explain [on|off]` 命令 — 开关 TeachRenderer.enabled
- [x] `app.py` 装配 TeachRenderer

### P10.2 合规审计模式
- [x] `security/audit.py` — AuditLogger 类，EventBus 订阅者，写 JSONL 审计日志
- [x] `/audit [on|off]` 命令 — 开关 + 显示日志路径和条目数
- [x] `app.py` 装配 AuditLogger
- [x] 哈希链防篡改 — 每条记录 `hash = sha256(prev_hash + 内容)`，改/删任何一行链即断裂
- [x] `/audit verify` — 重放校验整条链，跨进程重启链自动续接

### P10.3 内网离线环境
- [x] `skills/offline-ollama/SKILL.md` — Ollama 配置指引 Skill（零新代码，复用 OpenAI 兼容 API）

### P10.4 验证
- [x] 12 个新测试（audit 7 + teach 5），217 个测试全过
- [x] `/skill list` 显示 teach-mode 和 offline-ollama 两个新 Skill
- [x] 真实 API E2E：`/explain on` 后每次工具调用前 100% 出现 Teach 面板

---

## Phase 11: 机制实验 (P11)

### P11.1 LLM 摘要压缩策略（roadmap 1.1 兑现）
- [x] `memory/compressor.py` — LLMSummarizeOldest 策略（LLM 语义摘要 + 失败回退提取式 + 防递归直连调用）
- [x] 提取公共函数 `_extractive_digest` / `_make_summary_message`（SummarizeOldest 复用）
- [x] 4 个 MockLLM 单测（摘要成功/网络失败回退/空响应回退/消息过少跳过）

### P11.2 压缩策略 A/B 实验
- [x] `experiments/compression_ab.py` — 三臂（none/extractive/llm）× 5 个工具密集任务
- [x] 6000 token 小窗口 + 0.6 阈值迫使短任务触发压缩
- [x] 指标：success/tokens/cost/tool_calls/compressed_messages

### P11.3 强弱模型混合编排实验
- [x] `experiments/model_mix.py` — 三臂（strong-strong/strong-weak/weak-weak）× 2 复合任务
- [x] AgentTeam 装配：Planner(强) + SubAgentManager(弱)，llm_profiles 注入
- [x] 文件存在性验证 + 强弱分开计费

### P11.4 验证
- [x] 真实 API 跑实验收集数据，结果表格见 experiments/README.md
- [x] 发现 1：小窗口强制压缩下压缩不省 token 反而更贵（工具调用翻 2-5 倍的重复劳动）
- [x] 发现 2：strong-weak 混编帕累托最优（全通过 + 成本最低）

### P11.5 实验结论产品化（roadmap 2.5 配置层）
- [x] `AgentConfig.planner_profile / worker_profile` 字段 + 环境变量加载
- [x] `ProviderRegistry.create_for_role(config, role)` 工厂（未配置/未知 profile 回退主模型）
- [x] `.env.example` 混编配置示例
- [x] 5 个新测试（配置加载/角色工厂/回退），226 个测试全过

---

## Phase 12: 多 Agent 命令入口 (P12)

### P12.1 SubAgent 事件
- [x] `models/events.py` — SubAgentSpawnEvent + SubAgentCompleteEvent
- [x] `core/subagent.py` — spawn() emit SpawnEvent, wait() emit CompleteEvent

### P12.2 Application 装配
- [x] `app.py` — 新增 WorktreeManager + SubAgentManager 实例化
- [x] Worker LLM 使用 `ProviderRegistry.create_for_role(config, "worker")`（roadmap 2.5 接线）

### P12.3 /spawn 命令
- [x] 单任务派生：`/spawn <任务>` → 返回 agent_id
- [x] 并行派生：`/spawn -p <任务1> | <任务2>`
- [x] worktree 隔离：`/spawn --isolated <任务>`
- [x] 子命令：`/spawn list` / `/spawn wait [id]` / `/spawn cancel [id]`

### P12.4 /team 命令
- [x] 团队编排：`/team <大任务>` → Planner 分解 + SubAgent 并行执行 + 汇总报告
- [x] worktree 隔离：`/team --isolated <任务>`
- [x] Planner LLM 使用 `create_for_role(config, "planner")`（强弱混编完整接线）

### P12.5 验证
- [x] 8 个新测试（spawn 基础 3 + 事件 2 + 命令 handler 3），243 个测试全过

---

## Phase 13: SubAgent 进度面板 (P13)

### P13.1 快照接口
- [x] `core/subagent.py` — AgentSnapshot dataclass（agent_id/task/phase/tool_calls/elapsed_seconds）
- [x] `_ActiveAgent.started_at` 记录启动时间（time.monotonic）
- [x] `SubAgentManager.active_snapshots()` 公开访问器（面板不触碰私有成员）

### P13.2 进度面板
- [x] `ui/board.py` — SubAgentBoard 类，Rich Live + Table，4fps 刷新
- [x] `run_while(awaitable)` 包裹模式：面板伴随等待运行，结束自动收起（transient），结果/异常透传
- [x] 阶段上色（thinking 紫/tool_calling 蓝/terminated 绿/error 红），任务摘要截断，耗时实时跳动

### P13.3 命令接线
- [x] `/spawn wait [id]` 阻塞期间显示面板
- [x] `/team` 执行期间显示面板（Planner 分解后各 worker 进度可见）

### P13.4 验证
- [x] 7 个新测试（快照 2 + run_while 3 + 渲染 2），250 个测试全过

### P13.5 /team 真实运行暴露的三个缺陷修复
- [x] SubAgent system prompt 补平台/shell 信息 + 路径约束（修 LLM 写 /tmp 的 Unix 习惯）+ "文件不存在就报告勿重试"
- [x] 熔断即失败：AgentLoop.stopped_early 标志，SubAgent 熔断终止返回 success=False（此前熔断空转也算 [OK]，SUCCESS 误报）
- [x] 依赖感知分批执行：PlanStep.depends_on 字段 + Planner prompt 声明依赖 + AgentTeam 分批调度（无依赖并行/有依赖等前置批完成/依赖失败则跳过）+ 依赖产出注入后续步骤 prompt
- [x] 4 个新测试（依赖分批/依赖上下文传递/失败跳过/熔断失败），254 个测试全过

### P13.6 二轮 E2E 修复：子任务粒度与预算感知
- [x] Planner prompt 加 SIZE LIMIT：子任务须 ~15 次工具调用内可完成，禁止"读所有源码"式任务，要求限定文件/目录范围、允许抽样
- [x] SubAgent prompt 加 BUDGET 段：告知轮次预算（max_agent_iterations），要求预算将尽时立即写出已有发现——部分产出优于空手熔断

### P13.7 三轮 E2E 修复：消除中间文件污染
- [x] Planner prompt 加 NO INTERMEDIATE FILES：分析类子任务只在报告文本输出发现（报告自动传给依赖步骤），仅用户明确要求的文件由最终步骤写出——不再产生 project_overview.md 等垃圾中间文件
- [x] 依赖报告注入上限 1500 → 4000 字符（报告成为唯一信息通道后不能截太狠）
- [x] SIZE LIMIT 再收紧：单个子任务最多读 5 个文件

### P13.8 四轮 E2E 修复：从 prompt 说服到代码强制
- [x] `PlanStep.writes_files` 字段（Planner 输出解析 + 无标记时最后一步兜底）
- [x] AgentTeam 工具白名单强制：writes_files=false 的步骤剥夺 write_file/edit_file——物理只读，prompt 无法违规（P3 教训复用：能力剥夺优于黑名单说服）
- [x] Planner 喂真实项目结构：spawn 前两级目录扫描注入 context——不再套用 backend/frontend web 模板盲分解
- [x] 3 个新测试（writes_files 解析+兜底/非写步骤剥夺写工具/结构扫描），257 个测试全过

### P13.9 六轮 E2E 收官：死循环护栏误杀修复（真正的病根）
- [x] 根因定位：强模型 worker 也在"读多个文件"步骤熔断 → 排除模型纪律归因 → 死循环检测"同一工具连续 6 次"误杀正常批量读取（连续 read_file 6 个不同文件被判死循环）
- [x] 修复：死循环签名从"工具名"改为"工具名+参数 JSON"（record_tool_call 加 args_key）——只有完全相同的重复调用才熔断，批量读不同文件不再误杀
- [x] 成功验证：`/team 分析项目生成架构摘要到su.md` 四步全 [OK]，su.md 242 行真实生成，零中间文件，136K token（比首轮 426K 降 68%），进度面板真实场景亮相

---

## Phase 14: LLM 自主派生 SubAgent (P14)

### P14.1 ToolContext 扩展
- [x] `tools/base.py` — ToolContext 新增 `subagent_manager: SubAgentManager | None = None` 字段（TYPE_CHECKING 避循环导入）

### P14.2 SpawnAgentsTool 实现
- [x] `tools/builtin/spawn_agents.py` — 新工具（schema: tasks 数组 + isolated 布尔参数）
- [x] execute：调 SubAgentManager.spawn_parallel + wait_all，汇总结果为 ToolResult 回传 LLM
- [x] ctx.subagent_manager=None 时返回 error_result（天然递归防护之一）

### P14.3 注册 + 递归防护
- [x] `tools/builtin/__init__.py` — SpawnAgentsTool 加入 ALL_BUILTIN_TOOLS（7 个内置工具）
- [x] `models/config.py` — enabled_tools 默认值加 "spawn_agents"
- [x] `app.py` — SubAgentManager 创建后注入 tool_context.subagent_manager（post-hoc mutation）
- [x] `core/subagent.py` — SubAgent clone registry 后显式 `unregister("spawn_agents")`（递归防护双保险）

### P14.4 System Prompt 使用指引
- [x] `app.py` SYSTEM_PROMPT Guidelines 段追加 spawn_agents 使用说明（独立子任务并行 + 子代理不能再派生）

### P14.5 验证
- [x] 5 个新测试（基础执行/无 manager 拒绝/空任务/部分失败/SubAgent clone 不含 spawn_agents）+ 1 个 E2E 集成断言修正，262 个测试全过
- [x] 真实 API E2E：LLM 自主调用 spawn_agents 派生 3 个子代理并行（trace 可见 3 个并行 llm request），6 tools 递归防护生效
- [x] 递归验证：子代理被要求"再派生"时正确说明限制并用 read_file 直接完成任务

---

## Phase 15: 会话自动保存 (P15)

### P15.1 崩溃信号
- [x] `models/session.py` — SessionMetadata 新增 `closed_cleanly: bool = False`
- [x] `memory/session_store.py` — 序列化/反序列化/list_sessions 三处支持；旧文件无字段默认 True（不误报崩溃）

### P15.2 自动保存
- [x] `app.py` — `_autosave(force)` 方法：30s 节流、空会话跳过、OSError 静默（下轮重试）
- [x] 接线：`_handle_turn` 后 + 斜杠命令 finally 后自动保存
- [x] run() finally：`closed_cleanly = True` + force 保存——正常退出标记干净，硬杀进程跳过 finally 留下 False 即崩溃信号

### P15.3 启动恢复
- [x] `app.py` — `_maybe_restore_session()`：过滤同目录+未干净关闭+非当前会话，取最近一个提示恢复
- [x] `ui/terminal.py` — `ask_yes_no()` 朴素是/否提示（区别于权限确认红色面板）
- [x] 拒绝恢复：标记该会话已关闭，避免每次启动重复询问
- [x] 恢复成功：closed_cleanly 重新翻 False（恢复后的会话仍是进行中）

### P15.4 顺带修复：/session load 的 ToolContext 过期引用
- [x] `_adopt_session()` 统一恢复逻辑：session + tool_context.session + context_manager 三处同步更新
- [x] `/session load` 改调 `app._adopt_session(loaded)`（此前 `app.session = loaded` 后工具层仍指向旧 Session）

### P15.5 验证
- [x] 7 个新测试（closed_cleanly 往返/旧文件默认/list 含标志/节流+force/空会话跳过/OSError 静默/崩溃过滤三类），269 个测试全过

---

## Phase 16: /theme 主题切换 (P16)

### P16.1 主题系统接入
- [x] `ui/themes.py` 三套主题色差拉大（default 紫蓝 / dark 暖橙 #ff9e64 / light GitHub 蓝 #0550ae）
- [x] `ui/input_handler.py` — PROMPT_STYLE 常量改为 `create_prompt_style(theme)` 函数，补全菜单文字颜色跟随主题
- [x] `ui/terminal.py` — 构造器加 theme 参数，欢迎标题/工具行/确认面板/错误提示全部从 theme 取色
- [x] `ui/trace.py` — 构造器加 theme，阶段名/工具名/OK/FAIL 颜色跟随
- [x] `ui/teach.py` — 构造器加 theme，面板标题颜色跟随
- [x] `ui/board.py` — 构造器加 theme，_PHASE_COLORS 改为 _phase_colors(theme) 函数

### P16.2 /theme 命令 + 持久化
- [x] `/theme` 列出可用主题 + 标记当前；`/theme dark` 切换 + 即时生效 + 持久化到 `~/.mini-agent/.theme`
- [x] 运行时切换刷新：terminal.theme 赋值 + prompt_session 重建 + trace/teach 共享 theme 引用

### P16.3 验证
- [x] 7 个新测试（get_theme 默认/dark/未知回退/全主题字段/持久化往返/prompt_style/terminal 接受 theme），281 个测试全过

---

## Phase 17: 工具并行执行 (P17)

### P17.1 _act() 两阶段并行
- [x] Phase 1：串行权限预检（确认弹窗不可交错）
- [x] Phase 2：全部 GRANTED 的工具 asyncio.gather 并行执行
- [x] 单工具走快速路径不 gather（零开销）
- [x] `_run_tool_pipeline` 加 `skip_permission` 参数（Phase 2 跳过已预检的权限）

### P17.2 AuditLogger 并行安全
- [x] 三个 EventBus handler 加 `asyncio.Lock` 保护 hash chain（并行工具同时 emit 事件时 _last_hash 互斥）

### P17.3 验证
- [x] 5 个新测试（并行计时 < 0.25s / 单工具不变 / 未知工具错误 / 取消错误 / 顺序保持），281 个测试全过

---

## Phase 18: 双 Esc 中断流式输出 (P18)

### P18.1 EscWatcher 键盘监听
- [x] `ui/esc_watcher.py` — 守护线程 + 500ms 窗口双 Esc 检测
- [x] Windows msvcrt.kbhit/getch + Unix select 跨平台兼容
- [x] 无 TTY 环境静默不可用（不崩溃）

### P18.2 流式中断接线
- [x] `agent_loop.py` _think 循环每个 chunk 检查 `self._cancelled`，cancelled 时 break
- [x] `app.py` 回调接线：stream_start 启动 EscWatcher → stream_delta 检测 triggered 调 cancel() → stream_end 停止 EscWatcher

### P18.3 验证
- [x] 5 个新测试（默认未触发/手动触发/start-stop/cancel 中断 _think/中断后 conversation 保留），286 个测试全过

---

## Phase 19: PRE_LLM / SESSION_END Hook 接线 (P19)

### P19.1 Hook 接线
- [x] `agent_loop.py` _think：PRE_LLM hook 在 LLM 调用前触发（含 BLOCK 能力——阻止 LLM 调用并返回 reason）
- [x] `app.py` run() finally：SESSION_END hook 在会话结束时触发（异常安全）

### P19.2 内置 Hook
- [x] PRE_LLM 记忆注入：加载 PersistentMemory（项目级+用户级）→ 首次追加到 system prompt（标记去重）
- [x] SESSION_END 记忆提取：auto_extract=True 时调 MemoryExtractor 从对话提取偏好写入 PersistentMemory（配置首次生效）

### P19.3 验证
- [x] 4 个新测试（PRE_LLM 触发/BLOCK 阻止 LLM/SESSION_END 触发/metadata 传递），290 个测试全过

---

## Phase 20: 上下文溢写兜底 (P20)

### P20.1 ensure_fits 兜底方法
- [x] `memory/context.py` — `ContextManager.ensure_fits(conversation, max_tokens)` 最终兜底
- [x] 超窗口时强制 SlidingWindow 截断到 85% 水位（留 15% 给响应）
- [x] 返回 True 表示发生截断

### P20.2 _think 溢出预检
- [x] `agent_loop.py` _think 在 LLM 调用前调 ensure_fits，截断后重建 api_messages
- [x] 无 context_manager 时跳过（benchmark runner 等行为不变）

### P20.3 验证
- [x] 2 个新测试（未超限不截断/超限截断后 total_tokens ≤ max_tokens），292 个测试全过

---

## Phase 21: TOML 配置文件 (P21)

### P21.1 TOML 加载与合并
- [x] `config/loader.py` — `_load_toml()` 用 Python 3.11 stdlib tomllib 解析（零依赖）
- [x] `_merge()` 深度合并：顶级标量 setattr + `[section]` 子字段遍历 + `[mcp.servers.<name>]` MCPServerConfig 构造
- [x] `load()` 插入两层：user `~/.mini-agent/config.toml` → project `.mini-agent/config.toml`（在 .env 之前）
- [x] `_apply_cli()` 泛化：支持所有子配置（tools.*/memory.*/security.*/顶级标量），不限于 llm.*

### P21.2 示例与文档
- [x] `config.toml.example` 完整注释示例（[llm]/[tools]/[memory]/[security]/[mcp.servers.*]/顶级标量）

### P21.3 验证
- [x] 6 个新测试（user TOML/project 覆盖 user/env 覆盖 TOML/部分合并/MCP 服务器/顶级标量），298 个测试全过

---

## Phase 22: 接口冻结 + 覆盖率门禁 (P22)

### P22.1 接口冻结
- [x] `CHANGELOG.md` 新建——四个 ABC 的完整方法签名（Tool/LLMProvider/HookFn/CompressionStrategy）+ 支撑类型列表
- [x] 冻结承诺定义：签名不变、可加可选参数、可加新方法、破坏性变更需 2.0.0

### P22.2 覆盖率门禁
- [x] `pyproject.toml` — pytest-cov>=5.0 加入 dev 依赖
- [x] `[tool.coverage.run]` 排除无法在 CI 测试的模块（terminal/input_handler/esc_watcher/components/mcp client+transport/cli/__main__）
- [x] `[tool.coverage.report]` fail_under=80——低于 80% CI 自动失败
- [x] 当前覆盖率 81.62%（排除 TTY/MCP 层后），门禁通过

### P22.3 版本升级
- [x] `pyproject.toml` version 0.2.0 → 1.0.0（配合接口冻结的语义版本含义）
- [x] build 产出 mini_code_agent-1.0.0-py3-none-any.whl

---

## Phase 23: Diff 预览 + Streaming 扩展点 (P23)

### P23.1 Diff 预览
- [x] `tools/builtin/edit_file.py` — difflib.unified_diff 生成 diff 存入 ToolResult.metadata["diff"]（不改 output，diff 给用户看）
- [x] `ui/terminal.py` — show_tool_result 加 metadata 参数，edit_file 成功时 _render_diff 渲染整行背景色 diff（Rich Text.pad 填满终端宽度，删除行深红底、新增行深绿底）
- [x] `app.py` — on_tool_end 回调传完整 ToolResult（含 metadata）
- [x] 修复 diff 行粘连 bug（无换行符文件 splitlines(keepends=True) 不补 \n → 改为手动 +"\n"）

### P23.2 Streaming 中间态
- [x] `agent_loop.py` — on_tool_call_assembling 回调：流式期间 tool_call_delta 携带工具名时触发
- [x] `app.py` — 接线：首次收到工具名时打印 `╭─ tool_name ...`，on_tool_start 改为只补充参数摘要（不重复 ╭─），on_tool_end 清除标记

### P23.3 验证
- [x] 1 个新测试（edit_file diff in metadata），299 个测试全过

---

## Phase 24: 文件变更汇总 (P24)

### P24.1 变更跟踪
- [x] `core/agent_loop.py` — `_record_file_change()`：_execute_single_tool 中工具成功后集中跟踪（不改每个工具）
- [x] 判定规则：write_file + metadata["existed"]=False → created；write_file 覆写/edit_file → modified
- [x] 去重：dict 按路径去重，created 优先（先建后改仍算新建）
- [x] `last_turn_file_changes` 属性暴露（仿照 last_turn_tokens），run() 开始时重置

### P24.2 UI 显示
- [x] `ui/terminal.py` — `show_file_changes()`：新建 `+ 路径`（绿）、修改 `~ 路径`（黄）
- [x] `app.py` — _handle_turn 在 token 统计行前调用

### P24.3 验证
- [x] `tests/unit/test_file_changes.py` 新建 6 个测试（新建/修改/去重/每轮重置/失败不记录/覆写算修改），305 个测试全过

### P24.4 delete_file 工具
- [x] `tools/builtin/delete_file.py` 新建——删除单个文件，拒绝删除目录，专用工具替代 bash rm/del
- [x] 注册到 ALL_BUILTIN_TOOLS + config 默认 enabled_tools（现共 8 个内置工具）
- [x] `_record_file_change` 支持 deleted 类型（delete 覆盖一切——先建后删显示 deleted）
- [x] `show_file_changes` 红色 `- 路径` 标记删除
- [x] 4 个新测试（删除跟踪/删除覆盖新建/文件不存在报错/拒绝删目录），309 个测试全过

### 已知局限
- bash 命令造成的文件变更无法跟踪（如 echo x > file）
- delete_file 专用工具已提供——LLM 优先用它删除文件（可跟踪），bash rm/del 仍不可跟踪
- SubAgent 的文件变更不计入主轮汇总（独立 AgentLoop）

---

## Phase 25: 上下文感知 (P25)

### P25.1 指令文件发现与加载
- [x] `memory/project_context.py` 新建——`load_project_instructions()` 按优先级查找 AGENT.md → CLAUDE.md → .mini-agent/instructions.md，找到第一个就停
- [x] `load_user_instructions()` 读取 `~/.mini-agent/instructions.md`（所有项目共用的全局指令）
- [x] 单文件截断 8000 字符 + "(truncated)" 提示；空文件跳过找下一个

### P25.2 启动注入
- [x] `app.py` __init__ 中 system_prompt 构建后注入，marker `--- Project instructions ---` 去重（会话恢复不重复注入）
- [x] 启动时显示 `context: loaded CLAUDE.md` 提示

### P25.3 [context] 配置化
- [x] `models/config.py` 新增 `ContextConfig` dataclass（instruction_files/user_instructions_file/max_chars），挂到 AgentConfig.context
- [x] `project_context.py` 函数改为接受参数，原写死值降级为默认值——不配置行为不变
- [x] `config.toml.example` 加 [context] 注释示例；文件名/优先级/截断长度均可通过 config.toml 修改

### P25.4 验证
- [x] `tests/unit/test_project_context.py` 新建 12 个测试（优先级/回退/截断/空文件/用户指令/自定义文件名/自定义截断/Application 集成注入），321 个测试全过

### P25.5 文档
- [x] `docs/config-guide.md` 新建——配置文件/上下文文件/数据文件三类区分、全部文件清单、优先级链、修改方法、常见问题

---

## Phase 26: 对话分叉/回滚 (P26)

### P26.1 /undo 回滚
- [x] `extensions/builtin_commands.py` — `_make_undo`：扫描 Role.USER 消息定界轮次，截断最后 N 轮（默认 1）
- [x] 状态一致性：context_manager.update_total 重算 token + metadata.total_turns 递减
- [x] 显示被撤销的用户消息预览 + 回滚后 token 数
- [x] 边界处理：空对话/轮数不足报错不动

### P26.2 /fork 分叉
- [x] `_make_fork`：先存盘原线 → copy.deepcopy 对话 → 新 Session（新 session_id）→ _adopt_session 切换 → 存盘新分支
- [x] `/fork N` 支持分叉前先回滚 N 轮（从历史某点分叉）
- [x] 显示新旧 session_id，原线可 /session load 回去
- [x] 轮数不足时报错且不切换会话

### P26.3 验证
- [x] `tests/unit/test_undo_fork.py` 新建 10 个测试（单轮/多轮回滚/超界/空对话/tool 消息清理/token 重算/分叉隔离/深拷贝验证/带回滚分叉/回滚超界），331 个测试全过

---

## Phase 27: 操作级撤销 (P27)

### P27.1 文件快照
- [x] `memory/file_snapshots.py` 新建——FileSnapshotStore：每轮一个目录（turn_N/manifest.json + files/*.snap）
- [x] 三种状态：saved（存了旧内容）/ missing（原本不存在，undo=删除）/ too_large（>30MB 跳过，提示手动恢复）
- [x] 同轮同文件只快照第一次（保留轮开始时状态）
- [x] begin_turn 自动清理超过 5 轮的旧快照；clear() 会话结束清空整个目录

### P27.2 接线
- [x] `agent_loop.py` — snapshot_store 注入点 + current_turn_id 计数 + _execute_single_tool 中 write/edit/delete_file 执行前快照
- [x] `app.py` — 创建 FileSnapshotStore（.mini-agent/undo_snapshots/）+ 会话结束 clear()
- [x] `builtin_commands.py` /undo — 截断消息后按轮倒序恢复文件 + turn 计数回退 + 恢复报告追加到输出

### P27.3 验证
- [x] `tests/unit/test_file_snapshots.py` 新建 10 个测试（保存/missing 删除/too_large 跳过/首次快照优先/旧轮清理/多轮倒序恢复/clear + 三个 /undo 集成：新建删掉/修改还原/删除找回），344 个测试全过

### 边界（文档已注明）
- bash 命令的文件变更不快照
- 只保留最近 5 轮；单文件 30MB 上限
- 会话结束快照清空（undo 是会话内操作）

---

## Phase 28: 工具链录制/回放 (P28)

### P28.1 ToolRecorder
- [x] `core/tool_recorder.py` 新建——EventBus 订阅者（仿 AuditLogger 模式）：ToolCallStartEvent 捕获 name+args，ToolCallEndEvent 按 call_id 关联成功状态
- [x] 只录成功调用（is_error 的丢弃）；suspended 标志防回放自录
- [x] 存储 `~/.mini-agent/recordings/<name>.json`（含 name/created_at/steps）
- [x] start/stop/cancel/save/list_recordings/load/delete 完整生命周期

### P28.2 命令
- [x] `/record start <name>|stop|cancel|list|delete <name>` 五个子命令
- [x] `/replay <name>`——逐条构造 ToolCall 调 agent_loop._execute_single_tool（权限/hook/快照全走），逐步显示进度，失败即停

### P28.3 验证
- [x] `tests/unit/test_tool_recorder.py` 新建 10 个测试（保存/只录成功/cancel 丢弃/suspended 不录/未录制忽略/list-load-delete 往返 + 4 个命令集成：完整周期/回放真实执行/失败即停/录制不存在），354 个测试全过

### P28.4 参数模板化
- [x] render_template：递归替换 args 中的 {{变量}} 占位符（str/dict/list 全遍历）
- [x] 内置自动变量：{{date}}/{{time}}/{{datetime}}（回放时填当前值）
- [x] /replay <name> k=v 传自定义变量；缺变量时明确提示 Missing template variable(s)
- [x] find_placeholders 预扫描步骤中的占位符（回放前校验完整性）
- [x] 6 个新测试（替换/嵌套/内置变量/占位符发现/带变量回放/缺变量提示），360 个测试全过

### 局限（文档已注明）
- SubAgent 内部工具调用不录（独立 loop 不经主 EventBus）
- 回放结果不进对话历史（LLM 认知可能脱节，必要时提醒重读文件）
- 录制状态只在内存——中途崩溃丢失未保存的录制（已保存文件跨会话永久有效）

---

## Phase 29: 成本仪表盘 (P29)

### P29.1 数据管道
- [x] `models/events.py` — LLMResponseEvent 加 prompt_tokens/completion_tokens/model 三字段（带默认值向后兼容）
- [x] `agent_loop.py` — emit 时从 response.usage 填充（TokenUsage 的拆分数据原本被丢弃，现在接上）+ model_name 属性
- [x] `subagent.py` — SubAgent/SubAgentManager 传 model_name（强弱混编的 worker 便宜模型正确归属）
- [x] app.py — 模型切换（switch_llm_profile + /model 裸名兜底）同步 model_name

### P29.2 计价与预算
- [x] `models/config.py` — CostConfig（pricing dict + budget + currency），[cost] 段经 TOML 通用 _merge 自动生效
- [x] `core/cost_tracker.py` 新建——EventBus 订阅者（第 5 个纯订阅者）：按模型累计 prompt/completion/calls，input/output 分开计价（元/百万 token）
- [x] budget_status 三档：ok（<80%）/warn（80-100%）/over（≥100%）
- [x] app.py _show_budget_warning——每轮结束超 80% 黄色/超 100% 红色警告（提醒不阻断）

### P29.3 展示
- [x] `/cost` 命令——每模型 调用数/input/output/金额 + 总额 + 预算占比；未配置价格时提示如何配置
- [x] `/status` 加 Cost 行

### P29.4 验证
- [x] `tests/unit/test_cost_tracker.py` 新建 13 个测试（累计/unknown 归置/零用量忽略/计价公式/无价格 None/混合计价/预算三档/无预算恒 ok/摘要格式 + 4 集成：轮次记录模型用量/cost 命令/status 行/TOML [cost] 合并），373 个测试全过

### P29.5 累计总账与逐轮明细
- [x] `cost_ledger.json` 持久总账——存 token 非金额（价格调整后金额视图自动跟随），每轮幂等 flush，硬杀不丢
- [x] /cost 两区块面板（本次会话 + 累计总账）；/cost reset 确认后清零并重置起始日期
- [x] /cost turns 逐轮明细（会话级，end_turn 增量记录）
- [x] 轮末 token 行带金额：tokens: 6373 this turn (¥0.0089) / ... total (¥0.0182)
- [x] total_budget 总账预算——与会话 budget 独立检查，同 80%/100% 阈值，警告文案区分来源
- [x] 排版：宽度感知 CJK 填充（中文占2格）对齐表格 + 表头行 + "请求数=API调用次数"说明行

### 局限（文档已注明）
- 成本会话级（结束清零）——长期账单以供应商后台为准
- 价格表手工维护

---

## Phase 30: LLM 记忆提取 (P30)

### P30.1 LLM 提取替换 regex
- [x] `memory/extraction.py` 重写——regex 全删，改为 LLM 结构化提取：构造 EXTRACTION_PROMPT（3类：preference/convention/fact，JSON 数组输出）+ 调 `complete()` + JSON 解析（原 stream + assemble_response 已抽取为 `llm/base.py` 的 `complete()` 函数）
- [x] 取最近 20 条消息（MAX_RECENT_MESSAGES），ASSISTANT 内容截断 200 字（控制 token 消耗）
- [x] 降级：LLM 调用失败/JSON 解析失败/markdown 围栏 → 静默返回空列表（绝不阻断退出）

### P30.2 去重升级
- [x] 保留原有的完全匹配 + substring 去重
- [x] 新增词重叠度检查（_is_similar）：60% 词交集 → 视为重复（丢弃新的保留旧的）

### P30.3 SESSION_END hook 修复
- [x] `app.py` — 修复 P19 遗留 bug：MemoryExtractor() 无参数构造（与签名冲突）→ 改为传入 PersistentMemory + LLM Provider

### P30.4 验证
- [x] `tests/unit/test_persistent_memory.py` 重写 extraction 部分——9 个 LLM 提取测试（JSON 解析/空响应/畸形 JSON/markdown 围栏/精确去重/词重叠去重/项目级存储/无 LLM 降级/轮次不足跳过），391 个测试全过

---

## Phase 31: MCP HTTP Transport (P31)

### P31.1 HTTPTransport
- [x] `tools/mcp/transport.py` — HTTPTransport(MCPTransport)：httpx.AsyncClient POST JSON-RPC 2.0，30 秒超时，自动 id 递增
- [x] MCPTransport ABC 加 start() 非抽象方法（默认空操作），StdioTransport 和 HTTPTransport 都覆盖——不破坏接口冻结（加新方法含默认实现在 v1.0.0 承诺范围内）

### P31.2 MCPManager 分支
- [x] `tools/mcp/client.py` connect_server——transport=="http"/"sse" 时创建 HTTPTransport（需要 url，无 url 抛 ValueError）
- [x] MCPServerConfig 加 headers 字段——HTTP 认证（Bearer token / API key）经 config.toml 传入 HTTPTransport

### P31.3 app.py MCP 接线
- [x] 启动时 _connect_mcp_servers()：遍历 config.mcp.servers，connect_server 并显示 "MCP: name connected (N tools)"；连接失败显示错误不阻断启动
- [x] 退出时 mcp_manager.disconnect_all()

### P31.4 验证
- [x] 5 个新 MCP 测试（HTTP send/error/lifecycle/missing url/selects http），396 个测试全过

---

## Phase 32: 持久化任务系统 S12 (P32)

### S12 分析（实现前的缺口诊断）
- S01-S20 对照审计发现 S12 是唯一有实际价值的缺口
- 现状：PlanStep 有依赖图但用完即弃（/team 内存对象），无用户界面、不持久化
- 目标：TaskRecord + blockedBy + 磁盘持久化 + /todo 用户界面

### P32.1 TaskStore
- [x] `core/task_store.py` 新建——TaskRecord dataclass（id/description/status/blocked_by/tags）+ TaskStore（load/save/add/update/remove/get/clear_done/find_unblocked_by）
- [x] 存储 `<project>/.mini-agent/tasks.json`（JSON 单文件，方便手编辑）
- [x] ID 前缀匹配（/todo done task_a1 即可匹配完整 ID）；歧义前缀抛 AmbiguousTaskError 并列出所有匹配
- [x] min_unique_prefix()——显示时自动计算最短唯一前缀（替代固定 [:12] 截断）

### P32.2 /todo 命令
- [x] add/done/start/fail/delete/clear 子命令 + 默认 list
- [x] `--after <id>` 设依赖（blocked_by）
- [x] done 时提示 unblocked 的下游任务；start 时警告未完成的上游依赖
- [x] 列表按状态分组（pending/in_progress/completed/failed）

### P32.3 验证
- [x] 16 个新测试（CRUD + 持久化往返 + 依赖解锁 + /todo 命令各子命令），412 个测试全过

---

## Phase 33: PyPI 发布准备 (P33)

### P33.1 元数据补全
- [x] `pyproject.toml` — readme/license/authors/classifiers/[project.urls] 补齐（PyPI 必需字段）
- [x] `LICENSE` 文件新建（MIT）

### P33.2 发布 CI
- [x] `.github/workflows/publish.yml` 新建——tag v* 推送触发，PyPI Trusted Publisher（OIDC，无需 API token secret）

### P33.3 文档
- [x] README 加 `pip install mini-code-agent` 安装方式 + PyPI/Python/License 徽章 + 发布操作手册
- [x] 415 个测试全过

---

## Phase 34: Windows 终端适配 (P34)

### 审计发现（5 类问题）
- CLI 入口无 UTF-8 设置（CMD cp936 下特殊字符可能 UnicodeEncodeError）
- ask_yes_no 裸 PromptSession（TERM=xterm 时 NoConsoleScreenBufferError）
- 流式首行重复（Live 逻辑行 vs 物理行不一致，legacy 擦除不全）
- EscWatcher stop 不 join（残留线程吞按键）
- /todo emoji 在 legacy 控制台宽度错乱

### P34.1 修复
- [x] `cli.py` — _harden_windows_stdio()：入口 reconfigure UTF-8 + errors=replace 双保险
- [x] `ui/terminal.py` — ask_yes_no 构造失败退回朴素 input
- [x] `ui/renderer.py` — refresh 15→8Hz + vertical_overflow=crop + _tail_budget 物理行感知（长行换行时收缩逻辑行预算）
- [x] `ui/esc_watcher.py` — stop() join(timeout=0.2) 防吞键
- [x] `builtin_commands.py` — /todo 状态标记 legacy 下降级 ASCII（[ ]/[~]/[x]/[!]）

### P34.2 验证
- [x] `tests/unit/test_windows_rendering.py` 新建 10 个测试（legacy 控制台 diff/cost 渲染、GBK 流不崩、stdio 加固、EscWatcher join、ask_yes_no 兜底、emoji 降级、尾段预算收缩/不收缩），425 个测试全过

### P34.3 实战修复（真实终端验证时发现的问题）
- [x] `tools/builtin/bash.py` — `_decode_console_bytes()` 三级解码（严格 UTF-8 → 活动代码页/GBK → UTF-8 replace），修子进程 GBK 输出乱码
- [x] `app.py` + `security/permission.py` — LLM 擅自 git commit 双层防护：system prompt CRITICAL 红线 + DANGEROUS_COMMAND_PATTERNS 拦截全部 git 状态修改命令（commit/push/reset/stash/rebase/checkout/restore/clean）
- [x] `ui/terminal.py` — Git Bash（mintty）秒退修复：`_stdin_is_console()` isatty 检测 → 管道环境降级朴素 input；ask_yes_no 双重兜底（构造失败 + 运行时 EOF）
- [x] `cli.py` + `llm/openai_provider.py` — mintty 孤立代理字符崩溃修复：stdin reconfigure + 发送前 `_sanitize_surrogates()` 递归清洗消息树（GBK 用户名路径产生的 \udcXX 不再让 httpx JSON 编码崩溃）
- [x] `docs/terminal-guide.md` — 新建各系统各终端指南（打开方法/兼容等级/winpty 用法/问题排查表），README 双语链接接入
- [x] 遗留：压缩-重读膨胀待根治（tech-notes 34.3 ③）→ 已于 P36 根治

---

## Phase 35: 死循环诱导实验 (P35)

### 实验设计
- 5 个诱导场景：repeat_read / modify_until_match / search_nonexistent / infinite_subtask / self_referential
- 2 个实验臂：tight (max=5) / normal (max=20)
- 强硬系统提示迫使 LLM 不放弃、持续调用工具

### P35.1 实现
- [x] `experiments/deadlock_induction.py` — 新建实验脚本（沿用 compression_ab.py 模式）
- [x] 修复 max_iterations 通过 config 而非 _state 设置（_state 在 run() 中被重建覆盖）
- [x] 强化诱导 prompt + 专用 DEADLOCK_SYSTEM_PROMPT（禁止放弃、必须用工具）

### P35.2 结果
- [x] 全量运行 10 次，结果写入 `experiments/results/deadlock_*.json`
- [x] 核心发现：迭代上限是唯一可靠硬熔断（5/10 触发），same-tool-6x 在真实 LLM 下 0 次触发
- [x] self_referential 最危险：normal 臂跑满 20 轮消耗 330K token

### P35.3 文档
- [x] `experiments/README.md` 新增实验 3 完整段落（方法/结果/结论）
- [x] `docs/tech-notes.md` 新增 §35（same-tool-6x 盲区 / self_referential 危险模式 / 迭代上限可靠性）
- [x] `docs/roadmap.md` 死循环诱导实验标 ✅

---

## Phase 36: 压缩-重读膨胀根治 (P36)

### 背景
tech-notes 34.3 ③ 的实战问题：单请求烧 50 万 token。读大文件 → 压缩丢弃内容和文件名 → LLM 重读 → 再压缩循环。

### P36.1 实现（双层修复）
- [x] `memory/tool_result_cache.py` — 新建 ToolResultCache：>50K 字符工具结果溢写磁盘（`~/.mini-agent/cache/results/{session_id}/`），对话留 500 字符预览 + offset/limit 提示；错误结果不溢写；threshold=0 禁用
- [x] `models/config.py` — MemoryConfig 新增 `spill_threshold_chars = 50_000`（TOML `[memory]` 自动可配）
- [x] `core/agent_loop.py` — `_run_tool_pipeline()` 溢写钩子 + read_file 成功时记录已读文件
- [x] `memory/context.py` — `record_file_read()`（保序去重）+ `_inject_read_files()`：压缩后在摘要注入"已读文件清单"，二次压缩替换旧清单，纯滑窗路径插独立消息
- [x] `app.py` — 主循环注入 cache + 正常退出清理
- [x] `core/subagent.py` — SubAgent 独立 cache（子代理无 ContextManager，溢写是唯一保护）+ finally 清理

### P36.2 测试
- [x] `tests/unit/test_tool_result_cache.py` 新建 10 个测试（小结果不动/大结果溢写/错误不溢写/禁用/清理/去重保序/压缩注入清单/二次压缩替换/无已读不注入/agent_loop 集成），443 个测试全过

### P36.3 实战补修（真实验证暴露）
- [x] `memory/compressor.py` — SlidingWindow 任务锚点：截断后必保最近一条用户消息（长轮次提问被挤出窗口 → LLM 反问"你要做什么"）
- [x] `app.py` + `core/subagent.py` — system prompt 语言规则：用户用什么语言提问就用什么语言回答（此前默认英文回答中文问题）
- [x] 实测效果：同一问题 token 从 50 万降到 17 万，溢写生效（60K 字符文档只留 661 字符预览），熔断不误杀

---

## Phase 37: Anthropic Prompt 缓存 (P37)

### P37.1 实现
- [x] `llm/anthropic_provider.py` — stream() 三处 `cache_control: {"type": "ephemeral"}` 标记：系统提示（字符串→内容块列表）、工具 schema 最后一个、最后一条用户消息（字符串→块格式或已有块加标记）
- [x] `llm/anthropic_provider.py` — _parse_event() 解析 message_start 中的 cache_read_input_tokens / cache_creation_input_tokens
- [x] `llm/base.py` — TokenUsage 新增 cache_read_input_tokens / cache_creation_input_tokens 两个字段
- [x] `_mark_last_user_for_cache()` 独立辅助函数，处理字符串和内容块列表两种格式

### P37.2 测试
- [x] 6 个新测试（系统缓存标记/最后工具标记/最后用户消息/tool_result 用户消息/空工具/缓存统计解析），449 个测试全过

---

## Phase 38: 流式工具执行 (P38)

### P38.1 实现
- [x] `core/agent_loop.py` — IncrementalAssembler：流式中检测工具调用组装完成（index 前进 = 前序完成 / finish_reason = 全部完成），与 assemble_response 同构的 builder 逻辑但即时 flush
- [x] `core/agent_loop.py` — _think() 流式循环内：组装完成的调用经 would_ask 预判后 asyncio.create_task 立即提交；会弹窗的延迟到 _act
- [x] `core/agent_loop.py` — _act()：已提交的任务直接 await 收集，deferred 的走原有 Phase 1 串行确认；结果顺序保持
- [x] `security/permission.py` — would_ask() 非交互预判（bash→危险命令 / 路径工具→PathGuard+模式 / 其他→False），不弹窗无副作用
- [x] `models/config.py` — `streaming_tool_execution: bool = True` 开关（可关闭回退旧行为）
- [x] 取消清理：cancel() 和 no-tool-calls 分支取消孤儿任务

### P38.2 测试
- [x] `tests/unit/test_streaming_execution.py` 新建 10 个测试（组装器 3 / would_ask 4 / 集成 3：流中启动时序、开关回退、ask 工具延迟），459 个测试全过

---

## Phase 39: @file 内联引用 (P39)

### P39.1 实现
- [x] `ui/input_handler.py` — FileRefCompleter：@ 后触发文件路径补全（os.listdir 扫描，跳过 .git/.venv 等，目录结尾加 /，子目录路径支持）
- [x] `ui/input_handler.py` — expand_at_refs()：正则匹配 @filepath → 读文件内容替换为 `[File: path]\n```\ncontent\n```\``（10KB 上限截断，非文件原样保留）
- [x] `ui/input_handler.py` — merge_completers 合并斜杠命令补全和文件引用补全；_completion_active 条件扩展支持 @
- [x] `ui/terminal.py` — set_working_dir() + 传给 create_prompt_session
- [x] `app.py` — _handle_turn() 创建 Message 前展开 @file 引用

### P39.2 测试
- [x] `tests/unit/test_at_file_refs.py` 新建 12 个测试（展开 6 + 补全 6），471 个测试全过

---

## Phase 40: 权限规则文件 (P40)

### P40.1 实现
- [x] `security/permission.py` — load_rule_files()：解析用户级/项目级 permissions.toml 的 [commands]/[paths] allow/deny 规则；文件缺失跳过、格式错误警告不崩；reason 标注来源
- [x] `security/permission.py` — **PATH deny 短路修复**：check_path() 先查显式 DENY 规则再问 PathGuard——此前项目内路径被 PathGuard ALLOW 短路，用户的 deny 规则静默失效；_would_ask_path 对齐
- [x] `app.py` — 构造 PermissionManager 后加载两级规则文件
- [x] `permissions.toml.example` — 新建带注释示例（格式/优先级/glob 语法说明）

### P40.2 测试
- [x] `tests/unit/test_permission_files.py` 新建 9 个测试（用户级 allow/项目级 deny/两级合并/缺失/格式错误/项目内 deny 生效/would_ask 一致/deny 优先 allow/来源标注），480 个测试全过

---

## Phase 41: OS 级沙箱 (P41)

### P41.1 实现
- [x] `security/sandbox/__init__.py` — Sandbox ABC + SandboxConfig（allow_write/deny_write/network）+ create_sandbox() 工厂（Linux→BwrapSandbox / macOS→SeatbeltSandbox / Windows→None）
- [x] `security/sandbox/bwrap.py` — BwrapSandbox：bwrap --ro-bind / / + --bind 可写路径 + --ro-bind 强制只读 + --unshare-net 禁网 + --proc/--dev；shlex.quote 全转义
- [x] `security/sandbox/seatbelt.py` — SeatbeltSandbox：_build_profile SBPL（deny default + allow file-read* + 选择性 file-write* + 网络控制）；sandbox-exec -p profile bash -c command
- [x] `tools/builtin/bash.py` — sandbox/sandbox_config 工具属性 + execute() 创建子进程前 wrap
- [x] `models/config.py` — SecurityConfig 新增 sandbox/sandbox_auto_allow/sandbox_network
- [x] `app.py` — 启动接线（检测平台 + 注入 BashTool + 通知 PermissionManager）
- [x] `security/permission.py` — sandbox_auto_allow：危险命令在沙箱下免确认（显式 deny 规则仍拦）

### P41.2 测试
- [x] `tests/unit/test_sandbox.py` 新建 16 个测试（bwrap 5 / seatbelt 4 / 工厂 3 / bash 集成 2 / 权限 2），496 个测试全过

---

## Phase 42: 上下文窗口 API 探测 (P42)

### P42.1 实现
- [x] `llm/openai_provider.py` — _probe_context_window()：GET `{base_url}/models/{model}`，递归提取上下文窗口字段（context_window/context_length/max_context_length/max_model_len/max_input_tokens，阿里云 MaaS 实测嵌套在 extra_info.default_envs）；每实例只探测一次，失败静默回退硬编码表 → 128k 默认值
- [x] `llm/base.py` — LLMProvider.prepare() 可选预热钩子（默认无操作）
- [x] `app.py` — run() 首轮对话前调用 prepare()，让首轮溢出检查就用探测值（否则 agent_loop 在 stream() 前读 context_window 拿到的是回退值）
- [x] `extensions/builtin_commands.py` — /model 切换后对新 provider 调用 prepare()

### P42.2 测试
- [x] `tests/unit/test_llm_providers.py` 新增 8 个测试（字段提取 4 / 探测成功 / 失败回退 / 只探测一次 / prepare 预热），504 个测试全过；真实 API 实测阿里云 MaaS deepseek-v4-flash-0731 探测到 129024

---

## Phase 43: Token 计数精度提升 (P43)

### P43.1 实现
- [x] `llm/token_counter.py` — _estimate_tokens()：CJK 感知估算——CJK 字符（汉字/假名/谚文/全角符号 7 个 Unicode 区间）按 1 token/字，其余按 4 字符/token；替换纯 len//4（中文低估约 4 倍导致压缩迟迟不触发）
- [x] `memory/context.py` — record_api_usage()：API usage 锚点——LLM 返回的 usage 总量锚定在最新消息（prompt_tokens 含系统提示/全部消息/工具 schema，比估算准）；update_total() 优先用锚点总量 + 锚点后新消息估算；对象身份检查让压缩/undo 重排后锚点自动失效
- [x] `core/agent_loop.py` — 修复：assistant 消息 token_count 由 usage.total_tokens（含整个 prompt，按消息累加重复算 N 遍）改存 completion_tokens（消息自身大小）；每轮响应后调用 record_api_usage()
- [x] `llm/base.py`（原 `openai_provider.py`）— 修复：assemble_response 的 usage 由直接覆盖改按字段合并（Anthropic 把 prompt/completion 拆在 message_start/message_delta 两个事件，覆盖会丢 prompt 计数）；assemble_response 已从 openai_provider.py 移至 base.py

### P43.2 测试
- [x] `tests/unit/test_token_counter.py` 新建 11 个测试（CJK 估算 5 / usage 锚点 5 / usage 合并 1），515 个测试全过
- [x] 真实 API 实测校准（阿里云 MaaS，API usage 为真值）：中文估算从 -56% 低估（危险方向：压缩不触发→崩溃）修正为 +76% 高估（安全方向：压缩提前）；混合文本 -20% → +12%；英文/代码不变

---

## Phase 44: max_tokens 恢复 (P44)

### P44.1 实现
- [x] `core/agent_loop.py` — _think() 重试循环：finish_reason == "length" 时 max_tokens 翻倍重发（最多 MAX_TOKENS_RETRIES=3 次），仍截断保留最后结果；重试前取消流式提交的工具任务（参数可能被 JSON 中途切断）；用户取消不重试；流式调用逻辑提取为 _stream_once()
- [x] `llm/openai_provider.py` — stream() 的 max_tokens 支持 kwargs 覆盖配置值
- [x] `llm/anthropic_provider.py` — 同上；stop_reason="max_tokens" 归一化为 OpenAI 的 "length"（恢复逻辑两家通用）

### P44.2 测试
- [x] `tests/unit/test_agent_loop.py` 新增 3 个测试（翻倍重试成功 / 3 次后保留截断结果+倍增序列 / 正常结束不重试）+ `test_llm_providers.py` 补 max_tokens 映射断言，518 个测试全过

---

## Phase 45: Coordinator 模式 (P45)

### P45.1 实现
- [x] `core/planner.py` — _COORDINATOR_PREFIX 常量 + Planner 新增 coordinator 参数：coordinator 模式下 prompt 前追加协调者指令（只分解不操作）；max_steps 放宽到至少 8（不能自己补漏需更细粒度分解）
- [x] `core/team.py` — TeamConfig 新增 coordinator 字段；start() 中 coordinator 模式项目扫描从 2 级/80 行加深到 3 级/120 行；_scan_project_structure() 改为递归实现支持可配深度
- [x] `extensions/builtin_commands.py` — /team 解析 --coordinator flag + usage 字符串更新

### P45.2 测试
- [x] `tests/unit/test_team.py` 新增 3 个测试（prompt 注入验证 / max_steps 放宽 / 深度扫描），521 个测试全过

---

## Phase 46: Pydantic Schema 生成 (P46)

### P46.1 实现
- [x] `pyproject.toml` — pydantic>=2.0 从可选依赖移到主依赖（现在是核心功能）
- [x] `tools/base.py` — _schema_from_model()：从 Pydantic BaseModel 自动生成 ToolSchema；Tool.params_model/._name/._description 属性；schema 属性改为自动生成或手写覆盖
- [x] `tools/base.py` — Tool.validate_args() 升级：params_model 时用 Pydantic 验证含类型转换；否则走手写 schema 验证（向后兼容）
- [x] 7 个核心工具 Pydantic 化（P2 阶段 6 个工具 + P24 delete_file）：
  - [x] ReadFileParams — read_file（已完成，在先前改动中）
  - [x] WriteFileParams — write_file
  - [x] EditFileParams — edit_file（含 boolean replace_all）
  - [x] DeleteFileParams — delete_file
  - [x] GlobParams — glob（可选 path）
  - [x] GrepParams — grep（含 context: int）
  - [x] SpawnAgentsParams — spawn_agents（含 tasks: list[str]）
- [x] BashTool 保持手写 schema（向后兼容示例）

### P46.2 测试
- [x] `tests/unit/test_tools.py` 补充导入 DeleteFileTool, SpawnAgentsTool
- [x] 新增 7 个测试：write_file / edit_file / glob / grep / delete_file / spawn_agents schema 验证（各验证 name/param_names/required/default/type）
- [x] test_pydantic_schema_all_tools_json_format()：批量验证 7 个工具 JSON schema 格式合法
- [x] 已有测试覆盖：
  - test_pydantic_schema_generation() — ReadFile schema 生成
  - test_pydantic_schema_json_output() — JSON 格式验证
  - test_pydantic_validate_args_type_coercion() — 字符串→int 类型转换
  - test_pydantic_validate_args_missing_required() — 缺少必需参数报错
  - test_handwritten_schema_still_works() — BashTool 向后兼容
  - test_registry_mixed_pydantic_and_handwritten() — 混用验证
- [x] 543 个测试全过（新增 17 个）

### P46.3 优势
- 减少重复：从手写 7×(name + description + 参数列表) 减为 7 个 Pydantic 类
- 类型安全：Pydantic 自动验证和转换参数类型（数字字符串→int）
- LLM 友好：JSON schema 格式直接来自 Pydantic，无手工维护
- 向后兼容：BashTool 等可继续手写 schema，无破坏变更

---

## Phase 47: Pydantic Schema 全面增强 (P47)

### P47.1 实现
- [x] `tools/base.py` — 新增 `_resolve_refs(schema)`：递归解引用 `$ref/$defs`，去除 `title` 噪声，`seen: frozenset` 防循环引用
- [x] `tools/base.py` — `ToolSchema` 新增 `raw_parameters: dict | None = None` 字段
- [x] `tools/base.py` — `to_json_schema()` 双路径：`raw_parameters` 非空时直接用作 `parameters`；ToolParameter 后备路径补上 `default` 值输出
- [x] `tools/base.py` — `_schema_from_model()` 重写：`model_json_schema()` → `_resolve_refs()` → 存入 `raw_parameters`，不再拆解为 ToolParameter 列表
- [x] BashTool / MCP adapter 无需改动，继续走 ToolParameter 后备路径

### P47.2 新增支持的类型/模式
- [x] `str | None`（Optional）— anyOf 结构完整传递
- [x] `list[str]`（数组）— array + items 子 schema 完整保留
- [x] 嵌套 Pydantic 模型 — `$ref/$defs` 解引用内联，无残留引用
- [x] `Field(ge=0, le=100)` 约束 — minimum/maximum/minLength/maxLength 完整传递
- [x] `Literal["a","b"]` — enum + 正确类型
- [x] `dict[str, int]` — additionalProperties 完整传递
- [x] `default` 值 — 出现在 JSON schema 输出中（之前丢失）
- [x] 循环引用 — `seen` 集合防无限递归，遇到循环保留原始 $ref

### P47.3 测试
- [x] 改写 7 个旧 Pydantic schema 测试：从检查 `s.parameters`（ToolParameter 列表）改为检查 `to_json_schema()` 输出
- [x] 新增 10 个测试：
  - test_optional_type_schema — `str | None` → anyOf
  - test_array_items_schema — `list[str]` → array + items
  - test_nested_model_schema — 嵌套 BaseModel → $ref 解引用
  - test_constrained_field_schema — Field 约束 → minimum/maximum
  - test_literal_type_schema — Literal → enum
  - test_default_in_json_output — default 值输出
  - test_resolve_refs_direct — `_resolve_refs` 单元测试
  - test_dict_type_schema — `dict[str, int]` → additionalProperties
  - test_manual_schema_emits_defaults — ToolParameter 路径也输出 default
  - test_resolve_refs_circular — 循环引用防护
- [x] 48 个测试全过，ruff lint clean

---

## Phase 48: Agent Type Definition (P48)

### P48.1 实现
- [x] `core/agent_types.py` — 新文件：`AgentTypeDefinition` frozen dataclass + 4 种内置类型（explore/plan/worker/verify）
- [x] 每种类型定义：专属 system prompt、工具白名单（`allowed_tools: tuple`）、迭代上限（`max_iterations`）
- [x] `AGENT_TYPES` dict + `get_agent_type(name)` 查询（未知类型抛 ValueError）
- [x] `core/subagent.py` — `_intersect_tools()` 辅助函数：agent_type 白名单与调用方 allowed_tools 取交集
- [x] `SubAgent.__init__` 新增 `agent_type: AgentTypeDefinition | None` 参数：切换 prompt/工具过滤/config 浅拷贝覆盖迭代上限
- [x] `SubAgentManager.spawn` / `spawn_parallel` 新增 `agent_type: str | None` 参数，名称解析为定义后传给 SubAgent
- [x] `tools/builtin/spawn_agents.py` — `SpawnAgentsParams` 新增 `agent_type: str | None` 字段，execute 传递并捕获 ValueError
- [x] `extensions/builtin_commands.py` — `/spawn --type <name>` flag 解析，更新 usage 字符串
- [x] 向后兼容：不指定 agent_type 时行为与 P48 前完全一致

### P48.2 测试
- [x] `tests/unit/test_agent_types.py` 新文件：11 个测试
  - get_agent_type known/unknown、all_builtin_types_exist、definitions_are_frozen
  - worker_has_all_tools、verify_has_low_iterations、agent_types_dict_complete
  - intersect_tools 4 种组合（both_none/type_none/caller_none/both_set）
- [x] `tests/unit/test_subagent.py` 新增 4 个测试
  - subagent_with_explore_type、type_intersects_with_caller_tools
  - type_overrides_max_iterations、spawn_parallel_with_agent_type
- [x] `tests/unit/test_tools.py` 适配 spawn_agents schema 新增 agent_type 字段
- [x] 559 个测试全过，ruff lint + format clean

---

## Phase 49: Plan 模式只读 (P49)

### P49.1 实现
- [x] `core/agent_loop.py` — `_WRITE_TOOLS = frozenset({"write_file", "edit_file", "delete_file"})`
- [x] `AgentLoop.plan_mode: bool = False` — 运行时切换开关
- [x] `_think()` — plan_mode 时过滤 `get_schemas()` 排除写工具 schema
- [x] `_act()` — plan_mode 时写工具调用直接返回 `DENIED`（双保险）
- [x] 流式工具执行 — plan_mode 时延迟写工具到 `_act()` 拦截
- [x] `extensions/builtin_commands.py` — `/plan [on|off]` 命令注册
- [x] `/plan on` 注入只读 system prompt，`/plan off` 移除
- [x] bash 不在 _WRITE_TOOLS 中（由权限系统和沙箱控制）

### P49.2 测试
- [x] `tests/unit/test_agent_loop.py` 新增 3 个测试：
  - test_plan_mode_hides_write_schemas — schema 过滤
  - test_plan_mode_blocks_write_tool_call — 写工具拦截
  - test_plan_mode_off_allows_write — 正常模式不影响
- [x] 562 个测试全过，ruff lint + format clean

---

## Phase 50: Hook 事件类型扩充 (P50)

### P50.1 实现
- [x] `tools/hooks.py` — HookStage 新增 4 个：STARTUP/SHUTDOWN/TURN_START/TURN_END（共 11 个）
- [x] `core/agent_loop.py` — `run()` 开头触发 TURN_START（metadata: turn_id）
- [x] `core/agent_loop.py` — `run()` 结尾 TurnCompleteEvent 旁触发 TURN_END（metadata: iteration_count/tools_called/tokens_used）
- [x] `core/agent_loop.py` — `_think()` assemble_response 后触发 POST_LLM（观察式，metadata: content_preview/has_tool_calls/finish_reason）
- [x] `app.py` — `run()` 开头触发 STARTUP
- [x] `app.py` — SessionStartEvent 旁触发 SESSION_START（metadata: session_id/model）
- [x] `app.py` — 用户输入后触发 USER_INPUT，BLOCK 时跳过该轮显示 reason
- [x] `app.py` — finally 末尾触发 SHUTDOWN
- [x] 全部触发 try/except 包裹——hook 异常不破坏主流程
- [x] 11 个 HookStage 全部实际触发（此前 POST_LLM/SESSION_START/USER_INPUT 定义了但从未触发）

### P50.2 测试
- [x] `tests/unit/test_hooks_lifecycle.py` 新增 7 个测试：
  - test_all_stages_unique — 11 个枚举值唯一
  - test_turn_start_and_end_fire — 触发顺序 turn_start → pre_llm → turn_end
  - test_turn_end_receives_metadata — metadata 完整
  - test_post_llm_fires_with_content — content_preview/finish_reason
  - test_post_llm_block_does_not_affect_flow — 观察式验证
  - test_user_input_block_via_manager — BLOCK 拦截
  - test_startup_shutdown_session_start_via_manager — 生命周期注册链路
- [x] 569 个测试全过，ruff lint + format clean

---

## Phase 51: 工具搜索/延迟加载 (P51)

### P51.1 实现
- [x] `models/config.py` — `MCPServerConfig.loading: str = "eager"` 新增配置字段（"eager" | "dispatch"）
- [x] `tools/mcp/client.py` — `MCPManager._dispatch_tools` shadow catalog；`connect_server()` dispatch 模式不注册到 ToolRegistry
- [x] `tools/mcp/client.py` — `search_tools(query)` 按 name/description 模糊搜索；`list_dispatch_tools()` 列出全部概要
- [x] `tools/builtin/tool_search.py` — 新工具 ToolSearchTool：LLM 按关键词搜索 dispatch 工具
- [x] `tools/builtin/mcp_call.py` — 新工具 MCPCallTool：LLM 调用 dispatch 模式工具（server/tool/arguments）
- [x] `tools/builtin/__init__.py` — ALL_BUILTIN_TOOLS 增加 ToolSearchTool/MCPCallTool（共 10 个）
- [x] `tools/base.py` — ToolContext 新增 `mcp_manager: Any = None` 字段
- [x] `app.py` — ToolContext 注入 mcp_manager
- [x] `models/config.py` — enabled_tools 默认列表增加 tool_search/mcp_call

### P51.2 测试
- [x] `tests/unit/test_tool_search.py` 新文件，13 个测试：
  - search_tools 4 个（by_name/by_description/no_match/case_insensitive）
  - search_returns_parameters/search_multiple_matches
  - list_dispatch_tools/list_dispatch_tools_empty
  - dispatch_mode_not_in_registry/eager_mode_tools_in_registry
  - mcp_call_executes/tool_search_tool_returns_results/tool_search_no_results
- [x] `tests/integration/test_agent_e2e.py` 适配 10 工具集
- [x] 582 个测试全过，ruff lint + format clean

---

## Phase 52: 选择性记忆召回 (P52)

### P52.1 实现
- [x] `models/config.py` — MemoryConfig 新增 `recall_threshold: int = 10` / `recall_top_k: int = 5`
- [x] `memory/recall.py` 新模块 — `MemoryRecall.select_relevant()`：轻量 LLM 调用挑选相关记忆
- [x] RECALL_PROMPT：记忆列表（`id: content[:50]`）+ 用户最新消息（截断 500 字符）→ LLM 返回相关 ID JSON 数组
- [x] `_parse_ids()`：去 markdown fence → json.loads → 校验 list 类型，失败返回 None
- [x] 按 LLM 返回的 ID 顺序注入（保持相关性排序），截断到 top_k
- [x] fail-safe 回退链：llm=None / stream 异常 / 解析失败 → `entries[:10]`（现有行为）
- [x] 幻觉 ID 静默忽略（`by_id` 字典过滤）
- [x] `app.py` — `_pre_llm_inject_memory` hook 接入：>threshold 走召回，≤threshold 走原逻辑
- [x] marker 一次性注入机制保持不变（每会话注入一次）

### P52.2 测试
- [x] `tests/unit/test_memory_recall.py` 新文件，13 个测试：
  - selects_by_ids / preserves_llm_order / caps_at_top_k
  - invalid_json_fallback / llm_none_fallback / llm_exception_fallback / non_list_json_fallback
  - unknown_ids_ignored / empty_result / empty_entries
  - markdown_fenced_json / parse_ids_valid / parse_ids_invalid
- [x] 595 个测试全过，ruff lint + format clean

---

## Phase 53: 记忆合并 (P53)

### P53.1 实现
- [x] `models/config.py` — MemoryConfig 新增 `consolidation_threshold: int = 20`
- [x] `memory/consolidation.py` 新模块 — `MemoryConsolidator.consolidate()`：LLM 识别语义相关的记忆组并合并
- [x] CONSOLIDATION_PROMPT：全部记忆（`id: content` 全文）→ LLM 返回合并组 JSON（merge_ids + merged_content）
- [x] `_parse_groups()`：去 fence → json.loads → 逐项校验（merge_ids 是 list、merged_content 非空 str）
- [x] 合并规则：保留组内最新 created_at、tags 并集（保序去重）、source="extracted"
- [x] 防护：幻觉 ID 过滤、有效 ID <2 的组忽略、跨组重复 ID 只处理首组（consumed 集合）
- [x] 未合并条目原样保留
- [x] fail-safe：llm=None / <2 条 / 异常 / 解析失败 / 无有效合并组 → 返回 None（调用方 no-op）
- [x] `memory/extraction.py` — `MemoryExtractor.__init__` 新增 `consolidation_threshold` 参数；`maybe_extract()` 末尾调 `_maybe_consolidate()`（超阈值触发，try/except 包裹）
- [x] `app.py` — 传 `config.memory.consolidation_threshold` 给 MemoryExtractor
- [x] `extensions/builtin_commands.py` — `/memory consolidate` 手动子命令（≥2 条即可跑，无阈值限制）

### P53.2 测试
- [x] `tests/unit/test_memory_consolidation.py` 新文件，16 个测试：
  - merges_group / keeps_newest_created_at / merges_tags / unmerged_preserved
  - single_id_group_ignored / hallucinated_ids_filtered / duplicate_id_across_groups
  - empty_result / invalid_json / llm_none / exception / fewer_than_two_entries → 全部返回 None
  - markdown_fenced / parse_groups_valid / parse_groups_invalid / parse_groups_skips_malformed
- [x] 611 个测试全过，ruff lint + format clean

---

## Phase 54: Worktree 完善 (P54)

### P54.1 实现
- [x] `models/config.py` — SecurityConfig 新增 `worktree_max_age_days: int = 7`（0 = 禁用）
- [x] `security/worktree.py` — `create()` 自动符号链接依赖目录（`_LINK_DIRS = node_modules/.venv/vendor`）
- [x] `_link_dependency_dirs()`：存在才链，Windows 无符号链接权限时静默跳过（OSError）
- [x] `cleanup_stale(max_age_days)` — 扫描 base_dir，超龄且干净的 worktree 删除 + 删除对应分支；脏的保留（不丢未提交工作）；单个失败跳过不影响其他
- [x] `has_uncommitted_changes(worktree_path)` — 变更检测便捷方法
- [x] `app.py` — 启动时调 `cleanup_stale`（try/except 包裹，失败不阻断启动），有清理时显示提示
- [x] `extensions/builtin_commands.py` — `_format_agent_result()` 显示 worktree 路径 + `git merge <branch>` 合并提示

### P54.2 测试
- [x] `tests/integration/test_worktree.py` 新增 6 个测试：
  - create_symlinks_dependency_dirs（Windows 无权限 skip）
  - has_uncommitted_changes（干净 False / 脏 True）
  - cleanup_stale_removes_old_clean / keeps_dirty / keeps_recent / disabled
- [x] 616 个测试全过（1 skip：Windows symlink 权限），ruff lint + format clean

---

## Phase 55: Skill 安装命令 (P55)

### P55.1 实现
- [x] `extensions/skills.py` — `SkillRegistry.install(source, target_dir)` 安装方法
  - 本地路径 → `shutil.copytree`
  - git URL → `git clone --depth 1`
  - 安装后验证 SKILL.md 存在 + name 字段解析通过；验证失败自动清理已复制目录
- [x] `extensions/skills.py` — `SkillRegistry.uninstall(name, target_dir)` 卸载方法
  - 遍历 target_dir 匹配 SKILL.md 中的 name 字段 → `shutil.rmtree` + 从内存注册表移除
- [x] `extensions/builtin_commands.py` — `/skill install <path_or_url>` / `/skill uninstall <name>` 子命令
  - 安装目标固定为 `~/.mini-agent/skills/`
- [x] 已有安装拒绝（目标目录已存在 → 报错）

### P55.2 测试
- [x] `tests/unit/test_skills.py` 新增 5 个测试：
  - install_from_local_path / install_invalid_no_skill_md / install_invalid_no_name
  - uninstall_removes_dir / uninstall_not_found
- [x] 621 个测试全过，ruff lint + format clean

---

## Phase 56: Skill 热重载 (P56)

### P56.1 实现
- [x] `extensions/skills.py` — `load_all()` 改为先 `_skills.clear()` 再扫描（不再累积旧条目）
- [x] `SkillRegistry.reload(conversation)` — 保存活跃列表→全部停用（剥离旧 prompt）→重新加载→重激活（注入新 prompt）
- [x] 返回 `(loaded_count, lost_skills)` — lost 是活跃但磁盘已删除的 skill 名称列表
- [x] `extensions/builtin_commands.py` — `/skill reload` 子命令

### P56.2 测试
- [x] `tests/unit/test_skills.py` 新增 5 个测试：
  - reload_picks_up_new_skill / reload_removes_deleted_skill
  - reload_updates_active_prompt / reload_reports_lost_skills
  - load_all_clears_stale
- [x] 626 个测试全过，ruff lint + format clean

---

## Phase 57: 远程/浏览器模式 (P57)

### P57.1 实现
- [x] `pyproject.toml` — `websockets>=12.0` 可选依赖组 `[remote]`
- [x] `remote/__init__.py` 新目录
- [x] `remote/server.py` — RemoteServer 类
  - WebSocket 服务器 + HTTP 服务器（UI 托管 + `/cancel` + `/permission` 端点）
  - NDJSON 协议：12 种服务端事件 + 2 种 WS 客户端消息
  - 多客户端支持（`self._clients: set` 广播），回调通过 `_ws_send()` 广播给所有客户端
  - 权限确认通过 HTTP POST `/permission` + `call_soon_threadsafe` 解析 Future
  - Stop 通过 HTTP POST `/cancel`（绕过 WS 阻塞即时生效）
  - 新连接时 `_replay_history()` 回放对话历史
- [x] `remote/web_ui.py` — 嵌入式 HTML 前端
  - 深色主题（Catppuccin Mocha 色系）
  - Markdown 渲染（h1-h4、粗体、代码块、有序/无序列表、表格、链接+裸 URL、图片）
  - 流式文本渲染、工具调用（暗灰样式）、权限 Allow/Always/Deny 按钮（点击反馈+禁用）
  - Thinking 旋转指示器（荧光黄脉冲，工具调用间自动显示）
  - 用户输入框效果、起始引导（模型名+版本）
  - 自动滚动（300px 阈值）、info 等宽字体强制滚底
  - WebSocket 自动重连（2 秒）、Cache-Control 禁缓存
- [x] `remote/terminal.py` — RemoteTerminalAdapter
  - 拦截 show_info/show_error/show_file_changes 转发到浏览器
  - 内部 Python 异常过滤不推送到浏览器
  - show_file_changes 类型修复（list[tuple] 替代 dict）
- [x] `cli.py` — `--remote` / `--port 8765` / `--host localhost` / `--remote-token` 参数
  - remote 模式启动 RemoteServer 而非 app.run()
  - `--remote-token` 可选认证（WS 首条消息验证 + HTTP 端点参数验证）
  - websockets 未安装时优雅报错
- [x] `llm/base.py` — StreamChunk 加 `thinking` 字段
- [x] `llm/openai_provider.py` — 捕获 `reasoning_content`
- [x] `llm/anthropic_provider.py` — 捕获 `thinking_delta`
- [x] `core/agent_loop.py` — `on_thinking_delta` 回调 + `turn_start`/`turn_end` 事件

### P57.2 测试
- [x] `tests/unit/test_remote.py`，21 个测试：
  - NDJSON 格式：ndjson_event_format / client_message_format / turn_start_end / thinking_delta
  - 权限：permission_future_flow（3 种决策）
  - UI 构建：web_ui_builds / web_ui_port_embedded / web_ui_has_thinking_indicator
  - 服务器：remote_server_class_exists / remote_server_wraps_terminal
  - CLI：cli_remote_args / cli_default_no_remote
  - 终端适配器：show_info / suppresses_internal_errors / show_file_changes
  - Provider：openai_parse_reasoning_content / anthropic_parse_thinking_delta
  - StreamChunk：stream_chunk_thinking_field
  - 历史回放：replay_history_sends_messages
- [x] 649 个测试全过，ruff lint + format clean

### P57.3 增强
- [x] 多行输入 — `<textarea>` + Shift+Enter 换行 + auto-grow
- [x] 工具调用折叠 — `<details><summary>` 包装，默认展开
- [x] Token 用量显示 — `turn_end` 附带 tokens 字段
- [x] 工具耗时显示 — `on_tool_end` 传递 `duration_ms`，格式化显示
- [x] 动态命令列表 — 服务端发送 `commands` 事件，按字母排序
- [x] `<think>` 标签解析 — 渲染为折叠块
- [x] CSS 变量主题 — 18 个 CSS 变量替代硬编码色值
- [x] 应用层 ping/pong — 10 秒心跳
- [x] turn 完成摘要 — iterations + elapsed + tokens
- [x] 重连状态优化 — "Reconnecting..." + 黄色样式
- [x] `stream_end` 携带完整文本 — `full_text` 参数

### P57.4 修复
- [x] 单端口合并 — HTTP + WS 共用端口（`process_request` 拦截 GET `/`，`/ws` 走 WS 升级）
- [x] 多客户端回放修复 — `_replay_history` 只发给当前重连客户端
- [x] 用户消息多客户端同步 — 广播 `user_message` 事件
- [x] 段落换行 — CSS `white-space: pre-line` + `div.pg` 间距块
- [x] 滚动锁定 — `userScrolled` 标志，turn 结束重置
- [x] Cancel/Permission 改走 WS 消息
- [x] 主题切换 — 深/浅色（Catppuccin Mocha/Latte），header 按钮 + localStorage + `/theme` 命令联动
- [x] 651 个测试全过，ruff lint + format clean

## Phase 58: Mailbox 跨 Agent 通信 (P58)

> comparison-mewcode.md 6.2。SubAgent 从"派出去等结果"升级为运行中可互发消息。

### P58.1 实现
- [x] `core/mailbox.py` — MailMessage dataclass + Mailbox 类，每 Agent 一个 JSON 收件箱（`.mini-agent/mailboxes/<agent_id>.json`），register 总是重置避免跨会话残留
- [x] `send_message` 工具 — 发消息给指定 Agent（'main' = 主 Agent），收件人未注册报错并列出已知 Agent
- [x] `wait_message` 工具 — 阻塞等消息（0.5s 轮询，默认 120s / 上限 600s 超时），超时返回信息而非报错
- [x] `AgentLoop._deliver_mail()` — 每轮 THINK 前 drain 收件箱，消息以 `[Message from agent '<id>']` 前缀注入为 USER 消息
- [x] SubAgent 生命周期 — 构造时注册收件箱、system prompt 追加 MAILBOX_NOTICE、run() 结束注销
- [x] `ToolContext` 增加 mailbox / agent_id 字段；app.py 注册 'main' 收件箱并注入主循环
- [x] read-only agent 类型（explore/plan/verify）白名单含 send_message / wait_message

### P58.2 迭代修复
- [x] 兄弟 Agent 互不知 id → `spawn_parallel` 预生成全部 id，MAILBOX_NOTICE 列出同伴 id + 任务摘要（80 字符）
- [x] 主 LLM 分两次 spawn_agents 导致串行 → 工具描述明示"并发任务必须一次调用传入"
- [x] 接收方无等待原语、提前结束致 Unknown recipient → wait_message 工具 + notice 禁止 shell sleep 磨蹭
- [x] LLM 幻觉收件人 id（'agent-2'）→ notice 明令使用列出的精确 id + 同伴任务摘要消除角色歧义

### P58.3 测试
- [x] test_mailbox.py — 18 个单测：收发/清空/陈旧重置/peers/工具错误路径/AgentLoop 投递/SubAgent 注册注销/兄弟互见/wait_message 四路径
- [x] test_mailbox_e2e.py — 2 个端到端（Mock LLM 脚本化）：运行中互传、慢发送方时序下 wait_message 存活等待
- [x] 真实 LLM 验证 4 类拓扑：1→1 单向、2→1 汇聚多轮、1→2 判别寻址、1↔1 双向 5 轮乒乓
- [x] 671 个测试全过，ruff lint + format clean

### P58.4 增强：拉平 mewcode 四项差距
- [x] 广播 — `Mailbox.broadcast()`（排除发送者）+ send_message `to='*'`
- [x] 结构化消息协议 — `type=text/request/response` + request_id 配对（request 自动分配并回显）+ approve 表态；`_deliver_mail`/wait_message 前缀区分 [Request]/[Response]；response 缺 request_id 报错
- [x] 名字寻址 — `Mailbox.register(id, name)` 别名 + `resolve()` 双解析 + `describe_peers()`；spawn_agents 新增 `names` 参数（长度/唯一性/保留字 'main'/'*' 校验）；MAILBOX_NOTICE 显示 'explorer' (id xxx, task: ...)
- [x] 审计留痕 — drain 标记已读留盘（会话级）、unregister 保留收件箱文件、SubAgentManager 持有默认 Mailbox 时初始化 `reset_all()` 清理上一会话
- [x] 架构边界保持文档化不实现：跨进程文件锁 + 推送唤醒是 6.4 的前置（comparison 6.2）
- [x] 13 个新测试（test_mailbox.py 共 31 个），684 个全过，覆盖率 80.85%，ruff clean

## 会话自动清理 (comparison 9.1)

- [x] `SessionStore.cleanup_stale(max_age_days)` — 扫描 `~/.mini-agent/sessions/`，删除超过 N 天且 `closed_cleanly=True` 的会话；未正常关闭的跳过（崩溃恢复保留）
- [x] `MemoryConfig.session_cleanup_days = 30`（0 = 禁用）
- [x] `app.py` 启动时调用（worktree 清理之后、崩溃恢复之前），有清理时显示提示
- [x] 与 mewcode 差异：mini 跳过 `closed_cleanly=False`（崩溃会话保留），mewcode 直接按 `last_active` 删
- [x] 4 个测试（过期删除 / 未正常关闭跳过 / 0 禁用 / 空目录），688 个全过，ruff clean

## Hook 拒绝工具执行 (comparison 7.2)

- [x] 勘误：comparison 原描述"Hook 只能观察"陈旧——`HookAction.BLOCK` 在 `_run_tool_pipeline` 早已接线；真实差距是 mewcode 的拒绝 hook 可从**配置文件**声明，mini 只能写 Python
- [x] `tools/hooks.py` — `HookRule`（tool fnmatch + arg/contains/regex 匹配，非法正则告警跳过）+ `parse_hook_rules`（非法条目告警跳过）+ `register_hook_rules`（注册为 PRE_TOOL BLOCK）
- [x] `AgentConfig.hooks` 字段 — TOML `[[hooks]]` 经 loader `_merge` 顶层 setattr 自动落入，零 loader 改动
- [x] `app.py` 启动注册，提示 "Loaded N hook rule(s) from config"
- [x] 范围取舍：只做拒绝规则；mewcode 的 command/http/agent 动作类型不做——观察类扩展已有 EventBus 订阅者覆盖
- [x] regex 字段增量：re.search 匹配、与 contains AND 语义、非法正则告警跳过（parse 期 re.compile 校验）
- [x] 11 个测试（匹配/fnmatch/arg 限定/任意参数/默认 reason/非法跳过/TOML 往返/AgentLoop 端到端拦截/regex 三例），699 个全过

## 多后端 spawn (comparison 6.4)

### 前置：Mailbox 跨进程改造
- [x] `_with_lock` 文件锁：O_EXCL 锁文件 + 指数退避带抖动（5ms→80ms）+ 10s 陈旧锁接管 + 5s 超时抛 TimeoutError
- [x] 原子写：temp + os.replace，纯读免锁
- [x] 磁盘注册表 `_registry.json`（id→别名）替换内存注册，跨进程 resolve/peers/describe_peers
- [x] '_registry' 保留 id 守卫；reset_all 连注册表与锁残留清理
- [x] 唤醒以 wait_message 轮询替代推送（worker 为一次性任务，无需 send-keys 通道）
- [x] 实测 4 进程 × 20 条并发写同一收件箱零丢失

### worker 协议与窗格后端
- [x] `core/worker.py` — WorkerSpec（dump/load）+ run_worker：无头单任务，stdout 流式打窗格，结果原子写 JSON，hold_seconds 停留
- [x] `mini-agent --worker <spec.json>` CLI 入口
- [x] `core/spawn_backends.py` — 探测（TMUX/WT_SESSION 会话内分屏；装了 wt 但在其他终端 → wt -w -1 new-tab 降级弹新窗口）+ tmux split-window + wt split-pane（mewcode win32 放弃窗格，此为反超点）
- [x] `SubAgentManager.spawn_pane()` — _PaneWorkerProxy 顶替进活跃表，收集任务包装 asyncio.Task，wait/cancel/list 同构
- [x] `/spawn --pane <task>` 命令入口；spawn_agents 工具不暴露（窗格可视化给人看）
- [x] 顺带修复：wait() 对已 cancel agent 返回 error="Cancelled" 结果而非抛 CancelledError
- [x] 22 个新测试（探测含 wt-window 降级/命令构造/失败路径/WorkerSpec 往返/worker MockLLM 全链路/管理器收集/超时/取消/跨进程零丢失）
- [x] 真实 LLM 跨进程 E2E：worker 子进程注册可见 → send_message 跨进程送达 → 注销 → 结果收集 PASS
- [x] 实测踩坑修复：_PaneWorkerProxy.status 用了不存在的 AgentPhase.ACTING → /spawn wait 进度面板 AttributeError；cli 的 finally: sys.exit(0) 吞掉 traceback 让崩溃变无声 Goodbye；slash 命令异常缺兜底会炸整个会话——三处全修 + 回归测试
- [x] 728 个测试全过，ruff clean

### 实测反馈迭代（三轮真实使用暴露的问题）
- [x] `/spawn wait` 结果 200 字符截断腰斩交付物 → 完整输出（8000 字符防病态上限）
- [x] wt-window 降级每派发弹一个独立窗口轰炸 → `-w mini-agents` 命名窗口聚合，后续派发进同一窗口标签页
- [x] 两段式（派发+wait）对单任务多余 → `/spawn --wait` 一条命令派发+进度面板+结果（可与 --pane 组合）
- [x] slash 命令结果按 Markdown 渲染（app.py 打印处包 Markdown()）——worker 报告的 ##/表格/加粗此前按纯文本打印不渲染；_format_agent_result 改为 Markdown 友好结构（元数据列表 + 输出独立成段）
- [x] LLM Provider 429/5xx 退避重试（并行 pane worker 暴露：4 个 agent 同 key 打限流，一次 429 即零产出死亡）——两家 Provider stream 前置重试（尊重 Retry-After，指数退避带抖动，最多 3 次，chunk 产出后不重试防重复输出）+ 2 个 MockTransport 测试
- [x] worker 顶层崩溃护栏（实测暴露：崩在写结果之前 → 父进程只能超时、原因随窗格关闭消失）——任何异常都写失败结果文件 + 打印 traceback + 窗格停留
- [x] /spawn wait 超时 300→900 秒对齐收集器（实测暴露：大任务跑 5-15 分钟，300 秒超时后收集任务被取消，worker 后续完成的报告成孤儿）
- [x] 协议隔离修复（实测最深的坑）：worker 的 LLM 读到项目内自己的 spec（含 result_path）后"好心"提前自己写了结果桩，父进程 0.5s 轮询捡走（Tokens: 0），真结果被覆盖成孤儿——① spec/result 移到 ~/.mini-agent/workers/（工作目录外，agent 探索不到）② 收集器 schema+agent_id 双校验拒绝桩文件；2 个回归测试
- [x] 多 Agent wait 输出排版：总览表（状态/Tokens/Tools/任务）+ 逐份编号分节——worker 输出自带标题/分隔线，无硬边界糊成一片
- [x] 交付文件凸显：结果块自动提取输出中真实存在于工作目录的文件名列为"交付文件"行；slash 命令输出的行内代码（文件名/agent id）以亮橙色渲染（markdown.code 主题作用域覆盖）
- [x] 渲染回归修复（实测暴露：全量 Markdown 化把 /status /cost 的空格对齐版式搅碎）——改为显式哨兵 MARKDOWN_RESULT：只有 spawn 报告类输出走 Markdown 渲染（亮橙行内代码），其余命令恢复纯文本原样打印；remote 侧剥离哨兵
- [x] 429 重试耐心加大（实测再暴露：持续配额限流约几十秒，3 次约 7 秒退避扛不住）——MAX_HTTP_RETRIES 3→5，指数退避 1/2/4/8/16s 约 31 秒总耐心；测试用常量断言自动适配
- [x] 命令列表按字母排序：list_commands() 源头排序，一处改动覆盖四个消费方（`/` 下拉补全、/help、Unknown command 提示、浏览器端命令列表）
- [x] 新增 docs/commands-guide.md 命令参考（22 个命令完整语法/参数/示例/注意事项）——此前命令用法只有 /help 一行简述 + README 一行表 + 16 处用错才显示的 Usage 提示，无系统文档；README 双语已加链接，comparison 0.7 文档数 12→13

## OpenAI Responses API Provider (comparison 1.1)

- [x] `llm/openai_responses_provider.py` — 完整实现：消息转换（system→instructions / tool_calls→function_call / tool→function_call_output）、工具 schema 扁平化、SSE 事件解析（text/reasoning/tool call/completed/incomplete）、用量（cached_tokens 提取）、max_tokens→max_output_tokens 映射、上下文窗口探测+推理模型表（默认 200k）、429/5xx 退避重试
- [x] `llm/registry.py` — 注册 "openai-responses" → OpenAIResponsesProvider
- [x] 26 个单测（消息转换 4 + 工具扁平化 1 + 事件解析 8 + assemble 集成 1 + 窗口 2 + 注册 1 + 边界 2），747 个全过
- [x] 与 mewcode 差异：mewcode 依赖 openai SDK；mini 零 SDK（httpx 直连），自己解析 SSE 事件
- [x] 诚实边界：reasoning round-trip 未做（只影响 o1 会话恢复）；推理模型可能拒绝 temperature!=1（由 API 报错，不静默覆盖）

### 拉平 mewcode 三项差距
- [x] Thinking round-trip：agent_loop 累积 thinking 存入 Message.metadata["thinking"]，LLMResponse 新增 thinking 字段，assemble_response 组装 thinking；`_convert_to_input` 读 metadata 发出 reasoning 项（id + summary）
- [x] Tool pairing repair：`_convert_to_input` 跟踪 pending_call_ids，orphan function_call 补合成 "interrupted" 结果
- [x] 错误分类：LLMAuthenticationError（401）/ LLMRateLimitError（429，含 retry_after）/ LLMNetworkError（ConnectError/Timeout）——stream() 的 except 链在重试穿透后分类包装
- [x] 754 个测试全过

## Phase 59: 会话压缩边界 (P59)

> comparison-mewcode.md 9.2。压缩后记录边界标记，会话恢复时跳过已归档消息并恢复已读文件状态。

### P59.1 实现
- [x] `models/message.py` — `Conversation.compact_boundary: dict[str, Any] | None` 字段（summary + timestamp + read_files）
- [x] `memory/compressor.py` — `Compressor.compress()` 每个策略运行后记录边界（从压缩 SYSTEM 消息提取 summary）
- [x] `memory/context.py` — `check_and_compress()` 兜底：纯 SlidingWindow 不产生摘要时从 `_inject_read_files` 插入的消息创建边界 + 附加 `read_files` 列表
- [x] `memory/context.py` — 新增 `adopt_boundary()` 方法：从边界恢复 `_read_files` 状态
- [x] `memory/session_store.py` — 序列化：conversation 段写入 `compact_boundary`；反序列化：跳过 compressed SYSTEM 消息，从边界 summary 重建单条摘要消息
- [x] `app.py` — `_adopt_session()` 调用 `adopt_boundary()`，崩溃恢复 / `/session load` / `/fork` 三入口均自动恢复已读文件状态

### P59.2 测试
- [x] test_session_store.py — 4 个单元测试：边界往返 / 跳过压缩 SYSTEM / 保留非压缩消息（DropToolResults 的 TOOL 消息不被跳过）/ 无边界旧格式向后兼容
- [x] test_compact_boundary_e2e.py — 2 个集成测试：完整链路（ContextManager → Compressor → SessionStore 保存加载 → adopt_boundary 恢复 read_files）/ 旧格式兼容
- [x] 真实 LLM E2E 验证：DeepSeek 模型实际对话 → 压缩 → 保存 → 加载 → 边界 + read_files 恢复全链路 PASS
- [x] 实测暴露修复：纯 SlidingWindow 压缩（消息数 ≤ KEEP_RECENT=6 时 SummarizeOldest 跳过）不产生摘要消息，boundary 为 None → `check_and_compress` 兜底从 `_inject_read_files` 消息创建边界
- [x] 760 个测试全过，ruff lint + format clean

### P59.3 与 mewcode 的诚实差异（已记入总表）
- ~~恢复附件只记路径（mewcode 烤入最近 5 文件内容到摘要）~~ → ✅ 9.2a（P63 已完成）
- ~~KEEP_RECENT 固定切分可能切断 tool_use/tool_result 配对~~ → ✅ 9.2b（P60 已完成）
- ~~无压缩熔断器~~ → ✅ 9.2c（P62 已完成）

## Phase 60: 压缩工具对对齐 (P60)

> comparison-mewcode.md 9.2b。修复 9.2 诚实差异 #3：`KEEP_RECENT=6` 固定切分可能切断 tool_use/tool_result 配对，导致严格 API（OpenAI 官方/Anthropic）返回 400。

### P60.1 实现
- [x] `memory/compressor.py` — `_align_split_to_tool_pair(msgs, split)`：切分点落在 TOOL 消息时向前回退到工具对头部（assistant tool_calls 消息），配对整体保留在 kept；回退到 0 时无可摘要内容，压缩空操作
- [x] `SummarizeOldest` / `LLMSummarizeOldest` 均接入对齐（共用 helper）
- [x] `SlidingWindow` — 孤儿防护：token 切分落在工具对中间时丢弃开头的孤儿 tool result（向前扩会超预算），任务锚点逻辑不受影响

### P60.2 测试
- [x] test_context.py — 4 个单元测试：SummarizeOldest 对齐（边界回退到 assistant）/ 全部为工具对时空操作 / LLMSummarizeOldest 对齐 / SlidingWindow 孤儿丢弃 + 任务锚点共存
- [x] 真实 API 验证：DeepSeek 端点上对齐后的压缩产物发送成功；诚实发现——未对齐的孤儿 tool result 该端点也接受（宽容实现），修复价值在严格端点
- [x] 764 个测试全过（760 + 4 新增），ruff lint + format clean（顺手格式化了 2 个遗留未格式化的测试文件）

## Phase 61: 记忆导出/导入 (P61)

> comparison-mewcode.md 4.6。JSON 保持内部存储，新增 mewcode 兼容的 .md 互操作层：`/memory export [dir]` 与 `/memory import <dir>`。

### P61.1 实现
- [x] `memory/interop.py` 新模块 —— `export_memories(entries, dest, scopes)`：每条记忆一个 `{id}.md`（YAML 前置元数据）+ MEMORY.md 索引；`import_memories(dir)`：容错解析返回 `(entry, scope)` 对
- [x] 前置元数据字段：id / source / scope / created_at / tags（JSON 数组，逗号分隔回退）
- [x] `extensions/builtin_commands.py` —— `/memory export [dir]`（默认 `.mini-agent/memory-export/`，无项目时 `~/.mini-agent/memory-export/`）与 `/memory import <dir>`（id 去重 + scope 路由）
- [x] 容错导入：无前置元数据 / mewcode 风格（name/description/metadata 嵌套缩进跳过）/ 未闭合前置元数据整文件视为正文 / 空正文取 description / 空文件跳过

### P61.2 实测暴露修复
- [x] `source` ≠ 存储作用域：`/memory add` 进项目库的条目 `source="user"`，第一版按 source 路由导致跨机导入时项目记忆错进用户库 → 导出时显式写 `scope` 前置元数据，导入按 scope 还原

### P61.3 测试
- [x] test_memory_interop.py — 10 个单元测试：导出文件 + 索引 / 往返保真（含 scope）/ 无 scope 省略 / 跳过索引文件 / 纯 .md / mewcode 风格 / description 兜底 / 空文件 / 未闭合前置元数据 / tags 逗号回退
- [x] 真实 LLM E2E 验证：机器 A add → export → 机器 B import → 真实 Application 的 PRE_LLM hook 注入导入的记忆 → 真实 DeepSeek 正确答出只存在于记忆中的两个事实（项目代号 + 用户昵称），system prompt 注入确认为 True
- [x] 真实 handler 验证：临时目录跑真实 `_make_memory` —— add → export → 同机重导入全去重 → 跨机导入 scope 还原正确（project→项目库，user→用户库）→ 非目录/缺参数错误路径
- [x] 774 个测试全过（764 + 10 新增），ruff lint + format clean

## Phase 62: 压缩熔断器 (P62)

> comparison-mewcode.md 9.2c。连续压缩无效时熔断，防死循环烧 token。

### P62.1 实现
- [x] `ContextManager` 新增 `_compress_failures` / `_max_compress_failures` 字段——连续 N 次压缩后 token 未减少则跳过后续压缩
- [x] `MemoryConfig.compress_max_failures = 3` 配置项（0 = 禁用熔断器）
- [x] 成功压缩（token 减少）自动重置计数

### P62.2 测试
- [x] 3 个单元测试（test_context.py）：熔断触发 / 成功重置 / 禁用(0 值)
- [x] 1 个集成测试（test_compact_boundary_e2e.py）：完整链路 NoOp→失败累积→日志验证→熔断跳过→ensure_fits 兜底
- [x] 真实 LLM 验证（experiments/verify_circuit_breaker.py）：5 阶段——正常压缩 / 150 文件触发自然熔断 / ensure_fits 兜底 / 禁用对照 / 新会话恢复
- [x] 778 个测试全过（774 + 4 新增），ruff lint + format clean

## Phase 63: 压缩恢复附件含文件内容 (P63)

> comparison-mewcode.md 9.2a。消除 9.2 诚实差异 #1：压缩后烤入文件内容 + 用户请求，提升恢复质量。

### P63.1 实现
- [x] `llm/token_counter.py` — `truncate_to_tokens(text, max_tokens)`：二分搜索截断到指定 token 数内，超出追加 `\n... (truncated)`
- [x] `memory/context.py` — `_read_files: dict[str, str | None]` 升级：value 存储截断后的文件内容（5000 tokens/个）
- [x] `memory/context.py` — `record_file_read(path, content)` 增加 content 参数，有内容时截断存储，无内容时不覆盖
- [x] `core/agent_loop.py` — 在 spill 之前传递 `result.output` 到 `record_file_read`（修复 spill 后丢内容的 bug）
- [x] `memory/context.py` — `_inject_read_files()` 增强：注入三段恢复上下文（用户最近请求 + 已读文件路径 + 最近 5 个文件内容）
- [x] `memory/context.py` — `_last_user_request`：压缩前捕获最近 USER 消息（≤2000 字符），防压缩后 agent 丢失任务
- [x] `compact_boundary` 新增 `file_contents` + `last_user_request` 字段，`adopt_boundary()` 恢复，向后兼容旧格式
- [x] 模块常量提取：`_MAX_RECOVERY_FILES=5`、`_RECOVERY_TOKENS_PER_FILE=5000`、`_MAX_TASK_CHARS=2000`

### P63.2 测试
- [x] test_token_counter.py — 3 个测试：短文本保留 / 长文本截断 / 空文本边界
- [x] test_context.py — 11 个测试：内容存储截断 / 不覆盖 / 新内容覆盖 / 注入含内容 / 限制 5 个 / boundary 存储 / 恢复 / 向后兼容(2) / 用户请求压缩保留 / boundary 含请求 / 恢复请求 / 旧格式兼容
- [x] 真实 LLM 验证（DeepSeek）：`context_window=14000` 下读 2 文件 → 触发压缩 → 压缩后 agent 不重读文件、不丢失任务上下文、能引用文件内容细节
- [x] 793 个测试全过（778 + 3 + 11 + 1 flaky skip），ruff lint + format clean

## Phase 64: 上下文管理增强 (P64)

> todo-code-quality.md 上下文管理增强 ① + ②。P64.1 聚合工具结果预算（含三配套，已实现）；P64.2-64.4 LLM 摘要压缩接入 + 两个修复。

### P64.1 聚合工具结果预算（含三个配套机制）✅ 已实现
- [x] 【历史教训，非现状】P64.4 时期的首次尝试缺配套（反重溢写/预览太短/小结果豁免）→ 真实 LLM 验证失败 → 删除重做；对比 mewcode 后明确必须连同 3 个配套机制一起做（详见 todo-code-quality.md ①）。以下为重做后的完整实现：
- [x] `memory/tool_result_cache.py` — `PREVIEW_CHARS` 500→2000（配套 1b：预览太短 LLM 信息不足会绕过）；预览仍以 `min(PREVIEW_CHARS, threshold)` 封顶兼容小阈值测试
- [x] `maybe_spill(result, force=False)` — force=True 绕过单条阈值（供聚合预算强制溢写）；`len(output) <= 预览长度` 的结果一律豁免（配套 1c：溢写换不回空间）
- [x] `is_spill_readback(tool_name, arguments)` — read_file 的 file_path 落在溢写目录内时豁免（配套 1a：读回结果再溢写会死循环）
- [x] `spill_batch(results, already_used, exempt_ids)` — 累计超 `aggregate_chars` 时按 output 长度降序强制溢写至预算内；豁免错误结果/已溢写结果/exempt_ids/小结果；写盘 OSError 保留原文不炸 OBSERVE
- [x] `models/config.py` — `MemoryConfig.aggregate_spill_chars = 200_000`（0 = 禁用）
- [x] `core/agent_loop.py` — `_run_tool_pipeline()` 溢写前检查 `is_spill_readback`；OBSERVE 阶段调 `spill_batch`，`turn_result_chars` 跨迭代累计（只看单批会漏掉多次迭代累加撑爆）
- [x] `app.py` / `core/subagent.py` — ToolResultCache 装配传 `aggregate_chars`；`config.toml.example` 补注释
- [x] 溢写占位文案补溢写文件路径——LLM 可用 read_file offset/limit 精读（读回受 1a 豁免保护）
- [x] 13 个新测试（PREVIEW_CHARS/force 绕过阈值/force 小结果豁免/is_spill_readback 5 情形/批量欠额不动/降序溢写最大/exempt_ids/错误+已溢写跳过/跨迭代累计/aggregate=0 禁用/config 默认/2 集成：并行工具聚合溢写/读回不重溢写），816 个测试全过，ruff lint + format clean
- [x] 真实 LLM 验证（DeepSeek，threshold=50K/aggregate=8K）：并行读 3 个 ~6K 文件 → 单条不触发、聚合触发溢写 6/9 条、对话累计 15.5K 字符有界；LLM 看到 2000 字符预览后自主用 offset/limit 精读收敛作答；读回溢写文件未被重溢写
- [x] 交互式 E2E 验证（真实 mini 会话，aggregate=15000 极端参数，会话 JSON 审计 19 条工具结果）：6 验证点对账——溢写发生（9 条，read_file/grep/bash 全覆盖，SHA1 去重）✅ / 对话留 ~2284 字符预览 ✅ / 模型按占位路径 offset 精读一次收敛、零绕道 ✅ / 7 条大读回（最大 21.9K）原样保留不重溢写 ✅ / 小结果与首批"只溢写最大的"（CHANGELOG 溢写、README 保留）✅ / 成本有界⚠️见诚实边界
- [x] **配套修复 1：溢写缓存只读放行**（`security/path_guard.py` `_result_cache_root()`）——溢写目录在项目外，占位文案引导的读回每次弹权限框，'a'(always) 按精确路径记忆对新溢写文件无效；改为该目录 read 自动 ALLOW（write 仍询问），机制闭环不再需要人工放行。2 个测试
- [x] **配套修复 2：confirm() 提示符污染**（`ui/terminal.py`）——权限框复用主输入 PromptSession，prompt_toolkit 把传入 message 变成 session 新默认值，首次弹框后主提示符永久变成 "allow? [y/a/n] >"；改用临时 PromptSession（同 ask_yes_no 防污染模式）+ 无控制台兜底。2 个测试
- [x] **诚实边界**：豁免读回不被溢写但计入本轮累计预算——aggregate 设得小于典型单文件大小时（如 15K < 20K 文件），一次读回即耗尽预算，后续中等结果链式"溢写→读回"，对话同时保留预览+全文，预算未真正压住上下文。默认 200K 下单文件读回最多占 1/8 预算，无此问题；属极端参数下的已知行为，机制层面不可消除（模型执意读全文时内容终归进对话，预算只能让它显式地进）
- [x] 821 个测试全过（816 + 2 confirm + 2 path guard + 1 熔断器警告去重），ruff lint + format clean

### P64.2 LLM 摘要压缩接入
- [x] `models/config.py` — `MemoryConfig.llm_summarize = True`：默认启用 LLM 语义摘要
- [x] `app.py` — compressor 装配：`llm_summarize=True` 时用 `LLMSummarizeOldest(self._llm)` 替换 `SummarizeOldest`；失败自动回退抽取式
- [x] `config.toml.example` — `[memory]` 段补充 `llm_summarize` 注释示例

### P64.3 两个修复
- [x] **压缩检查移到 LLM 调用前**：`agent_loop.py` `_think()` 在 `ensure_fits` 之前调 `check_and_compress`——原来只在 OBSERVE 阶段（工具结果追加后）检查，纯对话场景永远不触发压缩
- [x] **压缩摘要前缀加明确指令**：`compressor.py` 三处摘要前缀加 "this is the authoritative record... Do NOT search session files"——压缩后 LLM 不再去磁盘翻会话文件

### P64.4 验证
- [x] 2 个新测试（config 默认 / config false） + 1 个已有测试适配摘要前缀变更，803 个测试全过
- [x] ruff lint + format clean
- [x] 真实 LLM 验证（context_window=10000）：纯对话场景压缩触发，但熔断器连续 3 次无效后开启——暴露 ⑤（token 驱动保留窗口）的必要性

---

## Phase 65: 压缩双阈值 (P65)

### P65.1 双阈值实现
- [x] `models/config.py` — `MemoryConfig.hard_compression_threshold: float = 0.90`（硬阈值，绕过熔断器）
- [x] `memory/context.py` — `ContextManager._hard_threshold` 字段 + `needs_hard_compression` 属性
- [x] `check_and_compress()` 熔断器检查加 `and not self.needs_hard_compression`：软阈值受熔断器控制，硬阈值绕过
- [x] 硬阈值触发时 WARNING 日志 `Hard compression threshold reached (X%), bypassing circuit breaker`
- [x] `/status` Context 行扩展：显示 `soft=75% hard=90% breaker=0/3`

### P65.2 测试
- [x] `tests/unit/test_context.py` 2 个新测试（硬阈值绕过熔断器 / 软阈值仍被阻断）
- [x] 3 个现有熔断器测试 + 1 个集成测试修复（显式设 `hard_compression_threshold=100.0` 防干扰）
- [x] 823 个测试全过，ruff lint + format clean

### P65.3 文档同步
- [x] `config.toml.example` / `docs/config-guide.md` / `docs/spec.md` — 新增硬阈值配置
- [x] `docs/capabilities.md` — "75% 阈值" → "75% 软阈值 + 90% 硬阈值绕过熔断器"
- [x] `docs/checklist.md` — 新增双阈值验收项
- [x] `docs/tech-notes.md` — 62.2 节更新为双阈值描述
- [x] `docs/todo-code-quality.md` — ☐ → ☑
- [x] `docs/comparison-mewcode.md` — 新增 4.7 节 + roadmap 表格行

### P65.4 验证
- [x] 真实 LLM E2E 脚本（Phase 1 核心逻辑 + Phase 2 五轮 DeepSeek 对话，context_window=6000）：熔断器开启后软阈值被阻断，硬阈值绕过执行完整级联压缩（8910→4760），熔断器重置
- [x] 终端窗口验证（context_window=20000，/trace + /status）：`breaker=3/3` 后消息数骤降证实硬阈值生效

---

## P66 Token 驱动的保留窗口

> todo-code-quality.md ⑤。替代固定 `KEEP_RECENT = 6` 消息的保留策略，改为 token 驱动：从尾部反向扫描累计 token，满足 `KEEP_RECENT_TOKENS(10K)` 且 `MIN_KEEP_MESSAGES(5)` 时停止，硬顶 `KEEP_MAX_TOKENS(40K)`。

### P66.1 实现
- [x] `memory/compressor.py` — 新增 `_compute_keep_split(msgs)` 函数：从尾部反向扫描，双条件停止（token ≥ 10K 且 count ≥ 5），硬顶 40K
- [x] `memory/compressor.py` — `SummarizeOldest` 移除 `KEEP_RECENT = 6`，改用 `_compute_keep_split()` + `_align_split_to_tool_pair()`
- [x] `memory/compressor.py` — `LLMSummarizeOldest` 同步移除 `KEEP_RECENT = 6`，改用 `_compute_keep_split()`
- [x] 消息数 ≤ `MIN_KEEP_MESSAGES` 时两个策略均跳过（与旧行为一致）

### P66.2 测试
- [x] `test_keep_split_short_messages_keeps_all` — 20 条 × 10 token = 200 < 10K → split=0 全保留（旧行为只保留 6）
- [x] `test_keep_split_long_messages_keeps_fewer` — 20 条 × 8K = 160K → 保留 5 条（MIN_KEEP_MESSAGES），旧行为保留 6 条 = 48K
- [x] `test_keep_split_hits_hard_cap` — 10 条 × 15K → 硬顶 40K 命中，只保留 2 条
- [x] `test_keep_split_minimum_messages` / `fewer_than_minimum` — ≤ MIN_KEEP_MESSAGES 时 split=0
- [x] `test_keep_split_meets_both_thresholds` — 15 条 × 2500 token → 双条件恰好满足时停在 5 条
- [x] `test_summarize_oldest_keeps_all_when_tokens_low` — 低 token 场景 SummarizeOldest 空操作
- [x] 已有 30+ 测试全部更新适配（token_count 调高触发 split，移除 `KEEP_RECENT` 引用）

### P66.3 验证
- [x] 真实 LLM 验证（DeepSeek，context_window=20000）：Phase 1 短消息全保留（20 条 × 10 token = 200，split=0，旧行为只留 6 条）；Phase 2 长消息少保留（20 条 × 8K，kept=5 = MIN_KEEP_MESSAGES，旧行为 6 × 8K = 48K）；Phase 3 真实对话压缩，token 驱动保留 13 条 ≈10639 tokens（旧 KEEP_RECENT=6 只保留 6 条）
- [x] 830 个测试全过（含 7 个新增），ruff lint + format clean

---

## P67 摘要 prompt 结构化

> todo-code-quality.md ⑥。`_SUMMARY_PROMPT` 从 4 条通用指令重写为 mewcode 风格的结构化 prompt：`<analysis>` 思考草稿 + `<summary>` 9 节结构化输出，只把 summary 块注入对话。

### P67.1 实现
- [x] `memory/compressor.py` — `_SUMMARY_PROMPT` 重写：先输出 `<analysis>`（时间线梳理消息 + 自查完整性），再输出 `<summary>` 9 节（主请求与意图 / 关键技术概念 / 文件与代码段 / 错误与修复 / 问题解决 / 全部用户消息 / 待做任务 / 当前工作 / 可选下一步）
- [x] mini 适配（非照搬 mewcode）：prompt 开头声明 "Recent messages are kept verbatim elsewhere"（mini 只摘要最旧前缀）；省去 "Do NOT call tools" 警告（`_summarize()` 直连 `llm.stream()` 不带工具）
- [x] `memory/compressor.py` — 新增 `_extract_summary()`：提取 `<summary>` 块内容注入对话；无标签回退完整输出；只有 `<analysis>`（输出截断）时剥离草稿返回空 → 触发上游抽取式回退
- [x] `memory/compressor.py` — 回退分支加 WARNING 日志（异常类型 + 消息）：真实验证遇到一次偶发回退但异常被静默吞掉，加日志让回退原因可观测

### P67.2 测试
- [x] `test_extract_summary_strips_analysis` — 只保留 summary 块内容
- [x] `test_extract_summary_no_tags_returns_all` — 无标签回退完整输出
- [x] `test_extract_summary_analysis_only_strips_scratchpad` — 截断场景草稿不泄漏
- [x] `test_llm_summarize_uses_extracted_summary` — 注入对话的消息不含 analysis 草稿
- [x] `test_llm_summarize_empty_summary_block_falls_back` — 空 summary 块触发抽取式回退
- [x] 既有 55 个 test_context 测试全过（mock 无标签输出走回退路径，无需改动）

### P67.3 验证
- [x] 真实 LLM E2E（`experiments/verify_summary_prompt.py`，20 条消息含 bug 修复剧情）：产出完整 9 节摘要，文件名（login.py/config.py）、用户约束（"不要改 session_store.py"）、错误根因与修复、下一步全部保留；`<analysis>` 无泄漏、`<summary>` 标签无泄漏、走 LLM 路径非回退
- [x] ruff lint + format clean

### P67.4 追加修复
- [x] 根因：DeepSeek 混合推理模型在 reasoning_content 烧 ~12K 字符，max_tokens=4096 下正文截断在 <analysis>/<summary> 中途 → 提取为空 → 8 次全部回退抽取式（回退日志暴露）
- [x] `SUMMARY_MAX_TOKENS = 8192` —— `_summarize()` kwargs 覆盖默认 4096
- [x] prompt 追加 "Keep the analysis BRIEF" —— 推理模型正文草稿不必重复展开
- [x] `_extract_summary()` 抢救未闭合 `<summary>` —— 残缺摘要仍好于抽取式（1 个新测试）
- [x] 真实会话 digest 复现验证：修复后 5708 字符完整 9 节摘要，无标签泄漏
- [x] 终端验证 P68 达标：Context 全程 64-76%，硬阈值仅 99% 触发一次（修复前 128%-191% 每轮）

### P67.5 二次压缩摘要退化（追加修复）
- [x] 第三轮终端验证：回退日志 0 次 / 硬阈值 0 次 / 熔断器未开启；压缩后主请求+约束+对话内约定全部答出，成本 ¥0.13
- [x] 新问题：`_extractive_digest` 300 字符截断作用于旧摘要消息，二次压缩产出"残缺摘要的摘要"（边界摘要自述 "the full request is unknown"）
- [x] 修复：对 `compressed=True` 的 SYSTEM 摘要消息豁免截断，整条传递（MAX_HISTORY_CHARS 统一封顶）
- [x] 真实 LLM 两轮压缩穿透验证：3 个埋点经两轮压缩全部存活；1 个新单测；841 个测试全过

---

## P68 保留窗口按压缩目标缩放

> P67 终端窗口验证（context_window=10000）暴露的真实缺陷：`KEEP_RECENT_TOKENS=10K` 绝对常量不小于压缩目标（7500）时，摘要级数学上永远达不到目标，压缩全部退化为 SlidingWindow 截断 + 硬阈值每轮空转，单轮烧 1M token 直到 80 轮迭代上限。

### P68.1 实现
- [x] `memory/compressor.py` — `_compute_keep_split(msgs, target_tokens)` 增加 target 参数：保留下限 `min(KEEP_RECENT_TOKENS, target//2)`、硬顶 `min(KEEP_MAX_TOKENS, target)`
- [x] 兜底：`keep_count == 0` 时强制保留 1 条尾部消息（最新消息单条超硬顶时不能全摘要掉）
- [x] `SummarizeOldest` / `LLMSummarizeOldest` 两个调用点传入 target_tokens
- [x] 大窗口行为不变：128K 窗口 target=96K 时 min 取的仍是 10K/40K 绝对值

### P68.2 测试
- [x] `test_keep_split_scales_to_small_target` — target=7500 时下限 3750/硬顶 7500，保留量在目标内
- [x] `test_keep_split_never_empties_tail` — 单条超硬顶也保底 1 条
- [x] `test_keep_split_large_target_unchanged` — 大目标下与缩放前行为一致
- [x] `test_llm_summarize_small_target_fits_budget` — 小目标端到端保留量 ≤ 目标
- [x] 既有测试适配：直接调用加 target 参数（200_000 保持原语义）、Summarize 测试 target 100 → 50_000

### P68.3 验证
- [x] 真实 LLM（target=7500 模拟 10K 窗口）：压缩后总量 7008 ≤ 7500，9 节结构化摘要存活；修复前该场景保留下限 10K 必然超标
- [x] 839 个测试全过，ruff lint + format clean

---

## P69 DropToolResults 尊重保留窗口

> 第五轮终端验证暴露：Stage 1 无差别截断全部工具结果（含模型正在使用的），诱发"以为工具坏了"的重读死循环（单轮 36+ 迭代 / 563K token）。第二轮验证的绕路脚本乱象深层机制相同。

### P69.1 实现
- [x] `DropToolResults.compress()` 先算 `_compute_keep_split(msgs, target_tokens)`，只截断可摘要前缀内的工具输出——与 Stage 2/3 的保留窗口语义对齐
- [x] 保留窗口内的工具结果（模型工作集）绝不截断；大结果入口防护由 tool_result_cache 溢写负责

### P69.2 测试与验证
- [x] 3 个单测：前缀截断 / 短输出跳过 / 保留窗口内新旧工具结果同场对照
- [x] 会话 JSON 取证：20 条工具消息 16 条被截（含近期结果），证实根因
- [x] 842 个测试全过，ruff lint + format clean
- [ ] 终端第六轮验证（无污染埋点召回 + 无重读螺旋）

---

## P70 第六轮终端验证收敛：恢复附件缩放 + 嵌套摘要约定前传

> P69 验收通过（36 迭代 → 4 迭代，重读螺旋消失）。会话 JSON 取证暴露两个新缺陷，当场修复。

### P70.1 缺陷 A：恢复附件预算不随窗口缩放
- [x] 取证：摘要消息 54,691 字符（LLM 摘要 7.8K + 附件 47K），25K token 附件超过 20K 窗口 → Context 钉死 112%
- [x] 修复：`_inject_read_files` 附件总预算 `min(25K, max_tokens//4)` 按文件数均分；128K 行为不变
- [x] 单测：8K vs 128K 窗口附件长度对照

### P70.2 缺陷 B：嵌套摘要二次总结丢约定
- [x] 取证：埋点进了第一次抽取式摘要，但二次 LLM 摘要只转述技术请求、丢弃约定
- [x] 修复：`_SUMMARY_PROMPT` 明确嵌套旧摘要是权威历史，约定/决策/约束必须前传
- [x] 真实 LLM 复现验证：第六轮丢失场景下 5 个约定全部前传
- [x] 843 个测试全过，ruff lint + format clean
- [x] 终端第七轮验证：P70 生效但暴露 P71（SlidingWindow 删摘要），见 P71

---

## P71 SlidingWindow 摘要锚点

> 第七轮终端验证定案：LLM 摘要完美保住埋点，但摘要位于头部、SlidingWindow 按尾部保留——Stage 3 第一个删的就是 Stage 2 刚生成的摘要。第六/七轮"边界空心化"的真正根因。

### P71.1 实现
- [x] `SlidingWindow.compress()` 增加摘要锚点：kept 无压缩 SYSTEM 消息时把摘要插回最前（与任务锚点同等待遇）

### P71.2 验证
- [x] 全管道插桩定位（真实 LLM + 真实文件 + check_and_compress）：确认 LLM summary out 含全部埋点、SlidingWindow 删除的恰好是摘要
- [x] 修复后全管道复现：S1/S2 两轮压缩四个埋点全部存活
- [x] 1 个新单测（紧预算摘要存活）；844 个测试全过，ruff lint + format clean
- [x] 终端第八轮验证：P71 生效但暴露 P72（附件污染 digest），见 P72

---

## P72 恢复附件污染 digest + 摘要重试

> 第八轮终端验证定案：LLM 摘要偶发失败 → 抽取式 S1 保住埋点但被烤入 17K 附件 → 二次摘要时埋点淹没在源码转储里被丢弃。

### P72.1 实现
- [x] `_extractive_digest` 传递旧摘要前剥离恢复附件（`RECOVERY_MARKERS` 共享常量）；纯附件消息剥后为空则跳过
- [x] `LLMSummarizeOldest.SUMMARY_RETRIES = 2`：偶发空摘要先重试再回退（todo ⑦ 重试部分落地）

### P72.2 验证
- [x] 复刻第八轮最恶劣路径（强制 LLM 失败×2 → 抽取式+附件 → 二次压缩）：埋点全存活
- [x] 3 个新单测；846 个测试全过，ruff lint + format clean
- [x] 终端第九轮验证 **最终通过**：五问全中（含反转题与陷阱题）；JSON 判定——4 个埋点全部不在保留历史（无污染）、全部存在于 LLM 摘要（9 节、无泄漏、无回退、breaker 0/3、¥0.13）


---

## P73 摘要 prompt 超长收缩重试

> mewcode 语义适配：prompt 超长时丢弃最旧 20% 消息后重试。mini 的 digest 已有 24K 截断，超长主要来自小窗口模型/网关限制——防御性收尾。

### P73.1 实现
- [x] `_is_prompt_too_long()`：httpx 400/413 一律算（流式下错误体常不可读、摘要请求格式固定）+ 错误消息关键词兜底
- [x] `LLMSummarizeOldest`：超长时丢最旧 20% 可摘要消息 + 字符 cap 缩 20% 重试（`MAX_SHRINKS=3`，与 `SUMMARY_RETRIES=2` 预算独立）
- [x] `_shrink_oldest()` 绝不丢头部旧压缩摘要（更早历史的唯一记录）
- [x] 穷尽即回退：收缩预算用完再遇超长直接落抽取式，不用相同请求烧偶发预算（真实运行暴露后当场修复）

### P73.2 验证
- [x] 6 个新单测（识别/收缩重试成功/穷尽回退/预算独立/旧摘要保护/无可丢不崩溃）；852 个测试全过，ruff clean
- [x] 真实 API 全管道验证（无污染埋点 + JSON 取证）：6.2M 字符 → 模型层真 400 → 2 轮收缩 → 3.98M（999K token）成功产出 9 节摘要，埋点约定存活、尺寸严格递减
- [x] 端点行为探明：阿里云 MaaS 网关 10MB→413、模型层 ~1.5M token→400，探测窗口 129K 非硬限制（811K token 照常接受）

---

## P74 最小前缀检查 + /todo 歧义前缀检测

> todo-code-quality.md ⑨（压缩器）+ /todo ID 前缀改进（task_store）。

### P74.1 压缩器最小前缀检查
- [x] `memory/compressor.py` — 新增 `MIN_SUMMARIZE_PREFIX_TOKENS = 2000` 常量 + `_prefix_tokens()` 辅助函数
- [x] `SummarizeOldest.compress()` + `LLMSummarizeOldest.compress()` — split 计算后检查前缀 token 量，< 2K 时跳过（与 mewcode `MIN_SUMMARIZE_PREFIX_TOKENS` 对齐）
- [x] 1 个新测试 `test_summarize_oldest_skips_when_prefix_too_small`

### P74.2 /todo 歧义前缀检测 + 最短唯一前缀
- [x] `core/task_store.py` — 新增 `AmbiguousTaskError` 异常类 + `get()` 分离精确匹配与前缀匹配（前缀匹配多个时抛异常）
- [x] `core/task_store.py` — 新增 `min_unique_prefix()` 方法（最少 5 字符，返回唯一标识该任务的最短前缀）
- [x] `extensions/builtin_commands.py` — `/todo` 全子命令（add/done/start/fail/delete）捕获 `AmbiguousTaskError` 并列出匹配项；ID 显示改用 `min_unique_prefix()` 替代固定 `[:12]` 截断
- [x] 5 个新测试（歧义前缀/精确匹配不误判/单任务前缀/共享前缀/命令层歧义处理）

### P74.3 文档同步
- [x] `docs/todo-code-quality.md` — ⑨ ☐→✅；④⑤⑥⑦⑩⑪ ☑→✅；节标题 ☐→✅
- [x] `docs/tasks.md` — P32.1 补充歧义前缀 + min_unique_prefix 完成项
- [x] `docs/tech-notes.md` — §32.2 扩展前缀匹配说明
- [x] `docs/commands-guide.md` — 补充歧义前缀报错和最短唯一前缀说明
- [x] `docs/checklist.md` — 功能检查项补充
- [x] `docs/agent-architecture.md` — S12 实现描述补充

---

## Phase 75: 遗忘代码接入 (P75)

> todo-code-quality.md 🔴「真正遗忘、应该接入」6 处，全部修复。

### P75.1 LLMResponse.model 赋值
- [x] `core/agent_loop.py` — `_stream_once()` 中 `assemble_response()` 后设置 `response.model = self.model_name`

### P75.2 CostTracker 缓存 token 差异化计费
- [x] `models/events.py` — `LLMResponseEvent` 新增 `cache_read_input_tokens` / `cache_creation_input_tokens`
- [x] `core/agent_loop.py` — `_stream_once()` 发射事件时填充缓存字段
- [x] `core/cost_tracker.py` — `_on_response()` 累计缓存 token；新增 `_compute_cost()` 统一方法：非缓存 = prompt - cache_read - cache_creation，按 `cache_read`/`cache_creation`/`input`/`output` 四种单价分别计费（缓存价未配则退回 input 价）
- [x] `end_turn()` / `_cost_of()` / `_model_lines()` / `_merged_models()` 全部改用 `_compute_cost()`
- [x] 测试适配新字段（`test_accumulates_per_model` / `test_flush_writes_and_reloads`）

### P75.3 enable_plan_mode 配置接入
- [x] `app.py` — 初始化时 `agent_loop.plan_mode = config.enable_plan_mode`
- [x] `models/config.py` — 默认值 `True` → `False`（用户需显式开启，避免默认禁写工具）

### P75.4 on_thinking_delta 终端接入
- [x] `ui/terminal.py` — 新增 `feed_thinking(delta)` 方法（dim italic 样式直出，不走 Live 缓冲）
- [x] `app.py` — 注册 `_on_thinking_delta` 回调，含双 Esc 中断检测

### P75.5 PermissionRequest.matched_rule 接入审计
- [x] `security/permission.py` — 新增 `last_matched_rule` 属性；`check()` / `_check_rules_only()` 规则匹配时同步赋值
- [x] `models/events.py` — `PermissionCheckEvent` 新增 `matched_rule` 字段
- [x] `core/agent_loop.py` — `_check_permission()` 发射事件时填充 `matched_rule`
- [x] `security/audit.py` — `_on_permission()` 有值时写入 JSONL

### P75.6 精确 token 计数 + 死函数清理
- [x] `memory/context.py` — `ContextManager.count_message()` 改为逐部分计数 + 每个 tool_call +3 开销（与原 `count_message_tokens` 精度一致）
- [x] `llm/token_counter.py` — 删除死函数 `count_message_tokens()` / `count_messages_tokens()`

### P75.7 文档同步
- [x] `docs/todo-code-quality.md` — 🔴 节标题 → ✅ 已全部修复，表格改为修复记录
- [x] `docs/spec.md` — `enable_plan_mode` 默认值 → `False` + 注释；`matched_rule` 补充用途说明
- [x] `docs/tech-notes.md` — §37.2 缓存统计补充 CostTracker 接入说明；token_counter 两层计数描述更新
- [x] `docs/tasks.md` — 新增 P75
- [x] `CHANGELOG.md` — 新增 Unreleased 条目

### P75.8 验证
- [x] 858 个测试全过，ruff lint + format clean

## 全局事件监听插件

**前因**：死代码审计发现 `EventBus.on_any()` 零调用方——用户想观察事件必须写 Python 改装配代码；且 `emit` 静默吞 handler 异常。**后果**：`listener_dirs` 丢 .py 即接入全局监听，异常隔离并可见。因果详述见 tech-notes §74。

- [x] `extensions/event_listeners.py` — `load_event_listeners(listener_dirs, bus)`：扫描配置目录加载 *.py 插件（下划线开头跳过），返回成功加载的插件名
- [x] 插件契约 — `register(bus)`（完全控制，优先）或 `on_event(event)`（同步/异步均可，自动经 `bus.on_any` 注册为全局监听）
- [x] 异常隔离 — 导入失败 / register 失败 / handler 异常均告警跳过，绝不影响 Agent 主流程
- [x] `events/bus.py` — `emit` 对 handler 异常记 warning 日志（原静默吞掉）；补充 `off_any()`
- [x] `models/config.py` — 顶级 `listener_dirs` 配置（默认 `./.mini-agent/listeners` + `~/.mini-agent/listeners`）
- [x] `app.py` — 启动时加载并提示 "Loaded N event listener(s): <名单>"

## HookAction.CONFIRM 接入

**前因**：`HookAction.CONFIRM` 自 P3 定义但 agent_loop 只处理 BLOCK，返回 CONFIRM 被静默放行（todo-code-quality 扩展点 #7）；`[[hooks]]` 只有一刀切拒绝，缺"敏感操作人工过闸"中间档。**后果**：`action = "confirm"` 规则弹 y/a/n 由用户裁决，拒绝原因回传 LLM。因果详述见 tech-notes §75。

- [x] `tools/hooks.py` — `HookRule` 新增 `action` 字段（`"block"` 默认 / `"confirm"`，非法值告警跳过）；`register_hook_rules` 按 action 注册 PRE_TOOL BLOCK/CONFIRM hook；`HookManager.would_confirm()` 非交互预判（对标 `PermissionManager.would_ask`，只覆盖声明式规则）
- [x] `core/agent_loop.py` — `_run_tool_pipeline` 处理 CONFIRM：`_resolve_hook_confirm` 弹 y/a/n（a = 本会话同 (工具, 原因) 不再问；无 UI 回调安全拒绝；asyncio.Lock 防并行弹窗交错）；拒绝回传 "Denied by user: <reason>"；流式执行对 would-confirm 的工具延迟到 `_act`
- [x] `app.py` — 注入 `terminal.confirm`（与权限确认同一 y/a/n 弹窗）；子 Agent 无 UI 保持安全拒绝
- [x] 测试 — 新增 9 个（解析/预判/短路/管道端到端 y/n/always/无回调），876 个全过，ruff clean
- [x] 真实 LLM 全管道验证（JSON 取证，三路径 PASS）：y 放行只问一次、n 拒绝且 LLM 正确收尾、a 两次写入只问一次