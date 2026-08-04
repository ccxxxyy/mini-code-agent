# Mini-Code-Agent

一个仿 Claude Code 的终端编程 Agent 工具。

## 快速开始

### 1. 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) 包管理器

安装 uv（如果还没有）：

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 克隆项目

```bash
git clone https://github.com/ccxxxyy/mini-code-agent.git
cd mini-code-agent
```

### 3. 安装依赖

```bash
uv sync
```

uv 会自动创建虚拟环境并安装所有依赖。

### 4. 配置 API Key

Mini-Code-Agent 需要一个 LLM API Key 才能工作。根据你使用的 LLM 服务，选择对应的配置方式。

#### 方式一：使用 OpenAI 官方 API

**Windows (PowerShell)：**
```powershell
# 临时设置（仅当前终端窗口有效）
$env:OPENAI_API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# 永久设置（写入用户环境变量，重启终端后生效）
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-xxxxxxxxxxxxxxxxxxxxxxxx", "User")
```

**Windows (CMD)：**
```cmd
:: 临时设置
set OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx

:: 永久设置
setx OPENAI_API_KEY "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
```

**macOS / Linux (Bash/Zsh)：**
```bash
# 临时设置（仅当前终端会话有效）
export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"

# 永久设置（写入 shell 配置文件，新终端自动生效）
echo 'export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxx"' >> ~/.bashrc
source ~/.bashrc
# 如果用 zsh，替换 .bashrc 为 .zshrc
```

#### 方式二：使用 OpenAI 兼容的第三方 API（推荐国内用户）

许多国内 LLM 服务提供 OpenAI 兼容接口（如 DeepSeek、智谱、月之暗面、硅基流动等），只需额外设置 Base URL：

**Windows (PowerShell)：**
```powershell
$env:OPENAI_API_KEY = "你的API密钥"
$env:OPENAI_BASE_URL = "https://api.deepseek.com/v1"       # DeepSeek 示例
# $env:OPENAI_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"  # 智谱示例
# $env:OPENAI_BASE_URL = "https://api.siliconflow.cn/v1"          # 硅基流动示例
```

**Windows (CMD)：**
```cmd
set OPENAI_API_KEY=你的API密钥
set OPENAI_BASE_URL=https://api.deepseek.com/v1
```

**macOS / Linux：**
```bash
export OPENAI_API_KEY="你的API密钥"
export OPENAI_BASE_URL="https://api.deepseek.com/v1"
```

#### 方式三：通过 CLI 参数指定（无需设置环境变量）

```bash
uv run mini-agent --api-key "你的API密钥" --base-url "https://api.deepseek.com/v1" --model "deepseek-chat"
```

#### 方式四：使用 .env 文件（推荐）

项目自带 `.env.example` 模板，复制一份为 `.env` 并填入你的实际密钥：

```bash
cp .env.example .env     # macOS / Linux
copy .env.example .env   # Windows CMD
```

然后编辑 `.env`，将占位值替换为你的密钥：

```bash
# .env
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1    # 可选，使用第三方API时设置
MINI_AGENT_MODEL=deepseek-chat                   # 可选，指定模型名
```

程序启动时会自动读取 `.env` 文件，无需手动加载，直接运行即可：

```bash
uv run mini-agent
```

> `.env` 已在 `.gitignore` 中忽略，不会被提交到仓库，你的密钥是安全的。

### 5. 启动

有两种启动方式：

**方式一：在项目目录中运行（开发模式）**

```bash
uv run mini          # 简短版
uv run mini-agent    # 完整版
```

无需安装，`uv run` 会自动使用项目虚拟环境。适合开发和调试。

**方式二：全局安装后直接运行（推荐日常使用）**

```bash
# 一次性安装到系统（在项目目录执行）
uv tool install .

# 之后在任何目录直接输入即可启动
mini
```

全局安装会把 `mini` 和 `mini-agent` 两个命令写入系统 PATH。之后不需要在项目目录，也不需要 `uv run`，任何终端窗口直接输 `mini` 就能用，和 `claude` 命令一样。

更新已安装的版本（改完代码后需要重新安装才能生效）：

```bash
# 先关掉正在运行的 mini 终端，然后执行：
uv cache clean mini-code-agent
uv tool install . --force
```

> **开发阶段建议用 `uv run mini`**，它直接运行源码，改完即生效，不需要重新安装。全局安装留给日常使用。

卸载：

```bash
uv tool uninstall mini-code-agent
```

启动后你会看到欢迎界面，直接输入你的问题即可开始对话。输入 `/exit` 或按 `Ctrl+C` 退出。

### 6. 常用 CLI 参数

```bash
mini --help              # 查看所有可用参数
mini --model gpt-4o      # 指定模型
mini --provider openai   # 指定 Provider
mini --base-url URL      # 自定义 API 地址
mini --version           # 查看版本
```

> 以下示例中 `mini` 和 `uv run mini-agent` 可互换使用。

## 支持的环境变量

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `OPENAI_API_KEY` | OpenAI 或兼容 API 的密钥 | `sk-xxxx` |
| `OPENAI_BASE_URL` | API 地址（第三方服务必填） | `https://api.deepseek.com/v1` |
| `MINI_AGENT_MODEL` | 模型名称 | `deepseek-chat`, `gpt-4o` |
| `MINI_AGENT_PROVIDER` | LLM Provider | `openai` |
| `MINI_AGENT_API_KEY` | API 密钥（优先级高于 OPENAI_API_KEY） | `sk-xxxx` |
| `MINI_AGENT_BASE_URL` | API 地址（优先级高于 OPENAI_BASE_URL） | `https://...` |
| `MINI_AGENT_MODELS` | 命名多模型定义（配合 `MODEL_<名>_MODEL` 等） | `fast,smart` |
| `MINI_AGENT_PLANNER_PROFILE` | 多 Agent 编排时 Planner 用的模型 profile | `smart` |
| `MINI_AGENT_WORKER_PROFILE` | 多 Agent 编排时 Worker 用的模型 profile | `fast` |

