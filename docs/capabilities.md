# Mini-Code-Agent 能力对照表

> 本文档逐条对照项目最初的 18 项需求（12 项核心功能 + 6 大技术层面），
> 说明每一项的实现位置、实现方式与验证证据。
> 当前版本 v1.1.0，1201 个测试全部通过（1 skipped）。

---

## 第一部分：12 项核心功能

### ✅ 1. 类 Claude Code 的终端交互体验

**要求**：基于 LLM 流式响应 + 多轮对话，边想边输出，整个对话过程和 Claude Code 一致。

**实现**：
- 流式渲染：`ui/renderer.py` — Rich Live 组件逐段提交式渲染 Markdown（8Hz，代码高亮/粗体），逐 token"边想边输出"；思考流（reasoning_content）dim 直连写入，Live 延迟到首个正文 delta 才启动（tech-notes §100）
- 多轮对话：`models/message.py` 的 Conversation 全量重放历史，LLM 记住上下文
- 交互细节：`>` 提示符、输入文字 bold 亮浅蓝着色 + 输入行上下同色横线、输入 `/` 弹出命令下拉菜单（上下键选择/Tab 补全/删字符重新过滤）、输入历史跨会话保留（↑ 键翻历史）、底部工具栏实时显示当前 LLM 和权限模式、工具调用 `╭─ ╰─` 连线展示、每轮 token 用量统计
- 启动体验：`mini` 一个单词全局启动（同 `claude`）；`mini -p "任务"` 非交互一次性执行（脚本/CI/管道，`--output-format stream-json` 输出 NDJSON 事件流，事件名同远程协议）

**验证**：真实 API 流式验证；终端交互全部手工验证过

---

### ✅ 2. 六个核心编程工具

**要求**：至少 ReadFile, WriteFile, EditFile, Bash, Glob, Grep 六个工具，覆盖高频场景。

**实现**（`tools/builtin/`，全部实现 Tool ABC）：

| 工具 | 能力 |
|---|---|
| read_file | 带行号读取，offset/limit 大文件分页，超大文件拒绝 |
| write_file | 写入/覆盖，自动创建父目录 |
| edit_file | 精确字符串替换，唯一匹配约束防误改，replace_all 批量 |
| bash | 跑命令，超时熔断，exit code 标注，Win/Unix 双平台 |
| glob | 文件名模式匹配，按修改时间排序，跳过噪音目录 |
| grep | 正则内容搜索（关键词搜索），include 文件过滤，context 上下文行 |

**验证**：24 个工具单测 + 真实 API E2E（Agent 自主读 README、grep 搜 TODO）

---

### ✅ 3. 自主任务循环（Agent Loop / ReAct）

**要求**：Agent 能自己拆任务、调用工具、看结果、再决策。

**实现**（`core/agent_loop.py`）：
- ReAct 循环：THINK（LLM 流式生成）→ 有 tool_calls 则 ACT（执行工具）→ OBSERVE（结果写回对话）→ 回到 THINK，直到 LLM 给出最终回答
- 自主性本质：工具结果作为 TOOL 消息进入对话，LLM 看到结果自然继续推理——循环不含任务逻辑，所有决策由 LLM 做出
- 熔断保护：max_iterations 上限（80）、用户取消、双层死循环检测（同签名连续 6 次 + 同一工具出现在连续 15 轮每轮中——P35 实验后升级 v2，不误杀批量并行）、确认拒绝熔断（任何确认框被拒即停下回问用户——危险命令/项目外路径/hook 确认，默认阈值 1；自动策略拒绝不计数）

**验证**：8 个 MockLLM 单测覆盖完整链路；真实 API 验证 Agent 自主多步执行（一次任务里自主 glob→read→回答）

---

### ✅ 4. MCP 协议接入

**要求**：无缝挂载任意符合 MCP 规范的外部工具服务（GitHub、Slack、数据库、12306 等）。

**实现**（`tools/mcp/`）：
- `transport.py`：StdioTransport（子进程）+ HTTPTransport（远程服务器）+ SSE 三种传输，JSON-RPC 2.0 通信
- `client.py`：MCPManager — 标准握手（initialize → initialized → tools/list）、多服务器管理、工具调用代理
- `adapter.py`：MCPToolAdapter — MCP 工具的 inputSchema 自动转为内部 ToolSchema，以 `mcp_{server}_` 前缀注册进同一个 ToolRegistry
- 无缝的含义：适配后的 MCP 工具和内置工具走完全相同的调用管道——权限检查、Hook 链、错误处理自动生效

