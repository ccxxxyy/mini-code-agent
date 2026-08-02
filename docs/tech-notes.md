# Mini-Code-Agent 核心技术实现原理与方案选型

本文档记录 P1-P3 阶段各核心技术的实现原理、设计权衡与方案选型理由，与 `spec.md`（架构规格）互补：spec 讲"是什么"，本文讲"为什么这么做"。

---

# 第一部分：P1 基础对话能力

## 1.1 LLM Provider 抽象层

### 要解决的问题

不同 LLM 服务（OpenAI、Claude、国内各家）的 API 格式、流式协议、工具调用格式都不同。如果代码直接依赖某一家的 SDK，切换模型就要改遍全身。

### 实现原理

定义一个抽象基类，把"所有 LLM 的共性"收敛为三个能力（`llm/base.py`）：

```
class LLMProvider(ABC):
    async def stream(messages, tools) -> AsyncIterator[StreamChunk]   # 流式生成
    def count_tokens(text) -> int                                     # token 计数
    context_window: int                                               # 窗口上限
```

上层（AgentLoop）只面向这个接口编程，具体 Provider 在启动时由工厂创建：

```
# llm/registry.py — 注册表 + 工厂模式
ProviderRegistry.register("openai", OpenAIProvider)
llm = ProviderRegistry.create(config.llm)   # 按配置字符串实例化
```

### 方案选型

| 候选方案 | 结论 | 理由 |
|---|---|---|
| 官方 SDK（openai/anthropic 包） | 弃用 | 重量级传递依赖；流式细节被封装难以控制；每加一家就多一个依赖 |
| LiteLLM 统一接入 | 弃用 | 依赖庞大；抽象层叠抽象层，出问题难调试 |
| **httpx 直连 + 自建抽象** | **采用** | 依赖只有 httpx；SSE 解析完全可控；OpenAI 兼容接口天然覆盖国内绝大多数服务 |

关键收益：任何提供 OpenAI 兼容接口的服务（DeepSeek、智谱、硅基流动、本地 Ollama）改一下 `base_url` 就能用，零代码改动。

## 1.2 流式响应：SSE 解析与增量组装

### 要解决的问题

"边想边输出"的体验要求逐 token 渲染；但 LLM 的工具调用是**碎片化传输**的——一个 `tool_call` 的名字和参数 JSON 被拆成多个 chunk 逐段下发：

```
chunk 1: {"index":0, "id":"call_abc", "function":{"name":"read_file"}}
chunk 2: {"index":0, "function":{"arguments":"{\"file_"}}
chunk 3: {"index":0, "function":{"arguments":"path\": \"a.py\"}"}}
```

### 实现原理

分两层处理（`llm/openai_provider.py`）：

1. **解析层 `_parse_chunk()`**：把每条 SSE 消息（`data: {json}` 行）转成统一的 `StreamChunk` 数据类——文本增量 `delta`、工具调用增量 `ToolCallDelta`、结束原因 `finish_reason`、用量 `usage`
2. **组装层 `assemble_response()`**：流结束后，按 `index` 归组所有 `ToolCallDelta`，拼接 `arguments` 字符串再 `json.loads`，还原出完整的 `ToolCall` 列表

```
# 组装核心：按 index 累积碎片
tool_call_builders[tcd.index]["arguments"] += tcd.arguments_delta
# 流结束后统一解析
parsed = json.loads(builder["arguments"])
```

### 设计权衡

- **文本与工具调用双路径**：文本 delta 实时推给 UI（即时渲染），工具调用必须等 JSON 完整才能解析，两条路径分离互不阻塞。
- **JSON 解析失败兜底为空字典**而非抛异常：个别模型偶发输出截断 JSON，宁可让工具因参数校验失败返回错误（LLM 看到错误会重试），也不让整个循环崩溃。
- **usage 从流中捕获**：请求带 `stream_options: {include_usage: true}`，最后一个 chunk 携带精确 token 用量，用于每轮统计显示。

## 1.3 消息模型与多轮对话

### 实现原理

对话历史是 Agent 的"工作记忆"。`models/message.py` 定义四种角色的统一消息结构：

```
Role: SYSTEM / USER / ASSISTANT / TOOL

Message:
  role, content
  tool_calls: list[ToolCall]        # ASSISTANT 发起工具调用时
  tool_result: ToolResult | None    # TOOL 角色回传结果时
  token_count, compressed, metadata
```

