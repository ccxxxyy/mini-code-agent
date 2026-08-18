# Agent 架构原理与实现解析

> 基于 [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) S01–S20 框架，
> 以 Mini-Code-Agent 的实际实现为例，解析每一层在解决什么问题、为什么需要它、
> 以及如何判断一个 Agent 框架是否完善。

---

## 一、Agent 的本质公式

```
Harness = Tools + Knowledge + Observation + Action Interfaces + Permissions
```

**模型是司机，Harness 是车。** 模型提供推理能力（Agency），Harness 让这种能力落地为可控、可观测、可扩展的软件系统。S01–S20 的 20 层机制就是这辆"车"的每个零件——缺一个不影响启动，但会在特定场景下暴露短板。

---

## 二、20 层逐层解析

### S01 — Agent Loop（核心循环）

**金句**："One loop & Bash is all you need"

**解决的问题**：LLM 只能返回文本——怎么让它"做事"而不只是"说话"？

**为什么需要**：把 LLM 的输出从"回答"变成"行动"的关键转换。没有循环，LLM 只是聊天机器人；有了循环，它变成 Agent。

**核心模式**：
```
while True:
    response = LLM(messages)
    if response.has_tool_calls:
        results = execute_tools(response.tool_calls)
        messages.append(results)  # 观察结果回传
        continue  # 继续思考
    else:
        break  # 最终回答
```

**本项目实现**：`core/agent_loop.py` 的 ReAct 循环——THINK（调 LLM）→ ACT（执行工具）→ OBSERVE（结果回传）。所有其他 19 层机制都是**挂在这个循环上**的，循环本身从不修改。

**判断标准**：一个 Agent 框架如果没有显式的循环+工具调用检测+结果回传，它可能只是一个 prompt wrapper，不是真正的 Agent。

---

### S02 — Tool Use（工具调度）

**金句**："加一个工具，只加一个 handler"

**解决的问题**：Agent 需要和真实世界交互（读写文件、执行命令、搜索代码），怎么让新工具的添加不影响循环？

**为什么需要**：工具是 Agent 的"手"——没有工具，Agent 只能纸上谈兵。但工具会不断增加（今天 6 个，明天可能 20 个），如果每加一个就改循环代码，系统会变得不可维护。

**核心原则**：
- 工具通过**声明式注册**（schema 描述 + handler 函数）加入系统
- 循环代码**永不修改**——只改注册表
- 工具的 schema 必须：描述清晰、参数简洁、边界明确、错误处理完善

**工具设计四原则**（从本项目 12 个内置工具中提炼）：

| 原则 | 正例 | 反例 |
|---|---|---|
| **描述清晰** | "Replace an exact string in a file" | "Edit a file"（太模糊，LLM 不知道是全文替换还是追加） |
| **参数简洁** | `file_path + old_text + new_text` | 把 diff 格式/行号/正则都塞进参数（LLM 容易出错） |
| **边界明确** | edit_file 要求 old_text 唯一匹配，否则报错让 LLM 加上下文 | 静默替换第一个匹配（LLM 不知道改对了没有） |
| **错误处理完善** | "old_text appears 3 times, provide more context" | 抛 Python 异常让 LLM 看到堆栈（无法理解） |

**本项目实现**：`tools/base.py` Tool ABC + ToolRegistry dispatch。12 个工具各自独立文件，注册到 registry 后循环通过名字分发，零耦合。

**判断标准**：框架是否允许"零改动加工具"？工具 schema 是否对 LLM 友好（不是对程序员友好）？

---

### S03 — Permission（权限治理）

**金句**："先划边界，再给自由"

**解决的问题**：Agent 有了工具就能改文件、执行命令——怎么防止它 `rm -rf /` 或读取 `~/.ssh/`？

**为什么需要**：不受限的 Agent 是危险的。用户必须能控制"哪些操作自动放行、哪些需要确认、哪些绝对禁止"。这不是事后补丁，是从第一天就要设计的。

**核心模式**：工具执行前过一道门控——自动放行 / 弹窗确认 / 直接拒绝。