**验证**：7 个单测（FakeMCPManager 模拟服务器）

---

### ✅ 5. Skill 技能包系统

**要求**：把 prompt+工具+资源打包成可装载的技能包，持续拓展能力。

**实现**（`extensions/skills.py`）：
- 技能包 = 目录 + SKILL.md（YAML front-matter 声明 name/triggers/tools + Markdown 正文作为 prompt）
- 装载：`load_all()` 扫描技能目录自动发现
- 激活：prompt 以带标记形式注入 system prompt；停用时精确移除，可逆可叠加
- 触发：用户消息含触发词时自动匹配建议
- 内置技能包：`skills/code_review/`（代码审查）、`skills/init_project/`（项目脚手架）、`skills/teach-mode/`（教学模式辅助）、`skills/offline-ollama/`（内网离线）
- 界面入口：`/skill` 列出、`/skill activate <名称>` 激活

**验证**：8 个单测（解析/激活/停用/触发/容错）

---

### ✅ 6. Slash Command 命令框架

**要求**：内置 + 用户自定义的斜杠命令，常用操作一键触发。

**实现**（`extensions/slash_commands.py` + `builtin_commands.py`）：
- 框架：SlashCommandRegistry — 注册/分发/列表，斜杠输入优先于 LLM 对话（本地操作零 token）
- 28 个内置命令：/help /clear /status /model /compact /memory /session /tools /skill /plugins /trace /explain /audit /theme /plan /mode /spawn /team /todo /cost /record /replay /undo /fork /allow /deny /quit /exit
- 自定义：`registry.register(SlashCommand(name=..., handler=...))` 一行注册
- 体验：输入 `/` 弹出下拉补全菜单（透明背景、实时过滤、上下键选择）

**验证**：7 个单测 + E2E 装配测试验证命令齐全

---

### ✅ 7. Hook 生命周期钩子

**要求**：危险命令会问你，敏感目录会拦截，Agent 有能力但不会失控。

