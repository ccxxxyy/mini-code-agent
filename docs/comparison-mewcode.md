# Mini-Code-Agent vs MewCode-Python 详细对比与增强路线

本文档逐维度对比 mini-code-agent 与 [mewcode-python](https://github.com/xiaolincoding/mewcode-python) 的功能差异，并为每一个 mini **弱于** mewcode 的方面给出具体的增强方案。

---

## 零、基础框架对比

### 0.1 代码规模与语言

| | mini-code-agent | mewcode-python |
|---|---|---|
| 源码行数 | ~14,000 行 | ~15,000+ 行 |
| Python 版本 | 3.11+（用 tomllib、StrEnum 等 3.11 特性） | 3.12+（用 type 语法） |
| 注释 | 全部中英双语（336 条） | 英文为主 |
| 代码风格 | ruff（line-length 100, target py311） | ruff |

**差距**：代码量已接近（14,000 vs 15,000+）——剩余差距主要在 TUI 框架（Textual vs 手拼）和多 Agent 团队系统（mewcode 13 个文件 vs mini 3 个）。

**增强方向**：代码量不是目标——功能对齐后代码自然会增长。不追求行数对等，追求每个维度不弱于。

### 0.2 TUI 框架

| | mini | mewcode |
|---|---|---|
| 渲染 | **Rich**（Console/Panel/Live/Markdown） | **Textual**（Rich 之上的完整 TUI 框架） |
| 输入 | **prompt_toolkit**（补全/工具栏/历史） | Textual 内置 TextArea 组件 |
| 布局 | 手动拼（print 顺序控制） | CSS 驱动布局（.tcss 样式表） |
| 组件 | 流式渲染器/diff 预览/进度面板 | 可折叠工具块/内联对话框/进度树/权限弹窗 |
| 分屏 | 无 | Textual 原生支持 |
| 主题 | 3 套（default/dark/light），代码定义 | CSS 主题，支持自定义 |

**差距**：Textual 是完整的 TUI 框架（类似终端里的 React），组件化程度高、布局灵活；mini 是 Rich + prompt_toolkit 手动拼接。

**增强方案**：
不建议迁移到 Textual——这是架构级重写（~2000 行 app.py 要全部重来），且 mini 的设计哲学是"最小依赖、可读性优先"。Rich + prompt_toolkit 能实现所有需要的功能。

在现有框架上补齐体验差距：
1. **可折叠工具调用块**：工具调用默认显示简略版（`╭─ read_file file_path=x.txt → ✓ 42 lines`），`/trace on` 时展开详情。当前已基本实现，只需微调格式
2. **内联权限对话框**：当前 `confirm()` 已是 Panel 形式，效果等同 mewcode 的 InlinePermissionWidget
3. **进度树**：`/team` 和 `/spawn` 已有进度面板显示，效果已对齐

### 0.3 依赖策略

| | mini | mewcode |
|---|---|---|
| LLM SDK | **零 SDK**——httpx 直接调 API | `anthropic` + `openai` 两个官方 SDK |
| 配置 | **tomllib**（Python 3.11 内置，零依赖） | `pyyaml`（第三方） |
| 参数校验 | **dataclass** + **pydantic**（工具参数） | `pydantic`（第三方） |
| TUI | Rich + prompt_toolkit（2 个） | Textual（1 个，但更重） |
| MCP | httpx 手写 JSON-RPC | `mcp` 官方 SDK |
| HTTP | httpx | httpx |
| WebSocket | 无 | `websockets` |
| 总第三方依赖 | **4 个**（httpx/rich/prompt_toolkit/pydantic） | **7 个**（anthropic/openai/pyyaml/pydantic/mcp/textual/websockets） |

**差距**：mini 的依赖更少更轻——这是**有意的设计取向**，不是弱点。零 SDK 意味着：
- 不受 SDK 版本更新的破坏性变更影响
- 安装快（pip install 秒装 vs SDK 拖一堆传递依赖）
- 用户可以审计全部代码（14,000 行 vs 15000 行 + SDK 黑盒）

**增强方向**：保持最小依赖原则。Pydantic 已引入用于工具 Schema 自动生成（P46），如后续需要 websockets（远程模式）按需单独引入。

### 0.4 配置系统

| | mini | mewcode |
|---|---|---|
| 格式 | **TOML**（Python 3.11 内置 tomllib） | YAML（需 pyyaml） |
| 层级 | **7 层优先级**：CLI > 环境变量 > .env > 项目 config.toml > 用户 config.toml > 代码默认 | 3 层：用户 > 项目 > 项目本地 |
| 环境变量解析 | 直接读 `os.environ` | YAML 内 `${VAR}` 语法 |
| .env 自动加载 | ✅ | ❌ |
| 合并策略 | `_merge` 通用递归合并 | 手动 `dict.update` |

**差距**：mini 的配置系统**更强**——7 层优先级 vs 3 层，且支持 .env 自动加载。TOML 也是更现代的选择（Python 3.11 内置 vs YAML 需要第三方库）。

**结论**：此维度 mini 已 ≥ mewcode，无需增强。

### 0.5 项目构建与发布

| | mini | mewcode |
|---|---|---|
| 构建工具 | **hatchling**（PEP 517） | hatchling |
| PyPI 发布 | ✅ `pip install mini-code-agent` | ❌ 未发布 |
| CI/CD | GitHub Actions（Lint + Test + Build） | 无 |
| 发布方式 | **Trusted Publisher**（tag 触发，零 secret） | — |
| 测试 | **793 测试，80%+ 覆盖率，fail_under=80** | 27 个测试文件，覆盖率未知 |

**差距**：此维度 mini **明显更强**——已发布 PyPI、有 CI/CD、测试数量是 mewcode 的 15 倍以上、有覆盖率门禁。

**结论**：此维度 mini 已 >> mewcode，无需增强。

### 0.6 事件/解耦架构

| | mini | mewcode |
|---|---|---|
| 事件系统 | **EventBus**（5 个订阅者：Trace/Teach/Audit/Recorder/Cost） | 无独立事件总线（组件间直接回调） |
| 解耦程度 | 五层架构通过 EventBus 解耦，单向依赖 | 组件间直接引用较多 |
| 观测能力 | `/trace`、`/explain`、`/audit` 三个独立观测维度 | `/trace` |

**差距**：此维度 mini **更强**——EventBus 发布-订阅模式让新增观测能力零耦合（加一个订阅者即可），mewcode 的观测需要改核心代码。

**结论**：此维度 mini 已 > mewcode，无需增强。

### 0.7 文档体系

| | mini | mewcode |
|---|---|---|
| 文档数量 | **13 个专题文档** + README 双语 | MEWCODE.md（项目说明）+ 配置示例 |
| 架构文档 | agent-architecture.md（S01-S20 逐层解析） | 无 |
| 技术笔记 | tech-notes.md（58 个部分，设计决策记录） | 无 |
| 配置指南 | config-guide.md（全配置文件说明） | config.yaml.example |
| 命令参考 | commands-guide.md（22 个命令完整语法/参数/示例） | 无 |
| 终端指南 | terminal-guide.md（各系统各终端） | 无 |
| 实验报告 | experiments/README.md（3 个实验完整数据） | 无 |
| 能力对照 | capabilities.md（18 项需求逐条证据） | 无 |
| 开发历史 | tasks.md（P1-P58 完整记录） | 无 |

**差距**：此维度 mini **远超** mewcode。

**结论**：此维度 mini 已 >> mewcode，无需增强。

---

## 一、LLM 集成

### 1.1 Provider 支持 ✅ Responses API 已实现

| | mini-code-agent | mewcode-python |
|---|---|---|
| OpenAI 兼容（Chat Completions） | ✅ | ✅ |
| Anthropic 原生 | 代码就绪，未 E2E 验证 | ✅ 完整验证 |
| OpenAI Responses API | ✅ `provider = "openai-responses"` | ✅ |

**已完成**（Responses API）：
- `llm/openai_responses_provider.py` — 完整实现，零 SDK（httpx 直连，mewcode 依赖 `openai` SDK）
- 消息转换：system → `instructions` / user/assistant → typed input items / tool_calls → `function_call` / tool → `function_call_output`
- 工具 schema 扁平化：`{function: {name, params}}` → `{name, parameters}`
- SSE 事件解析：text delta / reasoning summary delta / function_call start/args delta / completed（用量 + finish_reason 推断）/ incomplete → "length"（触发 max_tokens 恢复）
- 用量：`input_tokens_details.cached_tokens` 正确提取；`max_tokens` → `max_output_tokens` 映射
- 上下文窗口探测 + 推理模型表（默认 200k）
- 429/5xx 退避重试（共享基础设施）
- **Thinking round-trip**（mewcode 差距补齐）：agent_loop 累积 thinking 存入 Message.metadata → `_convert_to_input` 发出 `{type: "reasoning", id, summary}` 项回传 API，o1/o3 多轮对话推理过程不丢失
- **Tool pairing repair**（mewcode 差距补齐）：消息转换时跟踪未配对的 function_call，补合成 "interrupted" 结果——中断后继续对话不再 400 报错
- **错误分类**（mewcode 差距补齐）：401 → `LLMAuthenticationError` / 429 → `LLMRateLimitError`（含 retry_after）/ 连接超时 → `LLMNetworkError`
- 26 个单测（消息转换含 thinking round-trip/tool pairing/事件解析/assemble 集成/窗口/注册/错误分类）

**与 mewcode 的最终对比**：mini 在 7 项上超出（temperature/max_output_tokens/incomplete 事件/failed 事件/内置重试/动态窗口探测/并行工具追踪/零 SDK），mewcode 的 3 项差距（thinking round-trip/tool pairing/错误分类）已全部补齐，`function_call_arguments.done` 是纯风格差异不计入

**仍待做**（1.1 节内）：Anthropic Provider E2E 验证（需 API key）

### 1.2 Prompt 缓存 ✅ 已实现（P37）

| | mini | mewcode |
|---|---|---|
| Anthropic prompt caching | ✅ **三处 cache_control 标记**（系统提示 + 最后工具 + 最后用户消息）+ 缓存命中统计 | ✅ `cache_control: ephemeral` |

**原差距**：mini 每次请求都全价计费。P37 已实现，Anthropic 用户输入 token 成本降约 90%。

**增强方案**：
在 Anthropic Provider 的消息构造中，给以下三处加 `cache_control: {"type": "ephemeral"}`：
- 系统提示（system prompt）
- 工具 schema 列表的最后一个工具
- 最后一条用户消息

代码改动量：`llm/anthropic_provider.py` ~10 行。效果：系统提示和工具 schema 只在首次请求完整传输，后续请求命中缓存——**Anthropic 用户的输入 token 成本降低约 90%**。

### 1.3 上下文窗口探测 ✅ 已实现（P42）

| | mini | mewcode |
|---|---|---|
| 窗口大小获取 | ✅ **3 层回退**：API `/models/{model}` 探测 → 内置表 → 128k 默认值；递归提取 5 种字段名（context_window/context_length/max_context_length/max_model_len/max_input_tokens），兼容任意深度嵌套 | 4 层回退：配置 → API `/v1/models` 查询 → 内置表 → 默认值 |

**原差距**：新模型上线后 mini 需要手动更新代码里的表。P42 已实现：`LLMProvider.prepare()` 预热钩子在启动时（`app.run()`）和 `/model` 切换后触发探测，`stream()` 入口兜底；每实例只探测一次，失败静默回退。真实 API 实测（阿里云 MaaS 三个模型）均成功探测到 129024——窗口值藏在 `extra_info.default_envs.max_input_tokens` 深层嵌套里，正是递归提取要解决的场景。

### 1.4 流式工具执行 ✅ 已实现（P38）

| | mini | mewcode |
|---|---|---|
| 工具执行时机 | ✅ **边流式边执行**——IncrementalAssembler 检测组装完成立即提交（index 前进/finish_reason 双信号），需确认的工具延迟到流后；`streaming_tool_execution` 可关 | 边流式边执行——工具调用事件一完成就提交 |

**原差距**：LLM 一次返回 3 个工具调用时，mini 等全部解析完才执行。P38 已实现——第一个工具调用组装完成即执行，第二个还在流式传输时第一个已在跑。

**增强方案**：
在 `agent_loop.py` 的 `_think()` 方法中，引入 `StreamingExecutor`：
1. 流式解析 tool_call_deltas 时，每当一个完整的 tool_call 组装完成，立即提交到 executor
2. executor 内部用 asyncio.Task 异步执行（并发安全的工具直接跑，需确认的延后）
3. `_think()` 返回时，所有已提交的工具已在执行或已完成
4. `_act()` 只需收集结果

代码改动：`core/agent_loop.py` ~50 行重构。需要注意权限确认的工具必须延后到流式结束后串行弹窗。

### 1.5 max_tokens 恢复 ✅ 已实现（P44）

| | mini | mewcode |
|---|---|---|
| max_tokens 截断处理 | ✅ 检测 `finish_reason="length"` 自动翻倍重试（最多 3 次），仍截断保留最后结果 | 检测到 `stop_reason=max_tokens` 自动提升限制重试（最多 3 次） |

**原差距**：LLM 生成的回答超出 max_tokens 时被截断，mini 把不完整的回答直接展示。P44 已实现：

1. `_think()` 的重试循环：`finish_reason == "length"` 时把 max_tokens 翻倍（4096 → 8192 → 16384 → 32768）重发，最多 3 次，仍截断保留最后一次结果
2. 两家 Provider 的 `stream()` 支持 `max_tokens` kwargs 覆盖配置值；Anthropic 的 `stop_reason="max_tokens"` 归一化为 OpenAI 的 `"length"`，恢复逻辑两家通用
3. 细节：重试前取消截断尝试中流式提交的工具任务（参数可能在 JSON 中途被切断）；用户取消（Esc）时不重试

---

## 二、工具系统

### 2.1 工具 Schema 生成 ✅ 已实现（P46 + P47）

| | mini | mewcode |
|---|---|---|
| Schema 定义方式 | **Pydantic model** 自动生成 JSON Schema（P46），Raw Passthrough 全量保留（P47） | **Pydantic model** 自动生成 JSON Schema |

**已完成**（P46）：7/10 个工具定义 `ParamsModel(BaseModel)`，`Tool.params_model` 属性 + `_schema_from_model()` 自动生成。BashTool 保留手写 schema 向后兼容。

**已完成**（P47 增强）：`_schema_from_model()` 重写为 Raw JSON Schema Passthrough——Pydantic `model_json_schema()` 输出经 `_resolve_refs()` 解引用 `$ref/$defs`、去除 `title` 噪声后，完整 JSON Schema dict 直接存入 `ToolSchema.raw_parameters`，`to_json_schema()` 优先使用。全面支持：
- `str | None`（anyOf）、`list[str]`（array + items）、嵌套 BaseModel（$ref 解引用内联）
- `Field(ge=0, le=100)` 约束（minimum/maximum/minLength/maxLength）
- `Literal["a","b"]`（enum）、`dict[str, int]`（additionalProperties）
- `default` 值输出、循环引用防护

### 2.2 `@file` 引用 ✅ 已实现（P39）

| | mini | mewcode |
|---|---|---|
| 输入框文件引用 | ✅ **`@README.md` 自动内联 + Tab 补全**（10KB 上限截断，子目录路径支持，跳过 .git 等） | ✅ `@README.md` 自动内联文件内容 |

**原差距**：用户想让 LLM 看某个文件，要浪费一轮工具调用。P39 已实现。

**增强方案**：
1. 在 `ui/input_handler.py` 的 `SlashCommandCompleter` 中，识别 `@` 开头的输入
2. 补全器列出当前目录文件（用 glob）
3. 用户提交时，`app.py` 扫描消息中的 `@filepath` 模式，读取文件内容，拼接到用户消息末尾：`\n\n--- @README.md ---\n{file_content}\n---`
4. 补全提示使用 prompt_toolkit 的 `WordCompleter`，`@` 触发

代码改动：`ui/input_handler.py` ~30 行 + `app.py` ~15 行。

### 2.3 工具搜索/延迟加载 ✅ 已实现（P51）

| | mini | mewcode |
|---|---|---|
| MCP 工具加载策略 | **两种策略**：eager（默认，全部注册）/ dispatch（按需搜索+调用）(P51) | **三种策略**：EAGER / DISPATCH / NATIVE |

**已完成**（P51）：
- `MCPServerConfig.loading = "eager" | "dispatch"` 配置选项
- `MCPManager._dispatch_tools` shadow catalog：dispatch 模式工具不注册到 ToolRegistry
- `tool_search` 新工具：LLM 按关键词搜索 dispatch 工具的 name/description，返回完整 schema
- `mcp_call` 新工具：LLM 调用 dispatch 模式发现的工具（server + tool + arguments）
- `ToolContext.mcp_manager` 字段注入
- 10 个内置工具（原 8 + tool_search + mcp_call）

---

## 三、安全/权限

### 3.1 OS 级沙箱 ✅ 已实现（P41）

| | mini | mewcode |
|---|---|---|
| 沙箱隔离 | ✅ **Linux bubblewrap + macOS Seatbelt**（只读 rootfs + 可写白名单 + 可选禁网）+ sandbox_auto_allow（沙箱下危险命令免确认，deny 规则仍拦）；Windows 无内核沙箱退回正则 | ✅ Linux bubblewrap + macOS Seatbelt 内核级隔离 |

**原差距**：最大安全差距——正则匹配可被绕过。P41 已实现双平台内核沙箱。

**增强方案**：
1. 新建 `security/sandbox/` 目录
2. `bwrap_sandbox.py`（Linux）：用 `subprocess` 执行 `bwrap --ro-bind / / --bind {working_dir} {working_dir} --dev /dev --proc /proc -- {command}`——子进程看到只读根文件系统，只有工作目录可写
3. `seatbelt_sandbox.py`（macOS）：生成 SBPL profile 文件，用 `sandbox-exec -f profile.sb {command}`
4. `bash.py` 工具执行命令时，检查 `config.security.sandbox` 配置，如果启用则通过沙箱执行
5. Windows 无内核沙箱——保持现有正则拦截（Windows 的 Job Objects/AppContainers 复杂度过高）

代码改动：新增 2 个文件 ~100 行/个 + `bash.py` ~10 行集成。配置：`[security] sandbox = true`。

### 3.2 权限规则文件 ✅ 已实现（P40）

| | mini | mewcode |
|---|---|---|
| 权限规则定义 | ✅ **TOML 规则文件**（用户级 `~/.mini-agent/permissions.toml` + 项目级 `.mini-agent/permissions.toml`）+ 内置默认；顺带修复了 PATH deny 被项目内放行短路的盲区 | YAML 规则文件（用户级 + 项目级 + 本地三层） |

**原差距**：用户无法定制权限规则——想加一个"允许 docker build"要改代码。P40 已实现，见 permissions.toml.example。

**增强方案**：
1. 支持 `~/.mini-agent/permissions.toml`（用户级）和 `.mini-agent/permissions.toml`（项目级）
2. 文件格式：
   ```toml
   [commands]
   allow = ["docker build *", "npm run *"]
   deny = ["docker rm *"]

   [paths]
   allow = ["/tmp/workspace/**"]
   deny = ["~/.ssh/*"]
   ```
3. `PermissionManager` 加载时合并：代码内置规则 < 用户级规则 < 项目级规则
4. 现有的 `DANGEROUS_COMMAND_PATTERNS` 和 `SENSITIVE_PATTERNS` 仍作为内置默认值

代码改动：`security/permission.py` ~40 行。

### 3.3 Plan 模式只读权限 ✅ 已实现（P49）

| | mini | mewcode |
|---|---|---|
| Plan 模式权限 | **物理只读**——`/plan` 开启后 write/edit/delete schema 隐藏 + 调用拦截双保险 (P49) | **物理只读**——Plan 模式下 write/edit/bash 工具被禁用 |

**已完成**（P49）：
- `AgentLoop.plan_mode: bool` — 运行时切换
- `_think()` 过滤 `_WRITE_TOOLS` schema → LLM 看不到写工具
- `_act()` 双保险拦截 → 即使幻觉调用也返回 Permission denied
- 流式工具执行也延迟写工具到 `_act()` 拦截
- `/plan [on|off]` 命令切换 + system prompt 注入只读提示
- bash 保留（由权限系统和沙箱控制危险命令）

---

## 四、上下文/记忆管理

### 4.1 大工具结果溢写磁盘 ✅ 已实现（P36）

| | mini | mewcode |
|---|---|---|
| 大文件处理 | ✅ **>50K 字符溢写磁盘，对话留 2000 字符预览**（`memory/tool_result_cache.py`，SubAgent 同样受保护——mewcode 的溢写不覆盖子代理） | >50K 字符的结果存磁盘，对话只留摘要 |
| 聚合预算 | ✅ **单轮累计超 200K 字符时按大小降序强制溢写**（P64.1 `spill_batch`，跨迭代累计）+ 三配套：读回豁免 `is_spill_readback` / 预览 2000 / 小结果豁免 | `apply_tool_result_budget`：单批总量超 `AGGREGATE_CHAR_LIMIT=200K` 时降序溢写 |

**原差距**：曾是 mini 唯一的高严重度遗留问题（tech-notes 34.3 ③）。用户说"读 spec.md"（大文件），内容全进对话→触发压缩→LLM 忘了读过→重读→再压缩→循环烧 token。P36 已修复，实现见 tech-notes §36。

**增强方案**：
1. 新建 `memory/tool_result_cache.py`
2. 工具执行后检查结果长度，>50K 字符时：
   - 结果存入磁盘缓存（`~/.mini-agent/cache/result_{hash}.txt`）
   - 对话中替换为摘要：`[File content cached to disk (52,341 chars). First 2000 chars: ...]`（预览 P64.1 起为 2000，原方案 500）
3. 后续 LLM 需要该内容时可用 `read_file` 重新读取（文件本身没变，不需要缓存里的副本）
4. 会话结束时清理缓存

代码改动：新增 `memory/tool_result_cache.py` ~50 行 + `core/agent_loop.py` _act() ~10 行集成。

### 4.2 压缩后恢复 ✅ 已实现（P36）

| | mini | mewcode |
|---|---|---|
| 压缩后状态恢复 | ✅ **压缩后在摘要注入已读文件清单**（`ContextManager._inject_read_files()`，二次压缩自动替换旧清单） | 摘要后重新挂载最近读过的文件列表和激活的 skill |

**原差距**：压缩后 LLM 不知道自己读过哪些文件，导致重读。P36 已修复，实现见 tech-notes §36。

**增强方案**：
1. 在 `ContextManager` 中维护 `_recently_read_files: list[str]`
2. 每次 `read_file` 工具执行时记录文件路径
3. 压缩后，在摘要消息末尾追加一行：`Files already read this session: spec.md, tasks.md, config.py`
4. LLM 看到这行就知道不需要重读

代码改动：`memory/context.py` ~15 行 + `core/agent_loop.py` ~5 行记录。

### 4.3 Token 计数精度 ✅ 已实现（P43）

| | mini | mewcode |
|---|---|---|
| Token 计数方式 | ✅ **API usage 锚点** + CJK 感知估算混合：API 返回的权威总量锚定在最新消息，只对锚点后的新消息估算 | **真实 API usage** + 新消息字符估算混合 |

**原差距**：`len // 4` 对中文严重不准（一个汉字 1 char 但 ~1 token，低估 4 倍），导致压缩阈值判断偏差。P43 已实现：

1. **API usage 锚点**（`memory/context.py`）：每轮 LLM 响应后 `record_api_usage()` 把 `usage` 总量锚定在最新消息上——prompt_tokens 覆盖 API 实际计费的一切（系统提示、全部消息、工具 schema），比任何估算都准。`update_total()` 用锚点总量 + 锚点后新消息的估算；对象身份检查让压缩/undo 重排历史后锚点自动失效回退全量估算
2. **CJK 感知估算**（`llm/token_counter.py`）：按字符统计——CJK 字符（汉字/假名/谚文/全角符号）1 token/字，其余 4 字符/token；比原方案的"占比 >30% 则 len//2"更准且无阈值跳变。真实 API 实测校准：中文从 -56% 低估（危险方向）修正为 +76% 高估（安全方向——低估导致压缩不触发直至崩溃，高估只是压缩稍早），混合文本 +12%
3. **顺带修复两个真实 bug**：①assistant 消息的 `token_count` 原来存 `usage.total_tokens`（含整个 prompt），按消息累加会把对话重复算 N 遍——改存 `completion_tokens`（消息自身大小）；②`assemble_response` 的 usage 直接覆盖，Anthropic 把 prompt/completion 拆在两个事件里会丢 prompt 计数——改按字段合并

### 4.4 选择性记忆召回 ✅ 已实现（P52）

| | mini | mewcode |
|---|---|---|
| 记忆注入方式 | **LLM 选择性召回**——记忆 >10 条时 LLM 挑最相关的 ≤5 条注入 (P52) | **LLM 选择性召回**——先让 LLM 挑最相关的 ≤5 条 |

**已完成**（P52）：
- `memory/recall.py` 新模块：`MemoryRecall.select_relevant()`——轻量 LLM 调用挑选相关记忆
- 召回 prompt：所有记忆的 `id + content 前 50 字符` + 用户最新消息 → LLM 返回相关 ID 的 JSON 数组
- `MemoryConfig` 新增 `recall_threshold=10` / `recall_top_k=5` 配置
- ≤ threshold 时保持现有行为（全部注入，零额外调用）
- fail-safe：LLM 失败/解析失败/幻觉 ID → 静默回退头部截断 `entries[:10]`
- 保持 LLM 返回的相关性排序注入

### 4.5 记忆合并 ✅ 已实现（P53）

| | mini | mewcode |
|---|---|---|
| 重复记忆处理 | 60% 词重叠去重（提取时预过滤）+ **LLM 语义合并**（超阈值触发）(P53) | **LLM 语义合并**——自动把相关记忆整合成一条 |

**已完成**（P53）：
- `memory/consolidation.py` 新模块：`MemoryConsolidator.consolidate()`——LLM 识别语义相关的记忆组并合并
- 触发点：`MemoryExtractor.maybe_extract()` 末尾，记忆 > `consolidation_threshold`（默认 20，可配置）
- 合并规则：保留组内最新 `created_at`、tags 并集、source="extracted"、未合并条目原样保留
- 防护：幻觉 ID 过滤、单 ID 组忽略、跨组重复 ID 只处理首组、fail-safe 静默 no-op
- `/memory consolidate` 手动触发子命令（无阈值限制，≥2 条即可跑）

### 4.6 记忆存储格式 ✅ 已实现（P61：导出/导入互操作）

| | mini | mewcode |
|---|---|---|
| 存储格式 | 单个 `memory.json` 文件（内部）+ ✅ **`/memory export`/`import` 互操作 .md 格式**（P61） | **独立 .md 文件 + YAML 前置元数据 + MEMORY.md 索引** |

**已完成**（P61）：
1. `memory/interop.py` 新模块：`export_memories()` 每条记忆一个 `{id}.md`（YAML 前置元数据：id/source/scope/created_at/tags）+ MEMORY.md 索引；`import_memories()` 容错解析返回 `(entry, scope)` 对
2. `/memory export [dir]` —— 导出项目 + 用户全部记忆，默认目录 `.mini-agent/memory-export/`（无项目时 `~/.mini-agent/memory-export/`）
3. `/memory import <dir>` —— 按 id 去重导入，按 `scope` 前置元数据路由回项目/用户存储
4. 容错导入：无前置元数据的纯 .md、mewcode 风格前置元数据（name/description/metadata 嵌套）、未闭合前置元数据、正文为空取 description、tags 逗号分隔回退——均可导入
5. JSON 仍是内部存储格式，.md 仅作互操作/浏览层

**实测暴露的设计点**：mini 的 `MemoryEntry.source`（"user"/"extracted"）记录的是**谁创建的**，不是**存在哪里**——`/memory add` 进项目库的条目 source 也是 "user"。第一版按 source 路由导致跨机导入时项目记忆错进用户库；修复为导出时显式写 `scope` 前置元数据（project/user），导入按 scope 还原。

### 4.7 压缩双阈值 ✅ 已实现（P65）

| | mini | mewcode |
|---|---|---|
| 压缩阈值 | ✅ **双阈值**——软阈值（默认 75%）受熔断器控制 + 硬阈值（默认 90%）绕过熔断器强制完整级联压缩 (P65) | **双阈值**——`auto_compact_safety_margin`(13K) 触发正常压缩 + `manual_compact_safety_margin`(3K) 触发强制压缩绕过熔断器 |

**已完成**（P65）：
- `MemoryConfig.hard_compression_threshold = 0.90`：独立配置，默认 90%
- `check_and_compress()` 熔断器检查加 `and not self.needs_hard_compression`：软阈值被熔断器阻断时，硬阈值仍走完整三级级联（DropToolResults → SummarizeOldest → SlidingWindow），避免只剩 `ensure_fits` 的粗暴截断
- `/status` 显示 `soft=75% hard=90% breaker=0/3`，硬阈值触发时 WARNING 日志明确标识
- 默认 128K 窗口下：96K 触发软压缩，115K 触发硬压缩

---

## 五、TUI / 终端

### 5.1 TUI 框架

| | mini | mewcode |
|---|---|---|
| 框架 | Rich + prompt_toolkit 手动拼 | **Textual**（完整 TUI 框架，组件/布局/CSS） |

**差距**：mewcode 有完整的 UI 组件（可折叠工具块、内联权限对话框、进度树），mini 的 UI 相对简单。

**增强方案**：
不建议迁移到 Textual——这是架构级重写，且 mini 的设计哲学是"最小依赖、可读性优先"。Rich + prompt_toolkit 组合足够实现所有功能。

替代方案：在现有框架上补齐缺失的 UI 组件：
1. **可折叠工具调用块**——Rich Panel + 用户按键切换展开/折叠（`/trace on` 已有类似信息，改为默认显示简略版、Ctrl+O 展开详情）
2. **内联权限对话框**——当前的 `confirm()` 已经是 Panel 形式，足够好

### 5.2 远程/浏览器模式 ✅ 已实现（P57）

| | mini | mewcode |
|---|---|---|
| 远程访问 | ✅ `--remote` WebSocket 服务器 + 嵌入式浏览器 UI (P57) | ✅ WebSocket 服务器 + 浏览器 UI |

**已完成**（P57，经代码验证）：

架构：
- `remote/server.py` — RemoteServer：单端口 WebSocket 服务器，通过 `process_request` 回调复用——GET `/` 返回 HTML 页面，`/ws` 路径升级为 WebSocket 连接（事件推送 + 双向消息）
- `remote/web_ui.py` — 嵌入式 HTML+CSS+JS 浏览器前端（`build_html()` 返回自包含页面，零外部依赖）
- `remote/terminal.py` — RemoteTerminalAdapter：拦截 `show_info`/`show_error`/`show_file_changes` 三个方法转发到浏览器
- `cli.py` — `--remote` / `--port` / `--host` 三个 CLI 参数

NDJSON 协议（12 种服务端事件 + 3 种 WS 客户端消息）：
- 服务端事件：`turn_start` / `turn_end` / `stream_start` / `stream_text` / `stream_end` / `thinking_delta` / `tool_call` / `tool_result` / `permission_request` / `info` / `error` / `file_changes`
- WS 客户端消息：`user_input` / `cancel`（通过 WS 消息设置 `agent_loop._cancelled`，即时生效）/ `permission_response`（通过 `loop.call_soon_threadsafe` 线程安全解析 asyncio.Future）

浏览器 UI 功能：
- 深色主题（Catppuccin Mocha 色系）
- 流式文本渲染 + Markdown 渲染（h1-h4 标题、**粗体**、`代码`、代码块、有序/无序列表、表格）
- 工具调用/结果显示（暗灰色低调样式）
- 权限确认对话框（Allow/Always/Deny 按钮，点击后高亮+禁用+左侧状态条反馈）
- Thinking 旋转指示器（荧光黄脉冲动画，工具调用间自动显示）
- 用户输入泡泡框（蓝色左边框 + 深灰背景，与输出明确区分）
- 欢迎引导（显示当前模型名 + 可切换模型数量）
- 斜杠命令自动补全下拉框
- 自动滚动（底部 300px 阈值，用户上滚时不抢夺，info 消息强制滚到底）
- Stop 按钮（WS 消息 `cancel`，即时生效）
- 自动重连（断线 2 秒后重试）
- `Cache-Control: no-cache` + meta 标签禁缓存
- 多行输入（textarea + Shift+Enter + auto-grow）
- 工具调用折叠（details/summary，默认展开）
- Token 用量显示（turn_end 附带 tokens）
- 工具耗时显示（tool_result 附带 elapsed）
- 动态命令列表（服务端发送，按字母排序）
- `<think>` 标签解析（渲染为折叠块）
- CSS 变量主题（18 个 CSS 变量）+ 主题切换（深/浅色，header 按钮 + localStorage + `/theme` 联动）
- 应用层 ping/pong（10 秒心跳）
- turn 完成摘要（iterations + elapsed + tokens）
- 重连状态优化（Reconnecting...）
- stream_end 携带完整文本

安全与容错：
- `websockets>=12.0` 可选依赖（`[remote]` 组），未安装时优雅报错
- 内部 Python 异常（AttributeError/TypeError/Traceback 等）不推送到浏览器
- 多连接竞态处理：`_ws_send()` 运行时读 `self._ws`（始终最新连接），旧连接退出不影响新连接

测试：
- 21 个单元测试覆盖：NDJSON 格式、权限 Future 流程、UI 构建、CLI 参数解析、终端适配器、StreamChunk.thinking 字段、Provider 解析 reasoning_content/thinking_delta、内部错误过滤、show_file_changes 类型修复

**仍存在的局限**（已确认）：
- 多客户端支持（`self._clients: set` 广播），但所有客户端共享同一会话（无独立会话）
- 无 TLS（明文 `ws://`）。可选 token 认证（`--remote-token`），未设时无认证
- 浏览器刷新可恢复对话历史（`_replay_history()`），但服务器重启后丢失（远程模式未接入 SessionStore）
- Markdown 图片仅支持公网 URL（本地文件路径因浏览器安全策略无法加载）

### 5.3 输入补全增强 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| `/` 命令补全 | ✅ | ✅ |
| `@file` 补全 | ✅（P39） | ✅ |
| 输入历史 | ✅ `FileHistory(~/.mini-agent/input_history)`，跨会话上下箭头浏览，失败退回内存 | ✅ 上下箭头浏览历史 |

此维度已全部对齐。

---

## 六、多 Agent

### 6.1 Coordinator 模式 ✅ 已实现（P45）

| | mini | mewcode |
|---|---|---|
| 主 Agent 角色 | ✅ `/team --coordinator`——Planner 纯调度（prompt 强制"只分解不操作"+ max_steps 放宽到 8 + 项目扫描加深到 3 级），Workers 保持完整工具集 | **Coordinator 模式**——主 Agent 纯调度，物理上不能读写文件 |

**原差距**：主 Agent 同时规划和执行时注意力容易分散。P45 已实现：

1. `/team --coordinator` 入口（同 `--isolated` 的 flag 解析模式）
2. Planner 收到 `_COORDINATOR_PREFIX` 指令："你是 COORDINATOR，只分解和分派，不能直接读写文件"——当前 Planner 已经是纯 LLM 调用（不是 AgentLoop），prompt 强化让职责分离显式化
3. coordinator 模式下 `max_steps` 放宽到至少 8（Coordinator 不能自己补漏，需要更细粒度分解）
4. 项目扫描从 2 级/80 行加深到 3 级/120 行——Coordinator 不能自己读文件，给更丰富的结构上下文
5. Workers 保持完整工具集，不受影响

### 6.2 跨 Agent 通信 ✅ 已实现（P58）

| | mini | mewcode |
|---|---|---|
| Agent 间通信 | ✅ **Mailbox 消息传递**——文件式收件箱 + `send_message` 工具，Agent 每轮 THINK 前 drain 收件箱 (P58) | **Mailbox 消息传递** + **共享 TaskStore** |

**原差距**：mini 的 SubAgent 是"派出去等结果回来"模式，Agent 之间不能中途交流。P58 已实现：

1. `core/mailbox.py`——基于文件的消息队列（`.mini-agent/mailboxes/<agent_id>.json`，每个 Agent 一个收件箱；`register` 总是重置收件箱，避免上一会话残留消息被投递）
2. `send_message` 工具——LLM 可发消息给指定 Agent（`'main'` = 主 Agent），收件人未注册时报错并列出已知 Agent
3. `AgentLoop` 每轮 THINK 前 `_deliver_mail()` drain 收件箱，消息以 `[Message from agent '<id>']` 前缀追加为 USER 消息
4. SubAgent 注册收件箱（uuid id），system prompt 追加 MAILBOX_NOTICE 告知自身 id 与通信方式；`run()` 结束后注销
5. `spawn_parallel` 预生成全部 agent id，MAILBOX_NOTICE 列出同伴 id **及各自任务摘要**（80 字符）——兄弟 Agent 既知道 id 也知道谁是什么角色（实测发现的缺口：只列 id 时 LLM 分不清哪个同伴是收件方，会幻觉 'agent-2' 之类的 id）
6. `wait_message` 工具——接收方阻塞等消息（轮询 0.5s，超时上限 600s），等待期间保持存活；超时返回信息而非报错。实测发现的缺口：接收方靠 bash sleep 磨蹭会提前结束、收件箱注销，慢速发送方投递时报 Unknown recipient
7. read-only agent 类型（explore/plan/verify）的工具白名单也包含 `send_message`/`wait_message`——收发消息不算写文件
8. 共享 TaskStore 已有（`core/task_store.py`），文件式按项目目录共享，无需额外改动

**mini 相对 mewcode 的原创补充**（源自架构差异，非照抄）：

- `wait_message` 等待原语——mewcode 的队友是常驻交互进程天然一直在收消息，不需要它；mini 的 SubAgent 是一次性任务，没有它接收方会提前结束（实测翻车后补上的）
- 未知收件人报错**列出已知 Agent**，LLM 可自行降级转发；mewcode 只回 "Cannot resolve recipient"
- `register` 总是重置收件箱，杜绝跨会话残留投递；mewcode 靠 `cleanup_all` 手动清

**与 mewcode 的四项差距 ✅ 已拉平（P58.4）**（曾逐项对照 `mewcode/teams/mailbox.py` + `protocol.py` + `registry.py` 记录，现全部实现）：

| # | 原差距 | mewcode 实现 | mini 实现（P58.4） |
|---|---|---|---|
| 1 | 无广播 | `to='*'` 一键广播全队（可 exclude 自己） | ✅ `Mailbox.broadcast()` + send_message `to='*'`，自动排除发送者，返回收件人列表 |
| 2 | 无结构化消息协议 | `type`（含 shutdown/plan_approval 等团队生命周期类型）+ `request_id` 配对 + `approve` 表态 | ✅ **mini 适配版**：通用 `type=text/request/response` + `request_id`（request 自动分配并回显）+ `approve`；投递前缀区分 `[Request ...]`/`[Response ...]`。诚实差异：mewcode 的 shutdown/plan_approval 类型服务**常驻队友**的生命周期管理，mini 的 SubAgent 是一次性任务，故采用通用请求-应答而非照搬团队类型 |
| 3 | 无名字寻址 | `AgentNameRegistry` 按名字或 id 解析 | ✅ `Mailbox.register(id, name)` 别名注册 + `resolve()` id/名字双解析；spawn_agents 新增 `names` 参数（唯一性/保留字校验），MAILBOX_NOTICE 显示 `'explorer' (id xxx, task: ...)` |
| 4 | 无审计痕迹 | 消息带 `read` 标记 consume 后留盘；`read()` 只窥视 | ✅ `drain` 标记已读并留盘（会话内可 cat 排查）；`unregister` 保留文件；新会话 `SubAgentManager` 初始化时 `reset_all()` 统一清理。诚实差异：审计是**会话级**的，mewcode 留存至手动 cleanup |

**架构边界的演进（P58.4 记录 → 6.4 实现时解除）**：

- ~~无锁设计只在单进程内成立~~ **✅ 已解除（6.4 前置）**：Mailbox 现已具备完整跨进程能力——O_EXCL 文件锁（指数退避带抖动 + 10s 陈旧锁接管 + 5s 超时）+ temp/os.replace 原子写 + 磁盘注册表 `_registry.json`。实测 4 进程并发写零丢失。实现细节见 6.4
- ~~无推送唤醒~~ **✅ 以轮询替代（有意的适配）**：mewcode 推送唤醒服务的是常驻交互队友；mini 的 pane worker 是一次性任务，wait_message 0.5s 轮询天然跨进程收信，投递延迟上界即轮询间隔——无需推送通道
- **主 Agent 在 spawn_agents 期间阻塞**（仍成立），发给 'main' 的消息要等 wait_all 返回后的下一轮才被消费——真正实时的只有 Worker↔Worker 这条边。

### 6.3 Agent 类型定义 ✅ 已实现（P48）

| | mini | mewcode |
|---|---|---|
| Agent 类型 | **4 种内置**：explore（只读搜索）、plan（规划）、worker（全能，默认）、verify（PASS/FAIL 验证）(P48) | **4 种内置**：Explore、Plan、general-purpose、Verification |

**已完成**（P48）：
- `core/agent_types.py` — `AgentTypeDefinition` frozen dataclass，4 种内置类型
- 每种类型定义：专属 system prompt、工具白名单（`allowed_tools`）、迭代上限（`max_iterations`）
- `SubAgent.__init__` / `SubAgentManager.spawn` / `spawn_parallel` 均接受 `agent_type` 参数
- `SpawnAgentsTool` 新增 `agent_type` 字段，LLM 可自主选择类型
- `/spawn --type explore <task>` 命令行指定
- `_intersect_tools()` 辅助函数：agent_type 工具白名单与调用方 `allowed_tools` 取交集
- 向后兼容：不指定 agent_type 时行为与 P48 前完全一致

### 6.4 多后端 spawn ✅ 已实现

| | mini | mewcode |
|---|---|---|
| SubAgent 运行方式 | ✅ in-process + **tmux 窗格** + **Windows Terminal 窗格/新窗口**（`/spawn --pane`，wt 装了就能用——不在 WT 会话内降级为共享窗口标签页） | in-process + tmux 面板 + iTerm2 面板（**win32 一律回退 in-process**） |

**已完成**（前置 + 三层实现）：

**前置：Mailbox 跨进程改造**（兑现 6.2 架构边界的欠账）：
1. **文件锁**——`_with_lock`：O_EXCL 锁文件 + 指数退避带随机抖动（5ms 起、80ms 封顶）+ 10s 陈旧锁接管 + 5s 超时抛 TimeoutError（消息没送出去必须让调用方知道，不静默丢）。实测 4 进程 × 20 条并发写同一收件箱零丢失
2. **原子写**——temp 文件 + os.replace，纯读方永不见半截文件（读免锁）
3. **磁盘注册表**——`_registry.json`（id → 别名）替代内存 set/dict，worker 进程能解析父进程注册的同伴（mewcode 的注册表在内存里，跨进程要靠 AgentNameRegistry 单例 + 同进程假设，mini 此处更彻底）
4. **唤醒的适配**：mewcode 用 tmux send-keys 推送唤醒常驻队友；mini 的 worker 是一次性任务，靠 wait_message 0.5s 轮询天然跨进程收信，无需推送通道——投递延迟上界即轮询间隔

**worker 协议**（`core/worker.py`）：父进程写 WorkerSpec JSON（任务/身份/mailbox 目录/结果路径）→ 窗格跑 `mini-agent --worker <spec>`（无头单任务，进度流式打到窗格 stdout）→ 结果原子写 JSON → 父进程轮询收集。API key 经环境变量继承，不落盘。**协议文件放 `~/.mini-agent/workers/`（工作目录之外）**——见下方实测迭代第 4 条的教训

**窗格后端**（`core/spawn_backends.py`）：
- 探测跟随 mewcode 哲学——只在自身已跑在 tmux（`TMUX` env）/ Windows Terminal（`WT_SESSION` env）会话内才启用窗格，否则回退 in-process
- tmux：`split-window -d`（不抢焦点）；**Windows Terminal**：会话内 `wt -w 0 split-pane` 分屏，会话外只要装了 wt 就降级 `wt -w mini-agents new-tab`——首次派发弹一个共享窗口，后续派发进同一窗口的标签页不轰炸（cmd/PowerShell/IDE 终端都能用）——mewcode 在 win32 直接护栏放弃窗格，**此子项反超**
- `SubAgentManager.spawn_pane()`：`_PaneWorkerProxy` 顶替 SubAgent 进活跃表，wait/cancel/list 与 in-process 完全同构（收集任务包装为 asyncio.Task）
- 入口 `/spawn --pane <task>`；spawn_agents 工具不暴露（窗格可视化是给人看的，LLM 不需要）

**实测迭代加固**（六轮真实使用暴露并修复，全部有回归测试）：
1. **/spawn wait 结果不截断**——原 200 字符截断腰斩交付物；改完整输出（8000 字符病态防线）
2. **`--wait` 一步到位**——`/spawn --pane --wait <task>` 派发+进度面板+结果一条命令；wt 降级模式改 `-w mini-agents` 命名窗口标签页聚合（不再每 worker 弹一窗）
3. **worker 顶层崩溃护栏**——曾崩在写结果之前致父进程只能超时、原因随窗格关闭消失；任何异常都写失败结果 + traceback + 窗格停留。`/spawn wait` 超时 300→900s 对齐收集器
4. **协议隔离**（最深的坑）——worker 的 LLM 读到项目内自己的 spec（含 result_path）后"好心"提前自己写了结果桩，父进程 0.5s 轮询捡走（Tokens: 0），真结果被覆盖成孤儿。修复：协议文件迁至 `~/.mini-agent/workers/` + 收集器 schema/agent_id 双校验拒绝桩文件
5. **LLM Provider 429/5xx 退避重试**——并行 worker 共用一个 key 触发持续配额限流，一次 429 即零产出死亡；两家 Provider stream 前置重试（尊重 Retry-After，指数退避 1/2/4/8/16s 约 31 秒耐心，chunk 产出后不重试防重复输出）
6. **多报告排版**——总览表 + `# 报告 i/N` 硬分节 + 交付文件行（自动提取真实存在于工作目录的文件名，亮橙渲染）；slash 输出显式哨兵选择 Markdown 渲染，纯文本版式（/status /cost）不受污染

**验证**：24 个单测（探测含 wt-window 降级/命令构造/失败路径/WorkerSpec 往返/管理器收集/超时/取消/桩文件拒绝/崩溃护栏/worker MockLLM 全链路/4 进程并发零丢失）+ **真实 LLM 跨进程 E2E**：worker 子进程注册（父进程注册表实时可见）→ send_message 跨进程送达 main → 注销 → 结果文件收集，全链路 PASS；另经六轮交互式真实使用验证（多窗格并发、失败路径、大任务长时等待）

**诚实边界**：iTerm2 后端未做（无 macOS 验证环境，照 mewcode 抄 AppleScript 属于无法验证的代码）；pane worker 的 cancel 是尽力而为（停止等待收集，不强杀窗格进程）；worker 进程无权限弹窗（与 in-process SubAgent 一致——本就不接权限管理器）；wait 超时（900s）后完成的结果成孤儿，可手动查 `~/.mini-agent/workers/<id>.result.json`。

### 6.5 Worktree 完善 ✅ 已实现（P54）

| | mini | mewcode |
|---|---|---|
| Git worktree | **完整生命周期管理**：符号链接/过期清理/变更检测 (P54) | 完整生命周期管理（符号链接/过期清理/变更检测） |

**已完成**（P54）：
- `create()` 自动符号链接 `node_modules`/`.venv`/`vendor`（Windows 无权限静默跳过）
- `cleanup_stale(max_age_days)` — 启动时清理超龄的干净 worktree（脏的保留，不丢未提交工作）+ 删除对应分支
- `SecurityConfig.worktree_max_age_days = 7`（0 = 禁用）
- `has_uncommitted_changes()` 便捷检测方法
- `/spawn wait` 结果显示 worktree 路径 + `git merge <branch>` 合并提示

---

## 七、Hook 系统

### 7.1 Hook 事件类型 ✅ 已实现（P50）

| | mini | mewcode |
|---|---|---|
| 事件类型 | **11 种全部实际触发**：STARTUP/SHUTDOWN/SESSION_START/SESSION_END/USER_INPUT/TURN_START/TURN_END/PRE_LLM/POST_LLM/PRE_TOOL/POST_TOOL (P50) | 10 种事件（startup/shutdown/session_start/end/turn_start/end/pre_send/post_receive/pre_tool/post_tool） |

**已完成**（P50）：
- HookStage 新增 4 个：STARTUP/SHUTDOWN/TURN_START/TURN_END
- 接线 3 个已定义但未触发的：POST_LLM/SESSION_START/USER_INPUT
- 触发点：app.py（STARTUP/SESSION_START/USER_INPUT/SESSION_END/SHUTDOWN）+ agent_loop.py（TURN_START/PRE_LLM/POST_LLM/PRE_TOOL/POST_TOOL/TURN_END）
- USER_INPUT 支持 BLOCK 拦截用户输入；POST_LLM 观察式（含 content_preview/finish_reason）
- 全部触发 try/except 包裹——hook 异常不破坏主流程
- 对照 mewcode 的 pre_send/post_receive → mini 的 PRE_LLM/POST_LLM 等价

### 7.2 Hook 拒绝工具执行 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| Pre-tool hook 拒绝 | ✅ 代码层 `HookAction.BLOCK`+ **`[[hooks]]` 配置声明式规则**（fnmatch 工具名 + 参数子串/正则匹配；支持 `action = "confirm"` 弹 y/a/n 确认框） | ✅ 配置文件 hook `reject: true` 抛 `ToolRejectedError` 阻止执行 |

**实现前的勘误**：本条原描述"Hook 只能观察，不能阻止"已陈旧——`HookAction.BLOCK` 在 `_run_tool_pipeline` 早已接线（工具不执行，LLM 收到 "Blocked by hook: <reason>"）。对照 mewcode 源码后确认**真实差距是用户入口**：mewcode 的拒绝 hook 从配置文件加载（event/条件/reject/reason），mini 只能写 Python 代码注册。

**已完成**（声明式规则）：
1. `tools/hooks.py` — `HookRule` dataclass + `parse_hook_rules()`（非法条目告警跳过，不阻断启动）+ `register_hook_rules()`（注册为 PRE_TOOL BLOCK/CONFIRM hook，按 `action` 字段区分）
2. 匹配语义：`tool`（fnmatch 模式，默认 `*`）+ `contains`（参数值子串，可选）+ `regex`（re.search 正则，可选，与 contains 同时给则须同时命中；非法正则告警跳过）+ `arg`（限定只查某参数，可选）；命中即按 `action` 裁决（默认 BLOCK；`"confirm"` 弹 y/a/n 确认），`reason` 回给 LLM
3. `AgentConfig.hooks` 字段——TOML `[[hooks]]` 经 `_merge` 自动落入；`app.py` 启动时注册并提示数量
4. 配置示例（给 docs/spec.md 加只读锁，5 行配置替代 10 行 Python）：

   ```toml
   [[hooks]]
   tool = "write_file"
   arg = "file_path"
   contains = "docs/spec"
   reason = "docs/spec.md is read-only by project policy"
   ```

5. 11 个测试：工具名匹配 / fnmatch 模式 / arg 限定 / 任意参数子串 / regex（含 AND 语义与非法正则跳过）/ 默认 reason / 非法条目跳过 / TOML 往返 / **端到端**（AgentLoop 流水线内拦截，文件未写入且 LLM 收到原因）

**与 mewcode 的差异**：mewcode 的 hook 还支持 command/prompt/http/agent 四种动作类型和条件表达式引擎；mini 做拒绝（block）与确认两种规则，观察类扩展已有 EventBus 订阅者机制覆盖（含 `listener_dirs` 零代码插件），不重复建设。

---

## 八、Skill 系统

### 8.1 Skill 安装 ✅ 已实现（P55）

| | mini | mewcode |
|---|---|---|
| Skill 来源 | 内置 4 个 + **`/skill install <path_or_url>` 命令安装** + `/skill uninstall` 卸载 (P55) | 内置 + **`/skill install <path>` 命令安装** |

**已完成**（P55）：
- `SkillRegistry.install(source, target_dir)` — 本地路径 → `shutil.copytree`；git URL → `git clone --depth 1`
- 安装后验证：SKILL.md 存在 + `name` 字段解析通过；验证失败自动清理
- `SkillRegistry.uninstall(name, target_dir)` — 遍历匹配 SKILL.md 中的 name 字段后删除目录
- `/skill install <path_or_url>` / `/skill uninstall <name>` 子命令

### 8.2 Skill 热重载 ✅ 已实现（P56）

| | mini | mewcode |
|---|---|---|
| 修改 skill 文件后 | **`/skill reload` 热重载**——清除→重扫描→重激活，活跃 skill prompt 自动更新 (P56) | **自动检测文件变更，热重载** |

**已完成**（P56）：
- `load_all()` 改为先清除再扫描（不再累积旧条目）
- `SkillRegistry.reload(conversation)` — 保存活跃列表→全部停用→重新加载→重激活（prompt 自动更新）
- 磁盘删除的 skill 从活跃列表移除并报告 lost
- `/skill reload` 子命令

---

## 九、会话管理

### 9.1 会话自动清理 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| 旧会话清理 | ✅ **N 天自动清理**（默认 30 天，可配 `session_cleanup_days`），跳过未正常关闭的会话（崩溃恢复保留） | **30 天自动清理**（可配） |

**已完成**：
1. `SessionStore.cleanup_stale(max_age_days)` — 启动时扫描 `~/.mini-agent/sessions/`，删除超过 N 天且 `closed_cleanly=True` 的会话文件；未正常关闭的跳过（可能需要崩溃恢复）
2. `MemoryConfig.session_cleanup_days = 30`（0 = 禁用），可通过 `config.toml` 的 `[memory]` 段配置
3. `app.py` 启动时调用（在崩溃恢复检查之前），清理后显示 "Cleaned N stale session(s)"
4. 4 个测试：过期删除 / 未正常关闭跳过 / 0 禁用 / 空目录

### 9.2 会话压缩边界记录 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| 恢复压缩后的会话 | ✅ **压缩边界标记**——恢复时只加载边界后的消息 + 摘要，同时恢复已读文件状态 | **压缩边界标记**——恢复时只加载边界后的消息 + 摘要 |
| 边界数据结构 | `compact_boundary` dict（summary + timestamp + read_files） | `CompactBoundary(summary, keep)` + `CompactEvent` |
| 存储格式 | JSON conversation 段中的 `compact_boundary` 字段（覆写式） | JSONL 中 `type=compact_boundary` 记录（追加式） |
| 已读文件恢复 | ✅ `adopt_boundary()` 恢复文件路径 + **内容**到 `_read_files`；`_inject_read_files()` 烤入最近 5 文件内容（5000 tokens/个）（9.2a） | `RecoveryState` 烤入摘要附件（含文件**内容**截断到 5000 tokens/个） |
| keep 消息处理 | 尾部消息作为普通消息存在 messages 数组中 | `keep` 消息序列化到边界记录内，自包含 |
| 工具对完整性 | ✅ **`_align_split_to_tool_pair()`**——keep 边界回退到工具对头部，SlidingWindow 丢弃孤儿 tool result（9.2b/P60） | `_align_keep_start_to_tool_pair()` 确保不切断工具对 |
| 压缩熔断 | ✅ **熔断器**——连续 N 次压缩无效后跳过（`compress_max_failures`，默认 3，0 禁用） | `CompactCircuitBreaker`——连续失败 3 次后熔断，防死循环 |

**已完成**：
1. `Conversation.compact_boundary` 字段——压缩后由 `Compressor` 记录摘要文本、时间戳、已读文件列表
2. `SessionStore` 序列化/反序列化支持——保存时写入 `compact_boundary`，加载时跳过已压缩的 SYSTEM 消息，从边界摘要重建
3. `ContextManager.adopt_boundary()` —— 会话加载时从边界恢复 `_read_files` 状态，防止压缩-重读膨胀循环
4. `app.py._adopt_session()` 接入——崩溃恢复、`/session load`、`/fork` 三个入口均自动恢复已读文件状态
5. 兜底逻辑——纯 `SlidingWindow` 压缩（不产生摘要消息）时从 `_inject_read_files` 插入的消息创建边界（真实 LLM 验证暴露并修复）
6. 6 个测试（4 单元 + 2 集成）：边界往返 / 跳过压缩 SYSTEM / 保留非压缩消息 / 无边界向后兼容 / 完整链路 E2E / 旧格式兼容 E2E

**与 mewcode 的诚实差异**（源自架构差异，非照抄）：

| # | 差异点 | mewcode 做法 | mini 做法 | 影响 |
|---|---|---|---|---|
| 1 | 恢复附件含文件内容 | `build_recovery_attachment()` 把最近 5 个文件的实际内容（截断到 5000 tokens/个）+ 活跃 skill + 工具列表烤进摘要消息 | ~~只记文件路径，通过 `_inject_read_files` 提醒 LLM 不要重读~~ | ✅ 已消除（9.2a），见 9.2a 小节 |
| 2 | keep 消息自包含 | `CompactBoundary.keep` 把尾部消息序列化到边界记录内（JSONL 追加式，边界是自包含的恢复点） | 尾部消息作为普通消息存在 JSON messages 数组中 | mini 用单 JSON 覆写式存储，尾部消息天然与边界同文件，自包含性等价——仅格式层差异 |
| 3 | 工具对对齐 | `_align_keep_start_to_tool_pair()` 确保 keep 边界不切断 tool_use/tool_result 配对（切断会导致 API 400 错误） | ~~`KEEP_RECENT=6` 固定切分，可能切断~~ | ✅ 已消除（9.2b/P60 + P150 token 驱动替代固定 6），见 9.2b 小节 |
| 4 | 压缩熔断器 | `CompactCircuitBreaker`——连续失败 3 次后停止重试 | 无 | 独立防护机制，可作为后续增强单独实现 |

### 9.2a 压缩恢复附件含文件内容 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| 恢复附件 | ✅ `_inject_read_files()` 烤入最近 5 个已读文件的实际内容（`truncate_to_tokens` 截断到 5000 tokens/个）+ 用户最近请求 | `build_recovery_attachment()` 烤入最近 5 文件内容 + skill + 工具列表 |
| 内容捕获时机 | `record_file_read(path, content)` 在 spill **之前**立即截断存储（防溢写后丢失原始内容） | 压缩时从磁盘重读 |
| 用户请求保留 | ✅ 压缩前捕获最近 USER 消息（≤2000 字符），烤入摘要 + 持久化到 boundary | 无对应（mewcode 靠 keep 消息） |
| 边界持久化 | `compact_boundary["file_contents"]` + `["last_user_request"]`，`adopt_boundary()` 恢复 | 烤入摘要文本 |

**已完成**：
1. `truncate_to_tokens(text, max_tokens)` —— 二分搜索截断，超出追加 `\n... (truncated)`（`token_counter.py`）
2. `_read_files: dict[str, str | None]` —— value 存储截断后的文件内容（`context.py`）
3. `record_file_read(path, content)` —— 有内容时截断到 5000 tokens 存储；无内容时不覆盖已有记录
4. `agent_loop.py` 在 spill 之前传递 `result.output` 到 `record_file_read`（修复 spill 后丢失原始内容的 bug）
5. `_inject_read_files()` —— 注入三段恢复上下文：用户最近请求 + 已读文件路径 + 最近 5 个文件内容
6. `_last_user_request` —— 压缩前捕获最近 USER 消息（≤2000 字符），防压缩后 agent 丢失任务上下文
7. `compact_boundary["file_contents"]` + `["last_user_request"]` —— 持久化到边界，`adopt_boundary()` 恢复，向后兼容旧格式
8. 14 个测试：truncate 3 + content storage/injection/boundary 7 + user request 4

### 9.2b 压缩工具对对齐 ✅ 已实现（P60）

| | mini | mewcode |
|---|---|---|
| keep 边界对齐 | ✅ **`_align_split_to_tool_pair()`**——切分点落在 TOOL 消息时回退到工具对头部（assistant tool_calls 消息），`SummarizeOldest` / `LLMSummarizeOldest` 共用 | `_align_keep_start_to_tool_pair()` |
| 最后手段截断 | ✅ **SlidingWindow 孤儿防护**——token 切分落在工具对中间时丢弃开头的孤儿 tool result（向前扩会超预算） | 无对应（架构不同） |

**已完成**：
1. `_align_split_to_tool_pair(msgs, split)` —— `msgs[split].role == TOOL` 时向前回退到非 TOOL 消息，工具对整体保留在 kept；回退到 0 说明无可摘要内容，压缩空操作
2. `SlidingWindow` 孤儿防护 + 任务锚点（保留最近 USER 消息）共存，锚点逻辑在孤儿丢弃之后执行
3. 4 个单元测试：边界回退到 assistant / 全部为工具对时空操作 / LLM 变体对齐 / 孤儿丢弃 + 锚点共存
4. 真实 API 验证（DeepSeek）：对齐后的压缩产物发送成功；**诚实发现**——未对齐的孤儿 tool result 该端点也接受（宽容实现），修复价值在严格端点（OpenAI 官方 / Anthropic 的强校验）

---

## 十、mini-code-agent 优势

| 功能 | 说明 | 加强方向 |
|---|---|---|
| `/undo` 操作级撤销 | 对话 + 文件双回滚 | 可加：undo 预览（回滚前显示会恢复哪些文件） |
| `/fork` 对话分叉 | 深拷贝会话独立分支 | 可加：`/fork list` 查看所有分支 |
| `/record` + `/replay` | 零 LLM 调用工具链重放 | 可加：从 YAML/JSON 导入录制（手写工具链） |
| `/cost` 成本仪表盘 | 按模型分账 + 双层预算 | 可加：硬预算（到额停止） |
| 机制实验框架 | 3 个对照实验 + 数据 | 可加：实验 4（压缩恢复效果 A/B） |
| `/explain` 教学模式 | 工具调用教学面板 | 可加：新手引导教程 |
| 死循环诱导数据 | 真实 LLM 下的熔断行为数据 | 已完成 |
| 全中英双语注释 | 336 条注释全部中英对照 | 保持 |

---

## 十一、增强实施优先级总表

| 优先级 | 编号 | 增强项 | 解决什么 | 工作量 |
|---|---|---|---|---|
| ✅ 完成 | 4.1 | 大工具结果溢写磁盘（P36） | 压缩-重读膨胀（原唯一高严重度遗留） | 已完成 |
| ✅ 完成 | 4.2 | 压缩后恢复·已读文件清单（P36） | 同上 | 已完成 |
| ✅ 完成 | 1.2 | Prompt 缓存（P37） | Anthropic 省 90% 输入 token | 已完成 |
| ✅ 完成 | 1.4 | 流式工具执行（P38） | 多工具调用提速 | 已完成 |
| ✅ 完成 | 2.2 | `@file` 引用（P39） | 用户体验 | 已完成 |
| ✅ 完成 | 5.3 | 输入历史持久化 | 用户体验 | 已完成 |
| ✅ 完成 | 3.2 | 权限规则文件（P40） | 用户自定义权限 | 已完成 |
| ✅ 完成 | 3.1 | OS 级沙箱（P41） | 安全质变 | 已完成 |
| ✅ 完成 | 1.3 | 上下文窗口 API 探测（P42） | 新模型免更新代码 | 已完成 |
| ✅ 完成 | 4.3 | Token 计数精度提升（P43） | 压缩阈值准确性 | 已完成 |
| ✅ 完成 | 1.5 | max_tokens 恢复（P44） | 长回答不截断 | 已完成 |
| ✅ 完成 | 6.1 | Coordinator 模式（P45） | /team 质量 | 已完成 |
| ✅ 完成 | 6.3 | Agent 类型定义（P48） | SubAgent 差异化 | 已完成 |
| ✅ 完成 | 3.3 | Plan 模式只读（P49） | 规划安全 | 已完成 |
| ✅ 完成 | 7.1 | Hook 事件类型扩充（P50） | Hook 灵活性 | 已完成 |
| ✅ 完成 | 2.1 | Pydantic Schema 生成（P46+P47） | 工具开发效率 | 已完成 |
| ✅ 完成 | 2.3 | 工具搜索/延迟加载（P51） | 大量 MCP 工具场景 | 已完成 |
| ✅ 完成 | 4.4 | 选择性记忆召回（P52） | 记忆多时省 token | 已完成 |
| ✅ 完成 | 4.5 | 记忆合并（P53） | 记忆质量 | 已完成 |
| ✅ 完成 | 5.2 | 远程/浏览器模式 + 11 项增强（P57） | 新使用场景 | 已完成 |
| ✅ 完成 | 6.2 | Mailbox 跨 Agent 通信（P58） | 多 Agent 协作 | 已完成 |
| ✅ 完成 | 1.1 | OpenAI Responses API（openai-responses Provider） | o1/o3 模型支持 | 已完成 |
| ✅ 完成 | 6.4 | 多后端 spawn（tmux + Windows Terminal 窗格，含 Mailbox 跨进程改造） | 可视化 | 已完成 |
| ✅ 完成 | 6.5 | Worktree 完善（P54） | 并行隔离 | 已完成 |
| ✅ 完成 | 8.1 | Skill 安装命令（P55） | 扩展性 | 已完成 |
| ✅ 完成 | 8.2 | Skill 热重载（P56） | 开发效率 | 已完成 |
| ✅ 完成 | 9.1 | 会话自动清理 | 磁盘管理 | 已完成 |
| ✅ 完成 | 9.2 | 会话压缩边界 | 恢复性能 | 已完成 |
| ✅ 完成 | 4.6 | 记忆导出/导入（P61） | 互操作：export/import .md + scope 路由 | 已完成 |
| ✅ 完成 | 7.2 | Hook 拒绝工具执行（[[hooks]] 声明式规则;支持 action="confirm" 弹窗确认） | 自动化控制 | 已完成 |
| ✅ 完成 | 1.1 | LLM 摘要压缩接入（P64.2） | LLM 语义摘要设为默认，失败回退提取式 | 已完成 |
| ✅ 完成 | — | 压缩检查前移 + 摘要前缀指令（P64.3） | 纯对话场景压缩触发 + 防 LLM 翻会话文件 | 已完成 |
| ✅ 完成 | 4.7 | 压缩双阈值（P65） | 硬阈值绕过熔断器，紧急情况走完整级联而非粗暴截断 | 已完成 |
| ⚪ P3 | 1.1a | Anthropic Provider E2E 验证 | 1.1 遗留：代码就绪但未用真实 API key 端到端验证 | 2 小时（需 key） |
| ✅ 完成 | 9.2a | 压缩恢复附件含文件内容 | 9.2 诚实差异 #1 消除：`_inject_read_files` 烤入最近 5 文件内容（5000 tokens/个） | 已完成 |
| ✅ 完成 | 9.2b | 压缩工具对对齐（P60） | 9.2 诚实差异 #3 消除：keep 边界对齐 + SlidingWindow 孤儿防护 | 已完成 |
| ✅ 完成 | 9.2c | 压缩熔断器 | 9.2 诚实差异 #4 消除：`ContextManager` 内置熔断器，连续 N 次压缩无效后跳过 | 已完成 |
| ✅ 完成 | 4.1a | 聚合工具结果预算（P64.1） | 多工具单条不超阈值、合计撑爆上下文；含读回豁免/预览 2000/小结果豁免三配套 | 已完成 |
| ⚪ P4 | 6.4a | iTerm2 窗格后端 | 6.4 诚实边界：无 macOS 验证环境，未实现 | 半天（需 Mac） |
| ✅ 完成 | — | 摘要 prompt 结构化（P67） | mewcode 风格 `<analysis>` 草稿 + 9 节 `<summary>` 结构化输出，只注入 summary 块；回退可观测 | 已完成 |
| ✅ 完成 | — | 保留窗口按压缩目标缩放（P68） | 下限/硬顶随 target 缩放，修复小窗口下摘要级数学失效、压缩退化为纯截断 | 已完成 |
| ✅ 完成 | — | DropToolResults 尊重保留窗口（P69） | Stage 1 不再截断模型工作集，修复"以为工具坏了"重读死循环（36 迭代→4） | 已完成 |
| ✅ 完成 | — | 恢复附件预算缩放 + 嵌套摘要前传（P70） | 附件 min(25K, 窗口//4)；prompt 明确嵌套旧摘要为权威历史 | 已完成 |
| ✅ 完成 | — | SlidingWindow 摘要锚点（P71） | 修复"摘要刚生成就被尾部截断删除"——与任务锚点同等待遇 | 已完成 |
| ✅ 完成 | — | digest 剥附件 + 摘要重试（P72） | 附件不再淹没历史；偶发空摘要先重试再回退 | 已完成 |
| ✅ 完成 | — | 摘要 prompt 超长收缩重试（P73） | 400/413 识别 → 丢最旧 20% 消息 + cap 缩 20% 重试（≤3 轮）；穷尽立即回退不重复相同请求 | 已完成 |
| ✅ 完成 | — | 最小前缀检查 + /todo 歧义前缀（P74） | 压缩器前缀 < 2K 跳过；/todo ID 歧义检测 + 最短唯一前缀显示 | 已完成 |

**总工作量估算**：约 15-20 个工作日。全部完成后 mini-code-agent 在每一个维度都 ≥ mewcode-python，同时保持自身的差异化优势（/undo、/fork、/record、/cost、/explain、实验框架）。
