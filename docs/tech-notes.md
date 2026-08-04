# Mini-Code-Agent 核心技术实现原理与方案选型

本文档记录各阶段各核心技术的实现原理、设计权衡与方案选型理由，与 `spec.md`（架构规格）互补：spec 讲"是什么"，本文讲"为什么这么做"。

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

# 第四部分：P4 记忆 + 上下文管理

## 4.1 Token 计数体系

### 要解决的问题

上下文窗口有硬上限（如 128K tokens）。Agent 的工具输出（文件内容、命令输出）会快速膨胀历史，必须在**发送 API 请求之前**预判是否超窗口。API 响应后的 usage 字段只能事后确认，不能用于事前决策。

### 实现原理

`llm/token_counter.py` 提供两层计数：

```
count_tokens(text)          → 单段文本的 token 数
count_message_tokens(msg)   → 单条 API 消息（含 role 开销 + 工具调用序列化）
```

**双路径策略**：

| 路径 | 精度 | 场景 |
|---|---|---|
| tiktoken（cl100k_base 编码） | 精确 | 安装了可选依赖 tiktoken 时 |
| `len(text) // 4` | 估算 | 无 tiktoken 的兜底（英文 ~4 chars/token，中文偏差更大但足够做阈值判断） |

每条消息额外加 4 token 开销（角色标记 + 分隔符），工具调用额外加 3 token/call（函数名 + 参数包裹）。

### 设计权衡

- **为什么 tiktoken 是可选依赖？** 它是编译型包（Rust 实现），在部分环境下载困难（我们的清华镜像就 403 了）。核心功能不应因此无法使用。
- **为什么不调 API 的 token 计数端点？** 每次发请求前先调一次计数 API 开销太大且增加延迟。本地估算足够触发压缩阈值。

## 4.2 ContextManager 上下文管理器

### 实现原理

`memory/context.py` 是上下文窗口的"仪表盘"：

```
ContextManager:
    count_message(msg) → int      # 计数并缓存到 msg.token_count
    update_total(conv) → int      # 全量重算（system_prompt + 所有消息）
    usage_ratio → float           # 已用 / 总窗口（0.0~1.0）
    tokens_remaining → int        # 剩余可用
    needs_compression → bool      # >= threshold?
    check_and_compress(conv)      # 检查 + 触发压缩级联
```

**token_count 缓存机制**：每条消息首次计数后写入 `msg.token_count`，后续读取直接用缓存。压缩后清除缓存（`msg.token_count = None`）强制重算。

**与 AgentLoop 的集成点**：在 OBSERVE 阶段（工具结果追加后）调用 `check_and_compress`——这是上下文增长最快的时刻（一次 read_file 可能加几千 token），恰好在下一轮 THINK（发 API 请求）之前。

### 设计权衡

- **Compressor 通过 `set_compressor()` 延迟注入**而非构造函数参数：ContextManager 在 `memory/` 包，Compressor 也在 `memory/` 包但依赖 `ContextManager` 的 `count_tokens`——用延迟注入打破循环。
- **阈值默认 0.75**（可配置）：留 25% 给 LLM 输出 + 新一轮工具调用的空间。太高则压缩后马上又触发；太低则浪费窗口。

## 4.3 三级压缩策略级联

### 要解决的问题

简单截断会丢失上下文导致 LLM "失忆"。需要渐进式压缩：先压缩低价值内容，再压缩旧内容，最后才截断。

### 实现原理

`memory/compressor.py` 的 `Compressor` 按级联顺序尝试三个策略，每级执行后检查是否已达目标（`total_tokens <= target`），达标即停：

**Stage 1: DropToolResults（精简工具输出）**

工具输出是历史中最冗余的部分（一个 ReadFile 可能 2000 行）。将 > 200 字符的输出截断为前 200 字符 + 统计摘要。保留工具调用结构（LLM 知道"调了什么工具"），只丢弃原始输出。

```
Before: read_file → 2000 行文件内容
After:  read_file → 前 200 字符 + "... (2000 lines, 45000 chars total, truncated)"
```

跳过已压缩的（`msg.compressed == True`），避免重复处理。

