# 配置文件与上下文文件完全指南

> English version: [en/config-guide.md](en/config-guide.md)

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

另有**权限规则文件** `permissions.toml`（用户级 `~/.mini-agent/` + 项目级 `<项目>/.mini-agent/`，两级叠加），独立于 config.toml（因 `[tools]` 节名冲突无法合并），详见下方"权限规则文件"章节。

项目根目录提供三个模板文件供复制使用：`config.toml.example`、`permissions.toml.example`、`.env.example`。

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
| `~/.mini-agent/sessions/` | 用户级 | 会话持久化（自动保存/崩溃恢复），正常关闭超 `session_cleanup_days`（默认 30）天、崩溃会话超 `crashed_session_cleanup_days`（默认 40）天的启动时自动清理 |
| `~/.mini-agent/audit.jsonl` | 用户级 | 审计日志（`/audit on` 开启后） |
| `~/.mini-agent/recordings/` | 用户级 | 工具链录制（`/record` 保存，`/replay` 读取） |
| `~/.mini-agent/cost_ledger.json` | 用户级 | 成本累计总账（每轮自动写入；`/cost reset` 确认后清零并重置起始日期，删文件等效） |
| `<项目>/.mini-agent/tasks.json` | 项目级 | 持久化任务列表（`/todo` 管理，跨会话保留，手编辑 JSON 也可） |
| `<项目>/.mini-agent/undo_snapshots/` | 项目级 | undo 文件快照（**临时**——会话结束自动清空） |
| `~/.mini-agent/input_history` | 用户级 | 跨会话输入历史（↑ 键翻历史，自动写入） |

### 组件生命周期一览

不同数据的存活时长不同，理解生命周期能避免"为什么它没了/为什么它还在"的困惑：

| 数据 | 生命周期 | 崩溃后 |
|---|---|---|
| 对话历史 | 会话内（每轮强制存盘） | 可恢复（启动提示） |
| undo 文件快照 | 会话内，且只留最近 N 轮（`undo_keep_turns` 默认 5） | 丢失（undo 本就是会话内操作） |
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

## 三、快速上手：在任意目录使用 mini-agent

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

## 四、config.toml 使用说明

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
model = "deepseek-chat"      # 模型名（默认 "gpt-4o"）
api_key = "sk-..."           # API 密钥（建议放 .env 而非此处）
base_url = "https://api.deepseek.com/v1"  # API 地址（默认 None，用 Provider 内置地址）
temperature = 0.0
max_tokens = 4096            # 单次回复上限；截断时自动翻倍重试最多 3 次（P44），此值是重试的起点
timeout = 120.0
thinking = false             # 发送侧 extended thinking：Anthropic thinking 参数 / Responses reasoning 参数（tech-notes §110）；也可用 MINI_AGENT_THINKING 或按 profile 的 MODEL_<名称>_THINKING 开启；Responses 的 effort 用 extra = {reasoning_effort = "high"} 调整（默认 medium）；各场景示例见下方"思考流（extended thinking）配置详解"
# extra = {}                 # 透传给 API 的额外参数（如 top_p、stop、qwen 混合推理模型的 enable_thinking = true）；核心字段（model/messages）不可被覆盖

[tools]
bash_timeout = 120.0         # bash 命令超时（秒）
max_file_size = 10000000     # 文件读取上限（字节）
enabled_tools = ["read_file", "write_file", "edit_file", "delete_file", "bash", "glob", "grep", "spawn_agents", "send_message", "wait_message", "tool_search", "mcp_call", "ask_user", "exit_plan_mode", "task_create", "task_get", "task_list", "task_update", "load_skill", "install_skill", "synthetic_output"]
allowed_paths = []           # 额外放行的项目外路径（默认空）
denied_paths = ["~/.ssh", "~/.aws", "~/.gnupg"]   # 禁止访问的路径
enforce_read_before_edit = true  # 编辑前必读门：edit/覆盖 write 前必须先 read 且读后未被外部改动；false 关闭

[memory]
context_window = 128000      # 上下文窗口 token 数（压缩触发用；溢出兜底另用 Provider 从 API 自动探测的真实窗口值，P42）
compression_threshold = 0.75 # 软阈值（75% 时压缩，受熔断器控制）
hard_compression_threshold = 0.90 # 硬阈值（90% 时强制压缩，绕过熔断器）
auto_extract = true          # 会话结束自动提取记忆
spill_threshold_chars = 50000 # 工具结果超过此字符数溢写磁盘只留预览（0 = 禁用）——防大文件撑爆上下文
aggregate_spill_chars = 200000 # 单轮工具结果累计字符预算：超出时按大小降序强制溢写（0 = 禁用）——防"每条不超、合计撑爆"
session_cleanup_days = 30    # 正常关闭超过此天数的会话启动时自动清理（0 = 禁用）
crashed_session_cleanup_days = 40  # 崩溃会话超过此天数也清理（0 = 永久保留）——比正常 30 天更宽松（崩溃有恢复价值）
compress_max_failures = 3    # 压缩熔断器：连续 N 次压缩无效后跳过（0 = 禁用）——防已读文件列表过长时的死循环
llm_summarize = true         # LLM 语义摘要压缩（默认开启）；false 退回提取式截断（无 LLM 调用）
undo_keep_turns = 5          # /undo 文件快照保留最近 N 轮——调大可回滚更早的文件改动
recall_threshold = 10        # 记忆超过此数量时启用 LLM 选择性召回（≤ 阈值时全部注入）
recall_top_k = 5             # 选择性召回时 LLM 挑选的最大条数
recall_timeout = 8.0         # 召回预取超时秒数——挑选与主 LLM 调用并行（不增加首 token 延迟），超时降级注入头部条目
consolidation_threshold = 20 # 记忆超过此数量时自动 LLM 语义合并（0 = 禁用）
auto_consolidate = true      # 启动时后台整固：双门槛满足时无感合并记忆（锁防并发、失败回滚）
consolidate_min_hours = 24.0 # 后台整固门槛一：距上次整固的小时数
consolidate_min_sessions = 5 # 后台整固门槛二：期间活跃的新会话数
# persistent_memory_dir = "~/.mini-agent/memory"     # 用户级记忆目录
# project_memory_file = ".mini-agent/memory.json"    # 项目级记忆文件

