# 配置文件与上下文文件完全指南

本文档说明 Mini-Code-Agent 会读取的**所有**配置文件和上下文文件：每个文件是干什么的、放在哪、怎么改、不改时的默认行为。

---

## 一、总览：三类文件

程序会读取的文件分三类，**性质完全不同**：

| 类别 | 给谁看 | 内容 | 例子 |
|---|---|---|---|
| **配置文件** | 程序 | 行为参数（模型/超时/主题） | `config.toml`、`.env` |
| **上下文文件** | LLM | 自然语言指令（项目约定/个人偏好） | `CLAUDE.md`、`instructions.md` |
| **数据文件** | 程序自动读写 | 记忆/会话/审计（用户一般不手动编辑） | `memory.json`、`sessions/` |

区分方法：**改配置文件影响程序怎么运行，改上下文文件影响 LLM 怎么回答**。

---

## 二、全部文件清单

### 配置文件（程序行为）

| 文件 | 层级 | 优先级 | 说明 |
|---|---|---|---|
| `~/.mini-agent/config.toml` | 用户级 | 低 | 所有项目共用的默认设置 |
| `<项目>/.mini-agent/config.toml` | 项目级 | 中 | 本项目专属，覆盖用户级 |
| `<项目>/.env` | 项目级 | 较高 | API key 等敏感值（gitignore 忽略，不入库） |
| 环境变量（`MINI_AGENT_*` / `OPENAI_*`） | 会话级 | 高 | 临时覆盖 |
| CLI 参数（`--model` 等） | 单次启动 | 最高 | 一次性覆盖 |

**完整优先级链**（右边覆盖左边）：

```
内置默认值 → 用户 config.toml → 项目 config.toml → .env → 环境变量 → CLI 参数
```

### 上下文文件（LLM 指令）

| 文件 | 层级 | 说明 |
|---|---|---|
| `<项目>/AGENT.md` | 项目级 | 项目约定，优先级第 1（社区通用标准） |
| `<项目>/CLAUDE.md` | 项目级 | 项目约定，优先级第 2（Claude Code 生态兼容） |
| `<项目>/.mini-agent/instructions.md` | 项目级 | 项目约定，优先级第 3（本工具专属） |
| `~/.mini-agent/instructions.md` | 用户级 | 全局个人指令（如"回答用中文"），与项目指令**共存**（都注入） |

**项目级三个文件是"三选一"**：按优先级找到第一个非空的就停，不合并。
**用户级与项目级是"共存"**：两者同时注入 system prompt。

### 数据文件（自动管理）

| 文件 | 层级 | 说明 |
|---|---|---|
| `~/.mini-agent/.theme` | 用户级 | `/theme` 命令写入的主题偏好 |
| `~/.mini-agent/memory/user_memory.json` | 用户级 | 跨项目记忆（SESSION_END 自动提取 + `/memory add`） |
| `<项目>/.mini-agent/memory.json` | 项目级 | 项目记忆 |
| `~/.mini-agent/sessions/` | 用户级 | 会话持久化（自动保存/崩溃恢复），超过 `session_cleanup_days` 天的已正常关闭会话启动时自动清理 |
| `~/.mini-agent/audit.jsonl` | 用户级 | 审计日志（`/audit on` 开启后） |
| `~/.mini-agent/recordings/` | 用户级 | 工具链录制（`/record` 保存，`/replay` 读取） |
| `~/.mini-agent/cost_ledger.json` | 用户级 | 成本累计总账（每轮自动写入；`/cost reset` 确认后清零并重置起始日期，删文件等效） |
| `<项目>/.mini-agent/tasks.json` | 项目级 | 持久化任务列表（`/todo` 管理，跨会话保留，手编辑 JSON 也可） |
| `<项目>/.mini-agent/undo_snapshots/` | 项目级 | undo 文件快照（**临时**——会话结束自动清空） |

### 组件生命周期一览

