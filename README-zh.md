# Mini-Code-Agent

[![PyPI version](https://img.shields.io/pypi/v/mini-code-agent)](https://pypi.org/project/mini-code-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Tests](https://img.shields.io/badge/tests-1027%20passed-brightgreen)
[![Changelog](https://img.shields.io/badge/changelog-latest-blue)](CHANGELOG.md)

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

### 3. 安装

**方式一：PyPI 安装**

```bash
pip install mini-code-agent
```

安装后直接在任何终端输入 `mini` 即可启动。

**方式二：从源码安装**

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

更新已安装的版本：

```bash
# 先关掉正在运行的 mini 终端，然后执行：
uv cache clean mini-code-agent
uv tool install . --force
```

卸载：

```bash
uv tool uninstall mini-code-agent
```

启动后你会看到欢迎界面，直接输入你的问题即可开始对话。输入 `/exit` 或按 `Ctrl+C` 退出。

各系统各终端的打开方法、兼容等级、问题排查见 [docs/guide/terminal-guide.md](docs/guide/terminal-guide.md)。

### 6. 远程/浏览器模式

在浏览器中使用 Agent——适用于远程服务器、iPad 等无终端场景。

```bash
# 安装远程模式依赖
pip install mini-code-agent[remote]
# 或从源码：
uv sync --extra remote

# 在任意工作目录启动
cd /path/to/your/project
mini --remote

# 终端会显示：
#   Browser:   http://localhost:8765
# 浏览器打开 http://localhost:8765 即可使用
```

工作目录就是你运行命令时所在的目录——和终端模式完全一样。

**在任意目录使用**（全局安装）：

```bash
# 一次性全局安装（在项目目录执行）
uv tool install . --extra remote

# 之后在任何目录直接启动
cd ~/my-project
mini-agent --remote
# 浏览器打开 http://localhost:8765
```

**自定义主机和端口：**

```bash
mini --remote --host 0.0.0.0 --port 9000
# 浏览器:    http://0.0.0.0:9000

# 带 token 认证：
mini --remote --remote-token "my-secret"
# 浏览器:    http://localhost:8765?token=my-secret
```

### 7. 常用 CLI 参数

```bash
mini --help              # 查看所有可用参数
mini --model gpt-4o      # 指定模型
mini --provider openai   # 指定 Provider
mini --base-url URL      # 自定义 API 地址
mini --remote            # 远程/浏览器模式
mini --port 9000         # 自定义端口
mini --host 0.0.0.0      # 自定义主机（允许外部访问）
mini --remote-token x    # 远程模式 token 认证
mini --version           # 查看版本
```

> `mini` 和 `mini-agent` 是同一个程序的两个入口（pyproject.toml 注册了两个别名）。pip 安装后直接用 `mini`；源码运行用 `uv run mini`。本文档后续示例统一用 `mini`。

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
│       ├── core/               # Agent 引擎（ReAct 循环、状态机、SubAgent、团队、Planner、Mailbox、Pane Worker、成本跟踪、任务存储、工具录制、Agent 类型、窗格后端）
│       ├── tools/              # 工具系统（20 内置工具 + MCP 协议 stdio/HTTP/SSE eager/dispatch + Hook 11 阶段）
│       ├── memory/             # 记忆系统（四级压缩级联、持久记忆、会话存储、提取、召回、合并、文件快照、溢写缓存、项目上下文）
│       ├── security/           # 安全层（权限、路径守卫、审计、OS 沙箱 bwrap/seatbelt、worktree 隔离、跨进程权限确认）
│       ├── ui/                 # TUI 终端界面（终端、流式渲染、输入处理、组件、主题、Trace、Teach、进度面板、双 Esc 中断）
│       ├── remote/             # 远程/浏览器模式（WebSocket 服务器 + 嵌入式 HTML/JS 客户端、断连排队）
│       ├── extensions/         # 扩展协议（26 个斜杠命令、4 个技能包、事件监听插件、插件生态 plugin_loader）
│       ├── llm/                # LLM Provider 抽象层（OpenAI Chat Completions + Responses API + Anthropic、Token 计数）
│       ├── events/             # 事件总线（异步发布订阅、5 个内置订阅者共 17 个订阅）
│       ├── config/             # 分层配置加载（TOML + 环境变量 + CLI）、Shell/平台检测
│       └── models/             # 核心数据模型（消息、事件、配置、会话、权限）
├── tests/                      # 1027 个测试（61 单元 + 4 集成），80%+ 覆盖率
└── docs/
    ├── spec.md                 # 架构规格说明
    ├── tasks.md                # 开发任务清单
    ├── checklist.md            # 验收检查清单
    ├── capabilities.md         # 能力对照表（18 项需求逐条实现证据）
    ├── tech-notes.md           # 核心技术实现原理与方案选型
    ├── roadmap.md              # 后续演进路线图
    ├── positioning.md          # 项目立意与价值定位
    ├── guide/                  # 使用指南（命令/配置/输出/终端）
    │   ├── commands-guide.md   # 全部斜杠命令的完整语法与示例
    │   ├── config-guide.md     # 配置文件与上下文文件完全指南
    │   ├── output-guide.md     # 终端输出来源与配置指南
    │   ├── terminal-guide.md   # 各系统各终端的打开方法与兼容性指南
    │   └── en/                 # 上述四个指南的纯英文版
    ├── agent-architecture.md   # Agent 架构原理与 S01-S20 实现解析
    ├── comparison-mewcode.md   # 与 mewcode-python 的详细对比与增强路线
    └── comparison-config-cc.md # 配置系统对比：mini vs Claude Code
├── skills/                         # 4 个内置技能包（code_review / init_project / offline-ollama / teach-mode）
├── experiments/                    # 10 个机制实验脚本（压缩 A/B、模型混编、死循环诱导、熔断器验证等）
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
- [x] P13：SubAgent 进度面板（`/spawn wait` `/team` 期间实时表格展示各 agent 阶段/工具数/耗时）
- [x] P14：LLM 自主派生 SubAgent（`spawn_agents` 工具，LLM 在对话中自主并行调度子代理）
- [x] P15：会话自动保存（每轮自动保存 + 崩溃检测 + 启动恢复提示）
- [x] P16：/theme 主题切换（default/dark/light 三套主题全面接入 + 持久化）
- [x] P17：工具并行执行（权限预检串行 → 执行 asyncio.gather 并行 + 审计锁）
- [x] P18：双 Esc 中断流式输出（流式期间按两次 Esc 优雅中断，不用 Ctrl+C）
- [x] P19：PRE_LLM / SESSION_END Hook 接线（LLM 调用前注入记忆 + 会话结束自动提取偏好）
- [x] P20：上下文溢写兜底（发送前 token 预检 + 超限强制截断，防 API 400）
- [x] P21：TOML 配置文件（用户级 + 项目级 config.toml，Python 3.11 tomllib 零依赖）
- [x] P22：接口冻结 + 覆盖率门禁（v1.0.0 ABC 签名定稿 + pytest-cov 81.62% / fail_under=80）
- [x] P23：Diff 预览 + Streaming 扩展点（edit_file 彩色 diff 渲染 + on_tool_call_assembling 回调）
- [x] P24：文件变更汇总 + delete_file 工具（轮次结束显示本轮文件清单：+绿新建/~黄修改/-红删除）
- [x] P25：上下文感知（启动自动注入 AGENT.md/CLAUDE.md/instructions.md 项目指令 + 用户级全局指令）
- [x] P26：对话分叉/回滚（`/undo` 回滚 N 轮重新问 + `/fork` 分叉新会话保留原线——CC 没有的差异化能力）
- [x] P27：操作级撤销（`/undo` 连文件一起恢复——每轮快照被改文件，新建删掉/修改还原/删除找回）
- [x] P28：工具链录制/回放（`/record` 录制工具调用序列 + `/replay` 零 LLM 确定性重放）
- [x] P29：成本仪表盘（`/cost` 按模型分账 input/output 计价 + 会话预算 80%/100% 警告）
- [x] P30：LLM 记忆提取（MemoryExtractor 从 regex → LLM 结构化提取 + 词重叠去重 + SESSION_END hook 修复）
- [x] P31：MCP HTTP Transport（HTTPTransport + app 启动自动连接 MCP 服务器 + 关闭断连 + HTTP headers 认证）
- [x] P32：持久化任务系统（`/todo` 命令 + TaskStore 磁盘持久 + blockedBy 依赖追踪——S12 补全）
- [x] P33：PyPI 发布准备（元数据补全 + MIT LICENSE + publish workflow + pip install）
- [x] P34：Windows 终端适配（UTF-8 stdio 加固 + 流式降频防重影 + emoji 降级 + EscWatcher join + ask_yes_no 兜底；实战补修：bash GBK 解码、git 命令确认闸门、Git Bash 降级运行与代理字符清洗）
- [x] P35：死循环诱导实验（5 场景 × 2 臂实测三重熔断：迭代上限是唯一可靠硬熔断，same-tool-6x 未触发→已增强为同名占比检测）
- [x] P36：压缩-重读膨胀根治（>50K 工具结果溢写磁盘只留预览 + 压缩后注入已读文件清单——实战 50 万 token 单请求问题的双层修复）
- [x] P37：Anthropic Prompt 缓存（三处 cache_control 标记：系统提示/最后工具/最后用户消息——缓存命中部分输入 token 成本降约 90%）
- [x] P38：流式工具执行（工具调用流式中组装完成即执行，实测提前 400-550ms 开跑；需确认的延迟到流后，可配置关闭）
- [x] P39：@file 内联引用（输入 `@文件名` 自动内联文件内容 + Tab 补全，省掉 read_file 调用）
- [x] P40：权限规则文件（用户级/项目级 permissions.toml 自定义 allow/deny + 修复项目内 PATH deny 短路盲区）
- [x] P41：OS 级沙箱（Linux bubblewrap + macOS Seatbelt 内核隔离：只读 rootfs + 可写白名单 + 可选禁网；sandbox_auto_allow 免确认但 deny 规则仍拦）
- [x] P42：上下文窗口 API 探测
- [x] P43：Token 计数精度提升
- [x] P44：max_tokens 恢复
- [x] P45：Coordinator 模式
- [x] P46：Pydantic Schema 生成
- [x] P47：Pydantic Schema 全面增强
- [x] P48：Agent 类型定义
- [x] P49：Plan 模式只读
- [x] P50：Hook 事件类型扩充
- [x] P51：工具搜索/延迟加载
- [x] P52：选择性记忆召回
- [x] P53：记忆合并
- [x] P54：Worktree 完善
- [x] P55：Skill 安装命令
- [x] P56：Skill 热重载
- [x] P57：远程/浏览器模式
- [x] P58：跨 Agent Mailbox 通信
- [x] P59：会话压缩边界
- [x] P60：压缩工具对对齐
- [x] P61：记忆导出/导入
- [x] P62：压缩熔断器（连续 N 次压缩无效后跳过，防死循环烧 token）
- [x] P63：压缩恢复附件含文件内容（烤入最近 5 文件内容 + 用户请求，消除 9.2 诚实差异 #1）
- [x] P64：聚合工具结果溢写预算 + LLM 摘要压缩默认启用 + 压缩检查前移
- [x] P65：压缩双阈值（软 75% 受熔断器控制 + 硬 90% 绕过熔断器）
- [x] P67：摘要 prompt 结构化（analysis 草稿 + 9 节 summary）
- [x] P68：保留窗口按压缩目标缩放
- [x] P69：DropToolResults 尊重保留窗口（修复重读死循环 36→4 迭代）
- [x] P70：恢复附件预算随窗口缩放 + 嵌套摘要前传
- [x] P71：SlidingWindow 摘要锚点
- [x] P72：摘要偶发重试（2 次后回退提取式）
- [x] P73：摘要 prompt 超长收缩重试（丢最旧 20% + cap 缩 20%，≤3 轮）
- [x] P74：最小前缀检查 + /todo 歧义前缀检测
- [x] P75：Hook 确认裁决 CONFIRM 接入（`[[hooks]] action = "confirm"` 弹 y/a/n 确认框）+ 遗忘代码 6 处接入 + 事件监听插件
- [x] P76：三个轻量扩展点接入（/model Provider 列表 + 斜杠命令事件标记 + LLM 请求预估 token）
- [x] P77：四个中级扩展点接入（ToolRegistry.filter + Plan.is_complete + SessionMetadata.tags + PermissionRequest.tool_name）
- [x] P78：运行时权限规则管理（`/allow` `/deny` 斜杠命令动态添加权限规则，`--save` 持久化到 TOML；add_rule 增强校验/去重/事件；扩展点 #3 接入）
- [x] P79：工具级权限 PermissionScope.TOOL
- [x] P80：DEFAULT_AGENT_TYPE 接入
- [x] P81：Conversation.slice_window 删除
- [x] P82：PermissionDecision.PENDING（pane worker 跨进程权限审批 + 远程模式断连排队 + PENDING 事件可观测）
- [x] P83：插件生态（pip 包 `mini_agent.plugins` entry point / 本地 `plugin_dirs` 文件注册工具/命令/技能，四钩子契约 + 三层异常隔离，`/plugins` 展示）

**全部阶段已完成，1027 个测试全绿。** 18 项需求的逐条实现证据见 [docs/capabilities.md](docs/capabilities.md)。

## 多 Agent 并行：/spawn 与 /team

两个命令都在后台派生独立的 SubAgent（各自拥有独立对话上下文和工具副本），区别在**谁来拆任务**：

| | `/spawn` | `/team` |
|---|---|---|
| 任务怎么拆 | 你手动拆 | Planner LLM 自动分解 |
| 依赖处理 | 无（全并行） | 按依赖分批（无依赖并行、有依赖等前置完成） |
| 结果收集 | 手动 `/spawn wait` | 自动等待 + 汇总报告 |
| 适用场景 | 你清楚怎么拆的简单并行 | 复杂任务交给 LLM 规划 |

### /spawn —— 手动调度 SubAgent

```
/spawn 读取README统计总行数          # 派生单个后台 agent，立即返回 agent_id
/spawn -p 分析src结构 | 分析测试覆盖   # 用 | 分隔并行派生多个
/spawn --isolated 重构这个模块        # 在独立 Git worktree 中执行（改动隔离）
/spawn --type explore 分析项目结构    # 指定类型：explore/plan/worker(默认)/verify
/spawn --pane 执行部署检查            # 在可见终端窗格运行（独立进程，实时观看）
/spawn --wait 跑一遍测试              # 派发+进度面板+结果一条命令完成
/spawn list                          # 查看活跃 agent 及其阶段
/spawn wait                          # 等待全部完成（期间显示实时进度面板）
/spawn wait <id>                     # 等待指定 agent
/spawn cancel [id]                   # 取消指定/全部 agent
```

注意：`/spawn` 派生后立即返回（不阻塞输入框），结果要用 `/spawn wait` 收集。

LLM 自主调用 `spawn_agents` 工具时也支持后台模式（B4）：`background=true` 立即返回 agent id，LLM 继续做其他工作，每个子 agent 完成时其结果以消息形式自动注入对话（终端同步提示完成）。默认仍为阻塞模式。

### /team —— LLM 规划的团队编排

```
/team 分析项目生成一份架构摘要到sum.md
/team --isolated 重构工具层并补充测试
```

执行流程：Planner LLM 分解任务（含依赖关系）→ SubAgent 按依赖分批并行执行（期间显示进度面板）→ 自动汇总各步骤报告。分析类步骤被强制只读（物理剥夺写文件工具），只有产出交付文件的步骤能写文件——不会留下中间垃圾文件。

### 强弱模型混编（省成本）

`/team` 支持 Planner 和 Worker 用不同模型（机制实验验证：强 Planner + 弱 Worker 是成本效益最优）：

```bash
# .env
MINI_AGENT_MODELS=fast,smart
MODEL_FAST_MODEL=deepseek-v4-flash
MODEL_SMART_MODEL=deepseek-chat
MINI_AGENT_PLANNER_PROFILE=smart    # 分解任务用强模型
MINI_AGENT_WORKER_PROFILE=fast      # 执行子任务用便宜模型
```

未配置时两者都用主模型。

## 对话分叉与回滚：/undo 与 /fork

LLM 回答不满意时，不用继续追问（对话越来越乱）也不用 `/clear` 全清（丢失全部上下文）：

### /undo —— 回滚重来

```
/undo        # 撤销最后一轮（你的问题 + LLM 的回答 + 工具调用记录全部删除）
/undo 3      # 一次撤销最后 3 轮
```

回滚后 LLM 完全"忘记"被撤销的内容——重新问会得到不受之前回答影响的全新答案。**文件操作也会一并撤销**（P27 操作级撤销）：该轮新建的文件删掉、修改的还原、删除的找回：

```
> /undo
Rolled back 1 turn(s), removed 3 message(s).
Undone: "创建 test.txt 写入 hello"
Files restored 文件已恢复:
  - test.txt (deleted -- did not exist before)
Context is now 1240 tokens.
```

**适用场景**：换个问法重试、提问后发现给错了信息、撤销一轮误操作的文件修改、清掉一轮跑偏的探索。

**操作级撤销的边界**：
- 快照只保留**最近 5 轮**——更早的轮次只回滚对话不恢复文件
- 单文件超过 **30MB** 不快照（undo 时提示手动恢复）
- **bash 命令**改的文件不快照（无法预知 shell 会改什么）
- 快照存 `.mini-agent/undo_snapshots/`（磁盘临时目录），会话结束自动清空

### /fork —— 分叉探索

```
/fork        # 从当前状态分叉一个新会话，在分支里继续对话
/fork 2      # 从 2 轮之前的状态分叉（分叉前先回滚 2 轮）
```

分叉后进入新会话（新 session_id），原会话完整存盘。两条线完全隔离——分支里的任何操作不影响原线：

```
> /fork
Forked to new session 3f8a2c1b9e4d5a76.
Original session a1b2c3d4 saved -- return with /session load a1b2c3d4
```

**适用场景**：想尝试另一个方向但不想丢掉当前进展、对同一问题试两种方案对比、在关键决策点留个"存档点"。

**两条线之间切换**：`/session list` 查看所有会话，`/session load <id前缀>` 切换。

**/undo vs /fork 怎么选**：确定这轮没用 → `/undo` 删掉；不确定、想两边都保留 → `/fork` 分叉。

> 本项目的对话是本地自持有的数据结构——回滚、分叉、录制/回放天然可行，数据主权完全在用户手中。

## 工具链录制/回放：/record 与 /replay

有一类"固定流程"操作（例行检查、整理产物、部署步骤）每次让 LLM 重新推理既费 token 又不稳定。录一次，之后零 token 重复执行：

### /record —— 录制

```
/record start cleanup    # 开始录制——之后所有轮次的成功工具调用都被记录
（正常对话让 LLM 干活，比如"跑测试然后把结果写入 report.txt"）
/record stop             # 停止并保存（显示录了几步）
/record                  # 列出已保存的录制
/record cancel           # 放弃当前录制
/record delete cleanup   # 删除
```

只录**成功**的调用（失败的不该被重放）。录制内容存 `~/.mini-agent/recordings/<名称>.json`，可直接用编辑器修改。

### /replay —— 零 LLM 重放

```
/replay cleanup
```

逐条重新执行录制的工具序列——**不调用 LLM，零 token 消耗**，逐步显示进度，任何一步失败立即停止：

```
Replaying 'cleanup' (2 steps):
  [1/2] bash ... ok
  [2/2] write_file ... ok
```

**安全性与真实执行一致**：回放走完整的权限管线——危险命令照样弹确认，PRE_TOOL hook 照样生效，文件操作照样进快照（`/undo` 能撤销一次回放）。

**适用场景**：例行操作固化（每天跑一样的检查序列）、把一次成功的操作变成可重复脚本、弱模型不稳定时锁定"上次做对了的步骤"。

### 参数模板化——让录制适应变化

**为什么需要**：录制默认是字面重放——录的时候写了 `report_0807.txt`，以后每次回放都写这同一个文件（覆盖上次的）。这只适用于"每次结果完全相同"的操作，而现实中的例行任务几乎都有变化的部分：

| 例行任务 | 不变的部分（录制固化） | 变化的部分（模板参数化） |
|---|---|---|
| 每日报告 | 跑检查 → 写报告 的步骤 | 文件名里的日期 |
| 发布准备 | 改版本 → 构建 → 归档 的步骤 | 版本号 |
| 项目脚手架 | 建目录 → 写模板文件 的步骤 | 项目名 |

录制固化"步骤"，模板化把"数据"从步骤里抽成参数——两者合起来，录制才从"重放一次性操作"升级为"可复用脚本"。

**怎么用**：编辑录制的 JSON 文件（`~/.mini-agent/recordings/<名称>.json`），把想变化的部分改成 `{{变量}}` 占位符：

```json
{"tool": "write_file", "args": {"file_path": "report_{{date}}.txt", "content": "负责人 {{owner}}"}}
```

回放时：`{{date}}`/`{{time}}`/`{{datetime}}` **自动填充**当前日期时间；自定义变量用 `k=v` 传入：

```
/replay daily owner=张三          # {{owner}} → 张三，{{date}} → 今天 
/replay daily                     # 缺 {{owner}} 会明确提示：Missing template variable(s): owner
/replay daily owner=李四          # 同一份录制，换参数产出不同结果
```

**完整示例——从录制到模板化回放**：

① 录一次真实操作：

```
> /record start daily
> 跑一遍测试，把结果摘要写到 report.txt
（LLM 执行 bash + write_file）
> /record stop
Saved recording 'daily': 2 step(s) -> ~/.mini-agent/recordings/daily.json
```

② 打开 `daily.json`，此时内容是字面值：

```json
{"name": "daily", "steps": [
  {"tool": "bash", "args": {"command": "uv run pytest tests/ -q"}},
  {"tool": "write_file", "args": {"file_path": "report.txt", "content": "360 passed ..."}}
]}
```

③ 把想变化的部分改成占位符（bash 那步不用动）：

```json
  {"tool": "write_file", "args": {"file_path": "report_{{date}}.txt", "content": "{{summary}}"}}
```

④ 以后每天：

```
> /replay daily summary=全绿无异常
Replaying 'daily' (2 steps):
  [1/2] bash ... ok
  [2/2] write_file ... ok
```

生成 `report_2026-08-07.txt`（日期自动变）——零 LLM 调用，token 统计不动。

### 什么时候用哪个

| 你的操作是… | 用什么 |
|---|---|
| 每次完全一样（固定检查序列） | `/record` + `/replay`，不用改 JSON |
| 步骤固定但有变化的数据（日期/版本号/名字） | 录制后把变化处改成 `{{变量}}` |
| 步骤本身每次都不同、需要现场判断 | 别用录制——写 Skill 或直接让 LLM 做 |
| 只做一次的操作 | 都不用，直接让 LLM 做 |

**与 Skill 的区别**：Skill 是手写的自然语言指令（LLM 读了照做，仍要推理，弱模型可能理解偏差）；录制是从实际操作自动生成的确定性脚本（不经 LLM，逐字重放，零 token）。固定流程用录制，需要判断的流程用 Skill。

**局限**：bash 之外的环境变化不感知；SubAgent 内部的工具调用不录；回放结果不进对话历史——LLM 不知道 `/replay` 改了什么文件（与 `/undo` 后的脱节同理），回放后让 LLM 操作相关文件时它可能基于过时认知，必要时提醒它重新读文件；录制状态只在内存——录制中途会话崩溃（硬关窗口等），未 `/record stop` 的录制会丢失，需要重录（已保存的录制文件不受影响——它们在磁盘上跨会话永久有效）。

### 附：怎么写一个 Skill（上表"做法 3"的完整步骤）

Skill 是一个目录 + 一个 `SKILL.md` 文件，放在项目的 `./skills/` 或全局的 `~/.mini-agent/skills/` 下：

```
skills/
└── daily-check/          ← 目录名即技能名
    └── SKILL.md
```

`SKILL.md` 格式（YAML frontmatter + 自然语言指令）：

```markdown
---
name: daily-check
description: 每日例行检查流程
triggers:            # 用户输入包含这些词时自动激活
  - "每日检查"
  - "daily check"
tools:               # 该技能建议使用的工具（可省略）
  - bash
  - read_file
---

你是执行每日检查的助手。按以下步骤：

1. 运行 `uv run pytest tests/ -q` 检查测试
2. 运行 `uv run ruff check src/` 检查代码规范
3. 汇总结果：全绿则简短报告，有失败则列出失败项和建议
```

**使用**：
- 自动触发：对话中说"帮我做每日检查"（命中 triggers）→ 技能指令自动注入
- 手动管理：`/skill` 列出全部、`/skill activate daily-check` 强制激活、`/skill deactivate` 取消

项目自带 4 个示例技能（`skills/` 目录）：code_review / init_project / offline-ollama / teach-mode，可直接参考格式。

## 成本仪表盘：/cost 与预算警告

按 token 付费的用户（DeepSeek 等 API）需要知道自己花了多少钱——本项目内置了完整的成本可观测：

### 配置价格（一次性）

在 `~/.mini-agent/config.toml` 加 `[cost]` 段，按你的 API 供应商定价填写：

```toml
[cost]
budget = 5.0                     # 本会话预算上限（元），不设 = 不限
total_budget = 50.0              # 累计总账预算上限（元），/cost reset 后重新计
[cost.pricing.deepseek-chat]
input = 2.0                      # 元/百万 input token
output = 8.0
[cost.pricing.deepseek-v4-flash-0731]
input = 0.15
output = 1.5
```

### 查看

```
/cost        # 详细面板：本次会话 + 累计总账两个区块
/cost turns  # 逐轮明细：本会话每一轮的 token 和金额
/cost reset  # 清零累计总账（会话内统计不受影响，需确认）
/status      # 含一行 Cost: ¥0.2207 / budget ¥5.00
```

```
**Cost Dashboard 成本仪表盘：**
  deepseek-chat            12 calls   in  45,230 tok   out  8,120 tok   ¥0.1554
  deepseek-v4-flash-0731   38 calls   in 182,400 tok   out 25,300 tok   ¥0.0653
  ----------------------------------------------------------------------------
  Total: ¥0.2207    Budget: ¥5.00 (4.4%)
```

### 特性

- **input/output 分开计价**（两者价差可达 4-10 倍，合并算会失真）
- **按模型分账**——`/model` 切换模型后各算各的；`/team` 强弱混编时 Planner（贵）和 Worker（便宜）也分开计
- **SubAgent 计入**——子代理的 LLM 调用同样被跟踪
- **每轮即时显示**——配置价格后，轮末的 token 行带金额：`tokens: 6373 this turn (¥0.0089) / 13215 total (¥0.0182)`
- **双层预算警告**——会话预算（`budget`）和累计总预算（`total_budget`）各自独立检查，每轮对话结束时触发：
  - 已用 **< 80%**：不显示任何提示
  - 已用 **≥ 80%**：黄色警告 `会话预算警告: ¥4.12 / ¥5.00 (82%)`
  - 已用 **≥ 100%**：红色警告 `⚠ 会话预算超支: ¥5.31 / ¥5.00`
  - 只提醒不阻断——花钱决定权在你；两种预算同时越线会各出一条
- 未配置价格的模型只累计 token 不算钱，`/cost` 会提示怎么配
- **请求数是 LLM API 调用次数**，不是提问次数——一轮对话里 LLM 每次思考/调工具都是一次请求（ReAct 迭代），问一个复杂问题产生 4-6 次请求是正常的
- **累计总账怎么清零**：`/cost reset` → 确认 y → 总账归零、起始日期重置为今天（数据存 `~/.mini-agent/cost_ledger.json`，删这个文件效果等同）

**局限**：总账（All-time）按当前价格表现算历史 token——供应商调价后历史金额会跟着变（token 数是事实，金额是视图）；精确对账以 API 供应商后台为准。

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

拿自己的实现做对照实验（`experiments/`），三个反直觉发现：

- **压缩策略 A/B**（15 次运行）：小窗口强制压缩下，压缩不省 token 反而更贵——摘要丢失细节导致 Agent 重复读文件，工具调用翻 2-5 倍。压缩是防溢出兜底，不是省钱手段
- **强弱模型混编**（6 次运行）：强 Planner + 弱 Worker 全通过且成本最低，比全强模型便宜 33% 还多过了一个任务——分解质量比执行模型档次更重要
- **死循环诱导**（10 次运行）：详见下文

完整数据和方法见 [experiments/README.md](experiments/README.md)。

### 死循环诱导实验详解

#### 为什么要做这个实验？

Agent 有工具能力后，最大的风险之一是**死循环**：LLM 反复调用工具但永远完不成任务，不断消耗 token 和时间。比如用户说"帮我找到这个函数"，但这个函数根本不存在——Agent 会不会无限搜索下去？

为了防止这种情况，项目实现了**三重熔断**机制（代码在 `core/agent_loop.py` 的 `_should_continue()` 方法中）：

1. **迭代上限**：每次对话最多跑 N 轮（默认 80），超过就强制停止
2. **同工具检测**（双层）：①同一工具用完全相同的参数被连续调用 6 次 → 停止；②同一工具名连续 15 轮迭代每轮都出现（不看参数，实验后新增的 v2 层）→ 停止
3. **预算警告**：session/总账达到预算 80% 时警告，100% 时提示超支（软提醒，不硬停）

这三个机制在单元测试中用 MockLLM（假 LLM）验证过——但**从没在真实 LLM 下测过**。MockLLM 会机械地返回完全相同的工具调用，真实 LLM 的行为可能完全不同。所以需要用真实 LLM 实际跑一遍来验证。

#### 怎么做的？

设计了 5 个**故意让 Agent 陷入死循环的任务**（诱导场景）：

| 场景 | 怎么诱导 | 预期效果 |
|---|---|---|
| `repeat_read` | 反复读一个永远不变的文件，直到内容变成 'DONE' | 预期触发 same-tool-6x |
| `modify_until_match` | 反复编辑+运行代码，但 `sys.exit(1)` 保证永远失败 | 预期触发迭代上限 |
| `search_nonexistent` | 搜索一个根本不存在的函数 `calculate_quantum_state` | 预期触发 same-tool-6x |
| `infinite_subtask` | 逐词翻译 200 个单词（一个词一轮 read+edit+verify） | 预期触发迭代上限 |
| `self_referential` | 反复读-找缺陷-重写文章，"直到完美" | 预期触发迭代上限 |

每个场景跑 2 个臂：`tight`（最多 5 轮）和 `normal`（最多 20 轮），对比不同安全余量。

**重要细节**：第一次运行时，用的是普通系统提示——结果 LLM 太"聪明"，几轮就判断出"文件不会变"/"函数不存在"然后自行停止，**5 个场景全部 natural_stop**，没有任何熔断被触发。所以改成了**强硬系统提示**（"你不许放弃、不许说不可能、必须持续使用工具"），迫使 LLM 继续执行。这个强硬提示只在实验脚本里使用，**不影响正常的 `mini` 命令**。

#### 结果

| 场景 | tight (max=5) | normal (max=20) |
|---|---|---|
| repeat_read | 自然停止（3 轮，5K token） | 自然停止（5 轮，9K token） |
| modify_until_match | **迭代上限触发**（5 轮，8K token） | 自然停止（6 轮，11K token） |
| search_nonexistent | **迭代上限触发**（5 轮，11K token） | 自然停止（9 轮，26K token） |
| infinite_subtask | **迭代上限触发**（5 轮，14K token） | 自然停止（6 轮，19K token） |
| self_referential | **迭代上限触发**（5 轮，23K token） | **迭代上限触发**（20 轮，**330K token**，6 分钟） |

#### 发现了什么？

**1. 迭代上限是唯一真正有效的硬保护**

10 次运行里触发了 5 次 `iteration_limit`。它简单粗暴但可靠——不管 LLM 怎么变花样，到次数就停。

**2. same-tool-6x 在真实 LLM 下完全没用——已修复**

0 次触发。原因是：真实 LLM 不会机械地用完全相同的参数调同一个工具——它每次都会微调参数（换个搜索关键词、改一行代码、换个文件路径），使得 `工具名(参数前200字符)` 的签名永远不重复。MockLLM 单元测试验证不了这一点——因为 MockLLM 返回的就是完全相同的调用。

这是这个实验**最有价值的发现**：一个在单元测试中正确通过的安全机制，**在真实场景中形同虚设**。

**已修复（v2）**：新增第二层检测——同一个**工具名**（忽略参数）连续 15 轮迭代每轮都出现，判定为死循环。按轮统计而非按调用次数统计：一轮内并行读 10 个文件是正常批量工作（不触发），每轮读一次持续 8 轮才是真循环（触发）。第一版按调用次数统计曾误杀"并行读所有文档"的场景，实战验证后修正。

**3. "直到完美"类任务是最危险的死循环模式**

`self_referential`（"反复改进文章直到完美"）是唯一一个 normal 臂也没停下来的场景——跑满 20 轮烧了 330K token。因为"完美"这个停止条件天然模糊，LLM 总能找到"可以更好"的地方。

其余 4 个场景在 normal 臂下 LLM 都主动停了——说明 LLM 自己也能当"第零层防线"，但不能依赖它。

**4. LLM 比预期聪明**

即使系统提示要求"不许放弃"，`repeat_read`（最明显的死循环）LLM 仍然在 3-5 轮后就"领悟"了文件不会变并自行停止。

#### 对日常使用的影响

- 默认的 `max_iterations=80` 足够安全——最坏情况也在 80 轮内停止
- 遇到开放式改进类任务（"帮我把这篇文章改到完美"），Agent 可能会循环较多轮——这是正常的，迭代上限会兜底
- 实验用的强硬提示只在 `experiments/deadlock_induction.py` 里，`mini` 命令的正常 system prompt 完全不受影响

#### 怎么自己跑这个实验

```bash
# 在项目根目录运行
cd mini-code-agent

# 查看所有场景
uv run python experiments/deadlock_induction.py --list

# 跑单个场景
uv run python experiments/deadlock_induction.py --scenario repeat_read --arm tight

# 跑全部（5 场景 × 2 臂 = 10 次，约 10 分钟，消耗约 0.01 美元）
uv run python experiments/deadlock_induction.py --all
```

结果自动写入 `experiments/results/deadlock_*.json`，可对照验证 README 中的数据。

## 配置与上下文文件

三类文件，性质不同：**配置文件**（config.toml/.env，给程序读的参数）、**上下文文件**（AGENT.md/CLAUDE.md/instructions.md，给 LLM 读的项目约定）、**数据文件**（memory.json/sessions，程序自动管理）。均分用户级（`~/.mini-agent/`，所有项目共用）和项目级（项目目录内，覆盖或叠加用户级）。

完整清单、优先级链、修改方法见 [docs/guide/config-guide.md](docs/guide/config-guide.md)。

## 扩展与自定义

五种扩展机制，无需修改项目源码：

### 自定义 Agent 类型

在 `.mini-agent/agents/`（项目级）或 `~/.mini-agent/agents/`（用户级）放 `.md` 文件即可定义新类型：

```markdown
---
name: reviewer
description: 代码审查专家
allowed_tools:
  - read_file
  - glob
  - grep
  - bash
max_iterations: 25
---
你是代码审查 agent。工作目录: {working_dir} ...
```

使用：`/spawn --type reviewer 审查 src/main.py`。LLM 自主选择时也能看到自定义类型。优先级：项目 > 用户 > 内置 4 种。完整格式见 [配置指南](docs/guide/config-guide.md#自定义-agent-类型)。

### 自定义工具（插件）

在 `.mini-agent/plugins/` 下放一个 `.py` 文件，启动时自动加载：

```python
# .mini-agent/plugins/word_count.py
from mini_agent.tools.base import Tool, ToolContext, ToolSchema, ToolParameter
from mini_agent.models.message import ToolResult

class WordCountTool(Tool):
    _name = "word_count"
    _description = "统计文本字数"

    @property
    def schema(self):
        return ToolSchema(name=self._name, description=self._description,
                          parameters=[ToolParameter(name="text", type="string",
                                                    description="要统计的文本")])

    async def execute(self, ctx: ToolContext, **kwargs):
        return ToolResult(call_id="", name="word_count",
                          output=f"字数: {len(kwargs['text'].split())}")

def register_tools(registry):
    registry.register(WordCountTool())
```

也支持 pip 包通过 `mini_agent.plugins` entry point 注册。示例见 `examples/plugins/`。`/plugins` 命令查看已加载插件。

### MCP 外部工具

通过配置接入任何 [MCP](https://modelcontextprotocol.io/) 兼容的工具服务器，无需写代码：

```toml
# .mini-agent/config.toml
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"          # "stdio" | "http" | "sse"
loading = "dispatch"         # "eager"（全部注册）| "dispatch"（按需搜索+调用）
```

### 技能包（Skills）

Skill 是自然语言指令包（SKILL.md），触发后注入 system prompt 引导 LLM 行为：

```
skills/daily-check/SKILL.md          # 项目级
~/.mini-agent/skills/*/SKILL.md      # 用户级
```

管理命令：`/skill list`、`/skill activate <名称>`、`/skill install <路径或git URL>`。项目自带 4 个示例技能。写法详见[上方技能包章节](#附怎么写一个-skill上表做法-3的完整步骤)。

### Hook 规则

在 config.toml 中声明 `[[hooks]]` 规则，拦截或确认工具调用，无需写代码：

```toml
[[hooks]]
tool = "write_file"
contains = "spec.md"
action = "block"             # "block"（默认，直接拒绝）| "confirm"（弹 y/a/n 确认框）
reason = "spec.md 是项目策略只读文件"
```

支持 11 个 hook 阶段。完整选项见 [config.toml.example](config.toml.example)。

## 全部命令一览

输入 `/help` 可在终端内查看。

| 命令 | 用途 |
|---|---|
| `/help` | 列出所有命令 |
| `/status` | 当前模型/token/轮次/上下文 |
| `/model [名称]` | 查看或切换模型 |
| `/clear` | 清空当前对话 |
| `/compact` | 手动压缩对话历史 |
| `/memory [add\|delete\|consolidate\|export\|import]` | 查看、添加、删除、合并、导出或导入持久记忆 |
| `/session save\|list\|load\|delete\|tag\|untag\|tags` | 会话管理（tag 分类标签，list --tag 按标签过滤） |
| `/undo [N]` | 回滚最后 N 轮对话（默认 1），可换个问法重新问 |
| `/fork [N]` | 分叉出新会话（可选先回滚 N 轮），原会话保留可随时回去 |
| `/record start\|stop\|cancel\|list\|delete` | 录制工具调用序列为可重放脚本 |
| `/replay <名称>` | 零 LLM 确定性重放已录制的工具序列 |
| `/todo [add\|done\|start\|fail\|delete\|clear]` | 持久化任务列表（带依赖追踪，跨会话保留） |
| `/cost` | 成本仪表盘：按模型分账的 token 用量与金额 |
| `/trace [on\|off]` | 显示/隐藏 Agent 内部状态（阶段/权限/工具/LLM） |
| `/explain [on\|off]` | 显示/隐藏工具使用说明面板 |
| `/audit [on\|off\|verify]` | 审计日志开关 + 哈希链完整性验证 |
| `/theme [dark\|light\|default]` | 切换颜色主题（持久化） |
| `/spawn <任务>` | 派生后台 SubAgent（详见上方多 Agent 章节） |
| `/team <任务>` | LLM 规划 + 并行执行（详见上方多 Agent 章节） |
| `/plan` | 进入/退出 Plan 模式（只读规划，不执行工具） |
| `/tools` | 列出已注册工具 |
| `/skill [list\|activate\|deactivate\|install\|uninstall\|reload]` | 技能包管理 |
| `/plugins` | 列出已加载插件（各自注册的工具/命令/技能） |
| `/allow [remove] <command\|path\|tool> <模式> [--save]` | 运行时添加 ALLOW 权限规则（`--save` 持久化到 TOML） |
| `/deny [remove] <command\|path\|tool> <模式> [--save]` | 运行时添加 DENY 权限规则（`--save` 持久化到 TOML） |
| `/exit` | 退出 |

全部命令的完整语法、参数与示例见 [docs/guide/commands-guide.md](docs/guide/commands-guide.md)。

> 终端输出的详细来源和开关说明见 [docs/guide/output-guide.md](docs/guide/output-guide.md)。

## 发布到 PyPI

项目已配置好自动发布——推 tag 即触发：

```bash
# 1. 确保 pypi.org 已注册 + 配置 Trusted Publisher（GitHub ccxxxyy/mini-code-agent）
# 2. 打 tag 并推送
git tag v1.1.0
git push origin v1.1.0
# 3. GitHub Actions 自动构建并发布
# 4. 验证
pip install mini-code-agent && mini --version
```

首次发布前需要在 [pypi.org](https://pypi.org) 注册账号并为项目添加 Trusted Publisher（选 GitHub，填仓库 `ccxxxyy/mini-code-agent`，workflow `publish.yml`）。之后每次打 `v*` tag 推送都会自动发布新版本。

## License

[MIT](LICENSE)