[security]
permission_mode = "ask"      # "allow"（全放行）| "ask"（询问）| "deny"（全拒绝）
approval_mode = "default"    # 启动时的会话级权限模式："default"（危险命令/项目外路径确认）|
                             # "accept-edits"（文件写入自动放行，危险命令/项目外读取仍确认）|
                             # "plan"（只读计划模式）| "bypass"（全放行，DENY 规则和敏感路径除外）。
                             # 非法值告警并回退 default；运行时用 /mode 切换。
                             # enable_plan_mode = true 等价于 approval_mode = "plan" 且优先级更高。
allowed_commands = ["git *", "uv *"]   # 免确认的命令白名单（默认空），命中即放行（含危险命令）
denied_commands = ["rm -rf /", "sudo", "curl|sh", "wget|sh"]   # 无条件拒绝列表（默认值），命中即拒绝
# 注意：denied_commands 是 glob 精确匹配拒绝。另有 28 条硬编码正则（DANGEROUS_COMMAND_PATTERNS）
# 用于弹窗确认（删除类 rm/del/rmdir/rd 任意形态均命中——裸 rmdir、rm/del 单文件也算，不限于
# -rf、/s、/q；另有 sudo/chmod 777/mkfs/dd/git push/commit/reset/stash/rebase/checkout/
# restore/clean/Windows format/curl|sh/wget|sh/python -c/node -e/perl -e/ruby -e/
# sh -c/bash -c/powershell -Command/pwsh -c/cmd /c）——这些不可配，但可通过
# allowed_commands 放行或 sandbox_auto_allow 免确认。
worktree_base_dir = ".mini-agent/worktrees"  # Git worktree 隔离目录
worktree_max_age_days = 7    # 超过此天数的干净 worktree 启动时自动清理（0 = 禁用）
sandbox = true               # OS 级沙箱（Linux bwrap/unshare / macOS seatbelt / Windows 双模式），默认开启
sandbox_auto_allow = false   # 沙箱下危险命令免确认（deny 规则仍拦）
sandbox_network = false      # 允许沙箱内网络访问

[context]                    # 上下文感知（P25）
instruction_files = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
                             # 项目指令文件名及优先级（列表顺序=优先级，第一个命中即用）
user_instructions_file = "~/.mini-agent/instructions.md"   # 用户级全局指令路径
max_chars = 8000             # 单文件截断长度（字符，展开后整体截断）
max_include_depth = 5        # @-include 递归展开最大深度（0 禁用）

[cost]                       # 成本仪表盘（P29）
budget = 5.0                 # 会话预算上限（元），0 = 不限（默认 0）
total_budget = 50.0          # 累计总账预算上限（元），0 = 不限（默认 0）
currency = "¥"
[cost.pricing.deepseek-chat] # 每模型价格（元/百万 token）
input = 2.0
output = 8.0
# cache_read = 0.5            # 可选：缓存读取价（未配则按 input 价计）
# cache_creation = 3.0        # 可选：缓存创建价（未配则按 input 价计）

# 顶级配置（不属于任何段；注意必须写在所有 [段] 和 [[hooks]] 之前才算顶级）
max_agent_iterations = 80    # ReAct 循环最大迭代数（主循环与未指定类型的 SubAgent 共用；
                             # /spawn --type 显式选类型时采纳类型档案预算，见 P80）
max_consecutive_denials = 1  # 确认框连续被拒 N 次后熔断停机、回问用户（危险命令/项目外路径/hook 确认；
                             # 默认 1 = 拒一次即停；调大可给被拒后修正重试的空间。防止被拒后继续找绕过路径）
theme = "default"            # "default" | "dark" | "light"
collapse_tool_calls = false  # 只读工具（read_file/glob/grep）同轮 ≥2 次折叠为一行
                             # "✓ Done (N tool uses · Xs)" 摘要；默认 false（逐条完整显示），
                             # 设 true 开启折叠
streaming_tool_execution = true  # 流式期间工具调用一组装完成就开始执行（false 等流结束再执行）
enable_plan_mode = false     # 启动时进入只读计划模式（/plan on 运行时切换）；
                             # 等价于 [security].approval_mode = "plan" 且优先级更高
# self_verify = false        # 实验性：LLM 自动验证工具结果
# planner_profile = ""       # /team Planner 使用的 LLM Profile 名（空 = 用主模型）
# worker_profile = ""        # SubAgent worker 使用的 LLM Profile 名（空 = 用主模型）
skill_dirs = ["./skills", "~/.mini-agent/skills"]
                             # 技能包目录：每个子目录含 SKILL.md（YAML 前置 + prompt 正文）
listener_dirs = ["./.mini-agent/listeners", "~/.mini-agent/listeners"]
                             # 事件监听插件目录：目录下每个 *.py 文件是一个插件，
                             # 定义 register(bus)（订阅特定事件）或 on_event(event)（自动订阅全部事件，
                             # 同步/异步均可）。插件异常被隔离并记日志，不影响主流程。用于统计/调试，
                             # 如把所有事件落盘 JSONL。下划线开头的文件跳过。
