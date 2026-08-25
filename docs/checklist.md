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
- [x] 危险 bash 命令触发确认弹窗（28 条正则，含内联解释器 cmd /c 在内 + 删除类任意形态，即使 allow 模式也确认）
- [x] 敏感文件经 bash 通道读取触发确认（`type`/`cat`/`Get-Content .env` 弹确认，绕过 read_file 的洞已堵）
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
- [x] 压缩后对话连贯性保持（SummarizeOldest token 驱动保留窗口 ≥10K tokens 且 ≥5 条，硬顶 40K + 提取式摘要保留角色和关键内容）
- [x] Session 可序列化/反序列化（JSON，含 ToolCall/ToolResult 完整往返，6 个单测覆盖）
- [x] 会话恢复后对话状态完整（system_prompt + messages + metadata 全部还原）
- [x] 跨会话记忆 CRUD 正常（项目级 + 用户级双层存储，add/load/save/search）
- [x] 记忆搜索返回相关结果（关键词 + 标签双通道匹配，跨层搜索）

### 压缩策略验证
- [x] Stage 1: 工具输出精简生效（>200 字符截断 + 行数/字符数摘要，单测验证短输出跳过）
- [x] Stage 2: 提取式摘要生效（token 驱动保留窗口 P150 + 旧消息按 role 摘要，单测验证消息数不足时跳过）
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
- [x] 审计日志格式为 JSONL，每行含 ts/event/tool 等字段；permission 事件含 matched_rule（P75 接入）
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
- [x] 消息数 ≤ MIN_KEEP_MESSAGES 时不调用 LLM（零浪费）
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
- [x] `background=true` 后台派生立即返回,完成后经 mailbox 通知 main、终端提示(SubAgentCompleteEvent 订阅)
- [x] `/spawn --background <任务>` 命令入口——后台派发,完成后结果自动投递到主对话（无需 `/spawn wait`）
- [x] 后台 agent 结果自动投递——`Mailbox.has_pending()` 无锁只读查询 + `Terminal.interrupt_input()` 中断输入等待 + `_BG_INTERRUPT` 哨兵 + `_handle_background_delivery()` while-drain 循环 + `_run_agent_and_report()` 处理 mailbox 结果；3 个新 has_pending 测试（test_mailbox.py）
- [x] 用户输入行醒目化——Theme 新增 `user_input` 亮浅蓝字段（default `#5fd7ff`/dark `#7dcfff`/light 白底可读蓝 `#0969da`）；`create_prompt_style()` 根样式输入文字 bold 亮浅蓝；`get_user_input()` 输入行上下 `_input_rule()` 同色横线（`_BG_INTERRUPT` 中断不打下边线）
- [x] 确认弹窗输入行防并发输出打断——`Terminal._prompt_protected()` 把 `confirm`/`ask_yes_no`/`ask_structured` 的 `prompt_async` 包进 `patch_stdout(raw=True)`，并发输出重定向到提示行上方；proxy 建不出时退回裸 prompt；4 个新测试（test_windows_rendering.py）
- [x] 权限模式矩阵——`PermissionMode` 枚举（default/accept-edits/plan/bypass）嵌入 `PermissionManager` 命令/路径管道和 `would_ask()`；deny 规则、敏感路径、敏感文件命令（`type .env` 类）所有模式下有效（bypass 也拦）；`/mode` 运行时切换（bypass 附警告，plan 同步系统提示词）；`/plan`、`exit_plan_mode` 经 `Application.set_permission_mode()` 联动；`[security] approval_mode` 设启动模式（非法值回退 default，`enable_plan_mode` 兼容）
- [x] exit_plan_mode 用户审批门——LLM 不能自行解除只读限制：弹 yes/no 由用户裁决，拒绝保持 plan 模式，无 UI 回调拒绝退出（安全默认）；流式执行延迟该工具（审批弹窗不与流式渲染交错）；22 个新测试（test_permission_modes.py + test_process_tools.py）
- [x] plan 只读覆盖 bash 通道——`WRITE_COMMAND_PATTERNS` 写形态命令（重定向到真实文件/mkdir/copy/move/del 等）plan 下直接拒绝；`>nul`/`>/dev/null`/`2>&1` 丢弃型重定向不误伤
- [x] plan 下 spawn_agents 有门放行/无门禁用——权限栈传播后子 agent 携带父级 PLAN 模式（写在权限层被拒），可派研究 agent；无权限栈传播的旧式嵌入场景仍禁用
- [x] 工具类别税制——`ToolCategory`（read/write/execute/external）声明在每个 Tool 类上（默认 EXTERNAL 保守），统一 5 份独立列表（`_WRITE_TOOLS`×2/路由列表/would_ask 列表/schema 过滤）；矩阵新单元：plan×WRITE 拒绝（覆盖无路径参数的 install_skill）、plan×EXTERNAL 拒绝（MCP）、bypass×EXTERNAL 放行；类别门用 `pm.mode` 而非 loop 标志（子 agent 传播生效关键）；20 个内置工具类别快照测试
- [x] 子 agent 权限栈传播——`ChildPermissionManager` 共享父级规则/授权/写文件集（引用共享，/deny /mode 实时生效），mode 为委托父级的 property，confirm 恒 None（需弹窗处安全拒绝）；`SubAgentManager.spawn()` 传子视图；`has_permission_gate` 属性
- [x] 对话框工具不流式抢跑——Tool ABC `opens_dialog` 属性（ask_user/exit_plan_mode），流式延迟按属性判定（实测 ask_user 弹窗被流淹没后修复）
- [x] 无头熔断——`no_ui:default_deny` 纳入确认拒绝熔断（有门子 agent 被拒后不再无限找绕路；策略拒绝 rule:/mode: 仍中性）
- [x] 规则来源进拒绝理由——`rule:<scope>:<pattern> (来源)`（圆括号避 Rich 标记；/deny 会话规则/--save/config/permissions.toml），LLM 不再为内存规则翻配置文件，scope 使报告能给出可照抄的移除命令
- [x] deny 规则匹配包装与串联命令——解包 `cmd /c`/`cmd /k`/`powershell -Command`/`sh -c` 前缀 + 抹引号后逐 `&;|` 段匹配（`cmd /c "ping x"` 曾绕过 `ping*` 规则仅靠危险命令层兜底）；allow 规则不解包（扩大 deny 收紧、扩大 allow 放松）；引号内数据不误拒；**边界已文档化**：解包是纵深防御非围墙，深度混淆（转义/变量间接/base64）由危险命令确认层与 OS 沙箱兜底
- [x] trace 动态字段全转义——路径/理由/参数/用户文字过 `rich.markup.escape`（实测含 `[/...]` 的理由曾致 MarkupError 崩溃刷屏）
- [x] 写后执行检测补裸调用——段首 token 查写文件集 + call/start 形态（实测子 agent 写 run_ping.bat 裸执行绕过 deny 规则）；读取写过的文件（type x.bat）不误触发
- [x] 子 agent 熔断报告带原因与遗留——`confirm_denied` 早停时 error 含**本轮全部去重拒绝原因（根因在前，AgentState.denial_reasons）**（防父级盲目重派或误诊）+ 本次创建文件清单（熔断即停无清理机会，列出而非自动删）；rule 拒绝附带可照抄的移除命令（`/deny remove <scope> "<pattern>"` 完整代入）与"对所有 agent 生效"事实（防父级编造命令或提议代跑——占位符写法实测被错代入）
- [x] 模式可观测——`PermissionModeChangedEvent` + trace `mode` 行 + `/status` 显示 Permission mode + 底部工具栏始终显示 `mode: xxx`；6 个新测试
- [x] 权限拒绝消息带原因——`_denied_message()` 把 `last_decision_reason` 和可读提示拼进工具错误（实测：光秃 Permission denied 让 LLM 烧 5 万 token 排查不存在的配置）
- [x] `inherit_context=true` / `/spawn --fork` 摘要式上下文 fork——父对话 LLM 摘要注入子 agent system prompt
- [x] ContextSummaryStartEvent / ContextSummaryDoneEvent 正确 emit(摘要开始/完成,含耗时和字符数)
- [x] 摘要期间终端提示"Summarizing conversation for context fork..." + `/trace on` 显示 `ctx` 行(不再零输出)
- [x] `background=true + inherit_context=true` 非阻塞——摘要+spawn 整体后台 task,execute() 毫秒级返回(实测 13ms)

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
- [x] spawn_agents 工具注册到 ToolRegistry，/tools 显示 7 个内置工具（当前 12 个）
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
- [x] @-include 递归引用：指令文件中整行 `@./path` / `@~/path` 展开为引用文件内容，深度 5（`max_include_depth` 可配，0 禁用），相对路径随引用方目录解析，循环引用/缺失文件注释降级，展开后整体截断；行内 `@./` 不误触；用户级指令同样支持

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
- [x] 缓存 token 差异化计费：pricing 支持 `cache_read`/`cache_creation` 键（未配退回 input 价），避免缓存命中时成本虚高（P75 接入）
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
- [x] 任务 CRUD（add/get/update/remove）+ ID 前缀匹配 + 歧义前缀检测（AmbiguousTaskError）+ 最小唯一前缀显示（min_unique_prefix）
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
- [x] 缓存统计经 LLMResponseEvent 传递到 CostTracker 差异化计费（P75 接入）
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