**本项目实现**：`security/permission.py` PermissionManager + `security/path_guard.py` 路径守卫。项目内路径自动放行，`~/.ssh` 等敏感路径直接拒绝，项目外路径弹确认。三级模式（allow/ask/deny）可配。P34.3 实战加固：LLM 曾擅自执行 git commit——DANGEROUS_COMMAND_PATTERNS 扩充为拦截全部 git 状态修改命令（commit/push/reset/stash/rebase/checkout/restore/clean 均需确认），印证"提示词是软约束、权限确认是硬闸门"。P78 增加运行时规则管理：`/allow` `/deny` 斜杠命令动态添加规则，`--save` 持久化到 TOML 文件。P79 补上工具级 scope：`/deny tool delete_file` 直接拦掉整个工具（在命令/路径检查之前评估），`check()` 重构为按 scope 分发的通用检查入口。

**判断标准**：框架有没有工具执行前的权限检查？危险命令（rm、sudo）有没有拦截？用户能不能控制拦截策略（不仅能在启动前配文件，还能在运行中动态调整）？

---

### S04 — Hooks（生命周期钩子）

**金句**："挂在循环上，不写进循环里"

**解决的问题**：怎么在不修改核心循环的前提下，在特定时机注入行为（日志、记忆注入、审计、拦截）？

**为什么需要**：循环必须保持简单——它是系统的骨架，不能塞满业务逻辑。但你需要在"工具执行前记日志"、"LLM 调用前注入记忆"、"会话结束时提取偏好"这些时机做事。Hook 让这些需求以**外挂**方式接入，而非内嵌。

**核心原则**：循环提供插入点（PRE_TOOL / POST_TOOL / PRE_LLM / SESSION_END 等），外部注册 handler。Handler 可以 BLOCK（拦截）、MODIFY（修改参数）、或只做旁路操作（记日志）。

**本项目实现**：`tools/hooks.py` HookManager 支持 7 个 HookStage。实际挂载：PRE_LLM 注入记忆、SESSION_END 提取偏好、PRE_TOOL/POST_TOOL 审计。另有 `[[hooks]]` TOML 声明式规则（comparison 7.2）——用户零代码声明"什么工具调用要被拒绝或需要确认"（tool fnmatch + contains/regex 匹配），启动时自动注册为 PRE_TOOL hook：`action = "block"`（默认）直接拒绝，`action = "confirm"` 弹 y/a/n 确认框由用户裁决（裁决在 agent_loop，经 app 注入的 terminal.confirm 执行；无 UI 安全拒绝），配置方法见 config-guide.md。

**判断标准**：框架是否提供工具执行前后的扩展点？能不能在不改源码的情况下加审计/拦截？

---

### S05 — Planning（任务规划）

**金句**："没有计划的 Agent 走哪算哪"

**解决的问题**：复杂任务需要多步执行——Agent 是一步步盲干，还是先列计划再按步执行？

**为什么需要**：实验证明，先规划再执行的 Agent 完成率翻倍。规划把"模糊的大任务"拆成"明确的小步骤"，每步有清晰的目标和依赖关系。

**本项目实现**：`core/planner.py` Planner + PlanStep（含 depends_on 依赖图）。`/team` 命令触发：LLM 生成带依赖的计划 → 按依赖分批并行执行。

**判断标准**：Agent 面对复杂任务是否有规划能力？规划结果是否有依赖关系（而非简单的线性列表）？

---

### S06 — Subagent（子代理）

**金句**："大任务拆小，每个小任务干净的上下文"

**解决的问题**：一个 Agent 的上下文窗口有限且会被噪音污染——怎么并行处理独立子任务？

**为什么需要**：子代理有自己**独立的对话历史**（fresh messages[]），互不干扰。父代理只收取结果摘要，上下文保持干净。没有子代理，做 10 件独立的事就要 10 倍的上下文。

**本项目实现**：`core/subagent.py` SubAgent（独立 Conversation + ToolRegistry 克隆 + 递归防护）。`/spawn` 手动派生、spawn_agents 工具让 LLM 自主派生（S17）。4 种 Agent 类型档案（explore/plan/worker/verify，P48），未指定类型回退 `DEFAULT_AGENT_TYPE`（worker）档案且保留配置的迭代预算（P80）。P58 起子代理不再是"派出去等结果"：`core/mailbox.py` 文件式收件箱 + send_message/wait_message 工具，兄弟代理与主代理运行中互发消息（AgentLoop 每轮 THINK 前 drain 收件箱注入对话）。