plugin_dirs = ["./.mini-agent/plugins", "~/.mini-agent/plugins"]
                             # 插件目录：目录下每个 *.py 文件是一个插件（`_` 开头跳过），
                             # 可定义 register(ctx)（全控钩子，定义时优先且只运行它）或
                             # register_tools(registry) / register_commands(registry) /
                             # register_skills(registry) 专用钩子，注册工具/斜杠命令/技能。
                             # pip 包插件不走此目录，改在包内声明 entry point：
                             #   [project.entry-points."mini_agent.plugins"]
                             #   my_plugin = "my_pkg.plugin"
                             # 加载顺序：entry point 先、目录后，重名时目录文件让位并告警。
                             # 异常三层隔离（导入/钩子/运行时），坏插件绝不影响主流程。
                             # 插件工具不受 [tools].enabled_tools 白名单约束（安装即 opt-in）。
                             # 示例插件见 examples/plugins/word_count_plugin.py；/plugins 查看已加载。
# disabled_plugins = ["some_plugin"]
                             # 禁用插件：按 entry-point 名或文件名（去 .py 后缀）匹配

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
transport = "stdio"                  # "stdio"（子进程）| "http"（远程）| "sse"
loading = "eager"                    # "eager"（默认）| "native"（Anthropic 原生延迟）| "dispatch"（按需搜索+调用）

# [mcp.servers.remote-api]
# url = "http://localhost:8080/mcp"
# transport = "http"
# headers = { Authorization = "Bearer your-token-here" }   # 可选认证头
# loading = "dispatch"               # 大量工具时用延迟加载；Anthropic 官方端点可用 "native"（非官方自动降级 dispatch）
```

### 自定义 Agent 类型

在 `.mini-agent/agents/`（项目级）或 `~/.mini-agent/agents/`（用户级）放 `.md` 文件即可定义新的 agent 类型，用于 `/spawn --type <name>` 和 `spawn_agents` 工具。**一个 .md 文件定义一个类型**，想要多个类型就创建多个文件。

**完整示例**（`.mini-agent/agents/reviewer.md`）：

```markdown
---
name: reviewer
description: Code review specialist
allowed_tools:
  - read_file
  - glob
  - grep
  - bash
max_iterations: 25
---
You are a code review agent. Read code and report issues.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}
Budget: {iteration_budget} rounds.
```

**frontmatter 字段说明**：

| 字段 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `name` | ✅ 是 | — | 类型标识符，用于 `/spawn --type <name>`。只允许小写字母、数字、下划线、连字符（`[a-z0-9_-]+`） |
| `description` | 否 | `""` | 一行描述，出现在 `spawn_agents` 工具的 schema 中供 LLM 参考选择 |
| `allowed_tools` | 否 | 全部工具 | 该类型 agent 可使用的工具白名单。**省略则可用全部 21 个内置工具**。每行一个，格式 `  - 工具名` |
| `max_iterations` | 否 | `30` | agent 的最大迭代轮数（think→act 循环上限），超过后强制停止 |

**`allowed_tools` 可填的工具名**（从 `[tools] enabled_tools` 的 21 个内置工具中选）：

| 工具名 | 用途 | 只读 |
|---|---|---|
| `read_file` | 读文件内容 | ✅ |
| `glob` | 按模式搜索文件名 | ✅ |
| `grep` | 按正则搜索文件内容 | ✅ |
| `bash` | 执行 shell 命令 | 取决于命令 |
| `write_file` | 创建/覆盖文件 | ❌ |
| `edit_file` | 精确替换文件中的文本 | ❌ |
| `delete_file` | 删除文件 | ❌ |
| `spawn_agents` | 派生子 agent（子 agent 中不可用） | — |
| `send_message` | 向其他 agent 发消息 | — |
| `wait_message` | 等待其他 agent 的消息 | — |
| `tool_search` | 搜索 MCP 工具 | ✅ |
| `mcp_call` | 调用 MCP 工具 | 取决于工具 |
| `ask_user` | 向用户提问 | — |
| `exit_plan_mode` | 请求退出计划模式（需用户批准计划，拒绝则保持只读） | — |
| `task_create` / `task_get` / `task_list` / `task_update` | 任务板 CRUD | — |
| `load_skill` / `install_skill` | 加载/安装技能 | — |
| `synthetic_output` | 子 agent 以结构化 JSON 返回结果 | ✅ |

**典型组合**：只读审查类 agent 填 `[read_file, glob, grep, bash]`；全能 worker 不写此字段（省略 = 全部可用）。

**body（`---` 分隔线之后的部分）** 是发给 agent 的 system prompt 模板。支持 4 个占位符，运行时自动替换：

| 占位符 | 替换为 | 示例值 |
|---|---|---|
| `{working_dir}` | agent 的工作目录绝对路径 | `D:\Projects\my-app` |
| `{platform}` | 操作系统平台 | `win32` / `linux` / `darwin` |
| `{shell}` | 当前 shell 类型 | `cmd` / `bash` / `zsh` |
| `{iteration_budget}` | max_iterations 的值 | `25` |

不要使用这 4 个以外的 `{xxx}` 占位符，否则文件会被拒绝加载。普通花括号写法（如 JSON 示例）请用 `{{` `}}` 转义。

**使用方式**：

```bash
/spawn --type reviewer 审查 src/main.py        # 命令行指定
```

或让 LLM 自主选择（`spawn_agents` 工具的 `agent_type` 字段会自动列出所有已注册类型含自定义的）。

**优先级**：项目级 > 用户级 > 内置 4 种（explore/plan/worker/verify）。同名时后者覆盖前者。启动时加载，有自定义类型时终端提示 `Loaded N custom agent type(s)`。

**配置目录**（一般不需要改，默认值已覆盖常见场景）：

```toml
agent_dirs = ["~/.mini-agent/agents", "./.mini-agent/agents"]
```

### 编辑前必读门（read-before-edit）

`[tools] enforce_read_before_edit`（默认 `true`）控制一道文件安全门：`edit_file` 和覆盖**已存在**文件的 `write_file` 必须满足两个条件才放行——① 本会话内先用 `read_file` 读过该文件；② 读后文件未被外部改动（mtime 比对）。目的：防止 LLM 基于想象或过期的内容盲改文件。新建文件的 write 和 delete_file 不受限。

被拦时工具返回的报错（LLM 看到后通常会自动先读再重试，无需人工干预）：

- `File has not been read yet. Read it first before editing (read-before-edit safety).` —— 该文件从未被读过
- `File has been modified since it was last read. Read it again before editing (content may be stale).` —— 读后被外部改过（你在编辑器里改了、git 操作改了等）

关闭方式（写入项目级 `.mini-agent/config.toml` 或用户级 `~/.mini-agent/config.toml`，重启生效）：

```toml
[tools]
enforce_read_before_edit = false
```

注意：门禁只约束 `edit_file`/`write_file` 两个文件工具，bash 里的 `sed` 等命令不经过此门（命令风险由权限系统管控）；主 Agent 与每个 SubAgent 各持独立的已读记录。设计缘由见 `docs/tech-notes.md` §84。

### 多模型 Profile（环境变量配置）

预配多套模型参数，运行时 `/model` 一键切换。全部通过环境变量定义：

```bash
# 定义两个 Profile：fast 和 strong
MINI_AGENT_MODELS=fast,strong

