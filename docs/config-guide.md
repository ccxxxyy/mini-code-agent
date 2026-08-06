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
| `~/.mini-agent/sessions/` | 用户级 | 会话持久化（自动保存/崩溃恢复） |
| `~/.mini-agent/audit.jsonl` | 用户级 | 审计日志（`/audit on` 开启后） |

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
provider = "openai"          # LLM 提供方
model = "deepseek-chat"      # 模型名
temperature = 0.0
max_tokens = 4096
timeout = 120.0

[tools]
bash_timeout = 120.0         # bash 命令超时（秒）
max_file_size = 10000000     # 文件读取上限（字节）
enabled_tools = ["read_file", "write_file", "edit_file", "delete_file", "bash", "glob", "grep", "spawn_agents"]
denied_paths = ["~/.ssh", "~/.aws", "~/.gnupg"]   # 禁止访问的路径

[memory]
context_window = 128000      # 上下文窗口 token 数
compression_threshold = 0.75 # 压缩触发阈值（75% 时压缩）
auto_extract = true          # 会话结束自动提取记忆

[security]
permission_mode = "ask"      # "allow"（全放行）| "ask"（询问）| "deny"（全拒绝）
allowed_commands = ["git *", "uv *"]   # 免确认的命令白名单

[context]                    # 上下文感知（P25）
instruction_files = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
                             # 项目指令文件名及优先级（列表顺序=优先级，第一个命中即用）
user_instructions_file = "~/.mini-agent/instructions.md"   # 用户级全局指令路径
max_chars = 8000             # 单文件截断长度（字符）

# 顶级配置（不属于任何段）
max_agent_iterations = 50    # ReAct 循环最大迭代数
theme = "default"            # "default" | "dark" | "light"

# MCP 服务器
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"
```

### 修改后生效方式

改完 config.toml **重启 `mini` 生效**（启动时读取一次，无热重载）。

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

*相关文档：终端输出说明见 output-guide.md，能力对照见 capabilities.md。*