**判断标准**：子代理是否有独立的上下文？父子之间是否只传递结果而非完整历史？

---

### S07 — Skill Loading（技能加载）

**金句**："用到时再加载，别全塞 prompt 里"

**解决的问题**：Agent 可能需要领域知识（代码审查规范、部署流程），但全部塞进 system prompt 会浪费 token 且降低相关性。

**为什么需要**：按需加载——Agent 知道有哪些技能可用（manifest），需要时再展开注入。节省 token 且提高命中率。

**本项目实现**：`extensions/skills.py` SkillRegistry，扫描 SKILL.md 文件，trigger 关键词自动匹配或 `/skill activate` 手动激活。4 个内置技能（code-review / init-project / offline-ollama / teach-mode）。

**判断标准**：知识/指令是塞在 system prompt 里的还是按需加载的？有没有技能发现+激活机制？

---

### S08 — Context Compression（上下文压缩）

**金句**："上下文总会满，要有办法腾地方"

**解决的问题**：对话越长 token 越多——超过窗口就崩。怎么在不丢失关键信息的前提下压缩历史？

**为什么需要**：这不是"可能"需要，而是"一定"需要——任何长对话的 Agent 不做压缩就一定会撞墙（API 400）。

**核心模式**：多级策略，先便宜后昂贵：
1. 裁剪大工具输出（几乎零成本）
2. 摘要式压缩旧消息（中等成本）
3. LLM 总结（高成本但高质量）
4. 滑动窗口兜底（暴力截断，最后防线）

**本项目实现**：`memory/compressor.py` 三级级联 + `memory/context.py` 75% 阈值触发 + `agent_loop.py` 发送前溢出兜底（P20）。

**判断标准**：Agent 对话 100 轮后还能工作吗？有没有多级压缩策略？有没有最终的溢出兜底？

---

### S09 — Memory（跨会话记忆）

**金句**："记住该记的，忘掉该忘的"

**解决的问题**：会话结束后所有上下文丢失——下次开 Agent 又要重头解释自己的偏好。

**为什么需要**：三个子系统——**选择**（什么值得记）、**提取**（从对话中抽取）、**整合**（去重合并）。不是所有信息都值得记——"你好"不值得，"我喜欢简洁注释"值得。

**本项目实现**：`memory/persistent.py` PersistentMemory + `memory/extraction.py` LLM 结构化提取（P30 从 regex 升级）+ PRE_LLM hook 自动注入。三类提取：preference / convention / fact。60% 词重叠去重。

**判断标准**：Agent 重启后还记得上次的偏好吗？记忆是自动提取的还是必须手动？有没有去重防膨胀？

---

### S10 — System Prompt（动态提示组装）

**金句**："prompt 是组装出来的，不是写死的"

**解决的问题**：不同场景需要不同的 system prompt 内容——硬编码一个固定 prompt 无法适应变化。

**为什么需要**：System prompt 应该是多个片段的运行时拼接——基础身份 + 工具描述 + 项目指令 + 记忆 + 技能 prompt。不同会话、不同项目、不同技能激活状态下，prompt 内容不同。

**本项目实现**：`app.py` SYSTEM_PROMPT 模板（{model}/{working_dir}/{platform}/{shell} 占位符）+ 项目指令注入（P25 CLAUDE.md/AGENT.md）+ 记忆注入（PRE_LLM hook）+ 技能 prompt（activate 时拼接）。

**判断标准**：System prompt 是硬编码的还是运行时组装的？能不能根据上下文动态变化？

---

### S11 — Error Recovery（错误恢复）

**金句**："错误不是终点，是重试的起点"

**解决的问题**：API 调用失败、上下文太长、模型拒绝——Agent 是直接崩溃还是能自恢复？

**为什么需要**：真实环境里错误是常态。一个健壮的 Agent 应该：重试失败操作、压缩过长上下文、在必要时切换模型。

