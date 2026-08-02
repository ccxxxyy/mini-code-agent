# Mini-Code-Agent 开发检查清单

每个 Phase 完成前，按此清单逐项检查。

---

## 通用检查项（每个 Phase 都要过）

### 代码质量
- [ ] 所有函数/方法有类型注解（参数 + 返回值）
- [ ] 没有 `Any` 类型的滥用（仅在真正需要动态类型时使用）
- [ ] dataclass 使用 `slots=True`（性能敏感的模型类）
- [ ] 异步函数命名清晰区分 sync/async
- [ ] 没有未使用的 import
- [ ] 没有硬编码的魔法数字/字符串（使用常量或配置）

### 错误处理
- [ ] 外部 I/O（文件、网络、子进程）都有 try/except
- [ ] 异常信息对用户有意义（不是裸的 traceback）
- [ ] 不吞异常（至少 log）

### 安全
- [ ] 文件路径操作使用 `Path.resolve()` 防止路径穿越
- [ ] 没有 `shell=True` 的不可控命令注入
- [ ] 敏感信息（API key）不在代码中硬编码
- [ ] 不信任 LLM 输出的路径/命令（总是验证）

### 测试
- [ ] 新模块有对应的单元测试文件
- [ ] 核心逻辑分支有测试覆盖
- [ ] 测试可以独立运行（不依赖外部 API/网络）

---

## Phase 1 检查项

### 功能完整性
- [ ] `uv run mini-agent` 成功启动 TUI
- [ ] 能输入多行消息
- [ ] LLM 流式输出实时显示（逐 token）
- [ ] Markdown 内容正确渲染（代码块、粗体等）
- [ ] 多轮对话上下文保持（LLM 记得之前说的）
- [ ] Ctrl+C 优雅退出
- [ ] 配置文件加载正确（优先级：CLI > env > project > user > defaults）

### 架构合规
- [ ] 目录结构与 spec.md 一致
- [ ] EventBus 已就位且至少 emit 了 UserMessageEvent
- [ ] Conversation 对象正确追加消息
- [ ] LLMProvider 接口与 spec 定义一致

---

## Phase 2 检查项

### 功能完整性
- [ ] 6 个工具全部注册到 ToolRegistry
- [ ] LLM 能正确发出 tool_calls（OpenAI function calling 格式解析正确）
- [ ] 工具结果正确回传给 LLM
- [ ] Agent Loop ReAct 循环正常：think → tool_call → observe → think → answer
- [ ] 多步工具链正常（≥3 步）
- [ ] 并行工具调用正常（LLM 返回多个 tool_calls 时）
- [ ] 循环上限生效（max_iterations 到达后停止）

### 各工具验证
- [ ] ReadFile: 正确读取文件，行号正确，offset/limit 生效
- [ ] WriteFile: 正确写入文件，创建不存在的文件
- [ ] EditFile: 正确替换文本，old_text 匹配正确
- [ ] Bash: 命令执行，timeout 生效，stderr 捕获
- [ ] Glob: 模式匹配正确，返回排序文件列表
- [ ] Grep: 正则搜索，上下文行，文件过滤

### TUI
- [ ] 工具调用显示名称和参数
- [ ] 执行中显示 spinner
- [ ] 工具结果正确渲染

---

## Phase 3 检查项

### 功能完整性
- [ ] PermissionManager 评估顺序正确（DENY → ALLOW → Session → Default）
- [ ] PathGuard 敏感目录拒绝生效
- [ ] 危险 bash 命令触发确认弹窗
- [ ] 用户选择 "always allow" 后同类操作不再弹窗
- [ ] Hook PRE_TOOL 能阻止工具执行
- [ ] Hook POST_TOOL 能观察工具结果

### 安全验证
- [ ] `rm -rf /` → 确认弹窗
- [ ] `sudo xxx` → 确认弹窗
- [ ] 读取 `~/.ssh/id_rsa` → 拒绝
- [ ] 读取 `~/.aws/credentials` → 拒绝
- [ ] 项目内文件正常读写 → 自动允许

---

## Phase 4 检查项

### 功能完整性
- [ ] ContextManager 正确跟踪 token 使用
- [ ] 达到 75% 阈值自动触发压缩
- [ ] 压缩后对话连贯性保持（LLM 不会丢失关键上下文）
- [ ] Session 可序列化/反序列化（JSON）
- [ ] 会话恢复后对话状态完整
- [ ] 跨会话记忆 CRUD 正常
- [ ] 记忆搜索返回相关结果

### 压缩策略验证
- [ ] Stage 1: 工具输出精简生效
- [ ] Stage 2: LLM 摘要生成质量合格
- [ ] Stage 3: 滑动窗口兜底正常

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
