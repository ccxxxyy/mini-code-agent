# Mini-Code-Agent 开发检查清单

每个 Phase 完成前，按此清单逐项检查。

---

## 通用检查项（每个 Phase 都要过）

### 代码质量
- [x] 所有函数/方法有类型注解（参数 + 返回值）
- [x] 没有 `Any` 类型的滥用（仅工具 kwargs、事件负载等真正动态处使用）
- [x] dataclass 使用 `slots=True`（Message/ToolCall/ToolResult 3 处性能敏感模型）
- [x] 异步函数命名清晰区分 sync/async
- [x] 没有未使用的 import（ruff F401 通过）
- [x] 没有硬编码的魔法数字/字符串（MAX_OUTPUT_CHARS/MAX_RESULTS/MAX_MATCHES 等均为命名常量）

### 错误处理
- [x] 外部 I/O（文件、网络、子进程）都有 try/except（工具全部 OSError 兜底，LLM 调用 app 层捕获）
- [x] 异常信息对用户有意义（ToolResult 携带具体原因，如 "File not found: xxx"）
- [x] 不吞异常（全部转为 is_error ToolResult 回传 LLM 或 show_error 显示）

### 安全
- [x] 文件路径操作使用 `Path.resolve()` 防止路径穿越（PathGuard 4 处 resolve）
- [x] 没有 `shell=True` 的不可控命令注入（bash 工具用 create_subprocess_shell 是设计意图——Agent 本身就是执行命令的工具，防护靠权限系统而非禁用 shell）
- [x] 敏感信息（API key）不在代码中硬编码（grep 扫描通过，密钥仅存 .env）
- [x] 不信任 LLM 输出的路径/命令（validate_args 校验 + PermissionCheck + PathGuard 三重验证）

### 测试
- [x] 新模块有对应的单元测试文件（11 个测试文件对应各核心模块）
- [x] 核心逻辑分支有测试覆盖（110 个测试）
- [x] 测试可以独立运行（MockLLM/ScriptedLLM 脚本回放 + tmp_path，零网络依赖）

---

## Phase 1 检查项

### 功能完整性
- [x] `uv run mini-agent` 成功启动 TUI（--version 与真实终端验证）
- [x] 能输入多行消息（Esc+Enter 插入换行）
- [x] LLM 流式输出实时显示（真实 API 流式验证通过）
- [x] Markdown 内容正确渲染（Rich Live + Markdown 组件，15fps）
- [x] 多轮对话上下文保持（to_api_messages 全量重放历史）
- [x] Ctrl+C 优雅退出（cli/app 双层 KeyboardInterrupt 处理）
- [x] 配置文件加载正确（优先级：CLI > MINI_AGENT_* > OPENAI_* > .env > defaults，单测锁定；project/user 级 TOML 配置推迟到 P4+）

### 架构合规
- [x] 目录结构与 spec.md 一致
- [x] EventBus 已就位且 emit 了 UserMessage/StreamChunk/SessionStart/End 等事件
- [x] Conversation 对象正确追加消息（含 token_count 累计）
- [x] LLMProvider 接口与 spec 定义一致（stream/count_tokens/context_window）

---

## Phase 2 检查项

### 功能完整性
- [x] 6 个工具全部注册到 ToolRegistry（app.py 按 enabled_tools 装配）
- [x] LLM 能正确发出 tool_calls（碎片化 ToolCallDelta 增量组装，真实 API 验证）
- [x] 工具结果正确回传给 LLM（TOOL 角色消息 + tool_call_id 配对）
- [x] Agent Loop ReAct 循环正常：think → tool_call → observe → think → answer
- [x] 多步工具链正常（MockLLM 单测 + 真实 API E2E 验证）
- [x] 多个 tool_calls 逐一执行正常（顺序执行保证确认弹窗不交错；asyncio.gather 并行优化推迟到后续版本）
- [x] 循环上限生效（max_iterations 单测 + 同工具连续 6 次死循环护栏）

### 各工具验证
- [x] ReadFile: 正确读取文件，行号正确，offset/limit 生效（3 个单测）
- [x] WriteFile: 正确写入文件，创建不存在的文件（自动建父目录）
- [x] EditFile: 正确替换文本，old_text 匹配正确（唯一匹配约束 + replace_all）
- [x] Bash: 命令执行，timeout 生效，stderr 捕获（exit code 标注，Win/Unix 兼容）
- [x] Glob: 模式匹配正确，返回排序文件列表（修改时间倒序）
- [x] Grep: 正则搜索，上下文行（context 参数），文件过滤（include）

### TUI
- [x] 工具调用显示名称和参数（⚙ 图标 + 参数预览截断）
- [x] 执行流程可视化（工具行即时打印；spinner 组件已备于 components.py，流式场景下即时行足够）
- [x] 工具结果正确渲染（✓ 行数/字符数摘要，✗ 错误预览）

