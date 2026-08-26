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

分两层处理：

1. **解析层 `_parse_chunk()`**（各 Provider 各自实现）：把每条 SSE 消息（`data: {json}` 行）转成统一的 `StreamChunk` 数据类——文本增量 `delta`、工具调用增量 `ToolCallDelta`、结束原因 `finish_reason`、用量 `usage`
2. **组装层 `assemble_response()`**（`llm/base.py`，provider 无关）：流结束后，按 `index` 归组所有 `ToolCallDelta`，拼接 `arguments` 字符串再 `json.loads`，还原出完整的 `ToolCall` 列表。配套的 `complete(llm, messages, ...)` 函数将流式收集+组装封装为一次调用

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
    def off(event_type, handler)     # 取消订阅
    def off_any(handler)             # 取消全局订阅
    async def emit(event)            # 广播，asyncio.gather 并发分发
```

以**事件类的 type 对象**作为字典键做路由——`emit` 时 `type(event)` 精确匹配订阅者。所有处理器用 `asyncio.gather(..., return_exceptions=True)` 并发执行，单个处理器异常不影响其他订阅者；异常由 `emit` 逐个记 warning 日志（此前静默吞掉）。

**零代码全局监听**：`extensions/event_listeners.py` 从顶级配置 `listener_dirs`（默认 `./.mini-agent/listeners` + `~/.mini-agent/listeners`）加载 *.py 插件——契约为 `register(bus)`（完全控制，优先）或 `on_event(event)`（同步/异步均可，自动经 `on_any` 注册为全局监听）。插件导入/注册/运行异常全部隔离并记日志，绝不影响主流程；app 启动时提示 "Loaded N event listener(s)"。用途：把全部事件落盘 JSONL、统计工具调用分布等。

事件类型定义在 `models/events.py`：UserMessageEvent、LLMRequest/LLMResponseEvent、ToolCallStart/EndEvent、PermissionCheckEvent、AgentPhaseChangeEvent、TurnCompleteEvent、SessionStart/EndEvent 等，全部继承携带时间戳的 `Event` 基类。

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

- `renderer.py`：`StreamRenderer` 用 Rich 的 `Live` 组件实现流式 Markdown 渲染——逐段提交式（已完成段落永久打印固化、Live 区只渲染尾段），8Hz 刷新率（legacy Windows 控制台 15Hz 会撕裂），实现代码高亮、粗体等富文本的"边想边输出"；思考流（reasoning_content）不走 Live，Live 延迟到首个正文 delta 才启动（§100）
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
- **配置全部是 dataclass**（`models/config.py`）：AgentConfig 聚合 LLMConfig/ToolConfig/MCPConfig/MemoryConfig/SecurityConfig，类型安全 + IDE 补全。Pydantic 专用于工具参数定义（`params_model`，P46/P47 自动生成 JSON Schema + 类型校验）和配置文件校验，核心消息模型不使用 Pydantic。

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

`ToolSchema` 是中立的内部表示，通过 `to_json_schema()` 转成 OpenAI function calling 格式。Pydantic 工具（P46）通过 `params_model` 定义参数，`_schema_from_model()` 调用 `model_json_schema()` 后经 `_resolve_refs()` 解引用 `$ref/$defs`，完整 JSON Schema 存入 `ToolSchema.raw_parameters` 直通输出（P47）；手写 schema 工具（BashTool）和 MCP 适配工具走 ToolParameter 后备路径。Anthropic Provider 转换 OpenAI 格式为 Anthropic 格式，工具本身零改动。

`ToolRegistry` 是扁平字典 `dict[str, Tool]`：

```
register / unregister / get / list_tools     # 基础 CRUD
get_schemas()   # 一次性导出全部工具的 function calling 格式，供 LLM 请求携带
clone()         # 浅拷贝独立注册表（P6 SubAgent 各持一份，互不干扰）
filter(allowed, denied)   # 白/黑名单过滤（AgentTeam 非写步骤 + SubAgent 工具白名单使用）
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
3. **死循环检测**（双层）：同工具+参数签名连续 6 次 → 判定卡死；同一工具出现在连续 15 轮每轮中 → 判定卡死（P35 升级 v2，按轮检测不误杀批量并行）

### UI 解耦：回调注入而非直接依赖

```
loop.on_stream_delta = terminal.feed_stream      # 文本增量 → 渲染
loop.on_tool_start   = lambda tc: terminal.show_tool_call(...)
loop.on_tool_end     = lambda tr: terminal.show_tool_result(...)
```

AgentLoop 完全不 import UI 模块，只暴露七个可选回调（on_stream_start/delta/end、on_thinking_delta、on_tool_start/end、on_tool_call_assembling，不设置就静默运行）。收益：单元测试用列表收集回调验证行为；P6 的 SubAgent 复用同一个 AgentLoop 而不带 UI。

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

五级判定策略（`security/path_guard.py`），按优先级：

```
1. 敏感目录（~/.ssh, ~/.aws, ~/.gnupg，可配）   → DENY  硬拒绝
2. 敏感文件模式（.env, .env.*, *.pem, *.key,
   id_rsa*, id_ed25519*, credentials*,
   *secret*, *.p12, *.pfx，共 10 种）          → DENY  硬拒绝
   例外：.env.example / .env.sample / .env.template
3. 项目目录内                                   → ALLOW 自动放行
4. 溢写缓存目录只读（~/.mini-agent/cache/results/） → ALLOW
5. 显式 allowed_paths（可配）                   → ALLOW
6. 其余（项目外）                               → ASK   交用户决定
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
工具级门(TOOL 规则) → 显式 DENY 规则 → 显式 ALLOW 规则 → 会话授权 → 默认模式(allow/ask/deny)
```

**三级 scope**：`tool`（工具名）/ `command`（bash 命令）/ `path`（文件路径）。工具级门（P79，扩展点 #9）在资源级检查之前评估：TOOL DENY 直接拦截整个工具，TOOL ALLOW 整体信任（跳过命令/路径检查），无匹配落回资源级检查——默认模式刻意不参与工具门，否则 deny 模式会在工具层拦掉项目内读取。

**通用检查入口**（P79，扩展点 #15）：`check(request)` 按 `request.scope` 分发到 COMMAND / PATH / 通用管道，任意消费者构造 `PermissionRequest` 一次调用即得正确判定；`check_command` / `check_path` / `check_tool` 是各 scope 的便捷入口，共用内部管道无递归。

**危险命令检测**用 28 条正则覆盖高危模式（原 19 条 → 加 7 条内联解释器 + 删除类放宽/新增 `rd` → 权限矩阵完整性复查补 `cmd /c`）：

```
rm（任意形态，含裸 rm 删单文件；排除 rm --help/-h）、sudo、chmod 777、mkfs、dd if=、>/dev/sd、
git push/commit/reset/stash/rebase/checkout（-b 除外）/restore/clean、
curl|sh、wget|sh、
Windows: del/rmdir/rd（任意形态，含裸 rmdir 删空目录）、format c:、
D3 内联解释器: python -c / node -e|-p / perl -e / ruby -e / sh -c / bash -c / powershell -Command / pwsh -c
```

删除类命令 rm/del/rmdir/rd **任意形态均拦截**（裸 `rmdir` 空目录、`rm`/`del` 单文件也弹确认，不限于 -rf、/s、/q）——见 §90 之前的删除检测放宽记录。另有敏感文件命令检测（§90）不属于这 28 条正则，是独立的 `command_references_sensitive_file()` token 匹配。

命令检查的特殊逻辑：危险命令**即使在 allow 模式也要确认**（`check_command` 独立于普通规则流）；普通命令在 ask 模式下自动放行——弹窗只留给真正危险的操作，避免"狼来了"式的确认疲劳。

**会话授权**：用户批准一次后可 `grant_session_permission(scope, pattern)` 记入会话白名单，同类操作不再重复弹窗。

**运行时规则管理**（扩展点 #3 接入）：
- `add_rule(rule, *, _silent=False) -> bool`：运行时动态添加规则，带空 pattern 校验、去重、事件发射（`PermissionRuleAddedEvent`）。`_silent=True` 用于启动加载阶段（不发事件）
- `remove_rule(scope, pattern, level) -> bool`：按三元组移除，发射 `PermissionRuleRemovedEvent`
- `list_rules() -> list[PermissionRule]`：返回规则列表副本供外部查看
- `save_rule_to_file(path, rule)`：将规则追加到 TOML 权限文件（读取已有内容 → 合并去重 → 回写）
- `/allow` `/deny` 斜杠命令：`/allow command "docker *"` 添加 ALLOW 规则，`/deny path "*/secrets/*"` 添加 DENY 规则，`--save` 标志持久化到项目级 `permissions.toml`
- `_load_rules_from_config()` 和 `load_rule_files()` 统一走 `add_rule(_silent=True)`，保证所有规则入口单一

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
- **为什么 CONFIRM 短路上交？** HookManager 不持有 UI 引用（工具层不依赖交互层），确认动作由持有 terminal 的上层执行——已接线：`agent_loop._resolve_hook_confirm` 用 app 注入的 `terminal.confirm` 弹 y/a/n 裁决（a = 本会话内同一 (工具, 原因) 不再询问；无 UI 回调时安全拒绝；弹窗加 asyncio.Lock 防并行工具执行时交错），配置层经 `[[hooks]]` 的 `action = "confirm"` 直接可用
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

`PermissionManager(config, path_guard, confirm_callback=terminal.confirm, event_bus=event_bus)` 完成接线：权限系统需要问人时，Rich Panel 弹出黄色警告框，`y/n` 输入即裁决。依赖方向是 App 装配时注入回调，安全层本身不 import UI。`event_bus` 用于发射 `PermissionRuleAddedEvent` / `PermissionRuleRemovedEvent`。

## 3.6 测试验证矩阵

49 个 P3 测试（含 add_rule/remove_rule/list_rules/save_rule_to_file 13 个新增）覆盖：

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

`llm/token_counter.py` 提供基础文本计数，消息级精确计数由 `ContextManager.count_message()` 负责：

```
count_tokens(text)                    → 单段文本的 token 数（token_counter.py）
ContextManager.count_message(msg)     → 单条 Message（含 role +4 开销 + 每个 tool_call +3 开销）（memory/context.py）
```

> 注：原 `token_counter.py` 中的 `count_message_tokens()` / `count_messages_tokens()` 两个函数操作 API dict 格式但从未被调用，已在 P75 删除；其 per-tool-call +3 开销逻辑已合并进 `ContextManager.count_message()`。

**双路径策略**：

| 路径 | 精度 | 场景 |
|---|---|---|
| tiktoken（cl100k_base 编码） | 精确 | 安装了可选依赖 tiktoken 时 |
| CJK 感知估算（P43） | 估算 | 无 tiktoken 的兜底——CJK 字符 1 token/字 + 其余 4 字符/token（原纯 `len//4` 对中文低估 ~56%，实测见 §43） |

每条消息额外加 4 token 开销（角色标记 + 分隔符），工具调用额外加 3 token/call（函数名 + 参数包裹）。

### 设计权衡

- **为什么 tiktoken 是可选依赖？** 它是编译型包（Rust 实现），在部分环境下载困难（我们的清华镜像就 403 了）。核心功能不应因此无法使用。
- **为什么不调 API 的 token 计数端点？** 每次发请求前先调一次计数 API 开销太大且增加延迟。P43 用了零成本的替代：**复用每轮响应自带的 usage 字段**做锚点（见 §43.2）——权威计数不需要额外请求，本地估算只覆盖锚点后的增量消息。

## 4.2 ContextManager 上下文管理器

### 实现原理

`memory/context.py` 是上下文窗口的"仪表盘"：

```
ContextManager:
    count_message(msg) → int      # 计数并缓存到 msg.token_count
    update_total(conv) → int      # 重算总量（优先 API usage 锚点，P43）
    record_api_usage(conv, usage) # 锚定 API 返回的权威总量（P43）
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

**Stage 2: LLMSummarizeOldest（LLM 语义摘要，默认）**

token 驱动保留窗口（P65-P68）：从尾部反向累计 token，满足 `KEEP_RECENT_TOKENS`(10K) 且 `MIN_KEEP_MESSAGES`(5) 时停止，硬顶 `KEEP_MAX_TOKENS`(40K)，三者均按压缩目标缩放。保留的消息不动，之前的所有消息由 LLM 生成结构化摘要（`<analysis>` 草稿 + 9 节 `<summary>`，P67）。LLM 失败自动回退**提取式摘要**（每条消息取角色 + 前 300 字符 / 工具名 / 结果状态），不调 LLM：

```
[Compressed conversation history]
[user] 帮我读取 README...
[assistant] called tools: read_file
[tool] read_file → ok
[assistant] 这个项目是一个...
```

设计决策：P4 阶段用提取式而非 LLM 摘要，原因是避免压缩本身消耗 token、避免递归 API 调用的复杂性、以及保持可测性（无网络依赖）。P64.2 已将 LLM 摘要设为默认（`llm_summarize=True`），失败自动回退提取式。

**Stage 3: SlidingWindow（滑动窗口兜底）**

前两级仍然超限时，从后往前按 token 预算保留尽可能多的最近消息。这是"核选项"——会丢失所有早期上下文，但保证系统不会因为 context overflow 崩溃。

### 级联控制

```
Compressor.compress(conversation, target_tokens):
    for strategy in [DropToolResults, LLMSummarizeOldest, SlidingWindow]:
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

**序列化的关键挑战**：Message 中嵌套了 frozen dataclass（ToolCall/ToolResult）、datetime、Path——全部手动转换为 JSON 兼容类型（isoformat/str），不用 Pydantic 的 `.model_dump()`（核心消息模型是 dataclass 不是 Pydantic model）。

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

**Adapter 层**（`adapter.py`）：`MCPToolAdapter` 实现内部 Tool ABC——这是关键设计。MCP 工具的 inputSchema（JSON Schema）转换为内部 ToolParameter 列表（走 `to_json_schema()` 的 ToolParameter 后备路径，与 Pydantic 工具的 `raw_parameters` 直通路径共存），工具名加 `mcp_{server}_` 前缀防冲突。适配后 MCP 工具**注册进同一个 ToolRegistry**，AgentLoop 调用它和调用内置工具零区别——权限检查、Hook 链、错误处理全部自动生效。

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
    2. while not plan.is_complete:               # Plan.is_complete 驱动循环
         batch = 依赖已满足的 pending 步骤
         非写步骤 → registry.filter(denied=_WRITE_TOOLS)  # 剥夺写工具
         spawn(带角色前缀的子任务, allowed_tools)
         wait_all(batch) → 回写 step.status
    3. 生成 TeamRunReport
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

TraceRenderer（`ui/trace.py`）是一个**纯 EventBus 订阅者**——不改 ReAct 循环任何逻辑，只订阅 8 种事件渲染输出：

```
UserMessage / AgentPhaseChange / PermissionCheck / ToolCallStart /
ToolCallEnd / LLMRequest / LLMResponse / TurnComplete
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

# 第十部分：P10 垂直场景定制

## 10.1 问题：如何证明"可改造"不是空话

positioning.md 方向 3 提出"垂直场景定制"——CC 覆盖不好的场景做深度定制，证明拥有源码的实际价值。需要三个不同类型的场景，每个代表一种定制范式。

## 10.2 三个场景与三种范式

### 教学模式（EventBus 订阅者 + Skill 辅助）

`/explain on` 开启 `ui/teach.py` 的 TeachRenderer。它是一个纯 EventBus 订阅者（与 TraceRenderer 同范式），订阅 `ToolCallStartEvent`，在每次工具调用前**确定性打印** Rich Panel 教学面板——包含 "Why this tool"（为什么选这个工具）、"Args"（实际参数）、"Params guide"（参数含义）。原始 6 个内置工具（read_file/write_file/edit_file/bash/glob/grep）各有专属文案，其余工具（delete_file/spawn_agents 等）和 MCP 工具用默认兜底。

**从 Skill 注入到 EventBus 硬注入的演进**：最初尝试纯 Skill 方案（注入 system prompt 指令让 LLM "自觉"解释），但实测发现小模型对格式指令遵从度低——教学段要么不出现要么挪到末尾。改为 EventBus 订阅者后 100% 确定性输出，不依赖 LLM 能力。`skills/teach-mode/SKILL.md` 保留作为辅助（让 LLM 输出推理 walkthrough），两者互补。

### 合规审计模式（EventBus 订阅者范式）

`/audit on` 开启 `security/audit.py` 的 AuditLogger。它是一个纯 EventBus 订阅者（与 TraceRenderer 同范式），订阅 UserMessage + ToolCallStart/End + PermissionCheck 四种事件，每条写一行 JSON 到 `~/.mini-agent/audit.jsonl`。

设计选择：
- **同步写而非异步**：审计日志写入量极小（每次工具调用 2-3 行 JSON），同步 `open+append` 比引入 aiofiles 依赖更简单可靠
- **EventBus 而非 Hook**：Hook 可以 BLOCK/MODIFY（属于执行路径），审计只需观察（属于旁路监控）。EventBus 的 fire-and-forget 语义更准确，且订阅者异常不影响主流程
- **哈希链防篡改**：每条记录携带 `prev_hash` 和 `hash = sha256(prev_hash + 规范化内容)`，链式依赖使篡改或删除任何一行后，其后所有哈希全部失配。`/audit verify` 重放校验并定位第一处断裂（区分"内容被改"和"行被删"）。进程重启后从文件尾恢复链尾哈希自动续接。选哈希链不选加密：日志在用户机器上无需防读取，"可验证没改过"才是审计的核心价值；且零依赖（标准库 hashlib）
- **开关持久化**：`/audit on` 在日志目录写 `.audit_on` 标记文件，重启后 AuditLogger 构造时读取——审计开启后跨会话一直生效，直到显式 `/audit off`（审计的语义本就该持久，内存开关重启即失效违背直觉）

**安全边界**：哈希链提供的是 tamper-evident（篡改留痕）而非 tamper-proof（不可写入）——单机上任何有文件写权限的主体都能修改日志，软件层无法阻止，链只保证"改了必被 verify 检出"。两个已知局限：

1. **不防全链重算**：攻击者若把被改行之后的所有哈希重算一遍（算法开源无秘密），verify 会通过。防御需要 HMAC 密钥（单机存不住）或外部锚定（把链尾哈希定期发到攻击者控制不了的地方：远程日志服务器/时间戳服务），均超出单机工具边界
2. **发现依赖主动 verify**：篡改瞬间无警报，链不记录"谁在何时改的"

这与 Git 的提交历史是同一信任模型：不阻止改历史，但改了哈希全变。单机条件下这是行业标准做法的上限。

### 内网离线环境（零代码 Skill 范式）

`skills/offline-ollama/SKILL.md` 提供 Ollama 配置指引——这不需要任何新代码。项目本来就支持任意 OpenAI 兼容 API，Ollama 的 `/v1` 端点完全兼容。Skill 的价值在于**用户发现性**：用户输入"ollama"或"离线"时自动匹配建议，告诉用户怎么配置。

## 10.3 架构投资的兑现

三个场景各用一种定制范式，且每种都复用已有基础设施：

| 场景 | 范式 | 复用组件 |
|---|---|---|
| 教学模式 | EventBus 订阅者（确定性）+ Skill 辅助 | TeachRenderer + SkillRegistry |
| 审计模式 | EventBus 订阅者 | EventBus.on/off + 事件类型 |
| 离线环境 | 零代码 Skill | SkillRegistry + OpenAI 兼容 Provider |

这证明了 P1 的 EventBus（教学 + 审计两个订阅者）、P5 的 Skill 系统（教学辅助 + 离线指引）、P1 的 Provider 抽象层（Ollama 零代码接入）三项架构投资在垂直场景中的复用价值。

## 10.4 验证

- 12 个新单元测试（AuditLogger 7 + TeachRenderer 5）
- 217 个测试全过，lint/format 通过

---

# 第十一部分：P11 机制实验

## 11.1 问题：从"做了个项目"到"做了研究"

positioning.md 方向 4 提出"机制实验床"——拿自己的实现做对照实验，产出用商用产品得不到的数据。两个实验各回答一个具体研究问题。

## 11.2 LLMSummarizeOldest：roadmap 1.1 插槽的兑现

实验 1 需要 LLM 摘要作为第三个对照臂，恰好兑现 roadmap 1.1 预留的升级插槽：

- **策略选择逻辑复用**：把 `SummarizeOldest` 的提取式拼接抽成模块级函数 `_extractive_digest()`，LLM 版和提取式版共用消息选择/替换逻辑
- **防递归**：摘要调用是一次性直连 `llm.stream()` 请求，不经过 AgentLoop——压缩发生在 OBSERVE 阶段内部，若走 AgentLoop 会再次触发压缩检查造成递归
- **失败即回退**：LLM 网络异常或空响应时回退提取式摘要——压缩链在任何情况下都必须产出结果，否则对话会因超窗被 API 拒绝
- **P11 阶段不动默认链**：`Compressor()` 默认策略列表不变——压缩本身耗 token，是否值得由实验决定。P64.2 实验结论后改为默认启用（`llm_summarize=True`），`app.py` 装配时自动替换 Stage 2

## 11.3 实验设计要点

### 实验 1：压缩策略 A/B（compression_ab.py）

关键设计：**人为压小上下文窗口**（6000 token、阈值 0.6）。benchmark 任务只有几千 token，正常 128k 窗口永远不触发压缩，三臂无差异。压小窗口后压缩被强制触发，三臂的行为差异才可观测。

三臂：none（无压缩基线）/ extractive（提取式级联）/ llm（LLM 摘要级联）。指标：verify 通过率、token、成本、工具调用数、compressed 消息数。

### 实验 2：强弱模型混合编排（model_mix.py）

关键前提：架构原生支持——`Planner(llm)` 和 `SubAgentManager(llm)` 各自接受独立的 LLMProvider，`AgentTeam(config, planner, manager)` 只做编排不关心模型。强弱混合 = 构造两个 Provider 分别注入，零框架改动。

三臂：strong-strong / strong-weak（假设：分解靠智商，执行靠体力）/ weak-weak（成本下限）。任务是可分解复合任务（写 3 个文档），验证方式为产出文件存在且非空。

## 11.4 实验结果与发现

真实 API 全量运行（compression 15 次 + mix 6 次），两个反直觉发现：

1. **压缩的隐性代价是"重复劳动"**：小窗口强制压缩下，压缩臂不但没省 token 反而更贵（none 9.7k → extractive 13.8k → llm 36.1k 平均 token）。摘要丢失细节后 Agent 重新读文件找回信息，工具调用翻 2-5 倍。压缩的正确定位是防溢出兜底，不是省钱手段
2. **strong-weak 混编是帕累托最优**：强 Planner + 弱 Worker 全通过且成本最低（$0.0016 vs strong-strong $0.0024），而 strong-strong 反而挂了一个任务（失败在执行侧漏产出文件）——分解质量比执行模型档次更能决定结果

完整数据与边界说明见 `experiments/README.md`。4 个新单测（MockLLM：摘要成功/网络失败回退/空响应回退/过少跳过）。

---

# 第十二部分：P12 多 Agent 命令入口

## 12.1 问题：多 Agent 能力没有终端入口

P6 实现了完整的 SubAgent/AgentTeam/Planner/Worktree 体系，但只能通过 Python 代码调用——终端用户完全用不上。这让多 Agent 成了"有能力但不可触达"的暗功能。

## 12.2 /spawn 设计：从 SubAgent API 到用户命令

`/spawn` 是 SubAgentManager 的命令行壳。子命令设计参考了 `/session`（save/list/load/delete 模式），核心映射：

| 命令 | 底层 API |
|---|---|
| `/spawn <task>` | `subagent_manager.spawn(task)` |
| `/spawn -p t1 \| t2` | `spawn_parallel(tasks)` |
| `/spawn --isolated <task>` | `spawn(task, isolation="worktree")` |
| `/spawn list` | `list_active()` + `get_status()` |
| `/spawn wait [id]` | `wait(id)` 或 `wait_all()` |
| `/spawn cancel [id]` | `cancel(id)` 或 `cancel_all()` |

## 12.3 /team 设计：按需装配 + 强弱混编接线

`/team` 在每次调用时按需创建 Planner + AgentTeam（不在 Application.__init__ 预创建，因为大多数会话不用团队编排）：

```python
planner_llm = ProviderRegistry.create_for_role(config, "planner")  # roadmap 2.5
planner = Planner(llm=planner_llm)
team = AgentTeam(TeamConfig(...), planner, app.subagent_manager)
report = await team.start(task)
```

`create_for_role` 读取 `config.planner_profile` / `config.worker_profile`，有配置用配置的模型，没配置回退主模型——用户不感知混编细节，但 .env 配了立即生效。

## 12.4 Application 装配变更

`SubAgentManager` 和 `WorktreeManager` 是首次在 Application 中实例化。之前只有 AgentLoop（单 Agent 循环），现在加了多 Agent 基础设施：

- `WorktreeManager(repo_dir=working_dir)` — worktree 隔离能力
- `SubAgentManager(llm=worker_llm, ...)` — worker LLM 用 `create_for_role(config, "worker")` 创建
- 两个新事件 `SubAgentSpawnEvent` / `SubAgentCompleteEvent` 在 spawn/wait 时 emit，供未来进度面板（roadmap 2.2）和审计日志使用

## 12.5 验证

8 个新测试（spawn 单任务/并行/list+cancel、事件 emit 2 个、命令 handler 3 个）。

---

# 第十三部分：P13 SubAgent 进度面板

## 13.1 问题：多 Agent 执行期间的静默黑箱

`/spawn wait` 和 `/team` 阻塞等待后台 agent 时终端完全静默——用户不知道每个 agent 在做什么、卡在哪个阶段、跑了多久。roadmap 2.2 要求实时面板。

## 13.2 两个关键设计决策

### run_while 包裹模式，而非常驻订阅者

TraceRenderer/AuditLogger 是常驻 EventBus 订阅者（attach 一次，enabled 开关），但进度面板选择了不同的模式：

```python
board = SubAgentBoard(console, mgr)
result = await board.run_while(mgr.wait_all(timeout=300))
```

面板只在被包裹的 awaitable 运行期间存在（Live 用 `transient=True`，结束自动擦除）。原因：
1. **Live 冲突约束**：Rich 同一 Console 只允许一个 Live。StreamRenderer 的 Live 在 LLM 流式期间活跃；斜杠命令不经过 AgentLoop，`/spawn wait` 阻塞期间 StreamRenderer 必然不活跃——run_while 的生命周期天然落在安全窗口内。常驻订阅者做不到这一点（SubAgent 事件可能在主循环流式期间到达）
2. **无状态**：面板每 0.25s 轮询 `active_snapshots()` 重画整表，不维护任何跨刷新状态，不存在事件丢失/乱序问题

### 轮询快照，而非事件驱动

共享 EventBus 的 ToolCallStart/End 事件没有 agent_id——多个 SubAgent 并行时无法归属。与其给全部事件加 agent_id（侵入大），不如每次刷新时从各 agent 自己的 conversation 现数：`sum(len(m.tool_calls) for m in agent._conversation.messages)`。为此加了公开接口 `SubAgentManager.active_snapshots()`（AgentSnapshot：agent_id/task/phase/tool_calls/elapsed_seconds），面板不触碰私有成员。

## 13.3 效果

```
              SubAgent Progress
┌──────────┬──────────────────────┬─────────────┬───────┬───────┐
│ Agent    │ Task                 │ Phase       │ Tools │ Time  │
├──────────┼──────────────────────┼─────────────┼───────┼───────┤
│ a3f8c2d1 │ 读取 README 统计行数 │ tool_calling  │     2 │  3.2s │
│ 9b7e4f02 │ 分析 pyproject 依赖  │ thinking     │     1 │  3.1s │
└──────────┴──────────────────────┴─────────────┴───────┴───────┘
```

全部完成后表格消失（transient），命令返回的结果正常打印——面板是过程可视化，结果仍由命令输出承载。

## 13.4 验证

7 个新测试（快照字段/空列表、run_while 结果透传/包裹真实 wait/异常透传、渲染含 agent 信息/空表提示）。

## 13.5 真实 /team 运行暴露的三个缺陷（E2E 的价值）

面板上线后第一次真实 `/team` 运行（"分析项目写架构摘要"）报告 SUCCESS，但目标文件根本没生成——单测全绿挡不住的三个系统性缺陷：

1. **SUCCESS 误报**：两个 agent 触发迭代熔断被强停（输出 `(stopped: iteration limit)`），但 `SubAgent.run()` 只要不抛异常就 success=True。修复：`AgentLoop.stopped_early` 标志，熔断终止 = 失败
2. **并行执行撞上接力依赖**：Planner 分解出"第 4 步读前 3 步的产出文件"，但 AgentTeam 纯并行 spawn——第 4 步启动时文件不存在，反复重试直到熔断（烧掉 40 万 token）。修复：`PlanStep.depends_on` + 分批调度（无依赖并行、有依赖等前置批、依赖失败则跳过）+ 前置产出注入后续 prompt
3. **LLM 的 Unix 路径习惯**：SubAgent prompt 没有平台信息，LLM 把产出写到 `/tmp/`（Windows 上落到 D:\tmp）。修复：prompt 补平台/shell + 相对路径硬约束 + "文件不存在就报告勿重试"

教训与 P7 一致：**单测验证组件正确，只有真实 E2E 才暴露系统级交互缺陷**——依赖、平台、成功语义都是组件边界之外的问题。

第二轮 E2E（修复后重跑）暴露第 4 个问题：**弱模型 + 重任务 + 迭代上限的三重叠加**——"阅读项目主要源代码"这种任务对 60+ 文件的项目根本不可能在 50 轮内完成，弱 worker 又不会抓重点，读到一半被熔断（这次报告如实显示 FAILED，修复 2 生效）。对策双管齐下：
- **Planner 端控制粒度**：prompt 加 SIZE LIMIT——子任务须 ~15 次工具调用内可完成，"分析整个代码库"必须改写为限定范围（"读 src/core/ 下 3 个文件"），允许抽样
- **SubAgent 端预算感知**：prompt 加 BUDGET 段——告知总轮次预算，要求优先做最重要的事、预算将尽立即写出已有发现。部分产出优于空手熔断

第三轮 E2E 暴露第 5 个问题：**中间文件污染**——用户只要一个 sum.md，运行完根目录多出 project_overview.md 等三个中间文件。根因：修复 3 引入"依赖产出注入 prompt"后，信息已可走内存传递，但 Planner prompt 仍要求"每个子任务明确产出文件"，诱导它设计"各写一个文件再合并"的计划。对策：Planner prompt 加 NO INTERMEDIATE FILES（分析类子任务只输出报告文本，仅用户明确要求的文件由最终步骤写出）+ 依赖报告注入上限提到 4000 字符（成为唯一信息通道后不能截太狠）+ 单任务最多读 5 个文件。

第四轮 E2E 证明 **prompt 说服对弱模型不可靠**：NO INTERMEDIATE FILES 规则被无视（中间文件照写），Planner 还在套 backend/frontend 的 web 模板盲分解（第 2 步自己报告"这项目没有前端"）。两个代码级修复：
- **能力剥夺替代 prompt 约束**：`PlanStep.writes_files` 字段，AgentTeam 对非写步骤直接从工具白名单剔除 write_file/edit_file——物理上没有写文件能力，违规不可能发生。这是 P3 安全层教训的复用：黑名单/说服防不住，能力剥夺才防得住
- **信息对齐替代盲分解**：team.start() 分解前做两级目录扫描注入 Planner context——看到真实结构（Python CLI、src/mini_agent 分层）就不会套 web 模板

第五轮（换强模型 worker 对照）是**关键的排除实验**：deepseek-chat 也在完全相同的位置熔断——归因瞬间反转，问题不在模型纪律而在框架本身。

第六轮定位到真正的病根：**死循环护栏误杀正常工作**。三重熔断之一"同一工具连续 6 次即死循环"把"连续 read_file 读 6 个不同文件"——分析类任务的标准动作——当成了死循环。这解释了此前所有反常：熔断的总是读多文件的步骤、agent 遗言总是"让我再读几个文件"（它没失控，是被错杀）、模型越强执行越有条理反而死得越快。修复：死循环签名从"工具名"改为"工具名+参数 JSON"（`record_tool_call(name, args_key)`）——只有完全相同的重复调用才熔断（真卡死如反复试 heredoc 仍会被拦），批量处理不同文件不再误伤。

修复后立即验证成功：`/team 分析项目生成架构摘要到su.md` 四步全 [OK]，su.md（242 行）真实生成，零中间文件，136K token（比首轮 426K 降 68%）。

**六轮 E2E 的完整教训链**：成功语义误报 → 依赖并行冲突 → 平台路径习惯 → 任务粒度失控 → prompt 遵从失效 → **护栏误杀**。前五轮都在治症状，第六轮才找到病根——而找到它靠的是第五轮的对照实验（换强模型排除模型因素）。调试多 Agent 系统的方法论与调试代码相同：先隔离变量，再定位根因。425 个测试全过。

---

# 第十四部分：P14 LLM 自主派生 SubAgent

## 14.1 从命令到工具：多 Agent 的第三层入口

P12 实现了 `/spawn`（用户手动）和 `/team`（Planner LLM 规划）两层入口，但 LLM 在主对话中无法自己决定"这个任务我派子代理并行去做"。`spawn_agents` 工具补齐了第三层——LLM 自主调用，在 ReAct 循环的 ACT 阶段派生 SubAgent。

关键设计：`ToolContext` 加 `subagent_manager` 可选字段（TYPE_CHECKING 避循环导入），app.py 通过 post-hoc mutation 注入（无需重排构造顺序）。递归防护双保险：SubAgent clone registry 时 unregister("spawn_agents") + SubAgent 的 ToolContext.subagent_manager=None。

---

# 第十五部分：P15 会话自动保存

## 15.1 closed_cleanly 崩溃信号

`SessionMetadata.closed_cleanly` 字段：会话进行中每次自动保存都带 False，正常退出（finally 块）翻 True + 强制保存。硬杀进程跳过 finally → 磁盘留 False → 下次启动检测到同目录的 False 会话 → 提示恢复。

## 15.2 ask_yes_no 的 prompt_session 污染 bug

首次实现用 `self._prompt_session.prompt_async(f"{恢复提示} [y/n] > ")`——prompt_toolkit 的 `prompt_async(message=...)` 会永久更新 session 的默认 message，导致后续每轮输入框都显示恢复提示。修复：改用临时 `PromptSession()`，问完即销毁。

---

# 第十六部分：P16 /theme 主题切换

## 16.1 从"画好了"到"接上了"

themes.py 的三套主题从 P1 就存在，但 8 个语义色位从未接入渲染——所有颜色硬编码在 6 个 UI 文件里。本次把每个 UI 组件的构造器加 `theme: Theme` 参数，硬编码替换为 `self.theme.primary` 等引用。`/theme dark` 运行时切换通过 prompt_session 重建（`self._prompt_session = None`）+ 共享 theme 引用实现。

## 16.2 色差问题

首版三套主题色差太小（default/dark 都是紫蓝系，暗底终端几乎看不出差异）。修正：dark 的 primary 改为暖橙 `#ff9e64`、light 改为 GitHub 蓝 `#0550ae`——现在三套主题是三种完全不同的视觉风格。