**实现**（`tools/hooks.py` + `security/`）：
- Hook 框架：11 个生命周期阶段（STARTUP/SHUTDOWN/SESSION_START/SESSION_END/USER_INPUT/TURN_START/TURN_END/PRE_LLM/POST_LLM/PRE_TOOL/POST_TOOL）× 6 种裁决（CONTINUE/BLOCK/MODIFY/CONFIRM/COMMAND/NOTIFY），优先级链 + 否决短路；`[[hooks]]` 配置可声明四种动作——`block`（拒绝）/ `confirm`（弹 y/a/n 确认框）/ `command`（执行 shell 命令）/ `notify`（终端通知行）；支持条件表达式（`condition` 字段，`==`/`!=`/`=~`/`~=` + `and`/`or`）和模板变量（`$TOOL_NAME`/`$TOOL_ARGS.<key>`）；PRE_TOOL 与 POST_TOOL 均可声明式配置
- 危险命令确认：28 条正则（rm/sudo/chmod 777/mkfs/dd/git push/commit/reset/stash/rebase/checkout/restore/clean/Windows del/rmdir/rd/format/curl|sh/wget|sh/python -c/node -e/perl -e/ruby -e/sh -c/bash -c/powershell/pwsh/cmd /c——删除类命令 rm/del/rmdir/rd 任意形态均命中：裸 rmdir 删空目录、rm/del 删单个文件也弹确认，不限于 -rf、/s、/q）命中即弹窗，y/a/n 三选（允许一次/本会话总是/拒绝——拒绝危险命令即停止整个目标，默认阈值 1）；弹窗等输入期间并行工具的输出重定向到提示行上方，输入行不被打断
- 敏感目录拦截：~/.ssh、~/.aws、~/.gnupg 硬拒绝；.env/密钥/证书文件即使在项目内也拦截
- 敏感文件读泄漏防护：上面的敏感文件拦截只在 read_file/write_file/delete_file 工具层；bash 命令（`type`/`cat`/`Get-Content .env`）经 `command_references_sensitive_file()` 命中同一份敏感模式即弹确认，堵住"read_file 被拒后改用 bash 读密钥泄漏"的洞（真实验证实测泄漏过 API key）；诚实边界：变量/通配/base64 混淆仍可逃逸
- 三级路径策略：项目内自动放行 / 敏感硬拒绝 / 项目外询问
- 权限模式矩阵：`/mode` 运行时切换 `default`（标准询问）/ `accept-edits`（写免确认，危险命令仍询问）/ `plan`（只读：拒绝 WRITE 与 EXTERNAL 类别工具 + bash 写形态命令拒绝；有权限门控传导时允许 spawn 研究型子 Agent——子 Agent 继承 plan 模式、写操作在权限层被拒，无门控时 spawn 仍禁用）/ `bypass`（除安全底线外全免确认，EXTERNAL 类别工具也免确认放行）四模式；矩阵新增**工具类别轴**：每个工具声明 READ/WRITE/EXECUTE/EXTERNAL 类别（未声明的插件工具默认 EXTERNAL 保守处理），类别门控在路径检查之前评估——install_skill 这类无路径参数的工具也被拦住——且读 `permission_manager.mode` 而非循环标志，对子 Agent 同样生效；deny 规则、敏感路径、敏感文件命令（`type .env` 类）在所有模式下有效（bypass 也拦）；配置 `[security] approval_mode` 设启动模式；`exit_plan_mode` 工具需用户批准计划才退出 plan（LLM 不能自行解除只读）；模式切换发 `PermissionModeChangedEvent`（trace 可见），`/status` 和底部工具栏显示当前模式
- fail-safe：无 UI 时默认拒绝
- 执行管道：每次工具调用走 PermissionCheck → PRE_TOOL Hook → execute → POST_TOOL Hook
- 已激活的生命周期 Hook：PRE_LLM（LLM 调用前，含 BLOCK 能力 + 自动记忆注入）、SESSION_END（退出时自动提取偏好）、PRE_TOOL/POST_TOOL（工具执行前后）
- 声明式规则（comparison 7.2）：`[[hooks]]` TOML 配置，两种匹配方式——固定字段（tool fnmatch + arg/contains/regex）或条件表达式（`condition` 字段优先），四种动作（block/confirm/command/notify）+ 模板变量（`$TOOL_NAME`/`$TOOL_ARGS.<key>`/`$TOOL_ARGS`/`$EVENT`/`$RESULT`/`$RESULT_ERROR`）——给目录加只读锁、给 git push 加人工闸门、写 .py 文件后自动跑 formatter，均只需几行配置无需写 Python

**验证**：37 个安全测试（含危险命令三态、敏感文件拦截、敏感文件经 bash 通道弹确认、Hook 阻止与观察）+ 85 个 hook 测试（test_hooks.py 55 个 + test_hook_conditions.py 30 个：含条件引擎解析/求值、四种动作类型、confirm+condition 五路径端到端、command stdout 显示、模板展开、向后兼容）

---

### ✅ 8. 上下文压缩 + Token 管理

**要求**：对话变长后自动压缩历史，省 token 又不丢关键信息。

**实现**（`memory/context.py` + `compressor.py` + `llm/token_counter.py`）：
- Token 管理：tiktoken 精确计数（可选依赖，缺失时 CJK 感知估算——CJK 1 token/字 + 其余 chars/4，P43）+ API usage 锚点（对话总量直接用 API 返回的权威计数，只对新消息估算，误差不累积，P43）+ LRU 缓存 + 每轮界面显示用量（`tokens: xxx this turn / xxx total`）
- 自动压缩：ContextManager 每次 LLM 调用前 + OBSERVE 后检查（P64.3），软阈值 75% 触发、硬阈值 90% 绕过熔断器（P65）；ensure_fits 溢出兜底使用 API 探测的真实窗口值（P42）
- 三级压缩级联（保留关键信息的关键设计）：
  1. DropToolResults — 压可摘要前缀内的冗余工具输出，绝不碰模型正在使用的工作集（P69，防重读死循环）
  2. LLMSummarizeOldest — LLM 结构化摘要旧消息（`<analysis>` 草稿 + 9 节 `<summary>`，P67；偶发失败先重试 2 次再回退抽取式，P72；prompt 超长时丢最旧 20% 消息 + cap 缩 20% 收缩重试最多 3 轮，P73），token 驱动保留窗口随压缩目标缩放（P68）；旧摘要整条前传且剥离恢复附件防淹没（P67.5/P72），收缩丢弃时也绝不丢头部旧摘要（P73）
  3. SlidingWindow — 滑动窗口兜底，三重锚点：孤儿工具对防护 + 任务锚点（最新 USER 消息）+ 摘要锚点（P71，绝不删刚生成的摘要）