---

## Phase 43 检查项：Token 计数精度提升

- [x] CJK 感知估算：CJK 字符 1 token/字 + 其余 4 字符/token（7 个 Unicode 区间：汉字/扩展A/假名/谚文/全角/标点/兼容）
- [x] 纯英文估算行为不变（len//4）
- [x] API usage 锚点：record_api_usage() 锚定权威总量，update_total() 只对锚点后新消息估算
- [x] 锚点失效安全：压缩/undo 重排历史后对象身份检查自动失效，回退全量估算
- [x] 全 0 usage（供应商没返回）不建锚点
- [x] total_tokens 缺失时由 prompt + completion 计算（Anthropic 风格）
- [x] 修复：assistant 消息 token_count 存 completion_tokens 而非 total_tokens（消除对话重复计算 N 遍）
- [x] 修复：assemble_response usage 按字段合并（Anthropic 拆分事件不丢 prompt 计数）
- [x] 真实 API 实测校准：中文估算从 -56% 低估（危险方向）修正为 +76% 高估（安全方向），混合文本 +12%
- [x] 11 个新测试（CJK 估算 5 / 锚点 5 / 合并 1），总计 515 个全过

---

## Phase 44 检查项：max_tokens 恢复

- [x] finish_reason == "length" 触发翻倍重试（4096 → 8192 → 16384 → 32768）
- [x] 最多 3 次重试，仍截断保留最后一次结果（不丢弃）
- [x] 正常结束（stop/tool_calls）不重试
- [x] 用户取消（Esc）不重试
- [x] 重试前取消截断尝试中流式提交的工具任务（防半截 JSON 参数执行）
- [x] OpenAI/Anthropic 两家 Provider 的 stream() 都支持 max_tokens kwargs 覆盖
- [x] Anthropic stop_reason="max_tokens" 归一化为 "length"
- [x] 3 个新测试 + 1 个映射断言，总计 518 个全过
- [x] bash 副作用截断重试双执行修复：已 eager 完成的工具结果按 `(name, args_json)` 签名缓存（`_eager_completed`），重试产出相同签名时复用结果不重跑；不需命令意图分类，不牺牲流式延迟，WRITE 类工具仍走延迟路径（category gate 在前）；3 个新测试覆盖同签名复用 / 不同签名不命中 / WRITE 类不进缓存回归

---

## Phase 45 检查项：Coordinator 模式

- [x] `/team --coordinator` 正确解析 flag 并传入 TeamConfig 和 Planner
- [x] Planner prompt 包含 "COORDINATOR" 和 "cannot directly read, write" 指令
- [x] coordinator 模式下 max_steps 放宽到至少 8（已 ≥8 则不降低）
- [x] 项目扫描从 2 级/80 行加深到 3 级/120 行
- [x] 非 coordinator 模式行为不变（回归安全）
- [x] Workers 保持完整工具集不受影响
- [x] 3 个新测试，总计 521 个全过

---

## Phase 46 检查项：Pydantic Schema 生成

- [x] 7/8 工具定义 `ParamsModel(BaseModel)`，`_schema_from_model()` 自动生成 ToolSchema
- [x] BashTool 保留手写 schema（向后兼容验证）
- [x] `validate_args()` Pydantic 路径支持类型自动转换（字符串→int）
- [x] `pydantic>=2.0` 加入主依赖
- [x] 17 个新测试，总计 543 个全过

---

## Phase 47 检查项：Pydantic Schema 全面增强

- [x] `_resolve_refs()` 递归解引用 `$ref/$defs`，去除 `title` 噪声，`seen` 防循环
- [x] `ToolSchema.raw_parameters` 字段：Pydantic 路径直通完整 JSON Schema
- [x] `to_json_schema()` 双路径：`raw_parameters` 优先直通 / ToolParameter 后备（含 default 输出）
- [x] `str | None`（anyOf）完整传递
- [x] `list[str]`（array + items）完整传递
- [x] 嵌套 Pydantic 模型（$ref 解引用内联）
- [x] `Field(ge=0, le=100)` 约束（minimum/maximum/minLength/maxLength）
- [x] `Literal["a","b"]`（enum）、`dict[str, int]`（additionalProperties）
- [x] `default` 值出现在 JSON schema 输出中
- [x] 循环引用防护（保留原始 $ref 不死循环）
- [x] BashTool / MCP adapter 无需改动，后备路径正常工作
- [x] 改写 7 个旧测试 + 新增 10 个测试，总计 544 个全过

---

## Phase 48 检查项：Agent Type Definition

- [x] `AgentTypeDefinition` frozen dataclass 定义：name/system_prompt/allowed_tools/max_iterations/description
- [x] 4 种内置类型：explore（只读搜索）、plan（只读规划）、worker（全工具）、verify（PASS/FAIL）
- [x] explore/plan/verify 工具白名单仅含 read_file/glob/grep/bash
- [x] worker 的 allowed_tools 为 None（全部工具）
- [x] verify 迭代上限（20）< worker（50）
- [x] `_intersect_tools` 正确处理 4 种组合（both None / one None / both set）
- [x] `SubAgent.__init__` agent_type 参数切换 prompt + 工具过滤 + config 覆盖
- [x] `SubAgentManager.spawn/spawn_parallel` 名称解析 + 透传
- [x] `SpawnAgentsTool` 新增 agent_type 字段，无效类型名返回错误
- [x] `/spawn --type <name>` 命令行解析
- [x] 向后兼容：不指定 agent_type 时行为不变
- [x] 15 个新测试（test_agent_types.py 11 个 + test_subagent.py 4 个），总计 559 个全过

---

## Phase 49 检查项：Plan 模式只读

- [x] `_WRITE_TOOLS` 定义：write_file/edit_file/delete_file（不含 bash）
- [x] `AgentLoop.plan_mode` 运行时切换开关
- [x] `_think()` plan_mode 时从 schema 列表过滤写工具（LLM 看不到）
- [x] `_act()` plan_mode 时写工具调用返回 DENIED（双保险）
- [x] 流式工具执行延迟写工具到 `_act()` 拦截
- [x] `/plan [on|off]` 命令注册 + system prompt 注入/移除
- [x] plan_mode=False 时行为完全不变（回归安全）
- [x] `app.py` 初始化时读取 `config.enable_plan_mode` 赋给 `agent_loop.plan_mode`（P75 接入，默认 False）
- [x] 3 个新测试，总计 562 个全过

---

## Phase 50 检查项：Hook 事件类型扩充

- [x] HookStage 11 个值：STARTUP/SHUTDOWN/SESSION_START/SESSION_END/USER_INPUT/TURN_START/TURN_END/PRE_LLM/POST_LLM/PRE_TOOL/POST_TOOL
- [x] 全部 11 个实际触发（不再有定义了但从未触发的枚举值）
- [x] TURN_START/TURN_END 在 agent_loop.run() 头尾触发，metadata 完整
- [x] POST_LLM 在 assemble_response 后触发（观察式，BLOCK 无效果）
- [x] STARTUP/SESSION_START/SHUTDOWN 在 app.run() 生命周期触发
- [x] USER_INPUT 支持 BLOCK 拦截输入（显示 reason 跳过该轮）
- [x] 全部触发 try/except 包裹（hook 异常不破坏主流程）
- [x] 触发顺序验证：turn_start → pre_llm → turn_end
- [x] 7 个新测试，总计 569 个全过

---

