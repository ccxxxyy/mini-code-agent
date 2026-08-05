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
- [x] SubAgent 在独立 asyncio Task 中运行（asyncio.create_task, test_spawn_parallel 验证）
- [x] spawn_parallel 多个 SubAgent 并行执行（test_parallel_faster_than_serial: 3 个 0.1s Agent 并行 <0.35s 完成）
- [x] 每个 SubAgent 有独立的 ToolRegistry 副本（clone + 白名单过滤, 父注册表不受影响, 单测验证）
- [x] SubAgentResult 正确收集（agent_id/task/output/tool_calls/tokens/worktree_path/error）
- [x] SubAgent 超时/取消正常（wait timeout 触发 cancel + Timed out 错误, 单测验证）

### Worktree
- [x] `git worktree add` 正确创建（真实 git 仓库集成测试）
- [x] SubAgent 在 worktree 目录工作（isolation="worktree" 时 working_dir 切换到 worktree 路径）
- [x] worktree 未提交变更保护（remove 拒绝 dirty worktree, force=True 强制, 单测验证）
- [x] merge_back 正常合并（--no-ff 合并, 集成测试验证文件出现在主仓库）
- [x] 冲突时正确报告（diff --diff-filter=U 检测冲突文件列表 + merge --abort 保持仓库干净）

### Agent Teams
- [x] Orchestrator 能分解任务（Planner LLM 分解, 真实 API E2E 验证）
- [x] 团队成员按角色分配（_match_member 角色子串匹配 + 首成员兜底, 单测验证）
- [x] 各成员可在独立 worktree 工作（TeamConfig.isolation="worktree" 传递给 spawn）
- [x] 协调正常运行（start: 分解→分配→并行 spawn→wait_all, E2E 验证）
- [x] 结果汇总正确（TeamRunReport.summary 含每步状态+输出摘要）

---

## Phase 7 检查项

### 测试覆盖
- [x] 核心模块全部有单测（17 个单测文件覆盖 agent_loop/tools/llm_providers/memory/permissions/hooks/events/config/models/skills/slash/mcp/subagent/planner/team）
- [x] 所有集成测试通过（agent_e2e 装配冒烟 + worktree 真实 git 仓库）
- [x] `uv run pytest` 全绿（183 个测试, 35s）

### 生产就绪
- [x] 已知 edge case 有处理（截断 JSON、损坏 session 文件、缺失技能文件、超时、脏 worktree、未知工具/命令）
- [x] 内存防护（token 缓存上限 4096 条 + 超长文本跳过缓存；工具输出/glob/grep 结果均有截断上限）
- [x] 并发安全（SubAgent 独立 registry 克隆 + 独立 Conversation + asyncio.Task 隔离，单测验证父注册表不受影响）
- [x] 错误消息对最终用户友好（401/402/429/5xx/连接/超时 → 中文可操作提示）
- [x] 配置验证错误给出清晰提示（启动缺 API key → 三种配置方式指引）

---

## Phase 8 检查项：评测框架

### 框架完整性
- [x] runner.py 能 headless 跑单个任务（`--task fix_syntax_error`）
- [x] runner.py 能批量跑全部（`--all`）
- [x] report.py 能生成 Markdown 表格（`--output benchmarks/README.md`）
- [x] 10 个任务涵盖 bugfix/feature/test/refactor/search 五个类别
- [x] 每个任务有可执行的验证命令（pytest / import / 文件检查）
- [x] CC 手动结果有模板可填

### 评测结果验证
- [x] 10/10 全部通过（两次全量运行确认稳定）
- [x] 结果 JSON 正确采集 success/tokens/tool_calls/cost/iterations/time
- [x] 报告表格数据与 JSON 一致

---

## Phase 9 检查项：/trace 机制透明度

### 功能完整性
- [x] /trace 开关（无参切换、on/off 显式）行为正确（E2E 验证三态）
- [x] 阶段切换实时显示（iter N old -> new）
- [x] 权限判定显示决策+依据（GRANTED 绿/DENIED 红 + rule/mode/path_guard 等 reason）
- [x] 工具生命周期显示（start 参数预览 + done 耗时 + OK/FAIL）
- [x] LLM 请求/响应元信息（消息数/工具数/token/是否含工具调用）
- [x] 轮次汇总（iterations/tools/tokens）
- [x] 关闭时零输出（enabled=False 短路，单测验证）