**本项目实现**：`app.py` `_friendly_error`（HTTP 异常转用户友好提示）+ `core/agent_state.py` 熔断器（双层死循环检测：同签名 6 次 + 同工具名连续 8 轮，防无限递归）+ 溢出兜底（P20）+ `stopped_early` 标志优雅终止。

**判断标准**：Agent 遇到 API 错误会直接崩溃还是有恢复策略？有没有防无限循环的熔断？

---

### S12 — Task System（持久化任务系统）

**金句**："大目标拆成小任务，排好序，持久化"

**解决的问题**：用户有一个包含多步的目标——怎么把它拆成可跟踪、有依赖、可持久化的任务列表？

**为什么需要**：任务系统是多 Agent 协作的基础。没有持久化，关了程序进度就没了；没有依赖图，并行任务无法正确调度。

**本项目实现**：`core/task_store.py` TaskRecord（id/description/status/blocked_by）+ TaskStore JSON 持久化。`/todo` 命令管理任务列表。依赖图支持多入汇聚（A→C, B→C）。done 时提示 unblocked 的下游任务。ID 前缀匹配带歧义检测（AmbiguousTaskError），显示用 min_unique_prefix() 自动最短唯一前缀。

**判断标准**：任务能不能跨会话持久？有没有 blockedBy 依赖关系？任务完成后能不能自动解锁下游？

---

### S13 — Background Tasks（后台执行）

**金句**："慢操作丢后台，Agent 继续思考"

**解决的问题**：某些工具执行很慢（编译、测试）——Agent 是卡在那等，还是能继续处理其他事？

**为什么需要**：串行等待浪费时间。后台执行+完成通知让 Agent 的吞吐量成倍提升。

**本项目实现**：`core/subagent.py` SubAgentManager.spawn() 使用 `asyncio.create_task` 后台执行。`/spawn wait` 收集结果，`/spawn cancel` 取消。工具并行（P17）用 asyncio.gather。

**判断标准**：长操作能不能后台运行？Agent 在等待时能不能处理其他输入？

---

### S14 — Cron Scheduler（定时调度）

**金句**："定时触发，不需要人推"

**解决的问题**：某些操作需要定期自动执行——怎么让 Agent 不依赖人工触发？

**本项目决策**：**有意不实现。** 终端交互工具的定时调度用 OS 的 cron / Task Scheduler 更合适——内置 cron 引擎投入高收益低，且和"按需交互"的产品定位矛盾。CC 也没有内置 cron。

**判断标准**：需要定时调度的场景应该考虑是否适合内置还是委托给 OS 工具。

---

### S15 — Agent Teams（团队协作）

**金句**："一个搞不定，组队来"

**解决的问题**：复杂任务需要多个 Agent 各负其责——怎么协调它们？

**为什么需要**：单 Agent 的能力有上限——上下文有限、专注力分散。团队让不同 Agent 专注不同子任务，通过结构化通信协调。

**本项目实现**：`core/team.py` AgentTeam——Planner 分解任务 + SubAgent 按依赖分批执行 + 依赖输出转发 + 失败级联。`/team` 命令一键启动。

**判断标准**：多个 Agent 能不能协作完成一个任务？有没有分工机制？结果怎么汇聚？

---

### S16 — Team Protocols（团队协议）

**金句**："队友之间要有约定"

**解决的问题**：Agent 之间怎么传递信息？格式是什么？依赖怎么表达？

**本项目实现**：PlanStep 的 depends_on 创建依赖图 → 无依赖的步骤并行、有依赖的等前置完成 → 前置步骤的输出通过 `_build_dep_context` 转发给后续步骤 → 前置失败时级联标记后续为 failed。

**判断标准**：Agent 之间有没有结构化的通信协议？依赖传递是否正确（输出转发、失败级联）？

---

### S17 — Autonomous Agents（自主代理）

**金句**："队友自己看板，有活就认领"

**解决的问题**：能不能让 LLM 自己决定是否需要派生子代理？而不是用户手动 /spawn。

**本项目实现**：`tools/builtin/spawn_agents.py` SpawnAgentsTool——注册为普通工具，LLM 在认为需要并行时**自主调用**。递归防护：子代理注销 spawn_agents 工具（防无限套娃）。P58 起同批派生的代理互相可见（id + 任务摘要写入 system prompt），可通过 send_message/wait_message 运行中协作；工具描述明示阻塞语义——需要通信的任务必须一次调用传入。