## Phase 51 检查项：工具搜索/延迟加载

- [x] `MCPServerConfig.loading` 字段：`"eager"` / `"dispatch"`
- [x] dispatch 模式工具不注册到 ToolRegistry（shadow catalog 存储）
- [x] `search_tools(query)` 按 name/description 模糊搜索，大小写不敏感
- [x] `list_dispatch_tools()` 列出全部 dispatch 工具概要
- [x] `tool_search` 新内置工具：LLM 搜索 dispatch 工具
- [x] `mcp_call` 新内置工具：LLM 调用 dispatch 工具
- [x] `ToolContext.mcp_manager` 注入
- [x] 12 个内置工具：read_file、write_file、edit_file、delete_file、bash、glob、grep、spawn_agents、send_message、wait_message、tool_search、mcp_call
- [x] eager 模式行为完全不变（向后兼容）
- [x] 13 个新测试（test_tool_search.py），总计 582 个全过

---

## Phase 52 检查项：选择性记忆召回

- [x] `MemoryConfig.recall_threshold`（默认 10）/ `recall_top_k`（默认 5）
- [x] 记忆 ≤ threshold 时行为完全不变（全部注入，零额外 LLM 调用）
- [x] 记忆 > threshold 时轻量 LLM 调用挑选 ≤ top_k 条
- [x] 召回 prompt 只发 `id + content 前 50 字符`（省 token）+ 用户消息截断 500 字符
- [x] 按 LLM 返回顺序注入（保持相关性排序）
- [x] fail-safe：llm=None / 异常 / 解析失败 / 非 list JSON → 回退 `entries[:10]`
- [x] 幻觉 ID 静默忽略
- [x] LLM 返回 `[]`（无相关记忆）时不注入
- [x] 13 个新测试（test_memory_recall.py），总计 595 个全过

---

## Phase 53 检查项：记忆合并

- [x] `MemoryConfig.consolidation_threshold`（默认 20，可配置）
- [x] 记忆 ≤ threshold 时不触发合并（零额外 LLM 调用）
- [x] LLM 识别语义相关组（词重叠去重抓不住的"喜欢 tabs"vs"讨厌 spaces"场景）
- [x] 合并条目保留组内最新 created_at
- [x] tags 并集（保序去重），source="extracted"
- [x] 未合并条目原样保留
- [x] 幻觉 ID 过滤 / 单 ID 组忽略 / 跨组重复 ID 只处理首组
- [x] fail-safe：任何失败静默 no-op（合并绝不破坏现有记忆）
- [x] `/memory consolidate` 手动触发（≥2 条即可）
- [x] 自动触发点：SESSION_END 记忆提取后
- [x] 16 个新测试（test_memory_consolidation.py），总计 611 个全过

---

## Phase 54 检查项：Worktree 完善

- [x] `create()` 自动符号链接 node_modules/.venv/vendor（存在才链）
- [x] Windows 无符号链接权限时静默跳过（不阻断 worktree 创建）
- [x] `cleanup_stale(max_age_days)` 清理超龄的干净 worktree + 删除对应分支
- [x] 脏 worktree 不清理（未提交工作永不丢失）
- [x] 新 worktree 不清理（mtime 检查）
- [x] max_age_days=0 禁用清理
- [x] 单个 worktree 清理失败不影响其他
- [x] `SecurityConfig.worktree_max_age_days = 7` 可配置
- [x] app 启动时自动清理（失败不阻断启动）
- [x] `has_uncommitted_changes()` 变更检测
- [x] `/spawn wait` 结果显示 worktree 路径 + git merge 提示
- [x] 6 个新测试（test_worktree.py），总计 616 个全过（1 skip）

---

## Phase 55 检查项：Skill 安装命令

- [x] `/skill install <local_path>` 安装本地 skill（copytree + 验证 SKILL.md + name）
- [x] `/skill install <git_url>` 安装远程 skill（git clone --depth 1 + 验证）
- [x] 验证失败自动清理已复制/克隆的目录
- [x] 目标已存在时拒绝覆盖
- [x] `/skill uninstall <name>` 按 SKILL.md 中的 name 匹配删除
- [x] 卸载同时从内存注册表移除
- [x] 5 个新测试（test_skills.py），总计 621 个全过

---

## Phase 56 检查项：Skill 热重载

- [x] `load_all()` 先清除再扫描（磁盘删除的 skill 不再残留）
- [x] `reload(conversation)` 剥离旧 prompt → 重载 → 注入新 prompt
- [x] 活跃 skill 内容更新后 reload 对话中 prompt 自动更新
- [x] 磁盘删除的活跃 skill 报告为 lost
- [x] `/skill reload` 子命令
- [x] 5 个新测试（test_skills.py），总计 626 个全过

---

## Phase 57 检查项：远程/浏览器模式

- [x] `websockets>=12.0` 可选依赖（`[remote]` 组），终端用户不受影响
- [x] `--remote` / `--port` / `--host` / `--remote-token` CLI 参数
- [x] WebSocket 服务器 + HTTP 服务器（UI + `/cancel` + `/permission` 端点）
- [x] NDJSON 协议 12 种服务端事件 + 2 种 WS 客户端消息
- [x] 多客户端支持（`self._clients: set` 广播），`_ws_send()` 广播给所有客户端
- [x] 权限确认通过 HTTP POST + `call_soon_threadsafe`（绕过 WS 阻塞）
- [x] Stop 通过 HTTP POST `/cancel`（独立线程即时生效）
- [x] 浏览器 UI：深色主题、流式渲染、Markdown（h1-h4/列表/表格/链接+裸URL/图片）、工具调用、权限按钮（点击反馈）、Thinking 指示器、自动重连
- [x] `RemoteTerminalAdapter` 拦截 show_info/show_error/show_file_changes，内部异常过滤
- [x] `StreamChunk.thinking` + OpenAI/Anthropic Provider 捕获 reasoning/thinking
- [x] 刷新时 `_replay_history()` 回放对话历史
- [x] websockets 未安装时优雅报错
- [x] 21 个新测试（test_remote.py），总计 651 个全过

## Phase 58 检查项：Mailbox 跨 Agent 通信

- [x] `core/mailbox.py` — 文件式 JSON 收件箱，register/unregister/send/drain/has_pending/peers，单事件循环内同步读写原子无需文件锁
- [x] register 总是重置收件箱——上一会话残留消息不会被投递
- [x] `send_message` 工具注册（默认 enabled_tools），收件人未注册报错并列出已知 Agent
- [x] `wait_message` 工具注册，阻塞轮询直到消息到达或超时（上限 600s），超时是信息不是错误
- [x] AgentLoop 每轮 THINK 前 `_deliver_mail()` drain 收件箱注入 USER 消息
- [x] SubAgent：构造注册收件箱 + MAILBOX_NOTICE（自身 id / 同伴 id + 任务摘要 / 精确 id 告诫 / wait_message 指引 / main 降级），run() 结束注销
- [x] `spawn_parallel` 预生成 id，兄弟 Agent prompt 中互见（id + 任务摘要）
- [x] spawn_agents 描述明示阻塞语义："并发任务必须一次调用传入"
- [x] read-only agent 类型白名单含 send_message / wait_message（收发不算写文件）
- [x] app.py 注册 'main' 收件箱，主循环与 ToolContext 注入 mailbox
- [x] 真实 LLM 四类拓扑验证通过：1→1、2→1 汇聚、1→2 判别寻址、1↔1 五轮乒乓（零死锁/丢消息/幻觉 id）
- [x] 20 个新测试（test_mailbox.py 18 + test_mailbox_e2e.py 2），总计 671 个全过

## Phase 58.4 检查项：Mailbox 增强

- [x] `to='*'` 广播——排除发送者、返回收件人列表、空团队报错
- [x] `type=request` 自动分配 request_id 并在工具输出回传；`type=response` 缺 request_id 报错；非法 type 报错列出合法值
- [x] approve 表态字段贯通（send → 落盘 → 投递前缀 approve=true/false）
- [x] 投递前缀按类型区分：[Message ...] / [Request ... request_id=x] / [Response ... request_id=x approve=y]
- [x] 名字寻址：register 别名、resolve id/名字双解析、别名随 unregister 失效、describe_peers 显示 "name (id)"
- [x] spawn_agents `names` 参数校验：长度匹配、唯一、禁 'main'/'*'
- [x] MAILBOX_NOTICE 自身标签带名字，同伴列表 'name' (id xxx, task: ...)
- [x] 审计留痕：drain 标记已读留盘、unregister 保留文件、reset_all 会话启动清理
- [x] 无锁架构边界保持成立并文档化（单进程 asyncio；6.4 前置为文件锁+唤醒）
- [x] 13 个新测试，总计 684 个全过，覆盖率 80.85%

