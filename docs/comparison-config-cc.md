# 配置系统对比：Mini-Code-Agent vs Claude Code

本文逐项对比 Mini-Code-Agent（下称 mini）与 Claude Code（下称 CC）的配置系统——每个对比项都给出**双方的具体实现**，方便 CC 用户迁移和理解差异。

---

## 一、配置文件格式与位置

### CC 的实现

CC 使用 **JSON** 格式，配置分散在多个文件：

```
~/.claude/
  settings.json          # 用户级设置（JSON）
  settings.local.json    # 用户级本地设置（不提交 git）
  CLAUDE.md              # 用户级 LLM 指令

<项目>/
  .claude/
    settings.json        # 项目级设置（可提交 git）
    settings.local.json  # 项目级本地设置
  CLAUDE.md              # 项目级 LLM 指令
```

`settings.json` 示例：

```json
{
  "permissions": {
    "allow": ["Bash(npm test)", "Read(*)"],
    "deny": ["Bash(rm *)"]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": ["bash .claude/hooks/lint-check.sh"]
      }
    ]
  },
  "env": {
    "DEBUG": "true"
  },
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"]
    }
  }
}
```

### mini 的实现

mini 使用 **TOML** 格式，单一配置文件按层级覆盖：

```
~/.mini-agent/
  config.toml            # 用户级设置（TOML）
  permissions.toml       # 用户级权限规则（独立文件）
  instructions.md        # 用户级 LLM 指令

<项目>/
  .mini-agent/
    config.toml          # 项目级设置
    permissions.toml     # 项目级权限规则
  AGENT.md / CLAUDE.md   # 项目级 LLM 指令
  .env                   # API 密钥（gitignore 忽略）
```

`config.toml` 示例：

```toml
[llm]
provider = "openai"
model = "deepseek-chat"
api_key = "sk-..."        # 建议放 .env 而非这里
base_url = "https://api.deepseek.com/v1"
temperature = 0.0

[security]
permission_mode = "ask"
allowed_commands = ["git *", "uv *"]

[memory]
context_window = 128000

[[hooks]]
tool = "bash"
contains = "git push"
action = "confirm"
reason = "push 会影响远程仓库"

[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
```

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 格式 | JSON（不支持注释） | TOML（支持 `#` 注释） |
| 目录名 | `.claude/` | `.mini-agent/` |
| 本地覆盖 | `settings.local.json`（独立文件） | 无独立文件，敏感值放 `.env` |
| 权限规则 | 内嵌在 `settings.json` 的 `permissions` 字段 | 独立的 `permissions.toml` 文件 |
| API 密钥 | OAuth 登录 / 环境变量 | `.env` 文件 / 环境变量 / config.toml |

---

## 二、配置优先级

### CC 的实现

```
CLI 参数 > 项目 settings.local.json > 项目 settings.json > 用户 settings.local.json > 用户 settings.json > 默认值
```

CC 有四层文件配置（用户级和项目级各拆 `settings.json` + `settings.local.json`），`.local.json` 不进 git 用于放个人偏好。

### mini 的实现

```
CLI 参数 > 环境变量 > .env > 项目 config.toml > 用户 config.toml > 默认值
```

mini 只有两层文件配置（用户 + 项目），但多了 `.env` 和环境变量两个中间层。环境变量分两层优先级：`MINI_AGENT_*`（高）> `OPENAI_*`（低，兼容 OpenAI 生态）。

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 文件层级 | 4 层（user/project × normal/local） | 2 层（user/project） |
| 环境变量 | 少量（`ANTHROPIC_API_KEY` 等） | 完整覆盖（`MINI_AGENT_*` 可设所有 LLM 参数） |
| `.env` 支持 | 无（需手动 `source` 或放环境变量） | 内置（项目根的 `.env` 自动加载） |
| 敏感值隔离 | `settings.local.json`（不进 git） | `.env` 文件（gitignore 忽略） |

---

## 三、LLM 指令文件

### CC 的实现

CC 只认 **`CLAUDE.md`**，分两个层级：

- `<项目>/CLAUDE.md`：项目指令，启动时注入 system prompt
- `~/.claude/CLAUDE.md`：用户全局指令，所有项目生效

两者**共存**——都注入，不互斥。CC 还支持子目录的 `CLAUDE.md`（进入该目录时自动追加），以及 `.claudeignore` 控制哪些文件 LLM 不可见。

CC 的 `CLAUDE.md` 启动时读取，改了文件内容会话中 **`/refresh`** 可热重载。

### mini 的实现

mini 支持**三个候选文件名**，按优先级三选一：

```
AGENT.md > CLAUDE.md > .mini-agent/instructions.md
```

找到第一个非空的就停，不合并。用户级 `~/.mini-agent/instructions.md` 与项目级**共存**（都注入）。