---

## Phase 3 检查项

### 功能完整性
- [x] PermissionManager 评估顺序正确（DENY → ALLOW → Session → Default，单测锁定）
- [x] PathGuard 敏感目录拒绝生效（.ssh/.aws/.gnupg + 敏感文件模式）
- [x] 危险 bash 命令触发确认弹窗（13 条正则，即使 allow 模式也确认）
- [x] 用户选择 "always allow" 后同类操作不再弹窗（confirm 支持 y/a/n 三选，"a" 写入会话白名单，单测验证）
- [x] Hook PRE_TOOL 能阻止工具执行（BLOCK 短路 + reason 回传 LLM）
- [x] Hook POST_TOOL 能观察工具结果（集成测试验证）

### 安全验证
- [x] `rm -rf /` → 配置黑名单直接拒绝；`rm -rf ./xxx` → 确认弹窗（单测覆盖两种路径）
- [x] `sudo xxx` → 确认弹窗（危险正则命中）
- [x] 读取 `~/.ssh/id_rsa` → 拒绝（硬拒绝不弹窗）
- [x] 读取 `~/.aws/credentials` → 拒绝
- [x] 项目内文件正常读写 → 自动允许（.env 等敏感文件除外）

---

## Phase 4 检查项

### 功能完整性
- [x] ContextManager 正确跟踪 token 使用（count_message 缓存 + update_total 全量重算）
- [x] 达到 75% 阈值自动触发压缩（needs_compression 属性 + check_and_compress 集成到 AgentLoop OBSERVE 阶段）
- [x] 压缩后对话连贯性保持（SummarizeOldest 保留最近 6 条 + 提取式摘要保留角色和关键内容）
- [x] Session 可序列化/反序列化（JSON，含 ToolCall/ToolResult 完整往返，6 个单测覆盖）
- [x] 会话恢复后对话状态完整（system_prompt + messages + metadata 全部还原）
- [x] 跨会话记忆 CRUD 正常（项目级 + 用户级双层存储，add/load/save/search）
- [x] 记忆搜索返回相关结果（关键词 + 标签双通道匹配，跨层搜索）

### 压缩策略验证
- [x] Stage 1: 工具输出精简生效（>200 字符截断 + 行数/字符数摘要，单测验证短输出跳过）
- [x] Stage 2: 提取式摘要生效（保留最近 6 条 + 旧消息按 role 摘要，单测验证消息数不足时跳过）
- [x] Stage 3: 滑动窗口兜底正常（按 token 预算从后往前保留，最终一定收敛到目标以内）

---

## Phase 5 检查项

### Slash Commands
- [ ] `/help` 列出所有命令
- [ ] `/clear` 清空对话
- [ ] `/status` 显示状态
- [ ] `/model <name>` 切换模型
- [ ] `/compact` 手动压缩
- [ ] `/quit` 退出
- [ ] 未知命令给出提示

### Skill 系统
- [ ] SKILL.md 正确解析（YAML front-matter + prompt body）
- [ ] 技能激活后 system prompt 正确注入
- [ ] 触发词自动匹配
- [ ] 技能停用后 prompt 正确移除

### MCP
- [ ] stdio transport 连接正常
- [ ] 工具发现正确
- [ ] MCPToolAdapter 注册到 ToolRegistry
- [ ] 通过 Agent 调用 MCP 工具正常
- [ ] 服务器断连后优雅处理

### Anthropic Provider
- [ ] 流式响应正常
- [ ] tool_use 格式正确
- [ ] thinking blocks 解析（如适用）
- [ ] token 计数合理

---

## Phase 6 检查项

### SubAgent
- [ ] SubAgent 在独立 asyncio Task 中运行
- [ ] spawn_parallel 多个 SubAgent 并行执行
- [ ] 每个 SubAgent 有独立的 ToolRegistry 副本
- [ ] SubAgentResult 正确收集
- [ ] SubAgent 超时/取消正常

### Worktree
- [ ] `git worktree add` 正确创建
- [ ] SubAgent 在 worktree 目录工作
- [ ] worktree 无变更时自动清理
- [ ] merge_back 正常合并
- [ ] 冲突时正确报告

### Agent Teams
- [ ] Orchestrator 能分解任务
- [ ] 团队成员按角色分配
- [ ] 各成员在独立 worktree 工作
- [ ] 协调循环正常运行
- [ ] 结果汇总正确

---

## Phase 7 检查项

### 测试覆盖
- [ ] 单元测试 ≥ 80% 覆盖率（核心模块）
- [ ] 所有集成测试通过
- [ ] `uv run pytest` 全绿

### 生产就绪
- [ ] 所有已知 edge case 有处理
- [ ] 内存泄漏检查（长会话）
- [ ] 并发安全（多 SubAgent 场景）
- [ ] 错误消息对最终用户友好
- [ ] 配置验证错误给出清晰提示