不同数据的存活时长不同，理解生命周期能避免"为什么它没了/为什么它还在"的困惑：

| 数据 | 生命周期 | 崩溃后 |
|---|---|---|
| 对话历史 | 会话内（每轮强制存盘） | 可恢复（启动提示） |
| undo 文件快照 | 会话内，且只留最近 5 轮 | 丢失（undo 本就是会话内操作） |
| **录制中**的步骤（未 stop） | 内存——会话内 | **丢失**，需重录 |
| **已保存**的录制文件 | 磁盘永久 | 不受影响 |
| 模板变量的值（`/replay x k=v`） | **单次回放**——用完即弃，不落盘不进会话 | — |
| 记忆 / 主题 / 配置 | 磁盘永久 | 不受影响 |

关键点：**录制文件是无状态的静态模板**——`{{变量}}` 占位符永远保持原样存在文件里，回放时的替换只发生在内存（构造工具调用的瞬间）。所以换会话、崩溃恢复、多个终端窗口同时回放同一份录制，行为都完全一致，互不干扰。

### 跨组件交互点

三个值得知道的交互（都是良性设计，但行为略微妙）：

1. **回放 × undo 快照**：`/replay` 改的文件会进当前会话的 undo 快照——`/undo` 能撤销一次回放的文件改动。但回放不占对话轮次，如果回放后又对话了一轮再 `/undo`，撤的是对话那轮，回放的改动不在其中。
2. **回放 × LLM 认知**：回放结果不进对话历史——LLM 不知道 `/replay` 改了什么文件，之后让它操作相关文件可能基于过时认知，必要时提醒它重新读文件（`/undo` 后同理）。
3. **录制 × 回放防套娃**：录制进行中执行 `/replay`，回放的调用**不会**被录进去（suspended 保护）——录制里只有 LLM 真实执行的操作。

---

## 快速上手：在任意目录使用 mini-agent

默认情况下，API key 只在有 `.env` 文件的项目目录下生效。要在**任意目录**启动 `mini`，需要做以下**任一**配置：

### 方法一：设置系统环境变量（推荐，一次设置永久生效）

**Windows（PowerShell）**：

```powershell
# 设置 API key（必填）
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-你的key", "User")

# 如果使用第三方 API（DeepSeek、智谱、硅基流动等），还需设置 base URL
[System.Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://你的api地址/v1", "User")

# 可选：设置默认模型
[System.Environment]::SetEnvironmentVariable("MINI_AGENT_MODEL", "deepseek-chat", "User")
```

设置后**重启终端**生效。之后在任何目录执行 `mini` 都可以正常启动。

**macOS / Linux**：

```bash
# 添加到 ~/.bashrc 或 ~/.zshrc
echo 'export OPENAI_API_KEY="sk-你的key"' >> ~/.bashrc
echo 'export OPENAI_BASE_URL="https://你的api地址/v1"' >> ~/.bashrc
echo 'export MINI_AGENT_MODEL="deepseek-chat"' >> ~/.bashrc
source ~/.bashrc
```

### 方法二：用户级配置文件（跨项目共用，不进 git）

创建 `~/.mini-agent/config.toml`：

```bash
# Windows
mkdir "%USERPROFILE%\.mini-agent"
# macOS / Linux
mkdir -p ~/.mini-agent
```

写入内容：

```toml
[llm]
api_key = "sk-你的key"
base_url = "https://你的api地址/v1"
model = "deepseek-chat"
```

### 方法三：项目级 .env 文件（仅当前项目生效）

在目标项目根目录创建 `.env` 文件：

```bash
OPENAI_API_KEY=sk-你的key
OPENAI_BASE_URL=https://你的api地址/v1
MINI_AGENT_MODEL=deepseek-chat
```

> **优先级提醒**：CLI 参数 > 环境变量 > .env > 项目 config.toml > 用户 config.toml > 默认值。高优先级覆盖低优先级。

### 验证配置