**判断标准**：LLM 能不能自主决定何时需要并行？有没有递归防护？

---

### S18 — Worktree Isolation（工作区隔离）

**金句**："各干各的目录，互不干扰"

**解决的问题**：多个 Agent 并行修改文件——怎么防止冲突？

**本项目实现**：`security/worktree.py` WorktreeManager——基于 git worktree，每个隔离任务在独立的分支和目录中工作，完成后可 merge_back。`/spawn --isolated` 触发。

**判断标准**：并行 Agent 修改文件时有没有隔离机制？改完怎么合并？

---

### S19 — MCP Plugin（外部工具协议）

**金句**："能力不够？插上 MCP"

**解决的问题**：内置工具有限——怎么让 Agent 无缝接入第三方工具服务器（GitHub、Notion、数据库）？

**为什么需要**：Agent 不可能内置所有工具。MCP（Model Context Protocol）是标准化的工具扩展协议——第三方写一个 MCP server，Agent 通过配置即可接入，无需改代码。

**本项目实现**：`tools/mcp/` 三层架构（transport/client/adapter）。支持 stdio（子进程）+ HTTP（远程服务器）双传输。MCPToolAdapter 把外部工具包装成和内置工具完全一样的 Tool 对象——Agent 看不出区别。config.toml `[mcp.servers.*]` 配置即连。

**判断标准**：Agent 能不能无代码接入外部工具？有没有标准化的工具扩展协议？多传输支持？

---

### S20 — Comprehensive Agent（完整集成）

**金句**："机制很多，循环一个"

**解决的问题**：前 19 层机制怎么组合成一个完整可用的 Agent？

**核心洞察**：所有机制都是**附加到**循环上的，不是**替代**循环。S01 的循环从头到尾没变过——权限在工具执行前门控（S03）、Hook 在循环插入点触发（S04）、压缩在上下文满时介入（S08）、子代理开新循环（S06）。架构是**洋葱模型**：循环在最内层，每层机制包裹在外面。

**本项目实现**：`app.py` Application 类——统一编排 AgentLoop + ToolRegistry + PermissionManager + HookManager + ContextManager + SubAgentManager + MCPManager + CostTracker + ToolRecorder + FileSnapshotStore + TaskStore + SkillRegistry + TraceRenderer + TeachRenderer + AuditLogger。一个类，所有机制。

---

## 三、如何判断一个 Agent 框架是否完善

用以下检查清单——每项对应一个 S 层：

| 检查项 | 对应 | 问法 |
|---|---|---|
| 核心循环 | S01 | 有没有显式的"调 LLM → 检查工具调用 → 执行 → 回传"循环？ |
| 工具扩展 | S02 | 加一个新工具需要改几个文件？理想答案：1 个（工具文件本身） |
| 权限控制 | S03 | 危险操作有没有拦截？用户能不能控制拦截策略？ |
| 扩展点 | S04 | 能不能在不改源码的情况下加审计/日志/拦截？ |
| 任务规划 | S05 | 复杂任务是一步步盲干还是先列计划？ |
| 子代理 | S06 | 子任务有独立上下文还是共享一个？ |
| 知识管理 | S07 | 领域知识是全塞 prompt 还是按需加载？ |
| 上下文压缩 | S08 | **对话 100 轮后还能工作吗？** |
| 跨会话记忆 | S09 | 重启后还记得用户偏好吗？ |
| 动态 prompt | S10 | System prompt 是硬编码还是运行时组装？ |
| 错误恢复 | S11 | API 挂了是崩溃还是重试？ |
| 任务持久化 | S12 | 关了程序任务进度还在吗？ |
| 后台执行 | S13 | 慢操作能不能后台跑？ |
| 团队协作 | S15 | 多 Agent 能不能分工合作？ |
| 并行调度 | S16 | **任务图能并行吗？** 依赖关系怎么处理？ |
| 自主决策 | S17 | LLM 能不能自己决定何时需要并行？ |
| 文件隔离 | S18 | 并行修改文件有没有冲突隔离？ |
| 外部扩展 | S19 | 能不能无代码接入第三方工具？ |
| 完整集成 | S20 | 所有机制是否统一在一个循环架构里？ |

