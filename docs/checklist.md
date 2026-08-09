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

### Slash Commands（后续自动化测试已覆盖——test_slash_commands.py 等）
- [x] `/help` 列出所有命令
- [x] `/clear` 清空对话
- [x] `/status` 显示状态
- [x] `/model <name>` 切换模型
- [x] `/compact` 手动压缩
- [x] `/quit` 退出
- [x] 未知命令给出提示

### Skill 系统（后续自动化测试已覆盖——test_skills.py）
- [x] SKILL.md 正确解析（YAML front-matter + prompt body）
- [x] 技能激活后 system prompt 正确注入
- [x] 触发词自动匹配
- [x] 技能停用后 prompt 正确移除

### MCP（后续自动化测试已覆盖——test_mcp.py，P31 加 HTTP transport 测试）
- [x] stdio transport 连接正常
- [x] 工具发现正确
- [x] MCPToolAdapter 注册到 ToolRegistry
- [x] 通过 Agent 调用 MCP 工具正常
- [x] 服务器断连后优雅处理

### Anthropic Provider（未实际验证——代码就绪但从未连接真实 Claude API）
- [ ] 流式响应正常
- [ ] tool_use 格式正确
- [ ] thinking blocks 解析（如适用）
- [ ] token 计数合理
> 注：以上 4 项需要 Anthropic API key 才能验证。单元测试覆盖了消息格式转换，但端到端调用从未执行——待有 Claude API 访问权限时补验。

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

---

## Phase 15 检查项：会话自动保存

### 功能完整性
- [x] 每轮对话后自动保存（30s 节流，同一文件覆盖写幂等）
- [x] 斜杠命令后也触发（/model /clear 等改状态的命令不丢）
- [x] 正常退出（/exit、Ctrl+C、EOF）时 closed_cleanly=True + 强制保存
- [x] 硬杀进程跳过 finally → 磁盘留 closed_cleanly=False → 下次启动检出
- [x] 启动提示只针对：同项目目录 + 未干净关闭 + 非当前会话，取最近一个
- [x] 拒绝恢复后该会话被标记关闭，不再重复询问
- [x] 恢复成功后上下文完整（对话消息 + token 统计 + 工具层引用全部同步）

### 健壮性
- [x] 空会话（无消息）不落盘——不产生垃圾文件
- [x] 保存失败（OSError）静默吞掉，不打断对话，下轮重试
- [x] 旧版本 session 文件（无 closed_cleanly 字段）默认视为已关闭——升级不误报

### 架构合规
- [x] 复用 SessionStore.save 幂等覆盖特性，零新存储逻辑
- [x] _adopt_session 统一恢复路径（修复 /session load 的 ToolContext 过期引用既有缺陷）
- [x] ask_yes_no 与权限确认 confirm 分离（语义不同：普通询问 vs 安全确认）
- [x] 7 个新测试，总计 269 个全过

---

## Phase 16 检查项：/theme 主题切换

### 功能完整性
- [x] `/theme` 列出三套主题 + 标记当前
- [x] `/theme dark` 切换即时生效（提示符/工具行/trace/teach/board/确认面板全变色）
- [x] 持久化到 `~/.mini-agent/.theme`，重启保持
- [x] 三套主题色差明显（default 紫蓝 / dark 暖橙 / light GitHub 蓝）
- [x] 补全菜单文字颜色跟随主题（透明背景不加框）

### 架构合规
- [x] 6 个 UI 文件全部从 theme 对象取色，零硬编码
- [x] PROMPT_STYLE 从模块常量改为 create_prompt_style(theme) 函数
- [x] 运行时切换通过 prompt_session 重建刷新
- [x] 7 个新测试，总计 276 个全过

---

## Phase 17 检查项：工具并行执行

### 功能完整性
- [x] LLM 一次返回多个 tool_call 时并行执行（asyncio.gather）
- [x] 权限预检串行（确认弹窗不交错）
- [x] 单工具快速路径（不 gather，零开销）
- [x] 结果按原始 tool_call 顺序返回

### 安全性
- [x] AuditLogger 三个 handler 加 asyncio.Lock（并行写入不破坏 hash chain）
- [x] 权限被拒的工具返回错误且不执行
- [x] 取消后剩余工具不执行