在目标目录执行：

```bash
mini --version    # 确认安装成功
mini              # 启动 Agent
```

如果仍报错"未配置 API key"，检查：
1. 终端是否重启过（环境变量需要重启终端生效）
2. 环境变量名是否拼写正确（`OPENAI_API_KEY`，不是 `OPENAI_KEY`）
3. 是否有更高优先级的配置覆盖（如 `.env` 中设了空值）

---

## 三、config.toml 使用说明

### 创建

项目根有模板 `config.toml.example`，复制后按需取消注释：

```bash
# 用户级（推荐个人偏好放这里）
copy config.toml.example "%USERPROFILE%\.mini-agent\config.toml"    # Windows
cp config.toml.example ~/.mini-agent/config.toml                     # macOS/Linux

# 项目级（推荐团队约定放这里，可提交进 git）
mkdir .mini-agent && copy config.toml.example .mini-agent\config.toml
```

### 全部可配段落

```toml
[llm]
provider = "openai"          # "openai"（Chat Completions）| "openai-responses"（Responses API，o1/o3/o4-mini）| "anthropic"
model = "deepseek-chat"      # 模型名
temperature = 0.0
max_tokens = 4096            # 单次回复上限；截断时自动翻倍重试最多 3 次（P44），此值是重试的起点
timeout = 120.0

[tools]
bash_timeout = 120.0         # bash 命令超时（秒）
max_file_size = 10000000     # 文件读取上限（字节）
enabled_tools = ["read_file", "write_file", "edit_file", "delete_file", "bash", "glob", "grep", "spawn_agents", "send_message", "wait_message", "tool_search", "mcp_call"]
denied_paths = ["~/.ssh", "~/.aws", "~/.gnupg"]   # 禁止访问的路径

[memory]
context_window = 128000      # 上下文窗口 token 数（压缩触发用；溢出兜底另用 Provider 从 API 自动探测的真实窗口值，P42）
compression_threshold = 0.75 # 软阈值（75% 时压缩，受熔断器控制）
hard_compression_threshold = 0.90 # 硬阈值（90% 时强制压缩，绕过熔断器）
auto_extract = true          # 会话结束自动提取记忆
spill_threshold_chars = 50000 # 工具结果超过此字符数溢写磁盘只留预览（0 = 禁用）——防大文件撑爆上下文
aggregate_spill_chars = 200000 # 单轮工具结果累计字符预算：超出时按大小降序强制溢写（0 = 禁用）——防"每条不超、合计撑爆"
session_cleanup_days = 30    # 超过此天数的旧会话启动时自动清理（0 = 禁用）——未正常关闭的保留供崩溃恢复
compress_max_failures = 3    # 压缩熔断器：连续 N 次压缩无效后跳过（0 = 禁用）——防已读文件列表过长时的死循环

[security]
permission_mode = "ask"      # "allow"（全放行）| "ask"（询问）| "deny"（全拒绝）
allowed_commands = ["git *", "uv *"]   # 免确认的命令白名单
sandbox = false              # OS 级沙箱（Linux bwrap / macOS seatbelt），true 启用
sandbox_auto_allow = false   # 沙箱下危险命令免确认（deny 规则仍拦）
sandbox_network = false      # 允许沙箱内网络访问

[context]                    # 上下文感知（P25）
instruction_files = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
                             # 项目指令文件名及优先级（列表顺序=优先级，第一个命中即用）
user_instructions_file = "~/.mini-agent/instructions.md"   # 用户级全局指令路径
max_chars = 8000             # 单文件截断长度（字符）

[cost]                       # 成本仪表盘（P29）
budget = 5.0                 # 会话预算上限（元），0 = 不限
total_budget = 50.0          # 累计总账预算上限（元），0 = 不限
currency = "¥"
[cost.pricing.deepseek-chat] # 每模型价格（元/百万 token）
input = 2.0
output = 8.0

# 顶级配置（不属于任何段；注意必须写在所有 [段] 和 [[hooks]] 之前才算顶级）
max_agent_iterations = 50    # ReAct 循环最大迭代数
theme = "default"            # "default" | "dark" | "light"
listener_dirs = ["./.mini-agent/listeners", "~/.mini-agent/listeners"]
                             # 事件监听插件目录（issue #166）：目录下每个 *.py 文件是一个插件，
                             # 定义 register(bus)（订阅特定事件）或 on_event(event)（自动订阅全部事件，
                             # 同步/异步均可）。插件异常被隔离并记日志，不影响主流程。用于统计/调试，
                             # 如把所有事件落盘 JSONL。下划线开头的文件跳过。

# 声明式 Hook 规则——命中即拒绝工具执行（默认）或弹窗确认，reason 回给 LLM
# 可写多条 [[hooks]]；非法条目告警跳过不阻断启动
[[hooks]]
tool = "write_file"          # 工具名 fnmatch 模式（"bash"、"write_*"，默认 "*" 全部）
arg = "file_path"            # 可选：只检查此参数（缺省检查所有参数值）
contains = "docs/spec"       # 可选：参数值包含此子串才触发（缺省对该工具的所有调用生效）
reason = "docs/spec.md 项目策略只读"   # 拒绝原因，LLM 会收到并调整策略

[[hooks]]
tool = "bash"
contains = "curl"
reason = "外网下载被项目策略禁止"

[[hooks]]
tool = "bash"
regex = 'rm\s+-rf'           # 可选：re.search 正则（与 contains 同时给则须同时命中；非法正则告警跳过该条）
reason = "破坏性删除被项目策略禁止"

[[hooks]]
tool = "bash"
contains = "git push"
action = "confirm"           # 可选："block"（默认）直接拒绝；"confirm" 弹 y/a/n 确认框
reason = "push 会影响远程仓库"

# MCP 服务器
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"

# [mcp.servers.remote-api]
# url = "http://localhost:8080/mcp"
# transport = "http"
# headers = { Authorization = "Bearer your-token-here" }   # 可选认证头
```