---

# 第十七部分：P17 工具并行执行

## 17.1 预检分流：串行确认 + 并行执行

`_act()` 从"逐个串行"重写为两阶段：Phase 1 串行权限预检（确认弹窗按顺序弹，不交错）→ Phase 2 所有 GRANTED 的工具 `asyncio.gather` 并行执行。单工具走快速路径不 gather（零开销）。`_run_tool_pipeline` 加 `skip_permission` 参数跳过已在 Phase 1 做过的权限检查。

## 17.2 AuditLogger 并行安全

并行工具同时 emit ToolCallStartEvent → AuditLogger 的 `_on_tool_start` 协程可能在 `_write()` 的 `_last_hash` 读写之间交错（asyncio 单线程但有 await 点让出），破坏 hash chain。修复：三个 handler 加 `asyncio.Lock`，`_write` 的 hash 计算和文件 append 在锁内完成。

---

# 第十八部分：P18 双 Esc 中断流式输出

## 18.1 问题：Ctrl+C 的粗暴与风险

Ctrl+C 在 Python 中抛 KeyboardInterrupt，可能在任意 await 点打断——文件写到一半、HTTP 连接未关闭、conversation 状态不一致。需要一个优雅的中断方式。

## 18.2 守护线程 + cancelled 标志

EscWatcher 在流式开始时启动守护线程，以 50ms 间隔轮询 stdin（Windows msvcrt.kbhit/getch、Unix select）。检测到 500ms 内两次 Esc 后设 triggered 标志。on_stream_delta 回调检查该标志并调 agent_loop.cancel()，_think 循环在下一个 chunk 处 break——部分响应完整保留在 conversation，LLM 下轮可以看到它上次说到哪里。

关键约束：EscWatcher 只在流式期间活跃（start/stop 生命周期），不和 prompt_toolkit 的 stdin 读取冲突。

---

# 第十九部分：P19 PRE_LLM / SESSION_END Hook 接线

## 19.1 从死枚举到活接线

HookStage 从 P3 就定义了 7 个值，但只有 PRE_TOOL/POST_TOOL 真正接进执行流。PRE_LLM 和 SESSION_END 作为枚举值存在但从未被 run()——属于"有接口没接线"的死代码。本次激活它们并注册了两个内置 hook。

## 19.2 长记忆自动化

P4 实现了记忆系统的全部零件（存/取/提取），但需要用户手动 `/memory add`。本次通过两个内置 hook 把手动变自动：
- **PRE_LLM 记忆注入**：每轮 LLM 调用前加载 PersistentMemory，首次追加到 system prompt（`--- Relevant memories ---` 标记防重复）
- **SESSION_END 记忆提取**：退出时 MemoryExtractor 自动从对话中提取偏好写入 PersistentMemory（auto_extract 配置首次生效）

用户无需做任何事——聊天中说的偏好下次启动就会被 LLM 记住。

---

# 第二十部分：P20 上下文溢写兜底

## 20.1 防护链的最后一环

P4 实现了三级压缩（75% 阈值触发，压到 50%），但如果三级全走完还是放不下（消息太多/工具输出太长/系统 prompt 太大），消息原样发给 API → HTTP 400 → 对话崩溃。ensure_fits 是最后一道防线：在 _think() 的 llm.stream() 之前预检 token 总量，超限时直接调 SlidingWindow 截到 85%——不走三级级联（它们已经走过了），直接滑动窗口兜底。

放在 PRE_LLM hook 之后检查，因为 hook 可能修改 system prompt（如记忆注入）改变 token 数。

---

# 第二十一部分：P21 TOML 配置文件

## 21.1 从三层到七层

配置从 .env + 环境变量 + CLI 三层扩展为七层：defaults → user TOML → project TOML → .env → env vars → profiles → CLI。TOML 层插在 .env 之前——这意味着 .env 里的值优先于 TOML（用户可以用 .env 临时覆盖 TOML 配置而不用改文件）。

## 21.2 _merge 深度合并

TOML 解析后是嵌套 dict（如 `{"llm": {"model": "x"}}`），需要映射到 AgentConfig 的 dataclass 树。`_merge` 按三种情况处理：顶级标量（如 `theme = "dark"`）直接 setattr 到 AgentConfig；section dict（如 `[llm]`）遍历子字段 setattr 到对应子 dataclass；`[mcp.servers.<name>]` 特殊处理为 MCPServerConfig 构造（因为是 dict of dataclass，不是简单 setattr）。

`_apply_cli` 同步泛化：从只处理 `llm.*` 改为按 "." 拆分后 getattr 到任意子配置——这修复了之前 env var 层只能设 llm 字段的限制。

---

# 第二十二部分：P22 接口冻结 + 覆盖率门禁

## 22.1 接口冻结的含义

四个 ABC（Tool/LLMProvider/HookFn/CompressionStrategy）的方法签名从 v1.0.0 起承诺稳定——这不是"不再改"，而是"改了就必须升 major 版本"。新增可选参数（有默认值）和新增方法不算破坏，修改/删除已有签名算。

这个承诺的实际作用：如果有人写了一个自定义 Tool 或 LLMProvider，升级 mini-code-agent 的 patch/minor 版本不会让他的代码坏掉。对自己来说：改接口前必须三思——是改了真的更好，还是可以通过加可选参数向后兼容。

## 22.2 覆盖率门禁的排除策略

总覆盖率 77%，排除 TTY/MCP 层后 80.36%（P22 时为 81.62%）。排除的理由：

- `ui/terminal.py`（36%）、`ui/input_handler.py`（34%）：prompt_toolkit 的输入循环需要真实 TTY，CI 环境无 TTY。这些代码只能手动验证
- `ui/esc_watcher.py`（48%）：后台线程 + stdin 轮询，同样需要 TTY
- `ui/components.py`（0%）：Rich spinner/status 等 UI 组件，纯展示代码
- `mcp/client.py`（32%）、`mcp/transport.py`（32%）：需要真实 MCP 服务器子进程，FakeMCPManager 只覆盖 adapter 层

排除这些后，core/tools/security/memory/models/events/config/llm 的覆盖率 >80%——这些是逻辑密集、最容易出 bug 的代码。

---

# 第二十三部分：P23 Diff 预览 + Streaming 中间态

## 23.1 Diff 预览的实现选择

edit_file 执行后同时拥有旧内容和新内容，用 difflib.unified_diff 生成 diff 存入 ToolResult.metadata["diff"]——不改 output（output 是给 LLM 看的操作结果文本，加 diff 会浪费 token），diff 只在 UI 层渲染。

渲染用 Rich 的 Text 对象 + pad(terminal_width) + stylize("color on bg_color")——背景色从左到右铺满整行，视觉上形成色条块（删除行深红 #3d0000、新增行深绿 #002d00），比只高亮文字更醒目。跳过 ---/+++/@@ 头部只显示变更内容。

一个踩坑：无换行符的文件（如 `hello world` 没有 `\n` 结尾），splitlines(keepends=True) 最后一个元素不带 `\n`，导致 difflib 生成的删除行和新增行粘在一起（`-hello world+goodbye world`）。修复：改用 splitlines() 后手动给每行加 `\n`。

## 23.2 Streaming 工具调用组装提示

LLM 返回纯 tool_call（无 text delta）时，流式期间用户看到空白——因为 on_stream_start 只在有 text delta 时触发。on_tool_call_assembling 回调在 _think 循环中检测 tool_call_delta 的 name 字段（首次出现时触发），app.py 接线后立即打印 `╭─ tool_name ...`，让用户知道 LLM 在生成哪个工具的调用。on_tool_start 检查是否已显示过，避免重复 ╭─ 行——已显示的只补充参数摘要行 `│ args...`。

---

# 第二十四部分：P24 文件变更汇总

## 24.1 集中跟踪 vs 逐工具跟踪

两个选择：每个文件工具在 execute 里上报，或在 agent_loop 的工具执行处统一判定。选后者——_execute_single_tool 处工具名/参数/结果全部可用，一个 `_record_file_change()` 方法覆盖所有情况，工具本身零改动。write_file 已有的 metadata["existed"]（P2 就存在）恰好能区分新建和覆写，无需新增字段。

去重策略：dict 按路径去重，"created 优先"——一轮里先 write_file 新建再 edit_file 修改，对用户来说这个文件就是"这轮新建的"，显示 created 比 modified 更准确。

## 24.2 delete_file 专用工具

删除原本只能走 bash（rm/del），不可跟踪。新增 `delete_file` 工具（第 8 个内置工具）：删除单个文件、拒绝删除目录，schema description 写明 "Prefer this over shell rm/del" 引导 LLM 优先选它。`_record_file_change` 对 deleted 的合并规则是"删除覆盖一切"——先建后删显示 deleted（文件最终没了），与 created 优先的规则相反但语义一致：都以用户视角的最终状态为准。UI 显示红色 `- 路径`。

## 24.3 已知局限

bash 的文件变更（echo x > file、rm、mv）无法跟踪——bash 输出只有 exit_code，跟踪需要文件系统快照对比，成本远超收益。delete_file 提供后 LLM 会优先用可跟踪的删除方式，但 bash 直删仍是盲区。SubAgent 的变更也不计入（独立 AgentLoop 实例）。这些局限在输出上的表现是：汇总清单可能不完整，但列出来的一定是真的。

---

# 第二十五部分：P25 上下文感知

## 25.1 启动注入 vs PRE_LLM hook 注入

已有的记忆注入走 PRE_LLM hook（每次 LLM 调用前检查），但指令文件选择在 __init__ 启动注入——两者内容性质不同：记忆会随会话增长（SESSION_END 自动提取新条目），需要每次调用前重新加载；指令文件是静态的（改了要重启才生效，这是有意设计），启动读一次就够。两者都用 marker 去重（"--- Project instructions ---" / "--- Relevant memories ---"），防止会话恢复时重复拼接。

## 25.2 文件优先级设计

AGENT.md > CLAUDE.md > .mini-agent/instructions.md。AGENT.md 放最前是因为它是社区中立标准（多工具通用）；CLAUDE.md 兼容 CC 生态（大量项目已有现成文件，mini-agent 直接受益）；.mini-agent/instructions.md 是本项目专属命名空间，适合不想让其他工具读到的指令。找到第一个就停（不合并）——避免多文件内容冲突时 LLM 无所适从。

## 25.3 从写死到可配置：[context] 段

文件名列表、优先级、截断长度初版写死在模块常量里。后按"约定优于配置"改造：`models/config.py` 加 `ContextConfig` dataclass（instruction_files / user_instructions_file / max_chars），`project_context.py` 的函数改为接受参数、原写死值降级为参数默认值。P21 的 TOML `_merge` 是通用的（按 section 名自动映射到 AgentConfig 同名字段），所以 config.toml 里写 `[context]` 段零胶水代码即生效。不配置时行为与写死版完全一致——可配置性是纯增量。

---

# 第二十六部分：P26 对话分叉/回滚

## 26.1 为什么 CC 做不到而这里可以

CC 的对话历史由 Anthropic 服务端管理，客户端无法截断或复制。mini-code-agent 的 Conversation 是本地自持有的 dataclass（messages 列表），回滚 = 列表截断，分叉 = deepcopy + 新 session_id。数据结构的所有权决定了能力边界——这是"可读参考实现"的一个直接好处。

## 26.2 轮次定界与状态一致性

无显式 turn 标记，扫描 Role.USER 消息定界：一轮 = 一条 USER 消息 + 其后所有 ASSISTANT/TOOL 消息。/undo 找倒数第 N 条 USER 索引截断列表尾部。截断后两处状态要同步：context_manager.update_total() 重算 token（同 /compact 和 _adopt_session 的先例），metadata.total_turns 递减。metadata.total_tokens_used 不回退——它是累计消费（历史开销），不是当前状态。

/fork 的关键顺序：先把原线存盘（防止切换后丢失未保存的消息），再 deepcopy + 切换 + 存盘新分支。deepcopy 是必要的——Message 是可变 dataclass，浅拷贝会让两个会话共享消息对象，改一边脏另一边。

---

# 第二十七部分：P27 操作级撤销

## 27.1 快照的三态设计

工具执行前拦截 write_file/edit_file/delete_file，按目标文件当时的状态记录三种情况：文件存在且 ≤30MB → 复制内容（saved）；不存在 → 记 missing（undo 语义 = 删除该轮新建的文件）；>30MB → 记 too_large（undo 时提示手动恢复而非静默跳过——用户必须知道哪些没恢复）。同轮同文件只存第一次：一轮内改三次，undo 恢复到轮前状态而非中间态。

## 27.2 恢复顺序与容量控制

/undo N 按轮次倒序恢复（先恢复最新轮再恢复更早轮）——同一文件跨轮被改时，更早轮的快照最后写入，最终回到最早状态。容量三重控制：只保留最近 5 轮（begin_turn 时清理）、单文件 30MB 上限、会话结束 clear() 全清——最坏情况磁盘临时占用几十 MB，会话结束归零。bash 的文件变更仍是盲区（无法预知 shell 改什么），与 P24 文件变更汇总同样的既有局限。

---

# 第二十八部分：P28 工具链录制/回放

## 28.1 录制为什么走 EventBus 而非改 agent_loop

ToolCallStartEvent（带 arguments）+ ToolCallEndEvent（带 is_error，按 call_id 关联）已经包含录制所需的全部信息——加一个订阅者即可，agent_loop 零改动。这是 EventBus 解耦价值的又一次体现（前例：TraceRenderer/TeachRenderer/AuditLogger 都是纯订阅者）。只录成功调用：失败的调用重放出来还是失败，没有价值还可能有害。

## 28.2 回放的安全等价原则

/replay 逐条构造 ToolCall 调 _execute_single_tool（skip_permission=False）——权限检查、PRE/POST_TOOL hook、文件快照全部照走。这保证回放的安全性与 LLM 真实执行完全一致：录制里藏了危险命令，回放时照样弹权限确认；回放改错了文件，/undo 照样能撤。一个细节：回放期间 recorder.suspended 置 True，防止"正在录制时执行回放"把回放的调用再录进去（无限套娃）。

## 28.3 与 Skill 的定位差异

Skill 是手写的自然语言指令，LLM 读了照做——仍要推理，弱模型可能理解偏差；录制是从实际操作自动生成的确定性脚本，逐字重放不经 LLM。两者互补：探索性/需要判断的流程用 Skill，固定不变的流程用录制。

---

# 第二十九部分：P29 成本仪表盘

## 29.1 被丢弃的数据

openai_provider 一直在解析 usage chunk 的 prompt_tokens/completion_tokens（stream_options.include_usage），但 agent_loop 只把 total_tokens 加进计数——拆分数据在 emit LLMResponseEvent 时被丢弃。成本跟踪的第一步就是把这条已有的数据通路接完：事件加三个带默认值的字段（向后兼容，不碰冻结接口），emit 时填充。教训：做新功能前先查数据是不是已经有了——这次 80% 的"数据管道"原本就存在。

## 29.2 模型归属的三个来源

成本按模型分账，但 LLMProvider ABC 没有 model 属性（接口已冻结不能加）。解法：AgentLoop 加 model_name 普通属性，三处赋值——app 初始化（主模型）、switch_llm_profile 和 /model 裸名兜底（切换）、SubAgentManager 构造（worker 模型，从 llm_profiles[worker_profile] 解析）。SubAgent 的 LLM 调用 emit 到共享 EventBus，所以强弱混编下 Planner 用贵模型、Worker 用便宜模型，/cost 里各算各的——这正是验证混编省钱效果的直接工具。

## 29.3 预算不阻断的设计选择

超预算只警告（80% 黄/100% 红）不拦截 LLM 调用。理由：工具不该替用户做花钱决定——用户可能正在关键任务中途，强行阻断的代价（半途而废）通常高于超支本身。预算是提醒线不是熔断线；真要止损，用户看到红色警告后 Ctrl+C 或 /exit 即可。

---

---

# 第三十部分：P30 LLM 记忆提取

## 30.1 从 regex 到 LLM——为什么以及怎么做

P4 的 regex 匹配靠关键词（always/prefer/don't），用户不用这些词就什么也提取不到——"这个项目用 uv 管理"不含任何触发词但显然是值得记住的约定。LLM 理解语义，不依赖关键词，覆盖率质变。代价是 SESSION_END 时多一次 LLM 调用——取最近 20 条消息（ASSISTANT 截断 200 字），token 消耗约 2-5K（flash 模型几乎零成本）。

提取 prompt 要求只提取 USER 明确说的/确认的（不提取 ASSISTANT 的假设），跳过临时性内容，每条自包含可读——这些规则防止记忆池被垃圾污染。

## 30.2 词重叠去重的取舍

精确匹配 + substring 去重只能挡完全相同的重复。"always use type hints on functions" 和 "use type hints on all functions always" 内容等价但字面不同——substring 过不掉。词重叠（60% 交集）用最小集合分母衡量：5 个词里有 3 个一样 → 60% → 视为重复。60% 阈值在测试中验证过：太低（40%）会误杀不相关条目，太高（80%）形同虚设。不做 embedding 语义相似——需要额外模型，与 flash 级提取的成本定位矛盾。

---

# 第三十一部分：P31 MCP HTTP Transport

## 31.1 两步激活：传输层 + 应用接线

MCP 在 P5 就做了完整的 client/adapter/transport 三层架构和 config 解析，但从未接入 app.py——config.toml 里写了 [mcp.servers.github] 也不会有任何效果（没人调 connect_server）。P31 做两件事：加 HTTPTransport（约 30 行），以及在 app.py 的 run() 里遍历 config.mcp.servers 逐个连接（约 15 行）。大部分"工作"早就做完了——这次只是把线接上。

## 31.2 为什么不做 SSE

MCP 协议定义了 Streamable HTTP（POST + SSE 推送），但 SSE 是可选优化：它让服务器能主动推送进度/部分结果。工具调用（tools/list + tools/call）是请求-响应模式，POST 已完全覆盖。SSE 需要长连接管理、重连逻辑、事件解析——复杂度翻倍但本项目没有需要主动推送的 MCP 服务器场景。如果以后要对接需要 SSE 的服务器，只需加一个 SSETransport 实现 MCPTransport ABC。

## 31.3 认证 headers

HTTPTransport 构造时已接受 headers 参数（计划阶段预留），P31 收尾时补上了 MCPServerConfig.headers 字段和 connect_server 传递——3 行代码把认证链路接通。config.toml 里 `headers = { Authorization = "Bearer xxx" }` 经 TOML 解析为 dict，`_merge` 按字段 setattr 直通，HTTPTransport 在每次 POST 里带上。不做独立的 auth_token/auth_type 配置——headers 是最通用的形式（Basic/Bearer/自定义头都能表达），用户已经熟悉 HTTP headers 概念。

---

# 第三十二部分：P32 持久化任务系统（S12）

## 32.1 S12 缺口分析

S01-S20 对照审计中 S12 是唯一有实际价值的缺口。PlanStep 已有依赖图（depends_on）和四种状态（pending/in_progress/completed/failed），但它是 /team 执行引擎的内部数据结构——用完即弃，用户看不到改不了。S12 要求的是用户可管理、跨会话持久的任务列表。

解法不是改 PlanStep——两者粒度不同（LLM 一步可能对应用户好几个 task）。新建 TaskRecord + TaskStore，/todo 是纯用户界面，/team 是 LLM 执行引擎，两者独立互不干扰。

## 32.2 设计选择

单文件 `tasks.json` 而非按任务一个文件——任务量不会大到需要分文件（不是 sessions 的几百个），JSON 方便用编辑器直接改。ID 用 `task_<uuid8>` 而非整数（PlanStep 用整数 index 在 /team 内部自增，跨会话不唯一）。ID 前缀匹配（`/todo done task_a1` 匹配完整 ID）是用户体验细节——16 位全输太长。歧义前缀（匹配多个任务）抛 `AmbiguousTaskError` 并列出所有匹配项，避免静默返回第一个。显示时用 `min_unique_prefix()` 自动计算最短唯一前缀（最少 5 字符），替代固定 `[:12]` 截断——任务少时 ID 更短，任务多时自动加长以保证唯一。

# 第三十四部分：P34 Windows 终端适配

## 34.1 逻辑行 vs 物理行——流式首行重复的真相

Rich Live 擦除旧帧时按"上次渲染了几行"回退光标。_render_tail 限制尾段 15 逻辑行，但一条 200 字符的行在 80 宽终端下占 3 物理行——Live 以为画了 15 行实际占了 45 行，回退 15 行擦除后残留 30 行旧帧，视觉上就是"首行重复"。legacy Windows 控制台的光标控制精度更差，放大了这个问题。修复：_tail_budget 用 console.width 估算物理行数，超预算时按比例收缩逻辑行数；刷新率 15→8Hz 减少重绘竞争；vertical_overflow=crop 避免省略号在 legacy 下的额外不确定性。

## 34.2 兜底优先于完美

三个修复共享同一哲学：**先保证不崩，再谈体验**。UTF-8 reconfigure 失败就 errors=replace 显示问号（丑但不崩）；PromptSession 构造失败就退回朴素 input（没有补全但能答 y/n）；emoji 显示错乱就降级 ASCII 方括号。Windows 终端生态碎片化（conhost/Windows Terminal/ConEmu/Git Bash 行为各异），逐一完美适配不现实——分层降级让最坏情况也可用。

## 34.3 实战暴露的三个后续问题（P34 验证时发现）

**① bash 子进程输出 GBK 乱码（已修）**：P34 修了自己打印的字符编码，漏了子进程输出的解码——中文 Windows 的 CMD 错误信息是 GBK（"'wc' 不是内部或外部命令"变成乱码）。修复：`_decode_console_bytes` 三级解码——严格 UTF-8 → 控制台活动代码页/GBK → UTF-8 容错兜底。教训：编码适配要覆盖输入（自己打印）和输出（子进程返回）两个方向。

**② LLM 擅自执行 git 状态修改操作（已加双层防护）**：用户问"介绍所有文档"，LLM 跑偏成"审计 P34 工作状态"，中途执行了 git stash/stash pop，最后试图 git commit。两层修复：system prompt 加 CRITICAL 红线（非用户明确要求绝不执行 commit/push/stash/reset/rebase 等状态修改命令 + 不许把简单问题扩大为项目审计）；DANGEROUS_COMMAND_PATTERNS 从只拦 push --force / reset --hard 扩充为拦截全部 git 状态修改命令（commit/push/reset/stash/rebase/checkout/restore/clean 均需用户确认）。提示词是软约束、权限确认是硬闸门——LLM 不听话时闸门兜底。

**③ 压缩-重读膨胀的实战重现（已于 P36 根治，见 §36）**：同一请求烧了 50 万 token（¥0.51）。trace 显示同一文件被读 3-4 次：读大量文档 → 触发 75% 压缩 → 已读内容被摘要掉 → LLM"忘了"读过 → 重读 → 再触发压缩。机制实验 1 的结论（压缩的隐性代价是重复劳动）在真实使用中完整重现。same-tool-6x 熔断没拦住——每次读的参数不同（offset/文件名），签名不重复。**根治方案（P36 已实现）**：双层修复——大工具结果溢写磁盘 + 压缩后注入已读文件清单。

## 34.4 mintty（Git Bash）适配——管道 stdin 的两个坑

Git Bash 的 mintty 不是 Windows 控制台——它把 stdin 包装成管道，带来两个独立故障：

**① 启动秒退**：prompt_toolkit 的 PromptSession 在管道 stdin 上构造成功但 prompt_async 立即 EOF，主循环读到空输入直接 Goodbye。修复：`Terminal._stdin_is_console()` 用 `sys.stdin.isatty()` 检测，管道环境自动降级为朴素 `input()`（无补全/工具栏但可正常对话）。想要完整体验用 `winpty mini`——winpty 桥接出真控制台。

**② 孤立代理字符崩溃**：用户名/路径含中文（GBK）时，mintty 管道经 surrogateescape 解码产生 `\udc81` 这类孤立代理字符，混进 system prompt 的 working_dir——httpx 的 UTF-8 JSON 编码直接抛 `surrogates not allowed`，请求发不出去。修复双层：cli.py 入口把 stdin 也 reconfigure 为 UTF-8 + replace（源头减量）；openai_provider 发请求前 `_sanitize_surrogates` 递归清洗整个消息树（出口兜底，任何来源的代理字符都替换成 `?`）。教训同 34.2——**出口兜底比堵住所有入口更可靠**，代理字符可能来自 stdin、环境变量、文件读取任何一路。

> 各系统各终端的打开方法、兼容等级、排查表见 [terminal-guide.md](guide/terminal-guide.md)。

# 第三十五部分：死循环诱导实验

## 35.1 实验发现——same-tool-6x 形同虚设

三重熔断的单元测试（MockLLM）中 same-tool-6x 工作正常——因为 MockLLM 机械地返回完全相同的工具调用。但真实 LLM（deepseek-v4-flash）**从未触发过 same-tool-6x**：即使在明显的死循环中，LLM 每次都会微调参数（不同的搜索模式、不同的 edit 内容、不同的命令参数），使得 `name(args_key)` 签名永远不重复。

这揭示了一个设计盲区：`record_tool_call` 使用 `name + args 前 200 字符` 作为签名，本意是"同一工具处理不同文件是正常的"——但结果是**任何参数变化都让检测失效**。候选改进方向：只比较工具名（忽略参数），或改为"最近 N 次调用中同名工具占比超过阈值"。但要注意不能太激进——read_file 连读 6 个不同文件是正常的批量操作。

## 35.2 same-tool-6x 增强：按轮统计的同名工具检测（v2，修正过一次误杀）

实验暴露问题后，第一版增强按"最近 12 次调用中同名 ≥10 次"检测——**实战立刻误杀**：用户问"详细解释所有文档"，LLM 高效地在 4 轮内并行读了 10 个文档（一轮读 3-4 个），12 次调用里 read_file 占 10 次，触发熔断，回答没生成就被终止。

教训：**死循环的特征是"每轮迭代都在调同一个工具"，不是"调用总量大"**。一轮内并行调 10 次是高效批量；连续 8 轮每轮都调才是循环。

v2 改为按轮统计：`AgentState.iteration_tools` 记录每轮迭代用到的工具名集合（滑窗 8），`_should_continue` 检查**连续 8 轮的交集**——某个工具名在每一轮都出现才熔断。批量并行读文档只占 3-4 轮，永不触发；真死循环（每轮 read 一次 ×8 轮）依然被拦。

两层检测互补：
- 第一层（原有）：`name(args)` 签名完全相同 ×6 → 捕获机械重复
- 第二层（v2）：同一工具名连续 8 轮每轮出现 → 捕获真实 LLM 的参数变换式循环，且不误杀批量任务

## 35.3 self_referential 是最危险的模式

5 个诱导场景中，只有 "反复改进文章" 在 normal 臂（max=20）也没停下来——跑满 20 轮消耗 330K token。原因：这类任务的停止条件天然模糊（"直到完美"），LLM 总能找到"可以更好"的改进点，形成真正的无限循环。

其余 4 个场景在 normal 臂下都自然停止——LLM 足够"聪明"，几轮后就判断任务不可能完成并主动报告。这说明 LLM 的自主判断是第一道防线，迭代上限是兜底。

## 35.4 迭代上限是唯一可靠的硬熔断

实验证明三重熔断的实际保护力排序：**迭代上限 >> LLM 自主停止 >> same-tool-6x（未触发）**。预算警告只是提醒（soft fuse），不阻止循环。默认 max_iterations=50 保持合理——允许复杂任务有足够空间，同时在最坏情况下限制损失。

# 第三十六部分：压缩-重读膨胀根治（P36）

## 36.1 问题回顾与双层修复

34.3 ③ 记录的实战问题：单请求烧 50 万 token。链条是 读大文件 → 内容整体进对话 → 触发 75% 压缩 → 摘要连内容带文件名一起丢弃（`DropToolResults` 只留前 200 字符，`_extractive_digest` 压成 `read_file → ok`）→ LLM"忘了"读过 → 重读 → 再压缩 → 循环。

修复分两层，借鉴 mewcode 的成熟方案（comparison-mewcode.md §4.1/§4.2）：

**第一层：溢写（源头减量）**。`memory/tool_result_cache.py` 的 `ToolResultCache.maybe_spill()`——工具结果超过 50K 字符（`[memory] spill_threshold_chars` 可配，0 禁用）时写入 `~/.mini-agent/cache/results/{session_id}/`，对话中只留 2000 字符预览（P64.1 起，原 500）+ 占位提示（含溢写文件路径，可用 offset/limit 精读该文件或重跑工具）。大文件根本不进对话，压缩触发频率大幅下降。挂载点在 `agent_loop._run_tool_pipeline()`——工具管线层，SubAgent（没有 ContextManager）同样受保护。

**第二层：已读清单注入（断循环）**。`ContextManager.record_file_read()` 追踪本会话读过的文件（保序去重）；压缩完成后 `_inject_read_files()` 在摘要消息末尾追加 `[Files already read this session -- do NOT re-read unless their content changed: a.py, b.md]`。二次压缩时替换旧清单（清单可能已增长）；纯 SlidingWindow 路径（无摘要消息）插入独立 SYSTEM 消息。

## 36.2 为什么两层都要

只做溢写：小于 50K 的文件仍然会进对话并在压缩时丢失身份——多个中等文件累积照样触发重读。只做清单：大文件第一次读还是全量进对话，一个 200K 的文件立即吃掉 50K token。两层配合：大文件被拦在门外，中小文件被清单记住——重读循环的两个入口都被堵上。

## 36.3 实战验证暴露的第三个洞：任务锚点

P36 上线后实测"详细介绍所有文档"：溢写生效（tech-notes 60K+ 字符只留 661 字符预览）、熔断不再误杀（v2 按轮统计）、token 从 50 万降到 17 万——但 LLM 读完所有文档后反问"你要我做什么？"。

原因：单轮膨胀到 173K 超过 128K 窗口 → `ensure_fits` 强制 SlidingWindow 截断（从后往前保留）→ 用户的**提问是本轮最旧的消息**（后面跟着几十条工具结果）→ 被丢弃 → 任务没了。

修复：SlidingWindow 增加**任务锚点**——截断后如果保留的消息里没有任何 USER 消息，把最近一条用户消息插回最前。摘要路径（SummarizeOldest）不受此影响——提问会以 `[user] 内容前300字符` 形式留在摘要里。

教训：压缩策略的保护优先级应该是 **用户任务 > 已读状态 > 工具结果内容**——任务丢了一切白读。

## 36.4 设计细节

- `ToolResult` 是 frozen dataclass——溢写通过重建实现（与 `DropToolResults` 同模式），`metadata` 带 `spilled_path`/`full_chars` 供排查
- 错误结果永不溢写（错误信息本来就该完整可见）
- 文件路径只存在于 `tc.arguments`——记录点选在 agent_loop（同时看得到调用参数和结果），而非改 read_file 的 metadata
- 预览长度取 `min(PREVIEW_CHARS, threshold)`（PREVIEW_CHARS 初始 500，P64.1 升至 2000）——防止极小阈值下预览本身超阈值
- 缓存生命周期：主会话正常退出时清理；SubAgent 在 `run()` 的 finally 里清理

# 第三十七部分：Anthropic Prompt 缓存（P37）

## 37.1 三个缓存标记点

Anthropic API 支持 `cache_control: {"type": "ephemeral"}`——标记的内容被 API 缓存，后续请求前缀相同则命中缓存（输入 token 成本降约 90%）。标记放在"最长稳定前缀"的三个末端：

1. **系统提示**：每次请求都一样——`body["system"]` 从字符串改为 `[{"type": "text", "text": ..., "cache_control": {"type": "ephemeral"}}]`（Anthropic API 接受两种格式）
2. **工具 schema 最后一个**：工具定义每次也一样——浅拷贝最后一个 dict 加标记（不污染原始数据）
3. **最后一条用户消息**：到这里为止是对话的稳定前缀——字符串内容自动升级为块格式

三个标记后面的内容（新的 assistant 回复、工具结果）自然落在缓存范围之外。

## 37.2 缓存命中统计

`_parse_event` 在 `message_start` 事件中新增解析 `cache_read_input_tokens`（命中）和 `cache_creation_input_tokens`（首次写入），传入 `TokenUsage`。P75 已将这两个字段接入 `LLMResponseEvent` → `CostTracker`，支持 `cache_read` / `cache_creation` 差异化定价（pricing 中未配则退回 `input` 价格）。OpenAI/DeepSeek 等其他 Provider 服务端自动缓存，无需客户端标记。

# 第三十八部分：流式工具执行（P38）

## 38.1 判定信号：流式中怎么知道一个工具调用组装完了