`Conversation` 持有消息列表，核心方法 `to_api_messages()` 负责把内部模型转成 OpenAI API 的 wire format——关键是**工具调用的配对协议**：

```
assistant 消息携带 tool_calls[{id, function:{name, arguments}}]
   ↓ 必须紧跟
tool 消息携带 tool_call_id 与之配对
```

只要每轮把完整历史传给 API，LLM 就能"记住"之前的对话——多轮上下文的本质就是**全量重放**。

### 设计权衡

- **不可变 vs 可变**：`ToolCall`/`ToolResult` 用 `frozen=True, slots=True`（它们是历史事实，产生后不应再改）；`Message` 可变（token_count 事后回填、compressed 标记压缩状态）。
- **`raw_arguments` 保留原始 JSON 字符串**：回传给 API 时用原文而非重新序列化，避免 dict 序列化顺序差异导致与模型输出不一致。

## 1.4 事件总线（EventBus）

### 要解决的问题

五层架构中，UI 要显示 LLM 流、记忆层要在轮次结束时提取、安全层要审计工具调用——如果层与层直接互相调用，会形成循环依赖的意大利面。

### 实现原理

`events/bus.py` 实现最小化的异步发布/订阅：

```
class EventBus:
    _handlers: dict[type, list[EventHandler]]   # 事件类型 → 处理器列表

    def on(event_type, handler)      # 订阅特定事件
    def on_any(handler)              # 订阅全部（日志/调试用）
    async def emit(event)            # 广播，asyncio.gather 并发分发
```

以**事件类的 type 对象**作为字典键做路由——`emit` 时 `type(event)` 精确匹配订阅者。所有处理器用 `asyncio.gather(..., return_exceptions=True)` 并发执行，单个处理器异常不影响其他订阅者。

事件类型定义在 `models/events.py`：UserMessageEvent、LLMStreamChunkEvent、ToolCallStart/EndEvent、AgentPhaseChangeEvent、TurnCompleteEvent、SessionStart/EndEvent 等，全部继承携带时间戳的 `Event` 基类。

### 方案选型

| 候选方案 | 结论 | 理由 |
|---|---|---|
| 层间直接调用 | 弃用 | UI ↔ Engine ↔ Memory 循环 import，无法解耦 |
| 第三方事件库（blinker/pyee） | 弃用 | 功能过剩，且多数不原生支持 async |
| **自研 60 行 async pub/sub** | **采用** | 类型安全路由、原生 async、零依赖 |

### 踩坑记录

PyCharm 对 `dict[Type[Event], ...]` 报"不可哈希类型不能做字典键"（误把类型标注当实例）。解决：去掉 `from __future__ import annotations`、用小写 `type` 标注、给 `type(event)` 结果加显式 `: type` 标注。

## 1.5 TUI 终端界面

### 实现原理

采用 **Rich（输出渲染）+ Prompt Toolkit（输入交互）** 组合（`ui/` 目录）：

- `renderer.py`：`StreamRenderer` 用 Rich 的 `Live` 组件实现流式 Markdown 渲染——每收到一个 delta 就累积缓冲并整体重渲染 `Markdown(buffer)`，15fps 刷新率，实现代码高亮、粗体等富文本的"边想边输出"
- `input_handler.py`：Prompt Toolkit 的 `PromptSession` 提供输入历史（上下键）、`Esc+Enter` 插入换行的多行编辑
- `terminal.py`：`Terminal` 门面类聚合两者，暴露 `get_user_input() / start_stream() / feed_stream() / finish_stream() / confirm()` 等语义化接口

### 方案选型

| 候选方案 | 结论 | 理由 |
|---|---|---|
| Textual 全功能 TUI 框架 | 弃用 | 组件化+CSS 学习曲线陡，对"对话流"这种线性界面过重 |
| 纯 Rich + input() | 弃用 | 无输入历史、无多行编辑、无 async 输入 |
| **Rich + Prompt Toolkit** | **采用** | 两者各司其职且都是成熟库；prompt_async() 与 asyncio 无缝集成 |

### 踩坑记录