# fast Profile 参数
MODEL_FAST_MODEL=deepseek-chat
MODEL_FAST_API_KEY=sk-fast-key
MODEL_FAST_BASE_URL=https://api.deepseek.com/v1

# strong Profile 参数（可切换 Provider）
MODEL_STRONG_MODEL=claude-sonnet-4-20250514
MODEL_STRONG_PROVIDER=anthropic
MODEL_STRONG_API_KEY=sk-ant-strong-key
```

运行时：
```
/model           # 列出所有可用 Profile
/model fast      # 切换到 fast（DeepSeek）
/model strong    # 切换到 strong（Claude）
```

**强弱模型混编**——Planner 用强模型规划、Worker 用快模型执行：
```bash
MINI_AGENT_PLANNER_PROFILE=strong    # /team 的 Planner 用 strong Profile
MINI_AGENT_WORKER_PROFILE=fast       # SubAgent worker 用 fast Profile
```

### 思考流（extended thinking）配置详解

思考流指模型回答前的推理过程，终端里以暗斜体显示在正文前（tech-notes §110）。**能不能看到、要不要配置，取决于模型类型和接入协议**：

| 模型类型 | 例子 | 默认行为 | 需要的配置 |
|---|---|---|---|
| 永远思考型 | deepseek-reasoner、DeepSeek R1 | 自动吐思考，直接可见 | **无需任何配置** |
| Anthropic 协议接入 | Claude 系列、各家为接 Claude Code 提供的端点 | 官方 Claude **不思考**（必须显式开启）；第三方端点跟随各家默认（实测 deepseek 的 Anthropic 端点默认就思考） | `thinking = true`（官方 Claude 必需） |
| OpenAI Responses（o 系列） | o1 / o3 / o4-mini | 内部推理但摘要不流回（看不到） | `thinking = true` |
| 参数开关型（混合推理） | qwen3 系、GLM 思考版 | 跟随服务端/网关默认 | `extra = {enable_thinking = true/false}` |
| 非推理模型 | deepseek-chat、gpt-4o | 无思考能力 | **配了也没用**（模型没这能力） |

**场景一：Anthropic 协议模型开思考**（Claude 官方 / Anthropic 兼容网关）

```toml
# .mini-agent/config.toml
[llm]
provider = "anthropic"
model = "claude-sonnet-4-5-20250929"
thinking = true              # 开启后请求体自动带 thinking 参数
```

budget 自适应无需配置：opus/sonnet ≥ 4.6 传 `budget_tokens: 0`（模型自主决定思考量），其余传 `max(1024, max_tokens − 1)`。思考块签名自动随多轮对话往返，无需干预。

等价的环境变量写法（`.env`）：

```bash
MINI_AGENT_PROVIDER=anthropic
MINI_AGENT_MODEL=claude-sonnet-4-5-20250929
MINI_AGENT_THINKING=true     # 接受 1/true/yes/on（大小写不敏感）
```

**场景二：o1/o3 等 Responses 模型开思考 + 调节推理力度**

```toml
[llm]
provider = "openai-responses"
model = "o3"
thinking = true                            # reasoning 摘要以思考流形式流回
extra = {reasoning_effort = "high"}        # 可选：low/medium/high（部分新模型另支持 minimal），默认 medium
```

**场景三：qwen 混合推理模型的思考开关**（OpenAI 兼容模式）

```toml
[llm]
model = "qwen3.6-plus"
extra = {enable_thinking = true}     # 强制开（部分网关默认已开，配置后不依赖网关默认值）
# extra = {enable_thinking = false}  # 强制关——省输出 token，但推理质量下降
```

注意这里用的是 `extra` 而非 `thinking`——`thinking` 只作用于 Anthropic/Responses 协议；qwen 的开关是 OpenAI 兼容请求体里的厂商私有参数，走 `extra` 透传。实测参考：关思考后 qwen3.6-plus 会把 "9.11 和 9.9 哪个大" 答错。

**场景四：按 Profile 混搭**——日常快模型不思考，难题切换到思考档

```bash
# .env
MINI_AGENT_MODELS=fast,think

MODEL_FAST_MODEL=deepseek-chat               # 日常：快、便宜、不思考