Chat Completions 协议没有"单个工具调用结束"事件，但有两个可靠信号：**出现更高 index 的 delta**（协议按顺序传输，新调用开始意味着旧调用结束）和 **finish_reason 到达**（关闭最后一个未完成的调用）。`IncrementalAssembler.feed()` 维护与 `assemble_response` 同构的 per-index builder，在这两个信号上即时 flush ToolCall——组装逻辑不重复造，只是把"事后一次性组装"变成"流中增量组装"。

## 38.2 权限预判：会弹窗的不能流中执行

`_check_permission` 是 async 且可能弹确认框——弹窗和流式渲染会打架（Rich Live 冲突）。解法是 `PermissionManager.would_ask()`：**非交互、无副作用**地预判"这次调用会不会弹窗"。判定素材全部复用现有构件：显式规则匹配/session grant → 不弹；危险命令 → 弹；PathGuard 项目内 ALLOW/敏感 DENY → 不弹；项目外 + ask 模式 → 弹。不弹的流中直接 `asyncio.create_task` 提交（走完整的 `_execute_single_tool` 管线——权限、hook、溢写、审计全生效）；会弹的延迟到 `_act()` 的原有串行确认阶段。

## 38.3 顺序保持与取消清理

流中提交的任务按 `call_id` 存入 `_streaming_tasks`；`_act()` 收集时按 tool_calls 原顺序遍历——已提交的 await 任务，其余走常规路径，OBSERVE 阶段的 TOOL 消息顺序与调用顺序严格一致（API 要求 tool_result 与 tool_use 配对）。取消路径两处清理：`cancel()` 主动取消所有未完成任务；流中断导致 response 无 tool_calls 时取消孤儿任务（提交了但没人收集）。

`streaming_tool_execution = false` 完全回退 P17 的"流后并行"行为——排查问题时可对照。

# 第三十九部分：@file 内联引用（P39）

## 39.1 展开时机：_handle_turn 而非 get_user_input

`expand_at_refs()` 放在 `_handle_turn()` 创建 Message 之前——而非 `get_user_input()` 返回后立即展开。原因：斜杠命令也经过 `get_user_input()`，如果在那里展开，`/memory add @README.md` 会把整个文件内容作为记忆存入——不是预期行为。放在 `_handle_turn` 则只对真正要发给 LLM 的消息展开。

## 39.2 正则与容错

`_AT_REF_RE = r"@([\w./_\-\\]+(?:\.[\w]+)*)"` 匹配路径字符（字母/数字/点/斜杠/连字符/反斜杠），要求至少一个文件扩展名片段。不匹配 `@mention`（无路径分隔符且无扩展名时通常不是文件）——但如果有个目录叫 `mention/`，`@mention/` 会被尝试。匹配到但路径不是真实文件时**原样保留**（不报错不替换）。10KB 上限截断——大文件应该用 read_file 的 offset/limit 按需读取。

## 39.3 补全触发

`FileRefCompleter` 用 `os.listdir` 单目录扫描（不递归），跳过 `.git`/`.venv`/`__pycache__` 等。目录结尾加 `/` 支持钻入（`@src/` → 列出 src 下的文件）。`merge_completers` 合并斜杠命令和文件引用两个补全器——按键触发条件从 `text.startswith("/")` 扩展为 `text.startswith("/") or "@" in text`。

# 第四十部分：权限规则文件（P40）

## 40.1 从硬编码到用户可配

危险命令模式和敏感路径此前硬编码在 `DANGEROUS_COMMAND_PATTERNS` / `SENSITIVE_FILE_PATTERNS`——用户想"docker build 免确认"必须改源码。P40 支持两级 TOML 规则文件（用户级 `~/.mini-agent/permissions.toml` + 项目级 `.mini-agent/permissions.toml`），`load_rule_files()` 启动时解析 `[commands]`/`[paths]`/`[tools]`（P79 新增）的 allow/deny 列表为 `PermissionRule` 追加进现有规则表——评估逻辑零改动，完全复用 `check()` 的 DENY→ALLOW→session→mode 顺序。文件缺失跳过、格式错误警告不崩（启动韧性优先）。

## 40.2 顺带修复的盲区：PATH deny 被项目内放行短路

实现时发现 `check_path()` 的流程是"先问 PathGuard，项目内 ALLOW 直接返回"——显式 DENY 规则根本没机会被评估。用户写 `deny = ["*secrets*"]` 拦项目内的机密目录会**静默失效**。修复：`check_path()` 和 `_would_ask_path()` 都在 PathGuard 之前先查 `_deny_rule_matches()`——DENY 规则最优先，符合权限系统"显式拒绝高于一切"的一贯哲学。这是一个"加功能时暴露旧盲区"的典型案例：规则文件让 PATH deny 第一次有了真实用户，短路问题才浮出水面。

# 第四十一部分：OS 级沙箱（P41）

## 41.1 为什么 Windows 不做

Windows 的 Job Objects / AppContainers 需要管理员权限或 COM 接口调用，复杂度远超收益。Linux bwrap 和 macOS Seatbelt 都是用户态免提权——bwrap 用用户命名空间（`--unshare-user`），Seatbelt 是每进程 sandbox profile。Windows 保持现有正则拦截 + P40 的规则文件——regex 不是内核隔离但有 deny 规则兜底。

## 41.2 bwrap vs Seatbelt 的关键差异

两者效果等价（命令只能读不能写，除白名单路径外），但机制完全不同：

| | bwrap (Linux) | Seatbelt (macOS) |
|---|---|---|
| 隔离机制 | 用户命名空间 + 绑定挂载 | 进程沙箱策略（SBPL） |
| 只读方式 | `--ro-bind / /`（整个 rootfs 只读挂载） | `(deny default)` + `(allow file-read*)` |
| 可写方式 | `--bind <path> <path>`（覆盖挂载） | `(allow file-write* (subpath "<path>"))` |
| 禁网 | `--unshare-net`（网络命名空间隔离） | `(deny network*)` |
| deny > allow | 后挂载覆盖前挂载 | 后匹配优先（SBPL 是 last-match-wins） |

## 41.3 auto_allow 不绕过 deny

`sandbox_auto_allow` 的设计意图是"内核提供了隔离，不需要每次弹窗问用户了"——但显式 deny 规则仍然拦截。评估顺序：显式规则（P40）→ sandbox_auto_allow → 弹窗。deny 规则在 sandbox_auto_allow 之前被评估（`_check_rules_only` 在 `check_command` 的第一步），所以 `denied_commands = ["docker rm *"]` 即使沙箱开启也会被拒绝——用户的意志高于自动化。

# 第四十二部分：上下文窗口 API 探测（P42）

## 42.1 为什么需要：硬编码表跟不上模型上新

Provider 的 `context_window` 属性驱动 `ensure_fits` 溢出兜底（`agent_loop._think()` 在每次 LLM 调用前用它预检强制截断；压缩触发阈值另走 `MemoryConfig.context_window` 配置值）。此前它来自硬编码的 `MODEL_CONTEXT_WINDOWS` 表——每有新模型就要改源码，而第三方兼容服务（DeepSeek、阿里云 MaaS、OpenRouter、本地 vLLM）的模型名根本不可能提前穷举，全都落到 128k 默认值。默认值偏大时的后果是实质性的：真实窗口 8k 的本地模型按 128k 算，`ensure_fits` 预检永远放行，直接 HTTP 400 崩溃。

## 42.2 探测机制：GET /models/{model} + 递归字段提取

OpenAI 兼容服务普遍实现了 `GET {base_url}/models/{model}` 端点，但**返回结构没有标准**——这是本实现最核心的经验：

- 字段名各家不同：`context_window` / `context_length`（OpenRouter）/ `max_context_length` / `max_model_len`（vLLM）/ `max_input_tokens`（阿里云 MaaS）
- 嵌套深度各家不同：OpenRouter 在 `top_provider.context_length`，阿里云 MaaS 藏在 `extra_info.default_envs.max_input_tokens` 三层深

所以 `_extract_context_window()` 做**递归查找**：先查当前层的 5 个候选字段名（要求正整数），再深入所有 dict 子对象。初版只查顶层+一层嵌套，真实 API 实测（阿里云 MaaS）返回 `None` 才暴露问题——**mock 单测验证不了供应商响应结构的多样性，真实 API 实测不可省略**。实测三个模型（deepseek-v4-flash-0731 / deepseek-v4-flash / qwen3.6-plus）均成功探测到 129024。

回退链三层：探测值 → `MODEL_CONTEXT_WINDOWS` 表 → 128k 默认。探测失败（404、超时、无效 JSON、字段缺失）静默回退不打扰用户——探测是增强不是依赖。

## 42.3 探测时机：prepare() 钩子解决"首轮读不到"

天真的做法是在 `stream()` 入口探测——但 `agent_loop._think()` 在调用 `stream()` **之前**就读 `context_window` 做溢出预检，首轮拿到的永远是回退值。解决：`LLMProvider.prepare()` 可选预热钩子（基类默认无操作，Anthropic/Mock Provider 零改动），三个触发点覆盖 provider 的全部创建路径：

1. `app.run()` 启动时——首轮对话前完成探测
2. `/model` 切换后（命名 profile 和裸模型名两条路径）——新 provider 立即探测
3. `stream()` 入口兜底——其他路径（SubAgent worker 等）创建的 provider 首次调用时探测

`_probe_attempted` 标志保证每实例只探测一次（成败皆然），10 秒独立超时不拖慢启动。

# 第四十三部分：Token 计数精度提升（P43）

## 43.1 为什么需要：len//4 对中文低估过半，且误差逐轮累积

token 计数驱动压缩阈值判断（75% 水位触发）。此前无 tiktoken 环境（编译型依赖，部分镜像 403）全靠 `len(text) // 4` 估算——对英文尚可，对中文实测**低估 56%**（824 字符的中文段落真实 468 token，估算只有 206）。低估的方向是危险的：压缩迟迟不触发 → 上下文持续膨胀 → 超窗 HTTP 400。且估算按消息逐条累加，误差随对话轮数线性累积，越到后期越离谱。

## 43.2 主力机制：API usage 锚点——让估算退居配角

比"更准的估算"更本质的改进是**尽量不估算**。每次 LLM 响应的 `usage.prompt_tokens` 是 API 实际计费的权威数字，它覆盖了估算根本看不到的东西——工具 schema（几十个工具的 JSON schema 可能上万 token）、消息格式开销、系统提示。

`record_api_usage()` 在每轮响应后把 `prompt + completion` 总量锚定在最新一条消息上；`update_total()` 检查锚点有效性：有效则"锚点总量 + 锚点之后新消息的估算"，无效则回退全量估算。这样估算只覆盖锚点后追加的一两条消息（下一轮响应又会刷新锚点），**误差不再累积**。

锚点有效性用**对象身份**（`msgs[i] is anchor`）而非索引判断——压缩、undo、截断都会重排 `conversation.messages`，重排后锚定消息不在原位置（或已被替换），身份检查自动失效并安全回退。这比"在压缩代码里手动清锚点"可靠：不管未来加多少种历史重排操作，锚点永远不会错误地存活。

## 43.3 配角改进：CJK 感知估算 + 实测校准

估算公式从纯 `len//4` 改为：CJK 字符（7 个 Unicode 区间：汉字/扩展 A/假名/谚文/全角符号/中日韩标点/兼容汉字）按 1 token/字，其余按 4 字符/token。不采用原方案"CJK 占比 >30% 时 len//2"——按字符归类无阈值跳变，混合文本更平滑。

**真实 API 实测校准**（阿里云 MaaS deepseek-v4-flash-0731，API usage 为真值）：

| 样本 | API 真值 | 旧 len//4 | 新 CJK 感知 |
|---|---|---|---|
| 纯英文 1456 字符 | 237 | +54% | +54% |
| 纯中文 824 字符 | 468 | **-56%** | +76% |
| 中英混合 1592 字符 | 500 | -20% | +12% |
| 代码 1352 字符 | 340 | -1% | -1% |

两个实测发现：①DeepSeek 分词器对中文压缩率高（~0.57 token/字），1 token/字的假设在它身上偏保守——但 OpenAI cl100k 对中文就是 ~1 token/字，按最保守分词器估算是跨供应商的正确策略；②**高估与低估风险不对称**——低估导致压缩不触发直至崩溃，高估只是压缩稍微提前、多花一点压缩成本。对阈值判断用途，宁可高估。不做按 provider 的自适应系数：锚点机制已把估算的影响限制在增量消息上，那是过度工程。

## 43.4 顺带修复的两个真实 bug

**① assistant 消息的 token_count 存错了量级**（`agent_loop.py`）：原来存 `usage.total_tokens`——它包含**整个 prompt**（系统提示 + 全部历史 + 工具 schema）。`update_total()` 按消息累加时，每条 assistant 消息都携带一份"全对话总量"，对话被重复计算 N 遍——10 轮对话后总量虚高一个数量级，压缩被过早疯狂触发。改存 `completion_tokens`（消息自身的真实大小）。这个 bug 此前被"len//4 低估"部分掩盖——两个方向相反的误差抵消了一部分，修一个必须同时修另一个。

**② assemble_response 的 usage 覆盖丢数据**（现已移至 `llm/base.py`）：原来 `if chunk.usage: usage = chunk.usage` 直接覆盖。OpenAI 把完整 usage 放在最后一个 chunk 没问题；但 Anthropic 拆在两个事件——`message_start` 带 prompt_tokens（含缓存统计），`message_delta` 带 completion_tokens——后者会把前者覆盖清零。改按字段取 max 合并，两家协议都正确。

# 第四十四部分：max_tokens 恢复（P44）

## 44.1 为什么需要：截断的回答直接展示给用户

`max_tokens` 默认 4096——长回答（大文件生成、详细解释）超限时被 API 硬切，`finish_reason` 变为 `"length"`（OpenAI）或 `stop_reason="max_tokens"`（Anthropic）。此前 mini 不检查这个信号，半截回答直接进对话历史并展示。更隐蔽的是工具调用场景：参数 JSON 被中途切断 → 解析失败兜底为空字典 → 工具带错误参数执行。

## 44.2 实现：_think() 重试循环 + finish_reason 归一化

`_think()` 的流式调用提取为 `_stream_once()`，外面包一层重试循环：`finish_reason == "length"` 时把 max_tokens 翻倍（4096 → 8192 → 16384 → 32768）重发，最多 `MAX_TOKENS_RETRIES=3` 次，仍截断则保留最后一次结果——最后一次的上限已是配置值的 8 倍，再截断说明回答本身异常长，保留部分结果比丢弃好。

跨供应商归一化在 Provider 解析层做：Anthropic 的 `stop_reason="max_tokens"` 在 `_parse_event` 里映射为 OpenAI 的 `"length"`——agent_loop 的恢复逻辑对两家通用，未来新 Provider 只需遵守同一约定。max_tokens 的覆盖通过 `stream()` 已有的 `**kwargs` 传递（`kwargs.get("max_tokens") or config.max_tokens`），不改接口签名。

## 44.3 两个边界处理

**流式工具任务的丢弃**：截断尝试中已经流式提交的工具任务必须取消——它们的参数可能正是被切断的那个 JSON。重试成功后的完整响应会重新提交这些工具。

**用户取消不重试**：Esc 中断的流也可能没有正常 finish_reason，重试会违背用户意图——`self._cancelled` 在重试条件中短路。

# 第四十五部分：Coordinator 模式（P45）

## 45.1 为什么需要：规划和执行的注意力分散

`/team` 的 Planner 纯做分解（一次 LLM 调用输出 JSON 计划），看上去已经"只规划不执行"了。但差距在于：① Planner 的 prompt 没有明确声明职责边界，LLM 可能在分解时混入执行细节（"读 main.py 然后..."）而 Worker 其实无法访问 Planner 的上下文；② Planner 只看到 2 级、80 行的项目结构——当它不能自己读文件时，这些信息可能不够支撑细粒度分解。

## 45.2 实现：prompt 强化 + 上下文加深 + 粒度放宽

**不做成 AgentLoop**：comparison 原方案提到"Planner 的 ToolRegistry 只保留 spawn_agents"，暗示把 Planner 改成有工具的 Agent 循环。但当前 Planner 是纯 LLM 调用（一发一收），已经物理上不能操作文件——改 AgentLoop 复杂度远超 "~20 行"的估算，且引入递归风险（Coordinator 调 spawn_agents → Worker 的 AgentLoop 本身也可能被嵌套）。正确的做法是强化已有的纯调度属性。

三处加强：
1. `_COORDINATOR_PREFIX` 注入 Planner prompt——"你是 COORDINATOR，只分解和分派，不能直接读写文件，给 Worker 足够独立工作的上下文"
2. `max_steps` 从 5 放宽到至少 8——Coordinator 不能自己兜底（"最后一步我自己来"），必须把任务拆得更细让 Workers 各自独立
3. 项目扫描从 2 级/80 行加深到 3 级/120 行——`_scan_project_structure()` 重构为递归实现（`_scan_dir()`），coordinator 模式下给 Planner 看到 `core/agent_loop.py` 级别的文件而非只看到 `core/` 目录名

入口：`/team --coordinator <task>` flag 解析（同 `--isolated` 的模式），通过 `TeamConfig.coordinator` 和 `Planner(coordinator=True)` 贯穿数据流。

# 第四十六部分：Pydantic Schema 生成（P46）

## 46.1 为什么需要：手写 schema 的维护成本

每个工具手写 `ToolSchema(name=..., parameters=[ToolParameter(...), ...])` 容易出错（参数名拼错、漏字段、类型不对），且 JSON Schema 只反映了 Pydantic 能自动生成的信息子集。mewcode-python 用 Pydantic model 直接生成 JSON Schema 是明显更好的方案。

## 46.2 实现：params_model + _schema_from_model

每个工具定义 `ParamsModel(BaseModel)` 类（约 5 行），`Tool.params_model` 指向它。`_schema_from_model()` 调用 `model.model_json_schema()` 自动提取 properties/required，7/10 个工具完成转换，BashTool 保留手写 schema 作为向后兼容验证。`validate_args()` 在有 `params_model` 时走 Pydantic 路径（自动类型转换，字符串→int），否则走原手动校验。

## 46.3 设计权衡

- **为什么不全转？** BashTool schema 极简（两个参数），保留它验证手写路径始终可用
- **pydantic 升级为主依赖**：P46 之前是可选依赖，但 schema 自动生成是核心功能，不应降级

# 第四十七部分：Pydantic Schema 全面增强（P47）

## 47.1 为什么需要：P46 的 _schema_from_model 丢信息

P46 的 `_schema_from_model()` 只提取 `type/description/default/enum` 四个字段，Pydantic `model_json_schema()` 能产出的其他信息全部丢失：`str | None` 的 `anyOf` 结构、`list[str]` 的 `items` 子 schema、嵌套模型的 `$ref/$defs`、`Field(ge=0)` 约束、`Literal` 类型等。当前工具参数恰好都简单所以"碰巧能用"，但 schema 输出对 LLM 来说是不完整的。

## 47.2 实现：Raw JSON Schema Passthrough

**核心思路**：Pydantic 已经产出了正确完整的 JSON Schema，我们不应该拆解再重建，只需解引用 + 清理后直通。

1. **`_resolve_refs(schema)`**：递归遍历 JSON Schema dict，遇到 `{"$ref": "#/$defs/X"}` 用 `$defs[X]` 内容替换；`seen: frozenset` 追踪已访问定义防循环引用；去除所有 `title` 和 `$defs` 键（LLM 不用，浪费 token）
2. **`ToolSchema.raw_parameters`**：新增 `dict | None` 字段，Pydantic 路径存完整 JSON Schema
3. **`to_json_schema()` 双路径**：`raw_parameters` 非空时直通输出；否则从 ToolParameter 列表构建（BashTool/MCP adapter 后备路径，同时补上 `default` 值输出）
4. **`_schema_from_model()` 重写**：`model_json_schema()` → `_resolve_refs()` → 存入 `raw_parameters`，`parameters` 传空列表

## 47.3 设计权衡

- **为什么不扩充 ToolParameter？** 要加 `items/anyOf/properties/minimum/maximum/minLength/maxLength/pattern/additionalProperties/...` 等无穷字段，每增加 JSON Schema 特性就要改 ToolParameter + `_schema_from_model` + `to_json_schema` 三处。Raw Passthrough 一劳永逸——Pydantic 支持什么我们就支持什么
- **为什么去 title？** Pydantic 给每个 property 加 `title`（默认为字段名的 Title Case），LLM 不用它且浪费 token
- **循环引用**：理论上 Pydantic 递归类型会产生循环 `$ref`。`_resolve_refs` 用 `seen` 集合检测，遇到循环保留原始 `$ref` 不死循环。工具参数实际不会出现递归类型，但防护零成本

# 第四十八部分：Agent Type Definition（P48）

## 48.1 为什么需要：SubAgent 无差异化

所有 SubAgent 共用同一个 `SUBAGENT_SYSTEM_PROMPT`、同一套工具集、同一个迭代上限。搜索 Agent 带着 write_file 能力上场、验证 Agent 跟执行 Agent 一样的 50 轮预算——浪费且不安全。mewcode 的 4 种 Agent 类型（Explore/Plan/Worker/Verify）是明显更好的设计。

## 48.2 实现：AgentTypeDefinition dataclass + 参数透传

**不做文件加载**：comparison 原方案提到 `.md` 定义文件 + loader，但当前只有 4 种类型且不需要用户自定义，Python dataclass hardcode 更简单、可测、无解析器依赖。

`AgentTypeDefinition(frozen=True)` 包含三个控制维度：
1. **system_prompt** — 专属 prompt 模板（explore 强调只读、verify 要求 PASS/FAIL 结尾）
2. **allowed_tools** — 工具白名单 tuple（explore/plan/verify 只含 read_file/glob/grep/bash；worker 为 None 表示全部）
3. **max_iterations** — 迭代上限覆盖（explore/plan=30, verify=20, worker=50）

参数透传链：`SubAgent.__init__(agent_type=)` → 选择 prompt + 合并工具白名单 + 浅拷贝 config 覆盖迭代上限。`SubAgentManager.spawn(agent_type="explore")` 名称解析为 `AgentTypeDefinition`。`SpawnAgentsTool` 和 `/spawn --type` 暴露给 LLM 和用户。

## 48.3 设计权衡

- **`_intersect_tools` 取交集而非覆盖**：agent_type 的 `allowed_tools` 与调用方传入的 `allowed_tools` 取交集——Team 系统的 `writes_files` 工具剥离不会被 agent_type 绕过
- **浅拷贝 config**：`copy.copy(config)` 只覆盖 `max_agent_iterations`（int 不可变），子 dataclass 引用共享但 SubAgent 不会修改它们
- **不与 Team 系统耦合**：`TeamMember.role` 是自由字符串，由 Planner 输出匹配——连接到 agent_type 会要求 Planner 输出类型名，耦合两个独立系统
- **bash 保留在只读类型中**：安全由权限系统（沙箱/Hook）保障，类型系统只控制工具可见性

# 第四十九部分：Plan 模式只读（P49）

## 49.1 为什么需要：prompt 不是物理约束

主 Agent 没有物理级只读模式——即使 prompt 说"不要修改文件"，LLM 仍然**看得到** write_file/edit_file/delete_file 的 schema，可能仍然调用。SubAgent 的 P48 类型系统已经有物理级工具白名单，主 Agent 缺少同等能力。

## 49.2 实现：双层拦截 + `/plan` 命令

**第一层（schema 隐藏）**：`AgentLoop._think()` 中 `plan_mode=True` 时从 `get_schemas()` 结果过滤掉 `_WRITE_TOOLS`（write_file/edit_file/delete_file）——LLM 看不到这些工具的 schema，自然不会调用。

**第二层（执行拦截）**：`_act()` 中 plan_mode 时写工具调用直接返回 `DENIED`——防止 LLM 幻觉或缓存的旧 schema 触发写操作。流式工具执行也同样延迟写工具。

**`/plan [on|off]` 命令**：切换 `agent_loop.plan_mode`，同时向 system prompt 注入/移除只读提示。

## 49.3 设计权衡

- **bash 不在 _WRITE_TOOLS 中**：bash 可以做危险操作，但也是搜索的核心工具（grep/find/git log）。P48 的 explore/plan/verify 类型都保留 bash。危险命令由权限系统（DANGEROUS_COMMAND_PATTERNS）和 OS 沙箱拦截
- **不修改 ToolRegistry**：plan_mode 是临时状态，不应改变 registry 持有的工具。在 `_think()` 层面过滤 schema 列表比 clone+unregister 更轻量
- **不持久化**：plan_mode 是会话级运行时开关，不存入 config 或 session——重启自动回到正常模式

# 第五十部分：Hook 事件类型扩充（P50）

## 50.1 为什么需要：一半的 HookStage 是死代码

HookStage 定义了 7 个枚举值，但只有 4 个真正触发（PRE_TOOL/POST_TOOL/PRE_LLM/SESSION_END）——POST_LLM/SESSION_START/USER_INPUT 定义至今从未接线。mewcode 有 10 种事件全部生效。用户想在"每轮结束时"或"收到 LLM 响应后"挂 hook 做不到。

## 50.2 实现：新增 4 个 + 接线 3 个 = 11 个全部生效

**新增**：STARTUP（应用启动）/SHUTDOWN（应用退出）/TURN_START（每轮开始）/TURN_END（每轮结束）。

**接线已有**：POST_LLM（`_think()` assemble_response 后）/SESSION_START（SessionStartEvent 旁）/USER_INPUT（用户输入后，BLOCK 可拦截该轮）。

触发点分布：app.py 管生命周期（STARTUP → SESSION_START → USER_INPUT → ... → SESSION_END → SHUTDOWN），agent_loop.py 管轮次（TURN_START → PRE_LLM → POST_LLM → PRE_TOOL → POST_TOOL → TURN_END）。

## 50.3 设计权衡

- **观察式 vs 干预式**：USER_INPUT/PRE_LLM/PRE_TOOL 支持 BLOCK；其余全部观察式（返回值忽略）——干预点只放在"动作发生前"，事后 hook 拦截没有意义
- **全部 try/except 包裹**：hook 是扩展点，用户 hook 抛异常不能破坏主循环（与既有 SESSION_END 一致）
- **不动 EventBus**：comparison 原文把 Hook 和 EventBus 事件混在一起（改动估算指向 models/events.py），实际 7.1 标题是 Hook 事件——EventBus 已有 SessionStart/TurnComplete 等事件，两套系统职责不同（EventBus 观察渲染，Hook 拦截干预），不需要重复
- **PRE_SEND/POST_RECEIVE 等价映射**：mewcode 的这两个对应 mini 的 PRE_LLM/POST_LLM，不另加同义枚举

# 第五十一部分：工具搜索/延迟加载（P51）

## 51.1 为什么需要：100+ MCP 工具全塞上下文

当前所有 MCP 工具连接后全部注册到 ToolRegistry，每轮 `_think()` 都把全部 schema 发给 LLM。接入多个 MCP 服务器时（GitHub + Slack + DB + ...），100+ 工具 schema 轻松占 5000-10000 token，每轮浪费且可能分散 LLM 注意力。

## 51.2 实现：dispatch 模式 + tool_search + mcp_call

**三层设计**：
1. **配置层**：`MCPServerConfig.loading = "eager" | "dispatch"`——eager 是现有行为，dispatch 是新模式
2. **存储层**：`MCPManager._dispatch_tools` shadow catalog——dispatch 工具信息存这里而非注册到 ToolRegistry。LLM 看不到这些工具的 schema
3. **接口层**：两个新内置工具——`tool_search`（按关键词搜索 shadow catalog，返回匹配工具的完整 schema）和 `mcp_call`（用 server/tool/arguments 调用 dispatch 工具）

**流程**：LLM 需要某个功能 → 调 tool_search 搜索 → 看到工具名和参数 → 调 mcp_call 执行。整个过程只在实际需要时才消耗 token。

## 51.3 设计权衡

- **不动态提升到 registry**：ToolSearch 找到工具后不把它注册回 ToolRegistry（那样会越用越多），而是通过 mcp_call 中转——保持 registry 干净
- **搜索是简单子串匹配**：`query.lower() in name.lower() or query.lower() in desc.lower()`——够用，不需要向量搜索或 TF-IDF
- **ToolContext.mcp_manager 用 Any 类型**：避免循环导入（tools/ 不应 import tools/mcp/client）

# 第五十二部分：选择性记忆召回（P52）

## 52.1 为什么需要：无排序截断丢信息又浪费 token

记忆注入是 `entries[:10]` 头部截断——超出的静默丢弃（可能正好是相关的），注入的 10 条可能与当前任务无关。记忆越积越多后，这个问题越来越严重。mewcode 的做法：先让 LLM 挑最相关的 ≤5 条。

## 52.2 实现：MemoryRecall + 阈值触发

**`memory/recall.py`**（仿 `MemoryExtractor._extract_candidates` 的轻量 LLM 调用模式）：
- RECALL_PROMPT 只发 `id + content 前 50 字符`（不发全文，省 token）+ 用户最新消息（截断 500 字符）
- LLM 返回相关 ID 的 JSON 数组 → `_parse_ids()` 解析（去 fence → json.loads → list 校验）
- 按 LLM 返回的 ID 顺序过滤注入——保持 LLM 的相关性排序

**接入点**：`app.py` 的 `_pre_llm_inject_memory` hook——`len(entries) > recall_threshold` 时走召回，否则走原逻辑。marker 一次性注入机制不变。

## 52.3 设计权衡

- **阈值触发而非始终召回**：≤10 条时全部注入 + 零额外 LLM 调用——召回本身也有成本（延迟 + token），记忆少时不划算
- **fail-safe 回退链**：llm=None / stream 异常 / JSON 解析失败 / 非 list → 全部静默回退 `entries[:10]`（现有行为）——召回是优化不是依赖，绝不能因为召回失败丢掉记忆功能
- **幻觉 ID 处理**：LLM 可能返回不存在的 ID，`by_id` 字典过滤自动忽略——不报错不重试
- **不做并行预取**：comparison 提的可选优化（召回与主请求并行）会让 hook 结构复杂化，且 marker 机制每会话只注入一次，收益仅一次调用的延迟——不值得

# 第五十三部分：记忆合并（P53）

## 53.1 为什么需要：词重叠去重抓不住语义冗余

提取时的 `_is_similar`（60% 词重叠）只能挡住表面相似的新条目。"喜欢 tabs" 和 "讨厌 spaces" 语义相关但零词重叠，会作为两条独立记忆累积。长期使用后记忆库充满这类语义冗余——每条都占注入配额（P52 召回也一样按条算）。

## 53.2 实现：MemoryConsolidator + 双触发

**`memory/consolidation.py`**（第三个轻量 LLM 调用模块，与 extraction/recall 同模式）：
- CONSOLIDATION_PROMPT 发全部记忆的 `id: content` 全文（合并需要完整信息，不像召回只需要预览）
- LLM 返回合并组 JSON：`[{"merge_ids": [...], "merged_content": "..."}]`
- 合并规则：保留组内最新 `created_at`（信息新鲜度）、tags 并集保序去重、source="extracted"
- 未合并条目原样保留，整个列表 bulk `save_*_memory` 替换

**双触发**：
1. **自动**：`MemoryExtractor.maybe_extract()` 末尾（SESSION_END），记忆 > `consolidation_threshold`（默认 20）
2. **手动**：`/memory consolidate` 子命令，≥2 条即可跑（用户主动清理不受阈值限制）

## 53.3 设计权衡

- **返回 None 而非原列表**：`consolidate()` 无合并/失败时返回 None，调用方 no-op——避免无意义的整库重写（save 是全量替换，写坏了丢所有记忆）
- **consumed 集合防重复消费**：LLM 可能让同一 ID 出现在多个合并组，只处理首组——否则一条记忆被合并两次会凭空复制信息
- **有效 ID <2 的组直接忽略**：LLM 返回单 ID 组或全幻觉 ID 组时不产生合并条目——合并至少要两条真实记忆
- **与 `_is_similar` 分工**：词重叠去重继续做提取时的廉价预过滤（挡住明显重复的新条目），LLM 合并做周期性深度清理（语义级）——两层互补而非替代

# 第五十四部分：Worktree 完善（P54）

## 54.1 为什么需要：worktree 只有"创建"没有"生命周期"

`merge_back()`/`remove()` 定义了但零调用——隔离 Agent 的产出永远滞留在 `.mini-agent/worktrees/agent-xxxx`，worktree 和 `agent-*` 分支无限累积。且新 worktree 不含 `node_modules`/`.venv`，Agent 在里面跑测试要重装依赖。

## 54.2 实现：三项生命周期能力

1. **依赖符号链接**：`create()` 末尾 `_link_dependency_dirs()`——主仓库的 `node_modules`/`.venv`/`vendor` 存在则 symlink 进 worktree。Windows 无开发者模式缺符号链接权限 → OSError 静默跳过（worktree 仍可用，只是要重装依赖）
2. **过期清理**：`cleanup_stale(max_age_days)`——扫描 base_dir，目录 mtime 超龄且 `status().is_clean` 的删除 worktree + `git branch -D` 删分支。app 启动时自动调用（`worktree_max_age_days=7` 可配，0 禁用）
3. **变更可见**：`/spawn wait` 结果显示 worktree 路径 + `git merge <branch>` 提示——用户知道隔离产出在哪、怎么合并

## 54.3 设计权衡

- **脏 worktree 永不自动删**：`cleanup_stale` 跳过有未提交更改的——自动清理丢用户工作是不可接受的；脏 worktree 由用户手动处理
- **不自动 merge_back**：隔离 Agent 的产出质量未知，自动合并到主分支风险大——显示合并命令让用户决定（human-in-the-loop）
- **单个失败跳过**：一个损坏的 worktree（如手动删了目录但 git 元数据还在）不能阻断其他清理和应用启动
- **mtime 而非创建时间**：目录 mtime 反映最后活动时间——最近被 Agent 使用过的 worktree 即使创建很久也不清