`PromptSession` 在非 TTY 环境（CI、子进程）构造即抛 `NoConsoleScreenBufferError`。解决：**延迟初始化**——构造函数只置 `None`，首次 `get_user_input()` 才真正创建，保证 `Application` 可在无终端环境实例化（可测试性）。

## 1.6 分层配置系统

### 实现原理

`config/loader.py` 按优先级从低到高逐层覆盖：

```
内置默认值 (defaults.py 的 AgentConfig())
  ← .env 文件（自动读取，不覆盖已有环境变量）
  ← OPENAI_* 环境变量
  ← MINI_AGENT_* 环境变量（优先于 OPENAI_*）
  ← CLI 参数 (--model/--provider/--api-key/--base-url)
```

`.env` 自动加载是自研的 20 行解析（跳过注释、`key=value` 拆分、剥引号、`key not in os.environ` 保证真实环境变量优先），不引入 python-dotenv 依赖。

### 设计权衡

- **优先级实现为"分层字典按序覆盖"**：`env_layers` 列表低优先级在前、高优先级在后，遍历时后写覆盖先写，代码即文档。
- **配置全部是 dataclass**（`models/config.py`）：AgentConfig 聚合 LLMConfig/ToolConfig/MCPConfig/MemoryConfig/SecurityConfig，类型安全 + IDE 补全，不用 Pydantic（核心模型保持零依赖，Pydantic 只留给未来的配置文件校验场景）。

---

# 第二部分：P2 工具系统 + Agent Loop

## 2.1 工具系统（Tool ABC + Registry）

### 要解决的问题

Agent 的能力来自工具。工具系统要同时满足：LLM 能理解（需要 JSON Schema 描述）、代码能执行（需要统一调用协议）、未来能扩展（MCP 外部工具要能无缝挂载）。

### 实现原理

**组合优于继承**：`Tool` ABC 只要求两个成员（`tools/base.py`）：

```
class Tool(ABC):
    schema: ToolSchema                                    # 我是谁、要什么参数
    async def execute(ctx, **kwargs) -> ToolResult        # 怎么执行
```

`ToolSchema` 是中立的内部表示（名称+描述+参数列表），通过 `to_json_schema()` 转成 OpenAI function calling 格式。这个中间层是关键设计——未来接 Anthropic 只需再写一个转换方法，工具本身零改动。

`ToolRegistry` 是扁平字典 `dict[str, Tool]`：

```
register / unregister / get / list_tools     # 基础 CRUD
get_schemas()   # 一次性导出全部工具的 function calling 格式，供 LLM 请求携带
clone()         # 浅拷贝独立注册表（P6 SubAgent 各持一份，互不干扰）
filter(allowed, denied)   # 白/黑名单过滤（P3 ToolFilter 使用）
```

参数校验放在基类 `validate_args()`：按 schema 检查必填项、填充默认值，校验失败抛 `ValueError`——由 AgentLoop 捕获转成错误 ToolResult 回传 LLM，让模型自己修正参数重试。

### 方案选型

| 候选方案 | 结论 | 理由 |
|---|---|---|
| 深继承体系（FileTool → ReadFileTool...） | 弃用 | 继承层级带来的复用少、耦合多 |
| 装饰器注册（@tool 自动收集） | 弃用 | 隐式注册难以追踪，装配点分散 |
| **ABC 双成员 + 显式注册** | **采用** | 注册表就是一个 dict，一眼看清系统里有什么工具；MCP 适配器实现同一 ABC 即可入表 |

## 2.2 六个核心工具的实现要点

每个工具都是同构的：schema 声明 + execute 实现 + 错误兜底（`tools/builtin/`）。

| 工具 | 核心实现 | 关键细节 |
|---|---|---|
| **ReadFile** | `read_text` + 行切片 | 输出带 6 位右对齐行号（模仿 cat -n）；offset/limit 支持大文件分页；超过 max_file_size 拒绝 |
| **WriteFile** | `write_text` | 自动 `mkdir(parents=True)` 创建父目录；报告 Created/Overwrote 与字节数 |
| **EditFile** | `str.replace` 精确替换 | old_text 必须**恰好出现一次**（出现 N 次时报错要求提供更多上下文或 replace_all）——防止 LLM 意图外的多点误改 |
| **Bash** | `asyncio.create_subprocess_shell` | `wait_for` 超时后 kill 进程；stdout/stderr 分别捕获标注；非零退出码标记 is_error 并附加 exit code；输出超 30K 截断；Windows 用默认 shell、Unix 指定 /bin/bash |
| **Glob** | `pathlib.Path.glob` | 结果按修改时间倒序（最新文件通常最相关）；跳过 .git/.venv/node_modules 等噪音目录；上限 500 条 |
| **Grep** | `re` 逐行扫描 | 编译失败即报"无效正则"；include 参数按文件名过滤；单文件超 5MB 跳过；上限 200 条匹配 |