## 会话自动清理检查项（comparison 9.1）

- [x] `SessionStore.cleanup_stale(max_age_days)` 删除超龄且已正常关闭的会话
- [x] 未正常关闭（`closed_cleanly=False`）的会话跳过——崩溃恢复保留
- [x] `MemoryConfig.session_cleanup_days = 30`，0 禁用
- [x] `app.py` 启动顺序：worktree 清理 → 会话清理 → 崩溃恢复
- [x] 4 个测试：过期删除 / 未正常关闭跳过 / 0 禁用 / 空目录
- [x] config-guide 补 `session_cleanup_days` 配置说明
- [x] comparison 9.1 标记 ✅ + 优先级表更新

## Hook 拒绝工具执行检查项（comparison 7.2）

- [x] `[[hooks]]` TOML 声明式规则：tool（fnmatch）+ arg（限定参数）+ contains（子串）+ reason
- [x] 命中即 BLOCK：工具不执行，LLM 收到 "Blocked by hook: <reason>"
- [x] 非法条目（非表 / 不支持的 event / reject=false）告警跳过，不阻断启动
- [x] 无 reason 时给默认原因（含工具名）
- [x] `AgentConfig.hooks` 经 loader 顶层 setattr 自动合并，零 loader 改动
- [x] app.py 启动注册并提示数量
- [x] 11 个测试含 AgentLoop 端到端拦截 + regex 三例（含非法正则跳过）
- [x] comparison 7.2 勘误陈旧描述 + 标记 ✅ + 优先级表更新
- [x] config-guide 补 [[hooks]] 配置段（含 TOML 顶级键位置警告）

## HookAction.CONFIRM 接入检查项

- [x] `[[hooks]]` 规则新增 `action` 字段：`"block"`（默认）/ `"confirm"`，非法值告警跳过
- [x] 命中 confirm 规则弹 y/a/n 确认框：y 放行一次 / a 本会话同 (工具, 原因) 不再问 / n 拒绝
- [x] 拒绝时 LLM 收到 "Denied by user: <reason>"（工具不执行）
- [x] 裁决在 `agent_loop._resolve_hook_confirm`：app 注入 terminal.confirm（复用权限确认弹窗）；hook 层不持有 UI 引用
- [x] fail-safe：无 confirm 回调（脚本/CI/子 Agent）时安全拒绝
- [x] 确认弹窗加 asyncio.Lock：并行工具执行时不交错
- [x] 流式工具执行经 `HookManager.would_confirm` 预判：会弹窗的延迟到 _act（弹窗不与流式渲染交错）
- [x] 代码注册的 hook 返回 CONFIRM 走同一裁决路径（HookManager.run 短路上交语义不变）
- [x] 9 个新测试（解析/预判/短路/管道端到端 y/n/always/无回调），876 个全过
- [x] 真实 LLM 全管道验证（JSON 取证）：y 放行 / n 拒绝且 LLM 正确收尾 / a 两次写入只问一次
- [x] 文档同步：config-guide、config.toml.example、todo-code-quality #7 标 ✅、tech-notes、capabilities、comparison 7.2、CHANGELOG

## 全局事件监听插件检查项

- [x] `extensions/event_listeners.py`：从 `listener_dirs` 配置目录加载 *.py 插件（下划线开头跳过）
- [x] 插件契约：`register(bus)`（完全控制，优先）或 `on_event(event)`（同步/异步均可，自动 on_any 全局监听）
- [x] 异常隔离：插件导入失败/register 失败/handler 异常都告警跳过，不影响 Agent 主流程
- [x] `EventBus.emit` 记录 handler 异常日志（gather return_exceptions 后逐个 warning）；补充 `off_any()`
- [x] app 启动时加载并提示 "Loaded N event listener(s): <名单>"

## 多后端 spawn 检查项（comparison 6.4）

- [x] 文件锁：O_EXCL + 退避抖动 + 陈旧接管 + 超时；超时抛异常不静默丢消息
- [x] 原子写 temp+os.replace；读免锁
- [x] 磁盘注册表跨进程可见（第二实例/子进程能 resolve 父进程注册的名字）
- [x] 4 进程并发写零丢失实测
- [x] worker 协议：spec 进 → 结果 JSON 出；API key 环境变量继承不落盘
- [x] 后端探测：会话内分屏，装 wt 未在会话内降级弹新窗口；完全无后端报错清晰
- [x] wt 后端命令 `wt -w 0 split-pane --title ... -d cwd ...`；tmux `split-window -d`
- [x] spawn_pane 融入 wait/cancel/list；超时与取消路径有测试
- [x] 真实 LLM 跨进程 E2E 通过
- [x] 诚实边界记录：iTerm2 未做、cancel 不强杀、worker 无权限弹窗

## 多后端 spawn 实测迭代检查项（六轮真实使用）

- [x] /spawn wait 结果完整输出不截断（8000 字符病态防线带总长标注）
- [x] `--wait` 一条命令派发+面板+结果；与 --pane 可组合
- [x] wt 降级 `-w mini-agents` 命名窗口：首派弹窗，后续进标签页不轰炸
- [x] worker 任何崩溃写失败结果文件 + traceback + 窗格停留（不再无声超时）
- [x] /spawn wait 超时 900s 对齐收集器
- [x] 协议文件在 ~/.mini-agent/workers/（工作目录外，agent 探索不到）
- [x] 收集器 schema 7 字段 + agent_id 双校验，拒绝 LLM 早产桩/冒名文件
- [x] Provider 429/5xx 指数退避重试（1/2/4/8/16s），chunk 产出后不重试
- [x] 多报告：总览表 + 编号硬分节 + 交付文件行（仅列真实存在文件，亮橙渲染）
- [x] slash 输出哨兵机制：仅报告类走 Markdown，/status /cost 纯文本版式不受污染
- [x] 顺带修复：AgentPhase.ACTING 不存在（面板崩溃）、cli finally 吞 traceback、slash 异常炸会话——三处 + 回归测试

## OpenAI Responses API Provider 检查项（comparison 1.1）

- [x] `openai_responses_provider.py` 消息转换：system→instructions / tool_calls→function_call / tool→function_call_output
- [x] 工具 schema 扁平化：`{function: {...}}` → 顶层 `{name, parameters}`
- [x] SSE 事件解析：text delta / reasoning summary / tool call start+args / completed / incomplete / failed
- [x] 用量：input_tokens_details.cached_tokens 提取；max_tokens→max_output_tokens 映射
- [x] Thinking round-trip：LLMResponse.thinking + Message.metadata["thinking"] + reasoning 项回传
- [x] Tool pairing repair：orphan function_call 补 "interrupted" 合成结果
- [x] 错误分类：LLMAuthenticationError(401) / LLMRateLimitError(429) / LLMNetworkError
- [x] 注册 "openai-responses" 到 ProviderRegistry
- [x] 26 个单测，754 全过，覆盖率 80.83%
- [x] config-guide 补 provider 选项；comparison 1.1 标记 ✅ + 优先级表 ✅

## Phase 59 检查项：会话压缩边界（comparison 9.2）

### 功能完整性
- [x] 压缩后 `Conversation.compact_boundary` 自动记录 summary + timestamp + read_files
- [x] 每个压缩策略运行后都尝试记录边界（SummarizeOldest 创建的摘要不被后续 SlidingWindow 丢弃时错过）
- [x] 纯 SlidingWindow 路径（消息数 ≤ MIN_KEEP_MESSAGES 时 SummarizeOldest 跳过）兜底从 `_inject_read_files` 消息创建边界
- [x] `SessionStore` 序列化：`compact_boundary` 写入 conversation 段
- [x] `SessionStore` 反序列化：有边界时跳过 `compressed=True and role=system` 消息，从边界 summary 重建单条摘要
- [x] 非 SYSTEM 的 compressed 消息（DropToolResults 的 TOOL 消息）不被跳过（正常加载）
- [x] 无边界的旧格式会话文件加载行为完全不变（向后兼容）
- [x] `ContextManager.adopt_boundary()` 从边界恢复 `_read_files` 状态
- [x] `app.py._adopt_session()` 调用 `adopt_boundary()`——崩溃恢复 / `/session load` / `/fork` 三入口自动恢复

