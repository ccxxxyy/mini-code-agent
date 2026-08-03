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
- [ ] `security/worktree.py` — WorktreeManager (create, remove, list, merge_back)

### P6.2 SubAgent
- [ ] `core/subagent.py` — SubAgent, SubAgentResult, SubAgentManager (spawn, spawn_parallel, wait_all, cancel)

### P6.3 Plan 模式
- [ ] `core/planner.py` — Planner (decompose, 结构化任务分解)

### P6.4 Agent Teams
- [ ] `core/team.py` — TeamMember, TeamConfig, AgentTeam (start, coordinate, stop)

### P6.5 TUI 多 Agent 监控
- [ ] 多 Agent 状态面板, 进度展示

### P6.6 验证
- [ ] "并行修复 auth 和更新测试" → 两个 SubAgent 在不同 worktree 工作
- [ ] Agent Team 协调完成跨领域任务

---

## Phase 7: 打磨 (P7)

### P7.1 测试
- [ ] 单元测试: agent_loop, tools, llm_providers, memory, permissions, events, config, models
- [ ] 集成测试: mcp_client, agent_e2e, session_persistence, worktree

### P7.2 错误处理
- [ ] 全面错误处理审查, 优雅失败

### P7.3 性能优化
- [ ] 流式延迟优化, token 计数缓存

### P7.4 UI 打磨
- [ ] `ui/themes.py` — 主题系统
- [ ] `ui/components.py` 完善 — 可复用 UI 组件
- [ ] `ui/input_handler.py` 完善 — 快捷键, vi 模式, 自动补全