MODEL_THINK_MODEL=claude-sonnet-4-5-20250929 # 难题：/model think 切换
MODEL_THINK_PROVIDER=anthropic
MODEL_THINK_API_KEY=sk-ant-xxxx
MODEL_THINK_THINKING=true                    # 只有这个档案开思考
```

`MODEL_<名>_THINKING` 未设置时继承主配置的 `thinking` 值。

**场景五：什么都不配（默认）**

`thinking = false`、`extra = {}`——请求体不带任何思考参数，一切跟随服务端默认：永远思考型照常可见，Anthropic/Responses 不思考，混合型由网关决定。

**代价提醒**：思考内容计入输出 token（Anthropic 按输出价计费），且首字回答变慢。预算敏感场景建议只在难题档案开启（场景四），或对混合模型显式关闭（场景三）。

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

**作用**：不写一行 Python，用配置声明"什么工具调用要被拒绝、需要确认、触发命令或发出通知"。四种 action：

- `action = "block"`（默认）——命中即**不执行**，LLM 收到 `Blocked by hook: <reason>` 后会调整策略（换方案或告知用户），不会瞎重试
- `action = "confirm"`——命中弹 y/a/n 确认框由你裁决：y 放行一次、a 本会话内同一规则不再询问、n 拒绝（LLM 收到 `Denied by user: <reason>`，**Agent 停止当前目标**回问你怎么办——默认拒一次即停，`max_consecutive_denials` 可调）
- `action = "command"`——执行 shell 命令（`command` 字段指定）；`event = "pre_tool"` 时非零返回码**阻止工具执行**（LLM 收到 `Blocked by hook: <命令 stdout 或 reason>`）；`event = "post_tool"` 时火后不管（非零返回码不阻断，stdout 显示为终端通知）
- `action = "notify"`——在终端打印一行通知（`message` 字段指定），不阻断也不确认

**写在哪**：用户级 `~/.mini-agent/config.toml`（跨项目生效）或项目级 `.mini-agent/config.toml`（仅本项目）。
**层级语义（注意）**：项目级定义了 `[[hooks]]` 时**整体替换**用户级的规则列表（不合并）——想两边都生效，把用户级规则复制进项目级。

**全部字段**：

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `tool` | 否 | `"*"` | 工具名 fnmatch 模式：`"bash"` 精确、`"write_*"` 前缀族、`"*"` 全部工具 |
| `arg` | 否 | 空 | 只检查此参数的值（如 `"file_path"`）；缺省检查**所有**参数值 |
| `contains` | 否 | 空 | 参数值包含此子串才触发 |
| `regex` | 否 | 空 | 参数值 `re.search` 命中此正则才触发；非法正则**告警跳过该条**，不阻断启动 |
| `condition` | 否 | 空 | 条件表达式——**设置时优先于** `tool`/`arg`/`contains`/`regex` 四个固定字段；可用字段 `tool`（工具名）和 `args.<key>`（参数值）；运算符 `==`、`!=`、`=~`（正则 `re.search`）、`~=`（glob `fnmatch`），用 `and`/`or` 组合（**同一表达式内不可混用**） |
| `reason` | 建议填 | 自动生成 | 拒绝/确认原因，block 时原样回给 LLM、confirm 时也显示在弹窗里——写清楚"为什么+该怎么办"效果最好。notify 动作不使用此字段（用 `message`） |
| `action` | 否 | `"block"` | `"block"` 直接拒绝；`"confirm"` 弹 y/a/n 确认框（a = 本会话内同一规则不再询问）；`"command"` 执行命令（PRE_TOOL 非零返回码阻止工具，POST_TOOL 火后不管）；`"notify"` 终端通知行；其他值告警跳过 |
| `event` | 否 | `"pre_tool"` | `pre_tool`（默认）或 `post_tool`；其他值告警跳过 |
| `command` | 否 | 空 | `action = "command"` 时的 shell 命令模板，支持模板变量（见下方说明） |
| `command_timeout` | 否 | `30` | 命令超时秒数（仅 `action = "command"` 时生效） |
| `message` | 否 | 空 | `action = "notify"` 时的通知消息模板，支持模板变量（见下方说明） |
| `reject` | 否 | `true` | 目前只支持 `true`，`false` 告警跳过 |

**匹配语义**：
- `contains` 和 `regex` 都不写 = 该工具的**所有调用**都触发（block 等于禁用工具，但带解释）
- `contains` 和 `regex` 同时写 = **两者都命中**才触发（AND）
- 多条 `[[hooks]]` 规则 = 任一命中即触发（OR），block 与 confirm 规则可混用
- 匹配对参数值做 `str()` 后比较，数字/布尔参数也能匹配

**TOML 语法注意**：
1. `[[hooks]]` 必须写在所有顶级键（`max_agent_iterations`、`theme` 等）**之后**——顶级键出现在 `[[hooks]]` 之后会被归入该规则条目导致解析错乱
2. `regex` 的值用**单引号**（TOML literal string）：`regex = 'rm\s+-rf'`——双引号里 `\s` 是非法转义会报错

**模板变量**：`command` 和 `message` 字段支持以下变量，运行时自动替换：

| 变量 | 说明 |
|---|---|
| `$TOOL_NAME` | 当前工具名 |
| `$TOOL_ARGS.<key>` | 工具参数值（如 `$TOOL_ARGS.file_path`、`$TOOL_ARGS.command`） |
| `$TOOL_ARGS` | 全部参数的 JSON（无点号时返回完整 JSON 对象） |
| `$EVENT` | 事件阶段（`pre_tool` 或 `post_tool`） |
| `$RESULT` | 工具输出文本（仅 `event = "post_tool"` 时有值） |
| `$RESULT_ERROR` | 工具是否出错：`"true"` 或 `"false"`（仅 `event = "post_tool"` 时有值） |

**condition 表达式**：当 `condition` 字段非空时，它**优先于** `tool`/`arg`/`contains`/`regex` 四个固定字段来决定是否触发。语法示例：

```toml
# 等价于 tool="bash" + contains="git push" 但更灵活
condition = "tool == 'bash' and args.command =~ 'git push'"