**Stage 2: SummarizeOldest（摘要旧消息）**

保留最近 6 条消息不动（当前工作上下文），将之前所有消息提取为一条摘要。当前实现是**提取式摘要**（每条消息取角色 + 前 300 字符 / 工具名 / 结果状态），不调 LLM：

```
[Compressed conversation history]
[user] 帮我读取 README...
[assistant] called tools: read_file
[tool] read_file → ok
[assistant] 这个项目是一个...
```

设计决策：P4 阶段用提取式而非 LLM 摘要，原因是避免压缩本身消耗 token、避免递归 API 调用的复杂性、以及保持可测性（无网络依赖）。LLM 摘要作为可插拔升级留给未来。

**Stage 3: SlidingWindow（滑动窗口兜底）**

前两级仍然超限时，从后往前按 token 预算保留尽可能多的最近消息。这是"核选项"——会丢失所有早期上下文，但保证系统不会因为 context overflow 崩溃。

### 级联控制

```
Compressor.compress(conversation, target_tokens):
    for strategy in [DropToolResults, SummarizeOldest, SlidingWindow]:
        recount total tokens
        if total <= target: break
        strategy.compress(conversation, target)
```

每级执行后重算（`token_count = None` 的消息会被 recount），确保判断基于最新状态。

## 4.4 会话持久化

### 实现原理

`memory/session_store.py` 将 Session 对象序列化为 JSON 文件存储在 `~/.mini-agent/sessions/{session_id}.json`：

```
SessionStore:
    save(session) → Path     # 序列化写入，更新 last_active 时间戳
    load(session_id) → Session | None
    list_sessions() → [{id, model, turns, last_active, project_dir}]
    delete(session_id) → bool
```

**序列化的关键挑战**：Message 中嵌套了 frozen dataclass（ToolCall/ToolResult）、datetime、Path——全部手动转换为 JSON 兼容类型（isoformat/str），不用 Pydantic 的 `.model_dump()` 以保持零依赖。

**反序列化重建完整对象图**：JSON → `_deserialize_session` → SessionMetadata + Conversation（含重建的 ToolCall/ToolResult 列表）。datetime 用 `fromisoformat` 还原，Role 用枚举构造。

### 设计权衡

- **文件而非数据库**：会话数量通常几十到几百，JSON 文件 I/O 足够。SQLite 引入依赖且对调试不友好（看不到原文）。
- **list_sessions 只读 metadata 不反序列化全部消息**：列表场景不需要完整对话历史，只解析外层 metadata 即可。

## 4.5 跨会话记忆

### 实现原理

`memory/persistent.py` 实现双层记忆存储：

```
项目级: {project_dir}/.mini-agent/memory.json    ← 项目特有的约定、配置
用户级: ~/.mini-agent/memory/user_memory.json     ← 用户偏好、习惯
```

每条记忆是一个 `MemoryEntry`：

```
MemoryEntry:
    id: "mem_a1b2c3"          # UUID 前缀
    content: "User prefers tabs"
    source: "user" | "project" | "extracted"
    created_at: ISO 时间戳
    tags: ["style", "editor"]
```

**搜索**是双通道匹配：内容关键词 + 标签关键词，同时搜索项目级和用户级记忆。

### 4.6 记忆提取

`memory/extraction.py` 的 `MemoryExtractor` 从对话中自动提取可持久化的事实：

**触发条件**：用户消息 >= 5 条（短对话无法提取有意义的偏好）。

**提取方式**：正则模式匹配用户消息中的关键句式：

```
"always/prefer/please/remember + 内容"  → preference 标签
"this project/we/our team uses/runs"   → convention 标签
"don't/never/avoid + 内容"              → constraint 标签
```

**去重**：与已有记忆做精确匹配 + 子串包含检查，避免同一事实重复存储。

### 设计权衡

- **为什么不用 LLM 提取？** 提取发生在每次对话结束时，频率高；LLM 调用增加延迟和成本。正则模式覆盖了最常见的指令句式，误提取的代价低（多存一条无害记忆），漏提取可以未来加模式补救。
- **项目级 vs 用户级分离的理由**：`uses pytest` 是项目事实，换项目就不适用；`prefers tabs` 是用户偏好，跨项目通用。分层存储让搜索时可以按范围过滤。