### 架构合规
- [x] _run_tool_pipeline 加 skip_permission 参数（Phase 2 跳过已预检权限）
- [x] 5 个新测试（并行计时/单工具/未知工具/取消/顺序），总计 281 个全过

---

## Phase 18 检查项：双 Esc 中断流式输出

### 功能完整性
- [x] 流式输出期间快速按两次 Esc 触发优雅中断
- [x] 中断后部分响应保留在 conversation（LLM 可继续）
- [x] 回到输入框可继续对话
- [x] 单次 Esc 不触发（防误触）
- [x] 无 TTY 环境静默降级（不崩溃）

### 架构合规
- [x] EscWatcher 守护线程只在流式期间活跃，不和 prompt_toolkit 的 stdin 冲突
- [x] _think 循环通过 _cancelled 标志中断（与 Ctrl+C cancel 同一机制）
- [x] 5 个新测试，总计 286 个全过

---

## Phase 19 检查项：PRE_LLM / SESSION_END Hook 接线

### 功能完整性
- [x] PRE_LLM hook 在每次 LLM 调用前触发
- [x] PRE_LLM BLOCK 能力：hook 返回 BLOCK 时 LLM 不被调用，reason 作为响应返回
- [x] SESSION_END hook 在正常退出 finally 块触发
- [x] 内置 PRE_LLM hook 自动注入 PersistentMemory 到 system prompt（标记去重不重复追加）
- [x] 内置 SESSION_END hook 自动提取对话偏好写入 PersistentMemory（auto_extract 首次生效）

### 架构合规
- [x] PRE_LLM 接线在 LLMRequestEvent 之后、llm.stream() 之前
- [x] SESSION_END 在 finally 块中异常安全（try/except pass）
- [x] _register_builtin_hooks 闭包模式注册内置 hook
- [x] 4 个新测试，总计 290 个全过

---

## Phase 20 检查项：上下文溢写兜底

### 功能完整性
- [x] 压缩后仍超窗口时 ensure_fits 强制 SlidingWindow 截断
- [x] 截断目标 85%（留 15% 安全余量给 LLM 响应）
- [x] 截断后 api_messages 重建（不发旧的超限消息）
- [x] 无 context_manager 时不做检查（向后兼容）

### 架构合规
- [x] ensure_fits 复用已有 SlidingWindow 策略（零新压缩逻辑）
- [x] 预检位置在 PRE_LLM hook 之后、llm.stream() 之前（hook 可能修改 prompt 影响 token 数）
- [x] 2 个新测试，总计 292 个全过

---

## Phase 21 检查项：TOML 配置文件

### 功能完整性
- [x] 用户级 `~/.mini-agent/config.toml` 正确加载
- [x] 项目级 `.mini-agent/config.toml` 覆盖用户级
- [x] 环境变量覆盖 TOML（优先级高）
- [x] 部分配置（只设 [llm] model）不影响其他字段默认值
- [x] MCP 服务器 `[mcp.servers.<name>]` 正确解析为 MCPServerConfig
- [x] 顶级标量（theme/max_agent_iterations）正确合并
- [x] 未知字段静默忽略（向后兼容）

### 架构合规
- [x] Python 3.11 stdlib tomllib，零外部依赖
- [x] _apply_cli 泛化支持所有子配置
- [x] 优先级栈：defaults → user TOML → project TOML → .env → env → profiles → CLI
- [x] 6 个新测试，总计 298 个全过

---

## Phase 22 检查项：接口冻结 + 覆盖率门禁

### 接口冻结
- [x] CHANGELOG.md 列出 Tool/LLMProvider/HookFn/CompressionStrategy 四个 ABC 完整签名
- [x] 支撑类型（ToolSchema/StreamChunk/HookContext 等 14 个 dataclass）列入稳定接口
- [x] "冻结"含义明确定义（签名不变/可加可选参数/可加新方法/破坏性变更需 major bump）

### 覆盖率门禁
- [x] pytest-cov 集成，fail_under=80
- [x] 排除 TTY 交互层和 MCP 子进程层（CI 无法测试）
- [x] 当前覆盖率 81.62%，门禁通过
- [x] 版本升级到 v1.0.0