文件名和优先级可通过 `config.toml` 自定义：

```toml
[context]
instruction_files = ["CLAUDE.md", "AGENT.md"]   # 改优先级
max_chars = 8000                                  # 截断长度
```

修改后需**重启 mini**（无热重载）。

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 项目文件名 | 固定 `CLAUDE.md` | 可配，默认三选一（`AGENT.md` > `CLAUDE.md` > `instructions.md`） |
| 子目录指令 | 支持（子目录 `CLAUDE.md` 进入时追加） | 不支持 |
| 热重载 | `/refresh` 命令重载 | 不支持，需重启 |
| 截断 | 无明确限制（但有 context window 约束） | 可配 `max_chars`（默认 8000 字符） |
| 兼容性 | — | 兼容 CC 的 `CLAUDE.md`，迁移零改动 |

---

## 四、权限系统

### CC 的实现

CC 的权限规则写在 `settings.json` 的 `permissions` 字段里：

```json
{
  "permissions": {
    "allow": [
      "Bash(npm test)",
      "Bash(git diff:*)",
      "Read(*)",
      "Write(src/**)"
    ],
    "deny": [
      "Bash(rm *)"
    ]
  }
}
```

格式：`工具名(参数模式)`。`Read(*)` 表示所有文件可读，`Bash(npm test)` 表示 `npm test` 免确认。运行时权限弹窗选 "Always allow" 时，CC 自动写入 `settings.json`。

CC 的权限模式没有全局开关——默认就是 "ask" 模式（危险操作询问，安全操作放行）。

### mini 的实现

mini 的权限分两层：

**① `config.toml` 的全局模式和内置规则：**

```toml
[security]
permission_mode = "ask"              # "allow" | "ask" | "deny"
allowed_commands = ["git *", "uv *"] # 免确认白名单
denied_commands = ["rm -rf /"]       # 无条件拒绝
```

`permission_mode` 控制兜底行为：`allow` 全放行、`ask` 询问、`deny` 全拒绝。CC 没有这个全局开关。

**② `permissions.toml` 的细粒度规则（独立文件）：**

```toml
[commands]
allow = ["docker build *"]
deny = ["docker rm *"]

[paths]
allow = ["D:/shared/*"]
deny = ["*secrets*"]

[tools]
allow = ["glob"]
deny = ["delete_file"]
```

三个 scope 分别控制命令模式、文件路径、工具名。优先级 `deny > allow > 内置默认`。

运行时通过 `/allow` `/deny` 命令管理，`--save` 持久化到 `permissions.toml`：

```
/allow command "npm *" --save   # 写入 permissions.toml
/deny tool delete_file          # 仅本会话生效
```

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 规则格式 | `工具名(参数模式)` 统一格式 | 三个 scope 分离：`[commands]` `[paths]` `[tools]` |
| 存储位置 | 内嵌 `settings.json` | 独立 `permissions.toml` |
| 全局模式 | 无（固定 ask） | `permission_mode`：allow / ask / deny |
| 运行时管理 | 弹窗选 "Always allow" 自动写入 | `/allow` `/deny` 命令 + 弹窗 y/a/n |
| 工具级控制 | `Read(*)` / `Write(src/**)` | `[tools]` 节按工具名（`deny = ["delete_file"]`） |
| 路径级控制 | 参数模式里写路径 | 独立 `[paths]` 节，支持项目内路径拦截 |

---

## 五、Hooks 系统

### CC 的实现