### 测试
- [x] test_session_store.py — 4 个单元测试：边界往返 / 跳过压缩 SYSTEM / 保留非压缩消息 / 无边界旧格式兼容
- [x] test_compact_boundary_e2e.py — 2 个集成测试：完整链路 E2E（ContextManager → Compressor → save → load → adopt_boundary）/ 旧格式 E2E
- [x] 真实 LLM E2E 验证：DeepSeek 模型实际对话 → 压缩 → 保存 → 加载 → 边界 + read_files 恢复全链路 PASS
- [x] 760 个测试全过，ruff lint + format clean

## Phase 60 检查项：压缩工具对对齐（comparison 9.2b）

### 功能完整性
- [x] `_align_split_to_tool_pair(msgs, split)` —— 切分点落在 TOOL 消息时向前回退到工具对头部（assistant tool_calls 消息），配对整体保留在 kept
- [x] 回退到 0（切分点之前全是一个工具对）时无可摘要内容，压缩空操作，消息不变
- [x] `SummarizeOldest` 与 `LLMSummarizeOldest` 共用同一对齐 helper
- [x] `SlidingWindow` 孤儿防护：token 切分落在工具对中间时丢弃开头的孤儿 tool result（向前扩会超预算）
- [x] 任务锚点（保留最近 USER 消息）在孤儿丢弃之后执行，两者共存不冲突

### 测试
- [x] test_context.py — 4 个单元测试：边界回退到 assistant / 全部为工具对时空操作 / LLM 变体对齐 / SlidingWindow 孤儿丢弃 + 任务锚点共存
- [x] 真实 API 验证（合成消息）：对齐后压缩产物发 DeepSeek 成功；诚实发现——未对齐孤儿该端点也接受（宽容实现），修复价值在严格端点（OpenAI 官方/Anthropic）
- [x] 真实 LLM E2E 验证：真实 AgentLoop + 真实工具（read_file/glob/grep）+ 内存调小窗口（2500/0.5）跑 3 轮真实对话，压缩多次触发，配对检查器扫描 0 违规（检查器已用合成孤儿自检）
- [x] 764 个测试全过（760 + 4 新增），ruff lint + format clean，CI 全部检查项本地复跑通过（3.11/3.12 双版本）

## Phase 61 检查项：记忆导出/导入（comparison 4.6）

### 功能完整性
- [x] `memory/interop.py` —— `export_memories()`：每条记忆一个 `{id}.md`（前置元数据 id/source/scope/created_at/tags）+ MEMORY.md 索引
- [x] `import_memories()` 返回 `(entry, scope)` 对，容错解析：无前置元数据 / mewcode 风格 / 未闭合 / description 兜底 / tags 逗号回退 / 空文件跳过
- [x] `/memory export [dir]` —— 项目 + 用户记忆全量导出，默认 `.mini-agent/memory-export/`（无项目时 `~/.mini-agent/memory-export/`）
- [x] `/memory import <dir>` —— id 去重 + scope 路由（project→项目库，user→用户库，无 scope 默认项目库）
- [x] source ≠ scope 设计点：导出显式记录存储作用域，跨机导入还原正确（实测暴露并修复）
- [x] JSON 内部存储格式不变，命令 description 更新

### 测试
- [x] test_memory_interop.py — 10 个单元测试（导出 + 索引 / 往返保真含 scope / 容错解析各分支）
- [x] 真实 LLM E2E 验证：机器 A add → export → 机器 B import → 真实 Application 的 PRE_LLM hook 注入导入的记忆 → 真实 DeepSeek 正确答出只存在于记忆中的两个事实（项目代号 + 用户昵称），system prompt 注入确认为 True
- [x] 真实 handler 验证：临时目录跑真实 `_make_memory`——add → export → 重导入去重 → 跨机 scope 还原 → 错误路径
- [x] 774 个测试全过（764 + 10 新增），ruff lint + format clean

## Phase 62 检查项：压缩熔断器（comparison 9.2c）

### 功能完整性
- [x] `ContextManager._compress_failures` / `_max_compress_failures` —— 连续 N 次压缩后 token 未减少则跳过后续压缩
- [x] `MemoryConfig.compress_max_failures = 3` 配置项（0 = 禁用）
- [x] 成功压缩（token 减少）自动重置计数
- [x] 熔断触发时 WARNING 日志 + 每次无效压缩 INFO 日志（可观测性）
- [x] `ensure_fits()` 硬兜底不受熔断器影响
- [x] 双阈值：软阈值（75%）受熔断器控制，硬阈值（90%）绕过熔断器强制压缩

### 测试
- [x] 3 个单元测试（test_context.py）：熔断触发 / 成功重置 / 禁用(0 值)
- [x] 1 个集成测试（test_compact_boundary_e2e.py）：完整链路 NoOp→失败累积→日志验证→熔断跳过→ensure_fits 兜底
- [x] 真实 LLM 验证（experiments/verify_circuit_breaker.py）：5 阶段——正常压缩 / 150 文件 read_files 抵消触发熔断 / ensure_fits 兜底 / 禁用对照 / 新会话恢复
- [x] 778 个测试全过（774 + 4 新增），ruff lint + format clean

## Phase 63 检查项：压缩恢复附件含文件内容（comparison 9.2a）

### 功能完整性
- [x] `truncate_to_tokens(text, max_tokens)` 二分搜索截断（token_counter.py）
- [x] `_read_files` 升级为 `dict[str, str | None]`，value 存截断后文件内容
- [x] `record_file_read(path, content)` 有内容截断存储，无内容不覆盖
- [x] `agent_loop.py` 在 spill 之前传 `result.output`（修复顺序 bug）
- [x] `_inject_read_files()` 注入三段恢复上下文：用户请求 + 路径列表 + 文件内容
- [x] `_last_user_request` 压缩前捕获最近 USER 消息（≤2000 字符）
- [x] `compact_boundary` 新增 `file_contents` + `last_user_request`，`adopt_boundary()` 恢复
- [x] 向后兼容：旧格式 boundary 无这两个字段时默认空值

### 测试
- [x] test_token_counter.py — 3 个测试（短文本 / 长文本截断 / 空文本）
- [x] test_context.py — 11 个测试（内容存储/注入/boundary/用户请求/向后兼容）
- [x] 真实 LLM 验证（DeepSeek，context_window=14000）：压缩后 agent 不重读、不丢任务、能引用文件细节
- [x] 793 个测试全过，ruff lint + format clean

## 思考流渲染碎行修复 检查项

- [x] 真因确证（第一次 soft_wrap 修复真实运行验证失败后重查）：Live 拦截——agent_loop 首个 thinking chunk 即启动 Live，之后 `feed_thinking` 的 print 被拦截为独立行块（`end=""` 失效）且每碎片后跟 `\r\x1b[2K` 整行擦除
- [x] Live 延迟启动：`start_stream` 不再启动 Live，`feed_stream` 首个正文 delta 才启动（有思考文本先收尾+空行分隔）；思考期间直连顺序写入
- [x] `soft_wrap=True` 保留（管无 Live 路径的逐 print 宽度折行，次要机制）
- [x] ANSI 级取证（force_terminal=True）：旧行为每碎片后跟擦除码，新行为思考文本连续完整
- [x] 思考仅无正文（后接工具调用）时 finish_stream 不崩（Live 未启动安全跳过）
- [x] esc_watcher 仍在首个 thinking chunk 启动，双 Esc 中断思考不受影响
- [x] reasoning 自带换行原样保留（真内容不受影响）
- [x] 4 个新测试（Live 延迟+无擦除码 / 思考仅收尾 / 超宽无折行 / 自带换行保留），1158→1162
- [x] 真实推理模型运行验证（第一次修复即栽在跳过此步）：两轮真实推理运行（9.11 vs 9.9 / 水池注水问题），思考流连续完整显示在回答前，碎行消失，中英混排/长推理/自带换行均正常

## 崩溃会话启动清理 检查项

