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

```bash
uv run mini-agent
```

启动后你会看到欢迎界面，直接输入你的问题即可开始对话。输入 `/quit` 或按 `Ctrl+C` 退出。

### 6. 常用 CLI 参数

```bash
uv run mini-agent --help              # 查看所有可用参数
uv run mini-agent --model gpt-4o      # 指定模型
uv run mini-agent --provider openai   # 指定 Provider
uv run mini-agent --base-url URL      # 自定义 API 地址
uv run mini-agent --version           # 查看版本
```

## 支持的环境变量

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `OPENAI_API_KEY` | OpenAI 或兼容 API 的密钥 | `sk-xxxx` |
| `OPENAI_BASE_URL` | API 地址（第三方服务必填） | `https://api.deepseek.com/v1` |
| `MINI_AGENT_MODEL` | 模型名称 | `deepseek-chat`, `gpt-4o` |
| `MINI_AGENT_PROVIDER` | LLM Provider | `openai` |
| `MINI_AGENT_API_KEY` | API 密钥（优先级高于 OPENAI_API_KEY） | `sk-xxxx` |
| `MINI_AGENT_BASE_URL` | API 地址（优先级高于 OPENAI_BASE_URL） | `https://...` |

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
│       ├── ui/                 # TUI 终端界面
│       ├── tools/              # 工具系统（开发中）
│       ├── core/               # Agent 引擎（开发中）
│       ├── memory/             # 记忆系统（开发中）
│       ├── security/           # 安全层（开发中）
│       └── extensions/         # 扩展协议（开发中）
├── tests/                      # 测试
└── docs/
    ├── spec.md                 # 架构规格说明
    ├── tasks.md                # 开发任务清单
    └── checklist.md            # 验收检查清单
```

## 开发状态

- [x] P1：基础对话能力（项目结构、数据模型、事件系统、LLM Provider、TUI、对话循环）
- [x] P2：工具系统 + Agent Loop（6 个核心工具、ReAct 循环）
- [x] P3：安全 + Hook（权限管理、路径守卫、生命周期钩子）
- [ ] P4：记忆 + 上下文管理（压缩、会话持久化、跨会话记忆）
- [ ] P5：扩展协议（Skill 技能包、Slash 命令、MCP 协议）
- [ ] P6：多 Agent（SubAgent 分发、Git Worktree 隔离、Agent 团队）
- [ ] P7：打磨 + 测试

## License

MIT