### 架构合规
- [x] TraceRenderer 是纯 EventBus 订阅者，AgentLoop 零侵入
- [x] PermissionManager 只加溯源属性，方法签名不变（183 个既有测试全过证明零破坏）
- [x] 10 个新测试（trace 9 + 权限事件 1），总计 193 个全过

---

## Phase 10 检查项：垂直场景定制

### 功能完整性
- [x] `/explain on` 激活教学模式，每次工具调用前确定性出现 Teach 面板（不依赖 LLM 遵从）
- [x] `/explain off` 关闭教学模式，面板消失，输出干净
- [x] Teach 面板含 Why this tool / Args / Params guide 三段，6 个内置工具各有专属文案
- [x] `/audit on` 开启审计日志，工具调用写入 `~/.mini-agent/audit.jsonl`
- [x] `/audit off` 关闭审计日志
- [x] 审计日志格式为 JSONL，每行含 ts/event/tool 等字段
- [x] 哈希链防篡改：篡改内容/删除行均被 `/audit verify` 检出（单测验证两种攻击）
- [x] 进程重启后链自动续接（从文件尾恢复 last_hash）
- [x] `/audit on` 跨重启持久（.audit_on 标记文件），直到显式 `/audit off`
- [x] 安全边界已文档化：tamper-evident 而非 tamper-proof（不防全链重算/发现依赖主动 verify）
- [x] `/skill list` 显示 teach-mode 和 offline-ollama 两个新 Skill
- [x] offline-ollama Skill 包含 Ollama 配置步骤和推荐模型

### 架构合规
- [x] 教学模式 = TeachRenderer（EventBus 订阅者，确定性输出）+ teach-mode Skill（辅助 LLM 推理解释），AgentLoop 零侵入
- [x] AuditLogger 复用 EventBus 订阅者模式（与 TraceRenderer 同范式）
- [x] 21 个新测试（audit 16 + teach 5），总计 235 个全过

---

## Phase 11 检查项：机制实验

### 功能完整性
- [x] LLMSummarizeOldest 摘要成功时输出含 "LLM summary" 标记
- [x] LLM 调用失败/空响应时回退提取式摘要，压缩链不中断
- [x] 消息数 ≤ KEEP_RECENT 时不调用 LLM（零浪费）
- [x] compression_ab.py 三臂可独立运行（--arm）、可跑单任务（--task）
- [x] model_mix.py 从 llm_profiles 读取强弱模型，--strong/--weak 可指定
- [x] 实验结果 JSON 落盘 experiments/results/

### 架构合规
- [x] LLMSummarizeOldest 实现 CompressionStrategy ABC，Compressor 策略列表即插即用
- [x] 摘要调用直连 LLM 不经过 AgentLoop（防递归）
- [x] 未接入默认压缩链（向后兼容）
- [x] 实验脚本复用 benchmarks 的任务/workspace/计价，不改 benchmarks 代码

### 实验结论产品化
- [x] planner_profile/worker_profile 配置字段 + MINI_AGENT_PLANNER/WORKER_PROFILE 环境变量
- [x] create_for_role 工厂：profile 命中用 profile，未配置/未知回退主模型（永不报错）
- [x] 9 个新测试（LLM 摘要 4 + 混编配置 5），总计 226 个全过

---

## Phase 12 检查项：多 Agent 命令入口

### 功能完整性
- [x] `/spawn <任务>` 派生单个 SubAgent，返回 agent_id
- [x] `/spawn -p <任务1> | <任务2>` 并行派生多个
- [x] `/spawn --isolated <任务>` 在 worktree 隔离执行
- [x] `/spawn list` 列出活跃 agent + 当前阶段
- [x] `/spawn wait [id]` 等待结果（单个或全部）
- [x] `/spawn cancel [id]` 取消（单个或全部）
- [x] `/team <任务>` Planner 分解 + 并行 SubAgent + 汇总报告
- [x] `/team --isolated <任务>` 团队成员 worktree 隔离
- [x] SubAgentSpawnEvent / SubAgentCompleteEvent 正确 emit