## 4.7 AgentLoop 集成

ContextManager 通过构造函数注入 AgentLoop（可选参数，向后兼容不传）。集成点在 OBSERVE 阶段：

```
# core/agent_loop.py 的 run() 循环中
OBSERVE:
    for result in results:
        conversation.append(tool_result_message)
    # 新增：上下文压缩检查
    if self._context:
        await self._context.check_and_compress(conversation)
```

压缩发生在工具结果追加后、`_should_continue` 判断前——确保下一轮 THINK 发送的是压缩后的对话。

App 装配层（`app.py`）负责连线：

```
context_manager = ContextManager(config.memory)
context_manager.set_compressor(Compressor())
agent_loop = AgentLoop(..., context_manager=context_manager)
```

## 4.8 测试验证矩阵

27 个 P4 新测试（总计 110 个）：

| 模块 | 测试要点 |
|---|---|
| test_context.py (12) | token 计数缓存 / update_total / usage_ratio / needs_compression 阈值 / 低于阈值不压缩 / 超阈值触发压缩且消息数减少 |
| test_session_store.py (6) | save+load 完整往返 / 含 tool_calls 往返 / list 多会话 / delete / 删不存在的 / 加载不存在的 |
| test_persistent_memory.py (9) | 用户级 CRUD / 项目级 CRUD / 关键词搜索 / 标签搜索 / 跨层搜索 / 提取数不足不触发 / 提取偏好 / 去重 / 存储到项目级 |

---

# 第五部分：P5 扩展协议

## 5.1 Slash Command 命令框架

### 要解决的问题

用户的高频操作（查状态、清历史、存会话）不应该消耗 LLM 调用——它们是确定性的本地操作，应该"一键触发"而不是"对话请求"。

### 实现原理

`extensions/slash_commands.py` 实现极简的命令注册与分发：

```
SlashCommand:  name + description + handler(args, ctx) + hidden
SlashCommandRegistry:
    register / unregister / get / list_commands（过滤 hidden）
    is_slash_command(text)
    execute(input, context) → 解析 "/name args" → 分发到 handler
```

**分发优先级**：App 主循环中斜杠命令**先于** Agent 对话判断——`/` 开头的输入直接走命令分发，不进入 LLM。未知命令返回可用命令列表提示而非报错。

**闭包工厂模式**：内置命令（`builtin_commands.py`）用 `_make_xxx(app)` 闭包工厂生成 handler，让命令持有 Application 引用而不需要全局变量。11 个内置命令：/help /clear /status /model /compact /memory /session /tools /skill /quit /exit。

### 补全菜单（输入 / 弹出下拉框）

Prompt Toolkit 的 `Completer` 接口实现：

- `SlashCommandCompleter.get_completions()`：输入以 `/` 开头时按前缀匹配命令，`display_meta` 显示命令说明
- `complete_while_typing=True`：边输入边过滤
- **backspace 重触发**：默认删除字符不弹菜单，自定义 backspace 键绑定在删除后检测 `/` 前缀并 `buf.start_completion()` 主动弹出
- `reserve_space_for_menu=12`：光标在终端底部时预留空间，终端自动上滚保证菜单完整显示（模仿 Claude Code 行为）
- 补全项 `start_position=-len(text)` 整体替换输入，避免选中后文本拼接错误

## 5.2 Skill 技能包系统

### 要解决的问题

让用户能"装技能"扩展 Agent 能力——把领域专属的 prompt + 工具需求打包为可加载单元，不改核心代码。

### 实现原理

技能包 = 一个目录 + 一个 SKILL.md 文件（YAML front-matter + Markdown 正文）：

```
---
name: code-review
description: Review code changes
triggers:
  - "review"
tools:
  - read_file
  - grep
---
You are a code reviewer. Follow these steps: ...
```

`SkillRegistry`（`extensions/skills.py`）核心机制：