- [x] `MemoryConfig` 新增 `crashed_session_cleanup_days: int = 40`（0 = 永久保留）
- [x] `SessionStore.cleanup_stale()` 新增 `crashed_max_age_days` 参数：超龄崩溃会话也删除；正常会话 30 天逻辑不受影响
- [x] app.py + remote/server.py 两个调用点同步传入新参数
- [x] `config.toml.example` 补 `[memory]` 两个清理配置文档（`session_cleanup_days` 之前也未记录）
- [x] 3 个新测试：超龄崩溃被删 / 40 天内保留 / 0 禁用 + 正常 30 天不受影响回归，1179→1182

## 远程模式会话持久化 检查项

- [x] `app.py` — `_find_crashed_session()` 助手提取（closed_cleanly==False + 同项目 + 非当前会话，返回最新），终端 `_maybe_restore_session` 改用助手行为不变（询问式保留）
- [x] `remote/server.py` — 启动时 `cleanup_stale` + `_restore_last_session()` 自动恢复（不询问——启动时无客户端可问；恢复后 closed_cleanly=False 重新算进行中）
- [x] `remote/server.py` — turn 结束 finally `_autosave(force=True)`（镜像终端，硬杀不丢最后一轮）
- [x] `remote/server.py` — 斜杠命令后节流 `_autosave()`（镜像终端）
- [x] `remote/server.py` — serve 块 try/finally 退出保存（closed_cleanly=True；空会话跳过不落垃圾文件）
- [x] `/session load`/`/fork` 换会话后广播 `history_reset` + 对所有客户端重放历史（修复既有盲区：浏览器不知会话已换）
- [x] `web_ui.py` — `history_reset` 事件清空聊天区与流式状态
- [x] 诚实边界：自动恢复只针对崩溃/硬杀；正常关闭重启从新会话开始（/session load 可手动恢复）；多客户端仍共享会话
- [x] `/session new` 安全另起：旧会话完整存盘标记正常关闭（空会话跳过）、新 ID、保留 system prompt、继承 model/project_dir——堵住裸 /clear 的同 ID 覆盖坑（终端既有，本次文档化）
- [x] `ContextManager.reset_state()` 陈旧状态修复（既有 bug）：采用无边界会话不再继承上一会话的已读文件缓存与技能状态，`_adopt_session` 每次采用前复位
- [x] 13 个新测试（test_remote_session.py），1166→1179
- [x] 真实运行验证（experiments/verify_remote_session.py，WS 客户端驱动真实服务器+真实 LLM）：对话一轮 → 硬杀服务器 → 会话文件 closed_cleanly=False 存 2 条消息 → 重启 → 重连收到 history_user/history_assistant 完整重放，VERDICT: PASS
- [x] `/session new` 真实运行验证：真实 LLM 对话一轮 → WS 发 /session new → 收到新会话 ID + "Previous session ... saved" 提示 + `history_reset` 广播；落盘检查旧会话 closed_cleanly=True 消息完整，VERDICT: PASS
- [x] 用户终端人工验证（日常动作级四场景 + /session new 全流程）全部通过：① 远程关窗口硬杀 → 重启自动恢复历史；② 远程 Ctrl+C 善终 → 重启空白新会话；③ 终端关窗口 → 重启弹询问（y 恢复接上文 / n 拒绝后不再问、落盘 closed_cleanly=true）；④ 终端 exit → 重启不弹询问；⑤ /session new 后新会话隔离（答不出旧词）、list 可见旧会话、load 回去历史无损（答出"苹果"）

## on/off 模式命令无参数行为统一 检查项

- [x] `/trace`、`/explain`、`/audit` 无参数从 toggle 改为只显示当前状态不改变
- [x] `/plan` 无参数从无条件开启改为只显示当前状态（`Plan mode: **ON** (read-only)` / `**OFF**`）
- [x] 命令注册 description 去掉 "Toggle"，改为 "no args = show status"
- [x] 4 个新测试（每个命令 1 个，验证无参数状态显示+不改变状态），1162→1166

## 恢复附件含 skill 调用记录 检查项

### 功能完整性
- [x] `SkillRegistry._invocations` 保序去重激活历史（deactivate 不抹除——调用记录非当前状态）+ `active_names`/`invoked_names` 属性
- [x] `ContextManager.set_skill_provider()` 回调注入（memory 层不 import extensions 层）；provider 崩溃静默吞掉不破坏压缩
- [x] 恢复附件技能行：激活中的标注 "do NOT re-activate"（prompt 在 system prompt 中存活），已停用单列历史行；二次压缩替换旧块不堆叠
- [x] `compact_boundary` 持久化 `skill_invocations`/`active_skills`；`adopt_boundary()` 暂存 `adopted_skills`
- [x] app 层 `_adopt_session` 经 `SkillRegistry.restore_state()` 写回——不重注入 prompt（恢复的 system_prompt 已含）；会话恢复后 is_active/deactivate/match_triggers/reload 恢复正常
- [x] 向后兼容：旧 boundary 无技能字段时 `adopted_skills` 为 None；无 provider 时附件不变

### 测试
- [x] 手动 /compact 走 `check_and_compress(force=True)` 同一管道——修复直调 compressor 跳过恢复附件与全部边界字段的既有缺陷（复验实测暴露）；空对话+激活技能时也能建边界
- [x] 12 个新测试（3 skills + 9 context：历史记录/停用保留/restore 不动 prompt/附件行/停用单列/无 provider/二次压缩替换/provider 崩溃/adopt 暂存/向后兼容/端到端 boundary/force 全管道）

## Phase 64 检查项：聚合工具结果预算（①）

### 功能完整性
- [x] `PREVIEW_CHARS` 500→2000（配套 1b），预览以 `min(PREVIEW_CHARS, threshold)` 封顶
- [x] `maybe_spill(result, force=False)` —— force 绕过单条阈值；不长于预览的结果一律豁免（配套 1c）
- [x] `is_spill_readback(tool_name, arguments)` —— read_file 路径落在溢写目录内时豁免（配套 1a，防读回-溢写死循环）
- [x] `spill_batch(results, already_used, exempt_ids)` —— 累计超预算时按大小降序强制溢写；豁免错误/已溢写/exempt/小结果；OSError 保留原文
- [x] `MemoryConfig.aggregate_spill_chars = 200_000`（0 = 禁用），app.py / subagent.py 装配传参
- [x] `agent_loop.py` —— `_run_tool_pipeline` 单条溢写前检查读回豁免；OBSERVE 阶段 `spill_batch`，`turn_result_chars` 跨迭代累计
- [x] 溢写占位文案含溢写文件路径，LLM 可 offset/limit 精读

### 配套修复
- [x] 溢写缓存只读放行（`path_guard.py` `_result_cache_root()`，每次调用计算兼容测试 home 替换）——read 自动 ALLOW / write 仍询问，读回闭环不再弹权限框
- [x] confirm() 提示符污染（`terminal.py`）——临时 PromptSession 替代主 session，主提示符不再被 "allow? [y/a/n] >" 永久覆盖
- [x] 压缩熔断器警告去重（`context.py` `_breaker_warned`）——开启只警告一次，压缩恢复有效后重置

### 测试
- [x] 13 个新测试（test_tool_result_cache.py）：预览常量 / force 绕过 / force 小结果豁免 / 读回判定 5 情形 / 欠额不动 / 降序溢写 / exempt_ids / 错误+已溢写跳过 / 跨迭代累计 / aggregate=0 / config 默认 / 2 集成（并行聚合溢写、读回不重溢写）
- [x] 配套修复 5 个测试：溢写缓存读放行 / 写仍询问 / confirm 不碰主 session / confirm 兜底 / 熔断器警告仅一次
- [x] 真实 LLM 验证（DeepSeek，threshold=50K/aggregate=8K）：并行读 3 文件聚合触发溢写 6/9 条、对话累计 15.5K 字符有界、LLM 预览后自主 offset/limit 精读收敛、读回溢写文件不重溢写
- [x] 交互式 E2E 验证（真实 mini 会话，aggregate=15000，会话 JSON 审计）：6 验证点 5 全达成 + 成本有界在极端参数下部分达成（诚实边界：豁免读回计入累计，aggregate < 单文件时链式溢写-读回；默认 200K 无此问题）
- [x] 821 个测试全过，ruff lint + format clean

## Phase 65 检查项：Token 驱动的保留窗口（todo-code-quality ⑤）

