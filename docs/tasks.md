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
- [x] `memory/extraction.py` 重写——regex 全删，改为 LLM 结构化提取：构造 EXTRACTION_PROMPT（3类：preference/convention/fact，JSON 数组输出）+ 调 stream + assemble_response + JSON 解析
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