- **加载**：`load_all()` 扫描 skill_dirs 下所有子目录的 SKILL.md，解析 front-matter（自研 20 行 YAML 子集解析器：key:value + 列表项，不引入 PyYAML）
- **激活**：`activate(name, conversation)` 把技能 prompt 以带标记的形式追加到 system prompt（`--- Skill: name ---` 分隔符）
- **停用**：`deactivate` 按标记精确移除注入的 prompt 段，system prompt 恢复原状
- **触发匹配**：`match_triggers(user_message)` 检查用户消息是否包含触发词（已激活的技能跳过，避免重复注入）

### 设计权衡

- **为什么 prompt 注入 system prompt 而非独立消息？** system prompt 是 LLM 行为定义的正确位置；作为 user/assistant 消息注入会被后续对话稀释，且可能被上下文压缩掉。
- **带标记注入 = 可逆操作**：注入用 `--- Skill: name ---` 前缀标记，deactivate 时 `str.replace` 精确移除，多技能可叠加互不干扰。

## 5.3 MCP 协议客户端

### 要解决的问题

让 Agent 能挂载任意符合 MCP（Model Context Protocol）规范的外部工具服务——GitHub、Slack、数据库等——而无需为每个服务写专属集成代码。

### 实现原理

三层结构（`tools/mcp/`）：

**Transport 层**（`transport.py`）：`StdioTransport` 启动 MCP 服务器子进程，通过 stdin/stdout 收发 JSON-RPC 2.0 消息（每行一个 JSON，自动分配递增 request id，30 秒超时）。

**Client 层**（`client.py`）：
- `MCPServerConnection.initialize()`：MCP 握手三步——initialize 请求（带 protocolVersion + clientInfo）→ initialized 通知 → tools/list 发现工具
- `MCPManager`：多服务器连接管理（connect/disconnect/call_tool），`call_tool` 解析 MCP 响应的 content 数组提取 text 块拼接为输出

**Adapter 层**（`adapter.py`）：`MCPToolAdapter` 实现内部 Tool ABC——这是关键设计。MCP 工具的 inputSchema（JSON Schema）转换为内部 ToolParameter 列表，工具名加 `mcp_{server}_` 前缀防冲突。适配后 MCP 工具**注册进同一个 ToolRegistry**，AgentLoop 调用它和调用内置工具零区别——权限检查、Hook 链、错误处理全部自动生效。

### 设计权衡

- **为什么不用官方 MCP SDK？** 与 LLM Provider 同样的理由——P5 只需要 stdio transport + 三个方法（initialize/tools list/tools call），自研 JSON-RPC 循环 ~80 行，比引入 SDK 更可控。HTTP transport 预留了 MCPTransport ABC 插槽。
- **Adapter 模式的红利**：安全层（PermissionCheck/Hook）对 MCP 工具透明生效——因为它们只认 Tool 接口，不关心工具来自哪里。

## 5.4 Anthropic Provider（第二个 LLM 后端）

### 要解决的问题

验证 P1 的 Provider 抽象是否真的"可扩展"——接入一个 API 格式完全不同的后端（Claude Messages API），核心代码零改动。

### 实现原理

`llm/anthropic_provider.py` 实现 LLMProvider ABC，关键是**三个格式转换**：

**1. 消息格式转换**（`_split_system`）：

| OpenAI 格式 | Anthropic 格式 |
|---|---|
| messages 里的 system 角色 | 顶层独立 `system` 参数 |
| assistant.tool_calls 数组 | content 里的 tool_use 块 |
| tool 角色消息 + tool_call_id | user 角色 content 里的 tool_result 块 |

**2. 工具格式转换**（`_convert_tools`）：OpenAI 的 `{"type":"function","function":{name,parameters}}` → Anthropic 的 `{name, description, input_schema}`。

**3. SSE 事件流转换**（`_parse_event`）：Anthropic 的事件类型体系完全不同——`content_block_start`（tool_use 块携带 id+name）、`content_block_delta`（text_delta 文本增量 / input_json_delta 工具参数增量）、`message_delta`（stop_reason + usage）——全部归一化为内部 StreamChunk，AgentLoop 消费时无感知。

### 验证意义