# OR 组合——任一工具命中即触发
condition = "tool == 'bash' or tool == 'delete_file'"

# 多条件 AND
condition = "tool == 'bash' and args.command =~ 'git push' and args.command =~ '--force'"
```

运算符：`==`（相等）、`!=`（不等）、`=~`（正则匹配 `re.search`）、`~=`（glob 匹配 `fnmatch`）。组合用 `and`（全部命中）或 `or`（任一命中），**同一表达式内不可混用** `and` 和 `or`——需要混用时拆成多条 `[[hooks]]` 规则。

**验证是否生效**：启动时看到 `Loaded N hook rule(s) from config` 即已加载；让 Agent 触发一条规则，block 规则显示错误 `Blocked by hook: <你的 reason>`，confirm 规则弹出确认框（拒绝后 LLM 收到 `Denied by user: <你的 reason>`），command 规则查看命令输出日志，notify 规则查看终端通知行。

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

# ——— command / notify 配方 ———

# 写 .py 文件后自动格式化（post_tool 阶段，命令失败不影响写入）
[[hooks]]
event = "post_tool"
condition = "tool == 'write_file' and args.file_path =~ '\\.py$'"
action = "command"
command = "ruff format $TOOL_ARGS.file_path"
command_timeout = 15

# 写 .py 文件后自动语法检查（post_tool 阶段，仅告警不阻断）
[[hooks]]
event = "post_tool"
condition = "tool == 'write_file' and args.file_path =~ '\\.py$'"
action = "command"
command = "python -c \"import ast; ast.parse(open('$TOOL_ARGS.file_path').read()); print('syntax OK')\""

# bash 工具执行后打印通知行（观察/审计用途）
[[hooks]]
event = "post_tool"
tool = "bash"
action = "notify"
message = "[hook] bash 完成: $TOOL_ARGS.command"

# 用 condition 表达式替代固定字段——灵活组合
[[hooks]]
condition = "tool == 'bash' and args.command =~ 'git push' and args.command =~ '--force'"
action = "block"
reason = "禁止 force push，请走 PR"
```

**边界**：配置层做"拒绝"（block）、"强制确认"（confirm）、"执行命令"（command）与"终端通知"（notify）——四种 action 均为声明式配置，无需写代码。改写参数（MODIFY）、复杂观察记录等高级场景仍需写 Python Hook 或 EventBus 订阅者——见 docs/agent-architecture.md S04。confirm 的裁决弹窗由主 Agent 的 terminal 执行；子 Agent（spawn_agents）不加载 `[[hooks]]` 规则、无确认 UI，代码注册的 CONFIRM hook 在无 UI 时一律安全拒绝。

---

## 五、上下文文件使用说明

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

### @-include 递归引用

**作用**：把分散在多个文件的项目规范组合进一个指令入口——不必全塞进一个 CLAUDE.md 导致膨胀，每个被引用文件独立维护，改了任何一个重启 mini 就生效。

**语法**：在指令文件（AGENT.md / CLAUDE.md / instructions.md）中，**独占一整行**写 `@./相对路径` 或 `@~/home路径`，启动时该行被替换为引用文件的内容。行内出现的 `@./`（如正文中的 `see @./doc.md for details`）不会被展开。

**示例** — AGENT.md 做索引，各规范文件独立维护：

```markdown
# 项目规范

@./docs/code-style.md
@./docs/testing-rules.md
@~/.mini-agent/global-rules.md
```

启动 mini 后，system prompt 中会出现 code-style.md、testing-rules.md、global-rules.md 三个文件的完整内容（相当于全部内联进了 AGENT.md）。

**路径解析规则**：

- `@./path` — 相对于**当前引用文件所在目录**（不是项目根）。例：如果 `docs/rules.md` 里写 `@./sub/detail.md`，解析为 `docs/sub/detail.md`
- `@~/path` — 相对于用户 home 目录。适合跨项目通用规则

**嵌套引用**：被引用文件里还可以继续写 `@./`，递归展开至最大深度 5 层（`[context] max_include_depth` 可调，设 0 完全禁用）。

**容错**：

- 引用的文件不存在 → 插入 `<!-- include not found: ./path -->` 注释行，不影响其余内容
- 循环引用（A 引用 B，B 又引用 A）→ 插入 `<!-- circular include: ./path -->` 注释行，不死循环
- 展开后总内容超过 `max_chars` → 正常截断

**典型场景**：

| 场景 | 做法 |
|---|---|
| 大团队项目 | 不同角色维护不同规范文件，AGENT.md 只做索引 |
| 单体仓库 | 根 AGENT.md 按需引入各子项目规范 |
| 个人跨项目规则 | `@~/.mini-agent/global-rules.md`，避免每个项目重复写 |
| 用户级指令 | `~/.mini-agent/instructions.md` 同样支持 @-include |

**注意**：某些 IDE 可能对指令文件中的 `@./` 语法报 lint 警告（如"导入路径超出项目根目录"）——这是 IDE 自身的静态检查误报，不影响 mini-agent 运行。

---

## 六、常见问题

**Q：config.toml 和 CLAUDE.md 都是"项目级"，有什么区别？**
A：config.toml 是给**程序**读的参数（改了影响程序行为，如超时/主题）；CLAUDE.md 是给**LLM**读的自然语言（改了影响 LLM 的回答，程序行为不变）。

**Q：项目里同时有 AGENT.md 和 CLAUDE.md 会怎样？**
A：只读 AGENT.md（优先级高的赢），CLAUDE.md 被忽略。不合并是有意设计——避免两个文件内容冲突时 LLM 无所适从。