# 第五十五部分：Skill 安装命令（P55）

## 55.1 为什么需要：手动复制目录太原始

4 个内置 skill 开箱即用，但要加第三方 skill 必须手动找到 `~/.mini-agent/skills/` 然后 `cp -r`，还要确保目录结构对——不友好。mewcode 有 `/skill install` 一键安装。

## 55.2 实现：install + uninstall

**`SkillRegistry.install(source, target_dir)`**：
- 本地路径 → `shutil.copytree` 复制整个 skill 目录
- git URL → `git clone --depth 1`（浅克隆省空间）
- 安装后验证：目标必须含 `SKILL.md` 且 `name` 字段可解析——验证失败自动 `shutil.rmtree` 清理（不留垃圾）
- 目标已存在 → 拒绝覆盖 → ValueError

**`SkillRegistry.uninstall(name, target_dir)`**：遍历 target_dir 的子目录，解析每个 `SKILL.md` 找到 `name` 匹配的 → `shutil.rmtree` + 内存注册表移除

## 55.3 设计权衡

- **install 是异步的**（`async def`）：git clone 是外部进程调用，必须 await
- **验证-回滚模式**：先复制/克隆 → 验证 → 失败才删——不做预验证（源路径可能没有 SKILL.md 但 git repo 的子目录有）
- **uninstall 按 name 不按目录名**：skill 名和目录名可能不同（如目录叫 `code_review/` 但 SKILL.md 里 name 是 `code-review`）
- **不支持热重载**：install 后调 `load_all()` 重新扫描全部目录——简单可靠。热重载是 8.2 的范围

# 第五十七部分：远程/浏览器模式（P57）

P57 是大功能（WebSocket 服务器 + 嵌入式浏览器 UI + 11 项增强），实现细节和设计决策记录在以下位置：