### 修改后生效方式

改完 config.toml **重启 `mini` 生效**（启动时读取一次，无热重载）。

### 成本预算详解（[cost] 段）

两套预算独立工作，都在**每轮对话结束时**检查：

| 配置项 | 统计范围 | 清零方式 |
|---|---|---|
| `budget` | 本次会话（mini 启动 → /exit 或关窗口） | 重启自动清零 |
| `total_budget` | 累计总账（首次使用至今，跨会话跨项目） | `/cost reset` 手动清零 |

**警告阈值**（两种预算相同，写死不可配）：

| 已用比例 | 表现 |
|---|---|
| < 80% | 静默，无任何提示 |
| ≥ 80% | 黄色警告行：`会话预算警告: ¥4.12 / ¥5.00 (82%)` |
| ≥ 100% | 红色警告行：`⚠ 累计总预算超支: ¥51.30 / ¥50.00` |

只提醒不阻断——超支后 LLM 照常工作，是否停手由你决定。两种预算同时越线会各出一条警告。

**怎么修改预算**：编辑 `~/.mini-agent/config.toml` 的 `[cost]` 段（没有该文件先从 `config.toml.example` 复制），改 `budget` / `total_budget` 数值，重启 `mini` 生效。设为 0 或删掉该行 = 不限。

**注意**：预算基于金额计算，所以**必须先配置 `[cost.pricing.<模型名>]` 价格**——没有价格时成本恒为 0，预算永远不会触发。

### Hook 规则详解（[[hooks]] 段）

**作用**：不写一行 Python，用配置声明"什么工具调用要被拒绝或需要确认"。`action = "block"`（默认）命中即**不执行**，LLM 收到 `Blocked by hook: <reason>` 后会调整策略（换方案或告知用户），不会瞎重试；`action = "confirm"` 命中弹 y/a/n 确认框由你裁决——y 放行一次、a 本会话内同一规则不再询问、n 拒绝（LLM 收到 `Denied by user: <reason>`）。