**Q：指令文件里的 `@./path` 是什么意思？**
A：**@-include 递归引用**——一行只写 `@./relative/path.md` 或 `@~/home/path.md`，启动时该行会被替换为引用文件的内容（相对路径按引用方所在目录解析，不是项目根）。嵌套引用递归展开，最大深度 5（`[context] max_include_depth` 可调，设 0 禁用）。循环引用和文件不存在会插入 `<!-- circular include: ... -->` / `<!-- include not found: ... -->` 注释行，不影响其余内容。行内出现的 `@./`（如 `see @./doc.md for details`）不会被误展开。

示例 AGENT.md：
```markdown
# 项目规范
@./docs/code-style.md
@./docs/testing-rules.md
@~/.mini-agent/global-rules.md
```

**Q：为什么我改了 CLAUDE.md 但 LLM 没反应？**
A：指令文件启动时读取一次，改完要重启 `mini`。

**Q：API key 应该放哪？**
A：`.env` 文件（已被 gitignore 忽略）或环境变量。**不要**放 config.toml——项目级 config.toml 可能被提交进 git 泄露。

**Q：怎么确认指令注入成功了？**
A：启动时看有没有 `context: loaded <文件名>` 一行；或问 LLM 一个只有指令文件里写了的问题（如项目的测试命令），它不调工具直接答对就是注入成功。

**Q：记忆（memory.json）和指令文件（instructions.md）都会注入，区别是什么？**
A：指令文件是**你手写**的静态约定，启动注入；记忆是**LLM 自动提取**的动态积累（也可 `/memory add` 手动加），每次 LLM 调用前注入。前者适合稳定的规范，后者适合会话中发现的偏好。

---

## 七、自动记忆提取详解

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
| 注入方式 | 每次 LLM 调用前自动注入 system prompt（≤10 条全部注入；>10 条时 LLM 选最相关的 5 条） |
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

## 八、权限规则文件（permissions.toml）

自定义哪些命令/路径/工具免确认放行、哪些无条件拒绝——不用改代码。

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

[tools]
allow = ["glob"]           # 整体信任该工具（跳过命令/路径级检查，慎用）
deny = ["delete_file"]     # 直接拦截整个工具
```

**优先级**：`deny 规则 > allow 规则 > 内置默认`（危险命令确认 / 敏感路径拒绝 / 项目内放行）。deny 最优先——即使路径在项目内也会被拦。

**deny 命令规则的匹配范围与边界**：command 类 deny 规则除命令本体外，还匹配包装内层与串联分段——`cmd /c "ping x"`、`echo hi & ping x` 都会命中 `ping*` 规则（解包 cmd /c / cmd /k / powershell -Command / sh -c 前缀，抹引号后按 `&;|` 分段逐段匹配；引号内的数据不误拒；allow 规则不解包）。但这是纵深防御而非围墙：`p^ing` 转义、环境变量间接调用、base64 编码等深度混淆无法在规则层穷尽——安全保证靠分层：混淆载体本身（cmd /c、powershell -EncodedCommand 等）在危险命令清单里必弹确认，OS 沙箱是最终围墙。deny 规则的定位是表达策略意图，不是替代沙箱。

**子 Agent 边界**：deny 规则对会话内所有 Agent（含 spawn 的子 Agent）实时生效；但子 Agent 无确认 UI，需要弹窗确认的操作（危险命令等）一律安全拒绝而非询问——想让子 Agent 的危险操作被人工放行，目前请改由主 Agent 执行。

**内置路径保护**（PathGuard，不需配置，代码固定）：

评估顺序（先匹配先决定）：
1. `denied_paths`（`~/.ssh`/`~/.aws`/`~/.gnupg`，config.toml 可配） → 硬拒绝
2. 敏感文件名模式（`.env`/`.env.*`/`*.pem`/`*.key`/`id_rsa*`/`id_ed25519*`/`credentials*`/`*secret*`/`*.p12`/`*.pfx`，共 10 种） → 硬拒绝（项目内也拦）；`.env.example`/`.env.sample`/`.env.template` 豁免
3. 项目目录内 → 自动放行
4. `allowed_paths` 中的路径（config.toml 可配） → 自动放行
5. 以上都不匹配 → 询问用户（`permission_mode = "ask"` 时）

> **bash 通道也覆盖敏感文件**：上面这套 PathGuard 敏感文件保护只作用于 `read_file`/`write_file`/`delete_file` 三个文件工具。bash 命令曾对路径零检查——`type .env`/`cat ~/.ssh/id_rsa`/`Get-Content credentials.json` 会作普通命令被自动放行，绕过文件工具的拦截并把内容打印出来（真实验证实测泄漏过 API key）。现 permission.py 的 `command_references_sensitive_file()` 会把 bash 命令切成 token，任一 token 的 basename 命中上面同一份敏感文件模式即**弹确认**（判定 reason `sensitive_file_command`），拒绝时触发确认拒绝熔断。诚实边界同危险命令黑名单：变量展开（`$SECRET`）、通配、base64/echo 拼接等混淆仍可逃逸——详见 docs/tech-notes.md §90。

**工具级规则（P79）**：`[tools]` 节按工具名匹配（支持 glob），在命令/路径检查**之前**评估——`deny` 直接拦截整个工具；`allow` 整体信任该工具，跳过后续资源检查（`allow = ["bash"]` 意味着危险命令也不再确认，慎用）；无匹配规则的工具照常走命令/路径检查。

**匹配语法**：glob 风格。`git *` 匹配 `git status` 但不匹配 `github`；`*secrets*` 匹配任何含 secrets 的路径。

**验证是否生效**：`/trace on` 后触发相关操作，trace 行会显示 `rule:<scope>:<pattern>` 作为判定依据。

**修改后生效**：重启 mini（启动时加载一次）。或在运行中使用 `/allow` `/deny` 命令实时添加规则——带 `--save` 标志的规则会写入项目级 permissions.toml，下次启动自动加载。权限确认弹窗按 `a` 后也会追问一行是否持久化（y 写入同一文件，默认否）。

**运行时管理**（P78/P79）：
```
/allow command "docker *"          # 本会话放行所有 docker 命令
/deny path "*/secrets/*"           # 本会话拒绝 secrets 路径
/deny tool delete_file             # 本会话拦截 delete_file 工具
/allow command "npm *" --save      # 放行并持久化到 .mini-agent/permissions.toml
/deny                              # 列出当前所有 DENY 规则
```

---

## 九、OS 级沙箱（sandbox）

内核级别隔离 bash 命令的执行环境——即使命令通过了权限检查，也只能在受限范围内操作。

**支持平台**：

| 平台 | 后端 | 安装 |
|---|---|---|
| Linux | bubblewrap (bwrap)，不可用时自动降级 unshare | bwrap: `sudo apt install bubblewrap` 或 `yum install bubblewrap`；unshare: util-linux 预装 |
| macOS | Seatbelt (sandbox-exec) | 系统自带（`/usr/bin/sandbox-exec`） |
| Windows | 双模式：管理员 Low Integrity 进程（内核级）/ 非管理员无文件保护（限制仅文档说明，无启动警告） | 系统自带（ctypes）；详见下方文件权限表 |

**启用**：

```toml
# config.toml
[security]
sandbox = true               # 开启沙箱
sandbox_auto_allow = false    # 可选：沙箱下危险命令免确认
sandbox_network = false       # 可选：允许网络访问
```

**沙箱内的文件权限**（代码固定，非用户配置）：

**Linux/macOS（bwrap/seatbelt）**——进程级隔离，整个文件系统只读：

| 路径 | 权限 |
|---|---|
| 工作目录（项目目录） | 可读可写 |
| 系统临时目录（`tempfile.gettempdir()`，跨平台） | 可读可写 |
| `~/.mini-agent` | 只读（防命令篡改配置） |
| 其余整个文件系统 | 只读 |

Linux 上 bwrap 不可用时自动降级到 `unshare --mount --map-root-user`（util-linux 预装），提供类似的挂载命名空间隔离。

**Windows 管理员模式（Low Integrity 进程）**——内核级隔离，等同 bwrap/seatbelt：

| 路径 | 权限 |
|---|---|
| 工作目录（项目目录） | 可读可写 |
| 系统临时目录 | 可读可写 |
| 其余文件系统 | **内核强制不可写**（Low Integrity token 无法写入 Medium/High 完整性对象） |

通过 ctypes 降低子进程令牌完整性（`_low_integrity.py` helper），与 bwrap/seatbelt 提供等效的内核级保护。

**Windows 非管理员模式（无文件保护）**——attrib 已禁用（会阻断 agent 自身文件写入）：

非管理员模式不做任何文件保护，也不打启动警告（该限制仅在本文档说明，避免每次启动的噪音）。只有管理员 Low Integrity 模式提供真正的沙箱隔离。

**sandbox_auto_allow 与 permissions.toml 的配合**：

```
命令到达
  ↓