CC 的 hooks 是**命令式脚本**——配置指定一个 shell 命令，CC 在特定时机执行它，通过脚本的**退出码和 stdout** 决定行为：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": ["bash .claude/hooks/lint-check.sh"]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write",
        "hooks": ["bash .claude/hooks/auto-format.sh"]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": ["bash .claude/hooks/notify.sh"]
      }
    ]
  }
}
```

脚本通过环境变量接收上下文（`$TOOL_NAME`、`$TOOL_INPUT` 等），退出码 `0` = 继续、`2` = 阻止工具调用。stdout 内容回传给 LLM。

常用 hook 时机：`PreToolUse`、`PostToolUse`、`Notification`、`Stop` 等。

这意味着用户可以在 hook 里**运行任意程序**——调 linter、发通知、改参数，能力极强但需要写脚本。

### mini 的实现

mini 的 hooks 是**声明式规则**——在 `config.toml` 里用 TOML 表达匹配条件和动作，不需要写脚本：

```toml
[[hooks]]
tool = "bash"                # 工具名 fnmatch 模式
arg = "command"              # 可选：只检查此参数
contains = "git push"        # 子串匹配
regex = '--force|main'       # 正则匹配（AND with contains）
action = "confirm"           # "block"（默认）或 "confirm"
reason = "禁止强推/直推 main"
```

**匹配字段**：
- `tool`：工具名 glob（`"bash"` / `"write_*"` / `"*"`）
- `contains`：参数值子串
- `regex`：参数值正则
- 两者同时写 = AND

**动作**：
- `block`：直接拒绝，LLM 收到 `Blocked by hook: <reason>`
- `confirm`：弹 y/a/n 确认框（a = 本会话不再问）

mini 也支持代码注册的 **编程式 hooks**（`HookManager.register(stage, fn, priority)`），覆盖更多时机：`STARTUP`、`SHUTDOWN`、`SESSION_START`、`SESSION_END`、`USER_INPUT`、`TURN_START`、`TURN_END`、`PRE_LLM`、`POST_LLM`、`PRE_TOOL`、`POST_TOOL`。编程式 hooks 支持 `MODIFY` 动作（改写参数），声明式规则不支持。

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 范式 | 命令式（shell 脚本） | 声明式（TOML 规则） + 编程式（Python 函数） |
| 配置复杂度 | 需写脚本文件 + JSON 配置 | 纯 TOML，无需脚本 |
| 灵活性 | 极高（任意 shell 命令） | 声明式：匹配 + block/confirm；编程式同等灵活 |
| 匹配方式 | `matcher` 字符串 | `tool`（glob）+ `contains`（子串）+ `regex`（正则） |
| 支持时机 | PreToolUse / PostToolUse / Notification / Stop | 11 个阶段（startup 到 post_tool） |
| 参数改写 | 脚本修改后输出 | 编程式 `MODIFY` 动作 |
| 层级合并 | 用户 + 项目合并 | 项目有 hooks 时**整体替换**用户级（不合并） |

**适用场景**：CC 的方式适合已有 CI/linter 脚本的团队（直接调用现有脚本）；mini 的声明式方式适合快速配置简单规则（不用写代码），编程式方式适合复杂场景。

---

## 六、MCP 配置

### CC 的实现

CC 在 `settings.json` 的 `mcpServers` 字段配置：

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_TOKEN": "ghp_..."
      }
    },
    "remote-api": {
      "type": "url",
      "url": "https://api.example.com/mcp"
    }
  }
}
```

所有 MCP 服务器启动时**立即加载**，工具注册到全局工具列表。CC 会自动发现 MCP 服务器提供的工具并展示给用户。

### mini 的实现

mini 在 `config.toml` 的 `[mcp.servers.*]` 节配置：

```toml
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"                              # stdio | http | sse
env = { GITHUB_TOKEN = "ghp_..." }

[mcp.servers.remote-api]
url = "http://localhost:8080/mcp"
transport = "http"
headers = { Authorization = "Bearer token" }     # 可选认证头
loading = "dispatch"                              # eager（默认）| dispatch
```

mini 独有的 `loading` 字段：
- `eager`（默认）：启动时立即注册工具到全局列表，LLM 直接可用
- `dispatch`：延迟加载——工具不进全局列表，LLM 通过 `tool_search` 工具按需搜索和调用。适合工具数量很多的 MCP 服务器（避免撑大 system prompt）

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 格式 | JSON `mcpServers` 字段 | TOML `[mcp.servers.*]` 节 |
| 传输协议 | stdio / URL | stdio / http / sse（显式 `transport` 字段） |
| 加载模式 | 全部即时加载 | 支持 `dispatch` 延迟加载（大量工具时省上下文） |
| 认证 | 环境变量传递 | 环境变量 + HTTP `headers` 字段 |
| 工具命名 | 原始工具名 | `mcp_<服务器名>_<工具名>` 前缀（避免冲突） |

---

## 七、模型配置

### CC 的实现

CC 主要绑定 Claude 系列模型，通过 OAuth 登录或 API key 认证。模型选择通过 `/model` 命令或 CLI 参数：

```bash
claude --model claude-sonnet-4-20250514
```

CC 可在 Claude 家族内切换模型，Max 订阅还支持部分第三方模型。无 `base_url` 概念，不支持任意 OpenAI 兼容 API。不支持多模型 Profile 预配切换。

### mini 的实现

mini 通过 OpenAI 兼容接口支持**任意模型**（DeepSeek、智谱、硅基流动、Ollama 等），也支持 Anthropic 原生接口：

```toml
[llm]
provider = "openai"          # openai | openai-responses | anthropic
model = "deepseek-chat"
api_key = "sk-..."
base_url = "https://api.deepseek.com/v1"
```

**多模型 Profile 系统**——预配多套模型参数，运行时 `/model` 一键切换：

```bash
# 环境变量定义 Profile
MINI_AGENT_MODELS=fast,strong
MODEL_FAST_MODEL=deepseek-chat
MODEL_FAST_API_KEY=sk-fast
MODEL_STRONG_MODEL=claude-sonnet-4-20250514
MODEL_STRONG_PROVIDER=anthropic
MODEL_STRONG_API_KEY=sk-ant-...
```