**写在哪**：用户级 `~/.mini-agent/config.toml`（跨项目生效）或项目级 `.mini-agent/config.toml`（仅本项目）。
**层级语义（注意）**：项目级定义了 `[[hooks]]` 时**整体替换**用户级的规则列表（不合并）——想两边都生效，把用户级规则复制进项目级。

**全部字段**：

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `tool` | 否 | `"*"` | 工具名 fnmatch 模式：`"bash"` 精确、`"write_*"` 前缀族、`"*"` 全部工具 |
| `arg` | 否 | 空 | 只检查此参数的值（如 `"file_path"`）；缺省检查**所有**参数值 |
| `contains` | 否 | 空 | 参数值包含此子串才触发 |
| `regex` | 否 | 空 | 参数值 `re.search` 命中此正则才触发；非法正则**告警跳过该条**，不阻断启动 |
| `reason` | 建议填 | 自动生成 | 拒绝/确认原因，原样回给 LLM（confirm 时也显示在弹窗里）——写清楚"为什么+该怎么办"效果最好 |
| `action` | 否 | `"block"` | `"block"` 直接拒绝；`"confirm"` 弹 y/a/n 确认框（a = 本会话内同一规则不再询问）；其他值告警跳过 |
| `event` | 否 | `"pre_tool"` | 目前只支持 `pre_tool`，其他值告警跳过 |
| `reject` | 否 | `true` | 目前只支持 `true`，`false` 告警跳过 |

**匹配语义**：
- `contains` 和 `regex` 都不写 = 该工具的**所有调用**都触发（block 等于禁用工具，但带解释）
- `contains` 和 `regex` 同时写 = **两者都命中**才触发（AND）
- 多条 `[[hooks]]` 规则 = 任一命中即触发（OR），block 与 confirm 规则可混用
- 匹配对参数值做 `str()` 后比较，数字/布尔参数也能匹配

**TOML 语法注意**：
1. `[[hooks]]` 必须写在所有顶级键（`max_agent_iterations`、`theme` 等）**之后**——顶级键出现在 `[[hooks]]` 之后会被归入该规则条目导致解析错乱
2. `regex` 的值用**单引号**（TOML literal string）：`regex = 'rm\s+-rf'`——双引号里 `\s` 是非法转义会报错

**验证是否生效**：启动时看到 `Loaded N hook rule(s) from config` 即已加载；让 Agent 触发一条规则，block 规则显示错误 `Blocked by hook: <你的 reason>`，confirm 规则弹出确认框（拒绝后 LLM 收到 `Denied by user: <你的 reason>`）。

**常用配方**：

```toml
# 目录只读锁
[[hooks]]
tool = "write_file"
arg = "file_path"
contains = "docs/spec"
reason = "docs/spec.md 项目策略只读，修改请联系维护者"

# 禁外网下载
[[hooks]]
tool = "bash"
contains = "curl"
reason = "外网下载被项目策略禁止"

# 拦破坏性删除（正则防变体，不误伤 echo 'rm-rf' 之类）
[[hooks]]
tool = "bash"
regex = 'rm\s+-rf'
reason = "破坏性删除被项目策略禁止"

# 禁直推主干（AND：是 push 且带 --force 或指向 main）
[[hooks]]
tool = "bash"
contains = "git push"
regex = '--force|main'
reason = "禁止强推/直推 main，请走 PR"

# 整体禁用一个工具（带解释，LLM 会换路子而不是重试）
[[hooks]]
tool = "delete_file"
reason = "本项目禁止 Agent 删除文件，请让用户手动删"

# 全工具防泄密（tool 缺省 = *，检查一切工具的一切参数）
[[hooks]]
contains = "internal.corp.com"
reason = "内网地址不允许出现在工具调用中"

# 敏感操作需人工确认（不禁用，但每次问你；按 a 本会话不再问）
[[hooks]]
tool = "bash"
contains = "git push"
action = "confirm"
reason = "push 会影响远程仓库"
```

