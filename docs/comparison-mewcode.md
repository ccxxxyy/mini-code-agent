# Mini-Code-Agent vs MewCode-Python 详细对比与增强路线

本文档逐维度对比 mini-code-agent 与 [mewcode-python](https://github.com/xiaolincoding/mewcode-python) 的功能差异，并为每一个 mini **弱于** mewcode 的方面给出具体的增强方案。

---

## 零、基础框架对比

### 0.1 代码规模与语言

| | mini-code-agent | mewcode-python |
|---|---|---|
| 源码行数 | ~4,600 行 | ~15,000+ 行 |
| Python 版本 | 3.11+（用 tomllib、StrEnum 等 3.11 特性） | 3.12+（用 type 语法） |
| 注释 | 全部中英双语（336 条） | 英文为主 |
| 代码风格 | ruff（line-length 100, target py311） | ruff |

**差距**：代码量差 3 倍多——主要差在 TUI 框架（Textual vs 手拼）、多 Agent 团队系统（mewcode 13 个文件 vs mini 3 个）、沙箱/worktree 等模块。

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
| 参数校验 | **dataclass**（标准库） | `pydantic`（第三方） |
| TUI | Rich + prompt_toolkit（2 个） | Textual（1 个，但更重） |
| MCP | httpx 手写 JSON-RPC | `mcp` 官方 SDK |
| HTTP | httpx | httpx |
| WebSocket | 无 | `websockets` |
| 总第三方依赖 | **3 个**（httpx/rich/prompt_toolkit） | **7 个**（anthropic/openai/pyyaml/pydantic/mcp/textual/websockets） |

**差距**：mini 的依赖更少更轻——这是**有意的设计取向**，不是弱点。零 SDK 意味着：
- 不受 SDK 版本更新的破坏性变更影响
- 安装快（pip install 秒装 vs SDK 拖一堆传递依赖）
- 用户可以审计全部代码（4600 行 vs 15000 行 + SDK 黑盒）

**增强方向**：保持最小依赖原则。如果后续需要 Pydantic（工具 Schema 自动生成）或 websockets（远程模式），按需单独引入——不做一次性全加。

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
| 测试 | **496 测试，83.4% 覆盖率，fail_under=80** | 27 个测试文件，覆盖率未知 |

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
| 文档数量 | **12 个专题文档** + README 双语 | MEWCODE.md（项目说明）+ 配置示例 |
| 架构文档 | agent-architecture.md（S01-S20 逐层解析） | 无 |
| 技术笔记 | tech-notes.md（41 节，设计决策记录） | 无 |
| 配置指南 | config-guide.md（全配置文件说明） | config.yaml.example |
| 终端指南 | terminal-guide.md（各系统各终端） | 无 |
| 实验报告 | experiments/README.md（3 个实验完整数据） | 无 |
| 能力对照 | capabilities.md（18 项需求逐条证据） | 无 |
| 开发历史 | tasks.md（P1-P41 完整记录） | 无 |

**差距**：此维度 mini **远超** mewcode。

**结论**：此维度 mini 已 >> mewcode，无需增强。

---

## 一、LLM 集成

### 1.1 Provider 支持

| | mini-code-agent | mewcode-python |
|---|---|---|
| OpenAI 兼容（Chat Completions） | ✅ | ✅ |
| Anthropic 原生 | 代码就绪，未 E2E 验证 | ✅ 完整验证 |
| OpenAI Responses API | ❌ | ✅ |

**差距**：mini 缺 OpenAI Responses API 支持；Anthropic Provider 未实测。

**增强方案**：
1. **Anthropic Provider E2E 验证**：获取 API key 后验证 streaming/tool_use/thinking blocks/token counting 四项（代码已就绪）
2. **OpenAI Responses API**：在 `llm/` 下新增 `openai_responses_provider.py`，与现有 `openai_provider.py`（Chat Completions）并列。Responses API 支持 reasoning summaries，对 o1/o3 系列模型有价值。注册到 ProviderRegistry，用户通过 `provider = "openai-responses"` 切换

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

### 1.5 max_tokens 恢复

| | mini | mewcode |
|---|---|---|
| max_tokens 截断处理 | 无（截断就截断了） | 检测到 `stop_reason=max_tokens` 自动提升限制重试（最多 3 次） |

**差距**：LLM 生成的回答超出 max_tokens 时被截断，mini 把不完整的回答直接展示。

**增强方案**：
在 `agent_loop.py` 的 `_think()` 后检查 `response.finish_reason`，如果是 `max_tokens`：
1. 把当前 `max_tokens` 翻倍（或使用模型最大值）
2. 重发请求（最多 3 次）
3. 3 次后仍截断则保留最后一次结果

代码改动：`core/agent_loop.py` ~15 行。

---

## 二、工具系统

### 2.1 工具 Schema 生成

| | mini | mewcode |
|---|---|---|
| Schema 定义方式 | 手写 `ToolSchema` dict | **Pydantic model** 自动生成 JSON Schema |

**差距**：手写 schema 容易出错（参数名写错、漏字段、类型不对），每加一个工具要写一大段 dict。

**增强方案**：
1. 每个工具定义一个 `ParamsModel(BaseModel)` 类，字段名和类型即为参数定义
2. `Tool` ABC 新增可选的 `params_model` 属性
3. `ToolSchema` 的 `parameters` 从 `params_model.model_json_schema()` 自动生成
4. 向后兼容：不定义 `params_model` 的工具仍用手写 schema

代码改动：`tools/base.py` ~15 行 + 每个工具新增 ParamsModel 类（约 5 行/工具 × 8 工具）。新增依赖：`pydantic>=2.0`。

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

### 2.3 工具搜索/延迟加载

| | mini | mewcode |
|---|---|---|
| MCP 工具加载策略 | 全部注册到 ToolRegistry | **三种策略**：EAGER / DISPATCH / NATIVE |

**差距**：接入大量 MCP 工具（如 100+ 个）时，全部塞进上下文浪费 token。

**增强方案**：
1. 新增 `ToolSearch` 工具——LLM 可以搜索可用工具而不是看到完整列表
2. MCP 配置新增 `loading = "eager" | "dispatch"` 选项
3. `dispatch` 模式下 MCP 工具不注册到主 schema 列表，LLM 通过 ToolSearch 发现后用 `mcp_call` 间接调用
4. 对 Anthropic 原生模式预留 `native`（`defer_loading` flag）

代码改动：`tools/mcp/` ~50 行 + 新增 `tools/builtin/tool_search.py` ~40 行。

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

### 3.3 Plan 模式只读权限

| | mini | mewcode |
|---|---|---|
| Plan 模式权限 | 无物理限制（靠 prompt 说"不要改文件"） | **物理只读**——Plan 模式下 write/edit/bash 工具被禁用 |

**差距**：prompt 是软约束，LLM 可能无视。

**增强方案**：
1. `AgentLoop` 新增 `readonly_mode: bool` 参数
2. `readonly_mode=True` 时，`_act()` 中过滤掉 `write_file`/`edit_file`/`delete_file`/`bash` 工具调用，返回错误信息"Plan mode: write operations disabled"
3. `/plan` 命令进入 Plan 模式时设 `readonly_mode=True`，退出时设 `False`
4. 或者更简单：Plan 模式下从 `ToolRegistry` 临时移除写工具的 schema——LLM 根本看不到这些工具

代码改动：`core/agent_loop.py` ~10 行 或 `tools/base.py` ToolRegistry ~10 行。

---

## 四、上下文/记忆管理

### 4.1 大工具结果溢写磁盘 ✅ 已实现（P36）

| | mini | mewcode |
|---|---|---|
| 大文件处理 | ✅ **>50K 字符溢写磁盘，对话留 500 字符预览**（`memory/tool_result_cache.py`，SubAgent 同样受保护——mewcode 的溢写不覆盖子代理） | >50K 字符的结果存磁盘，对话只留摘要 |

**原差距**：曾是 mini 唯一的高严重度遗留问题（tech-notes 34.3 ③）。用户说"读 spec.md"（大文件），内容全进对话→触发压缩→LLM 忘了读过→重读→再压缩→循环烧 token。P36 已修复，实现见 tech-notes §36。

**增强方案**：
1. 新建 `memory/tool_result_cache.py`
2. 工具执行后检查结果长度，>50K 字符时：
   - 结果存入磁盘缓存（`~/.mini-agent/cache/result_{hash}.txt`）
   - 对话中替换为摘要：`[File content cached to disk (52,341 chars). First 500 chars: ...]`
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

### 4.4 选择性记忆召回

| | mini | mewcode |
|---|---|---|
| 记忆注入方式 | 全部注入（最多 10 条） | **LLM 选择性召回**——先让 LLM 挑最相关的 ≤5 条 |

**差距**：记忆条目多了以后全部注入浪费 token，且无关信息可能干扰 LLM。

**增强方案**：
1. 当记忆条目 >10 条时，启用选择性召回
2. 构造一个轻量级 LLM 请求：把所有记忆的 `id + content 前 50 字符` 列表 + 用户最新消息发给 LLM，让它返回最相关的 ≤5 个 ID
3. 只注入这 5 条完整内容
4. ≤10 条时保持现有行为（全部注入，不额外调 LLM）
5. 可选优化：召回请求与主 LLM 请求并行发起（非阻塞预取）

代码改动：`memory/persistent.py` ~30 行 + `app.py` ~10 行。

### 4.5 记忆合并

| | mini | mewcode |
|---|---|---|
| 重复记忆处理 | 60% 词重叠去重 | **LLM 语义合并**——自动把相关记忆整合成一条 |

**差距**：词重叠去重是表面相似度——"喜欢 tabs"和"讨厌 spaces"语义相关但词不重叠，不会被合并。

**增强方案**：
1. 在 `MemoryExtractor.maybe_extract()` 末尾，当总记忆条目 >20 时触发合并
2. 把所有记忆发给 LLM："以下记忆中哪些可以合并？输出合并后的 JSON"
3. 替换旧条目，保留最新的 `created_at`
4. 合并阈值可配置：`[memory] consolidation_threshold = 20`

代码改动：`memory/extraction.py` ~30 行。

### 4.6 记忆存储格式

| | mini | mewcode |
|---|---|---|
| 存储格式 | 单个 `memory.json` 文件 | **独立 .md 文件 + YAML 前置元数据 + MEMORY.md 索引** |

**差距**：单 JSON 文件不方便用户手动浏览/编辑。

**增强方案**：
1. 保持 JSON 作为内部存储格式（程序读写方便）
2. 新增 `/memory export` 命令——导出为 mewcode 格式的独立 .md 文件（方便用户浏览）
3. 新增 `/memory import <dir>` 命令——从 .md 文件目录导入

代码改动：`extensions/builtin_commands.py` ~30 行。这是优先级较低的增强——JSON 格式在功能上不弱，只是用户体验不同。

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

### 5.2 远程/浏览器模式

| | mini | mewcode |
|---|---|---|
| 远程访问 | ❌ 只能本地终端 | ✅ WebSocket 服务器 + 浏览器 UI |

**差距**：mewcode 可以 `--remote` 启动后在浏览器里用，适合远程服务器/iPad 等场景。

**增强方案**：
1. 新建 `remote/` 目录
2. `ws_server.py`：用 `websockets` 库起 WebSocket 服务器（端口可配）
3. `web_ui.py`：内嵌 HTML+CSS+JS 的浏览器前端（单文件，~300 行）
4. 协议：NDJSON 事件流（stream_text / tool_call / tool_result / permission_request / user_input）
5. `cli.py` 新增 `--remote` 参数
6. 新增依赖：`websockets`

代码改动：新增 ~400 行。优先级较低——大多数用户场景用终端就够了。

### 5.3 输入补全增强 ✅ 已实现

| | mini | mewcode |
|---|---|---|
| `/` 命令补全 | ✅ | ✅ |
| `@file` 补全 | ✅（P39） | ✅ |
| 输入历史 | ✅ `FileHistory(~/.mini-agent/input_history)`，跨会话上下箭头浏览，失败退回内存 | ✅ 上下箭头浏览历史 |

此维度已全部对齐。

---

## 六、多 Agent

### 6.1 Coordinator 模式

| | mini | mewcode |
|---|---|---|
| 主 Agent 角色 | 既规划又执行 | **Coordinator 模式**——主 Agent 纯调度，物理上不能读写文件 |

**差距**：主 Agent 同时规划和执行时注意力容易分散——一边想下一步做什么、一边在读文件写代码。

**增强方案**：
1. `/team` 命令新增 `--coordinator` 选项
2. 开启时，Planner 的 ToolRegistry 只保留 `spawn_agents` + `send_message` 工具
3. System prompt 追加："你是协调者。你只负责分解任务和分配给 Worker，不能直接读写文件。"
4. Worker 仍保持完整工具集

代码改动：`core/agent_team.py` ~20 行 + `extensions/builtin_commands.py` ~5 行。

### 6.2 跨 Agent 通信

| | mini | mewcode |
|---|---|---|
| Agent 间通信 | SubAgent 只返回最终结果 | **Mailbox 消息传递** + **共享 TaskStore** |

**差距**：mini 的 SubAgent 是"派出去等结果回来"模式，Agent 之间不能中途交流。

**增强方案**：
1. 新建 `core/mailbox.py`——基于文件的消息队列（JSON 文件，每个 Agent 一个收件箱）
2. 新增 `SendMessage` 工具——LLM 可以发消息给指定 Agent
3. Agent 每轮开始前检查收件箱，有消息则追加到对话
4. 共享 TaskStore 已有（`core/task_store.py`），只需让 SubAgent 也能访问

代码改动：新增 `core/mailbox.py` ~50 行 + 新增工具 ~30 行。

### 6.3 Agent 类型定义

| | mini | mewcode |
|---|---|---|
| Agent 类型 | 无正式定义 | **4 种内置**：Explore（只读搜索）、Plan（规划）、general-purpose（全能）、Verification（验证） |

**差距**：mini 的所有 SubAgent 都是相同配置——不区分"搜索 Agent"和"执行 Agent"。

**增强方案**：
1. 新建 `agents/` 目录，放 `.md` 格式的 Agent 定义文件
2. 每个定义文件包含：名称、系统提示、允许的工具列表、模型偏好、最大轮次
3. 至少定义 4 种：
   - `explore.md`：只读工具（read_file/glob/grep），用弱模型
   - `plan.md`：只读 + 输出规划，不执行
   - `worker.md`：全工具
   - `verify.md`：只读 + 输出 PASS/FAIL 判定
4. `/spawn` 命令新增 `--type explore` 参数

代码改动：新增 `agents/` 目录 + loader ~40 行 + SubAgent 集成 ~20 行。

### 6.4 多后端 spawn

| | mini | mewcode |
|---|---|---|
| SubAgent 运行方式 | in-process 异步 | **in-process + tmux 面板 + iTerm2 面板** |

**差距**：in-process 时用户看不到 SubAgent 的实时输出。

**增强方案**：
1. 检测 `tmux` 环境时，`/spawn` 在新面板中启动 SubAgent（`tmux split-window -h "mini --teammate ..."）
2. iTerm2 通过 AppleScript 新建面板
3. 非 tmux/iTerm2 环境保持 in-process

代码改动：新增 `core/spawn_backends.py` ~80 行。优先级较低——进度面板已提供可视化。

### 6.5 Worktree 完善

| | mini | mewcode |
|---|---|---|
| Git worktree | 代码就绪 | 完整生命周期管理（符号链接/过期清理/变更检测） |

**增强方案**：
1. 创建 worktree 时自动符号链接 `node_modules`/`.venv`/`vendor`（避免重装依赖）
2. 过期清理：启动时扫描 `.mini-agent/worktrees/`，超过可配天数的自动删除
3. 退出 worktree 前检测是否有未提交变更，有则提示

代码改动：`security/worktree.py` ~40 行。

---

## 七、Hook 系统

### 7.1 Hook 事件类型

| | mini | mewcode |
|---|---|---|
| 事件类型 | PRE_TOOL / POST_TOOL / PRE_LLM / SESSION_END | 10 种事件（startup/shutdown/session_start/end/turn_start/end/pre_send/post_receive/pre_tool/post_tool） |

**差距**：mini 的 hook 事件类型较少。

**增强方案**：
补齐缺失的事件类型：
- `STARTUP`：应用启动时触发
- `SHUTDOWN`：应用退出时触发
- `TURN_START`：每轮用户输入后、调 LLM 前触发
- `TURN_END`：每轮 Agent 回答后触发
- `PRE_SEND`：发送消息给 LLM 前（可修改消息）
- `POST_RECEIVE`：收到 LLM 响应后（可修改响应）

代码改动：`models/events.py` ~6 个新事件类 + `app.py` / `agent_loop.py` ~20 行 emit 调用。

### 7.2 Hook 拒绝工具执行

| | mini | mewcode |
|---|---|---|
| Pre-tool hook 拒绝 | Hook 只能观察，不能阻止 | ✅ Pre-tool hook 可以抛 `ToolRejectedError` 阻止执行 |

**增强方案**：
1. `PRE_TOOL` hook 回调返回值新增 `reject` 选项
2. hook 返回 `{"reject": true, "reason": "..."}` 时，工具不执行，LLM 收到拒绝原因

代码改动：`tools/hooks.py` ~10 行 + `core/agent_loop.py` ~5 行。

---

## 八、Skill 系统

### 8.1 Skill 安装

| | mini | mewcode |
|---|---|---|
| Skill 来源 | 内置 4 个 + 手动复制 | 内置 + **`/skill install <path>` 命令安装** |

**增强方案**：
1. `/skill install <path_or_url>`——从本地路径或 git URL 安装 skill 到 `~/.mini-agent/skills/`
2. 安装时验证 skill 格式（有 `prompt.md` 或合法的 .md 文件）

代码改动：`extensions/builtin_commands.py` ~20 行。

### 8.2 Skill 热重载

| | mini | mewcode |
|---|---|---|
| 修改 skill 文件后 | 需要重启 | **自动检测文件变更，热重载** |

**增强方案**：
1. Skill 加载时记录文件的 mtime
2. 每次 `/skill list` 或激活时检查 mtime，变了就重新加载
3. 不需要文件监控守护线程——按需检查即可

代码改动：`extensions/skill_loader.py` ~15 行。

---

## 九、会话管理

### 9.1 会话自动清理

| | mini | mewcode |
|---|---|---|
| 旧会话清理 | 无（永远保留） | **30 天自动清理**（可配） |

**增强方案**：
1. `SessionStore` 启动时扫描 `~/.mini-agent/sessions/`
2. 删除超过 N 天的会话文件（默认 30 天，可配 `[session] cleanup_days = 30`）
3. 清理前检查 `closed_cleanly=True`——未正常关闭的不删（可能是崩溃恢复用的）

代码改动：`memory/session_store.py` ~15 行。

### 9.2 会话压缩边界记录

| | mini | mewcode |
|---|---|---|
| 恢复压缩后的会话 | 加载全部消息（含已压缩的） | **压缩边界标记**——恢复时只加载边界后的消息 + 摘要 |

**增强方案**：
1. 压缩时在 session JSONL 文件中写入一条 `{"type": "compact_boundary", "summary": "..."}` 记录
2. 加载会话时，如果找到 compact_boundary，只加载：摘要 + 边界后的消息
3. 减少加载时间和内存占用

代码改动：`memory/session_store.py` ~20 行 + `memory/compressor.py` ~5 行。

---

## 十、mini-code-agent 独有优势（mewcode 没有的）

以下功能是 mini 有而 mewcode 没有的——**必须保持并加强**：

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
| 🟢 P2 | 1.5 | max_tokens 恢复 | 长回答不截断 | 2 小时 |
| 🟢 P2 | 6.1 | Coordinator 模式 | /team 质量 | 半天 |
| 🟢 P2 | 6.3 | Agent 类型定义 | SubAgent 差异化 | 半天 |
| 🟢 P2 | 3.3 | Plan 模式只读 | 规划安全 | 2 小时 |
| 🟢 P2 | 7.1 | Hook 事件类型扩充 | Hook 灵活性 | 半天 |
| 🔵 P3 | 2.1 | Pydantic Schema 生成 | 工具开发效率 | 1 天 |
| 🔵 P3 | 2.3 | 工具搜索/延迟加载 | 大量 MCP 工具场景 | 半天 |
| 🔵 P3 | 4.4 | 选择性记忆召回 | 记忆多时省 token | 半天 |
| 🔵 P3 | 4.5 | 记忆合并 | 记忆质量 | 半天 |
| 🔵 P3 | 5.2 | 远程/浏览器模式 | 新使用场景 | 2 天 |
| 🔵 P3 | 6.2 | Mailbox 跨 Agent 通信 | 多 Agent 协作 | 1 天 |
| 🔵 P3 | 1.1 | OpenAI Responses API | o1/o3 模型支持 | 1 天 |
| 🔵 P3 | 6.4 | 多后端 spawn（tmux） | 可视化 | 1 天 |
| ⚪ P4 | 6.5 | Worktree 完善 | 并行隔离 | 半天 |
| ⚪ P4 | 8.1 | Skill 安装命令 | 扩展性 | 2 小时 |
| ⚪ P4 | 8.2 | Skill 热重载 | 开发效率 | 2 小时 |
| ⚪ P4 | 9.1 | 会话自动清理 | 磁盘管理 | 2 小时 |
| ⚪ P4 | 9.2 | 会话压缩边界 | 恢复性能 | 半天 |
| ⚪ P4 | 4.6 | 记忆导出/导入 | 互操作 | 半天 |
| ⚪ P4 | 7.2 | Hook 拒绝工具执行 | 自动化控制 | 2 小时 |

**总工作量估算**：约 15-20 个工作日。全部完成后 mini-code-agent 在每一个维度都 ≥ mewcode-python，同时保持自身的差异化优势（/undo、/fork、/record、/cost、/explain、实验框架）。