**统一的防御设计**：所有工具的输出都有截断上限——工具输出会进入对话历史消耗 token，无上限的 cat 一个大文件就能撑爆上下文窗口。

相对路径统一相对 `ctx.working_dir` 解析（ToolContext 注入），LLM 不需要关心绝对路径。

## 2.3 ReAct Agent Loop（核心）

### 要解决的问题

让 Agent"自主"完成任务：自己决定调什么工具、看结果、再决定下一步——直到得出最终答案。这就是 ReAct 范式（Reason 推理 + Act 行动 交替）。

### 实现原理

`core/agent_loop.py` 的主循环是一个状态机：

```
while True:
    iteration += 1
    THINKING:  response = await _think(conversation)     # LLM 流式生成
               conversation.append(assistant_msg)         # 记录（含 tool_calls）
    ├─ 无 tool_calls → RESPONDING，流式文本就是最终答案，break
    └─ 有 tool_calls:
       TOOL_CALLING: results = await _act(tool_calls)    # 执行（含安全管道）
       OBSERVING:    conversation.append(tool 消息 × N)   # 结果写回对话
                     _should_continue()?                  # 熔断检查
                       ├─ 否 → TERMINATED, break
                       └─ 是 → 回到 THINKING（LLM 看到结果继续推理）
IDLE + TurnCompleteEvent(iterations, tools_called, tokens)
```

"自主"的本质：**工具结果作为 TOOL 角色消息追加进对话，下一轮 THINK 时 LLM 看到结果自然会继续推理**。循环不含任何任务逻辑——所有决策都是 LLM 基于对话历史做出的。

### 三重熔断（`_should_continue`）

失控的 Agent 会无限烧钱。三道保险丝：

1. **迭代上限**：`iteration >= max_iterations`（默认 50）硬停
2. **用户取消**：`cancel()` 置标志位，循环与工具执行两处检查
3. **死循环检测**：滑动窗口记录最近工具名，**同一工具连续 6 次** → 判定卡死强制停止（LLM 反复读同一个文件是常见故障模式）

### UI 解耦：回调注入而非直接依赖

```
loop.on_stream_delta = terminal.feed_stream      # 文本增量 → 渲染
loop.on_tool_start   = lambda tc: terminal.show_tool_call(...)
loop.on_tool_end     = lambda tr: terminal.show_tool_result(...)
```

AgentLoop 完全不 import UI 模块，只暴露五个可选回调（不设置就静默运行）。收益：单元测试用列表收集回调验证行为；P6 的 SubAgent 复用同一个 AgentLoop 而不带 UI。

### 设计权衡

- **工具顺序执行而非 asyncio.gather 并行**：P2/P3 阶段顺序执行换来확定的权限确认顺序（并行时多个确认弹窗会交错），spec 中的并行优化留给后续版本。
- **错误全部转 ToolResult 而非抛异常**：未知工具、参数校验失败、执行异常，一律包成 `is_error=True` 的结果回传——**失败是对话的一部分**，LLM 看到错误信息会调整策略，抛异常则整个循环崩溃。

## 2.4 测试策略：MockLLM 脚本回放

### 实现原理

测试 ReAct 循环不能依赖真实 API（慢、贵、不确定）。`MockLLM` 实现 LLMProvider 接口，按预设脚本回放：

```
scripts = [
    tool_call_response("read_file", {"file_path": "..."}),   # 第 1 轮：发起工具调用
    text_response("The file contains..."),                    # 第 2 轮：给出答案
]
```

由此可以精确验证：直接回答不调工具、工具调用→结果→再回答的完整链路、未知工具报错、参数缺失报错、死循环护栏、迭代上限、流式/工具回调触发——8 个场景全部毫秒级完成。

**接口抽象的红利**：MockLLM 之所以能无缝替换，正是因为 AgentLoop 只依赖 LLMProvider ABC。