**边界**：配置层做"拒绝"（block）与"强制确认"（confirm）。改写参数（MODIFY）、观察记录需写 Python Hook 或 EventBus 订阅者——见 agent-architecture.md S04。confirm 的裁决弹窗由主 Agent 的 terminal 执行；子 Agent（spawn_agents）不加载 `[[hooks]]` 规则、无确认 UI，代码注册的 CONFIRM hook 在无 UI 时一律安全拒绝。

---

## 四、上下文文件使用说明

### 项目指令（AGENT.md / CLAUDE.md / .mini-agent/instructions.md）

**作用**：把项目约定写进去，LLM 启动即知，不用每次对话解释。

**写什么**：构建/测试命令、目录结构约定、代码规范、架构要点。例：

```markdown
# 我的项目

## 常用命令
- 测试：uv run pytest tests/
- Lint：uv run ruff check src/

## 约定
- 全类型注解，line-length 100
- 测试放 tests/unit/ 和 tests/integration/
```

**默认查找逻辑**（不改配置时）：

```
项目根按顺序找：AGENT.md → CLAUDE.md → .mini-agent/instructions.md
找到第一个非空文件 → 注入 system prompt → 启动显示 "context: loaded <文件名>"
三个都没有 → 静默跳过（无任何提示）
超过 8000 字符 → 截断并标注 "(truncated)"
```

**修改文件名/优先级**：在 config.toml 的 `[context]` 段改 `instruction_files` 列表：

```toml
[context]
instruction_files = ["MY_RULES.md"]        # 只认这一个文件
# 或者调整顺序让 CLAUDE.md 优先：
# instruction_files = ["CLAUDE.md", "AGENT.md"]
```

**生效时机**：启动时读取一次。改了指令文件内容需重启 `mini`。

### 用户级全局指令（~/.mini-agent/instructions.md）

**作用**：跨所有项目的个人偏好——不管在哪个目录启动 `mini` 都注入。

**写什么**：语言偏好、回答风格等和具体项目无关的指令。例：

```markdown
- 始终用中文回答
- 回答尽量简洁，不要重复我的问题
```

**与项目指令的关系**：**共存**——两者都注入（用户级在前、项目级在后），不是二选一。

**修改路径**：config.toml `[context]` 段的 `user_instructions_file`：

```toml
[context]
user_instructions_file = "~/my-notes/ai-rules.md"
```

---

## 五、常见问题

**Q：config.toml 和 CLAUDE.md 都是"项目级"，有什么区别？**
A：config.toml 是给**程序**读的参数（改了影响程序行为，如超时/主题）；CLAUDE.md 是给**LLM**读的自然语言（改了影响 LLM 的回答，程序行为不变）。

**Q：项目里同时有 AGENT.md 和 CLAUDE.md 会怎样？**
A：只读 AGENT.md（优先级高的赢），CLAUDE.md 被忽略。不合并是有意设计——避免两个文件内容冲突时 LLM 无所适从。

**Q：为什么我改了 CLAUDE.md 但 LLM 没反应？**
A：指令文件启动时读取一次，改完要重启 `mini`。

**Q：API key 应该放哪？**
A：`.env` 文件（已被 gitignore 忽略）或环境变量。**不要**放 config.toml——项目级 config.toml 可能被提交进 git 泄露。

**Q：怎么确认指令注入成功了？**
A：启动时看有没有 `context: loaded <文件名>` 一行；或问 LLM 一个只有指令文件里写了的问题（如项目的测试命令），它不调工具直接答对就是注入成功。