---

## Phase 23 检查项：Diff 预览 + Streaming 扩展点

### 功能完整性
- [x] edit_file 成功后显示整行背景色的彩色 diff（删除行深红底、新增行深绿底）
- [x] diff 只显示变更内容（跳过 ---/+++/@@ 头部，更干净）
- [x] 无换行符文件的 diff 行正确分离（不粘连）
- [x] 流式期间 LLM 开始生成工具调用参数时立即显示工具名（不等 JSON 组装完）
- [x] on_tool_start 不与 assembling 提示重复（已显示过的工具只补参数摘要）

### 架构合规
- [x] diff 通过 ToolResult.metadata 传递（不改 output——output 给 LLM 看，diff 给用户看）
- [x] on_tool_call_assembling 是可选回调（未接线时行为不变——向后兼容）
- [x] Rich Text.pad(width) 实现整行背景色（不依赖 ANSI 转义码）
- [x] 1 个新测试，总计 299 个全过

---

## Phase 24 检查项：文件变更汇总

### 功能完整性
- [x] 轮次结束后显示本轮新建/修改的文件清单
- [x] 新建文件 `+` 绿色标记、修改文件 `~` 黄色标记
- [x] 同一文件多次操作只显示一次（created 优先）
- [x] 工具执行失败不计入
- [x] 每轮开始重置（不累积跨轮）
- [x] 无变更时不显示（不打空标题）
- [x] delete_file 工具：删除文件红色 `-` 标记进入汇总，拒绝删除目录

### 架构合规
- [x] 集中跟踪在 agent_loop._record_file_change（不改每个工具）
- [x] 复用 write_file 已有的 metadata["existed"] 区分新建/覆写
- [x] last_turn_file_changes 属性暴露（与 last_turn_tokens 同模式）
- [x] 6 个新测试，总计 305 个全过

---

## Phase 25 检查项：上下文感知

### 功能完整性
- [x] 启动自动发现 AGENT.md / CLAUDE.md / .mini-agent/instructions.md（优先级递减，第一个命中即用）
- [x] 用户级 ~/.mini-agent/instructions.md 全局指令支持
- [x] 超长文件截断 8000 字符（防挤爆上下文）
- [x] 启动提示 `context: loaded <文件名>`
- [x] marker 去重（会话恢复/模型切换不重复注入）
- [x] [context] 配置段：文件名/优先级/用户指令路径/截断长度均可通过 config.toml 修改，不配置行为不变

### 架构合规
- [x] 独立模块 memory/project_context.py（纯函数，无状态）
- [x] 注入模式与记忆注入一致（marker 去重先例：--- Relevant memories ---）
- [x] ContextConfig dataclass 复用 P21 TOML 通用 _merge（零胶水代码）
- [x] 12 个新测试，总计 321 个全过
- [x] docs/config-guide.md 新建（三类文件区分 + 全清单 + 修改方法）

---

## Phase 26 检查项：对话分叉/回滚

### 功能完整性
- [x] /undo 回滚最后一轮（用户消息 + 之后全部 assistant/tool 消息）
- [x] /undo N 回滚多轮；轮数不足报错且对话不动
- [x] /fork 分叉新会话，原会话磁盘保留可 /session load 回去
- [x] /fork N 从 N 轮之前的状态分叉
- [x] 深拷贝隔离：改分支不影响原线
- [x] token 数和轮次计数在回滚后正确更新

### 架构合规
- [x] 复用现有基础设施：Role 扫描定轮次 + SessionStore 存盘 + _adopt_session 切换（零新增模块）
- [x] 10 个新测试，总计 331 个全过

---

## Phase 27 检查项：操作级撤销

### 功能完整性
- [x] /undo 撤销该轮新建的文件（删除）
- [x] /undo 还原该轮修改的文件（写回旧内容）
- [x] /undo 找回该轮删除的文件（从快照恢复）
- [x] 超过 30MB 的文件不快照，undo 时明确提示需手动恢复
- [x] 只保留最近 5 轮快照（自动清理）
- [x] 会话结束快照目录自动清空（零残留）
- [x] 恢复报告逐文件显示在 /undo 输出里