### 架构合规
- [x] Application 装配 SubAgentManager + WorktreeManager（之前只有 Python API，无终端入口）
- [x] /team 使用 create_for_role("planner") + create_for_role("worker") 完成强弱混编接线（roadmap 2.5）
- [x] 沿用 _make_xxx 工厂 + 子命令分支模式（与 /session /audit 一致）
- [x] 8 个新测试（spawn/team），总计 243 个全过

---

## Phase 13 检查项：SubAgent 进度面板

### 功能完整性
- [x] `/spawn wait` 阻塞期间显示实时表格（Agent/Task/Phase/Tools/Time 五列）
- [x] `/team` 执行期间显示各 worker 进度
- [x] 阶段实时更新且带颜色区分（thinking/tool_calling/terminated/error）
- [x] 工具调用数和耗时实时增长
- [x] 全部完成后面板自动收起（transient Live），命令结果正常显示
- [x] 无活跃 agent 时显示 "collecting results..."（wait 已 pop 但结果未返回的窗口期）
- [x] awaitable 异常时面板正常收起且异常透传

### 架构合规
- [x] active_snapshots() 公开接口——面板不触碰 SubAgentManager 私有成员
- [x] run_while 包裹模式——面板只在等待期间存在，无常驻订阅，天然避开 StreamRenderer 的 Live 冲突窗口（斜杠命令不经过 AgentLoop）
- [x] 7 个新测试（board），总计 250 个全过

### 真实运行缺陷修复（/team 六轮 E2E 迭代）
- [x] SubAgent 不再写 /tmp（prompt 平台信息 + 相对路径约束）
- [x] 熔断终止返回 success=False + error 标注（报告不再误报 SUCCESS）
- [x] 依赖步骤等前置批完成后执行（不再并行抢跑找不到文件空转熔断）
- [x] 依赖失败的步骤跳过并标注原因（不浪费 token）
- [x] 前置步骤产出注入依赖步骤 prompt（4000 字符）
- [x] Planner SIZE LIMIT（~15 工具调用/最多读 5 文件）+ SubAgent BUDGET 预算感知
- [x] NO INTERMEDIATE FILES + writes_files 工具白名单强制（非写步骤物理只读）
- [x] Planner 分解前注入真实项目结构扫描（不再套 web 模板）
- [x] 死循环签名改为 工具名+参数（修复"连续读 6 个不同文件被误杀"的护栏 bug）
- [x] 最终验证：/team 四步全 OK，su.md 真实生成，零中间文件，token 比首轮降 68%
- [x] 7 个新测试，总计 257 个全过

---

## Phase 14 检查项：LLM 自主派生 SubAgent

### 功能完整性
- [x] spawn_agents 工具注册到 ToolRegistry，/tools 显示 7 个内置工具
- [x] LLM 在 ReAct 循环中自主调用 spawn_agents 派生多个子代理并行执行
- [x] 子代理结果汇总为 ToolResult 回传 LLM，LLM 据此继续推理给出最终回答
- [x] 支持 isolated=true 参数（Git worktree 隔离）
- [x] 空任务列表返回 error_result（参数校验）
- [x] system prompt 包含 spawn_agents 使用指引

### 递归防护（双保险）
- [x] SubAgent clone registry 时显式 unregister("spawn_agents")——子代理物理上没有此工具（trace 可见 6 tools vs 主循环 7 tools）
- [x] SubAgent 的 ToolContext.subagent_manager=None——即使工具存在也执行不了
- [x] 真实 API 验证：要求子代理"再派生"时，子代理正确说明限制并直接用 read_file 完成任务

### 架构合规
- [x] ToolContext 加 subagent_manager 字段（TYPE_CHECKING 避循环导入）
- [x] app.py post-hoc mutation 注入（无需重排构造顺序）
- [x] SpawnAgentsTool 遵循 Tool ABC 模式（schema + execute），与其他 6 个工具走完全相同的权限/Hook/事件管道
- [x] 6 个新测试（spawn_agents_tool 5 + e2e 断言修正 1），总计 262 个全过