**Q：记忆（memory.json）和指令文件（instructions.md）都会注入，区别是什么？**
A：指令文件是**你手写**的静态约定，启动注入；记忆是**LLM 自动提取**的动态积累（也可 `/memory add` 手动加），每次 LLM 调用前注入。前者适合稳定的规范，后者适合会话中发现的偏好。

---

## 六、自动记忆提取详解

记忆系统**完全自动**——不需要手动打开任何开关，默认开启。

### 工作流程

```
对话中你说了偏好/约定（"我喜欢简洁注释"、"项目用 uv"等）
  ↓ /exit 或关窗口退出
SESSION_END hook → LLM 分析最近 20 条消息 → 提取 → 去重 → 存盘
  ↓ 下次启动 mini（任何时候，甚至重启电脑后）
PRE_LLM hook → 自动读取记忆 → 注入 system prompt → LLM 从第一轮就"知道"
```

### 什么会被提取（LLM 的筛选规则）

| 类别 | 会提取的 | 不会提取的 |
|---|---|---|
| **preference 偏好** | "我喜欢简洁的代码注释" | "你好"（打招呼） |
| **convention 约定** | "这个项目用 uv 管理依赖" | "帮我看看这个 bug"（任务细节） |
| **fact 事实** | "Python 版本要求 3.11+" | "好的谢谢"（语气词） |
| — | — | LLM 自己说的建议（只提取**用户**说的） |

### 筛选条件（三层）

**第一层：门槛**——本次会话的用户消息少于 5 条 → 不触发提取（太短没价值）。

**第二层：去重**——新提取的和已有记忆对比，命中任一条就丢弃：
- 完全相同（大小写不敏感）
- 已有记忆包含新提取的内容（子串）
- 60% 以上的词重叠（防"换个说法重复记"——如"always use type hints on functions"和"use type hints on all functions always"是同一件事）

**第三层：LLM prompt 规则**——告诉 LLM 只提取用户明确说的、跳过临时内容、每条自包含可读、1-2 句话、没有值得记的返回空。

### 存储与有效期

| 项 | 说明 |
|---|---|
| 存储位置 | `~/.mini-agent/memory/user_memory.json`（跨项目）+ `<项目>/.mini-agent/memory.json`（项目级） |
| 有效期 | **永久**——文件在磁盘上不删就一直在 |
| 注入方式 | 每次 LLM 调用前自动注入 system prompt（最多 10 条） |
| 手动添加 | `/memory add 我喜欢某某某`（不等退出，立即生效） |
| 查看 | `/memory` |
| 删除 | `/memory delete <ID或关键词>`（ID 可从 `/memory` 列表复制，也可用内容关键词匹配） |

### 关闭/调试

如果发现自动提取质量差（弱模型理解偏差导致垃圾记忆），在 config.toml 关掉：

```toml
[memory]
auto_extract = false   # 关闭后改用 /memory add 手动添加
```

调试时可在 `/exit` 前 `/memory` 查看上次提取了什么，不满意就手动编辑 JSON 文件删掉。

### 与 CLAUDE.md（上下文感知）的区别

| | CLAUDE.md / AGENT.md | 记忆（memory.json） |
|---|---|---|
| 来源 | 你手写 | LLM 自动提取 + `/memory add` |
| 内容性质 | 稳定的项目规范 | 动态积累的偏好 |
| 注入时机 | 启动时一次 | 每次 LLM 调用前 |
| 适用范围 | 本项目 | 跨项目（用户级）或本项目（项目级） |
| 修改方式 | 编辑 md 文件 | 自动 / `/memory add` / 编辑 JSON |

**两者共存互补**——CLAUDE.md 写"本项目用 uv、测试放 tests/"这种稳定规范；记忆记"用户喜欢简洁注释"这种个人偏好。

---

## 权限规则文件（permissions.toml）

自定义哪些命令/路径免确认放行、哪些无条件拒绝——不用改代码。

**位置**（两级，同时生效）：

| 文件 | 作用域 |
|---|---|
| `~/.mini-agent/permissions.toml` | 用户级——所有项目 |
| `<项目>/.mini-agent/permissions.toml` | 项目级——仅当前项目 |