---

# 第三部分：P3 安全 + Hook

## 3.1 安全模型总览

Agent 的核心风险：**LLM 决定调什么工具、传什么参数，人无法预知**。P3 的目标是"Agent 有能力但不失控"，由三个协作组件组成纵深防御：

```
LLM 发出 ToolCall
   ↓
① PermissionManager  —— 系统级硬规则（危险命令/敏感路径）
   ↓
② HookManager (PRE_TOOL) —— 用户级可编程拦截
   ↓
③ Tool.execute
   ↓
④ HookManager (POST_TOOL) —— 观察审计
```

Permission 与 Hook 分离的理由：Permission 回答"这个操作**本质上**危不危险"（内置、不可拆卸）；Hook 回答"**当前项目**有什么额外规矩"（可插拔扩展）。

## 3.2 PathGuard 路径守卫

### 实现原理

三级判定策略（`security/path_guard.py`），按优先级：

```
1. 敏感目录（~/.ssh, ~/.aws, ~/.gnupg）        → DENY  硬拒绝
2. 敏感文件模式（.env, *.pem, *.key, id_rsa*,
   credentials*, *secret* ...）                → DENY  硬拒绝
   例外：.env.example / .env.sample（模板非机密）
3. 项目目录内                                   → ALLOW 自动放行
4. 显式 allowed_paths                           → ALLOW
5. 其余（项目外）                               → ASK   交用户决定
```

实现要点：
- 路径先 `expanduser().resolve()` 规范化，用 `Path.parents` 包含关系判断目录归属——**防路径穿越**（`../../.ssh/id_rsa` 解析后照样命中拒绝规则）
- 敏感文件用 `fnmatch` 通配匹配文件名（大小写不敏感）

### 设计权衡

**为什么敏感文件即使在项目内也拒绝？** `.env` 就在项目根目录，若"项目内自动放行"优先，Agent 读到 API 密钥后会进入对话历史——历史可能被日志、被压缩摘要、被上传，密钥就泄露了。所以敏感模式检查排在项目目录检查**之前**。

## 3.3 PermissionManager 权限管理器

### 实现原理

**评估顺序**（`security/permission.py`），与 Claude Code 同构：

```
显式 DENY 规则 → 显式 ALLOW 规则 → 会话授权 → 默认模式(allow/ask/deny)
```

**危险命令检测**用 13 条正则覆盖高危模式：

```
rm -rf / rm -r / rm -f、sudo、chmod 777、mkfs、dd if=、
git push --force、git reset --hard、curl|sh、wget|sh、
Windows: del /s /q、rmdir /s、format c:
```

命令检查的特殊逻辑：危险命令**即使在 allow 模式也要确认**（`check_command` 独立于普通规则流）；普通命令在 ask 模式下自动放行——弹窗只留给真正危险的操作，避免"狼来了"式的确认疲劳。

**会话授权**：用户批准一次后可 `grant_session_permission(scope, pattern)` 记入会话白名单，同类操作不再重复弹窗。

### 关键安全默认值

**无 UI 时拒绝**：`confirm_callback=None`（脚本模式/CI）时，所有需要确认的操作直接 DENY——安全系统的默认值必须是安全的（fail-safe），绝不能"没人在就放行"。

### 踩坑记录

通配匹配 `git *` 曾误匹配 `github-cli`——`pattern.rstrip("*").rstrip()` 把分隔空格也剥掉了。修正：保留分隔符做前缀匹配，`git *` → `startswith("git ")`，单测 `test_glob_pattern_matching` 锁定该行为。

## 3.4 Hook 生命周期钩子

### 实现原理

在 Agent 执行流的关键节点插入可编程拦截点（`tools/hooks.py`）。四个数据结构 + 一个管理器：

- **HookStage**（在哪拦）：PRE_TOOL / POST_TOOL / PRE_LLM / POST_LLM / SESSION_START / SESSION_END / USER_INPUT。P3 实际接线前两个，其余为 P4/P5 预留插槽（PRE_LLM 注入记忆、SESSION_END 触发提取）
- **HookContext**（能看到什么）：stage + tool_name + tool_args（**可变**，参数改写通道）+ tool_result（仅 POST 有值）
- **HookAction**（能做什么）：CONTINUE 放行 / BLOCK 阻止 / MODIFY 改参 / CONFIRM 上交用户
- **HookResult**（裁决书）：action + modified_args + reason（阻止理由回传给 LLM）
- **HookManager**：按 stage 分组注册，优先级降序执行