### 架构合规
- [x] 快照失败绝不阻断工具执行（try/except 包裹）
- [x] 磁盘存储零内存占用；快照时机在工具执行前（agent_loop 集中拦截）
- [x] 10 个新测试，总计 344 个全过

---

## Phase 28 检查项：工具链录制/回放

### 功能完整性
- [x] /record start 后所有成功工具调用被捕获，失败调用不录
- [x] /record stop 保存 JSON 并显示步数；cancel 丢弃
- [x] /replay 零 LLM 逐条重放，逐步进度显示，失败立即停止
- [x] 回放走完整权限管线（危险命令弹确认/hook 生效/快照进 undo）
- [x] 回放期间 suspended 防自录
- [x] 录制文件可手工编辑（JSON 明文）

### 架构合规
- [x] EventBus 订阅者模式（与 AuditLogger/TraceRenderer 同款——零侵入 agent_loop）
- [x] 回放复用 _execute_single_tool（不绕过任何安全层）
- [x] 10 个新测试，总计 354 个全过

---

## Phase 29 检查项：成本仪表盘

### 功能完整性
- [x] input/output token 分开计价（TokenUsage 拆分数据不再被丢弃）
- [x] 按模型分账（/model 切换、强弱混编 worker、SubAgent 均正确归属）
- [x] /cost 面板：每模型明细 + 总额 + 预算占比
- [x] /status 含 Cost 行
- [x] 预算警告：80% 黄 /100% 红，提醒不阻断
- [x] 未配置价格的模型只计 token 不算钱，且提示如何配置
- [x] 累计总账跨会话持久（cost_ledger.json），每轮幂等 flush
- [x] /cost reset 确认后清零；/cost turns 逐轮明细
- [x] total_budget 总账预算独立检查（同 80%/100% 阈值，文案区分会话/总账）
- [x] 表格宽度感知对齐（CJK 2格），表头行 + 请求数说明

### 架构合规
- [x] EventBus 订阅者模式（第 5 个纯订阅者：Trace/Teach/Audit/Recorder/Cost）
- [x] LLMResponseEvent 扩展字段带默认值（向后兼容，接口冻结不受影响）
- [x] [cost] 配置段复用 TOML 通用 _merge（零胶水）
- [x] 13 个新测试，总计 373 个全过

---

## Phase 30 检查项：LLM 记忆提取

### 功能完整性
- [x] LLM 结构化提取替代 regex（覆盖率从"只匹配 always/prefer/don't"升级为"LLM 理解对话语义"）
- [x] 三类提取：preference（用户偏好）/ convention（项目约定）/ fact（技术事实）
- [x] JSON 解析容错：markdown 围栏自动剥离、畸形 JSON 静默降级
- [x] 词重叠去重（60% 阈值）避免"换个说法重复记"
- [x] SESSION_END hook 修复（P19 遗留 bug 消除）

### 架构合规
- [x] 接口不变（maybe_extract 签名兼容）
- [x] LLM 调用失败绝不阻断会话退出（try/except + 空列表降级）
- [x] 9 个新测试（全面覆盖 LLM 响应变体），总计 391 个全过

---

## Phase 31 检查项：MCP HTTP Transport

### 功能完整性
- [x] HTTPTransport 实现 send（POST JSON-RPC）+ close（aclose httpx）
- [x] MCPManager 按 config.transport 选择 stdio/http 传输层
- [x] config.toml [mcp.servers.*] 的 url 和 transport 字段激活（P5 预留的插槽终于接通）
- [x] 启动自动连接 + 退出断连
- [x] HTTP headers 认证支持（config.toml headers = { Authorization = "Bearer ..." }）

### 架构合规
- [x] httpx 零新增依赖（已是核心依赖）
- [x] MCPTransport ABC 加 start() 不破坏冻结接口（默认空实现）
- [x] 5 个新测试，总计 396 个全过

---

## Phase 32 检查项：持久化任务系统 S12

### 功能完整性
- [x] 任务 CRUD（add/get/update/remove）+ ID 前缀匹配
- [x] 磁盘持久化（JSON 单文件，跨会话保留）
- [x] blockedBy 依赖追踪
- [x] done 解锁提示 + start 阻塞警告（不阻断，只提醒）
- [x] clear 批量清除已完成/失败任务
- [x] 列表按状态分组显示