**格式**（完整示例见项目根 `permissions.toml.example`）：

```toml
[commands]
allow = ["git push origin dev", "docker build *"]   # 免确认放行（危险命令也行）
deny = ["docker rm *"]                               # 无条件拒绝

[paths]
allow = ["D:/shared/workspace/*"]    # 放行项目外路径（默认项目外要确认）
deny = ["*secrets*", "*.key"]        # 拒绝访问（项目内路径也拦）
```

**优先级**：`deny 规则 > allow 规则 > 内置默认`（危险命令确认 / 敏感路径拒绝 / 项目内放行）。deny 最优先——即使路径在项目内也会被拦。

**匹配语法**：glob 风格。`git *` 匹配 `git status` 但不匹配 `github`；`*secrets*` 匹配任何含 secrets 的路径。

**验证是否生效**：`/trace on` 后触发相关操作，trace 行会显示 `rule:<pattern>` 作为判定依据。

**修改后生效**：重启 mini（启动时加载一次）。或在运行中使用 `/allow` `/deny` 命令实时添加规则——带 `--save` 标志的规则会写入项目级 permissions.toml，下次启动自动加载。

**运行时管理**（P78）：
```
/allow command "docker *"          # 本会话放行所有 docker 命令
/deny path "*/secrets/*"           # 本会话拒绝 secrets 路径
/allow command "npm *" --save      # 放行并持久化到 .mini-agent/permissions.toml
/deny                              # 列出当前所有 DENY 规则
```

---

## OS 级沙箱（sandbox）

内核级别隔离 bash 命令的执行环境——即使命令通过了权限检查，也只能在受限范围内操作。

**支持平台**：

| 平台 | 后端 | 安装 |
|---|---|---|
| Linux | bubblewrap (bwrap) | `sudo apt install bubblewrap` 或 `yum install bubblewrap` |
| macOS | Seatbelt (sandbox-exec) | 系统自带（`/usr/bin/sandbox-exec`） |
| Windows | 不支持 | 保持现有正则拦截 + permissions.toml 规则 |

**启用**：

```toml
# config.toml
[security]
sandbox = true               # 开启沙箱
sandbox_auto_allow = false    # 可选：沙箱下危险命令免确认
sandbox_network = false       # 可选：允许网络访问
```

**沙箱内的文件权限**（代码固定，非用户配置）：

| 路径 | 权限 |
|---|---|
| 工作目录（项目目录） | 可读可写 |
| `/tmp` | 可读可写 |
| `~/.mini-agent` | 只读（防命令篡改配置） |
| 其余整个文件系统 | 只读 |

**sandbox_auto_allow 与 permissions.toml 的配合**：

```
命令到达
  ↓
① permissions.toml deny 规则？→ 拒绝（沙箱也救不了）
  ↓
② permissions.toml allow 规则 / session grant？→ 放行
  ↓
③ 危险命令？
     sandbox_auto_allow=true → 放行（内核兜底）
     sandbox_auto_allow=false → 弹窗确认
  ↓
④ 执行：有沙箱 → 内核隔离执行（只读 rootfs）
       无沙箱 → 原样执行
```

- **permissions.toml** 管"要不要执行这条命令"
- **sandbox** 管"执行时能碰哪些文件"
- **deny 规则最大**，谁都绕不过——sandbox_auto_allow 不影响它

**验证是否生效**：`/trace on` 后执行命令，trace 行会显示 `sandbox_auto_allow` 作为判定依据（沙箱下免确认时）。

**Windows**：`sandbox = true` 但无 bwrap/sandbox-exec → 静默退回，功能不受影响、无报错。

---

*相关文档：终端输出说明见 output-guide.md，各系统终端打开方法与兼容性见 terminal-guide.md，能力对照见 capabilities.md，架构原理见 agent-architecture.md。*