### 功能完整性
- [x] `_compute_keep_split(msgs)` 从尾部反向扫描累计 token，双条件停止（≥10K tokens 且 ≥5 条），硬顶 40K
- [x] `SummarizeOldest` 移除 `KEEP_RECENT = 6`，改用 `_compute_keep_split()` + `_align_split_to_tool_pair()`
- [x] `LLMSummarizeOldest` 同步改用 `_compute_keep_split()`
- [x] 短消息全保留（总 token < 10K 时 split=0，不浪费压缩空间）
- [x] 长消息少保留（8K/条 × 5 = 40K 命中硬顶，不保留过多）
- [x] 工具对对齐仍然生效（`_align_split_to_tool_pair` 未变）

### 测试
- [x] 7 个新 `_compute_keep_split` 单测：短消息全保留 / 长消息少保留 / 硬顶 / 最少消息数 / 少于最少 / 双条件停止 / SummarizeOldest 低 token 空操作
- [x] 已有 30+ 测试全部适配（token_count 调高、移除 KEEP_RECENT 引用）

## Phase 66 检查项：摘要 prompt 结构化（P67）

### 功能完整性
- [x] `_SUMMARY_PROMPT` 重写为结构化格式：`<analysis>` 思考草稿（时间线梳理 + 自查）+ `<summary>` 9 节输出（主请求/技术概念/文件代码/错误修复/问题解决/全部用户消息/待做/当前工作/下一步）
- [x] mini 适配：prompt 声明"近期消息已原样保留"（只摘要旧前缀）；省去 mewcode 的 "Do NOT call tools" 警告（直连调用不带工具）
- [x] `_extract_summary()` 只注入 `<summary>` 块；无标签回退完整输出；只剩 `<analysis>`（截断）时剥离草稿返回空 → 触发抽取式回退
- [x] 回退分支 WARNING 日志（异常类型 + 消息），回退原因可观测

### 测试
- [x] 5 个新单测：提取剥离草稿 / 无标签回退 / 截断剥离 / 注入内容不含草稿 / 空 summary 块回退
- [x] 真实 LLM E2E（`experiments/verify_summary_prompt.py`）：9 节摘要完整，文件名/用户约束/下一步保留，5 项断言全 PASS
- [x] 835 个测试全过，ruff lint + format clean

## Phase 67 检查项：保留窗口按压缩目标缩放（P68）

### 功能完整性
- [x] `_compute_keep_split(msgs, target_tokens)`：下限 `min(10K, target//2)`、硬顶 `min(40K, target)` 随压缩目标缩放
- [x] `keep_count == 0` 兜底强制保留 1 条尾部消息
- [x] 大窗口（128K）行为与缩放前完全一致
- [x] 小窗口（10K）摘要级恢复可达标，不再退化为纯 SlidingWindow

### 测试
- [x] 4 个新单测：小目标缩放 / 超顶保底 / 大目标不变 / 端到端预算内
- [x] 真实 LLM 验证（target=7500）：压缩后 7008 ≤ 7500，结构化摘要存活
- [x] 841 个测试全过，ruff lint + format clean

## Phase 68 检查项：DropToolResults 尊重保留窗口（P69）

### 功能完整性
- [x] Stage 1 只截断可摘要前缀（`_compute_keep_split`）内的工具输出，绝不碰模型工作集
- [x] 修复"以为工具坏了"重读死循环：同场景 36 迭代 → 4 迭代（终端实测）

### 测试
- [x] 3 个单测（前缀截断 / 短输出跳过 / 保留窗口内新旧对照）；会话 JSON 取证确认根因

## Phase 69 检查项：恢复附件缩放 + 嵌套摘要前传（P70）

### 功能完整性
- [x] `_inject_read_files` 附件总预算 `min(25K, max_tokens//4)`，128K 行为不变
- [x] `_SUMMARY_PROMPT` 明确嵌套旧摘要为权威历史，约定/决策/约束必须前传

### 测试
- [x] 附件缩放单测（8K vs 128K 对照）；真实 LLM 嵌套场景 5 约定全前传

## Phase 70 检查项：SlidingWindow 摘要锚点（P71）

### 功能完整性
- [x] kept 无压缩 SYSTEM 消息时把摘要插回最前（与任务锚点同等待遇）
- [x] 全管道插桩定案：LLM 摘要含全部埋点、SlidingWindow 删的恰是摘要

### 测试
- [x] 紧预算摘要锚点单测；修复后全管道两轮压缩埋点全存活

## Phase 71 检查项：digest 剥附件 + 摘要重试（P72）

### 功能完整性
- [x] `_extractive_digest` 按 `RECOVERY_MARKERS` 剥离旧摘要上的恢复附件（共享常量防不同步）
- [x] `SUMMARY_RETRIES = 2`：偶发空摘要先重试再落抽取式，重试/穷尽有 WARNING 日志

### 测试与终验
- [x] 3 个单测；复刻第八轮最恶劣路径（LLM 失败×2 → 抽取式+附件 → 二次压缩）埋点全存活
- [x] **终端第九轮无污染验证最终通过**：五问全中（反转/陷阱题在内），JSON 判定埋点全在摘要、不在保留历史
- [x] 846 个测试全过，ruff lint + format clean

## Phase 72 检查项：摘要 prompt 超长收缩重试（P73）

### 功能完整性
- [x] `_is_prompt_too_long()`：400/413 + 关键词识别；非超长错误（网络/空摘要）不误判
- [x] 超长时丢最旧 20% 可摘要消息 + cap 缩 20% 重试，`MAX_SHRINKS=3` 与偶发重试预算独立
- [x] 头部旧压缩摘要绝不被 shrink 丢弃
- [x] 收缩穷尽后立即回退抽取式，不重复相同超长请求；shrink/穷尽有 WARNING 日志

### 测试与终验
- [x] 6 个新单测；852 个测试全过，ruff lint + format clean
- [x] 真实 API 全管道验证 PASS：真 400 → 2 轮收缩 → 成功 9 节摘要，埋点存活、请求尺寸严格递减

---

## Phase 73 检查项：最小前缀检查 + /todo 歧义前缀（P74）

### 功能完整性
- [x] 压缩器：`MIN_SUMMARIZE_PREFIX_TOKENS = 2000`，`SummarizeOldest` + `LLMSummarizeOldest` 前缀不足 2K token 时跳过
- [x] TaskStore：`AmbiguousTaskError` 歧义前缀检测 + `min_unique_prefix()` 最短唯一前缀
- [x] /todo 命令：全子命令捕获歧义异常并列出匹配项；ID 显示改用动态最短前缀

### 测试
- [x] 6 个新测试（压缩器前缀跳过 + TaskStore 歧义/精确/唯一前缀 + /todo 命令歧义处理）
- [x] 97 个相关测试全过，ruff lint clean

---

## Phase 76 检查项：三个轻量扩展点接入

### #4 ProviderRegistry.list_providers() 接入 /model
- [x] `/model` 无参数输出追加"可用 Provider: openai, anthropic, openai-responses"行
- [x] 调用 `ProviderRegistry.list_providers()` 获取列表（非硬编码）

### #12 UserMessageEvent.is_slash_command 接入
- [x] `app.py` 斜杠命令分支 emit `UserMessageEvent(content=user_input, is_slash_command=True)`
- [x] `AuditLogger` 新增 `UserMessageEvent` 订阅（4 种事件），写 `user_message` 审计条目（content 截断 200 字符 + is_slash_command 标记）
- [x] `TraceRenderer` 新增 `UserMessageEvent` 订阅（8 种事件），trace 行显示 `user "内容前60字" [slash]`

### #13 LLMRequestEvent.estimated_tokens 接入
- [x] `agent_loop.py` emit `LLMRequestEvent` 时从 `ContextManager.total_tokens` 填入 `estimated_tokens`（无 ContextManager 时默认 0）
- [x] `TraceRenderer._on_llm_request` 追加 `~{estimated_tokens} tok` 显示（为 0 时隐藏）

### 测试
- [x] 11 个新测试（list_providers 2 + is_slash_command 6 + estimated_tokens 3），887 个全过

## Phase 77 检查项：四个中级扩展点接入

### #2 ToolRegistry.filter() 接入
- [x] `team.py` 非写文件步骤改用 `self._manager._tools.filter(denied=list(_WRITE_TOOLS))`
- [x] `subagent.py` 工具白名单改用 `registry.filter(allowed=effective_tools)`
- [x] 原有 test_team.py 测试不受影响（行为等价）