AnthropicProvider 只用 `ProviderRegistry.register("anthropic", ...)` 一行接入，AgentLoop/工具系统/UI 零改动——证明了 P1 抽象层的正确性。`--provider anthropic` CLI 参数即可切换。

## 5.5 测试验证矩阵

22 个 P5 新测试（总计 131 个）：

| 模块 | 测试要点 |
|---|---|
| test_slash_commands.py (7) | 注册+执行 / 未知命令提示 / is_slash_command 判定 / hidden 过滤 / 无参数 / 非斜杠返回 None / 卸载 |
| test_skills.py (8) | SKILL.md 解析 / 多技能加载 / 激活注入+停用移除 / 触发词匹配 / 已激活不重复 / 无 front-matter 拒绝 / 缺 name 跳过 |
| test_mcp.py (7) | Adapter schema 转换 / JSON Schema 输出 / 执行代理 / 错误传递 / 注册进 Registry / 可选参数识别（FakeMCPManager 模拟，零真实服务器依赖） |

---

# 第六部分：P6 多 Agent 协作

## 6.1 Git Worktree 隔离

### 要解决的问题

多个 Agent 同时改代码会互相覆盖。git worktree 让同一仓库的多个分支同时检出到不同目录——每个 Agent 在自己的工作树里改代码，互不干扰，完成后合并回主分支。

### 实现原理

`security/worktree.py` 封装 git worktree 命令族（全部通过 asyncio 子进程执行，`_run_git` 统一返回 exit_code/stdout/stderr）：

```
create(branch)      → git worktree add {base}/{branch} -b {branch}
remove(path)        → 先 status --porcelain 检查未提交变更，dirty 拒绝（force=True 强制）
list()              → git worktree list --porcelain 逐行解析（worktree/HEAD/branch 三元组）
status(path)        → 干净检测 + 当前分支 + HEAD commit
merge_back(branch)  → git merge --no-ff；失败时 diff --diff-filter=U 列出冲突文件
                      并自动 merge --abort 保持仓库干净
```

### 设计权衡

- **未提交变更保护是默认行为**：Agent 的工作树可能有半成品，误删就丢了。remove 先查 status，dirty 必须显式 force。
- **冲突时 abort 而非留着**：合并冲突留在仓库里会阻塞后续所有操作。检测到冲突 → 记录文件列表 → 立即 abort → 把冲突信息返回给调用方决策。
- **worktree 放在 `.mini-agent/worktrees/` 下**：集中管理便于清理，且已在 .gitignore 中。

## 6.2 SubAgent 子任务分发

### 要解决的问题

复杂任务（"并行修复 A 和 B"）单 Agent 串行太慢。SubAgent 把子任务委派给独立 Agent 并行执行——每个有自己的对话上下文、工具集、工作目录。

### 实现原理

**SubAgent**（`core/subagent.py`）= 一次性任务执行器：

- **复用 AgentLoop**：SubAgent 内部就是一个标准 AgentLoop + 专属 Conversation（系统提示词强调"专注单任务、自主决策、最终消息即报告"）
- **隔离三件套**：克隆的 ToolRegistry（`clone()` + 白名单过滤）、独立 Session、可选 worktree 作为 working_dir
- **结果封装**：SubAgentResult 携带 agent_id/task/success/output/tool_calls_made/tokens_used/worktree_path/error

**SubAgentManager** = 生命周期管理器：

```
spawn(task, isolation, allowed_tools) → asyncio.create_task 后台启动，返回 agent_id
spawn_parallel(tasks)                 → 批量 spawn，全部并发运行
wait(agent_id, timeout)               → await 单个结果；超时则 cancel + 返回 Timed out 错误
wait_all(ids)                         → asyncio.gather 并发等待全部
cancel / cancel_all / list_active / get_status
```

`isolation="worktree"` 时 spawn 自动调 WorktreeManager.create 建独立工作树，SubAgent 的所有文件操作都发生在里面。

### 并行的实现本质