```
/model fast      # 切换到 DeepSeek
/model strong    # 切换到 Claude
/model           # 列出所有可用 Profile
```

**强弱模型分工**——Planner 用强模型、Worker 用快模型：

```bash
MINI_AGENT_PLANNER_PROFILE=strong
MINI_AGENT_WORKER_PROFILE=fast
```

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 支持模型 | Claude 系列为主（Max 订阅支持部分第三方） | 任意 OpenAI 兼容 + Anthropic 原生 |
| 认证方式 | OAuth 登录 / Anthropic API key | 任意 API key + base_url |
| 模型切换 | `/model` 在 Claude 家族内切换 | `/model` 在任意预配 Profile 间切换 |
| 多模型分工 | 不支持 | Planner/Worker 独立 Profile |
| 本地模型 | 不支持 | 通过 Ollama base_url 支持 |

---

## 八、费用管理

### CC 的实现

CC 在会话中显示 token 用量和费用，按 Anthropic 官方定价计算。无预算上限设置——用户在 Anthropic Console 管理配额。

### mini 的实现

mini 内置费用仪表盘，支持自定义价格和预算：

```toml
[cost]
budget = 5.0                         # 会话预算（元），0 = 不限
total_budget = 50.0                  # 累计总账预算（元）
currency = "¥"

[cost.pricing.deepseek-chat]         # 每模型自定义价格
input = 2.0                          # 元 / 百万输入 token
output = 8.0                         # 元 / 百万输出 token
cache_read = 0.5                     # 缓存读取价（可选）
cache_creation = 3.0                 # 缓存创建价（可选）
```

超 80% 黄色警告、超 100% 红色警告（只提醒不阻断）。`/cost` 查看实时费用，`/cost reset` 清零总账。

### 关键差异

| 维度 | CC | mini |
|------|-----|------|
| 定价来源 | Anthropic 官方 | 用户自定义（支持任意模型） |
| 预算控制 | 无内置（Anthropic Console 管理） | 会话预算 + 累计总账，80%/100% 警告 |
| 费用命令 | 会话结束显示 | `/cost` 实时查看 + 每轮自动显示 |

---

## 九、其他 mini 独有配置

以下功能在 CC 中无对应配置：

| 功能 | 配置方式 | 说明 |
|------|----------|------|
| **事件监听插件** | `listener_dirs` 列表 | 目录下的 `*.py` 文件自动注册为 EventBus 监听器 |
| **插件生态** | `plugin_dirs` / `disabled_plugins` | 本地 `*.py` 或 pip 包（`mini_agent.plugins` entry point）注册工具/命令/技能，`/plugins` 查看 |
| **技能系统** | `skill_dirs` 列表 | `skills/*/SKILL.md` 定义可复用的 LLM 指令模板 |
| **OS 沙箱** | `[security] sandbox = true`（默认开启） | Linux bwrap/unshare + macOS seatbelt + Windows 双模式（管理员 Low Integrity 内核级 / 非管理员无文件保护，限制仅文档说明） |
| **压缩调优** | `[memory]` 段 | 软/硬压缩阈值、熔断器、溢写预算等 |
| **会话清理** | `session_cleanup_days` | 自动清理 N 天前的旧会话文件 |
| **主题** | `theme` | `default` / `dark` / `light`，也可 `/theme` 运行时切换 |
| **远程/浏览器模式** | `--remote --port 8765` | WebSocket 服务器，浏览器代替终端 |

---

## 十、迁移指南：CC → mini

### 已有 CLAUDE.md

**零改动可用**——mini 默认查找 `CLAUDE.md`（优先级第 2）。如果项目同时有 `AGENT.md`，mini 会优先用 `AGENT.md`。

### 已有 .claude/settings.json

需要手动迁移到 `.mini-agent/config.toml` + `permissions.toml`：

| CC 字段 | mini 对应 |
|---------|-----------|
| `permissions.allow` | `permissions.toml` 的 `[commands] allow` 或 `[tools] allow` |
| `permissions.deny` | `permissions.toml` 的 `[commands] deny` 或 `[tools] deny` |
| `mcpServers` | `config.toml` 的 `[mcp.servers.*]` |
| `hooks.PreToolUse` | `config.toml` 的 `[[hooks]]`（声明式）或 Python hook（编程式） |
| `env` | `.env` 文件或 `config.toml` 内联 |

### API 密钥

CC 用 Anthropic OAuth 或 `ANTHROPIC_API_KEY`。mini 用 `.env` 文件：

```bash
# .env（项目根，gitignore 忽略）
OPENAI_API_KEY=sk-你的key
OPENAI_BASE_URL=https://api.deepseek.com/v1
```

或用户级 `~/.mini-agent/config.toml`：

```toml
[llm]
api_key = "sk-你的key"
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
```