① permissions.toml deny 规则？→ 拒绝（沙箱也救不了）
  ↓
② permissions.toml allow 规则 / session grant？→ 放行
  ↓
③ 危险命令（28 条正则，含内联解释器）？
     sandbox_auto_allow=true → 放行（沙箱兜底）
     sandbox_auto_allow=false → 弹窗确认
  ↓
④ 执行：有沙箱 → 隔离执行（Linux/macOS 只读 rootfs；Windows 管理员 Low Integrity 内核级隔离）
       无沙箱 → 原样执行
```

- **permissions.toml** 管"要不要执行这条命令"
- **sandbox** 管"执行时能碰哪些文件"
- **deny 规则最大**，谁都绕不过——sandbox_auto_allow 不影响它

**验证是否生效**：`/trace on` 后执行命令，trace 行会显示 `sandbox_auto_allow` 作为判定依据（沙箱下免确认时）。

> **⚠ 安全边界（三个平台都适用）**
>
> **`sandbox=false` 时**（已改为默认开启）：三个平台都只有正则 + 确认框防护。LLM 被拒 `rm -rf` 后可改用 `python -c "shutil.rmtree(...)"` 绕过（已把常见内联解释器加入危险模式弹确认；写 `.py` 文件再执行会被写后执行检测拦截弹确认）。
>
> **`sandbox=true` 时**：
> - **Linux**：bwrap（或 unshare 后备）提供内核级只读文件系统。即使 LLM 绕过正则，也写不了受保护路径。这是最强防护。
> - **macOS**：seatbelt 提供内核级只读文件系统，等同 Linux bwrap。
> - **Windows 管理员**：Low Integrity 进程提供内核级隔离，等同 bwrap/seatbelt。
> - **Windows 非管理员**：非管理员模式无文件保护（该限制仅在本文档说明，不打启动警告）。attrib 已禁用，因为会阻断 agent 自身文件写入。只有管理员 Low Integrity 提供真正保护。
>
> **读泄漏边界**：沙箱管"能写哪"，管不了"能读哪"——Low Integrity 进程仍能读 Medium 完整性对象。敏感文件（`.env`/密钥/凭据）经 bash `type`/`cat`/`Get-Content` 读取的泄漏，靠命令层的 `command_references_sensitive_file()` 弹确认拦（见 §八"bash 通道也覆盖敏感文件"说明），而非沙箱。同样是减速带：混淆路径仍可逃逸。
>
> **结论**：拒绝一条命令 ≠ 该操作不可能完成。沙箱收窄了可写范围，正则 + 确认框 + 写后执行检测防常见误操作，但在无沙箱或 Windows 非管理员沙箱下无法完全防 LLM 刻意绕过。

---

*相关文档：终端输出说明见 output-guide.md，各系统终端打开方法与兼容性见 terminal-guide.md，能力对照见 docs/capabilities.md，架构原理见 docs/agent-architecture.md。*