`asyncio.create_task` 让每个 SubAgent 的 run() 立即开始跑（LLM I/O 等待时事件循环切换到其他 Agent）。单测 `test_parallel_faster_than_serial` 锁定该行为：3 个 0.1s 延迟的 Agent 并行完成 <0.35s（串行需 0.3s+）。真实 API 验证：2 个 Agent 并行读不同文件 2.3s 完成。

### 设计权衡

- **失败不抛异常**：SubAgent.run() 捕获所有异常转成 `success=False` 的 SubAgentResult——一个子任务失败不应炸掉整个编排。
- **超时即取消**：wait 超时后主动 cancel 该 Agent（停止烧 token），返回明确的 Timed out 错误。
- **工具白名单**：spawn 时可限制子 Agent 能用的工具（如只读任务只给 read_file/glob/grep），最小权限原则。

## 6.3 Plan 模式（结构化任务分解）

### 实现原理

`core/planner.py` 用 LLM 做任务分解——prompt 要求输出纯 JSON 数组，每项含 description + role：

```
Planner.decompose(task) → Plan(steps=[PlanStep(index, description, role, status)])
```

**三级解析容错**（LLM 输出不可控，解析必须健壮）：

1. 剥 markdown 代码围栏（```json ... ```）
2. 正则提取第一个 JSON 数组；数组项支持 dict（取 description/role）和纯字符串两种形态
3. JSON 解析失败 → 整段文本兜底为单步计划（宁可单步执行也不崩溃）

`max_steps` 截断防止 LLM 过度拆分。

## 6.4 Agent Teams 团队协作

### 实现原理

`core/team.py` 实现 Orchestrator 编排策略，串起 Planner 和 SubAgentManager：

```
AgentTeam.start(task):
    1. plan = planner.decompose(task)            # LLM 分解任务
    2. for step in plan.steps:
         member = _match_member(step.role)        # 角色匹配（子串双向匹配 + 首成员兜底）
         spawn(带角色前缀的子任务, member.allowed_tools)
    3. results = wait_all()                       # 并行等待全部完成
    4. 状态回写 plan.steps + 生成 TeamRunReport
```

**角色匹配**：Planner 给每个子任务建议 role（如 "backend"），`_match_member` 用双向子串匹配找团队成员（"test" 匹配 "tester"）；没匹配到用第一个成员兜底，空团队则不带成员配置直接执行。

**TeamRunReport**：每步的状态（OK/FAILED）+ 输出摘要，`success` 属性要求全部子任务成功。

### 设计权衡

- **为什么是 Orchestrator 而非 peer-to-peer？** 编排逻辑集中在一处（分解→分配→收集），数据流单向清晰。Agent 间横向通信会引入复杂的消息路由和死锁风险，收益不明。
- **复用而非新造**：AgentTeam 没有自己的执行引擎——分解交给 Planner、执行交给 SubAgentManager，它只做匹配和汇总（~100 行）。

## 6.5 测试验证矩阵

25 个 P6 新测试（总计 156 个）：

| 模块 | 测试要点 |
|---|---|
| test_subagent.py (8) | 任务完成 / 工具使用 / 并行 spawn / 并行快于串行（计时断言）/ 未知 agent / 超时取消 / 工具白名单 / 注册表隔离 |
| test_planner.py (6) | JSON 数组解析 / markdown 围栏剥离 / 无效 JSON 兜底 / max_steps 截断 / 字符串项 / is_complete |
| test_team.py (5) | 完整编排流程 / 报告摘要 / 角色匹配 / 首成员兜底 / 空团队 |
| test_worktree.py (6, 集成) | 真实 git 仓库: create+list / 重复创建报错 / clean/dirty 状态 / remove / dirty 拒绝+force / merge_back |

**E2E 真实 API 验证**：2 个 SubAgent 并行读不同文件 2.3s 完成各自正确报告；AgentTeam 完整编排（Planner 分解 → 2 角色成员并行执行 → 汇总 success=True）。

---

# 第七部分：P7 打磨 + 测试

## 7.1 测试补缺：解析层单测 + 装配冒烟

P7 前的测试盲区是 **LLM Provider 的解析层**——P1/P5 的流式解析（`_parse_chunk`/`_parse_event`/`assemble_response`）只被间接覆盖。新增 23 个直接单测：