### 三个关键执行语义

1. **责任链 + 否决短路**：BLOCK 立即返回，后续 Hook 不执行——安全裁决一票否决，低优先级不能推翻高优先级的否决
2. **MODIFY 链式累积不短路**：多个 Hook 各改参数的不同部分（一个管超时、一个管路径规范化），叠加生效
3. **POST_TOOL 只观察不裁决**：工具已执行完，BLOCK 无意义；用途是审计日志、结果脱敏、统计

### 设计权衡

- **为什么全异步？** Hook 常需 I/O（弹窗、写日志、查外部策略），同步会阻塞事件循环卡死 TUI
- **为什么显式 register 不用装饰器？** 装配点集中在 app.py，装了哪些拦截器一目了然——安全组件最忌魔法注册
- **为什么 CONFIRM 短路上交？** HookManager 不持有 UI 引用（工具层不依赖交互层），确认动作由持有 terminal 的上层执行
- **为什么 BLOCK 回传 reason 而非抛异常？** 异常终止整个 ReAct 循环；作为 ToolResult 返回则 LLM 能"看到"拒绝理由并换方案

## 3.5 安全管道集成进 AgentLoop

### 实现原理

`core/agent_loop.py` 的 `_run_tool_pipeline()` 四段式流水线：

```
1. PermissionCheck   按工具类型路由：
                     bash → check_command
                     read_file/glob/grep → check_path(read)
                     write_file/edit_file → check_path(write)
                     DENIED → "Permission denied" 回传 LLM
2. PRE_TOOL Hooks    BLOCK → "Blocked by hook: {reason}" 回传
                     MODIFY → 用改写后的参数继续
3. Tool.execute      validate_args → 执行 → 异常兜底
4. POST_TOOL Hooks   观察结果
```

细节：`args = dict(tc.arguments)` **先复制再给 Hook 改**——ToolCall 是 frozen 的对话历史事实，Hook 修改的是副本，历史不被污染。

### TUI 确认闭环

`PermissionManager(confirm_callback=terminal.confirm)` 完成接线：权限系统需要问人时，Rich Panel 弹出黄色警告框，`y/n` 输入即裁决。依赖方向是 App 装配时注入回调，安全层本身不 import UI。

## 3.6 测试验证矩阵

35 个 P3 测试（总计 81 个）覆盖：

| 层 | 测试要点 |
|---|---|
| PathGuard 单元 | 项目内允许 / .ssh .aws 拒绝 / 项目外询问 / .env 拒绝 / .env.example 例外 / *.pem 拒绝 |
| PermissionManager 单元 | 评估顺序 / 危险命令弹窗三态（批准/拒绝/无UI默认拒）/ 配置黑名单 / 会话授权免重复弹窗 / deny 模式全拦 / 通配边界（git * ≠ github） |
| HookManager 单元 | 空链放行 / BLOCK 短路 / MODIFY 改参 / 优先级顺序 / 阶段隔离 / 卸载 |
| AgentLoop 集成 | ScriptedLLM 驱动完整管道：项目文件放行 / 危险 bash 三态 / .env 拦截 / PRE_TOOL 阻止且 reason 回传 / POST_TOOL 观察 |

---

# 附录：贯穿三个阶段的通用设计原则

1. **接口先行**：LLMProvider / Tool / HookFn 都是先定契约再做实现，Mock 测试与未来扩展（Anthropic Provider、MCP 工具）都吃这个红利
2. **失败即数据**：所有错误（权限拒绝、Hook 阻止、工具异常）都转成 `is_error=True` 的 ToolResult 进入对话，LLM 可见可纠错；异常只用于程序性 bug
3. **默认安全（fail-safe）**：无 UI 默认拒绝、敏感文件优先于项目放行、危险命令无视 allow 模式
4. **分层不越界**：工具层不 import 交互层（回调注入）、引擎层不 import UI（事件+回调）、依赖方向永远单向向下
5. **一切可测**：延迟初始化解 TTY 依赖、MockLLM 解 API 依赖、tmp_path 解文件系统依赖——81 个测试 30 秒跑完且不出网