优先级：CLI 参数 > `MINI_AGENT_*` 环境变量 > `OPENAI_*` 环境变量 > 内置默认值

## 项目结构

```
mini-code-agent/
├── pyproject.toml              # 项目配置和依赖
├── src/
│   └── mini_agent/
│       ├── cli.py              # CLI 入口
│       ├── app.py              # 应用编排器
│       ├── models/             # 核心数据模型
│       ├── events/             # 事件总线系统
│       ├── config/             # 分层配置加载
│       ├── llm/                # LLM Provider 抽象层
│       ├── ui/                 # TUI 终端界面（主题、补全、流式渲染）
│       ├── tools/              # 工具系统（6 内置工具 + MCP + Hook）
│       ├── core/               # Agent 引擎（ReAct 循环、SubAgent、团队）
│       ├── memory/             # 记忆系统（压缩、会话、跨会话记忆）
│       ├── security/           # 安全层（权限、路径守卫、worktree）
│       └── extensions/         # 扩展协议（Skill、Slash 命令）
├── tests/                      # 测试
└── docs/
    ├── spec.md                 # 架构规格说明
    ├── tasks.md                # 开发任务清单
    ├── checklist.md            # 验收检查清单
    ├── capabilities.md         # 能力对照表（18 项需求逐条实现证据）
    ├── tech-notes.md           # 核心技术实现原理与方案选型
    ├── roadmap.md              # 后续演进路线图
    └── positioning.md          # 项目立意与价值定位
```

## 开发状态

- [x] P1：基础对话能力（项目结构、数据模型、事件系统、LLM Provider、TUI、对话循环）
- [x] P2：工具系统 + Agent Loop（6 个核心工具、ReAct 循环）
- [x] P3：安全 + Hook（权限管理、路径守卫、生命周期钩子）
- [x] P4：记忆 + 上下文管理（压缩、会话持久化、跨会话记忆）
- [x] P5：扩展协议（Skill 技能包、Slash 命令、MCP 协议、Anthropic Provider）
- [x] P6：多 Agent（SubAgent 分发、Git Worktree 隔离、Agent 团队、Plan 模式）
- [x] P7：打磨 + 测试（错误友好提示、token 缓存、主题系统、历史持久化）
- [x] P8：评测框架（benchmarks/ 10 任务 headless 评测，10/10 通过）
- [x] P9：机制透明度（`/trace` 命令实时展示 ReAct 内部状态）
- [x] P10：垂直场景定制（`/explain` 教学模式 + `/audit` 合规审计 + 内网离线 Skill）
- [x] P11：机制实验（`experiments/` 压缩策略 A/B + 强弱模型混合编排对照实验）
- [x] P12：多 Agent 入口（`/spawn` SubAgent 调度 + `/team` 团队编排 + 强弱混编接线）

**全部阶段已完成，243 个测试全绿。** 18 项需求的逐条实现证据见 [docs/capabilities.md](docs/capabilities.md)。

## 机制透明：/trace 模式

商用 Agent 是黑盒，本项目每个内部状态都可观测。`/trace on` 后实时显示：

```
trace [15:23:21.715] iter  1  idle -> thinking
trace [15:23:21.719] llm   request  2 msgs, 6 tools
trace [15:23:22.906] llm   response 1082 tokens, tool_calls=true
trace [15:23:22.908] tool  read_file start  file_path=README.md
trace [15:23:22.910] perm  path README.md -> GRANTED (path_guard:project_dir)
trace [15:23:22.910] tool  read_file done   0ms OK
trace [15:23:24.369] turn  complete 2 iterations, 1 tools, 2236 tokens
```

`/trace off` 关闭。每一行都标注了权限判定的**依据**（命中哪条规则/哪种模式）——这是理解 Agent 安全机制的活教材。

## 评测结果

在 10 个标准编程任务（修 bug/加功能/写测试/重构/搜索）上的评测结果：

| 指标 | 数据 |
|---|---|
| 通过率 | **10/10 (100%)** |
| 总 token | 62,040 |
| 总成本 | **$0.0015**（不到一分钱） |
| 平均每任务 | 6,204 token / $0.0002 / 4 次工具调用 / 6.2 秒 |

完整评测数据和方法见 [benchmarks/README.md](benchmarks/README.md)。

```bash
uv run python benchmarks/runner.py --all    # 跑全部评测
uv run python benchmarks/report.py          # 生成报告
```

## 机制实验

拿自己的实现做对照实验（`experiments/`），两个反直觉发现：

- **压缩策略 A/B**（15 次运行）：小窗口强制压缩下，压缩不省 token 反而更贵——摘要丢失细节导致 Agent 重复读文件，工具调用翻 2-5 倍。压缩是防溢出兜底，不是省钱手段
- **强弱模型混编**（6 次运行）：强 Planner + 弱 Worker 全通过且成本最低，比全强模型便宜 33% 还多过了一个任务——分解质量比执行模型档次更重要

完整数据和方法见 [experiments/README.md](experiments/README.md)。

## License

MIT