- **OpenAI 解析**：文本 delta / finish_reason / 工具调用碎片 / usage 提取 / context_window 查表兜底
- **碎片组装**：跨 3 个 chunk 的 tool_call 参数拼接、多工具并发、截断 JSON 兜底为空字典
- **Anthropic 解析**：text_delta / tool_use 块 / input_json_delta / stop_reason 映射（end_turn→stop, tool_use→tool_calls）/ 未知事件忽略
- **格式转换**：system 分离、tool_calls→tool_use 块、tool 消息→tool_result 块、工具 schema 转换

**装配冒烟测试**（`test_agent_e2e.py`）：完整 Application 构造一遍，断言所有层就位、6 工具注册、slash 命令齐全、system prompt 含平台信息——防止装配代码腐化（wiring 错误往往单测查不出）。

## 7.2 错误处理：友好化最后一公里

原则"失败即数据"已贯穿各层（工具异常→ToolResult、截断 JSON→空字典、损坏 session→None），P7 补的是**面向用户的两个出口**：

**1. LLM API 错误翻译**（`app.py` 的 `_friendly_error`）：httpx 异常按状态码映射为中文可操作提示——401→"检查 .env 中的 OPENAI_API_KEY"、402→余额不足、429→稍后重试、5xx→服务端错误、ConnectError→检查网络/BASE_URL、Timeout→超时。用户看到的是"怎么办"而不是 traceback。

**2. 启动前置检查**（`cli.py`）：API key 为空直接给出三种配置方式指引后退出——比启动后第一次对话才报 401 的体验好得多。

## 7.3 性能：token 计数 LRU 缓存

**热点分析**：每次压缩检查（每轮 OBSERVE 都触发）会重算全对话 token——system prompt（~800 token 的长文本）和所有历史消息被反复 tiktoken 编码，而它们的内容根本没变。

**方案**（`token_counter.py`）：

```
@lru_cache(maxsize=4096)  # 按文本内容缓存
def _count_cached(text): ...

超过 50K 字符的文本跳过缓存 —— lru_cache 持有字符串引用，
缓存超大文本会导致内存膨胀
```

配合 Message.token_count 字段缓存（P4 已有），二级缓存让压缩检查的重复计数开销趋近于零。

## 7.4 UI 打磨

- **主题系统**（`ui/themes.py`）：Theme frozen dataclass 定义 8 个语义色位（primary/success/error/warning/dim/menu 系列），内置 default/dark/light 三套配色，`get_theme(name)` 兜底默认主题。
- **输入历史持久化**（`ui/input_handler.py`）：InMemoryHistory → FileHistory（`~/.mini-agent/input_history`），上下键历史跨会话保留；目录创建失败时退回内存历史（fail-safe）。

## 7.5 最终测试矩阵

179 个测试（P7 新增 23 个），34 秒跑完：

| 类别 | 文件数 | 覆盖 |
|---|---|---|
| 单元测试 | 18 | models/events/config/tools/agent_loop/agent_security/permissions/hooks/context/session_store/persistent_memory/slash/skills/mcp/subagent/planner/team/llm_providers |
| 集成测试 | 2 | agent_e2e（装配冒烟）、worktree（真实 git 仓库） |

---

# 第八部分：P8 评测框架

## 8.1 Headless Runner 设计

评测不能依赖 TUI——需要程序化运行、采集指标、自动验证。`benchmarks/runner.py` 直接调 AgentLoop 而非 Application：

- 构造 headless 上下文：ConfigLoader + ProviderRegistry + ToolRegistry + EventBus + ToolContext，**不创建 Terminal**
- 工具调用计数：订阅 `ToolCallEndEvent` 累加
- Token 采集：复用 `AgentLoop.last_turn_tokens`
- 验证：`subprocess.run(verify_command, cwd=workspace)` 检查 exit code
- Workspace 隔离：`shutil.copytree` 到临时目录，原始 fixture 不被修改

## 8.2 任务设计原则

