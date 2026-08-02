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
- [ ] `models/permissions.py` — PermissionLevel, PermissionScope, PermissionRule, PermissionRequest, PermissionDecision
- [ ] `security/permission.py` — PermissionManager (check, check_path, check_command, grant_session)
- [ ] `security/path_guard.py` — PathGuard (敏感目录拒绝, 项目目录允许, 其余 ask)
- [ ] `security/tool_filter.py` — ToolFilter (上下文过滤)

### P3.2 Hook 系统
- [ ] `tools/hooks.py` — HookStage, HookContext, HookAction, HookResult, HookFn, HookManager
- [ ] 内置 Hook: 危险命令确认, 敏感文件保护
- [ ] Agent Loop 集成 Hook 链 (PRE_TOOL, POST_TOOL, PRE_LLM, POST_LLM)

### P3.3 TUI 权限交互
- [ ] `ui/terminal.py` 扩展 — confirm() 确认弹窗

### P3.4 验证
- [ ] bash 执行 `rm -rf /` → 触发确认弹窗
- [ ] 尝试读取 `~/.ssh/id_rsa` → 拒绝
- [ ] 正常读写项目内文件 → 自动允许

---

## Phase 4: 记忆 + 上下文管理 (P4)

### P4.1 Token 管理
- [ ] `llm/token_counter.py` 完善 — 各 Provider 精确 token 计数

### P4.2 上下文管理
- [ ] `memory/context.py` — ContextManager (add_message, check_and_compress, usage_ratio, tokens_remaining)
- [ ] `memory/compressor.py` — CompressionStrategy ABC + 三级策略 (DropToolResults, SummarizeOldest, SlidingWindow)

### P4.3 会话持久化
- [ ] `memory/session_store.py` — SessionStore (save, load, list_sessions, delete)

### P4.4 跨会话记忆
- [ ] `memory/persistent.py` — PersistentMemory (项目级 + 用户级, CRUD, search)
- [ ] `memory/extraction.py` — MemoryExtractor (对话分析, 自动提取, 去重)

### P4.5 验证
- [ ] 长对话 (50+ 轮) 后自动压缩, token 使用率下降
- [ ] 退出后重启, `/session resume` 恢复会话
- [ ] 跨会话记忆: 上次提到的偏好在新会话中被回忆

---

## Phase 5: 扩展协议 (P5)

### P5.1 Slash Commands
- [ ] `extensions/slash_commands.py` — SlashCommand, SlashCommandRegistry
- [ ] 内置命令: /help, /clear, /status, /model, /compact, /memory, /session, /plan, /tools, /mcp, /skill, /quit

### P5.2 Skill 系统
- [ ] `extensions/skills.py` — Skill, SkillRegistry (扫描加载, 激活/停用, trigger 匹配)
- [ ] `extensions/plugin_loader.py` — 动态发现
- [ ] 内置技能包: `skills/code_review/SKILL.md`, `skills/init_project/SKILL.md`

### P5.3 MCP 协议
- [ ] `tools/mcp/transport.py` — StdioTransport, HTTPTransport
- [ ] `tools/mcp/client.py` — MCPManager (connect, disconnect, call_tool, discover)
- [ ] `tools/mcp/adapter.py` — MCPToolAdapter (MCP 工具 → 内部 Tool 接口)

### P5.4 第二个 LLM Provider
- [ ] `llm/anthropic_provider.py` — Claude Messages API (SSE, tool_use, thinking blocks)

### P5.5 验证
- [ ] `/help` 列出所有可用命令
- [ ] `/skill code-review` 激活代码审查技能
- [ ] 配置 MCP GitHub 服务器 → 列出其工具 → 通过 Agent 调用
- [ ] 切换到 Anthropic Provider, 流式对话正常

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
