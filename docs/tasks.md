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