- 压缩后恢复注入：最近请求 + 已读文件清单 + 文件内容（预算 min(25K, 窗口//4) 随窗口缩放，P70）+ **skill 调用记录**（激活中标注勿重复激活、已停用单列；边界持久化、会话恢复重建激活集合不重注入 prompt）
- 手动入口：`/compact` 命令

**验证**：12 个单测 + 压缩链专项 20+ 单测；九轮真实终端无污染埋点验证（虚构约定穿透多轮压缩后五问全中，JSON 判定答案唯一来源为摘要）

---

### ✅ 9. 跨会话记忆系统

**要求**：项目级 + 用户级记忆，多次会话之间持续积累理解。

**实现**（`memory/persistent.py` + `extraction.py` + `session_store.py`）：
- 双层存储：项目级 `.mini-agent/memory.json`（项目约定）+ 用户级 `~/.mini-agent/memory/`（跨项目偏好）
- 自动提取：MemoryExtractor 从对话中提取 "always/prefer/don't" 类偏好，自动去重入库
- 手动管理：`/memory add <内容>` 添加、`/memory` 查看、`/memory export/import` 导出导入（mewcode 兼容 .md 互操作格式，comparison 4.6）
- 会话持久化：`/session save/new/list/load/delete/tag/untag/tags` — 完整对话（含工具调用）JSON 序列化，重启后恢复继续；`new` 安全另起新会话（旧会话完整存盘标记正常关闭）；`tag` 分类标签；`list` 默认最近 20 条（`--page N` 翻页、`--all` 全部、`--tag` 过滤，可组合）
- 会话自动清理（comparison 9.1）：启动时 `cleanup_stale` 删除超龄会话——正常关闭超 30 天（`session_cleanup_days`）+ 崩溃会话超 40 天（`crashed_session_cleanup_days`），均可配（0 = 禁用）
- 压缩边界标记（comparison 9.2）：压缩后记录 `compact_boundary`（摘要 + 已读文件清单与内容 + 用户最近请求 + 技能调用记录/激活集合），会话恢复时跳过已归档消息、从边界重建并恢复已读文件状态与技能激活状态——防止压缩-重读膨胀循环的入口

**验证**：15 个单测（CRUD/搜索/提取/去重/序列化往返） + 4 个清理测试 + 6 个边界测试（4 单元 + 2 集成）

---

### ✅ 10. SubAgent 子任务分发

**要求**：把任务委派给独立的子 Agent 并行执行，复杂任务速度拉满。

**实现**（`core/subagent.py`）：
- SubAgent：复用 AgentLoop，每个子 Agent 拥有独立对话上下文 + 克隆的工具注册表（可白名单限制）+ 独立工作目录
- 4 种 Agent 类型（P48）：explore/plan/verify 只读档案 + worker 全能档案，各带专属 prompt/工具白名单/迭代预算；未指定类型回退默认 worker 档案（P80，保留 config 迭代预算）
- SubAgentManager：spawn（asyncio.create_task 后台启动）/ spawn_parallel（批量并发）/ wait_all（gather 收集）/ cancel / timeout 超时取消
- 权限栈传导：SubAgentManager 持有主 PermissionManager（app.py 传入），spawn 时经 `child_view()` 给每个进程内子 Agent 注入 ChildPermissionManager 子视图——规则/会话授权/写文件集与父级按引用共享（运行中 /allow /deny 对子 Agent 立即生效）、mode 实时委托父级（/mode 切换即时传导）、需弹窗的请求一律失败安全拒绝（消解并发确认框交错问题；诚实边界：子 Agent 危险操作只能拒不能问——人工放行需跨 loop 确认队列，暂无场景不做）；此前进程内子 Agent 完全没有权限门控（只有 pane worker 有）
- 失败即数据：子 Agent 异常转 SubAgentResult(success=False)，不炸编排
- Mailbox 跨 Agent 通信（P58）：共享文件式收件箱，SubAgent 运行中通过 send_message 互发消息、wait_message 阻塞等待；spawn_parallel 预生成 id 让兄弟 Agent 互见（id + 任务摘要）
- Mailbox 增强（P58.4）：`to='*'` 广播、request/response 结构化协议（request_id 配对 + approve 表态）、名字寻址（spawn_agents names 参数）、会话级审计留痕（drain 标记已读留盘）
- 多后端 spawn（comparison 6.4）：`/spawn --pane` 把 SubAgent 跑进可见终端窗格（tmux 分屏 / **Windows Terminal** 分屏或共享窗口标签页——任意终端装了 wt 即可用，独立进程实时观看）；`--wait` 一条命令派发+进度面板+结果；Mailbox 跨进程改造（O_EXCL 文件锁 + 原子写 + 磁盘注册表，4 进程并发写零丢失实测）；worker 协议（spec JSON 进 → 结果 JSON 出，协议文件隔离在工作目录外 + schema 双校验防 LLM 早产桩）；worker 崩溃护栏 + Provider 429 退避重试；真实 LLM 跨进程 E2E + 六轮交互实测迭代
- 后台派发 + 自动投递：spawn_agents 工具 `background=true` 立即返回，LLM 继续其他工作；子 agent 完成时经 mailbox 向 main 投递含结果的通知（截断 4000 字符），自动中断输入等待并触发 agent loop 处理结果（无需用户手动输入）；终端同步提示完成；工具默认仍阻塞。**`/spawn` 命令默认即后台自动投递**（无需 `--background`，`--wait` 为阻塞式 opt-in）
- 摘要式上下文 fork：spawn_agents 工具 `inherit_context=true` / `/spawn --fork` 把父对话的 LLM 摘要（P67 9 节结构，失败回退提取式 digest）注入子 agent system prompt——"按我们讨论的去做"类任务子 agent 出生即知上下文；冻结快照回避 fork 一致性问题，与 background 可组合（background+fork 时摘要+spawn 整体后台执行、立即返回）；摘要生成期间终端提示+trace 可见（`ContextSummaryStartEvent`/`ContextSummaryDoneEvent`）

**验证**：8 个单测含并行计时断言（3 个 0.1s Agent 并行 <0.35s）；真实 API E2E：2 个 Agent 并行读不同文件 2.3 秒各自正确报告

---

### ✅ 11. Git Worktree 并行隔离

**要求**：多个 Agent 同时改代码自动放进不同 Git 工作树，互相不打架。

**实现**（`security/worktree.py`）：
- WorktreeManager：create（新分支+工作树到 `.mini-agent/worktrees/`）/ remove（脏树保护，未提交变更拒绝删除）/ list / status / merge_back（--no-ff 合并 + 冲突检测 + 自动 abort 保持仓库干净）
- 自动接入：`SubAgentManager.spawn(isolation="worktree")` 自动创建工作树并把子 Agent 的 working_dir 切进去——多个 Agent 的文件修改天然隔离
- TeamConfig.isolation="worktree" 让整个团队每个成员各占一棵工作树

**验证**：6 个真实 git 仓库集成测试（创建/脏树保护/合并/冲突）

---

### ✅ 12. Agent Teams 多 Agent 团队

**要求**：组建长期协作的 Agent 团队，处理跨多个领域的大型项目。

**实现**（`core/team.py` + `core/planner.py`）：
- TeamMember：名称 + 角色（backend/frontend/tester...）+ 工具白名单
- Planner：LLM 结构化任务分解（JSON 输出，三级解析容错）
- AgentTeam 编排（Orchestrator 策略）：分解大任务 → 按角色匹配成员 → 并行 spawn（可 worktree 隔离）→ wait_all 收集 → TeamRunReport 汇总（每步状态+输出摘要）；`--coordinator` 模式 Planner 纯调度（prompt 强化 + max_steps 放宽 + 扫描加深，P45）

**验证**：5+6 个单测；真实 API E2E：Planner 分解调研任务 → 2 角色成员并行执行 → 汇总 success=True

---

## 第二部分：6 大技术层面

### ✅ 层面 1：基础对话能力

| 要求点 | 实现 |
|---|---|
| System Prompt 工程 | `app.py` SYSTEM_PROMPT — 动态注入工作目录/平台/shell/当前模型名，平台感知命令指引，工具使用准则 |
| LLM API | httpx 直连（不依赖厂商 SDK），OpenAI Chat Completions + OpenAI Responses API（o1/o3/o4-mini，含 thinking round-trip + tool pairing repair + 错误分类）+ Anthropic 三 Provider，注册表工厂模式，`/model` 多模型热切换，上下文窗口 API 自动探测（P42） |
| 流式响应 | SSE 逐行解析 → StreamChunk 统一抽象 → Rich Live 实时渲染；截断恢复——finish_reason="length" 自动翻倍 max_tokens 重试最多 3 次（P44） |
| 多轮对话 | Conversation 全量重放，工具调用配对协议（tool_calls ↔ tool_call_id） |
| 对话管理器 | Conversation 类：append / to_api_messages / token 累计（窗口截取由 ContextManager/Compressor 负责） |

### ✅ 层面 2：Agent 核心机制

| 要求点 | 实现 |
|---|---|
| Function Calling | OpenAI tool_calls 格式（碎片化 delta 增量组装）+ Anthropic tool_use 格式（双向转换） |
| Tools 工具系统 | Tool ABC（schema + execute 双成员）+ ToolRegistry（注册/克隆/过滤）+ 参数校验 |
| ReAct 范式 | think → act → observe 循环，失败即数据（错误回传 LLM 自纠错） |
| Agent Loop 主循环 | `core/agent_loop.py` 状态机（8 个 AgentPhase），四重熔断护栏 |
| 事件流 | `events/bus.py` 异步发布订阅 EventBus（on/on_any/off/off_any，handler 异常隔离并记日志），14 种类型化事件贯穿全部组件，5 个内置订阅者共 17 个订阅（Trace 8/Audit 4/Teach 2/Recorder 2/Cost 1）；`listener_dirs` 目录 *.py 插件零代码接入全局监听 |

### ✅ 层面 3：能力拓展协议

| 要求点 | 实现 |
|---|---|
| MCP 协议 | JSON-RPC 握手 + 工具发现 + Adapter 透明挂载（见核心功能 4） |
| Skill 技能包 | SKILL.md 装载/激活/触发（见核心功能 5） |
| Slash Command | 26 内置 + 自定义注册 + 下拉补全（见核心功能 6） |
| Hook 生命周期钩子 | 11 阶段 × 6 裁决 + 优先级链 + 短路 + 条件表达式 + 模板变量（见核心功能 7） |
| 插件生态 | pip 包（`mini_agent.plugins` entry point）/ 本地 `.py` 文件（`plugin_dirs`）注册工具/命令/技能，四钩子契约 + 三层异常隔离，`/plugins` 展示 |

### ✅ 层面 4：工程化功能

| 要求点 | 实现 |
|---|---|
| 权限防御 | 评估顺序 DENY→ALLOW→Session→Default；三级 scope（command/path/tool，工具级门先于资源检查）；deny 规则匹配包装与串联命令（解包 cmd /c / cmd /k / powershell -Command / sh -c 前缀 + 抹引号后逐 `&;|` 段匹配，allow 规则不解包——扩大 deny 收紧、扩大 allow 放松；解包是纵深防御非围墙，深度混淆由危险命令确认层与 OS 沙箱兜底）；28 条危险命令正则（含内联解释器拦截 cmd /c 在内，删除类命令任意形态均拦截）+ 写后执行检测（record_written_file + is_executing_written_script）；确认拒绝熔断（任何确认框被拒——危险命令/项目外路径/hook 确认——连续 `max_consecutive_denials` 次后停止本回合、回问用户，默认 1——拒一次即停，防止被拒后继续找绕过路径；自动策略拒绝如敏感路径/deny 规则不计数、仅跳过继续）；三级路径策略；fail-safe 默认拒绝；`check()` 按 scope 分发的通用检查入口；`/allow` `/deny` 运行时动态管理规则（`--save` 持久化到 TOML）；pane worker 跨进程权限审批（RemoteConfirm 文件协议 + PENDING 事件）；OS 沙箱默认开启（Linux bwrap/unshare + macOS seatbelt + Windows 管理员 Low Integrity / 非管理员无文件保护——限制仅文档说明，无启动警告） |
| 上下文压缩 | 四级级联（DropToolResults → LLMSummarizeOldest → SummarizeOldest → SlidingWindow），双阈值（75% 软 + 90% 硬绕过熔断器），token 驱动保留窗口，聚合溢写，/compact 手动 |
| token 管理 | tiktoken/CJK 感知估算双路径 + API usage 锚点（P43）+ LRU 缓存 + 每轮界面显示 |
| 上下文溢写 | 压缩不达标时 SlidingWindow 强制截断兜底 |
| 跨会话记忆 | 项目级 + 用户级双层 JSON 存储 + 关键词/标签搜索 |
| 会话持久化 | SessionStore 完整序列化（含 ToolCall/ToolResult），/session 全套命令（含 new 安全另起），启动时自动清理超龄会话（正常 30 天 + 崩溃 40 天，可配置） |
| 记忆提取 | MemoryExtractor 从对话自动提取偏好/约定/约束，去重入库 |

### ✅ 层面 5：多 Agent 协作

| 要求点 | 实现 |
|---|---|
| SubAgent 子任务分发 | asyncio 真并行（E2E 计时验证），独立上下文/工具表/工作目录 |
| Git Worktree 并行隔离 | spawn(isolation="worktree") 自动建树，脏树保护，合并回主分支 |
| Agent Teams 团队协作 | Planner 分解 + 角色匹配 + 并行编排 + 报告汇总 |
| Mailbox 跨 Agent 通信 | 文件式 JSON 收件箱 + send_message/wait_message 工具，Agent 运行中互发消息（P58）；广播/结构化协议/名字寻址/审计留痕（P58.4）；真实 LLM 验证 4 类拓扑（单向/汇聚/判别寻址/双向乒乓） |

### ✅ 层面 6：Spec 开发模式 + CLAUDE 项目指令

| 要求点 | 实现 |
|---|---|
| spec.md | `docs/spec.md` — 15 章完整架构规格（目录结构/分层架构/数据模型/模块接口/数据流/状态机/安全模型/开发阶段） |
| tasks.md | `docs/tasks.md` — P1-P83 全部任务清单，逐项打勾并附验证依据 |
| checklist.md | `docs/checklist.md` — 每阶段验收检查清单，全部核查通过 |
| CLAUDE.md | 项目根目录 — 常用命令/架构要点/代码规范的项目指令 |
| 附加文档 | 18 个文档（14 个专题 + 4 个英文版指南）：tech-notes（技术原理）、roadmap（演进路线，含代码质量清单）、agent-architecture（架构解析）、guide/（config/commands/output/terminal 四指南，另有 guide/en/ 纯英文版 ×4）、comparison-mewcode（mewcode 对比）、comparison-config-cc（CC 配置对比）、positioning 等，及本文档 |

---

## 第三部分：总体质量证据

| 维度 | 数据 |
|---|---|
| 源文件 | 112 个 Python 文件，五层架构（交互/引擎/工具/记忆/安全）+ EventBus 解耦 |
| 测试 | 1201 个测试全部通过（1 skipped，约 100 秒，零网络依赖），单元 64 文件 + 集成 5 文件 |
| 工具 | 20 个内置工具（read_file / write_file / edit_file / delete_file / bash / glob / grep / spawn_agents / send_message / wait_message / tool_search / mcp_call / ask_user / exit_plan_mode / task_create / task_get / task_list / task_update / load_skill / install_skill），LLM 自主决定使用 |
| CI | GitHub Actions 三个 Job（Lint / Test 双 Python 版本 / Build）全绿 |
| E2E | 真实 LLM API 验证：自主工具调用、并行 SubAgent、Team 编排、流式渲染、/trace 全链路 |
| 评测 | 10 个标准编程任务 **10/10 通过**，总成本 $0.0015，详见 `benchmarks/README.md` |
| 机制透明 | `/trace` 命令实时展示 ReAct 内部状态（阶段/权限判定+依据/工具耗时/LLM 元信息）——商用 Agent 给不了的白盒能力 |
| 垂直场景 | `/explain` 教学模式（TeachRenderer 确定性面板 + Skill 辅助）+ `/audit` 合规审计（哈希链防篡改 JSONL + `/audit verify` 完整性校验）+ offline-ollama 内网离线 Skill——"因为拥有源码所以能做"的三个活证据 |
| 机制实验 | `experiments/` 10 个实验脚本：压缩策略 A/B（发现：压缩的隐性代价是重复劳动，工具调用翻 2-5 倍）、强弱模型混编（发现：strong-weak 帕累托最优）、死循环诱导（发现：迭代上限是唯一可靠硬熔断→已升级 v2）、压缩熔断器验证、摘要 prompt 验证、token 保留窗口验证、摘要召回验证、默认 Agent 类型验证、工具权限验证、跨进程 PENDING 协议验证——从"做了个项目"到"做了研究" |
| 流式中断 | 双 Esc 优雅中断流式输出（守护线程 + cancelled 标志），不用 Ctrl+C 冒险杀进程 |
| 长记忆自动化 | PRE_LLM hook 自动注入记忆 + SESSION_END hook 自动提取偏好——用户无感知的跨会话记忆 |
| 溢出兜底 | 发送前 token 预检（P20）+ 超限强制 SlidingWindow 截断——三级压缩走完仍超窗时的最终防线，杜绝 API 400 |
| TOML 配置 | 用户级 + 项目级 `config.toml`（P21），Python 3.11 tomllib 零依赖，七层优先级栈（spec.md 13.3 设计的完整落地） |
| Diff 预览 | edit_file 成功后整行背景色彩色 diff（P23）——删除行深红底、新增行深绿底，一眼看出改了什么 |
| Streaming 中间态 | LLM 生成工具调用参数时立即显示工具名（P23）——不再等 JSON 组装完才冒出工具行 |
| 文件变更汇总 | 轮次结束显示本轮新建（+绿）/修改（~黄）/删除（-红）的文件清单（P24）——多文件操作一目了然 |
| 上下文感知 | 启动自动注入 AGENT.md/CLAUDE.md/instructions.md 项目指令 + 用户级全局指令（P25）——LLM 无需读文件即知项目约定；**@-include 递归引用**：指令文件中整行 `@./path` / `@~/path` 展开为引用文件内容（深度 5 可配置，循环/缺失注释降级） |
| 对话分叉/回滚 | `/undo` 回滚 N 轮 + `/fork` 分叉新会话原线保留（P26）——CC 无此能力（服务端历史不可操作），本地自持有 Conversation 的差异化优势；P27 进一步支持操作级撤销（undo 连文件一起恢复） |
| 工具链录制/回放 | `/record` 录制工具调用序列 + `/replay` 零 LLM 确定性重放（P28）——例行操作录一次永久复用，CC 无此能力 |
| 成本仪表盘 | `/cost` 按模型分账 input/output 计价 + 会话预算警告（P29）——按量付费用户的刚需，CC 订阅制无此功能 |
| LLM 记忆提取 | MemoryExtractor 从 regex 升级为 LLM 结构化提取（P30）——理解语义不依赖关键词，覆盖率质变 |
| MCP HTTP Transport | HTTPTransport 远程 MCP 服务器连接 + app 启动自动发现（P31）——P5 预留的 MCP 架构终于接通，支持 headers 认证 |
| 持久化任务系统 | `/todo` 命令 + TaskStore 磁盘持久 + blockedBy 依赖追踪（P32）+ 歧义前缀检测 + 最短唯一前缀显示（P74）——S12 补全，S01-S20 覆盖 19/20 |
| PyPI 发布 | `pip install mini-code-agent` 一行安装（P33）——元数据补全 + MIT LICENSE + tag 触发自动发布 workflow |
| Windows 终端适配 | UTF-8 加固/流式防重影/按键防吞/无控制台兜底/emoji 降级（P34）——CMD/PowerShell/Windows Terminal 全兼容；P34.3 补修 bash GBK 解码、git 命令确认闸门、Git Bash（mintty）降级运行与代理字符清洗，各终端指南见 guide/terminal-guide.md |
| 注释 | 全部英文注释附中文翻译（约 336 条） |

## 早期简化项（全部已升级）

以下为 mini 早期实现的合理取舍，**已在后续阶段全部升级**：

1. ✅ 压缩链 Stage 2 已默认使用 LLM 语义摘要（P64.2，`llm_summarize=True`），失败自动回退提取式
2. ✅ 记忆提取已从正则升级为 LLM 结构化提取（P30）
3. ✅ MCP HTTP transport 已实现（P31，含 headers 认证 + SSE）
4. ✅ 多个 tool_calls 已改为权限预检串行 + 执行并行（P17，asyncio.gather + 审计锁）；P38 进一步升级为流式执行（组装完成即跑，不等流结束）

---

**结论：18 项需求（12 项核心功能 + 6 大技术层面）全部正确实现，每项均有代码位置、实现方式与测试证据支撑。**