### 架构合规
- [x] 与 PlanStep/team 分离（/todo = 用户手动管理，/team = LLM 自动执行）
- [x] TaskStore 仿 SessionStore 存盘模式
- [x] 16 个新测试（含 6 个 /todo 命令集成），总计 412 个全过

---

## Phase 33 检查项：PyPI 发布准备

### 功能完整性
- [x] pyproject.toml 包含 PyPI 发布所需的全部元数据
- [x] LICENSE 文件存在（MIT）
- [x] publish.yml 自动发布 workflow（tag 触发 + Trusted Publisher）
- [x] README 包含 pip install 安装方式
- [x] uv build 成功产出 wheel + sdist

---

## Phase 34 检查项：Windows 终端适配

### 功能完整性
- [x] CMD 旧代码页（cp936/cp437）下特殊字符不崩溃（UTF-8 加固 + replace 容错）
- [x] TERM=xterm 等无控制台环境下 ask_yes_no 不崩（input 兜底）
- [x] 流式长行换行不再首行重复（物理行感知预算）
- [x] 双 Esc 停止后不吞用户按键（线程 join）
- [x] legacy 控制台 /todo 标记降级 ASCII

### 架构合规
- [x] 全部修复不改变非 Windows 行为（platform/legacy_windows 条件分支）
- [x] 10 个新测试模拟 legacy 条件（无需真实 CMD），总计 425 个全过

### 实战验证补充（P34.3）
- [x] bash 子进程 GBK 输出正确解码（三级解码，中文 CMD 错误信息不乱码）
- [x] 全部 git 状态修改命令需用户确认（human-in-the-loop 硬闸门，13 断言矩阵测试）
- [x] Git Bash（mintty）直接运行不秒退（isatty 检测 → 朴素输入降级）
- [x] GBK 用户名/路径产生的孤立代理字符不再崩 API 请求（_sanitize_surrogates 出口兜底）
- [x] docs/terminal-guide.md 覆盖 Windows/macOS/Linux 各终端打开方法与排查表

---

## Phase 35 检查项：死循环诱导实验

### 实验完整性
- [x] 5 个诱导场景覆盖不同死循环模式（重复读/无限编辑运行/搜索不存在/逐词翻译/自我改进）
- [x] 2 个实验臂（tight=5 / normal=20）对比安全余量
- [x] 10 个结果 JSON 全部生成（experiments/results/deadlock_*.json）
- [x] 结果表、熔断矩阵、结论写入 experiments/README.md

### 发现验证
- [x] 迭代上限在 tight 臂 4/5 场景触发（正确生效）
- [x] same-tool-6x 在所有 10 次运行中 0 次触发（已记录为设计盲区）
- [x] self_referential/normal 跑满 20 轮 330K token（最危险模式已识别）
- [x] tech-notes §35 记录 3 条实验结论

---

## Phase 36 检查项：压缩-重读膨胀根治

### 功能完整性
- [x] >50K 字符工具结果溢写磁盘，对话只留预览（阈值可配，0 禁用）
- [x] 错误结果不溢写（错误信息保持完整可见）
- [x] 压缩后摘要含"已读文件清单"，LLM 不再重读
- [x] 二次压缩替换旧清单而非重复追加
- [x] SubAgent 同样受溢写保护（独立 cache + finally 清理）
- [x] 主会话正常退出时缓存清理

### 架构合规
- [x] 溢写挂在工具管线层（agent_loop），不侵入任何工具实现
- [x] frozen ToolResult 通过重建修改（与 DropToolResults 同模式）
- [x] 10 个新测试，总计 443 个全过（含 P36.3 补修 2 个）

### 实战验证补充（P36.3）
- [x] 熔断 v2 按轮统计——批量并行读 10 个文档不再误杀（v1 按调用次数曾误杀）
- [x] 任务锚点——单轮超窗强制截断后用户提问不丢失（曾致 LLM 反问"你要做什么"）
- [x] 语言跟随——中文提问全程中文回答（system prompt 语言规则）
- [x] 实测同一问题 token 从 50 万降到 17 万，最终正常输出完整回答

---

## Phase 37 检查项：Anthropic Prompt 缓存