- 架构与协议设计：[comparison-mewcode.md §5.2](comparison-mewcode.md)（NDJSON 协议 12 种事件 + 3 种客户端消息、浏览器 UI 功能清单、安全与容错、测试覆盖）
- 已知限制与后续改进：[roadmap.md "已知限制"](roadmap.md)（无 TLS、共享会话；重启丢会话后经 §102 接入 SessionStore 已修复）
- P82 断连排队增强：[roadmap.md 第八节 扩展点 #8](roadmap.md)（PermissionDecision.PENDING 跨连接持久化）

# 第五十八部分：Mailbox 跨 Agent 通信（P58）

## 58.1 为什么需要：SubAgent 是"派出去等结果"模式

spawn_agents 阻塞等待所有子代理返回最终报告（各截断 500 字符）——代理之间零交流。两个并行代理重复发现同一事实、或一方基于错误假设跑满全程，只能事后返工。comparison-mewcode.md 6.2 的差距项。

## 58.2 实现：文件收件箱 + 两个工具 + 循环注入

- `core/mailbox.py`：每 Agent 一个 JSON 收件箱文件。所有 Agent 跑在同一事件循环，send/drain 内部无 await，单文件读改写天然原子——**不需要文件锁**
- `send_message` 工具：发给 'main' 或同伴 id；收件人未注册报错并列出已知 Agent（LLM 可据此降级）
- `wait_message` 工具：0.5s 轮询阻塞等消息（上限 600s）——接收方的等待原语，超时返回信息而非错误
- `AgentLoop._deliver_mail()`：每轮 THINK 前 drain 收件箱，消息注入为 USER 消息。后台 agent 完成时另有自动投递路径（`terminal.interrupt_input()` → `_handle_background_delivery()`），不依赖用户输入
- `Mailbox.has_pending(agent_id)`：无锁只读查询是否有未读消息，用于自动投递前判断是否需要发合成消息，避免空 drain
- 生命周期：SubAgent 构造时注册收件箱、结束时注销；register 总是重置文件防跨会话残留

## 58.3 三轮迭代

单测全绿后，真实 LLM 运行连续暴露三个设计缺口，全部当场修复：

1. **兄弟代理互不知 id**——任务文本由主 LLM 事先写好，id 构造时才生成。修复：spawn_parallel 预生成全部 id，MAILBOX_NOTICE 列出同伴 id + 任务摘要（只列 id 仍不够：LLM 分不清哪个同伴是收件方，会幻觉 'agent-2'）
2. **主 LLM 分两次 spawn_agents 导致串行**——工具描述未说明阻塞语义。修复：描述明示"需要通信的任务必须一次调用传入"
3. **接收方无等待原语**——靠 bash sleep 磨蹭会提前结束、收件箱注销，慢速发送方投递报 Unknown recipient。修复：wait_message 工具 + notice 禁止 sleep 等待

验证矩阵：4 类拓扑真实 LLM 全通过（1→1 单向 / 2→1 汇聚多轮 wait / 1→2 判别寻址 / 1↔1 双向 5 轮乒乓，零死锁零丢消息）。

## 58.4 设计权衡

- **文件而非内存队列**：符合 comparison 原方案；跨进程可扩展（未来多后端 spawn）；调试时可直接 cat 收件箱
- **结束即注销、消息丢弃**：发给已结束代理的消息宁可报错也不静默入黑洞——错误信息引导 LLM 转发给 'main'
- **read-only 类型也能收发**：send/wait_message 不算写文件，explore/verify 代理可参与协作
- **主代理在 spawn_agents 期间阻塞**：发给 'main' 的消息在 wait_all 返回后的下一轮才被消费——真正实时的是 Worker↔Worker 这条边，是当前架构的已知边界

## 58.5 已拉平四项

P58 学的骨架（每 Agent 一个 JSON 收件箱 + turn 开始前消费注入对话），按 mini 的单进程架构做了减法（去锁）和加法（wait_message / 报错列已知 Agent / register 重置）。逐项对照 `mewcode/teams/` 曾记录四项差距，P58.4 全部实现：

1. **广播** ✅——`Mailbox.broadcast()` + send_message `to='*'`，自动排除发送者，返回收件人列表
2. **结构化消息协议** ✅——通用 `type=text/request/response` + request_id 配对（request 自动分配并回传）+ approve 表态，投递前缀区分 [Request]/[Response]。适配说明：mewcode 的 shutdown/plan_approval 类型服务**常驻队友**的生命周期管理，mini 的 SubAgent 是一次性任务，故用通用请求-应答而非照搬团队类型
3. **名字寻址** ✅——`register(id, name)` 别名注册 + `resolve()` id/名字双解析，spawn_agents 新增 `names` 参数（唯一性/保留字校验），notice 显示 'explorer' (id xxx, task: ...)
4. **审计痕迹** ✅——drain 标记已读并留盘（会话内可 cat 排查），unregister 保留文件，新会话 SubAgentManager 初始化 `reset_all()` 统一清理。与 mewcode 差异：审计是**会话级**的，mewcode 留存至手动 cleanup

**架构边界（P58.4 记录，6.4 实现时解除）**：当时 mini 的无锁只在单 asyncio 进程内成立。6.4 落地多后端 spawn 时按此预告补齐——见 58.6。

完整对照表见 comparison-mewcode.md 6.2 节。

## 58.6 多后端 spawn（6.4）：Mailbox 跨进程改造 + 窗格 worker

**为什么**：in-process SubAgent 运行期不可见（只有进度面板）；mewcode 能把队友放进 tmux/iTerm2 窗格实时观看。做窗格意味着 Agent 跨进程，58.5 预告的锁债必须先还。

**前置——Mailbox 跨进程**（`core/mailbox.py` 重写）：
1. `_with_lock(path, fn)`：O_EXCL 创建 `<file>.lock`（原子原语）+ 指数退避带随机抖动（5ms 起、80ms 封顶，避免多进程同刻醒来对撞）+ 10s 陈旧锁接管（崩溃者遗留）+ 5s 超时抛 TimeoutError——消息没送出去必须让调用方知道
2. 原子写：temp 文件 + `os.replace`，纯读免锁永不见半截文件
3. **磁盘注册表** `_registry.json`（id → 别名）替换内存 set/dict——worker 进程能解析父进程注册的同伴。这一步 mewcode 也没做（其注册表是进程内单例），是 mini 的必要发明
4. 唤醒适配：mewcode send-keys 推送服务常驻队友；mini worker 是一次性任务，wait_message 0.5s 轮询天然跨进程收信——无需推送
5. 单进程代价：每次 send/drain 多两个 syscall（锁建删）+ 注册表小文件读——实测 33 个既有测试从 3.1s 到 6.4s，可接受

**worker 协议**（`core/worker.py`）：WorkerSpec JSON（任务/身份/mailbox 目录/结果路径/hold 秒数）→ `mini-agent --worker <spec>` 无头运行（stdout 流式打窗格）→ 结果原子写 JSON → 父进程轮询。API key 走环境变量继承不落盘

**窗格后端**（`core/spawn_backends.py`）：探测：会话内（TMUX/WT_SESSION）分屏；Windows 装了 wt 但在其他终端（cmd/IDE）降级 `wt -w mini-agents new-tab` 进共享窗口标签页，任意终端可用；tmux `split-window -d` / **Windows Terminal `wt -w 0 split-pane`**——mewcode 在 win32 一律放弃窗格，wt 后端是 mini 的反超点；`_PaneWorkerProxy` 顶替 SubAgent 进活跃表，wait/cancel/list 同构

**顺带修复**：`wait()` 对已 cancel 的 agent 原会抛 CancelledError 炸等待方——补分支返回 error="Cancelled" 的结果（失败即数据原则）

**真实验证**：真 LLM worker 子进程 E2E——父进程注册表实时看到 worker 注册、跨进程 send_message 送达 main、注销、结果收集，全链 PASS；4 进程 × 20 条并发写同一收件箱零丢失

**诚实边界**：iTerm2 未做（无 macOS 环境，不写无法验证的代码）；pane cancel 尽力而为不强杀进程；worker 无权限弹窗（与 in-process SubAgent 一致）

## 58.7 实测迭代

1. **协议隔离（最深）**：worker 的 LLM 在探索项目时读到自己的 spec 文件（曾放在项目 `.mini-agent/workers/`，含 result_path），"好心"提前用 write_file 自己写了一份结果——父进程 0.5s 轮询立刻捡走早产桩（Tokens: 0），真结果 15 秒后写入但已无人收。**教训：父子协调文件绝不能放在 agent 可自由读写的目录里**。修复：协议文件迁 `~/.mini-agent/workers/` + 收集器 schema 7 字段 + agent_id 双校验。讽刺的是另一个并行 worker 的分析报告正确预言了此缺陷（"result 文件缺 schema 校验"）
2. **崩溃可见性**：worker 崩在写结果之前 → 父进程只能干等超时，原因随窗格关闭消失。修复：顶层护栏任何异常都写失败结果 + traceback + 窗格停留。同类教训：cli 的 `finally: sys.exit(0)` 会吞掉一切崩溃 traceback（一个 AgentPhase.ACTING 枚举笔误曾借此无声杀死整个应用）
3. **持续限流 ≠ 瞬时抖动**：并行 worker 共用一个 API key，429 是持续配额窗口（几十秒），首版 3 次约 7 秒重试扛不住 → 5 次指数退避约 31 秒；且只在 chunk 产出前重试（流中途重试会产生重复输出）
4. **超时语义**：/spawn wait 300s 超时会取消收集任务并移出活跃表——大任务（实测 5-15 分钟、0.7-1.8M tokens）完成的报告成孤儿。对齐收集器 900s
5. **交付物不可截断**：结果格式化的 `output[:200]` 对小任务合理，对整篇分析报告就是自毁交付
6. **渲染的显式选择**：全量 Markdown 化让 /status /cost 的空格对齐版式被折叠搅碎——修复为哨兵前缀显式 opt-in（MARKDOWN_RESULT），默认纯文本永远安全

## 59. 会话压缩边界（P59）

### 59.1 核心设计：边界 = 摘要 + 已读文件 + 时间戳

压缩后在 `Conversation.compact_boundary` 记录一个 dict：

```python
{
    "summary": "[Compressed conversation history]\n...",
    "timestamp": "<ISO8601 压缩时刻>",
    "read_files": ["src/app.py", "README.md"]
}
```

为什么不只用 `compressed=True` 标记？因为 `compressed` 有两种含义：① `DropToolResults` 截断的工具输出（TOOL 角色）② `SummarizeOldest` 生成的摘要（SYSTEM 角色）。反序列化时需要区分"哪些是摘要、哪些是截断的工具结果"——边界是显式标记，消除歧义。

### 59.2 为什么记录 read_files

`ContextManager._read_files` 在会话加载时不会恢复（`_adopt_session` 只调 `update_total`）。丢失后果：LLM 不知道自己读过什么文件 → 重读 → 触发压缩 → 再丢失 → 再重读——这是 tech-notes §36 根治的压缩-重读膨胀循环的另一个入口。边界里带 `read_files`，`adopt_boundary()` 恢复它，堵住这个入口。

### 59.3 反序列化跳过逻辑

有边界时，加载跳过 `compressed=True and role="system"` 的消息（摘要已被边界覆盖），从边界 summary 重建单条摘要。非 SYSTEM 的 compressed 消息（DropToolResults 的 TOOL 消息）正常加载——它们虽被截断但仍是工具调用历史的一部分。

### 59.4 实测暴露：纯 SlidingWindow 路径

消息数 ≤ `MIN_KEEP_MESSAGES`(5) 时 SummarizeOldest 跳过（P65 前为固定 `KEEP_RECENT=6`），只有 SlidingWindow 执行——SlidingWindow 不创建摘要消息，边界录不到。

修复：`check_and_compress` 在 `_inject_read_files`（它会插入一条 compressed SYSTEM 消息）之后兜底检查，若 `compact_boundary` 仍为 None 则从这条消息创建边界。两层保底：Compressor 内部录 + ContextManager 外部兜底。

### 59.5 与 mewcode 的架构差异

mewcode 用 JSONL 追加式存储，边界是一条自包含的 `type=compact_boundary` 记录（内含 summary + keep 消息序列化），恢复时"找最后一个边界，丢弃之前全部"。mini 用单 JSON 覆写式存储，每次 save 已是当前完整状态，边界是 conversation 段的一个字段。两种方式在功能上等价——区别只在存储格式层。

mewcode 的 `build_recovery_attachment()` 把最近 5 个文件的实际内容烤进摘要（每个 5000 tokens），恢复后 LLM 不仅知道"读过什么"还记得"读到了什么"。mini 只记路径——省 token 但恢复后 LLM 对内容记忆更弱。这是有意的取舍：路径足以阻止重读循环，内容恢复的收益是"少一轮工具调用"，代价是摘要膨胀 25000 tokens。

## 60. 压缩工具对对齐（P60）

### 60.1 问题：固定切分切断工具对

P65 之前 `SummarizeOldest.KEEP_RECENT=6` 固定从尾部数 6 条切分（已改为 token 驱动的 `_compute_keep_split`）。若切分点恰好落在 TOOL 消息上，其对应的 tool_use（assistant 的 tool_calls 消息）被摘要吞掉，kept 开头是孤儿 tool result——严格的 API（OpenAI 官方、Anthropic）会直接 400 拒绝。

### 60.2 修复：边界回退对齐

`_align_split_to_tool_pair(msgs, split)`——当 `msgs[split].role == TOOL` 时向前回退，直到落在非 TOOL 消息（即工具对头部的 assistant 消息）上。工具对整体进入 kept，摘要区永不切断配对。回退到 0 说明切分点之前全是一个工具对，无可摘要内容，压缩空操作。SummarizeOldest 和 LLMSummarizeOldest 共用。

SlidingWindow 方向相反：按 token 预算从尾部选取，向前扩会超预算，所以对开头的孤儿 TOOL 消息直接丢弃（最后手段本来就是有损的）。任务锚点（保留最近 USER 消息）逻辑在孤儿丢弃之后执行，不受影响。

### 60.3 真实 API 验证的诚实发现

用 DeepSeek 真实端点验证：对齐后的压缩产物发送成功；但**未对齐的孤儿 tool result 消息 DeepSeek 也接受了**（未报 400）——该端点对孤儿宽容。修复价值在于严格端点（OpenAI 官方 / Anthropic 的 tool_use/tool_result 强校验），与 mewcode 的 `_align_keep_start_to_tool_pair()` 对齐。

## 61. 记忆导出/导入（P61）

### 61.1 分层：JSON 内部存储 + .md 互操作层

内部存储保持单 `memory.json`（程序读写方便，原子覆写），`.md` 只是互操作/浏览层：`/memory export` 生成 mewcode 风格的独立文件（YAML 前置元数据 + MEMORY.md 索引），`/memory import <dir>` 反向解析。逻辑放在独立的 `memory/interop.py`（纯函数、无 I/O 依赖注入），命令层只做去重与路由。

### 61.2 关键设计：source ≠ scope

实测暴露：`MemoryEntry.source`（"user"/"extracted"）记录**谁创建的**，不是**存在哪里**——`/memory add` 写进项目库的条目 source 也是 "user"。第一版按 source 路由导入，跨机导入时项目记忆全部错进用户库。修复：导出时把存储作用域显式写成 `scope` 前置元数据（project/user），导入按 scope 还原；无 scope 的外来文件（如 mewcode 原生格式）默认进项目库（在项目里导入即是为了本项目）。

### 61.3 容错解析而非严格 YAML

不引 YAML 依赖，手写 ~20 行前置元数据解析：`---` 包围的 `key: value` 行；嵌套缩进行（mewcode 的 metadata）跳过；未闭合 `---` 整文件视为正文；tags 先试 JSON 数组再回退逗号分隔；空正文取 `description`（mewcode 文件的要点常在 description）。原则：导入面对的是"别人的文件"，宁可宽容导入也不报错拒绝——错误只在目录不存在这类硬失败时返回。

## 62. 压缩熔断器（P62）

### 62.1 问题：压缩无效时的死循环

`check_and_compress()` 在 `usage_ratio >= 0.75` 时触发压缩。但压缩不一定降低 token——两种实际场景：

1. **已读文件列表过长**：agent 读了上百个文件后，`_inject_read_files()` 注入的清单本身几百 token，压缩减少的量被注入量抵消甚至反超（实测 150 文件时 2040 → 3183 tokens，token 不降反增）
2. **对话已压到极限**：经几轮压缩后只剩 system prompt + 摘要 + 最近几条消息，三级级联（DropToolResults → LLMSummarizeOldest → SlidingWindow）均无可操作空间

没有熔断器时，每轮工具调用后都会白跑一次完整的三级压缩链。

### 62.2 方案：计数器 + 会话级熔断

`ContextManager` 新增两个字段：

- `_compress_failures: int` —— 连续无效（压缩后 token ≥ 压缩前）计数
- `_max_compress_failures: int` —— 阈值，来自 `MemoryConfig.compress_max_failures`（默认 3，0 禁用）

`check_and_compress()` 在调用 `Compressor.compress()` 前后对比 `_total_tokens`：有效则重置为 0，无效则 +1。计数达到阈值后所有后续调用直接返回 False。

**不做会话内恢复**——计数器只在压缩有效时重置，不随时间自动恢复。理由：硬阈值（P65）在紧急情况绕过熔断器执行压缩，`ensure_fits()` 作为最终兜底不受熔断器影响。新会话 = 新 `ContextManager` = 计数器从零开始。

### 62.3 真实 LLM 验证

`experiments/verify_circuit_breaker.py` 五阶段验证（DeepSeek V4 Flash）：

1. **正常压缩**：3 轮 LLM 对话触发压缩，均有效（3371→53、3130→51、2523→50），failures=0
2. **自然熔断**：注册 150 个已读文件，`_inject_read_files` 注入抵消压缩收益，连续 3 次无效后熔断触发（attempt 12-14：2000→2000→2000）
3. **ensure_fits 兜底**：熔断后 `check_and_compress` 返回 False，但 `ensure_fits` 仍正常截断（50 条→11 条）
4. **禁用对照**：`compress_max_failures=0` 时无保护，持续白跑压缩
5. **新会话恢复**：新 `ContextManager` 计数器归零，压缩正常工作

## 63. 压缩恢复附件含文件内容（P63 / comparison 9.2a）

### 63.1 问题：压缩后 agent 丢失文件内容和任务上下文

原有 `_inject_read_files` 只记录已读文件路径，压缩后 LLM 虽然知道不该重读，但对文件内容没有记忆，遇到需要引用文件内容的问题时仍会调 `read_file`。更严重的是，如果压缩在一轮中间触发（工具调用后的 `check_and_compress`），token 驱动保留窗口保留的消息可能全是工具返回，用户原始请求被摘要吞掉，agent 完全丢失任务上下文。

### 63.2 三层修复

**第一层：文件内容烤入**。`record_file_read(path, content)` 在 `read_file` 工具成功后立即将内容截断到 5000 tokens 存入 `_read_files: dict[str, str | None]`。`_inject_read_files()` 在摘要消息中追加最近 5 个文件的截断内容（`--- path ---` 格式）。

**第二层：用户请求保留**。`check_and_compress()` 在调用 compressor 之前，从 `conversation.messages` 逆序找到最近的 USER 消息，截取前 2000 字符存入 `_last_user_request`。`_inject_read_files()` 在摘要消息最前面插入 `[User's most recent request before compression:]` 段。

**第三层：边界持久化**。`compact_boundary` 新增 `file_contents: dict[str, str]` 和 `last_user_request: str`，`adopt_boundary()` 恢复时读取这两个字段，向后兼容旧格式（字段缺失时默认空）。

### 63.3 关键设计决策

1. **内容在 spill 之前捕获**：`record_file_read` 在 `maybe_spill` 之前执行。如果反过来（先 spill 再记录），超过 50000 字符的文件溢写后 `result.output` 变成占位符，存入的是占位符而非真实内容。
2. **截断在记录时发生**：不在压缩时截断，而在 `record_file_read` 调用时立即截断。好处是内存使用可控（每个文件最多 5000 tokens），且后续压缩、序列化都不需要再处理长文本。
3. **二分搜索截断**：`truncate_to_tokens` 用二分搜索找最大可保留前缀（O(log n) 次 `count_tokens` 调用），比线性扫描高效。
4. **模块常量**：`_MAX_RECOVERY_FILES=5`、`_RECOVERY_TOKENS_PER_FILE=5000`、`_MAX_TASK_CHARS=2000`，集中管理恢复预算。

### 63.4 真实验证

`context_window=14000` 配置下读 2 个文件（token_counter.py + config.py），触发 grep 工具调用后压缩触发。压缩后 agent 能：(1) 知道用户在问什么（不说"我不知道你的请求"）；(2) 不重读文件直接回答 `truncate_to_tokens` 的实现细节；(3) 正确引用代码行号和逻辑。

## 64. 聚合工具结果预算（P64.1）

**问题**：`maybe_spill()` 只看单条 50K 阈值。10 个并行工具各返回 49K 字符，单条都不触发，一轮塞入 ~500K 字符撑爆上下文。

**实现**：

1. **聚合预算** `spill_batch(results, already_used, exempt_ids)`：本轮累计工具结果字符超 `aggregate_spill_chars`（默认 200K，0 禁用）时，按 output 长度降序强制溢写（`maybe_spill(force=True)`），直到回到预算内。降序意味着回到预算内动的条数最少。每条结果独立成消息，改为 `turn_result_chars` 在 `run()` 内跨迭代累计。
2. **配套 1a 读回豁免** `is_spill_readback`：read_file 的 file_path 落在溢写目录内时豁免（单条层在 `_run_tool_pipeline` 检查，聚合层经 exempt_ids 传入）。没有它：LLM 读回溢写文件 → 结果又被溢写 → 死循环。
3. **配套 1b 预览 2000**：500 字符太短，LLM 信息不足会放弃重读改用 bash 绕过。预览仍以 `min(PREVIEW_CHARS, threshold)` 封顶，兼容测试小阈值。
4. **配套 1c 小结果豁免**：不长于预览的结果溢写换不回空间（预览+提示反而更大），force 路径也豁免。

**细节**：溢写占位文案现在带溢写文件路径（原来只说"re-run with offset/limit"），LLM 可直接对溢写文件 offset/limit 精读，读回受 1a 保护；spill_batch 写盘 OSError 时保留原文，不炸 OBSERVE 阶段；错误结果和已溢写结果（metadata 有 spilled_path）跳过。

**真实 LLM 验证**（DeepSeek，threshold=50K / aggregate=8K）：并行读 3 个 ~6K 文件——单条不触发、聚合触发，9 条结果溢写 6 条，对话累计 15.5K 字符有界；LLM 看到 2000 字符预览后自主用 offset/limit 分段精读并正确作答（预览给足信息量的效果）；读回溢写文件未被重溢写。

**交互式 E2E 验证与配套修复**：会话（aggregate=15000 极端参数）+ 会话 JSON 审计 19 条工具结果，6 验证点中 5 项全达成（溢写发生/预览留存/精读收敛零绕道/读回不重溢写/小结果与最大优先）。暴露并当场修复两个可用性缺口：① 溢写目录在项目外，读回每次弹权限框且 'a' 按精确路径记忆对新文件无效——PathGuard 对 `~/.mini-agent/cache/results` read 自动放行（write 仍询问）；② confirm() 复用主输入 PromptSession，prompt_toolkit 把传入 message 固化为 session 默认值。

**诚实边界**：豁免读回不被溢写但计入本轮累计预算。aggregate 设得小于典型单文件大小时（15K < 20K），一次读回即耗尽预算，后续中等结果链式"溢写→读回"，对话同时保留预览与全文——预算未真正压住上下文，只多花迭代。默认 200K 下单文件读回（≤50K，更大的被单条阈值先截）最多占 1/8 预算，无链式反应。机制层面不可消除：模型执意读全文时内容终归进对话，预算的职责是让它显式地进，不是拦住它。

## 64a. LLM 摘要压缩接入（P64.2）

**背景**：P11 实现了 `LLMSummarizeOldest` 但未接入默认链（实验阶段）。P64.2 根据实验结论和实际使用体验，将 LLM 语义摘要设为默认。

**实现**：
- `MemoryConfig.llm_summarize: bool = True`：默认启用，`False` 回退提取式
- `app.py` 装配：`llm_summarize=True` 时用 `LLMSummarizeOldest(self._llm)` 替换 Compressor 默认的 `SummarizeOldest`；失败自动回退（LLMSummarizeOldest 内置回退机制）
- `config.toml.example` `[memory]` 段补 `llm_summarize` 注释

## 64b. 压缩检查前移 + 摘要前缀指令（P64.3）

**问题 1**：`check_and_compress()` 原来只在 OBSERVE 阶段（工具结果追加后）调用。纯对话场景（用户多轮提问无工具调用）永远不触发压缩，token 持续增长直到 `ensure_fits` 粗暴截断。

**修复**：`_think()` 在 `ensure_fits` 之前增加 `check_and_compress` 调用——每次 LLM 调用前都检查，纯对话也能触发三级级联。

**问题 2**：压缩后 LLM 看到 `[Compressed conversation history]` 标记，误以为有更完整的历史存在磁盘上，去 `.mini-agent/sessions/` 翻会话文件浪费迭代。

**修复**：摘要前缀加明确指令 "this is the authoritative record... Do NOT search session files"。

## 65. 压缩双阈值（P65）

### 65.1 问题：熔断器过度保护——紧急压缩也被阻断

P62 引入的熔断器解决了"压缩无效时白跑"的问题，但带来新问题：熔断器开启后**所有**压缩都被阻断，包括上下文即将溢出的紧急情况。此时只剩 `ensure_fits()` 兜底——它直接调 SlidingWindow 粗暴截断到 85%，跳过 DropToolResults 和 SummarizeOldest 两级，丢失大量上下文信息。

真实场景：P64.4 验证中 context_window=10000 时观察到——熔断器 3 次无效后开启，后续对话 token 持续增长，check_and_compress 全部返回 False，最终由 ensure_fits 暴力截断，LLM 丢失任务上下文后反复重读文件。

### 65.2 方案：软硬双阈值

参考 mewcode 的 `auto_compact` 双阈值设计（200K 窗口下 167K 触发软压缩、177K 触发硬压缩），引入两个独立阈值：

- **软阈值** `compression_threshold`（默认 0.75）：正常压缩触发点，受熔断器控制——连续 N 次无效后熔断器阻断，避免白跑
- **硬阈值** `hard_compression_threshold`（默认 0.90）：紧急压缩触发点，**绕过熔断器**——即使熔断器开启，只要 `usage_ratio >= 0.90` 仍执行完整三级级联压缩

默认 128K 窗口下：96K 触发软压缩，115K 触发硬压缩。两个阈值均可通过 `[memory]` 配置调整。

### 65.3 实现

改动集中在 `check_and_compress()` 的熔断器检查处，一行条件：

```python
# 原：达到熔断阈值就跳过
if self._compress_failures >= self._max_compress_failures > 0:
    return False

# 改：达到熔断阈值 且 未达硬阈值 才跳过
if (self._compress_failures >= self._max_compress_failures > 0
    and not self.needs_hard_compression):
    return False
```

硬阈值绕过后走的仍是同一条压缩路径（Compressor.compress → 三级级联），不需要新的压缩逻辑。区别仅在入口处是否放行。

附带改进：
- `/status` Context 行显示 `soft=75% hard=90% breaker=0/3`，运行时可观测
- 硬阈值触发时 WARNING 日志 `Hard compression threshold reached (X%), bypassing circuit breaker`，与熔断器开启日志配对可区分软/硬阈值行为

### 65.4 防护链完整图景（更新后）

```
usage_ratio >= 0.75（软阈值）
  → 熔断器未开启 → 三级级联压缩（正常路径）
  → 熔断器已开启 → 跳过（避免白跑）
      → usage_ratio >= 0.90（硬阈值）→ 绕过熔断器，三级级联压缩（紧急路径）
      → usage_ratio < 0.90 → 继续跳过
          → _think() 前 ensure_fits(真实窗口) → SlidingWindow 强制截断（最终兜底）
```

三层防护各管一段：软阈值管常规、硬阈值管紧急、ensure_fits 管溢出。熔断器只在软-硬之间的"安全区"生效。

### 65.5 真实 LLM 验证

**E2E 脚本**（context_window=6000，soft=0.6，hard=0.85）：
1. AlwaysFailCompressor 触发熔断器（3/3），软阈值被阻断（返回 False）
2. 推高 usage_ratio 到 1.12，硬阈值绕过熔断器（返回 True）
3. 五轮 DeepSeek 对话：熔断器开启后 ratio 继续增长，硬阈值触发有效压缩（8910→4760），熔断器重置

**终端窗口验证**（context_window=20000，/trace + /status）：
- `/status` 确认 `breaker=3/3`，Context 60%-85% 之间波动
- trace 中反复出现 `Compression circuit breaker open`（软阈值被阻断）
- 消息数骤降（如 35→8）证实硬阈值绕过熔断器执行了压缩

## 66. Token 驱动的保留窗口

### 66.1 问题：固定消息数保留不适应消息大小

`SummarizeOldest.KEEP_RECENT = 6` 固定保留最近 6 条消息。6 条短消息可能只有 1K token（浪费压缩空间），6 条长消息可能有 40K token（保留太多导致压缩无效）。

### 66.2 修复：token 驱动的 `_compute_keep_split`

`_compute_keep_split(msgs)` 从尾部反向扫描累计 token，双条件停止：

1. 累计 ≥ `KEEP_RECENT_TOKENS`(10K) **且** 消息数 ≥ `MIN_KEEP_MESSAGES`(5)
2. 累计 + 下一条 > `KEEP_MAX_TOKENS`(40K)（硬顶，防止保留过多）

`SummarizeOldest` 和 `LLMSummarizeOldest` 共用此函数替代固定 `KEEP_RECENT = 6`，工具对对齐（`_align_split_to_tool_pair`）不变。（P68 起 10K/40K 为绝对上限，实际下限/硬顶随压缩目标缩放，见 §68）

效果：短消息全保留（不浪费），长消息少保留（不超限）。

### 66.3 验证

真实 LLM 三场景验证 + 终端交互验证：
- **长回复场景**（context_window=20000）：5 轮长回复压缩后 kept=5（MIN_KEEP_MESSAGES），旧行为 6 × 几千 token = 过多
- **混合场景**（context_window=8000）：2 个长回复 + 8 个短问答，压缩后 19 条消息全保留（旧 KEEP_RECENT=6 只留 7 条）
- 7 个新单测覆盖所有边界条件

## 67. 摘要 prompt 结构化（P67）

### 67.1 问题：4 条通用指令产出的摘要质量不稳定

`_SUMMARY_PROMPT` 只要求 4 条（目标/步骤/文件/未解决），无输出结构约束——LLM 有时输出三两句概述，丢失文件名、错误修复过程和用户反馈等续作必需的细节。

### 67.2 修复：analysis 草稿 + 9 节结构化输出

- prompt 要求先输出 `<analysis>` 块（按时间线梳理消息，自查完整性），再输出 `<summary>` 块，含 9 节：主请求与意图 / 关键技术概念 / 文件与代码段 / 错误与修复 / 问题解决 / 全部用户消息 / 待做任务 / 当前工作 / 可选下一步
- **mini 适配**（非照搬）：mini 只摘要最旧前缀（近期消息原样保留在 kept 窗口），prompt 开头明确 "Recent messages are kept verbatim elsewhere; this summary replaces only the older history"；mewcode 的 "Do NOT call tools" 警告不需要——mini 的 `_summarize()` 是直连 `llm.stream()` 不带工具
- `_extract_summary()` 只把 `<summary>` 块内容注入对话——analysis 草稿提升质量但注入会浪费上下文；无标签时回退完整输出（模型没按格式，文本仍可用）；只有 `<analysis>` 时（输出中途截断）剥离草稿返回空，触发上游抽取式回退
- 回退分支加 WARNING 日志（异常类型 + 消息）——验证中遇到一次偶发回退但异常被静默吞掉无法诊断，现在回退原因可观测

### 67.3 验证

- 真实 LLM E2E（`experiments/verify_summary_prompt.py`，20 条消息含 bug 修复剧情）：产出完整 9 节摘要，文件名/代码行/用户约束（"不要改 session_store.py"）/下一步全部保留；`<analysis>` 无泄漏、走 LLM 路径非回退，5 项断言全 PASS
- 5 个新单测：提取/无标签回退/截断剥离/注入内容不含草稿/空 summary 块回退

### 67.4 暴露的推理模型截断问题（追加修复）

**现象**：终端窗口验证（context_window=20000，DeepSeek v4 flash）中 `LLM summarization failed (ValueError: empty summary)` 出现 8 次，结构化摘要从未生效，全部回退抽取式——压缩后模型丢失首问和用户约束。67.2 加的回退日志立功，否则该问题不可见。

**根因**（用真实会话 digest 复现确认）：DeepSeek 是混合推理模型，先在 `reasoning_content` 通道烧 ~12K 字符原生思考，正文输出预算（`max_tokens` 默认 4096）所剩无几；P67 prompt 又要求正文写 `<analysis>` 草稿——**双重思考**，9 节 summary 写不完。截断在 `<analysis>` 内 → 提取为空 → 回退；截断在 `<summary>` 内 → 原逻辑判为无闭合标签也走回退。脚本验证没暴露是因为 digest 只有 571 字符，思考量小。

**三处修复**：
1. `SUMMARY_MAX_TOKENS = 8192` —— `_summarize()` 用 kwargs 覆盖默认 4096（两个 Provider 均支持 P44 的 max_tokens 覆盖）
2. prompt 追加 "Keep the analysis BRIEF -- a compact bullet list, not prose"——推理模型已在 reasoning 通道思考过，正文草稿不必重复展开
3. `_extract_summary()` 抢救未闭合的 `<summary>`——有开标签就取标签后内容，残缺摘要仍远好于抽取式

**复现验证**：修复后用同一份真实会话 digest 重跑——5708 字符完整 9 节摘要，无标签泄漏。终端会话中 P68 的表现符合预期：Context 全程 64-76% 无失控，硬阈值仅 99% 触发一次（修复前 128%-191% 每轮触发）。

### 67.5 二次压缩摘要退化（追加修复）

**第三轮终端验证结果**（context_window=20000）：67.4 修复生效——回退日志 0 次（第二轮 8 次）、硬阈值 0 次、熔断器全程未开启（中途 2/3 后被有效压缩重置）；压缩后模型准确答出主请求、"不读测试文件"约束和只存在于对话中的约定，成本 ¥0.13（第二轮 ¥1.46）。

**但边界摘要自述 "the full request is unknown"**：`_extractive_digest` 把每条消息砍到 300 字符——包括上一轮的摘要消息。二次压缩时承载全部细节的旧摘要先被截断再喂 LLM，产出"残缺摘要的摘要"，细节损失复利叠加。会话内问答能通过是因为相关内容还在保留窗口，但边界摘要（会话恢复的依赖）已经空心化。

**修复**：`_extractive_digest` 对 `compressed=True` 的 SYSTEM 摘要消息豁免截断，整条传递（总量仍由 `MAX_HISTORY_CHARS=24K` 封顶）。

**验证**：真实 LLM 两轮压缩穿透测试——第一轮压缩产出摘要后追加 16 条消息触发第二轮压缩，三个埋点（用户约束 session_store / 配置项 SESSION_TTL / 文件名 login.py）经两轮压缩全部存活于最终摘要。1 个新单测（旧摘要整条保留 + 普通消息仍截断）。841 个测试全过。

**第四轮终端验证**（context_window=20000，两次读大文件推两轮压缩）：边界摘要中三个埋点（"不读测试文件"约束 / compressor.py+context.py 文件名 / MAX_TOOL_OUTPUT 约定）全部存活——上一轮全部丢失。残留观察（非本项回归）：`empty summary` 出现 1 次（67.4 修复前 8 次，回退兜底正常，根治靠 todo ⑦ 摘要重试）；breaker 爬到 3/3 是 20K 人为小窗下会话活在 91-103% 边缘的固有现象（todo ⑨ 场景），128K 真实窗口无此问题。

**无污染召回验证**（`experiments/verify_summary_recall.py`，终端验证的补强——排除"答对靠残留历史"和"巧合蒙对"两类质疑）：虚构埋点覆盖五种题型——因果链（决策+原因）/ 中途反转（先 30 后改 45，只抓首次提及会答错）/ 否定约束（"不要用 pandas"）/ 英文标识符（精确字符串）/ 陷阱题（问从未埋过的事实，答"没有"才过，暴露幻觉）。对话含工具调用对；压缩后程序化确认埋点不在保留消息中（22 条压至 1 摘要 + 2 保留）；每题独立 LLM 调用互不提示。真实 LLM 5/5 全过。证明"结构化摘要生成 → 注入 → LLM 从摘要恢复信息"链路本身有效。

## 68. 保留窗口按压缩目标缩放（P68）

### 68.1 问题：绝对常量在小窗口下让摘要级数学失效

P67 终端窗口验证（context_window=10000）暴露：`KEEP_RECENT_TOKENS = 10_000` 是绝对常量，恰好等于整个窗口——Stage 2 承诺"尾部至少保留 10K token"，但压缩目标只有 75% × 10000 = 7500。摘要级**数学上永远达不到目标**，每次都落到 SlidingWindow 硬截断，摘要消息活不到边界里。

实测雪崩链：单次 read_file（16K 字符 ≈ 8K token）+ 系统提示就顶满窗口 → usage_ratio 一路 128%→191%，硬阈值每轮触发但压缩无效 → DropToolResults 把模型正需要的文件内容截成 200 字符 → 重读 → 又被截 → 模型开始写 `_dump_*.py` 脚本绕截断 → 80 轮迭代上限才刹住（再次印证 §35 实验结论"迭代上限是唯一可靠硬熔断"），单轮烧 1M token。

### 68.2 修复：下限/硬顶随 target_tokens 缩放

`_compute_keep_split(msgs, target_tokens)` 增加 target 参数：

- 保留下限 `keep_recent = min(KEEP_RECENT_TOKENS, target_tokens // 2)`
- 保留硬顶 `keep_max = min(KEEP_MAX_TOKENS, target_tokens)`
- 兜底：`keep_count == 0` 时强制保留 1 条——最新消息单条超硬顶时也不能把尾部全摘要掉（丢了进行中的任务）

大窗口行为完全不变（128K 窗口 target=96K：min 取的仍是 10K/40K 绝对值）；小窗口下摘要级恢复可达标——window=10K 时 target=7500 → 下限 3750 / 硬顶 7500。

### 68.3 验证

- 真实 LLM（target=7500 模拟 10K 窗口）：压缩后总量 7008 ≤ 7500 达标，9 节结构化摘要存活（修复前保留下限 10K 就已超标）
- 4 个新单测：小目标缩放 / 单条超顶保底 1 条 / 大目标行为不变 / 小目标端到端在预算内
- 841 个测试全过

## 69. DropToolResults 尊重保留窗口（P69）

### 69.1 问题：Stage 1 截断模型正在使用的工具结果，诱发重读死循环

第五轮终端验证（context_window=20000）实测：模型读 16K 字符文件 → 下一迭代软阈值触发压缩 → `DropToolResults` 把**全部** TOOL 消息（含本轮刚读、正要用的结果）截到 200 字符 → 模型回看上下文以为"工具输出被截断/工具坏了" → 换小块重读 → 新结果又被截 → 单轮 36+ 迭代、563K token 的死循环，只能人工打断。

证据链：模型自己量出"输出上限约 300 字符"== `MAX_TOOL_OUTPUT(200)` + 截断说明行；会话 JSON 显示 20 条工具消息 16 条被截，包括尾部近期结果；第一次"截断"抱怨的时间点恰在 token 越过软阈值之后。回看第二轮验证的 `_dump_*.py` 乱象，深层机制相同——当时只归因于 10K 窗口数学失效（P68），漏了这一层。

### 69.2 修复：Stage 1 与 Stage 2/3 语义对齐——绝不动保留窗口

`DropToolResults.compress()` 先算 `_compute_keep_split(msgs, target_tokens)`，只截断 `msgs[:split]`（可摘要前缀）内的工具输出。保留窗口内的工具结果是模型的工作集，压缩它等于当着模型的面撕它正在读的文件；真正的大结果防护由 `tool_result_cache` 溢写机制（入口端）负责。

### 69.3 验证

- 3 个单测：前缀截断 / 短输出跳过 / **保留窗口内不动**（新旧工具结果同场对照）
- 842 个测试全过，ruff lint + format clean
- 终端第六轮验证待跑（同第五轮流程，预期不再出现"输出被截断"重读螺旋）

## 70. 第六轮终端验证：P69 达标 + 两个新缺陷修复（P70）

### 70.1 P69 验收通过

同流程重跑：读 context.py 的轮次从 36 迭代（P69 修复前）降到 **4 迭代**，"输出被截断"重读螺旋彻底消失。另一亮点：五问召回失败时模型**诚实回答"无相关记忆"而非编造**（反幻觉行为正确）。

### 70.2 缺陷 A：恢复附件预算不随窗口缩放

会话 JSON 取证：摘要消息膨胀到 54,691 字符——LLM 摘要只占 7.8K，其余 ~47K 是 `_inject_read_files` 烤入的 5 文件 × 5000 token 附件。25K token 的附件超过整个 20K 测试窗口 → Context 钉死 112-115%、压缩连续无效（breaker 空转）。与 P68 同类的"绝对常量 vs 目标"缺陷。

**修复**：附件总预算 `min(5×5000, max_tokens // 4)`，按文件数均分（单文件下限 200 token）。128K 窗口行为不变（25K < 32K），20K 窗口附件收敛到 5K token。

### 70.3 缺陷 B：嵌套摘要二次总结丢约定

埋点确实进过第一次压缩的抽取式摘要（短消息 <300 字符整条保留，P67.5 也把旧摘要整块传给了二次摘要）——但第二次 LLM 摘要把嵌套摘要里的技术请求转述了、约定类内容丢了（边界摘要自述 "paraphrased from compressed history" 只列读文件请求）。prompt 没告诉模型嵌套旧摘要的地位。

**修复**：`_SUMMARY_PROMPT` 增加明确指令——"[Compressed conversation history" 开头的块是权威历史而非噪音，其中的约定/决策/约束/用户指令必须前传，丢弃即永久损失。

**验证**：真实 LLM 复现第六轮丢失场景（埋点在嵌套抽取式摘要内 + 12 条大段技术讨论）——修复后 5 个约定（WebSocket 因果/最终值 7/手机号禁令/BUILD_TAG_Kite_88）全部前传到二次摘要。

### 70.4 测试

- 2 个新单测：恢复附件随窗口缩放（8K vs 128K 对照）/ （B 由真实 LLM 场景复现验证）
- 843 个测试全过，ruff lint + format clean

## 71. SlidingWindow 摘要锚点（P71）——第七轮终端验证定案

### 71.1 排查过程：三步逼近真凶

第七轮终端验证（P70 修复后）：压缩正常、无回退日志、Context 正常回落——但五个埋点依然全丢，模型诚实答"无记录"。逐步定位：

1. **会话 JSON**：摘要的 All User Messages 节写着 "Earlier (exact wording not preserved)"——第一次压缩就丢了，排除嵌套问题
2. **单步复现失败**：真实难度（埋点 + 高密度技术讨论竞争）的离线 digest 摘要测试通过——说明 LLM 摘要本身没问题
3. **全管道插桩复现**（ContextManager + check_and_compress + 真实文件内容）：`LLM summary out: plants=[全部四个]` → `SlidingWindow RUNNING: msgs=5 → 4`——**LLM 摘要完美保住了埋点，Stage 3 恰好删掉的那一条就是摘要**

### 71.2 根因：摘要在头部，SlidingWindow 从尾部保留

Stage 2 产出的摘要消息位于消息列表头部；Stage 2 之后总量仍超目标时，Stage 3 按尾部预算保留——第一个牺牲品必然是摘要。上一级刚花一次 LLM 调用保住的全部历史被当场销毁，随后 `_inject_read_files` 找不到摘要消息，插入纯附件消息顶替（这就是第六/七轮边界"空心化"的完整解释链）。SlidingWindow 已有任务锚点（绝不丢最新 USER 消息）却没有摘要锚点——防护不对称。

### 71.3 修复：摘要锚点

`SlidingWindow.compress()` 尾部保留后检查：kept 中无 `compressed=True` 的 SYSTEM 消息时，把原列表中的摘要消息插回最前（与任务锚点同等待遇，允许轻微超预算——ensure_fits 的 85% 目标留有余量）。

### 71.4 验证

- 全管道真实 LLM 复现：修复后两轮压缩（S1/S2）四个埋点全部存活
- 1 个新单测：紧预算下摘要锚点存活
- 846 个测试全过，ruff lint + format clean
- 终端第八轮验证待跑（同流程，预期五问全中）

## 72. 恢复附件污染 digest + 摘要重试（P72）——第八轮终端验证定案

### 72.1 第八轮现象与定位

P71（摘要锚点）后第八轮终端验证：五问依然全丢。JSON 取证 + trace 时间线还原完整链条：

1. turn 7 压缩时 LLM 摘要偶发失败（三轮会话各出现一次，已成主要回退来源）→ 抽取式 S1 **保住了埋点**
2. `_inject_read_files` 把 ~17K 字符的文件内容附件烤到 S1 消息体上
3. 下一次压缩时 P67.5 把 S1 **整条**（含附件）传入 digest——500 字符的埋点约定淹没在 17K 源码转储里
4. LLM 摘要把输入总结为"用户在研究 memory 子系统"，埋点丢弃

此前离线嵌套测试一直通过的原因：测试构造的 S1 没有烤入附件——缺了真实管道的关键一环。

### 72.2 修复

1. **digest 剥离恢复附件**：`_extractive_digest` 传递旧摘要前按 `RECOVERY_MARKERS`（与 `_inject_read_files` 共享常量防不同步）切掉附件部分。附件每次压缩后都会重新注入，剥离零损失；纯附件消息剥后为空则整条跳过
2. **摘要重试（todo ⑦ 重试部分）**：`SUMMARY_RETRIES = 2`，偶发空摘要重试一次通常恢复，穷尽后才落抽取式；重试/穷尽各有 WARNING 日志

### 72.3 验证

- 复刻第八轮最恶劣路径（强制首次压缩 LLM 失败×2 → 抽取式 S1 + 附件烤入 → 二次压缩）：埋点在 S1 和二次压缩后**全部存活**
- 全管道双 LLM 压缩路径（§71.4）继续全存活
- 3 个新单测：digest 剥附件 / 偶发失败重试恢复 / 熔断重置测试适配摘要锚点语义
- 846 个测试全过，ruff lint + format clean
- **终端第九轮验证最终通过**：五问全中（反转题主动说明"3 改 7"，陷阱题明确"没定过"零幻觉）；JSON 客观判定——4 个埋点全部不在保留历史（无污染）且全部存在于 LLM 摘要；全程无回退日志、breaker 0/3、成本 ¥0.13

### 72.4 压缩链路缺陷全景

| # | 缺陷 | 修复 |
|---|---|---|
| P68 | 保留窗口绝对常量小窗口失效 | 随 target 缩放 |
| P69 | Stage 1 截断工作集诱发重读死循环 | 尊重保留窗口 |
| P70 | 恢复附件不随窗口缩放 + 嵌套摘要 prompt 缺指令 | 预算缩放 + prompt 强化 |
| P71 | SlidingWindow 删摘要（有任务锚点无摘要锚点） | 摘要锚点 |
| P72 | 附件污染 digest + 摘要无重试 | 剥离附件 + 重试 2 次 |

每个都由真实终端验证暴露、全管道插桩定位、真实 LLM 复现修复验证——离线单步测试全程通过恰恰说明单元级正确性不等于管道级正确性。

## 73. 摘要 prompt 超长收缩重试（P73）

### 73.1 设计

mewcode 语义（"prompt 太长时丢弃最旧 20% 后重试"）适配 mini 的 digest 架构：

1. **识别**：`_is_prompt_too_long()`——httpx 400/413 一律算（流式模式下错误响应体常不可读，而摘要请求格式固定，400 几乎必是长度问题；误判最多多花几次有界重试后落抽取式），错误消息关键词兜底识别包装过的异常
2. **收缩**：丢弃最旧 20% 可摘要消息（mewcode 语义，最旧价值最低）**并**把字符 cap 缩 20%——后者保证 digest 仍超 cap 时请求也确实变小（只丢消息时切片长度不变，窗口只是前移）
3. **旧摘要保护**：`_shrink_oldest()` 绝不丢头部的旧压缩摘要——它是更早全部历史的唯一记录，丢了就重演 300 字符截断的"完整请求未知"失败
4. **独立预算**：`MAX_SHRINKS=3` 与 `SUMMARY_RETRIES=2` 互不消耗——收缩是确定性修正，偶发重试是赌运气，混用预算会让一次超长吃掉全部容错
5. **穷尽即回退**：收缩预算用完后再遇超长错误直接落抽取式，不用相同的超长请求烧偶发预算

被丢弃的消息和其余消息一样被摘要替换，只是不再体现在摘要文本里——空间已经不够，mewcode 接受同样的损失。

### 73.2 真实验证

无污染埋点（包装 provider 记录每次调用 + logging handler，零生产代码改动）+ JSON 取证：

- **端点行为探明**：模型层不按探测窗口（129K）拒绝——811K token 照常接受并产出正确摘要；真实拒绝有两层：网关 10MB 体积上限（413）、模型层约 1.5M token 上限（400）
- **首轮暴露真缺陷**：12.5M 字符起步，3 轮收缩（11.9M→9.5M→7.6M 均 413）后 6.1M 字符落到模型层真 400——但收缩预算已穷尽，代码把它当偶发失败，用**完全相同的请求**又打了两次（必然同败）。当场修复为穷尽即回退（73.1 第 5 条），并同步修正单测断言（穷尽路径调用数 5→4）
- **修复后全管道 PASS**：cap0=6.5M → 首调 6.2M 真 400 → 收缩至 4.97M 仍 400 → 再收缩至 3.98M（999K token）成功产出 9 节 LLM 摘要；中部埋点约定被摘要捕获、早期埋点按设计随最旧消息丢弃；2 条 shrink WARNING、请求尺寸严格递减

### 73.3 测试

6 个新单测：识别函数（400/413/关键词/非超长不误判）/ 400 后丢最旧重试成功（验证第二次 prompt 不含最旧消息）/ 穷尽立即回退（调用数 = MAX_SHRINKS+1，不烧偶发预算）/ 收缩与偶发预算独立（400→ConnectionError→成功共 3 次调用）/ 旧摘要保护 / 无可丢消息不崩溃。852 个测试全过，ruff lint + format clean。

## 74. 全局事件监听插件

### 74.1 前因

死代码审计（todo-code-quality 扩展点 #1）发现 `EventBus.on_any()` 自 P1 就存在但**零调用方**——注释写着"日志/调试用"，实际从未有人能用上：订阅需要写 Python 并改 app.py 装配代码，"零改循环代码加可观测性"的架构承诺（agent-architecture 4.3）只对内置订阅者成立，对**用户**并不成立。同时 `emit` 的 `return_exceptions=True` 把 handler 异常静默吞掉——坏订阅者无声失效，调试无从下手。

### 74.2 方案

`extensions/event_listeners.py`：启动时从顶级配置 `listener_dirs`（默认 `./.mini-agent/listeners` + `~/.mini-agent/listeners`）加载 *.py 插件。契约两档：`register(bus)` 完全控制（订阅特定事件），`on_event(event)` 便捷形式（同步/异步均可，自动经 `on_any` 全局订阅）；两者都有时 register 优先。配套补齐 `off_any()`（有 on 必有 off）和 `emit` 的 handler 异常 warning 日志。

**权衡**：导入即执行任意代码——但插件目录在用户自己的项目/home 下，信任边界与 CLAUDE.md、`.mini-agent/config.toml` 一致（能改这些文件的人本就能改一切）；换取的是零装配成本。异常三层全隔离（导入/注册/运行）——观测组件绝不能反噬被观测系统。

### 74.3 后果与验证

用户丢一个 .py 进目录即可把全部事件落盘 JSONL、做工具调用统计——不改一行源码。启动提示 "Loaded N event listener(s)" 确认加载。`on_any` 从死代码变为插件机制的承载点。

## 75. Hook 确认裁决 CONFIRM 接入

### 75.1 前因

`HookAction.CONFIRM` 自 P3 定义、`HookManager.run()` 也实现了"遇 CONFIRM 短路上交"，但上层（agent_loop）**只处理 BLOCK**——hook 返回 CONFIRM 会被静默当作放行，语义悬空至今（todo-code-quality 扩展点 #7"未来交互式 hook 可能用"）。spec 14.4 当初就设计了 `action = "confirm"` 的配置 hook，一直没落地。用户侧的真实缺口：`[[hooks]]` 只有"一刀切拒绝"，没有"敏感操作让我看一眼"的中间档——比如 git push 不想禁死但想人工过闸。

### 75.2 方案

三层接线，遵循既有架构约束（§3"HookManager 不持有 UI 引用，确认动作由持有 terminal 的上层执行"）：

1. **配置层**：`HookRule` 新增 `action` 字段（`"block"` 默认 / `"confirm"`，非法值告警跳过不阻断启动——与既有非法条目语义一致）
2. **裁决层**：`agent_loop._resolve_hook_confirm()` 用 app 注入的 `terminal.confirm` 弹 y/a/n（与权限确认同一弹窗，用户零新概念）；"a" 按 (工具名, 原因) 记会话授权，同规则不再问
3. **并发防护**：确认弹窗加 `asyncio.Lock`（并行工具执行时弹窗不可交错，等锁后重查授权防重复问）；流式工具执行经 `HookManager.would_confirm()` 非交互预判（对标 `PermissionManager.would_ask`），会弹窗的延迟到 `_act`——弹窗不能和流式渲染交错；弹窗等输入期间并行工具的输出经 `_prompt_protected` 的 `patch_stdout` 重定向到提示行上方（§94），输入行不被打断

**权衡**：CONFIRM 短路意味着用户放行后**不再执行链上后续 hook**（与 BLOCK 同语义）——按"安全裁决一票定案"的既有原则接受；`would_confirm` 只覆盖声明式规则，代码注册的 hook 返回 CONFIRM 无法不执行即预测（诚实边界）。fail-safe 延续：无 confirm 回调（脚本/CI/子 Agent）一律拒绝。

### 75.3 后果与验证

`[[hooks]]` 从"禁止清单"升级为"禁止 + 人工闸门"双档；拒绝时 LLM 收到 `Denied by user: <reason>` 会调整策略而非重试。9 个新单测（解析/预判/短路/管道端到端 y/n/always/无回调）+ 真实 LLM 全管道三路径验证（JSON 取证 PASS）：y 放行只问一次、n 拒绝且 LLM 正确收尾、a 两次写入只问一次。887 个测试全过（P77 后 897）。

## 77. 四个中级扩展点接入

### 77.1 前因

todo-code-quality 审计的 16 个有意预留扩展点中，P76 接入了 3 个轻量点（#1/#4/#12/#13），仍有 4 个中级扩展点有明确的自然接入位置但零调用方：#2 `ToolRegistry.filter()`、#6 `Plan.is_complete`、#11 `SessionMetadata.tags`、#14 `PermissionRequest.tool_name`。

### 77.2 改动

**#2 ToolRegistry.filter()**：`AgentTeam.start()` 非写文件步骤的工具过滤从手动 list comprehension（`[t for t in base if t not in _WRITE_TOOLS]`）改为 `self._manager._tools.filter(denied=list(_WRITE_TOOLS))`；`SubAgent.__init__` 工具白名单过滤同样改用 `registry.filter(allowed=effective_tools)` 后再 unregister。一处代码路径、一个语义。

**#6 Plan.is_complete**：`AgentTeam.start()` 主循环从 `while pending:` + 手动维护 `pending = [s for s in pending if s.index not in results_by_index]` 改为 `while not plan.is_complete:`，每轮从 `plan.steps` 中筛选 `status == "pending"` 的步骤。步骤完成时 `step.status` 已在回写，`is_complete` 自然为 True 时循环终止。

**#11 SessionMetadata.tags**：新增 `/session tag <name>` / `/session untag <name>` / `/session tags` 三个子命令；`/session list --tag <name>` 按标签过滤。tag 名只取第一个词（真实终端验证暴露贪心 bug 后修复）。`session_store.list_sessions()` 返回 `tags` 字段。tags 经 JSON 序列化/反序列化往返存活。

**#14 PermissionRequest.tool_name**：`check_path()` 新增 `tool_name` 参数（默认空串，向后兼容），`agent_loop._check_permission()` 三个分支（read_file/glob/grep + write_file/edit_file + delete_file）传入 `tool_name=tc.name`。`check_command()` 已有 `tool_name="bash"`。审计日志的 permission 条目中 `"tool"` 字段来自 `PermissionCheckEvent.tool_name`，此前 path 类工具也能正确记录。

### 77.3 后果

- 10/16 扩展点已有真实调用方（#1/#2/#3/#4/#6/#7/#11/#12/#13/#14），剩余 6 个是纯 API 表面预留
- `/session` 从 4 个子命令扩展到 7 个（save/list/load/delete/tag/untag/tags）
- 10 个新测试，897 个全过

# 78. 运行时权限规则管理

## 78.1 动机

`PermissionManager.add_rule()` 是 16 个预留扩展点中的 #3，原始实现仅一行 `self._rules.append(rule)`，零调用方。用户在会话中发现新的命令/路径需要放行或拦截时，只能编辑 TOML 文件并重启——运行时动态管理权限规则是明确需求。

## 78.2 实现

**PermissionManager 增强**（`security/permission.py`）：
- `add_rule(rule, *, _silent=False) -> bool`：空 pattern 校验（`ValueError`）→ 三元组去重（scope+pattern+level）→ 追加 `_rules` → 发射 `PermissionRuleAddedEvent`（`_silent=True` 跳过事件，供启动阶段使用）。返回 `False` 表示重复
- `remove_rule(scope, pattern, level) -> bool`：按三元组查找移除 → 发射 `PermissionRuleRemovedEvent`
- `list_rules() -> list[PermissionRule]`：返回副本，供 `/allow` `/deny` 无参列出
- `save_rule_to_file(path, rule)`（静态方法）：`tomllib.load` 读取已有 TOML → 合并去重 → 回写。自动创建父目录
- `__init__` 新增 `event_bus: EventBus | None` 参数
- `_load_rules_from_config()` 和 `load_rule_files()` 统一走 `add_rule(_silent=True)`，保证规则入口单一

**事件类型**（`models/events.py`）：
- `PermissionRuleAddedEvent(scope, pattern, level, reason)`
- `PermissionRuleRemovedEvent(scope, pattern, level)`

**斜杠命令**（`extensions/builtin_commands.py`）：
- `/allow <command|path> <pattern> [--save]`：添加 ALLOW 规则
- `/deny <command|path> <pattern> [--save]`：添加 DENY 规则
- 无参数：列出该级别的全部规则
- `--save`：追加写入项目级 `.mini-agent/permissions.toml`，重启自动加载

**装配**（`app.py`）：`PermissionManager(event_bus=self.event_bus)` 一行接线。

## 78.3 后果

- 10/16 扩展点已接入（新增 #3）
- 可见斜杠命令从 22 个增至 24 个（`/allow` `/deny`）
- 13 个新测试（add_rule 验证/去重/事件/静默 + remove_rule + list_rules + save_rule_to_file），912 个全过
- 规则生命周期：不带 `--save` 仅当前会话；带 `--save` 持久化到 TOML

# 79. 工具级权限与通用检查入口

## 79.1 动机

权限系统此前只有两个生效的 scope：COMMAND（bash 命令）和 PATH（文件路径）。`PermissionScope.TOOL` 枚举值（扩展点 #9）从第一天就存在但零消费——用户想"这个会话禁用 delete_file 工具"没有任何入口，只能逐条 deny 路径。同时 `PermissionManager.check()`（扩展点 #15）名为通用入口，实际只被 `check_path` 尾部调用：外部消费者拿着 COMMAND scope 的 `PermissionRequest` 调 `check()` 会**绕过危险命令确认**（check() 只走规则+默认模式），拿着 PATH scope 的请求会**绕过 PathGuard**——"通用入口"实为陷阱。

## 79.2 实现

**工具级门**（`check_tool(tool_name) -> PermissionDecision | None`）：构造 TOOL scope 请求走 `_check_rules_only()`——显式 TOOL 规则和会话授权判定，无匹配返回 `None`。`agent_loop._check_permission()` 对**所有**工具调用先过这道门：DENY 拦截、ALLOW 整体信任（跳过命令/路径检查）、None 落回原有资源级路由。事件照常发射（scope="tool"，带 matched_rule）。

**通用入口重构**（`check(request)`）：按 `request.scope` 分发——COMMAND → `_check_command_request()`（含危险模式确认），PATH → `_check_path_request()`（DENY 规则 → PathGuard → 通用管道，operation 从 request.context 前缀解析），其余 → `_check_generic()`（原 check() 逻辑）。`check_command`/`check_path` 改为构造请求后调分发目标，同一批内部管道无递归。

**配套接入**：`/allow` `/deny` 新增 `tool` scope 和 `remove` 子命令（`/deny remove tool bash` 调 `remove_rule()` 精确移除会话内规则——TOML 来源的规则下次启动仍加载）；permissions.toml 新增 `[tools]` 节（`load_rule_files` 解析 + `save_rule_to_file` 经 `_SCOPE_SECTIONS` 映射回写）；`would_ask()` 开头加工具级预判——显式工具规则直接判定，不弹窗（流式执行预提交不受影响）。顺带修复输出转义：`Added ... [tool] \`x\`` 中的 `[tool]` 被 markdown 当未定义引用链接吞掉，改为 `\\[tool]` 转义。

## 79.3 权衡

- **默认模式为什么不参与工具门**：若工具门无规则时落到默认模式，deny 模式会在工具层拦掉 read_file——PathGuard 的项目内放行永远走不到，等于 deny 模式下 Agent 全瘫。`None` 落回资源级检查保持了原有行为的完整性。
- **TOOL ALLOW 为什么跳过资源检查**：`/allow tool bash` 若只在工具层放行、危险命令照旧确认，则该规则对 bash 近乎空操作（普通命令本来就自动放行）。整体信任语义让规则有真实效果，代价是危险命令也不确认——文档标注"慎用"。
- **operation 从 context 前缀解析**：PATH 分发需要 read/write 语义，`PermissionRequest` 没有 operation 字段。约定 `check_path` 写入的 context 以操作名开头（"write access ..."），外部消费者不写 context 时默认按 read 处理——宽松但安全（write 比 read 严格，误判为 read 只影响溢写缓存这一处只读放行）。

## 79.4 后果与验证

- 12/16 扩展点已接入（新增 #9/#15）
- 22 个新测试（check_tool 六态 + check() 分发四路 + [tools] 持久化两向 + would_ask + agent_loop 集成四例 + /allow /deny 处理器五例），934 个全过，ruff clean
- 真实 LLM 验证（`experiments/verify_tool_permission.py`，deepseek-v4-flash-0731）四阶段全过：TOOL deny 拦下 LLM 发起的 `echo hello`（事件 scope=tool、rule=deny:bash）；对照组危险命令 `git commit` 弹确认；TOOL allow 后同一危险命令零弹窗执行；check() 三 scope 分发判定正确；[tools] 节 save/load 往返生效
- 规则文件格式向后兼容：旧 permissions.toml 无 `[tools]` 节照常加载

# 80. 默认 Agent 类型接线

## 80.1 动机

P48 引入 4 种 Agent 类型（explore/plan/worker/verify）时定义了 `DEFAULT_AGENT_TYPE = "worker"` 常量，但 `SubAgent.__init__` 的未指定类型分支没有引用它，而是走一条独立的内联 `SUBAGENT_SYSTEM_PROMPT` 旧路径——该 prompt 与 `_WORKER_PROMPT` 几乎逐字重复（只多一句中文报告提示），改一处忘另一处的典型隐患。

## 80.2 实现

`SubAgent.__init__`：`agent_type is None` 时回退 `get_agent_type(DEFAULT_AGENT_TYPE)`，工具/提示词逻辑与显式类型统一为一条路径；删除 `SUBAGENT_SYSTEM_PROMPT`。`SubAgentManager.spawn`/`worker.py` 传 None 的调用方零改动自动获益。

## 80.3 权衡：迭代预算的不对称

worker 类型档案是 `max_iterations=50`，而 `config.max_agent_iterations` 默认 80 且用户可配。若未指定类型也整体采纳 worker 档案，用户配置的预算会被静默压到 50——SubAgent 提前熔断且用户难以察觉。因此保留不对称语义：**未显式选类型 → 保留 config 预算（仅统一 prompt/工具逻辑）；显式选类型 → 采纳类型完整档案（含 50 轮预算）**。这与改动前的行为完全一致（改前未指定类型也用 config 预算），向后兼容优先。

## 80.4 后果与验证

- 13/16 扩展点已接入（新增 #10）；`SUBAGENT_SYSTEM_PROMPT` 双份维护点消除
- 4 个新测试（DEFAULT_AGENT_TYPE 合法性 + 未指定类型走 worker 模板 + 未指定类型保留 config 预算 + 显式类型仍覆盖），938 个全过，ruff clean
- 真实 LLM 验证（`experiments/verify_default_agent_type.py`，deepseek-v4-flash-0731）两阶段全过：未指定类型的 spawn 用 worker 模板 + config 预算 80 + 全工具集完成真实写文件任务；对照组显式 verify 类型仍是 20 轮预算 + 只读工具集 + PASS 判定
- 行为差异仅一处：旧内联 prompt 里的 "(Chinese task -> Chinese report)" 示例短语消失，语言跟随规则本身仍在（"Respond in the same language the task is written in"）

# 81. slice_window 删除

## 81.1 动机

拓展点清单最后两行都指向 `Conversation.slice_window()`：#16 自己标注"同 #5（重复列出）"，故实为一处。分析后判定它不是健康的预留 API 而是**设计变更后的残留物**：按 token 从尾部截取消息的职责已被 ContextManager/Compressor 完全取代，且后者带着五个阶段的教训（工具对对齐、计数兜底、三重锚点、目标缩放）做得严格更对。

## 81.2 为什么删而不是接入

- **语义有坑**：`cost = msg.token_count or 0`——未计数消息按零成本通过、循环不 break，预算形同虚设；compressor 后来全部改用 `token_count or count_tokens(...)` 兜底，slice_window 是这个教训之前的产物
- **安全隐患**：尾部截取可切断 tool_use/tool_result 配对产生孤儿——严格 API 直接 400，正是压缩链路已付费修过的 bug 类（P71 等）
- **修好 = 重复**：补齐兜底计数 + 工具对对齐等于重抄 `_compute_keep_split`，制造 P80 刚消灭的那种双份维护点
- **零需求**：80 个阶段零生产调用方；已接入的 13 个拓展点每个都有真实消费者，为打勾硬造消费者违背接入标准

## 81.3 后果

- 删除 `slice_window()` 方法 + 对应单测；grep 确认源码零残留（spec.md 为历史设计文档按惯例保留）
- 拓展点清单收口：15 处实际条目中 13 已接入、#5 已删除、仅 #8 `PermissionDecision.PENDING` 待接入——已在 todo-code-quality 定义为一个三部分任务（pane worker 跨进程审批通道为主体 + remote 断连排队 + pending 事件可观测；PENDING 不做 check() 返回值而做跨进程边界的持久化中间状态）
- 937 个测试全过（938 减去随死方法删除的 1 个测试），ruff clean

# 附录：贯穿各阶段的通用设计原则

1. **接口先行**：LLMProvider / Tool / HookFn / CompressionStrategy / MCPTransport 都是先定契约再做实现，Mock 测试与扩展（AnthropicProvider 一行注册接入、MCP 工具透明挂载）都吃这个红利
2. **失败即数据**：所有错误（权限拒绝、Hook 阻止、工具异常、SubAgent 失败）都转成携带原因的结果对象进入数据流，上层可见可决策；异常只用于程序性 bug
3. **默认安全（fail-safe）**：无 UI 默认拒绝、敏感文件优先于项目放行、危险命令无视 allow 模式、dirty worktree 拒绝删除
4. **分层不越界**：工具层不 import 交互层（回调注入）、引擎层不 import UI（事件+回调）、记忆层延迟注入打破循环依赖、MCP 工具经 Adapter 走统一 Tool 接口——依赖方向永远单向向下
5. **一切可测**：延迟初始化解 TTY 依赖、MockLLM/FakeMCPManager 解外部服务依赖、tmp_path 解文件系统依赖、真实 git 仓库 fixture 做集成测试、Console(record=True) 捕获渲染输出——953 个测试约 90 秒跑完
6. **渐进式增强**：压缩用提取式→可升级 LLM 摘要；记忆提取用正则→可升级 LLM 分析；MCP 只做 stdio→预留 HTTP 插槽；每个模块保持简单可测但留有升级路径
7. **复用而非新造**：SubAgent 复用 AgentLoop、AgentTeam 复用 Planner+SubAgentManager、MCP 工具复用整条安全管道、/trace 复用 EventBus 事件流、/explain 复用 Skill 激活、/audit 复用 EventBus 订阅、/spawn /team 是 SubAgentManager/AgentTeam 的命令行壳——新能力尽量是既有组件的组合

# 82. PermissionDecision.PENDING 跨进程权限协议

## 82.1 为什么需要：pane worker 无权限门

`/spawn --pane` 的 worker 在独立进程中运行 `mini-agent --worker <spec.json>`。`_run_worker_inner()` 创建 `SubAgent` 时不传 `PermissionManager`，`AgentLoop._act()` 看到 `self._permissions is None` 后对所有工具调用返回 `PermissionDecision.GRANTED`——包括 `rm -rf /`、`git push --force` 等危险命令，零用户确认。

同时，远程/浏览器模式（`server.py`）的 `_confirm_via_ws()` 创建的 asyncio.Future 在所有 WebSocket 客户端断开时永远挂起——agent loop 阻塞，无超时无降级。

## 82.2 方案：文件协议 + 断连排队 + PENDING 事件

**Part 1（主体）：跨进程文件协议**

复用 worker 已有的文件协议模式（spec JSON → result JSON → 原子写 → 轮询收集）：

1. `security/remote_confirm.py` — `RemoteConfirm(workers_dir, agent_id)` 实现 `ConfirmCallback` 签名
2. Worker 侧：写 `<agent_id>.perm-request.json`（含 request_id/prompt/status=pending），轮询 `<agent_id>.perm-decision.json`，超时 120s 返回 False（安全拒绝）
3. Parent 侧：`_collect_pane_result()` 已有 0.5s 轮询循环，增加 `read_request()` 检查 → 发现请求 → `_resolve_worker_permission()` 调父进程的 `terminal.confirm` → `write_decision()` 写回
4. 文件由 worker 侧 finally 清理；parent 超时/取消后清理孤文件

`SubAgent.__init__` 新增 `permission_manager` 参数直传 `AgentLoop`；`worker.py` 搭建 PathGuard + PermissionManager + RemoteConfirm 完整权限栈并加载 permissions.toml 规则。

**Part 2：断连排队**

`server.py` 新增 `_pending_prompts: dict[str, str]`（req_id → prompt 文本）和 `_disconnect_timeout_task`。最后客户端断开时启动 120s 超时任务（deny all），重连时取消超时并 `_replay_pending_confirms()` 重发待处理请求。

**Part 3：PENDING 事件**

`permission.py._ask_user()` 在 `await self._confirm(prompt)` 前发射 `PermissionCheckEvent(decision="pending", reason="awaiting_user")`。`trace.py._on_permission()` 增加 pending 分支用 `theme.warning` 色显示 `PENDING (awaiting user)`。

## 82.3 设计权衡

- **PENDING 不做 check() 的返回值**：asyncio 的 await 吞掉中间态（调用方无法区分"正在等"和"还没问"）；LLM API 要求 tool_use/tool_result 配对，停放工具调用必伪造结果污染对话。PENDING 的语义是**跨进程/跨连接边界上的持久化中间状态**，不是权限判定结果
- **文件协议而非 IPC**：复用 worker 已有的 spec/result 文件模式（原子写 + 轮询 + schema 校验），零新依赖；跨进程 socket/pipe 在 Windows 上复杂度高且需要新的错误处理
- **单文件 per worker**：每个 worker 同一时刻最多一个权限请求（AgentLoop 的 `_confirm_lock` 串行化确认弹窗），文件名用 agent_id 而非 request_id——简化轮询逻辑

## 82.4 验证

- 15 个新测试（test_remote_confirm 10 + test_permissions 2 + test_remote 3）
- `experiments/verify_pending.py` 全管道 E2E：4/4 通过（y→GRANTED / n→DENIED / a→GRANTED+always / timeout→DENIED），每步带时间戳检查点和取证 JSON
- 真实 LLM 终端验证：`/trace` 显示 `perm command ... → PENDING (awaiting user)` → `GRANTED (user_confirm:yes)` 两行事件

# 83. 插件生态：pip 包与本地文件注册工具/命令/技能

## 83.1 基础就绪

P74（event_listeners 零代码监听插件）已经把文件式插件加载的全部基础打好：importlib 动态导入、契约函数发现、三层异常隔离、加载名回报。PyPI 发布（P33）后 `pip install mini-code-agent` 可用，entry point 发现有了宿主。剩下的工作只是把"只能挂事件监听"泛化为"能注册工具/命令/技能"。

## 83.2 方案：四钩子契约 + 双通道发现

`extensions/plugin_loader.py`（P83）：

**契约**（模块级可选钩子，沿袭 event_listeners 的 register 优先先例）：
- `register(ctx: PluginContext)` — 全控钩子，定义时优先且只运行它（ctx 暴露 tool_registry / slash_commands / skill_registry / event_bus / config）
- `register_tools(registry)` / `register_commands(registry)` / `register_skills(registry)` — 专用钩子，各拿对应注册表
- 都没有 → 警告跳过

**发现双通道**：
1. pip 包：`importlib.metadata.entry_points(group="mini_agent.plugins")`，包内 `[project.entry-points."mini_agent.plugins"] my_plugin = "my_pkg.plugin"` 声明
2. 本地文件：`plugin_dirs` 目录（默认 `./.mini-agent/plugins` + `~/.mini-agent/plugins`）的 `.py` 文件——免打包本地开发，信任边界与 listener_dirs/config.toml 相同（§74 论证沿用）

先 entry points 后目录；同名时目录文件让位并告警。`disabled_plugins` 按 entry-point 名或文件 stem 禁用。

**装配点**：app.py 在 `register_builtin_commands` 之后、终端补全接线之前加载——插件命令能进 `/` 下拉。`/plugins` 命令展示每个插件注册了哪些工具/命令/技能（钩子前后注册表 key-set 快照差分统计，对全控钩子同样有效）。

## 83.3 设计权衡

- **插件工具不受 `enabled_tools` 白名单约束**：白名单枚举的是内置工具；安装插件本身就是 opt-in 动作，`disabled_plugins` 是关闭开关。若让白名单管插件工具，每装一个插件都要改配置，违背"装上即用"
- **SkillRegistry 加 `_external` dict 而非贡献 skill_dirs**：`load_all()` 会 clear `_skills` 且被 `/skill reload` 重新触发——目录贡献方案需要新 API 加重扫，还强迫插件打包 SKILL.md 数据文件。编程注册的技能单独存放、每次重扫后合并，天然在热重载后存活
- **`entry_points` 顶层导入**：`from importlib.metadata import entry_points` 放模块顶层而非函数内——留出 monkeypatch 的测试缝，假 EntryPoint（`.name` + `.load()`）即可离线测试发现逻辑
- **三层异常隔离沿袭 §74**：导入失败 / 钩子异常 / 运行期异常都只警告不传播，坏插件绝不影响 Agent 主流程；钩子异常时整个插件记录丢弃（不出现在 /plugins），但已注册进注册表的条目不回滚——回滚需要注册表事务语义，成本远超收益（钩子内部分成功属罕见路径，日志已可定位）

## 83.4 验证

- 16 个新测试：test_plugin_loader 14（三钩子/register 优先/导入失败隔离/钩子异常隔离/无钩子警告/下划线与缺失目录/disabled 文件+entry point/entry point 发现与失败隔离/重名告警//plugins 命令两态）+ test_skills 编程注册存活 load_all + test_slash_commands names() 含 hidden
- 968 passed, 1 skipped，覆盖率门禁通过，ruff clean
- 真实运行验证（examples/plugins/word_count_plugin.py 复制进 ./.mini-agent/plugins）：启动横幅 "Loaded 1 plugin(s)"、`/plugins` 表格、`/greet` 输出、`/skill list` 见 haiku-mode、真实 LLM 成功调用 word_count 工具（words=9 chars=43 lines=1）、`disabled_plugins` 置顶级后插件确实不加载
- 验证中的教训：TOML 顶级键必须写在所有 `[section]` 之前——追加到文件末尾会落进最后一个 section 而静默失效，config.toml.example 的示例块因此放在"顶级配置"注释区

# 84. read-before-edit 门禁与强制问题修复

## 84.1 动机

edit_file/write_file 原本对文件内容零认知要求：LLM 可以凭想象的 old_text 编辑从未读过的文件，或基于早前读到的旧内容覆盖掉用户/外部进程刚做的修改。mewcode 的 `file_state_cache.py` 已验证此门禁的价值，列为 B2 增强项。

## 84.2 方案：FileStateCache 两道门

`tools/file_state_cache.py`：会话级 `{绝对路径: mtime_ns}` 缓存。read_file 成功后 `record`；edit_file 与覆盖**已存在**文件的 write_file 执行前 `check` 两道门——① 路径在缓存中（读过）② `mtime_ns` 未变（读后未被外部改）——任一不满足即拒绝，报错文案可行动（"Read it first" / "Read it again"），LLM 收到后通常自主先读再重试。成功编辑/写入后 `update` 刷新，连续编辑免重读。新建 write 与 delete_file 豁免（无内容可破坏/不依赖内容）。缓存挂 `ToolContext.file_state`，为 None 时门禁失效。

## 84.3 强制问题与修复

B2 首版在 app.py/subagent.py **无条件** `FileStateCache()`——门禁强制开启、用户无法关闭；同时 config 里加的 `enforce_read_before_edit: bool = False` 从未被任何代码读取（死配置），且语义与实际行为相反（声明默认关、实际永远开）。修复：字段默认改 `True`，两处装配点改条件创建（`false` → `file_state=None` 门禁整体关闭），主 Agent 与所有 SubAgent 同步受控。

## 84.4 设计权衡

- **默认 true 而非沿用死配置的 false**：B2 的防护价值已真实 LLM 验证（直接 edit 被拦 → LLM 自主改为先读再编辑），默认关闭等于默认放弃防护——"修复强制"给的是关闭出口，不是撤防
- **bash 旁路不堵**：sed 等命令改文件不经过此门。门禁定位是"文件工具的认知一致性检查"，命令风险由权限系统（DANGEROUS_COMMAND_PATTERNS / [[hooks]] 规则）另行管控
- **主/子 Agent 独立缓存**：SubAgent 各持实例——子 Agent 的上下文里本来就没有主 Agent 读到的内容，共享缓存反而会放行"子 Agent 没见过内容却能编辑"
- **mtime_ns 而非内容哈希**：零读取成本；误报（touch 未改内容）的代价只是一次重读，漏报（同纳秒改内容）概率可忽略

## 84.5 验证

- 15 个测试：10 门禁行为（未读拦/读后放行/外部改动拦/编辑后免重读/新建豁免/覆盖须先读/None 失效）+ 5 配置接线（默认值 / app 装配开关 / SubAgent 装配开关，关闭路径实测 edit 免读成功）；全量 1022 passed + 1 skipped
- TOML 加载端到端实测：`[tools] enforce_read_before_edit = false` 经 ConfigLoader 后字段确为 False（`_merge` 的 hasattr 动态映射天然支持新字段，无需改 loader）
- 真实终端验证：真实 LLM 会话中直接 edit 被拦、报错文案返回后 LLM 自主调整策略（先读或改用 bash——后者即"bash 旁路"设计边界的实证）

# 85. 自定义 Agent 类型：.md 声明式定义

## 85.1 动机

P48 实现了 4 种硬编码 agent 类型（explore/plan/worker/verify），但用户无法定义新类型。实际需求：reviewer（代码审查专用 prompt + 只读工具）、translator（翻译专用）、特定业务领域的定制 agent。mewcode 已支持从 `.md` 文件声明式定义。

## 85.2 方案：frontmatter + body

`core/agent_type_loader.py`：`parse_agent_md` 从单个 `.md` 文件解析出 `AgentTypeDefinition`（YAML frontmatter 提供 name/description/allowed_tools/max_iterations，body 作为 system_prompt 模板）；`load_agent_types` 扫描双目录（用户级 `~/.mini-agent/agents/` 先、项目级 `./.mini-agent/agents/` 后，后者覆盖前者）。`agent_types.py` 新增 `register_agent_type()` setter 写入 `AGENT_TYPES` 字典，消费侧（`get_agent_type`/`SubAgent`/`spawn_agents` 工具）零改动。app.py 启动时在 skill 加载之后调用。

## 85.3 设计权衡

- **内置不改 .md**：4 种内置保持硬编码，pip install 后无 .md 文件也可用；用户通过同名 .md 覆盖内置——灵活但不强制
- **无 PyYAML 依赖**：复用 `skills.py._parse_skill_file` 的 regex+逐行扫描模式，与项目"零厂商 SDK 依赖"一致
- **占位符白名单验证**：body 中的 `{xxx}` 在 parse 时试 format，含未知占位符则拒绝（`str.format` 只做命名替换不执行代码，无注入风险）
- **spawn_agents schema 动态化**：`agent_type` 字段 description 从 `AGENT_TYPES` 实时生成——自定义类型自动出现在 LLM 的工具提示中

## 85.4 验证

- 12 个新测试：parse 7（完整/最小/缺 name/非法 name/无 frontmatter/空 body/未知占位符）+ load 5（注册/项目覆盖用户/覆盖内置/跳过无效/不存在目录）
- autouse fixture 保存/恢复 AGENT_TYPES 防测试交叉污染
- 全量 1022 passed + 1 skipped，ruff clean

# 86. 后台子代理与完成通知

## 86.1 动机

LLM 的 `spawn_agents` 工具阻塞等待全部子 agent 完成（`wait_all(ids, timeout=300)`）——派发一个 5 分钟的分析任务后，LLM 只能干等，不能先做别的。comparison 6.2 自认此限制："主 Agent 在 spawn_agents 期间阻塞，真正实时的只有 Worker↔Worker 这条边"。mewcode 用 task_manager.py（BackgroundTask）+ notification.py（完成后注入通知）解决。

## 86.2 方案：复用 mailbox 通道，零新增注入机制

关键洞察：**通知注入通道现成**。`agent_loop.run()` 的 while 循环每轮迭代 THINK 前调用 `_deliver_mail`——drain 主 agent 收件箱并以 USER 消息注入对话。子 agent 完成通知只需是一封发给 'main' 的普通 mailbox 消息。

实现：`spawn_agents` 工具加 `background: bool = False` 参数；true 时走 `SubAgentManager.spawn_background()`——`spawn_parallel` 后为每个 agent 起 notifier 协程 `_notify_on_complete`（引用存 `_notify_tasks` 防 GC），协程内 `await self.wait(agent_id, 3600)` 拿到结果后 `mailbox.send(sender=agent_id, recipient="main", content="[Background agent 'x' completed successfully]\nTask: ...\nResult: ...")`。结果自动投递：`SubAgentCompleteEvent` 触发 `terminal.interrupt_input()` 中断输入等待，主循环通过 `_handle_background_delivery()` 即时 drain mailbox 并运行 `agent_loop.run()` 处理——无需等待用户下一次输入。

## 86.3 设计权衡

- **复用 mailbox 而非新通知机制**：mewcode 的 notification.py 是独立通知系统；mini 的 mailbox 已具备"注入对话"的全部语义（`_deliver_mail` + `[Message from agent 'x']` 前缀），新机制只会重复。通知就是一封信。投递时机后续增强：除迭代开始时 `_deliver_mail` drain 外，后台 agent 完成时 `terminal.interrupt_input()` 中断输入等待触发即时投递（见 §92）
- **notifier 内部调用 `wait()` 而非挂 done_callback**：wait 已封装超时/取消/`_active` 清理/`SubAgentCompleteEvent` 发射的全部语义，done_callback（同步）反而要重复这些
- **结果截断 4000 字符**：通知注入对话消耗上下文，超长输出（如整文件内容）会撑爆；4000 足够容纳典型报告，超出提示 truncated
- **默认仍阻塞**：需要全部结果才能继续的场景（如并行分析后汇总）阻塞语义更简单；background 是 opt-in
- **事件加 `background` 字段而非新事件**：app.py 的终端提示订阅者需要区分"后台完成"（提示用户）和"前台 wait 完成"（结果已在显示，提示重复）——`wait()` 发事件时查 `_background_ids` 即可，无需第二个事件类型

## 86.4 诚实边界

- ~~主 Agent 完全空闲（REPL 等用户输入）时，通知滞留 mailbox 直到下一次用户输入触发 `run()` 才注入对话~~ **✅ 已解除（见 §92）**：`SubAgentCompleteEvent` 触发 `terminal.interrupt_input()` 中断输入等待，主循环收到 `_BG_INTERRUPT` 哨兵后自动调 `_handle_background_delivery()` drain mailbox 并运行 `agent_loop.run()` 处理结果——空闲场景通知也即时送达，不再滞留
- mewcode 的 fork.py（fork 当前对话上下文的 worker）未纳入本批——后续由 §87（摘要式 fork）实现
- notifier 的 3600s 超时后 agent 被 cancel 并通知 FAILED——比无限等待更可预测

## 86.5 验证

- 5 个新测试：立即返回（返回时 agent 仍 active）/ 完成通知内容与 sender / 取消后 FAILED 通知 / 事件 background 字段两态 / spawn_agents 工具 background 路径
- 全量测试通过，ruff clean
- 真实终端验证（4 场景全过）：① 后台派发 24ms 返回（对照阻塞模式 7125ms），LLM 并行完成 README 12 章节总结，通知轮内送达；② 空闲滞留——LLM"已派发"结束 turn 后终端提示先行、通知不丢、输入"结果"两字即送达并注入第一轮迭代；③ 默认阻塞行为原样；④ 任务内容失败（文件不存在）由 agent 如实报告、通知仍为 completed（FAILED 语义只对应 agent 本身取消/超时/崩溃）
- **验证中的设计红利发现**：LLM 两次自主调用 `wait_message` 主动等待后台通知而非被动等 `_deliver_mail` 注入——因通知走 mailbox 通道，天然兼容三种消费方式（wait_message 阻塞等 / 迭代注入 / 自动投递），零额外代码。LLM 还两次交叉验证后台结果（抓到子 agent 107 vs 实际 109 的统计误差并修正）——后台结果作为消息注入而非工具返回值，LLM 对其保持了应有的怀疑态度

# 87. 摘要式上下文 fork

## 87.1 动机

SubAgent 空白上下文是刻意设计（便宜/可并行/可预测），但暴露真实痛点：和主 agent 讨论半天需求后说"派个 agent 按我们讨论的去做"——task 文本装不下讨论内容，子 agent 不知道之前聊了什么。mewcode `agents/fork.py` 用全量继承对话解决，两个代价：并行 N 个 agent = N 倍历史 token；fork 后主对话继续变化，子 agent 的认知从哪一刻冻结说不清。

## 87.2 方案：摘要即冻结快照

`compressor.py` 新增公开函数 `summarize_conversation(llm, messages)`：`_extractive_digest`（消息→历史字符串，取最近 24K 字符）→ `LLMSummarizeOldest._summarize`（P67 的 9 节结构化摘要）→ 异常时回退 digest 本身。两个入口共用：`spawn_agents` 工具 `inherit_context=true`（LLM 判断任务引用了当前讨论时自主开启）+ `/spawn --fork`（用户命令）。摘要经 `SubAgentManager.build_context_summary()` 生成一次，`context_summary` 参数透传 spawn/spawn_parallel/spawn_background 三层，注入子 agent system prompt 的 `[Inherited context ...]` 段（MAILBOX_NOTICE 之后）。

## 87.3 设计权衡

- **摘要而非全量**：成本 = 一次摘要调用 + 摘要长度 × N 个 agent（≪ 全量历史 × N）；摘要是冻结快照——fork 后主对话变化不影响子 agent 认知，一致性问题天然消解
- **失败回退 digest 而非报错**：fork 的语义是"带上下文派发"，摘要失败时降级为提取式摘录仍远好于空白上下文；绝不让派发本身失败
- **worker LLM 生成摘要**（manager 的 `self._llm`）：摘要的消费者就是 worker，用同一模型生成认知一致；也避免 ToolContext 加 llm 字段的接线
- **每次 spawn 调用摘要一次而非每 agent 一次**：同批 agent 共享同一快照，语义一致且省 N-1 次调用
- **复用 P67 而非新写摘要 prompt**：9 节结构（Primary Request/Key Concepts/Files/Errors/...）本就是为"让后续 LLM 接续工作"设计的——fork 场景与压缩恢复场景的需求同构

## 87.4 诚实边界

- `spawn_pane` 不支持——独立进程走 WorkerSpec 文件协议，传摘要需扩展跨进程协议，本批不做
- `/team` 不纳入——Planner 生成的子任务自带完整描述，fork 需求弱
- 摘要质量依赖 LLM——弱 worker 模型可能摘不全关键细节；回退的 digest 只有每条消息前 300 字符

## 87.5 验证

- 6 个新测试：summarize_conversation 成功/失败回退、SubAgent 注入/默认不注入、spawn_background 透传、spawn_agents 工具 inherit_context 端到端（MockLLM 脚本序列：第一项摘要输出、第二项子 agent 回复）
- 全量测试通过，ruff clean
- 真实终端验证（干净会话，4 场景全过）：① `/spawn --fork` 子 agent **Tools:0 且 5/5 讨论细节全中**（120→300/example 同步/中英文档/不动 llm timeout/跑测试查断言），连"当前仅讨论未修改文件"的状态都继承了；② 对照组（无 --fork）同任务 Tools:0 但 **0/5 细节、自信编造了完全不同的方案**（含虚构文件名）——空白上下文的幻觉风险实证，比"承认不知道"更糟（→ B9.1）；③ LLM 自主开 `inherit_context=True`，报告 300 秒正确；④ `background=true + inherit_context=true` 组合生效，通知报告"llm 的 timeout"正确

## 87.6 验证中暴露的问题（全部如实记录）

- **摘要生成阻塞且不可观测（已修复见 §91）**：`inherit_context` 的摘要是 execute 内的同步 LLM 调用，实测 46-54 秒终端零输出（用户以为卡住）；`complete()` 直调不发 trace 事件，`/trace on` 也不可见；background 组合下"立即返回"承诺打折（spawn_agents done 53938ms）。**已由 §91 修复：事件+终端提示+非阻塞后台。**
- **空白上下文幻觉编造（→ B9.1）**：见上 ②
- **首轮验证被测 LLM 擅自动手（→ B9）**：用户说"先不要动手只讨论"，agent 盘点后主动问"确认 A/B 后动手"，用户下一句以"对"开头的补充讨论被解读为授权，未经明确指令改了 6 处文件（后经指令还原，git diff + grep + 测试三重核查确认恢复彻底）
- **验证方案自身的两处判定错误（方法论教训）**：① 预设"trace 可见摘要 LLM 调用"——实际不可见（正是 §91 修复的可观测性缺口）；② 预设"background 组合毫秒级返回"——inherit_context 时不成立。教训：判定标准应先在代码层核实事件/输出的真实路径，而非从设计意图推断
- **对话污染判断失误（流程教训）**：首轮验证 agent 改文件又还原后，曾判断"讨论细节还在可继续 fork 测试"——错误：对话历史含"修改成功"记录，摘要会把污染传给子 agent 使判定失真。正确做法（已执行）：重启干净会话重测

---

# §88 内联解释器绕过封堵 + Windows 安全边界

## 88.1 前因

A2 真实验证实测暴露两次绕过：用户拒掉 4 条 `rm`/`rmdir`/`del` 命令后，LLM 改用 `python -c "import shutil; shutil.rmtree(...)"` 绕过正则黑名单，命令被 GRANTED 并真实删除了目录。第二次是 PathGuard 拒了 `delete_file` 工具后，LLM 用 `python -c "import os; os.remove(...)"` 同样绕过。

根因：`DANGEROUS_COMMAND_PATTERNS` 只看命令签名（`rm -rf`/`sudo` 这类），`python -c "..."` 引号内的任意代码完全不在检查范围内。Windows 上问题更严重——Linux/macOS 有 bwrap/seatbelt 内核沙箱兜底（即使绕过签名也写不了受保护路径），Windows 此前没有沙箱后端（`create_sandbox()` 返回 None），正则是唯一防线。

## 88.2 方案

**内联解释器黑名单 + Windows Low Integrity 沙箱 + 写后执行检测**。

`DANGEROUS_COMMAND_PATTERNS`（`security/permission.py`）新增 7 条正则（19→26 条，IGNORECASE），命中即弹确认框：`python -c`/`python - < file`、`node -e/-p`、`perl -e`、`ruby -e`、`(ba)?sh -c`、`powershell -Command/-c`、`pwsh -Command/-c`。

**Windows Low Integrity 沙箱**（`sandbox/windows.py` + `_low_integrity.py`）：管理员运行时，`_low_integrity.py` helper 用 ctypes 调 `SetTokenInformation` 将子进程 token 降为 Low 完整性。内核级强制——Low 进程不能写 Medium 对象（用户文件默认值），`os.chmod`/`attrib -R`/`shutil.rmtree+onerror` 全部被内核阻止。允许写入路径用 `icacls /setintegritylevel L` 降为 Low（需管理员），命令结束后恢复 Medium。deny_write 路径保持 Medium 不降。

**attrib 方案的教训**：最初尝试用 `attrib +R` 设置只读保护敏感路径。实测发现三个致命缺陷：① 子进程可用 `os.chmod`/`attrib -R` 一行清除；② `attrib` 是系统级的，阻断了 agent 自身对 `~/.mini-agent/input_history`/session/memory 的写入；③ 崩溃时只读标志残留。已完全禁用——`activate()`/`deactivate()` 为空操作，非管理员模式无文件保护且不打启动警告（限制仅 config-guide 文档说明）。

**写后执行检测**：`record_written_file()` 追踪本会话 agent 写过的文件，`is_executing_written_script()` 检测 `python script.py`/`cmd /c script.bat`/`./script.py`/`python -m module` 执行写过的脚本时弹确认。`_would_ask_command()` 同步更新防流式抢跑。`shared_written_files` 支持跨 Agent 共享。

## 88.3 权衡

- 内联解释器黑名单是减速带——LLM 仍可用更冷门的解释器绕过，但写后执行检测堵住了"先写 .py 再执行"的路径
- Windows 管理员 Low Integrity = 内核级保护（等同 bwrap/seatbelt），非管理员 = 无文件保护（OS 限制无解）
- Linux：bwrap 优先，bwrap 不可用时自动降级 unshare（`unshare --mount --map-root-user`，util-linux 预装）
- sandbox 默认开启（`SecurityConfig.sandbox = True`），后端不可用时启动警告

## 88.4 验证

- 权限测试 6 个 + 沙箱测试 17 个 = 23 个新测试函数，全量 1055 passed
- 管理员 Low Integrity E2E 验证通过：写入/删除/shutil.rmtree+onerror/attrib -R 绕过全被内核阻止，读取正常
- 管理员 icacls setintegritylevel L/M 实测返回 0（降级和恢复都成功）
- deny_write Low Integrity 验证通过：allow_write 内的 deny 子路径保持 Medium 不可写
- 真实 LLM 运行验证通过：`python -c "print('hello')"` 弹确认框 `dangerous command detected`
- record_written_file + is_executing_written_script + would_ask 集成验证通过
- 非管理员模式无文件保护、不打启动警告（限制仅 config-guide 文档说明，避免每次启动噪音）；`wrap()` 原样返回命令
- Linux/macOS 待对应平台验证（unshare 需 unprivileged user namespaces，seatbelt 需 macOS）

## 88.5 已知遗留

完整清单见 roadmap.md D3 条目。

---

# §89 危险命令被拒后停下求助，而非找绕过路径

## 89.1 前因

A2 实测事故：用户让删 `/tmp/a2test`，agent 连续被拒 4 条危险命令（rm/rmdir/del 各形态，正则全命中弹窗、用户全拒），但没停下，继续换方式，第 12 轮用 `python -c "shutil.rmtree(...)"`（不匹配任何危险正则）GRANTED 并真的删了目录——共 13 轮、烧 97k tokens。

根因是**行为层**：拒绝一条命令的语义是"这条不行"，agent 据此重构等价命令重试。绕过之所以得逞，本质是"被拒后继续找路"，而非正则不够全。D3（执行层：让绕过路径也弹确认）是互补项，D2 才是治本——连续被拒后停下。

## 89.2 方案

采用候选方案 ①（连续被拒熔断），复用现有 `_should_continue` + `stopped_early` 熔断机制，零新机制。初版只统计危险命令被拒，后扩展为覆盖**所有确认框被拒**——危险命令确认、项目外路径确认、hook（`[[hooks]] action=confirm`）确认：

1. **检测**：以真实确认框被拒为准——权限判定 reason `user_confirm:no` + hook 确认被拒。初版靠 `permission.py` 的 `last_check_was_dangerous` peek 属性识别危险命令，扩展后该属性已移除。自动策略拒绝不算：敏感路径拒绝（`path_guard:sensitive`）、显式 deny 规则、无 UI 默认拒绝是策略在拦、不是用户在说"别做"，不计数。
2. **计数**（`agent_state.py`）：`AgentState.consecutive_confirm_denials`，每轮 run() 重建 AgentState 自动重置。
3. **计数逻辑**（`agent_loop._check_permission`）：确认框 DENIED→+1、确认框 GRANTED→归零；未弹确认的调用中性（被拒之间的只读分析不动计数器）。
4. **熔断**（`_should_continue`）：计数 ≥ `max_consecutive_denials`（默认 1，拒一次即停）→ 设 `stop_reason="confirm_denied"` 停循环。
5. **回问**：run() 熔断分支按 stop_reason 定制 final_content（中文回问），app.py 按 stop_reason 显示区别于迭代上限的提示。

## 89.3 权衡

- 阈值 1：用户拒绝确认框通常就是"别做"，停下问你比猜下一条更好；调大可给被拒后修正重试的空间。
- 熔断只统计**用户在确认框上的拒绝**（`user_confirm:no` + hook 确认被拒）——自动策略拒绝（敏感路径 `path_guard:sensitive`、显式 deny 规则、无 UI 默认拒绝）不计数、仍只是跳过该次调用继续：那是配置好的策略在拦，不是用户当场表达"别做"。
- 为什么"未弹确认的调用中性"而非"任何命令都重置"：事故里被拒之间夹杂只读分析（读文件/grep）。若任何 grant 都重置，counter 永远到不了阈值。只统计连续的**确认框**被拒才是正确信号。
- 为什么确认框 GRANTED 重置：用户放行了 = 目标合法推进，不该再累积。

## 89.4 验证

- 4 个新测试：熔断触发 / 放行重置计数 / 未弹确认的调用中性 / 计数属性。全量 1059 passed。
- 真实复现 D2 事故脚本（rm→rmdir→del→python -c shutil.rmtree）：确认第 3 次被拒后 agent 停下（iterations=3），第 4 步 python 内联解释器绕过从未执行——D2 事故的完整绕过链被行为层截断（验证时默认阈值为 3、stop_reason 时名 repeated_denials；现默认阈值 1、`stop_reason="confirm_denied"`，首次被拒即停）。
- 扩展后范围补充：项目外路径确认被拒、hook 确认被拒同样触发熔断停机（验证时熔断只覆盖危险命令，此为后续扩展的行为）。

## 89.5 与 D3 的关系

D3 执行层（内联解释器正则 + 写后执行检测 + Windows Low Integrity 沙箱）让绕过路径也弹确认/被内核拦；D2 行为层让连续被拒后停下。两者叠加：D2 在阈值内仍可能有绕过尝试（默认阈值 1 时首次被拒即停、窗口几乎为零；调大阈值窗口相应变大），D3 兜住这些尝试的执行。单独任一层都不完整。

**诚实边界（Windows 非管理员）**：上面"D3 兜住执行"只在有 OS 沙箱时成立——Linux bwrap/unshare、macOS seatbelt、Windows 管理员 Low Integrity。**Windows 非管理员下 D3 沙箱啥也不做**（attrib 已禁用），执行层只剩危险正则。若一条破坏性命令既不触发危险正则、又不是写后执行的脚本，它会被静默放行（auto-grant）直接执行，D2（只数确认框被拒——这条命令根本没弹确认）计数器不增加、D3 也拦不住。这是 #1/#8 的执行层 OS 限制，D2/D3 都无法在此场景消除，只能靠 D2 缩小攻击面。完全解决只有管理员运行或 Windows 出非管理员进程级沙箱原语（不存在）。

## 90. bash 通道读敏感文件绕过 read_file 拦截（泄漏 API key）

## 90.1 现象

严重读泄漏：让 agent 读 `.env`，`read_file` 工具正确拒绝（命中 `PathGuard.is_sensitive_file`），但 agent 立刻改用 `type D:\...\.env`（bash 工具通道）成功打印文件内容，**泄漏了真实 API key**。与删除绕过同源——bash 能绕过工具层保护——但方向是读泄密而非破坏。

## 90.2 根因

敏感文件保护 `PathGuard.is_sensitive_file`（`.env`/`*.pem`/`*.key`/`id_rsa*`/`credentials*`/`*secret*` 等）只在 `read_file`/`write_file`/`delete_file` 三个文件工具上生效。**bash 命令管道（`_check_command_request`）从不做路径检查**——它只过 deny 规则、危险正则、写后执行检测，然后按默认模式放行。于是 `type`/`cat`/`Get-Content`/`more .env` 作为"普通命令"被 auto-grant。

## 90.3 方案

permission.py 新增 `command_references_sensitive_file(command)`：用 `_TOKEN_SPLIT_RE`（空白/`=`/shell 操作符 `|;&<>()`）把命令切成类路径 token，逐个取 basename，命中 `SENSITIVE_FILE_PATTERNS`（复用 path_guard 的同一份模式，`.env.example`/`.sample`/`.template` 例外）即为真。`_check_command_request` 里与 `is_dangerous`/`is_written_script` 并列判断，命中则 `request.context` 标注、`last_decision_reason="sensitive_file_command"`，走 `_ask_user`。

**为什么用确认而非静默拒绝**：静默 auto-deny（像 `path_guard:sensitive` 那样）不触发熔断（只数确认框被拒），agent 会换着法子重试；确认既给用户可见性，拒绝时又设 `user_confirm:no` 触发停目标。两个机制在这里自然咬合。

## 90.4 权衡与诚实边界

减速带而非围墙，同命令黑名单：token 化只能抓字面出现的敏感文件名，**变量展开（`$SECRET_FILE`）、通配、base64/echo 拼接、间接读取（`for /f`）等混淆仍可逃逸**。真正堵死读泄漏需要 OS 沙箱的读 ACL（Windows Low Integrity 不限制读 Medium 对象，故读保护它也做不到），架构上不可完全消除。本条目把常见明显形态从"静默放行"提升到"弹确认+可熔断"。

## 90.5 验证

`test_sensitive_file_command_detected`（token 检测正误报）+ `test_sensitive_file_command_asks_confirmation`（`type .env` 弹确认、拒绝后 reason=`user_confirm:no`）。真实验证：`type .env`/`cat ~/.ssh/id_rsa` 弹确认，`echo hello`/`cat README.md` 不受影响。2 个新测试，1058→1060。

## 91. fork 摘要生成可观测 + background 非阻塞

## 91.1 问题

终端验证实测暴露：`inherit_context=true` 时 `SubAgentManager.build_context_summary()` 调 `summarize_conversation()` → `LLMSummarizeOldest._summarize()` → `complete()`，做一次完整 LLM 调用（实测 46-54 秒）。期间终端零输出、`/trace on` 也看不到——`complete()` 直调绕过 AgentLoop 的事件链。`background=true` 组合下 `spawn_agents.execute()` 阻塞在摘要调用上，"立即返回"承诺打折。

## 91.2 方案

**可观测性**：`build_context_summary()` 前后发射 `ContextSummaryStartEvent`/`ContextSummaryDoneEvent`（新事件，`models/events.py`）。两个订阅者：① `app.py` 订阅显示终端提示（"Summarizing conversation for context fork..." / "Context summary ready (Xs, N chars)"），无论 `/trace` 是否开启用户都看到；② `TraceRenderer` 订阅显示 `ctx` 行，`/trace on` 下可见。事件在 `subagent.py` 的 `build_context_summary()` 发射（而非 `compressor.py`），因为后者没有 EventBus 且被压缩管线共用。

**非阻塞**：`background=true + inherit_context=true` 时把"摘要+spawn"整体放进 `asyncio.create_task`（`spawn_agents.py`），`execute()` 立即返回。消息列表浅拷贝防后续对话修改，task 引用存 `mgr._notify_tasks`（已有的 GC 保护模式）。前台模式不变（阻塞等摘要完成后再 spawn）。

`/spawn --fork` 命令总是前台，可观测性已被事件覆盖，无需非阻塞改造。

## 91.3 验证

3 个新测试：`test_build_context_summary_emits_events`（Start/Done 各一、duration_ms≥0、char_count 匹配）、`test_background_inherit_context_returns_immediately`（background+fork 立即返回、输出含 "context fork"）、`test_trace_renderer_ctx_summary`（TraceRenderer 渲染两行 ctx 事件）。全量 1060→1063 passed。

## 92. 后台 agent 结果自动投递

## 92.1 问题

终端验证实测暴露：`background=true` 派发的子 agent 完成后，`_notify_on_complete` 把结果写进 mailbox，但 `_deliver_mail()` 只在 `agent_loop.run()` 的每轮迭代开头执行——主 Agent 空闲等输入时 `run()` 已返回，消息滞留到用户下一次输入才被 drain。用户必须发一条无关消息才能看到后台结果，体验割裂。

## 92.2 方案

主循环把 `get_user_input()` 与后台完成信号做竞争。`SubAgentCompleteEvent(background=True)` 订阅者调 `terminal.interrupt_input()`：设置 `asyncio.Event` + TTY 路径 `prompt_session.app.exit(_BG_INTERRUPT)`（先保存 `current_buffer.text`，处理完经 `prompt_async(default=...)` 恢复，用户打了一半的字不丢）。非 TTY 路径 `asyncio.wait(FIRST_COMPLETED)` 竞争 `input()` executor 与 event（input 线程无法取消，中断后任务暂存 `_pending_input_task` 下次复用）。主循环收到 `_BG_INTERRUPT` 哨兵调 `_handle_background_delivery()`：注入合成 USER 消息触发 `agent_loop.run()`，`_deliver_mail()` 在第一轮迭代自然 drain 到结果。

**关键竞态（并行验证实测暴露）**：第二个 agent 在第一个结果处理期间完成时，`_bg_interrupt_event` 是 None（不在 `get_user_input()` 里），event 信号丢失——首版实现靠 prompt_toolkit `app.exit()` 的排队行为碰巧触发第二次投递。修复：`_handle_background_delivery()` 改为 `while mailbox.has_pending("main")` 循环，处理完一个结果立即检查是否有新到消息，不依赖中断信号的可靠性。`Mailbox.has_pending()` 为此新增——无锁只读（写入走 atomic replace，纯读安全）。

**为什么注入合成消息而非直接 drain**：`agent_loop.run()` 每轮迭代开头本就 drain mailbox，复用该路径零新增注入机制；合成消息同时给 LLM 明确指令（"结果已到，处理并汇报"），LLM 对 mailbox 注入的后台结果保持了交叉验证的怀疑态度（实测抓到子 agent 统计误差并修正）。

## 92.3 验证

3 个新 has_pending 测试。真实 LLM 终端验证：单任务 `spawn_agents(background=true)` 空闲 13 秒自动投递；`/spawn --background -p` 双任务并行，第二个 agent 在第一个处理期间完成，while 循环正确捕获，两个结果都送达。1063→1066 passed。

## 93. 用户输入行醒目化

## 93.1 问题

终端验证实测暴露：回车后 prompt_toolkit 输入行留在原地（默认样式无颜色），紧接 dim trace 行、工具输出、LLM 流式回答——滚动历史中很难定位"哪些是我打的话"。

## 93.2 方案

给输入行本身上样式：`create_prompt_style()` 根样式 `"": "bold {theme.user_input}"`，prompt_toolkit 输入文字打字时即着色、回车后保持样式；`get_user_input()` 在输入行上下由 `_input_rule()` 打同色横线形成边界。输入行本就在正确位置，缺的只是视觉权重——上样式即可，不需要追加任何新输出行。

## 93.3 细节

- Theme 新增 `user_input` 字段而非复用 `warning`：实测 `#f39c12` 黑底偏暗，输入行需要更亮——语义也不同（输入标识 vs 警告）。配色：default `#5fd7ff` 亮浅蓝 / dark `#7dcfff` / light 白底可读蓝 `#0969da`
- 根样式 `""` 影响所有未声明 noinherit 的元素——补全菜单/工具栏/滚动条早已全部 noinherit，无泄漏
- `_BG_INTERRUPT` 中断返回时不打下边线：没有用户输入确认，打线会留孤儿横线
- 非 TTY 朴素 `input()` 路径不经过 prompt_toolkit，保留上下横线

## 94. 确认弹窗输入行防并发输出打断

## 94.1 问题

终端验证实测暴露：工具并行执行时，一个工具触发权限确认弹窗（`allow? [y/a/n] > ` 等待输入），另一个并行工具完成时的 trace 行直接打进确认输入行——用户看不到输入位置。此前的 `patch_stdout` 只包裹了主输入框（`get_user_input` 的 `prompt_async`），`terminal.confirm()`/`ask_yes_no()`/`ask_structured()` 三条临时 PromptSession 输入路径未覆盖。`agent_loop` 的 `_confirm_lock` 只防多个弹窗互相交错，不防其他输出打断。

## 94.2 方案

`Terminal._prompt_protected(session, message)` 辅助方法：`prompt_async` 外包 `patch_stdout(raw=True)`——等输入期间所有 stdout 写入（Rich console 的 trace/工具结果行）经 StdoutProxy 重定向到提示行上方，输入行自动重绘保持干净。三条输入路径统一改走该方法。

**为什么不用 `with patch_stdout(...)` 直接包**：StdoutProxy 构建在无控制台环境（pytest、管道）抛 `NoConsoleScreenBufferError`，直接包会把本能正常工作的 prompt 拖进 plain-input 兜底（该兜底在 pytest 下 `input()` 又抛 OSError 连环炸）。辅助方法手动 `__enter__`/`__exit__`：proxy 建不出来就置 None、裸跑 prompt——保护是增强而非前置条件。

## 94.3 验证

4 个新测试（test_windows_rendering.py）：三条路径各验证 prompt 在 fake patch_stdout 上下文内执行且正常退出（真 StdoutProxy 需真控制台，pytest 下用记录替身）+ proxy 构建失败时 confirm 仍正常返回。1066→1070 passed。

## 95. 权限模式矩阵

## 95.1 背景

mewcode `permissions/modes.py` 有 default/acceptEdits/plan/bypassPermissions 四模式 × 工具类别决策矩阵。mini 此前只有三块拼图：plan 模式（`AgentLoop.plan_mode` 布尔，双重锁但权限层不知情）、`sandbox_auto_allow`（只覆盖危险命令场景）、`permission_mode`（allow/ask/deny，是"无规则匹配时的默认判定"另一根轴）——没有 acceptEdits/bypass 等价物，也没有统一的模式概念。

## 95.2 设计

`PermissionMode` StrEnum（default / accept-edits / plan / bypass），落在 `PermissionManager.mode` 属性上。矩阵单元不需要新的工具类别税制——权限管道的 scope + operation（命令 / 路径读 / 路径写）已经就是类别轴：

| 模式 | 危险命令 | 项目外写 | 项目内写 | 项目外读 |
|---|---|---|---|---|
| default | 询问 | 询问 | 放行 | 询问 |
| accept-edits | 询问 | **免确认** | 放行 | 询问 |
| plan | 询问 | **拒绝** | **拒绝** | 询问 |
| bypass | **免确认** | **免确认** | 放行 | **免确认** |

**判定顺序是安全关键**：显式规则（deny 优先）→ 模式 → 原有流程。bypass 放在规则之后——deny 规则在所有模式下有效（沿用 sandbox_auto_allow 的先例）；路径管道里 bypass/accept-edits 的免确认放在 PathGuard 敏感拒绝**之后**——任何模式都打不开 ~/.ssh 和 .env；plan 的写拒绝放在 PathGuard 项目内 ALLOW **之前**——否则项目内写会被先放行。

**plan 与既有双重锁的关系**：loop 的 schema 过滤（LLM 看不到写工具）和 act 拦截（幻觉调用兜底）保留，权限层的 plan 写拒绝是第三重锁——三层各有独立价值（提示词层/执行层/权限层），且权限层这把锁让 pane worker 等持有独立 PermissionManager 的场景也能受控。

**状态同步**：模式的唯一入口是 `Application.set_permission_mode()`——同时写 `pm.mode` 和 `agent_loop.plan_mode`（后者驱动 schema 过滤）。`/plan on|off`、`/mode`、`exit_plan_mode` 工具三个入口全部收敛到它，不存在两处状态漂移。

`would_ask()` 同步更新（bypass 永不问、accept-edits 写不问、plan 写直接拒不问）——否则流式工具执行的"会弹窗就延迟"预判与实际判定不一致，会造成无谓延迟。

## 95.3 命名

启动配置字段用 `approval_mode` 而非复用 `permission_mode`——后者已被 allow/ask/deny 的默认判定轴占用，语义不同（一个是"模式矩阵"，一个是"无匹配时的兜底决策"），复用会造成两义。

## 95.4 真实运行暴露的两个问题

首版实现终端实测暴露两个安全问题：

**① bypass 经 bash 通道泄漏敏感文件**：`read_file .env` 被 PathGuard 敏感拒绝拦下，但 LLM 立刻换 `type .env`——bypass 短路排在敏感文件命令检查（`command_references_sensitive_file`）**之前**，直接放行泄漏了真实 API key。"敏感路径所有模式有效"的承诺只在路径管道兑现了，命令管道漏了。修复：敏感文件命令检查移到模式短路**之前**——`type .env` 在所有模式下（含 bypass）都弹确认；`_would_ask_command` 同步补上敏感文件判断（此前完全缺失——顺带修了敏感命令可能在流式期间 eager 执行弹窗交错的既有缺口）。

**② plan 模式被 LLM 自批穿透**：`exit_plan_mode` 工具无条件退出 plan 模式——工具描述里"The user will review and approve"是空话，"Do not call any more tools this turn"也被 LLM 无视：实测它在同一批调用里 exit_plan_mode → write_file 直接落盘，用户没批准任何东西。修复三处：工具加**审批门**（`ctx.ask_user_callback` 弹 yes/no，用户拒绝则保持 plan 模式提示 LLM 修改计划；无 UI 回调时拒绝退出——安全默认与权限系统一致）；流式执行把 `exit_plan_mode` 加入延迟名单（审批弹窗不能和流式渲染交错）；工具描述改为如实陈述审批语义。

教训：**"模式只放宽询问"的不变量必须对每条管道逐一核对**——路径管道核对了，命令管道漏了；**任何让 LLM 解除自身限制的工具都必须有人在环**——纯提示词约束（"don't call more tools"）在实测中零约束力。

## 95.5 验证

22 个新测试（test_permission_modes.py 20 + test_process_tools.py 改造 2）：四模式矩阵单元格 × 底线不变量（bypass 下 deny 规则/敏感路径/敏感文件命令仍拦）；exit_plan_mode 批准退出/拒绝保持/无 UI 保持三路径；would_ask 各模式短路含敏感命令。default 行为与改动前完全一致。1070→1092 passed。终端实测：`/mode bypass` 后 `type .env` 弹确认不再泄漏；plan 模式下计划审批 yes/no 由用户裁决。

## 95.6 完整性复查：plan 只读承诺的三个穿透点

修复验证通过后做完整性复查（逐管道核对"模式只放宽询问"不变量），发现 plan 的只读承诺还有三个穿透点，两个当场修复、一个记 roadmap：

**① bash 写命令穿透（已修复）**：`echo HELLO> a.txt`、`mkdir`、`copy`、`move` 都不在危险正则里，plan 下作为普通命令直接放行——实测 LLM 的计划步骤里就写着 `echo HELLO> a.txt`，它不调 exit_plan_mode 也能落盘。修复：`WRITE_COMMAND_PATTERNS`（重定向到真实文件 + 分隔符后的改文件命令）plan 下 DENIED；`>nul`/`>/dev/null`/`2>&1` 是丢弃输出不算写，不误伤 `type x 2>nul` 类只读用法。与危险清单同为减速带诚实边界：混淆仍可逃逸。del/rm 等删除形态同时在危险清单和写清单——plan 下拒绝（强于询问）。

**② spawn_agents 穿透（已修复——禁用）**：`_READ_ONLY_TOOLS` 档案含 bash，且 in-process 子 agent 完全没有权限门（`spawn()` 不传 permission_manager，P82 只接了 pane worker）——plan 下派任何类型的子 agent 都等于绕开只读。限制只读类型不够（其 bash 无门照样写），传播权限栈是中等工程（并发弹窗交错问题），故 plan 下 spawn_agents 直接报错禁用；权限栈传播后续由 §96 实现，封条改为有门放行/无门禁用。

**③ 非文件写类工具穿透（后由 §96 实现）**：`unrestricted_tool` 分支直接放行 install_skill（写磁盘）/MCP 工具（外部副作用）——工具类别税制统一独立列表后按 模式 × 类别 判定，见 §96。

**可观测性补齐**：`PermissionModeChangedEvent`（`set_permission_mode` 发射，启动期无事件循环时跳过）→ trace `mode` 行；`/status` 显示 Permission mode；底部工具栏始终显示 `mode: xxx`（初版仅非 default 显示——实测 approval_mode 配置非法回退 default 时工具栏空白，用户无从确认回退成功，改为始终显示）。**拒绝消息带原因**：`_denied_message()` 把 `last_decision_reason` + 可读提示拼进工具错误（实测光秃的 Permission denied 让 LLM 烧 5 万 token 排查不存在的配置规则）；`_act` 阶段 1 逐工具捕获 `deny_reasons`——`last_decision_reason` 是管理器共享状态，结果构建时已被后续检查覆盖。

6 个新测试（plan bash 写拒绝/只读放行/default 不受影响/would_ask 一致 + spawn plan 禁用/非 plan 放行）。1092→1098 passed。

## 95.7 写形态检测的引号误伤与 cmd /c 补漏

实测边界确认 `WRITE_COMMAND_PATTERNS` 存在引号误伤：`findstr ">" file`、`git log --pretty="a>b"`、`awk "$1 > 5"` 等只读命令里引号内的 `>` 被当作重定向，plan 下误拒。修复：`is_write_command()` 匹配前剥离成对引号段（`_QUOTED_SEGMENT_RE`）——引号内的 `>` 是数据不是重定向；不成对引号不剥离，宁可误拦。

**剥离引号打开的新洞及其堵法**：`cmd /c "echo x > a.txt"` 的重定向在引号内，剥离后会逃逸——但 `cmd /c` 内联执行本身就是 Windows 版 `sh -c`（引号内任意命令绕过签名匹配），它却不在内联解释器危险清单里（清单收 sh -c/powershell -Command 时漏了它）。补进 `DANGEROUS_COMMAND_PATTERNS`（27→28 条）：`cmd /c` 一律弹确认，引号内重定向经人工确认兜底。安全论证：能把引号内重定向真正执行起来的内联执行器（sh -c / powershell -Command / pwsh -c / cmd /c）现已全部在危险清单内，引号剥离不会放走任何真实写入。

3 个新测试（引号内 `>` 放行 / 不成对引号仍拒 / cmd /c 危险确认）。1098→1101 passed。

## 96. 工具类别税制 + 子 agent 权限栈传播

## 96.1 问题

权限矩阵完整性复查（§95.6）留下的两个结构性缺口：① "工具类别"轴只覆盖 bash + 文件路径——`unrestricted_tool` 分支直接放行 `install_skill`（写磁盘）和 MCP 工具（外部副作用），plan 只读对它们无效；相关工具名单散落 5 处且已漂移（team.py 的本地 `_WRITE_TOOLS` 漏了 delete_file）。② in-process 子 agent 完全没有权限门——`spawn()` 不传 permission_manager（P82 只接了 pane worker），子 agent 的 bash 零检查，任何模式下都是洞。

## 96.2 类别税制

`ToolCategory`（read/write/execute/external）声明在每个 Tool 类上；**未声明默认 EXTERNAL**（保守：plan 拒绝，快照测试强制新工具做一次有意识归类）。矩阵新单元：plan×WRITE 拒绝——类别门在路径检查**之前**，所以无路径参数的 `install_skill` 也逃不掉；plan×EXTERNAL 拒绝——MCP 的进程外副作用无法验证只读，一刀切；bypass×EXTERNAL 显式放行。`task_*` 归 READ 是有意决策：任务板是 agent 的规划笔记本，plan 模式禁它等于禁规划本身。

**类别门必须读 `pm.mode` 而非 `loop.plan_mode`**——子 agent 的 loop 标志是 False，但传播来的权限栈带着父级模式；写在 loop 标志上传播就废了。schema 过滤/流式延迟/act 拦截仍用 loop 标志（它们是主会话的 UX 层），权限层用 pm.mode（它是跨 agent 的真值）。

`_READ_ONLY_TOOLS`（agent_types）**有意保留不合并**：它是类型档案的可用性白名单（explore 该拿到哪些工具），与权限判定（这次调用放不放行）是不同的轴——强行统一会把"能看见"与"能通过"两种语义搅在一起。

## 96.3 权限栈传播

`ChildPermissionManager`（`PermissionManager.child_view()`）的核心是**共享与隔离的边界选择**：规则表/会话授权/写文件集按引用共享（`/allow` `/deny` 实时生效，写后执行检测跨 agent 联动）；`mode` 是委托父级的 property（`/mode` 即时影响运行中子 agent，setter 也写回父级——单一事实源不允许分叉）；`last_decision_reason` 每子实例独立（并行 agent 不互相覆盖 trace 上下文）；**confirm 恒 None**——需要弹窗的一律 `no_ui:default_deny` 安全拒绝，多子 agent 并发弹窗交错问题就此消解而非解决（不弹就不交错）。刻意不调 `super().__init__`：从配置重建会把配置声明的规则重复灌进共享列表。

**联动收益**：B5 的"plan 禁 spawn"封条改为有门放行/无门禁用——子 agent 携带 PLAN 模式，写在权限层被拒，plan 模式恢复派研究 agent 的能力（对齐 Claude Code plan 模式可派 explore agent 的行为）。

**诚实边界**：子 agent 无 confirm 意味着危险命令一律拒绝而非询问——要让子 agent 的危险操作可人工放行需要串行化的跨 loop 确认队列，暂无场景不做。

## 96.4 终端实测暴露的对话框工具流式抢跑（当场修复）

实测 plan 模式下 LLM 调 `ask_user` 问方案调整——弹窗出现时 LLM 流还没结束（trace：`tool ask_user start` 早于 `llm response`），提示符被 trace 行淹没、用户盲打。根因：流式工具执行把 `ask_user` 当普通工具 eager 提交（READ 类别、不弹权限窗，逃过所有延迟判定），但它自己开对话框——对话框不能和流式渲染交错。`exit_plan_mode` 当初按名字特判延迟了，`ask_user` 漏了。修复：Tool ABC 加 `opens_dialog` 声明属性（ask_user/exit_plan_mode 为 True），流式延迟判定按属性而非名字——与类别税制同哲学（声明在工具上，不散落在名单里），新的对话框工具声明即生效。另一个实测确认：plan 模式下 LLM 根本看不到 install_skill（schema 过滤按类别把 4 个 WRITE 工具全滤掉，llm request 显示 16 tools）——类别税制在 schema 层就拦截，比权限层更早；权限层的 mode:plan 拦截作为子 agent（schema 不过滤）和幻觉调用的后备。

## 96.5 传播实测暴露的两个行为缺口（当场修复）

四步终端实测（plan 装技能包/plan 派 explore/plan 派 worker 写文件/deny 规则打子 agent）安全预期 16 项全守住，但暴露两个行为缺口：

**① 子 agent 绕路不熔断**：被 deny 规则拒掉 ping 后，子 agent 连试 9 个工具 10 轮找绕路（cmd /c → python -c → 写脚本再执行→ tool_search），每层都被拦但烧掉大量 token。根因：熔断只计 `user_confirm:no`，子 agent 的拒绝全是自动拒绝不计数。修复：`no_ui:default_deny` 纳入熔断计数——它是"确认拒绝"语义在无头循环中的对应物（本该问人、没人可问、安全拒绝）；策略拒绝（rule:/mode:/敏感路径）仍中性。主会话不受影响（永远有 confirm 回调，不会产生 no_ui）。`_DENY_REASON_HINTS` 的 no_ui 提示同步加"do NOT retry via alternative routes"。

**② 会话规则不可溯源**：主 agent 为查 `rule:ping*` 来源烧了 34 万 token 翻遍源码/配置/事件日志——`/deny` 加的会话规则只存在于内存，无文件可查。修复：拒绝理由带规则来源——`_rule_reason()` 拼 `rule:ping* [/deny session rule, not persisted]`（规则的 reason 字段本就记录来源：config/"permissions.toml(user|project)"/斜杠命令，此前没进判定理由）；运行时规则的 reason 文案同步明确化。LLM 看一眼就知道是会话规则、没有配置文件可找。

4 个新测试（no_ui 触发熔断/策略拒绝中性/规则来源进理由/无 reason 保持原格式）。1120→1124 passed。

## 96.6 复验暴露的两洞（当场修复）

上节两修的复验又抓到两个洞：

**① 方括号来源格式撞 Rich 标记**：`rule:ping* [/deny session rule, not persisted]` 里的 `[/...]` 被 Rich 解析为闭合标记，trace 处理器 MarkupError 崩溃、traceback 刷屏。双重修复：来源格式改圆括号 `rule:ping* (/deny ...)`；trace 渲染器所有动态字段（资源路径/理由/参数预览/用户文字）过 `rich.markup.escape`——含方括号的路径或输入本就是既有崩溃风险，一并堵死。

**② deny 规则被写后执行真实绕过（严重）**：子 agent 被拒 ping 后写 `run_ping.bat` 再**裸文件名执行**——`GRANTED (mode:ask)`，ping 真跑起来了。写后执行检测的正则只认 `./x`、`cmd /c x`、解释器三种形态，Windows 最简单的裸调用漏了。修复：`is_executing_written_script` 新增段首 token 检查（按 `|;&` 切段，每段首 token 解析后查写文件集）——只查首 token，`type run_ping.bat` 这类写后自检的读取不误触发；另补 `call`/`start` 启动形态正则。修复后完整绕过链变为：写脚本（放行）→ 裸调用 → 写后执行确认 → 子 agent 无 UI → 拒绝 + 熔断停。

3 个新测试（裸调用/分隔符/call/start 检出 + 读取不误触发 + 子视图完整链拒绝）。1124→1127 passed。

## 96.7 早停报告带原因与遗留物

四修复验全过后剩两个观察：① 子 agent 熔断报告只有"Stopped early"不带拒绝原因——主 agent 以为是偶发问题**盲目重派了一模一样的子 agent**走同一条死路；② 熔断即停没有清理机会，绕路写的 .bat 留在磁盘（两次重演 = 两个孤儿文件）。一处修复覆盖两者：`SubAgent.run()` 在 `stop_reason == "confirm_denied"` 时，error 消息带上子视图的 `last_decision_reason`（每子实例独立，不会被并行覆盖）+ 明示"Re-spawning will hit the same denial"+ 列出本次 `created` 的文件清单。父级 LLM 看到原因不再重派，看到遗留清单可以清理或告知用户。刻意不自动删：熔断停止的子 agent 也可能留下合法的半成品，删除是父级/用户的判断。1 个新测试（完整链：写 bat→裸调用→no_ui 熔断→报告含原因/劝阻重派/遗留清单）。1127→1128 passed。

**复验再修：报告带全部拒绝原因而非最后一击**——上述修复的复验发现报告取 `last_decision_reason`（熔断那一刻的值 = 最后一次拒绝 `no_ui:default_deny`），而根因 `rule:ping*` 已被覆盖——主 agent 误诊为"缺确认 UI"，建议加白名单/主 agent 代跑（代跑会撞同一规则）。修复：`AgentState.denial_reasons` 累积本轮全部去重拒绝原因（`_check_permission` 每次 DENIED 追加，`run()` 新建 state 自动按轮重置），早停报告列出全序列（根因在前）："Denials encountered: rule:ping* (/deny session rule, not persisted); no_ui:default_deny"。复验通过：主 agent 首次正确点名 deny 规则为根因、不再重派、列出遗留文件——但建议里编造了不存在的 `/permit` 命令、并提议主 agent 代跑（deny 规则对主 agent 同样生效，代跑必撞同一规则）。再补两条事实进报告：拒绝原因含 `rule:` 时附加 "deny rules apply to every agent in this session including the main agent" 与移除命令，让父级不靠猜。

**占位符再修 + 包装绕行真实洞**——上述提示的复验暴露两问题。① 占位符移除命令被错代入：提示写 `/deny remove <command|path|tool> <pattern>`，主 agent 代入成 `/deny remove ping ping*`（scope 填了 "ping"，实际执行会报 Unknown scope）。修复：拒绝理由格式改为内嵌 scope 的 `rule:<scope>:<pattern> (来源)`（如 `rule:command:ping*`），报告从中完整构造可照抄的命令 `/deny remove command "ping*"`——LLM 照抄不会错，占位符会。② 真实规则绕行：子 agent 第二轮试了 `cmd /c "ping -n 2 127.0.0.1"`——trace 显示拒绝原因是 `no_ui:default_deny` 而非 `rule:command:ping*`，即 deny 规则的 glob 匹配没认出包在 cmd /c 里的内层命令，拦住它的只是"cmd /c 属危险命令 → 需确认 → 子 agent 无 UI 兜底拒"这层纵深防御。隐患在主 agent：有 UI 时 `cmd /c "ping x"` 只弹确认框，用户一旦没注意内层是被拒命令就点了同意，规则被实质绕过。修复：deny 匹配引入 `_deny_command_variants`——解包 `cmd /c`/`cmd /k`/`powershell|pwsh -Command`/`sh|bash -c` 包装前缀（递归至 3 层），再对每个变体抹掉成对引号段后按 `&;|` 分段逐段匹配（`echo "a & ping x"` 引号内是数据，不产生 ping 段、不误拒）。allow 规则刻意不解包：扩大 deny 命中面是收紧（fail closed），扩大 allow 授权面是放松（fail open）。5 个新测试（cmd /c 包装、& 串联段、引号数据不误拒、allow 不解包、powershell 包装），1128→1133。

**边界声明（有意不做的部分）**：① 解包匹配是纵深防御非围墙——`p^ing` 转义、`set P=ping & %P%` 变量间接、`powershell -EncodedCommand` 等深度混淆在规则层原理性无法穷尽（完备识别命令最终行为等价于静态分析任意 shell 程序）；分层保证：混淆载体本身在危险命令清单里必弹确认，OS 沙箱是最终围墙；新形态实测暴露一个补一个。② 子 agent 危险操作只能拒不能问——跨 loop 确认队列技术可行（子 agent 挂起 → 确认请求入队 → 主 loop 安全时机弹窗 → 答复回传），但弹窗归属标识、挂起超时、background 完成时用户不在场、打断用户输入等交互成本高，暂无真实场景不做；需要人工放行的危险操作由主 agent 执行。两条边界均已写入 roadmap 遗留行、capabilities、checklist 与配置指南（zh/en）。

## 96.8 验证

19 个新测试（test_tool_categories.py）：20 内置工具类别快照（防漂移）、默认 EXTERNAL、矩阵单元格（plan×WRITE 无路径参数/plan×EXTERNAL/未注册名/bypass×EXTERNAL/default 不变/plan×READ 放行）、子视图（不弹窗拒危险/规则实时共享/mode 双向委托/敏感路径/trace 隔离）、spawn 传播（子视图类型与 mode 跟随/无 pm 无门/plan 有门派生放行）、对话框工具声明快照 + 默认 False。1101→1120 passed。

# §97 指令文件 @-include

## 97.1 问题

`memory/project_context.py` 只读单个指令文件（候选列表中 first-match-wins），不支持文件内引用其他文件。mewcode 的 `memory/instructions.py` 支持 `@./path @~/path` 递归引用（深度 5），mini 无此能力——项目规范分散在多个文件时，要么全复制进 AGENT.md 导致膨胀，要么 LLM 看不到没写进来的规范。

## 97.2 方案

`_expand_includes(text, base_dir, max_depth, _seen)` 逐行扫描，整行 `@./path` 或 `@~/path`（正则 `^\s*@(\./[^\s]+|~/[^\s]+)\s*$`）被替换为引用文件内容。关键设计：

1. **base_dir 跟着文件走**——A 引用 `@./sub/B.md` 时 B 的 base_dir 变为 `sub/`，B 中的 `@./C.md` 解析为 `sub/C.md`，符合直觉
2. **_seen 集合做循环检测**——resolve 后入 set，命中插 `<!-- circular include: path -->`
3. **缺失文件注释降级**——`<!-- include not found: path -->`，不中断加载
4. **max_depth=0 时不展开**——保留原行，`ContextConfig.max_include_depth` 可配
5. **展开后整体截断**——`_read_capped` 先展开再 max_chars 截断，include 引入的内容计入总长度
6. **只匹配整行**——行内 `see @./doc.md for details` 不触发，避免误触正文中的 @ 引用

`_read_capped` 新增 `max_include_depth` 参数（首文件自身也入 `_seen` 防自包含）。`load_project_instructions` / `load_user_instructions` 签名新增 `max_include_depth`，`app.py` 传递 `config.context.max_include_depth`。

## 97.3 验证

10 个新测试（test_project_context.py 从 11→21）：相对路径展开、home 路径展开、两层嵌套、循环引用注释标记、文件缺失注释标记、深度限制保留原行、depth=0 禁用、展开后截断、行内不误触、用户指令 @-include。全量 1143 passed。


# §98 恢复附件含 skill 调用记录

## 98.1 问题

压缩时 system prompt 不参与压缩，激活的 skill prompt 本身不丢——丢的是**激活历史**：`load_skill` 工具调用 / `/skill activate` 所在的消息被摘要吞掉后，LLM 不知道自己已激活过什么，会重复激活或遗忘能力。会话恢复的缺口更实际：system_prompt 序列化在会话 JSON 里（prompt 存活），但 `SkillRegistry._active` 集合是运行时状态——恢复后 `is_active()` 全 False、`deactivate()` 失效、`match_triggers()` 重复建议已激活技能、`reload()` 丢激活状态。mewcode 的恢复附件含 `record_skill_invocation/snapshot_skills`，mini 无对应。

## 98.2 方案

1. **SkillRegistry 记录调用历史**：`_invocations` 保序去重列表，`activate()` 成功时追加，`deactivate()` 不移除——它是"调用记录"不是"当前状态"。暴露 `active_names`/`invoked_names` 属性。
2. **回调注入保持层级方向**：`ContextManager.set_skill_provider(fn)` 接收返回 `(invoked, active)` 的可调用对象，app 装配时注入 lambda——memory 层不 import extensions 层。provider 崩溃被静默吞掉（不能因技能状态获取失败破坏压缩主流程）。
3. **恢复附件技能行**（`_inject_read_files` 第 4 段）：激活中的列 `[Skills active (their prompts remain in the system prompt -- do NOT re-activate): x, y]`——与已读文件 "do NOT re-read" 同一防重复模式；激活过但已停用的单列 `[Skills previously used this session (now deactivated): z]`。二次压缩剥离旧块的标记清单加入两个技能标记（否则只有技能没有已读文件的会话会堆叠旧块）。
4. **边界持久化与恢复**：`compact_boundary["skill_invocations"/"active_skills"]`；`adopt_boundary()` 暂存到 `adopted_skills` 属性（context.py 不反向操作 registry）；app 层 `_adopt_session` 调 `SkillRegistry.restore_state(invocations, active)`——**只恢复两个集合，不重注入 prompt**：恢复的 system_prompt 已含 skill prompt 标记，重走 `activate()` 会重复拼接。

**复验补修：手动 /compact 绕过管道**——终端复验（/skill activate → /compact → save → 重启 load → /skill）发现恢复后 `[ACTIVE]` 标记消失。根因链：/compact 直接调 `compressor.compress()` 而非 `check_and_compress()`，恢复附件与全部边界字段（已读文件/用户请求/技能状态）都不写——这是既有缺陷（read_files 等字段在手动压缩路径一直缺失），技能字段跟着一起缺；且复验对话为空（0 消息无可压），无摘要无边界。修复：`check_and_compress` 加 `force` 参数（跳过阈值与熔断检查），/compact 改走 `check_and_compress(conv, force=True)`——手动与自动压缩同一管道。连锁收益：force 模式下即使空对话，只要有激活技能，`_inject_read_files` 会插入恢复 SYSTEM 消息、fallback 从它建边界并写入技能字段——空对话场景也能持久化技能状态了。

## 98.3 验证

12 个新测试（3 skills + 9 context）：激活历史保序去重、停用保留历史、restore_state 不动 system_prompt、附件含激活行与 do NOT re-activate、停用单列、无 provider 附件不变（向后兼容）、二次压缩替换旧块不堆叠、provider 崩溃静默、adopt 暂存、旧边界无技能字段 adopted_skills 为 None、check_and_compress 端到端边界写入、force=True 低于阈值也走全管道并写技能边界。全量 1143→1155。

# §99 bash 副作用截断重试双执行修复

## 99.1 问题

A3 已通过 category gate 把 WRITE 类工具延迟到 `_act()` 消除双执行，但 bash 工具（`ToolCategory.EXECUTE`）未纳入——非危险的带副作用 bash（`mkdir`、`npm install`、`git add`）仍在流式期间 eager 执行。双执行链条：eager 任务已完成 → `task.cancel()` 空操作 → 重试产出相同工具调用 → `_act()` 中 `tc.id` 不在新 `streaming` 字典里（上次已清空）→ 再次执行。三重巧合但确实可触发。

## 99.2 方案

Roadmap 候选 ②：跨 attempt 结果缓存（根因修复）。不需要判断命令是否有副作用（不可穷尽），不需要牺牲流式延迟（只读 bash 仍即时执行）。

1. `_think()` 开始前初始化 `_eager_completed: dict[str, ToolResult]`（key = `name + "\0" + json.dumps(args, sort_keys=True)`）和 `_eager_keys: dict[str, str]`（tc.id → cache key）。
2. 截断重试时，已完成的 eager 任务（`task.done() and not task.cancelled()`）的结果存入 `_eager_completed`；未完成的照旧 cancel。
3. `_stream_once()` eager 提交前先查缓存——命中则创建 `asyncio.Future` 并 `set_result()`，不再执行；未命中则照常 `create_task()`。两者都记入 `_eager_keys`。
4. `_act()` 不变——`tc.id in streaming` 找到 Future 直接 await 返回。
5. 缓存生命周期限于单次 `_think()` 调用——不跨迭代、不跨轮次。
6. WRITE 类工具仍由 category gate 在缓存检查之前拦截，不进缓存路径（A3 不受影响）。

## 99.3 验证

3 个新测试（test_agent_loop.py）：同签名 bash 复用缓存只执行 1 次（核心）/ 不同签名不命中各执行一次 / WRITE 类仍走延迟路径回归守卫。全量 1155→1158。

# §100 思考流渲染碎行修复

## 100.1 问题

推理模型吐 `reasoning_content` 时，`ui/terminal.py` 的 `feed_thinking` 用 `console.print(delta, end="", ...)` 逐 token 输出，正文前出现一长串断续碎行（`.`/`11` 等孤立碎片各自成行）。仅推理模型触发（普通模型无思考流），时有时无非稳定复现。

## 100.2 第一次修复失败：soft_wrap 假设

roadmap D1 的初始分析把病灶定位在 Rich 的逐 print 宽度折行：`console.print` 不跨调用记录光标列位，每个小片段被当作从第 0 列起算的独立渲染单元按 `console.width` 折行。据此加了 `soft_wrap=True`（关闭 Rich 内部折行，交给终端），文件控制台单测也反向验证了该机制（Console(width=10) 下超宽片段确实被错位折行）。**但真实推理模型运行验证失败——碎行原样复现。** 教训：文件控制台（force_terminal=False）单测走的不是真实终端渲染路径，"测试通过 + 机制反向验证"不等于修好了真实症状，真实运行验证不可省。

## 100.3 真因：Live 拦截 + 整行擦除

真实终端的主机制在 agent_loop 与 renderer 的交互里：`_stream_once` 在**第一个 thinking chunk** 就触发 `on_stream_start` → `terminal.start_stream()` → `StreamRenderer.start()` 启动 Live。之后每个 `feed_thinking` 的 `console.print` 都发生在 Live 活跃期间——Rich 把 Live 期间的 print 拦截为 Live 区上方的独立行块（renderer.py 自己的注释就写着这行为），`end=""` 失效；且 ANSI 级取证显示每个碎片后跟 Live 刷新的 `\r\x1b[2K`（回车+整行擦除），碎片被后续刷新擦除/打断，与滚动竞争后只剩零星碎片幸存、各自成行——正好是实测症状（大部分思考文本消失，只剩 `.`/`11` 孤行）。宽度折行机制真实存在但只在无 Live 路径生效（次要）。

## 100.4 最终修复

Live 延迟启动（terminal.py）：`start_stream()` 只打分隔行不再启动 Live；`feed_stream()` 首个正文 delta 到达时才 `renderer.start()`（若有思考文本先收尾思考行+空行分隔）；`feed_thinking` 直连顺序写入（保留 soft_wrap 管无 Live 路径折行）。esc_watcher 仍在首个 thinking chunk 启动（双 Esc 中断思考不受影响）；思考仅无正文（后接工具调用）时 `renderer.finish()` 对未启动的 Live 天然安全（`_live is None` 跳过）。

备选方案（未采用）：thinking 缓冲按行 flush（引入缓冲状态与额外 bug 面）；裸 console.file.write + 手动 ANSI（丢样式整合、跨平台更脆）；agent_loop 层拆分 thinking/正文的 stream_start 回调（改动面更大且 esc_watcher 时机耦合）。

诚实边界：超宽思考文本由终端硬折行（不按词）——dim 辅助信息可读性足够；reasoning 自带换行是真内容原样保留。

## 100.5 验证

ANSI 级取证（force_terminal=True）：旧行为每碎片后跟 `\r\x1b[2K` 擦除码；新行为思考文本连续完整（`9.11 vs 9.9, thinking...` 一行直通）、正文 delta 才见 Live 控制码。4 个新测试（test_renderer.py）：思考期间无 Live+无擦除码+正文延迟启动 Live / 思考仅无正文 finish 不崩 / 超宽片段无 Rich 折行 / 自带换行保留。全量 1158→1162。终端真实验证已通过：两轮真实推理模型运行（9.11 vs 9.9 短推理 + 水池注水长推理，中英混排/自带换行/长段落全覆盖），思考流以 dim 连续段落完整显示在回答前，碎行消失（对照第一次修复时同款问题的碎行症状）。

# §101 on/off 模式命令无参数行为统一

## 101.1 问题

4 个 on/off 模式命令（`/trace`、`/explain`、`/audit`、`/plan`）无参数时行为各不相同：前三个是 toggle（`else: x = not x`），`/plan` 是无条件打开（`sub in ("", "on")`）。用户输 `/plan` 想看当前状态却被打开了（验证时暴露）。四个命令都不是最直觉的"显示当前状态"。

## 101.2 方案

统一为**无参数 = 只显示当前状态不改变**，`on`/`off` 显式切换。`/trace`、`/explain`、`/audit` 删除 `else` 分支的 toggle 赋值（直接落到已有的状态返回行）；`/plan` 拆开 `sub in ("", "on")`——`"on"` 走开启逻辑，`""` 走新增的状态显示（`Plan mode: **ON** (read-only)` / `**OFF**`，读 `app.permission_manager.mode is PermissionMode.PLAN`）。description 去掉 "Toggle"，改为 "no args = show status"。

备选方案（未采用）：统一为 toggle——但 `/plan` 从无条件打开改为 toggle 仍不直觉（用户不知道当前状态就盲切），且与 `/mode` 的"无参数 = 显示当前"不一致。

## 101.3 验证

4 个新测试（test_slash_commands.py）：每个命令初始状态 → 无参数调用 → 断言状态不变 + 返回包含当前状态描述。全量 1162→1166。

# §102 远程模式 SessionStore 接入

## 102.1 问题

远程模式（`--remote`）跑 `RemoteServer.start()` 而非 `Application.run()`，绕过了终端模式的全套会话持久化：每轮 `_autosave`、启动崩溃恢复、退出 `closed_cleanly` 标记、`cleanup_stale` 全部被跳过。结果：服务器重启丢失所有会话（roadmap 已知限制承认过；浏览器刷新的 `_replay_history` 只重放内存里的对话）。而 `app.session_store`、`_autosave()`、`_adopt_session()` 在 Application 构造时已存在且 UI 无关——远程模式缺的只是接线。

## 102.2 方案

**app.py**：从 `_maybe_restore_session()` 提取 `_find_crashed_session() -> dict | None`（列 sessions、过滤 closed_cleanly==False 且 project_dir==cwd 且非当前会话、返回最新），终端询问式恢复与远程自动恢复共用同一份过滤逻辑。

**remote/server.py 四个接线点**：
① `start()` 开头：`cleanup_stale`（镜像终端启动）+ `_restore_last_session()`——自动采用最新未关闭会话（`closed_cleanly=False` 恢复后重新算进行中），浏览器随后连接时 `_replay_history` 自然重放恢复的对话；
② turn 执行 finally：`_autosave(force=True)`（镜像终端每轮强制保存，硬杀不丢最后一轮）；
③ 斜杠命令后：节流 `_autosave()`（镜像终端）；
④ serve 块 try/finally：退出时 `closed_cleanly=True` + 强制保存（Ctrl+C 取消时 finally 仍执行；`_autosave` 对空会话跳过，全新服务器不落垃圾文件）。

**附带修复既有盲区**：远程模式下 `/session load`/`/fork` 换掉会话后浏览器不知情（连接时的重放不会重跑）。斜杠命令执行前后对比 `app.session` 对象身份，变化则广播新 WS 事件 `history_reset`（web_ui.py 清空聊天区与流式状态）并对所有客户端重放历史。

备选方案（未采用）：首个客户端连接时询问恢复——语义与终端一致但需新 WS 消息类型 + 前端弹窗 + 多客户端竞争处理，工作量明显更大；只持久化不自动恢复——"重启丢会话"体感只解决一半。

**复验补修**（核查"误恢复怎么处置"时暴露两洞，当场修复）：
① **无安全的"另起新会话"命令**——原表述"误恢复可用 /session 命令另起"不成立：/session 没有 new 子命令，裸 `/clear` 有数据覆盖坑（不换会话 ID，之后自动保存覆盖盘上旧历史——终端模式同样存在的既有坑）。新增 `/session new`：旧会话完整存盘并标记正常关闭（主动离开不是崩溃，不标记会被下次启动的崩溃检测误判；空会话跳过存盘防垃圾文件）、新会话换 ID 写另一个文件（旧文件从此不被碰——与 /clear 的本质区别）、保留 system prompt（与 /clear 语义一致）、继承 model/project_dir。三命令定位：/clear 擦黑板（同 ID，盘上旧历史会被覆盖）、/fork 复印一份接着写（新 ID + 深拷贝历史）、/session new 旧本子收进抽屉开新本子（新 ID + 空白）——用法详见 commands-guide /session 节。
② **`_adopt_session` 陈旧状态 bug（既有）**——ContextManager 持有三份会话级状态，都服务于压缩恢复附件：`_read_files`（本会话读过的文件，压缩后提醒 LLM"这些读过、变了要重读"）、`_last_user_request`（最近用户请求，压缩后防丢任务）、`_adopted_skills`（从边界恢复的技能激活状态，供 app 层写回 SkillRegistry）。`adopt_boundary` 的逻辑是"**有**压缩边界才写入，**没有**边界直接 return"——不清空。于是：load 带边界的会话 A（读过 a.py、激活 skill-x）→ 状态 = A 的；再 load 无边界的会话 B（从没压缩过的旧会话）→ adopt_boundary 直接 return 状态没动 → B 顶着 A 的状态跑——压缩恢复附件谎称"读过 a.py"，技能恢复把 A 的 skill-x 错误写回 registry。`/session new` 的全新空会话正是无边界路径，同一个洞的两面。修复：ContextManager 新增 `reset_state()`（三份状态全清空），`_adopt_session` 采用前**先复位再 adopt_boundary**——被采用会话永远从干净状态开始，有边界用边界重建，无边界就是真空白。代价：无边界会话（含 /fork 无边界分支）采用后压缩恢复附件的已读文件清单从零重建——正确性优先于恢复清单完整性。

## 102.3 诚实边界

- 恢复不询问，与终端模式的询问式语义不同（启动时无客户端可问）。误恢复处置（详见 commands-guide /session 节）：`/session new` 一条命令安全另起（误恢复会话完整存盘）；或 `/session load` 无损切走；**不要**直接 `/clear` 后继续对话——同一会话 ID 的自动保存会覆盖盘上旧历史（/clear 不换会话 ID，此坑终端模式同样存在，本次文档化并以 /session new 提供安全出口）
- 正常关闭（Ctrl+C）后会话标记 `closed_cleanly=True`，重启从新会话开始——自动恢复只针对崩溃/硬杀，与终端语义一致；旧会话可 `/session list` + `load` 手动恢复
- 多客户端仍共享同一会话（既有限制，不在本条目范围）

## 102.4 验证

13 个新测试（test_remote_session.py，FakeApp 借用真实 Application 方法 + 裸 RemoteServer 模式）：`_find_crashed_session` 三条件过滤/空库/排除当前 3 个；启动自动恢复 adopt+live-again/无候选不恢复 2 个；退出保存标记 closed_cleanly 1 个；WS 消息循环 turn 后强制保存/换会话广播 history_reset+重放/未换会话不广播 3 个；终端 `_maybe_restore_session` 仍询问式（提取助手后回归）1 个；`/session new` 旧会话存盘+新会话空历史保留 system prompt/空会话跳过存盘 2 个；`reset_state` 清陈旧状态 1 个。全量 1166→1179。

真实运行验证已通过（experiments/verify_remote_session.py，WS 客户端两阶段驱动真实服务器+真实 LLM）：对话一轮（"9.9 和 9.11 哪个大"）→ 硬杀服务器进程 → 检查会话文件 closed_cleanly=False 且存 2 条消息（每轮强制保存生效）→ 重启服务器 → WS 重连收到 history_user/history_assistant 完整重放上一轮对话（启动自动恢复生效），VERDICT: PASS。顺带发现启动横幅 print 在 stdout 为管道时被缓冲不可见，恢复提示行加 flush=True。

`/session new` 真实运行验证已通过：真实 LLM 对话一轮 → WS 发 `/session new` → 收到 "New session started: <新ID> / Previous session <旧ID> saved -- return with /session load <前缀>" 提示与 `history_reset` 广播（浏览器聊天区清空）；落盘检查旧会话 closed_cleanly=True、消息完整，VERDICT: PASS。

用户终端人工验证（日常动作级）全部通过：远程模式关窗口硬杀→重启自动恢复 / 远程 Ctrl+C 善终→重启空白新会话 / 终端关窗口→重启弹询问（y 恢复接上文、n 拒绝后标记 closed_cleanly=true 不再问）/ 终端 exit→重启不弹询问 / `/session new` 全流程（新会话隔离、旧会话 list 可见、load 回去历史与 LLM 上下文无损）。验证方法论教训：留给用户的验证只含日常动作（关窗口/Ctrl+C/聊天/刷新），文件取证类步骤由开发侧脚本完成，不混入用户步骤。

# §103 崩溃会话启动清理

## 103.1 问题

`SessionStore.cleanup_stale()` 只删"已正常关闭 + 超龄"的会话，`closed_cleanly=False` 的一律跳过。但崩溃恢复只取本项目最新一个崩溃会话——非最新的、以及再也不启动的项目的崩溃会话永久留盘（159 个会话 6.8MB，§102 远程持久化真实验证时实测暴露此积累）。

## 103.2 方案

`cleanup_stale()` 新增 `crashed_max_age_days` 参数：`closed_cleanly=False` 且超过该天数的会话也删除。默认 40 天——比正常会话的 30 天更宽松 10 天（崩溃会话有恢复价值，多留缓冲），0 = 永久保留（禁用此清理维度）。`MemoryConfig` 新增 `crashed_session_cleanup_days: int = 40`，app.py 和 remote/server.py 两个调用点同步传入。清理时机保持启动时、在崩溃恢复检测之前——40 天前的崩溃会话直接清掉不进恢复候选（正是意图）。`config.toml.example` 补 `[memory]` 两个清理配置的文档（`session_cleanup_days` 之前也未记录）。

当 `max_age_days <= 0 AND crashed_max_age_days <= 0` 时整体跳过（不扫文件）；单维度 0 只关该维度、另一维度仍生效。

## 103.3 验证

3 个新测试（test_session_store.py）：超龄崩溃会话被删且 40 天内的保留 / 0 禁用崩溃清理 / 正常 30 天逻辑不受 crashed 参数影响（回归）。全量 1179→1182。

# §104 /session list 分页

## 104.1 问题

`/session list` 把 `list_sessions()` 全部结果逐行输出——§102 远程持久化真实验证时实测 159 个会话一次刷 159 行，把之前的终端内容全部顶出屏幕；用户实际只关心最近几个。`--tag` 过滤是唯一收窄手段，但未打标签的会话无法过滤。远程模式浏览器里同样一大坨。

## 104.2 方案

默认只显示最近 20 条（list 已按 last_active 降序，直接切片）：`_SESSION_LIST_LIMIT = 20` 模块常量——不进配置，`--all` 已是出口、没有配置价值。参数解析从原来的 `startswith("--tag")` 改为 token 扫描（`--all` 标志 / `--page N` 取下一 token / `--tag <name>` 取下一 token），任意顺序组合。`--tag` 过滤先执行、分页后执行。

**真分页**（用户复验指出首版只有"截断+--all"不是分页，当场补上）：`--page N` 显示第 (N-1)*20+1 ~ N*20 条；尾行双语提示 `Page N/M 第 N/M 页 (总数) —— --page N+1 下一页 / --all 查看全部`，末页不显示下一页提示；页码超范围返回错误并提示总页数；非法页码值（非正整数）忽略回退第 1 页；`--all` 优先于 `--page`（全量出口语义不被页码干扰）。

## 104.3 验证

7 个新测试（test_slash_commands.py，真实 SessionStore + tmp_path）：25 个会话默认 20 行+尾行含总数 / `--all` 25 行无尾行 / 3 个无尾行 / `--tag` 过滤后仍截断 + `--tag --all` 组合全量 + 无匹配标签提示 / `--page 2` 显示剩余 5 条+页码 2/2+末页无下一页提示 / `--page 99` 超范围报错 / `--page 2 --all` 时 --all 优先全量。全量 1182→1189。终端真实验证：用户实际的 159 个会话场景直接跑 `/session list` 肉眼确认（这正是暴露此问题的原始场景）。

# §105 模糊确认不算授权 + 子 agent 反幻觉守则

## 105.1 问题

两个行为层 prompt 缺陷，均由真实 LLM 终端验证实测暴露：

① **模糊确认被当授权**：用户明确说"先不要动手，只讨论"，agent 盘点后主动问"确认 A 还是 B，确认后动手"；用户下一句以"对，另外提醒：改完要跑测试"开头（附和分析 + 继续讨论），agent 把"对"解读为方案授权，直接修改了 6 处文件——之后经指令还原、git diff + grep + 测试三重核查确认恢复彻底。根因："只讨论"是对话级约束，但 SYSTEM_PROMPT 没有"模糊确认不解除约束"的规则，LLM 按默认语义理解"对"。

② **无上下文子 agent 幻觉编造**：无 fork 的子 agent 收到"总结我们讨论的方案"类任务（引用它不知道的上下文）时，不承认不知道，自信编造了完整方案——含虚构实现细节和不存在的文件名（`bash_tool.py`，实际是 `builtin/bash.py`），`Tools: 0` 纯凭空生成。worker prompt 有"文件不存在要如实报告"守则，但没有"引用未知上下文时如实说明"的守则。

## 105.2 方案

纯 prompt 工程，无逻辑代码改动。

**B9**：`app.py` SYSTEM_PROMPT 的 Guidelines 列表末尾新增 `IMPORTANT:` 规则——用户明确表示只讨论/不要动手时约束持续有效（列举中英文关键词："先不要动手"/"只讨论"/"let's just discuss"/"don't make changes yet"），直到用户给出显式动手指令（"开始动手"/"执行"/"go ahead"/"do it"/"make the changes"）；模糊确认（"对"/"嗯"/"好"/"right"/"ok"/"yes"）只确认理解不解除约束；不确定时主动问"现在可以动手了吗？/ Ready to proceed with changes?"。与 git commit 守则同级别 `IMPORTANT:` 风格，英文正文中文关键词示例。

**B9.1**：`core/subagent.py` SubAgent 初始化时根据 `context_summary` 有无条件注入——无继承上下文时在 system prompt 末尾追加 `[IMPORTANT: You have NOT been given any context about the parent conversation. If the task refers to a discussion, decision, or context you have no knowledge of, say so explicitly and ask for the missing information in your report -- NEVER fabricate what was discussed.]`；有 context_summary 时不触发（已有真实摘要，fork 场景不受影响）。注入点在 agent 类型 prompt 之后（覆盖所有类型含自定义 .md），比 roadmap 方向建议的逐类型修改更全面且维护成本更低。

备选方案（未采用）：B9 用 /discuss 命令注入模式守则（类似 /plan 的 _PLAN_MODE_PROMPT 动态注入/移除）——语义更强但增加了命令复杂度、用户需显式激活/退出，而真实场景是对话中自然流露的意图不适合强制命令化。

## 105.3 诚实边界

prompt 守则是**提示非强制**——LLM 仍可能违反（尤其模型能力较弱或上下文窗口尾端时），但实测暴露问题的场景中加守则后命中率显著提高。这是 system prompt 技术的天然边界——真正的强制需要执行层机制（如 plan 模式的工具 schema 隐藏 + 执行拦截），但对话级讨论模式不适合全面禁工具（用户可能需要 agent 读文件辅助讨论）。

## 105.4 验证

无新测试（prompt 字符串改动不改变代码行为路径，全量 1189 回归通过）。真实 LLM 验证（可选但推荐）：说"先不要动手只讨论" → 给方案 → 回"对" → 看 agent 是否问"现在可以动手了吗"而非直接改文件。

# §106 /spawn 默认后台自动投递

## 106.1 问题

`/spawn <task>` 默认前台模式：子 agent 跑完后结果只存在于内存 task handle 里，用户必须手动 `/spawn wait` 收集——不输就永远看不到。后台模式 `--background` 已实现完整自动投递链（spawn_background → _notify_on_complete watcher → mailbox 投递 → SubAgentCompleteEvent(background=True) → terminal.interrupt_input() → _handle_background_delivery 触发 agent loop），但需显式加参。两模式功能实质重叠：前台除"需要手动 wait"外无任何额外价值——它是自动投递实现前的权宜设计，投递做好后默认行为没跟着改。真实使用中用户 spawn 后总要多输一步 wait（本任务即由用户实际使用时的困惑触发："我记得有一个问题是 spawn 的时候可以让结果主动返回……难道还没解决掉吗"——功能其实早已存在，只是没成为默认）。

## 106.2 方案

语义反转，改动收敛在 `_make_spawn` 一个函数：

- 单任务与 `-p` 并行的默认分支统一改调 `spawn_background`（原 background 专用分支合并删除）。`spawn_background` 签名本就支持 isolation/agent_type/context_summary 透传——subagent.py 零改动
- `--background` 解析保留但变 no-op 别名：向后兼容，脚本/肌肉记忆不炸
- `--wait` 保持阻塞式 opt-in：进度面板（SubAgentBoard）+ 内联返回完整格式化结果——语义反转前 --background 是 opt-in，反转后 --wait 是 opt-in
- 不变：`--pane`（独立进程模式，结果仍走 /spawn wait 或 --wait 收集）、`wait`/`list`/`cancel` 子命令（wait 仍服务 pane 收集与手动阻塞）、`--type`/`--fork`/`--isolated` 全部透传
- usage 文本与注册 description 同步新默认

## 106.3 诚实边界

两条路径的**输出保真度不同**：自动投递的结果经 mailbox 消息进入对话、由 LLM 转述给用户，且投递内容截断 4000 字符（NOTIFY_MAX_CHARS）；`--wait` 直接内联返回未经 LLM 转述的完整格式化结果（8000 字符 cap + worktree 合并提示 + deliverable 提取）。需要完整/精确输出时用 `--wait`。spawn_agents LLM 工具的 background 参数不在本次范围（工具默认仍阻塞——LLM 调用方语义不同，等结果是常态）。

**远程模式的投递差异**：主动弹出依赖终端输入循环的 `interrupt_input()` 中断机制，远程模式（--remote）没有该循环——`RemoteTerminalAdapter.__getattr__` 委托到原 Terminal 安全无效，结果退化为"用户下一条消息时经 mailbox drain 送达对话"（`--background` 时代的既有行为，非本次引入；远程主动推送需 WS 层新事件类型，另行考虑）。

## 106.4 验证

4 个新测试（test_spawn_team.py，handler 级 + 真实 SubAgentManager/MockLLM）：无 flag 单任务走 spawn_background（_background_ids 注册+消息含 auto-delivered）/ -p 并行默认后台 / --background no-op 别名行为与默认一致 / --wait 仍阻塞内联返回结果（回归）。全量 1189→1193。

真实 LLM 终端验证已通过（日常动作级）：`/spawn 数一下项目里有几个md` 派发后**零手动输入**，终端自动弹 "Background agent 08501734 finished — processing result..."，主 LLM 转述结果并主动 glob 复核子 agent 计数（44 个 .md，还纠正了其分类明细的出入——自动投递路径"LLM 转述"的增值面）；`/spawn --wait 输出<随机串>` 阻塞后内联返回完整原始输出（回归）。

# §107 对照文档事实修正

## 107.1 问题

comparison-mewcode.md 三处陈述与实际不符（roadmap 文档过时清单登记）：① 把"无 TLS"单独列为 mini 对 mewcode 的劣势，但 mewcode 远程模式 TLS 与认证两者皆无、mini 反而有 token 认证——劣势表述漏掉了反超事实；② 称 mewcode hook 有"command/prompt/http/agent 四种动作"，实际 agent executor 是 stub；③ "mewcode 13 文件 vs mini 3 文件"的团队系统对比双边都过时。

## 107.2 修正与复验

实施前对 mewcode 源码（本地 mewcode-python）逐条重新核实，不盲信登记时的旧结论：

- **远程认证**：`grep -i "tls|token|auth" mewcode/remote.py` 命中 4 处——逐行检查全部是 `inputTokens`/`outputTokens` LLM 计数，非认证。结论成立：mewcode 无任何认证。comparison 5.2 局限行与 roadmap 已知限制行改为"无 TLS 加密但有 token 认证（常量时间比较）；认证维度 mini 反超（mewcode 两者皆无）"。
- **hook 动作**：`hooks/executors.py` 实测含 "agent executor not yet implemented" stub。comparison 7.2 改为"三种可用 + agent stub"，同时**诚实降级** mini 侧论证：原文"EventBus 订阅者覆盖观察类，不重复建设"只半成立——能力可达但需写 Python，mewcode 是零代码 YAML + 条件表达式引擎（==/!=/=~/~= + and/or）；零代码声明式 hook 列为可选补齐方向。
- **团队文件数**：mewcode teams/ 实测 15 文件 2069 行（与登记一致）；mini 侧重新实测为 **8 文件 2055 行**（登记时估"约 7"漏了 agent_type_loader）。改为按实测数字陈述，并指出两者体量已持平、真实差异在组织方式（常驻队友 vs 一次性 worker）。

## 107.3 验证

纯文档修正，无代码改动，测试计数不变（1193）。三条修正的数据来源均为实施当日对 mewcode 源码/mini 源码的直接实测命令输出，非转录旧文档。

## 107.4 衍生发现

本次修正过程暴露两个真实改进方向，已详细登记 roadmap 待做：① 零代码声明式 hook 增强（hook 论证诚实降级暴露的差距：自定义 command/notify 动作 + 条件表达式引擎，command 动作须走既有权限管道的安全设计是关键）；② 远程模式 TLS 支持（认证对比暴露的自身短板：token 在明文信道传输打折认证价值——轻方案反代文档化优先，原生 TLS 视公网部署需求再做）。后续追查 mewcode 远程实现细节又发现：其默认绑定 `0.0.0.0:18888` 监听所有网卡且 CLI 无参数可改，叠加无认证——局域网任何设备可直连完全控制 agent；mini 默认 localhost/可配/可选 token，安全姿态四项中三项反超（均已补录 comparison 与 TLS 待做条目的对比参照）。

随后应用户要求做了 mewcode **全模块面对照扫描**（146 文件 23209 行全量清点 + teams/hooks/memory/TUI/agent 五子系统深挖，双侧源码逐项核实），产出完整差距清单并全部登记 roadmap：完全缺失 4 项（`-p` 非交互模式+NDJSON、发送侧 extended thinking 控制、MCP native 延迟加载、SyntheticOutput 结构化输出——各自单列登记）、程度差距 4 项（检查点选择性恢复、后台整固节律+并行 recall 预取合并一条、worktree 重目录软链单列）、UX 小项 4 个打包一条——共 8 条新待做（首轮登记漏了 SyntheticOutput 与 worktree 软链两条，经用户核对指出后补登）。零代码 hook 待做条目以实测细节增援（15 事件/async/once/reject 修饰符/prompt 动作注入 system prompt + mewcode 自身 TUI 路径不触发 hook 的残缺）。同时确认 mewcode 自身多处脚手架未接线（teammate transcript 无调用方、md 自定义命令 loader 未挂接、多 provider 只用第一个），常驻队友"暂不做"论证获增援。mini 反超面复核确认：成本追踪/多模型热切换/远程安全/崩溃恢复/record-replay/审计链/插件生态/Windows 沙箱/会话管理。