### #6 Plan.is_complete 接入
- [x] `team.py` 主循环从 `while pending` 改为 `while not plan.is_complete`
- [x] 不再维护独立的 `pending` 列表，用 `plan.steps` 的 status 驱动

### #11 SessionMetadata.tags 接入
- [x] `/session tag <name>` 添加标签（只取第一个词，忽略多余内容）
- [x] `/session untag <name>` 移除标签
- [x] `/session tags` 查看当前会话所有标签
- [x] `/session list --tag <name>` 按标签过滤已保存会话
- [x] `list_sessions()` 返回 `tags` 字段
- [x] tags 经 save/load 往返存活（JSON 持久化）
- [x] 真实终端验证：tag/untag/tags/save/list --tag 全链路 PASS

### #14 PermissionRequest.tool_name 接入
- [x] `check_path()` 新增 `tool_name` 参数
- [x] `agent_loop._check_permission()` 的 read/write 分支传入 `tool_name=tc.name`
- [x] 审计日志 permission 条目中 `tool` 字段正确记录工具名

### 测试
- [x] 10 个新测试（filter 2 + is_complete 2 + tags 4 + tool_name 2），897 个全过

## Phase 78 检查项：运行时权限规则管理（扩展点 #3）

### PermissionManager.add_rule() 增强
- [x] 空 pattern 抛 ValueError
- [x] scope+pattern+level 三元组去重，重复返回 False
- [x] 非静默模式发射 PermissionRuleAddedEvent（event_bus 注入）
- [x] _silent=True 跳过事件发射（启动加载阶段使用）
- [x] _load_rules_from_config 和 load_rule_files 统一走 add_rule(_silent=True)

### 新增方法
- [x] remove_rule(scope, pattern, level) -> bool，发射 PermissionRuleRemovedEvent
- [x] list_rules() -> list[PermissionRule]，返回副本
- [x] save_rule_to_file(path, rule) 静态方法：读取 TOML → 合并去重 → 回写，自动创建父目录

### 事件与装配
- [x] PermissionRuleAddedEvent(scope, pattern, level, reason)
- [x] PermissionRuleRemovedEvent(scope, pattern, level)
- [x] events/types.py 导出
- [x] app.py 传入 event_bus=self.event_bus

### /allow /deny 斜杠命令
- [x] /allow command "docker *" — 添加 ALLOW 规则
- [x] /deny path "*/secrets/*" — 添加 DENY 规则
- [x] 无参数列出该级别全部规则
- [x] --save 追加写入项目级 .mini-agent/permissions.toml
- [x] 重复规则提示 "Rule already exists"

### 测试
- [x] 13 个新测试，912 个全过，ruff clean
- [x] 原有 27 个 permission 测试 + 9 个 permission_files 测试不受影响（行为等价）
## Phase 79 检查项：工具级权限与通用检查入口（扩展点 #9/#15）

### check_tool 工具级门
- [x] check_tool(tool_name) 显式 TOOL 规则 + 会话授权判定，无匹配返回 None
- [x] TOOL DENY 直接拦截工具（无害命令也拦）
- [x] TOOL ALLOW 整体信任（危险命令零弹窗执行）
- [x] 无 TOOL 规则落回命令/路径资源级检查（行为与改前完全一致）
- [x] DENY 优先于 ALLOW；工具名支持 glob 匹配
- [x] agent_loop._check_permission 所有工具调用先过工具门，事件 scope="tool" 带 matched_rule
- [x] would_ask 显式工具规则直接判定不弹窗（流式预提交一致）

### check() 通用入口
- [x] COMMAND scope 请求经 check() 走危险模式确认（不再绕过）
- [x] PATH scope 请求经 check() 走 DENY 规则 → PathGuard（不再绕过）
- [x] operation 从 request.context 前缀解析（write 前缀 → write，其余 read）
- [x] TOOL/其他 scope 走通用管道（规则 → 会话授权 → 默认模式）
- [x] check_command/check_path/check_tool 复用同一批内部管道，无递归

### 规则持久化与命令
- [x] permissions.toml [tools] 节加载生效（load_rule_files）
- [x] save_rule_to_file TOOL 规则写入 [tools] 节；旧文件无 [tools] 节向后兼容
- [x] /allow tool <name> 与 /deny tool <name>（含 --save）
- [x] /allow remove 与 /deny remove 子命令（scope+pattern+level 精确移除会话内规则；level 不匹配不误删）
- [x] 输出中 [scope] 转义，不再被 markdown 当引用链接吞掉
- [x] permissions.toml.example 补 [tools] 示例

### 测试与验证
- [x] 22 个新测试，934 个全过，ruff clean
- [x] 真实 LLM 四阶段验证（experiments/verify_tool_permission.py）：deny 拦截 / 对照组弹确认 / allow 零弹窗 / check() 分发 / TOML 往返

## Phase 80 检查项：默认 Agent 类型接线（扩展点 #10）

### DEFAULT_AGENT_TYPE 回退
- [x] SubAgent 未指定 agent_type 时使用 get_agent_type(DEFAULT_AGENT_TYPE)（worker）的提示词模板
- [x] 未指定类型保留 config.max_agent_iterations（不被 worker 的 50 覆盖），预算正确注入 prompt
- [x] 显式指定类型仍采纳类型完整档案（worker=50 / verify=20 + 只读工具集）
- [x] 内联 SUBAGENT_SYSTEM_PROMPT 已删除，无残留引用
- [x] DEFAULT_AGENT_TYPE 是 AGENT_TYPES 中的合法键

### 测试与验证
- [x] 4 个新测试，938 个全过，ruff clean
- [x] 真实 LLM 两阶段验证（experiments/verify_default_agent_type.py）：未指定类型完成真实任务 / 显式类型对照组不变

## Phase 81 检查项：slice_window 删除

- [x] Conversation.slice_window() 方法已删除，源码/测试零残留（spec.md 历史文档按惯例保留）
- [x] capabilities.md 对话管理器行更新（窗口截取职责归 ContextManager/Compressor）
- [x] 937 个测试全过，ruff clean

## Phase 82 检查项：PermissionDecision.PENDING 跨进程权限协议

- [x] `security/remote_confirm.py` RemoteConfirm 文件协议：worker 写 `<agent_id>.perm-request.json` → 父进程 0.5s 轮询中转 `terminal.confirm` → 写回 decision；超时 120s 安全拒绝，文件 finally 清理
- [x] `worker.py` 搭建完整权限栈（PathGuard + PermissionManager + RemoteConfirm）并加载 permissions.toml 规则——pane worker 不再自动放行全部工具调用
- [x] 远程/浏览器模式断连排队：`_pending_prompts` 存活断连、重连 `_replay_pending_confirms()` 重发、120s 超时 deny all
- [x] `_ask_user()` 弹窗前发射 `PermissionCheckEvent(decision="pending")`，`/trace` 以 warning 色显示 `PENDING (awaiting user)`
- [x] 15 个新测试（test_remote_confirm 10 + test_permissions 2 + test_remote 3），952 passed + 1 skipped，ruff clean
- [x] E2E 验证脚本 `experiments/verify_pending.py`：4/4 全过（y→GRANTED / n→DENIED / a→GRANTED+always / timeout→DENIED）
- [x] 真实 LLM 终端验证：`/trace` 显示 PENDING → GRANTED 两行事件

## Phase 83 检查项：插件生态 plugin_loader

- [x] `extensions/plugin_loader.py`：四钩子契约（register 全控优先 / register_tools/commands/skills 专用）+ 双通道发现（entry_points `mini_agent.plugins` + `plugin_dirs`）+ 三层异常隔离 + 重名告警
- [x] `SkillRegistry.register()` 编程注册的技能在 load_all()/reload() 后存活（`_external` 合并）
- [x] `plugin_dirs` / `disabled_plugins` 配置字段生效（TOML 顶级键，loader 零改动）
- [x] 插件工具不受 `enabled_tools` 白名单约束（安装即 opt-in，docstring 有论证）
- [x] `/plugins` 命令展示插件名/来源/注册的工具/命令/技能（快照差分）
- [x] 示例插件 `examples/plugins/word_count_plugin.py` 三钩子全演示
- [x] 16 个新测试，968 passed + 1 skipped，覆盖率门禁通过，ruff clean
- [x] 真实运行验证：启动横幅 / /plugins 表格 / /greet / haiku-mode 技能 / 真实 LLM 调用 word_count 工具 / disabled_plugins 禁用生效