- [x] 系统提示以 cache_control 内容块列表形式传入（非字符串）
- [x] 工具 schema 列表最后一个工具携带 cache_control
- [x] 最后一条用户消息内容被升级为块格式并携带 cache_control
- [x] tool_result 类型的用户消息（role=user, content=[tool_result block]）同样被标记
- [x] 空工具列表不崩溃
- [x] message_start 事件正确解析 cache_read/cache_creation 统计
- [x] 6 个新测试，总计 449 个全过

---

## Phase 38 检查项：流式工具执行

- [x] 工具调用在流式期间组装完成即提交执行（index 前进 + finish_reason 双信号）
- [x] 会弹确认框的工具不在流式期间执行（would_ask 预判 → 延迟到 _act 串行确认）
- [x] 结果顺序与 tool_calls 顺序一致（OBSERVE 阶段配对不乱）
- [x] streaming_tool_execution=false 完全回退旧行为
- [x] 取消时清理未完成任务（cancel + 孤儿任务兜底）
- [x] would_ask 无副作用不弹窗（危险命令 True / session grant 后 False / 项目内路径 False / 敏感路径 False）
- [x] 10 个新测试，总计 459 个全过

---

## Phase 39 检查项：@file 内联引用

- [x] @filepath 匹配到真实文件时自动内联内容（`[File: path]` + 代码块格式）
- [x] 不存在的文件原样保留（不报错）
- [x] 多个 @ref 同时展开
- [x] 超过 10KB 的文件内容自动截断
- [x] 子目录路径支持（@src/main.py）
- [x] Tab 补全：@ 后显示文件列表，子目录可钻入
- [x] .git/.venv/__pycache__ 等目录不出现在补全菜单
- [x] @ 后有空格时停止补全
- [x] 12 个新测试，总计 471 个全过

---

## Phase 40 检查项：权限规则文件

- [x] 用户级 ~/.mini-agent/permissions.toml 加载生效
- [x] 项目级 .mini-agent/permissions.toml 加载生效，与用户级合并
- [x] allow 规则让危险命令免确认（如 git push）
- [x] deny 规则无条件拒绝（DENY > ALLOW > 内置默认）
- [x] PATH deny 规则对项目内路径同样生效（短路盲区已修复）
- [x] would_ask 与 deny 规则一致（不弹窗直接拒）
- [x] 文件缺失/格式错误不影响启动
- [x] /trace 显示规则来源（rule:pattern）
- [x] 9 个新测试，总计 480 个全过

---

## Phase 41 检查项：OS 级沙箱

- [x] Linux bwrap 命令格式正确（只读根 + 可写白名单 + 禁网 + proc/dev）
- [x] macOS Seatbelt SBPL profile 正确（deny default + 选择性 file-write + 网络控制）
- [x] create_sandbox() 按平台返回正确实现（Linux/Darwin/Windows）
- [x] bwrap/sandbox-exec 不可用时 available() 返回 False（静默退回正则拦截）
- [x] BashTool 默认无沙箱；注入后命令被 wrap
- [x] sandbox_auto_allow 让危险命令免确认
- [x] 显式 deny 规则不被沙箱绕过
- [x] Windows 无内核沙箱——保持现有正则拦截（不崩不报错）
- [x] 16 个新测试，总计 496 个全过

---

## Phase 42 检查项：上下文窗口 API 探测

- [x] GET {base_url}/models/{model} 探测成功时 context_window 返回探测值
- [x] 递归提取 5 种字段名（context_window/context_length/max_context_length/max_model_len/max_input_tokens），任意嵌套深度
- [x] 探测失败（网络错误/404/无效 JSON/字段缺失）静默回退硬编码表 → 128k 默认
- [x] 每实例只探测一次（成败皆然），10 秒独立超时
- [x] prepare() 预热：app.run() 启动时 + /model 切换后（两条路径）+ stream() 入口兜底
- [x] 基类 prepare() 默认无操作——Anthropic/Mock Provider 零改动
- [x] 真实 API 实测：阿里云 MaaS 三个模型均探测到 129024（extra_info.default_envs.max_input_tokens 深层嵌套）
- [x] 8 个新测试，总计 504 个全过