10 个任务覆盖五个类别（bugfix/feature/test/refactor/search），每个任务：
- YAML 定义：name + prompt + verify_command，格式极简
- Workspace fixture：预置的有 bug 的代码 / 待通过的测试 / 待搜索的文件
- 验证命令：pytest / import / 文件存在检查，exit 0 = 通过（搜索类用 echo OK 人工判定）

## 8.3 评测结果

10/10 全部通过，总成本 $0.0015。详细数据见 `benchmarks/README.md`。

---

# 第九部分：P9 /trace 机制透明度

## 9.1 要解决的问题

CC 等商用 Agent 是黑盒——用户只能看到工具调用的表面行为，看不到内部决策过程。`/trace` 命令实时展示 ReAct 循环内部状态：阶段切换、权限判定（含依据）、工具生命周期、LLM 请求/响应元信息。这是"理解 Agent"的直接证据。

## 9.2 架构：纯订阅者，零侵入

TraceRenderer（`ui/trace.py`）是一个**纯 EventBus 订阅者**——不改 ReAct 循环任何逻辑，只订阅 7 种事件渲染输出：

```
AgentPhaseChange / PermissionCheck / ToolCallStart / ToolCallEnd /
LLMRequest / LLMResponse / TurnComplete
```

关键设计：
- **enabled 开关在 handler 内部判断**：attach 只做一次，/trace 切换只翻 bool，不反复订阅/退订
- **只显示元信息**：工具参数截断 40 字符、只显示 token 数不显示内容——避免刷屏
- **P1 的 EventBus 投资在这里兑现**：如果当初层间直接调用，做 trace 就要改遍 AgentLoop；事件驱动架构让 trace 变成"加一个订阅者"

## 9.3 补齐的两处事件缺口

1. **权限判定溯源**：PermissionManager 原来只返回 GRANTED/DENIED，不说"为什么"。加 `last_decision_reason` 属性，每条判定路径赋值（rule:<pattern> / session_grant / mode:<x> / user_confirm:<x> / dangerous_command / path_guard:<x> / no_ui:default_deny）——方法签名零改动，183 个既有测试全过证明零破坏。
2. **LLM 事件激活**：LLMRequestEvent/LLMResponseEvent 在 P1 就定义了但从未发射（死代码），本次在 `_think()` 前后接线激活。

## 9.4 验证

- 10 个新测试（Console(record=True) 捕获渲染输出断言；权限事件字段断言）
- 真实 API E2E：完整 trace 流 14 行输出全部正确（阶段→llm 请求→响应→权限→工具→汇总）

---

# 附录：贯穿各阶段的通用设计原则

1. **接口先行**：LLMProvider / Tool / HookFn / CompressionStrategy / MCPTransport 都是先定契约再做实现，Mock 测试与扩展（AnthropicProvider 一行注册接入、MCP 工具透明挂载）都吃这个红利
2. **失败即数据**：所有错误（权限拒绝、Hook 阻止、工具异常、SubAgent 失败）都转成携带原因的结果对象进入数据流，上层可见可决策；异常只用于程序性 bug
3. **默认安全（fail-safe）**：无 UI 默认拒绝、敏感文件优先于项目放行、危险命令无视 allow 模式、dirty worktree 拒绝删除
4. **分层不越界**：工具层不 import 交互层（回调注入）、引擎层不 import UI（事件+回调）、记忆层延迟注入打破循环依赖、MCP 工具经 Adapter 走统一 Tool 接口——依赖方向永远单向向下
5. **一切可测**：延迟初始化解 TTY 依赖、MockLLM/FakeMCPManager 解外部服务依赖、tmp_path 解文件系统依赖、真实 git 仓库 fixture 做集成测试、Console(record=True) 捕获渲染输出——193 个测试 35 秒跑完
6. **渐进式增强**：压缩用提取式→可升级 LLM 摘要；记忆提取用正则→可升级 LLM 分析；MCP 只做 stdio→预留 HTTP 插槽；每个模块保持简单可测但留有升级路径
7. **复用而非新造**：SubAgent 复用 AgentLoop、AgentTeam 复用 Planner+SubAgentManager、MCP 工具复用整条安全管道、/trace 复用 EventBus 事件流——新能力尽量是既有组件的组合