一个框架不需要 20/20 全满分——但**缺哪个就意味着在对应场景下有短板**。知道缺什么比知道有什么更重要。

---

## 四、通用 Agent 开发原理（从本项目提炼）

### 4.1 循环不变，机制外挂

Agent 的核心循环（S01）**永远不改**——所有新能力都以以下三种方式接入：
- **注册**：工具注册到 ToolRegistry（S02）
- **订阅**：EventBus 订阅者（TraceRenderer 订阅 8 种事件 / AuditLogger 订阅 4 种事件 / CostTracker / ToolRecorder——都是纯订阅者，Agent 循环完全不知道它们的存在）；用户可零代码接入——`listener_dirs` 目录下的 *.py 插件（`register(bus)` 或 `on_event(event)` 契约）启动时经 `bus.on_any` 注册为全局监听，异常隔离不影响主流程
- **钩子**：HookManager 注册 handler（PRE_LLM 记忆注入 / SESSION_END 记忆提取）

这意味着你可以**拿掉任何一个机制**（如删掉 CostTracker），Agent 照常工作——机制是可插拔的。

### 4.2 数据所有权决定能力边界

本项目 Conversation 是本地 dataclass——所以 `/undo`（截断列表）和 `/fork`（deepcopy）天然可行。CC 的对话在服务端——所以它**做不到**这两个。

这不是实现细节，而是**架构决策**：谁拥有数据，谁就有操作数据的能力。选择本地持有数据 = 放弃云端协同但获得数据操控自由。

### 4.3 EventBus 解耦 > 直接调用

5 个 EventBus 纯订阅者（Trace / Teach / Audit / Recorder / Cost），Agent 循环只管 emit 事件，**不知道也不关心**有谁在监听。好处：
- 新增功能零改循环代码
- 订阅者互不影响（一个崩溃不影响其他）
- 可在运行时 attach/detach（/trace on/off）

### 4.4 安全是第零层，不是附加层

权限（S03）不是做完功能后"加固"的——它在工具执行管线里是**前置门控**。先检查权限，通过了才执行。PathGuard + PermissionManager + Hook 三层防护，每层独立判断。

### 4.5 "能力剥夺"优于"提示限制"

告诉 LLM "不要写文件"没有用——它可能不听。正确做法：**物理剥夺写文件的工具**（从 ToolRegistry 注销 write_file）。本项目的递归防护（子代理注销 spawn_agents）和 /team 的只读步骤（剥夺写工具）都是这个原则。

### 4.6 三层时间范围覆盖用户所有"到底花了多少"的疑问

| 层 | 范围 | 存储 |
|---|---|---|
| 每轮 | 一次提问到回答 | 内存（token 行即时显示） |
| 本次会话 | 启动到退出 | 内存（/cost 查看） |
| 累计总账 | 首次使用至今 | 磁盘（/cost 跨会话） |

CC 订阅制不需要这个——按量付费的工具需要。架构设计要**贴合用户的付费模型**。

---

## 五、举一反三从零构建一个 Agent

1. **从 S01 开始**——先跑通"LLM + 一个 bash 工具"的循环，确认工具调用能往返
2. **加 S02 的注册表**——让第二个工具的加入不碰循环代码
3. **立即加 S03 权限**——在工具执行前门控。不要等"做完功能再补安全"
4. **用 EventBus 而非直接调用**——从第一天就解耦。你未来会加的所有可观测性（日志/审计/追踪/成本）都是订阅者
5. **S08 上下文压缩不能拖**——对话超过 20 轮就需要了。没有压缩的 Agent 是演示品不是产品
6. **S06 子代理的关键是上下文隔离**——不是"多起一个 Agent"那么简单，核心是 fresh messages[]

**不需要一次全做**——但你应该**知道 20 层各在解决什么问题**，这样在碰到特定场景时知道该往哪个方向扩展。

---

*本文档对应 [learn-claude-code S01–S20 框架](https://github.com/shareAI-lab/learn-claude-code)，以 Mini-Code-Agent 的实际代码为实现佐证。*
