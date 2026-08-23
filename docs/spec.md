# Mini-Code-Agent：完整架构规格说明

本文档是项目的架构设计基线——定义目录结构、分层架构、核心模块接口和开发阶段划分。目录树和数字随开发持续同步更新。

## 1. 项目目录结构

```
mini-code-agent/
├── pyproject.toml                    # Project metadata, dependencies, entry points
├── uv.lock                          # uv lockfile
├── README.md                        # 英文项目介绍与快速上手
├── README-zh.md                     # 中文项目介绍与快速上手
├── CHANGELOG.md                     # 版本变更日志
├── CLAUDE.md                        # 项目指令文件（LLM 上下文注入）
├── LICENSE
├── .python-version                  # 3.11+
│
├── src/
│   └── mini_agent/                  # Top-level package (importable as mini_agent)
│       ├── __init__.py              # Package version, top-level exports
│       ├── __main__.py              # python -m mini_agent entry point
│       ├── cli.py                   # CLI argument parsing (argparse), launches app
│       ├── app.py                   # Application orchestrator — wires all layers
│       │
│       ├── core/                    # === ENGINE LAYER ===
│       │   ├── __init__.py
│       │   ├── agent_loop.py        # ReAct agent loop state machine
│       │   ├── agent_state.py       # AgentState dataclass + state transitions
│       │   ├── agent_types.py       # Agent type definitions (explore/plan/worker/verify)
│       │   ├── cost_tracker.py      # Cost tracking per model (EventBus subscriber)
│       │   ├── mailbox.py           # Cross-agent file-based mailbox (inter-process)
│       │   ├── planner.py           # Plan mode — structured task decomposition
│       │   ├── spawn_backends.py    # Pane spawn backends (tmux / Windows Terminal)
│       │   ├── agent_type_loader.py  # Custom agent types from .md files (B3)
│       │   ├── subagent.py          # SubAgent spawning and lifecycle
│       │   ├── task_store.py        # Persistent task store (/todo)
│       │   ├── team.py              # Agent Teams — multi-agent coordination
│       │   ├── tool_recorder.py     # Tool chain recording (/record, /replay)
│       │   └── worker.py            # Headless pane worker mode (--worker)
│       │
│       ├── llm/                     # === LLM PROVIDER ABSTRACTION ===
│       │   ├── __init__.py
│       │   ├── base.py              # LLMProvider ABC, LLMResponse, streaming types
│       │   ├── openai_provider.py   # OpenAI / compatible API provider (Chat Completions)
│       │   ├── openai_responses_provider.py # OpenAI Responses API (o1/o3/o4-mini)
│       │   ├── anthropic_provider.py# Claude API provider
│       │   ├── registry.py          # Provider registry + factory
│       │   └── token_counter.py     # Token counting per provider
│       │
│       ├── models/                  # === CORE DATA MODELS ===
│       │   ├── __init__.py
│       │   ├── message.py           # Message, ToolCall, ToolResult, Conversation
│       │   ├── events.py            # Event types (event stream)
│       │   ├── session.py           # Session, SessionMetadata
│       │   ├── config.py            # Config dataclasses
│       │   └── permissions.py       # Permission types and rules
│       │
│       ├── tools/                   # === TOOL LAYER ===
│       │   ├── __init__.py
│       │   ├── base.py              # Tool ABC, ToolRegistry, ToolContext
│       │   ├── file_state_cache.py    # Read-before-edit enforcement (B2)
│       │   ├── builtin/             # 20 core tools
│       │   │   ├── __init__.py
│       │   │   ├── read_file.py     # ReadFile tool
│       │   │   ├── write_file.py    # WriteFile tool
│       │   │   ├── edit_file.py     # EditFile tool
│       │   │   ├── delete_file.py   # DeleteFile tool
│       │   │   ├── bash.py          # Bash tool
│       │   │   ├── glob_tool.py     # Glob tool
│       │   │   ├── grep.py          # Grep tool
│       │   │   ├── spawn_agents.py  # SubAgent spawning tool
│       │   │   ├── send_message.py  # Inter-agent messaging (send)
│       │   │   ├── wait_message.py  # Inter-agent messaging (receive)
│       │   │   ├── tool_search.py   # Dynamic tool discovery (MCP dispatch)
│       │   │   ├── mcp_call.py      # MCP tool invocation
│       │   │   ├── ask_user.py      # Structured question to user (B1)
│       │   │   ├── exit_plan_mode.py # LLM exits plan mode for review (B1)
│       │   │   ├── task_create.py    # Create task on board (B1)
│       │   │   ├── task_get.py       # Get task details (B1)
│       │   │   ├── task_list.py      # List all tasks (B1)
│       │   │   ├── task_update.py    # Update task status/description (B1)
│       │   │   ├── load_skill.py     # Activate installed skill (B1)
│       │   │   └── install_skill.py  # Install skill from path/URL (B1)
│       │   ├── mcp/                 # MCP client integration
│       │   │   ├── __init__.py
│       │   │   ├── client.py        # MCPManager — manages server connections
│       │   │   ├── transport.py     # Transport abstractions (stdio, HTTP)
│       │   │   └── adapter.py       # Adapts MCP tools to internal Tool interface
│       │   └── hooks.py             # Hook system — pre/post tool execution
│       │
│       ├── memory/                  # === MEMORY LAYER ===
│       │   ├── __init__.py
│       │   ├── _utils.py            # Shared helpers (strip_json_fence, etc.)
│       │   ├── context.py           # ContextManager — window tracking, overflow
│       │   ├── compressor.py        # Compression strategies (summarize, drop, etc.)
│       │   ├── consolidation.py     # Semantic memory consolidation
│       │   ├── extraction.py        # Memory extraction — pull learnings from convos
│       │   ├── file_snapshots.py    # Per-turn file snapshots for /undo
│       │   ├── interop.py           # Memory format interop (import/export)
│       │   ├── persistent.py        # Cross-session memory (project + user level)
│       │   ├── project_context.py   # Project context loading (CLAUDE.md etc.)
│       │   ├── recall.py            # Selective memory recall
│       │   ├── session_store.py     # Session save/restore (JSON on disk)
│       │   └── tool_result_cache.py # Spill-to-disk cache for oversized tool results
│       │
│       ├── security/                # === SECURITY LAYER ===
│       │   ├── __init__.py
│       │   ├── permission.py        # PermissionManager — allow/deny/ask
│       │   ├── path_guard.py        # Path restriction enforcement
│       │   ├── remote_confirm.py    # File-based remote permission for pane workers
│       │   ├── audit.py             # Audit logger (JSONL event trail)
│       │   ├── worktree.py          # Git worktree isolation manager
│       │   └── sandbox/             # OS-level sandbox backends
│       │       ├── __init__.py
│       │       ├── bwrap.py         # Linux bubblewrap backend
│       │       ├── seatbelt.py      # macOS sandbox-exec backend
│       │       ├── unshare.py       # Linux unshare fallback (when bwrap unavailable)
│       │       ├── windows.py       # Windows sandbox (admin: Low Integrity / non-admin: no file protection, documented only)
│       │       └── _low_integrity.py # Windows Low Integrity process helper (ctypes)
│       │
│       ├── ui/                      # === INTERACTION LAYER ===
│       │   ├── __init__.py
│       │   ├── terminal.py          # Main TUI application — Rich + Prompt Toolkit
│       │   ├── renderer.py          # Streaming output renderer (markdown, code, etc.)
│       │   ├── input_handler.py     # Input handling, key bindings, multi-line
│       │   ├── components.py        # Reusable UI components (spinners, panels, etc.)
│       │   ├── themes.py            # Color themes and styles
│       │   ├── trace.py             # Trace renderer (real-time agent internals)
│       │   ├── teach.py             # Teach mode renderer (tool chain explanation)
│       │   ├── board.py             # Progress board (sub-agent status display)
│       │   └── esc_watcher.py       # Double-Esc cancellation watcher
│       │
│       ├── extensions/              # === EXTENSION PROTOCOLS ===
│       │   ├── __init__.py
│       │   ├── builtin_commands.py  # Built-in slash command registration
│       │   ├── event_listeners.py   # Event listener plugin loader
│       │   ├── plugin_loader.py     # Plugin ecosystem — pip/file plugins registering tools/commands/skills
│       │   ├── skills.py            # Skill system — load/register/invoke skill packs
│       │   └── slash_commands.py    # Slash command registry + execution
│       │
│       ├── events/                  # === EVENT SYSTEM ===
│       │   ├── __init__.py
│       │   ├── bus.py               # EventBus — pub/sub async event dispatch
│       │   └── types.py             # Re-exports from models/events.py + helpers
│       │
│       ├── remote/                  # === REMOTE / BROWSER MODE ===
│       │   ├── __init__.py
│       │   ├── server.py            # WebSocket server (browser UI bridge)
│       │   ├── terminal.py          # RemoteTerminalAdapter (intercept UI calls)
│       │   └── web_ui.py            # Single-page HTML/JS browser client
│       │
│       └── config/                  # === CONFIGURATION ===
│           ├── __init__.py
│           ├── loader.py            # Layered config loading (global -> project -> session)
│           ├── defaults.py          # Default configuration values
│           └── environment.py       # Shell / platform detection helpers
│
├── tests/
│   ├── conftest.py                  # Shared fixtures
│   ├── unit/                        # 61 unit test files, 1063 tests
│   │   ├── test_agent_loop.py
│   │   ├── test_permissions.py
│   │   ├── test_remote_confirm.py
│   │   ├── ...                      # (61 files total)
│   └── integration/                 # 4 integration test files
│       ├── test_mcp_client.py
│       ├── test_agent_e2e.py
│       ├── test_session_persistence.py
│       └── test_worktree.py
│
├── docs/                            # 18 个文档：14 个专题 + 4 个英文版指南（guide/en/）
│   ├── guide/                       # 使用指南（面向使用者）
│   │   ├── commands-guide.md        # 26 个斜杠命令完整语法与示例
│   │   ├── config-guide.md          # 配置文件与上下文文件完全指南
│   │   ├── output-guide.md          # 终端输出格式与样式说明
│   │   ├── terminal-guide.md        # 各系统终端打开方法与兼容性
│   │   └── en/                      # 纯英文版（与中文版同步维护，头部互指链接）
│   │       ├── commands-guide.md
│   │       ├── config-guide.md
│   │       ├── output-guide.md
│   │       └── terminal-guide.md
│   ├── spec.md                      # 完整架构规格说明（本文档，设计基线）
│   ├── agent-architecture.md        # 五层架构详解与模块交互图
│   ├── capabilities.md              # 功能全景与验收状态总览
│   ├── checklist.md                 # 分阶段验收清单（P1-P83 逐项打勾）
│   ├── comparison-config-cc.md      # 配置系统对比：mini vs Claude Code
│   ├── comparison-mewcode.md        # 功能对照：mini vs mewcode-python
│   ├── positioning.md               # 项目定位与技术亮点
│   ├── roadmap.md                   # 开发路线图与里程碑（含代码质量清单与扩展点跟踪）
│   ├── tasks.md                     # 开发任务全记录（P1-P83）
│   └── tech-notes.md                # 技术笔记（实现细节与决策记录）
│
├── skills/                          # Built-in skill packs (shipped with project)
│   ├── code_review/
│   │   └── SKILL.md
│   ├── init_project/
│   │   └── SKILL.md
│   ├── offline-ollama/
│   │   └── SKILL.md
│   └── teach-mode/
│       └── SKILL.md
│
└── examples/
    └── plugins/
        └── word_count_plugin.py     # Example plugin  — demos all three register hooks
```

---

## 2. 分层架构图

```
+-------------------------------------------------------------------+
|              INTERACTION LAYER (ui/ + remote/)                    |
|                                                                   |
|  +----------+ +----------+ +------------+ +-----------------+     |
|  | Terminal | | Renderer | |   Input    | |  Remote Mode    |     |
|  |  (Rich)  | |(Markdown | |  Handler   | | (WebSocket srv  |     |
|  |          | | Streaming| |(PromptTk)  | |  + web_ui)      |     |
|  +----+-----+ +----+-----+ +-----+------+ +-------+---------+     |
|       |            |             |                 |              |
|  Slash Cmds / Skills / plugin_loader -> extensions/               |
+-------+------------+-------------+-----------------+--------------+
        |      EVENT BUS (events/bus.py)             |
        |  +-------------------------------------+   |
        +--+  async pub/sub -- all layers emit & +---+
           |  subscribe to typed events          |
           +---------+---------------------------+
+--------------------+----------------------------------------------+
|                    |     ENGINE LAYER (core/)                     |
|                    v                                              |
|  +----------------------------------------------------------+     |
|  |                   Agent Loop (ReAct)                      |    |
|  |  +----------+  +------------+  +-------------+  +------+  |    |
|  |  | Planner  |  | SubAgent   |  | Agent Teams |  | Mail |  |    |
|  |  |(PlanMode)|  | Dispatch   |  |(Coordinate) |  | box  |  |    |
|  |  +----------+  +------------+  +-------------+  +------+  |    |
|  |  +--------------+   (also: task_store / worker /          |    |
|  |  | Cost Tracker |    spawn_backends / tool_recorder)      |    |
|  |  +--------------+                                         |    |
|  +----------+------------------------------------------------+    |
|             |                                                     |
|  +----------v------------------------------------------------+    |
|  |              LLM Provider Abstraction (llm/)              |    |
|  |  +--------+  +-----------+  +------------------+          |    |
|  |  | OpenAI |  | Anthropic |  | OpenAI Responses |          |    |
|  |  +--------+  +-----------+  +------------------+          |    |
|  |  (ProviderRegistry.register 支持自定义 Provider 注册)     |    |
|  +------------------------------------------------------------+   |
|                                                                   |
+-------------------------------------------------------------------+
|                    TOOL LAYER (tools/)                            |
|                                                                   |
|  +--------------------------------------------+  +-----------+    |
|  |            Tool Registry                    |  |  Hook     |   |
|  |  +------------+  +-----------------------+  |  |  Chain    |   |
|  |  | Built-in   |  |    MCP Client         |  |  | pre/post |    |
|  |  | (12 tools) |  | (external servers)    |  |  | confirm  |    |
|  |  +------------+  +-----------------------+  |  +-----------+   |
|  +--------------------------------------------+                   |
|                                                                   |
+-------------------------------------------------------------------+
|                    MEMORY LAYER (memory/)                         |
|                                                                   |
|  +--------------+ +--------------+ +----------------------+       |
|  |   Context    | |  Compressor  | |   Persistent Memory  |       |
|  |   Manager    | |  (auto-trim) | | (project + user)     |       |
|  +--------------+ +--------------+ +----------------------+       |
|  +--------------+ +--------------------+ +-----------------+      |
|  | Session Store| | Memory Extraction  | | Tool Result     |      |
|  |              | | + Recall /         | | Cache (spill)   |      |
|  |              | |   Consolidation    | |                 |      |
|  +--------------+ +--------------------+ +-----------------+      |
|  (also: file_snapshots / project_context / interop)               |
+-------------------------------------------------------------------+
|                    SECURITY LAYER (security/)                     |
|                                                                   |
|  +--------------+ +--------------+ +----------------------+       |
|  | Permission   | |  Path Guard  | |   Worktree Isolation |       |
|  |  Manager     | |              | |                      |       |
|  +--------------+ +--------------+ +----------------------+       |
|  +--------+ +----------------------------------------------+ +----+|
|  | Audit  | | OS Sandbox (bwrap/unshare/seatbelt/windows) | |Rmte||
|  +--------+ +----------------------------------------------+ +----+|
+-------------------------------------------------------------------+
```

补充说明：

- 交互层除终端 UI（`ui/`）外，还包含浏览器远程模式（`remote/`：WebSocket 服务端 `server.py` + 内嵌 Web UI `web_ui.py`）；远程模式下的权限确认由安全层 `remote_confirm.py` 桥接。
- 斜杠命令、技能与插件加载位于 `extensions/`（`slash_commands.py` / `skills.py` / `plugin_loader.py`，P83 插件机制），不在 `ui/` 中。
- 引擎层除 Agent Loop 外还有：跨 Agent 邮箱（`core/mailbox.py`）、成本跟踪（`core/cost_tracker.py`），以及后台任务存储 / worker / spawn 后端 / 工具录制（`task_store.py` / `worker.py` / `spawn_backends.py` / `tool_recorder.py`）。
- 记忆层的工具结果缓存（`memory/tool_result_cache.py`）将超大工具输出溢写到磁盘；记忆召回与固化见 `recall.py` / `consolidation.py`。

数据**自下而上**流转用于安全防御（安全层过滤每个工具调用），**自上而下**传递用户意图（交互层将用户消息送入引擎层），**横向**通过事件总线通信（任意组件可发射事件，任意组件可监听）。

---

## 3. 核心数据模型

### 3.1 消息类型 (`models/message.py`)

```python
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool invocation requested by the LLM."""
    id: str                          # Unique call ID (from LLM or generated)
    name: str                        # Tool name, e.g. "read_file"
    arguments: dict[str, Any]        # Parsed arguments
    raw_arguments: str = ""          # Unparsed JSON string (for debugging)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result returned after executing a tool."""
    call_id: str                     # Matches ToolCall.id
    name: str                        # Tool name that produced this
    output: str                      # String output for LLM consumption
    is_error: bool = False           # Whether execution failed
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata may contain: bytes_written, lines_matched, exit_code, etc.


@dataclass(slots=True)
class Message:
    """A single message in a conversation."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    role: Role = Role.USER
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_result: ToolResult | None = None      # Set when role == TOOL
    timestamp: datetime = field(default_factory=datetime.now)
    token_count: int | None = None             # Cached token count
    compressed: bool = False                    # True if this was summarized
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata may contain: model used, latency, thinking content, etc.


@dataclass
class Conversation:
    """An ordered sequence of messages with system prompt."""
    system_prompt: str = ""
    messages: list[Message] = field(default_factory=list)
    total_tokens: int = 0                      # Running total
    # 压缩后由 Compressor 设置；随会话持久化，加载时跳过已归档消息并恢复已读文件状态
    compact_boundary: dict[str, Any] | None = None

    def append(self, message: Message) -> None: ...
    def to_api_messages(self) -> list[dict[str, Any]]: ...
```

### 3.2 Agent 状态 (`core/agent_state.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentPhase(StrEnum):
    IDLE = "idle"                    # Waiting for user input
    THINKING = "thinking"            # LLM is generating
    TOOL_CALLING = "tool_calling"    # Executing tool(s)
    OBSERVING = "observing"          # Processing tool results
    RESPONDING = "responding"        # Streaming final answer
    ERROR = "error"                  # Recoverable error state
    TERMINATED = "terminated"        # Agent loop ended


@dataclass
class AgentState:
    """Mutable state of an agent loop instance."""
    phase: AgentPhase = AgentPhase.IDLE
    iteration: int = 0              # Current ReAct loop iteration
    max_iterations: int = 50        # Hard cap (AgentConfig overrides to 80)
    # 死循环检测：名称+参数签名滑窗（12 条）——同一工具处理不同文件是正常批量
    recent_tool_names: list[str] = field(default_factory=list)
    last_tool_results: list[ToolResult] = field(default_factory=list)
    # 每轮迭代用到的工具名集合（滑窗 15，与熔断阈值一致）——真死循环是每轮都调同一个工具
    iteration_tools: list[frozenset[str]] = field(default_factory=list)

    def record_iteration_tools(self, names: set[str]) -> None: ...
    def record_tool_call(self, name: str, args_key: str = "") -> None: ...

    @property
    def is_terminal(self) -> bool:
        return self.phase in (AgentPhase.TERMINATED, AgentPhase.ERROR)

    def transition(self, new_phase: AgentPhase) -> AgentPhase:
        """No validation -- sets the new phase and returns the old one."""
        ...
```

`record_tool_call()` / `record_iteration_tools()` 供 AgentLoop 做死循环检测：前者记录
`name(args_key)` 签名（只有完全相同的重复调用才算真死循环），后者记录每轮迭代的工具名集合。

计划模型 `PlanStep` 与 `Plan` 定义在 `core/planner.py`（与 Planner 同文件，见 4.15）：

```python
@dataclass
class PlanStep:
    """A single step in a structured plan."""
    index: int
    description: str
    role: str = ""
    status: str = "pending"          # pending | in_progress | completed | failed
    result: str = ""
    depends_on: list[int] = field(default_factory=list)
    writes_files: bool = False


@dataclass
class Plan:
    task: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def is_complete(self) -> bool: ...   # all steps completed or failed
```

### 3.3 会话 (`models/session.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionMetadata:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    project_dir: Path | None = None
    model: str = ""
    total_turns: int = 0
    total_tokens_used: int = 0
    tags: list[str] = field(default_factory=list)
    closed_cleanly: bool = False         # Flipped True on graceful exit; False = crash


@dataclass
class Session:
    """A complete agent session that can be persisted and restored."""
    metadata: SessionMetadata = field(default_factory=SessionMetadata)
    conversation: Conversation = field(default_factory=Conversation)
```

Session 本身是纯数据容器——序列化/反序列化（JSON 落盘、加载、按 `compact_boundary`
跳过已归档消息）由 `memory/session_store.py` 的 SessionStore 负责。

### 3.4 配置 (`models/config.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LLMConfig:
    provider: str = "openai"              # openai | anthropic | custom
    model: str = "gpt-4o"
    api_key: str = ""                     # Loaded from env / config
    base_url: str | None = None           # For custom endpoints
    max_tokens: int = 4096
    temperature: float = 0.0
    timeout: float = 120.0
    extra: dict = field(default_factory=dict)  # Provider-specific params


@dataclass
class ToolConfig:
    enabled_tools: list[str] = field(default_factory=lambda: [
        "read_file", "write_file", "edit_file", "delete_file",
        "bash", "glob", "grep", "spawn_agents",
        "send_message", "wait_message", "tool_search", "mcp_call",
        "ask_user", "exit_plan_mode", "task_create", "task_get",
        "task_list", "task_update",
        "load_skill", "install_skill",
    ])
    bash_timeout: float = 120.0
    max_file_size: int = 10_000_000       # 10MB
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=lambda: [
        "~/.ssh", "~/.aws", "~/.gnupg"
    ])


@dataclass
class MCPServerConfig:
    command: str = ""                     # For stdio transport
    args: list[str] = field(default_factory=list)
    url: str = ""                         # For HTTP/SSE transport
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    transport: str = "stdio"              # stdio | http | sse
    loading: str = "eager"                # eager | dispatch


@dataclass
class MCPConfig:
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)


@dataclass
class MemoryConfig:
    context_window: int = 128_000         # Provider's context limit
    compression_threshold: float = 0.75   # Soft threshold (75%), breaker-controlled
    hard_compression_threshold: float = 0.90  # Hard threshold (90%), bypasses breaker
    persistent_memory_dir: str = "~/.mini-agent/memory"
    project_memory_file: str = ".mini-agent/memory.json"
    auto_extract: bool = True
    spill_threshold_chars: int = 50_000   # 超过此字符数的工具结果溢写磁盘（0 = 禁用）
    aggregate_spill_chars: int = 200_000  # 单轮工具结果累计超此值时按大小降序强制溢写
    recall_threshold: int = 10            # 记忆超过此数量时用 LLM 选择性召回
    recall_top_k: int = 5
    consolidation_threshold: int = 20     # 条目超过此数量时用 LLM 语义合并相关记忆
    session_cleanup_days: int = 30        # 旧会话启动时自动清理（0 = 禁用）
    compress_max_failures: int = 3        # 熔断器：连续 N 次压缩无效后跳过（0 = 禁用）
    llm_summarize: bool = True            # LLM 语义摘要压缩（False = 抽取式截断）


@dataclass
class SecurityConfig:
    permission_mode: str = "ask"          # allow | ask | deny
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /", "sudo", "curl|sh", "wget|sh"
    ])
    worktree_base_dir: str = ".mini-agent/worktrees"
    worktree_max_age_days: int = 7        # 过期 worktree 启动时自动清理（0 = 禁用）
    sandbox: bool = True                  # OS 级沙箱（Linux bwrap/unshare / macOS seatbelt / Windows 管理员 Low Integrity / 非管理员无文件保护——限制仅文档说明），默认开启
    sandbox_auto_allow: bool = False
    sandbox_network: bool = False


@dataclass
class CostConfig:
    """成本跟踪：每模型价格与会话预算 (P29)。"""
    pricing: dict = field(default_factory=dict)  # model -> {"input": 元/1M token, "output": ...}
    budget: float = 0.0                   # 会话预算，0 不限
    total_budget: float = 0.0             # 总账预算，0 不限
    currency: str = "¥"


@dataclass
class ContextConfig:
    """上下文感知：项目指令文件注入 (P25)。"""
    instruction_files: list[str] = field(       # 优先级顺序，第一个命中即用
        default_factory=lambda: ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
    )
    user_instructions_file: str = "~/.mini-agent/instructions.md"
    max_chars: int = 8000


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    # 用于 /model 切换的命名 LLM 档案
    llm_profiles: dict[str, LLMConfig] = field(default_factory=dict)
    # 强弱模型混编：Planner 和 SubAgent worker 的 profile 名，空 = 使用主模型
    planner_profile: str = ""
    worker_profile: str = ""
    tools: ToolConfig = field(default_factory=ToolConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    max_agent_iterations: int = 80
    # 确认框连续被拒 N 次后停下回问用户（危险命令/项目外路径/hook 确认；默认 1 = 拒一次即停；防止被拒后找绕过路径）
    max_consecutive_denials: int = 1
    # `[[hooks]]` TOML 的声明式 PRE_TOOL 拒绝规则（原始字典，注册时解析）
    hooks: list = field(default_factory=list)
    self_verify: bool = False
    # 流式期间工具调用一组装完成就开始执行
    streaming_tool_execution: bool = True
    enable_plan_mode: bool = False  # 启动时是否开启 plan 模式（app.py 读取此值赋给 agent_loop.plan_mode）
    skill_dirs: list[str] = field(default_factory=lambda: [
        "./skills", "~/.mini-agent/skills"
    ])
    # 事件监听插件目录：*.py 文件监听总线全部事件
    listener_dirs: list[str] = field(
        default_factory=lambda: ["./.mini-agent/listeners", "~/.mini-agent/listeners"]
    )
    # 插件目录 (P83)：*.py 文件注册工具/命令/技能；pip 包走 mini_agent.plugins entry point
    plugin_dirs: list[str] = field(
        default_factory=lambda: ["./.mini-agent/plugins", "~/.mini-agent/plugins"]
    )
    disabled_plugins: list[str] = field(default_factory=list)  # 按 entry-point 名或文件名禁用
    theme: str = "default"
```

### 3.5 权限类型 (`models/permissions.py`)

```python
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class PermissionLevel(StrEnum):
    ALLOW = "allow"          # Always permitted
    ASK = "ask"              # Prompt user for confirmation
    DENY = "deny"            # Always blocked


class PermissionScope(StrEnum):
    TOOL = "tool"            # Permission for a specific tool
    PATH = "path"            # Permission for a file/directory path
    COMMAND = "command"      # Permission for a bash command pattern


@dataclass(frozen=True)
class PermissionRule:
    scope: PermissionScope
    pattern: str                     # Glob or regex pattern
    level: PermissionLevel
    reason: str = ""                 # Why this rule exists


@dataclass
class PermissionRequest:
    scope: PermissionScope
    resource: str                    # The specific resource being accessed
    tool_name: str = ""
    context: str = ""                # Human-readable description
    matched_rule: PermissionRule | None = None  # PermissionManager 赋值，经 PermissionCheckEvent 传递到 AuditLogger


class PermissionDecision(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    PENDING = "pending"              # Waiting for user response
```

---

## 4. 模块职责与公共接口

### 4.1 `app.py` -- 应用编排器

职责：装配所有层，管理应用生命周期，提供顶层 `run()` 入口。

```python
class Application:
    def __init__(self, config: AgentConfig): ...
    async def run(self) -> None: ...
    async def shutdown(self) -> None: ...

    # Internal wiring -- constructed in __init__:
    # self.event_bus: EventBus
    # self.config: AgentConfig
    # self.llm_provider: LLMProvider
    # self.tool_registry: ToolRegistry
    # self.permission_manager: PermissionManager
    # self.hook_manager: HookManager
    # self.context_manager: ContextManager
    # self.session: Session
    # self.session_store: SessionStore
    # self.agent_loop: AgentLoop
    # self.terminal: Terminal
    # self.mcp_manager: MCPManager
    # self.worktree_manager: WorktreeManager
    # self.subagent_manager: SubAgentManager
    # self.mailbox: Mailbox                    # 跨 Agent 收件箱（主 Agent 注册为 "main"）
    # self.audit_logger: AuditLogger           # /audit -- 工具调用写 JSONL
    # self.task_store: TaskStore               # /todo -- 持久化任务系统
    # self.tool_recorder: ToolRecorder         # /record + /replay
    # self.cost_tracker: CostTracker           # 按模型计价 token 用量
    # self.result_cache: ToolResultCache       # 超大工具结果溢写磁盘
    # self.trace_renderer: TraceRenderer       # /trace 实时内部状态
    # self.teach_renderer: TeachRenderer       # /explain 工具解释
    # self.skill_registry: SkillRegistry
    # self.slash_commands: SlashCommandRegistry
    # self.loaded_listeners: list[str]         # 事件监听插件
    # self.loaded_plugins: list[LoadedPlugin]  # P83 插件生态
```

### 4.2 `core/agent_loop.py` -- ReAct Agent Loop (主循环)

职责：编排 think-act-observe 循环。接收用户消息，调用 LLM，分发工具调用，收集结果，循环直到 LLM 产生最终回答或达到上限。

```python
class IncrementalAssembler:
    """Detects completed tool calls mid-stream (streaming tool execution).
    在流式过程中检测已组装完成的工具调用，一确定完成就产出 ToolCall。"""

    def feed(self, chunk: StreamChunk) -> list[ToolCall]: ...


class AgentLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        event_bus: EventBus,
        config: AgentConfig,
        tool_context: ToolContext,
        permission_manager: PermissionManager | None = None,
        hook_manager: HookManager | None = None,
        context_manager: ContextManager | None = None,
    ): ...

    async def run(self, conversation: Conversation) -> str:
        """Execute the full ReAct loop. Appends messages to the
        conversation, returns the final assistant text response.
        Streaming output goes through on_stream_delta etc. callbacks;
        events go through the EventBus."""
        ...

    def _deliver_mail(self, conversation: Conversation) -> None:
        """Drain the mailbox at the start of each iteration and inject
        cross-agent messages into the conversation."""
        ...

    async def _think(self, conversation: Conversation) -> LLMResponse:
        """Call LLM with current conversation. Returns response
        with possible tool calls. Retries with doubled max_tokens
        (up to 3 times) when the response is cut off by the limit
        (finish_reason "length") -- keeps the last result if still
        truncated (P44)."""
        ...

    async def _act(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
        """Execute tool calls (possibly in parallel).
        Runs hooks and permissions."""
        ...

    async def _run_tool_pipeline(self, ...) -> ToolResult:
        """Single tool call pipeline: PRE_TOOL hooks -> permission ->
        execute -> POST_TOOL hooks -> result spill/snapshot."""
        ...

    async def _check_permission(self, tc: ToolCall) -> PermissionDecision:
        """Tool-level gate first (check_tool), then resource-level
        command/path checks."""
        ...

    def _should_continue(self) -> bool:
        """Check iteration limits, loop detection, user cancellation."""
        ...

    def cancel(self) -> None:
        """Cancel the running loop (user interrupt)."""
        ...
```

工具结果的追加（原 `_observe`）内联在 `run()` 的迭代体中；`streaming_tool_execution`
开启时，`IncrementalAssembler` 让读类工具（写工具无条件延迟、需弹窗确认的工具经 `would_ask()`/`would_confirm()` 预判也延迟到 `_act`）在 LLM
仍在流式输出期间提前提交执行。

### 4.3 `llm/base.py` -- LLM Provider 抽象层

职责：定义所有 LLM Provider 实现的统一接口。处理流式响应、工具调用解析、token 计数。

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator


@dataclass
class ToolCallDelta:
    """Incremental tool call data from streaming."""
    index: int
    id: str | None = None
    name: str | None = None
    arguments_delta: str = ""


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""
    delta: str = ""                       # Text content delta
    thinking: str = ""                    # Extended thinking delta
    tool_call_deltas: list[ToolCallDelta] = field(default_factory=list)
    finish_reason: str | None = None      # "stop", "tool_calls", "length"
    usage: TokenUsage | None = None       # Only on final chunk


@dataclass
class LLMResponse:
    """Completed LLM response (assembled from stream or non-streaming)."""
    content: str = ""
    thinking: str = ""                    # Extended thinking content (Claude)
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    model: str = ""


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    async def prepare(self) -> None:
        """Optional warmup before first use (e.g. context window probing).
        Default: no-op. 首次使用前的可选预热（如上下文窗口探测），默认无操作。"""

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion -- yields chunks as they arrive."""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Estimate token count for the given text."""
        ...

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window size for the configured model."""
        ...
```

模块级辅助函数（独立函数而非方法，可用于鸭子类型的 LLM 对象）：

- `assemble_response(chunks: list[StreamChunk]) -> LLMResponse` -- 将 stream chunk
  列表组装为完整响应（内容、thinking、工具调用增量拼装、usage 取最大值）
- `complete(llm, messages, tools=None, **kwargs) -> LLMResponse` -- 非流式补全：
  一次调用完成流式收集和组装
- `compute_retry_delay(attempt, retry_after=None) -> float` -- 可重试 HTTP 失败
  （429/500/502/503/529）的退避时长：优先尊重 Retry-After 头，否则指数退避带抖动
  （1s -> 16s，共 5 次约 31 秒总耐心）

工具 schema 到 API 格式的转换不再是 Provider 方法（原 `format_tools` 已删除）——
各 Provider 直接消费 `ToolRegistry.get_schemas()` 产出的 JSON Schema。

### 4.4 `tools/base.py` -- 工具系统

职责：定义 Tool 接口、用于注册和查找的 ToolRegistry、以及工具执行上下文 ToolContext。

```python
from abc import ABC, abstractmethod


@dataclass
class ToolParameter:
    """Schema for a single tool parameter."""
    name: str
    type: str                                # "string", "integer", "boolean", etc.
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


def _resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline all $ref pointers and strip Pydantic metadata (title).
    Resolves $defs references, guards against circular refs with seen set."""
    ...

def _schema_from_model(name: str, description: str, model: type) -> ToolSchema:
    """Build ToolSchema from Pydantic BaseModel via raw JSON Schema passthrough.
    Calls model.model_json_schema() → _resolve_refs() → stores in raw_parameters."""
    ...


@dataclass
class ToolSchema:
    """JSON Schema-like description of a tool."""
    name: str
    description: str
    parameters: list[ToolParameter]
    raw_parameters: dict[str, Any] | None = None  # Pydantic 路径直通完整 JSON Schema

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema for LLM function calling.
        raw_parameters 非空时直通；否则从 ToolParameter 列表构建（后备路径）。"""
        ...


@dataclass
class ToolContext:
    """Context passed to every tool execution."""
    working_dir: Path
    session: Session
    event_bus: EventBus
    config: AgentConfig
    subagent_manager: SubAgentManager | None = None
    mcp_manager: Any = None
    # Cross-agent messaging: shared Mailbox + this agent's identity
    mailbox: Any = None
    agent_id: str = "main"


class Tool(ABC):
    """Base class for all tools (builtin + MCP-adapted)."""

    params_model: type | None = None  # Pydantic BaseModel for auto schema (P46)

    @property
    def schema(self) -> ToolSchema:
        """Return the tool's schema. Auto-generated from params_model (P46)
        via raw JSON Schema passthrough (P47); subclasses without
        params_model must override."""
        ...

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """Execute the tool with given arguments. Returns result."""
        ...

    def validate_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Validate and coerce arguments against schema.
        Pydantic path (params_model set): full type coercion.
        Manual path: basic required/default checks. Raises ValueError."""
        ...

    def error_result(self, call_id: str, message: str) -> ToolResult:
        """Helper to build an error ToolResult (is_error=True)."""
        ...


class ToolRegistry:
    """Central registry of all available tools."""

    def __init__(self): ...
        # self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> Tool | None: ...
    def list_tools(self) -> list[Tool]: ...
    def get_schemas(self) -> list[dict[str, Any]]: ...
    def clone(self) -> ToolRegistry:
        """Create an independent copy (for sub-agents)."""
        ...
    def filter(
        self,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> list[Tool]: ...
```

### 4.5 `tools/hooks.py` -- Hook 生命周期系统

职责：围绕工具执行的生命周期钩子。前置钩子可以阻止、修改或要求确认。后置钩子观察执行结果。

```python
from enum import Enum
from typing import Callable, Awaitable


class HookStage(StrEnum):
    STARTUP = "startup"              # Application startup
    SHUTDOWN = "shutdown"            # Application shutdown
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"        # After user submits message
    TURN_START = "turn_start"        # Before each user turn
    TURN_END = "turn_end"            # After each user turn
    PRE_LLM = "pre_llm"             # Before LLM call
    POST_LLM = "post_llm"           # After LLM response
    PRE_TOOL = "pre_tool"            # Before tool execution
    POST_TOOL = "post_tool"          # After tool execution


@dataclass
class HookContext:
    stage: HookStage
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: ToolResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HookAction(StrEnum):
    CONTINUE = "continue"            # Proceed normally
    BLOCK = "block"                  # Block the operation
    MODIFY = "modify"                # Proceed with modified context
    CONFIRM = "confirm"              # Ask user for confirmation


@dataclass
class HookResult:
    action: HookAction = HookAction.CONTINUE
    modified_args: dict[str, Any] | None = None
    reason: str = ""


# Hook callable type
HookFn = Callable[[HookContext], Awaitable[HookResult]]  # type: ignore


class HookManager:
    """Manages registration and execution of lifecycle hooks."""

    def __init__(self): ...
        # self._hooks: dict[HookStage, list[tuple[int, HookFn]]]

    def register(
        self, stage: HookStage, hook: HookFn, priority: int = 0
    ) -> None: ...

    def unregister(self, stage: HookStage, hook: HookFn) -> None: ...

    async def run(self, ctx: HookContext) -> HookResult:
        """Run all hooks for the given stage in priority order.
        Short-circuits on BLOCK and CONFIRM. Returns final result."""
        ...
```

### 4.6 `tools/mcp/client.py` -- MCP 客户端

职责：管理与 MCP 服务器的连接，发现工具，代理工具调用。零 SDK 依赖——自研 JSON-RPC 传输层（`MCPTransport` / `StdioTransport` / `HTTPTransport`，见 `tools/mcp/transport.py`）。

```python
class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self): ...
        # self._connections: dict[str, MCPServerConnection] = {}
        # self._dispatch_tools: dict[str, list[dict[str, Any]]] = {}

    async def connect_server(
        self, name: str, config: MCPServerConfig, tool_registry: ToolRegistry
    ) -> int:
        """Connect to an MCP server, discover its tools, register them.
        Returns the number of tools discovered."""
        ...

    async def disconnect_server(self, name: str) -> None: ...
    async def disconnect_all(self) -> None: ...
    def list_servers(self) -> list[str]: ...
    def list_server_tools(self, server_name: str) -> list[dict[str, Any]]: ...

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict
    ) -> ToolResult:
        """Proxy a tool call to the appropriate MCP server."""
        ...
```

### 4.7 `memory/context.py` -- 上下文管理器

职责：跟踪对话中的 token 使用量，在接近上限时触发压缩，管理上下文窗口。

```python
class ContextManager:
    """Tracks and manages the conversation context window."""

    def __init__(self, config: MemoryConfig): ...

    def set_compressor(self, compressor) -> None:
        """Inject the compressor after init (avoids circular import)."""
        ...

    def count_message(self, message: Message) -> int:
        """Count and cache tokens for a message."""
        ...

    def update_total(self, conversation: Conversation) -> int:
        """Recount total tokens for the conversation."""
        ...

    async def check_and_compress(self, conversation: Conversation) -> bool:
        """Check if compression is needed and perform it. Returns True
        if compressed."""
        ...

    def record_api_usage(self, conversation: Conversation, usage) -> None:
        """Anchor the API-reported authoritative token total at the newest
        message (P43). update_total() then only estimates messages appended
        after the anchor; identity check auto-invalidates on compression."""
        ...

    @property
    def usage_ratio(self) -> float:
        """Current context usage as fraction of window (0.0 to 1.0)."""
        ...

    @property
    def total_tokens(self) -> int: ...
    @property
    def tokens_remaining(self) -> int: ...
    @property
    def needs_compression(self) -> bool: ...
    @property
    def needs_hard_compression(self) -> bool: ...

    async def ensure_fits(self, conversation: Conversation, max_tokens: int) -> bool:
        """Last-resort guard: force-truncate if conversation exceeds max_tokens."""
        ...
```

### 4.8 `memory/persistent.py` -- 跨会话记忆

```python
class PersistentMemory:
    """Stores and retrieves long-term memory across sessions."""

    def __init__(self, config: MemoryConfig): ...

    # Project-level memory (stored in .mini-agent/memory.json)
    async def load_project_memory(self, project_dir: Path) -> list[MemoryEntry]: ...
    async def save_project_memory(
        self, project_dir: Path, entries: list[MemoryEntry]
    ) -> None: ...
    async def add_project_memory(
        self, project_dir: Path, entry: MemoryEntry
    ) -> None: ...

    # User-level memory (stored in ~/.mini-agent/memory/)
    async def load_user_memory(self) -> list[MemoryEntry]: ...
    async def save_user_memory(self, entries: list[MemoryEntry]) -> None: ...
    async def add_user_memory(self, entry: MemoryEntry) -> None: ...

    async def search(
        self, query: str, project_dir: Path | None = None
    ) -> list[MemoryEntry]: ...


@dataclass
class MemoryEntry:
    id: str = ""                      # auto-generated in __post_init__
    content: str = ""                 # The memorized fact/learning
    source: str = "user"              # "project" | "user" | "extracted"
    created_at: str = ""              # ISO string, set in __post_init__
    tags: list[str] = field(default_factory=list)
```

### 4.9 `security/permission.py` -- 权限管理器

```python
class PermissionManager:
    """Evaluates permission requests against rules.
    Prompts user when needed."""

    def __init__(
        self, config: SecurityConfig, path_guard: PathGuard,
        confirm_callback: ConfirmCallback | None = None,
        event_bus: EventBus | None = None,
    ): ...

    def add_rule(self, rule: PermissionRule, *, _silent: bool = False) -> bool:
        """Add a permission rule at runtime. Validates pattern,
        deduplicates, emits PermissionRuleAddedEvent. Returns False
        if duplicate."""
        ...
    def remove_rule(
        self, scope: PermissionScope, pattern: str, level: PermissionLevel
    ) -> bool:
        """Remove a rule by scope+pattern+level. Emits
        PermissionRuleRemovedEvent. Returns True if found."""
        ...
    def list_rules(self) -> list[PermissionRule]:
        """Return a copy of the current rule list for introspection."""
        ...
    @staticmethod
    def save_rule_to_file(path: Path, rule: PermissionRule) -> None:
        """Append a rule to a TOML permission file, creating if needed."""
        ...

    def load_rule_files(
        self, user_file: Path | None = None, project_file: Path | None = None,
    ) -> int:
        """Load user-defined rules from TOML files ([commands]/[paths]/
        [tools] sections with allow/deny lists). Returns rule count."""
        ...

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        """Universal entry -- dispatches by scope:
        COMMAND -> _check_command_request (dangerous-pattern confirmation)
        PATH    -> _check_path_request (DENY rules -> PathGuard -> generic)
        TOOL    -> _check_generic (rules -> session grants -> default mode)"""
        ...

    async def check_tool(self, tool_name: str) -> PermissionDecision | None:
        """Tool-level gate: explicit TOOL rules and session grants only.
        None = no match, caller falls through to resource-level checks."""
        ...

    async def check_path(
        self, path: Path, operation: str = "read", tool_name: str = ""
    ) -> PermissionDecision:
        """Convenience: check file path access permission."""
        ...

    async def check_command(self, command: str) -> PermissionDecision:
        """Convenience: check bash command permission."""
        ...

    @staticmethod
    def is_dangerous_command(command: str) -> bool:
        """Match against DANGEROUS_COMMAND_PATTERNS (regex)."""
        ...

    def would_ask(self, tool_name: str, arguments: dict) -> bool:
        """Non-interactive peek: would this call pop a confirm dialog?
        Used by streaming tool execution -- never prompts, no side effects.
        非交互预判：这次调用会不会弹确认框？供流式工具执行使用。"""
        ...

    def grant_session_permission(
        self, scope: PermissionScope, pattern: str
    ) -> None:
        """User granted permission for remainder of session."""
        ...
```

配置规则（`allowed_commands` / `denied_commands` / `denied_paths`）在 `__init__` 内通过
私有方法 `_load_rules_from_config()` 加载，外部无需调用。

### 4.10 `ui/terminal.py` -- TUI 终端应用

```python
class Terminal:
    """Main terminal UI -- Rich for rendering, Prompt Toolkit for input."""

    def __init__(self, event_bus: EventBus, config: AgentConfig): ...

    async def run(self) -> None:
        """Main UI event loop."""
        ...

    async def get_user_input(self) -> str | object:
        """Prompt for user input, or return _BG_INTERRUPT sentinel
        when a background agent completes while waiting.
        TTY: prompt_session.app.exit(_BG_INTERRUPT) interrupts prompt_async(),
        saves/restores partial user input.
        Non-TTY: asyncio.wait(FIRST_COMPLETED) races input() executor
        against asyncio.Event."""
        ...

    def interrupt_input(self) -> None:
        """Signal get_user_input() to return _BG_INTERRUPT for
        background agent result processing. Called by
        _on_background_complete event handler."""
        ...

    async def render_stream(
        self, stream: AsyncIterator[StreamChunk]
    ) -> str:
        """Render streaming LLM output in real-time. Returns full text."""
        ...

    async def render_tool_call(self, tool_call: ToolCall) -> None:
        """Display a tool call being executed (with spinner)."""
        ...

    async def render_tool_result(self, result: ToolResult) -> None:
        """Display tool execution result."""
        ...

    async def confirm(self, prompt: str) -> bool:
        """Ask user for yes/no confirmation."""
        ...

    def show_status(self, message: str) -> None: ...
    def show_error(self, error: str) -> None: ...
    def show_info(self, message: str) -> None: ...
```

### 4.11 `extensions/skills.py` -- 技能包系统

```python
@dataclass
class Skill:
    """A loadable skill pack: prompt + tools."""
    name: str
    description: str = ""
    prompt: str = ""                   # System prompt addition
    trigger_patterns: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    source_path: Path | None = None


class SkillRegistry:
    """Discovers, loads, and manages skill packs from SKILL.md files."""

    def __init__(self, skill_dirs: list[Path] | None = None): ...

    def load_all(self) -> None:
        """Scan skill directories and load all valid skill packs."""
        ...

    def register(self, skill: Skill) -> None:
        """Programmatically register a skill (plugin API, P83).
        Survives load_all()/reload() -- kept in a separate dict merged
        after each rescan."""
        ...

    def get(self, name: str) -> Skill | None: ...
    def list_skills(self) -> list[Skill]: ...
    def is_active(self, name: str) -> bool: ...

    def activate(self, name: str, conversation: Conversation) -> bool:
        """Activate a skill -- inject its prompt into the conversation.
        Returns False for unknown skills."""
        ...

    def deactivate(self, name: str, conversation: Conversation) -> bool:
        """Remove the skill's prompt from the conversation."""
        ...

    def match_triggers(self, user_message: str) -> list[Skill]: ...

    def reload(self, conversation: Conversation) -> tuple[int, list[str]]:
        """Hot-reload: rescan disk, update active skill prompts (P56).
        Returns (loaded_count, lost_skills)."""
        ...

    async def install(self, source: str, target_dir: Path) -> str:
        """Install a skill from a local path or git URL (P55).
        Returns the skill name."""
        ...

    def uninstall(self, name: str, target_dir: Path) -> bool: ...
```

### 4.12 `extensions/slash_commands.py` -- 斜杠命令

```python
@dataclass
class SlashCommand:
    name: str                          # e.g. "help", "clear", "status"
    description: str
    handler: Callable[[str, Session], Awaitable[str | None]]
    hidden: bool = False               # Not shown in /help


class SlashCommandRegistry:
    """Registry for built-in and user-defined slash commands."""

    def __init__(self, event_bus: EventBus): ...

    def register(self, command: SlashCommand) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> SlashCommand | None: ...
    def list_commands(self) -> list[SlashCommand]: ...

    async def execute(
        self, input_text: str, session: Session
    ) -> str | None:
        """Parse and execute a slash command. Returns None if not a
        slash command."""
        ...

    def is_slash_command(self, text: str) -> bool: ...

    # Built-in commands (26 visible + 1 hidden):
    # /help, /clear, /status, /model, /compact, /memory, /session,
    # /plan, /tools, /skill, /plugins, /allow, /deny, /exit, /undo,
    # /fork, /trace, /explain, /audit, /theme, /spawn, /team, /todo,
    # /cost, /record, /replay, /quit (hidden alias for /exit)
```

### 4.13 `core/subagent.py` -- 子 Agent 分发

```python
class SubAgent:
    """An independent agent that runs a single task in isolation
    (possibly in a worktree)."""

    def __init__(
        self,
        task: str,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        event_bus: EventBus,
        working_dir: Path,
        worktree_path: Path | None = None,
        allowed_tools: list[str] | None = None,
        model_name: str = "",
        agent_type: AgentTypeDefinition | None = None,  # 类型档案：提示词/工具/迭代预算
        mailbox: Mailbox | None = None,
        agent_id: str | None = None,
        peers: list[tuple[str, str, str]] | None = None,  # (id, name, task) 同伴列表
        name: str = "",
        permission_manager: PermissionManager | None = None,
    ): ...

    @property
    def status(self) -> AgentPhase: ...

    async def run(self) -> SubAgentResult: ...
    def cancel(self) -> None: ...


@dataclass
class SubAgentResult:
    agent_id: str
    task: str
    success: bool
    output: str
    tool_calls_made: int = 0
    tokens_used: int = 0
    worktree_path: Path | None = None
    error: str | None = None


@dataclass
class AgentSnapshot:
    """Point-in-time view of an active sub-agent (progress display)."""
    agent_id: str
    task: str
    phase: str
    tool_calls: int
    elapsed_seconds: float


class SubAgentManager:
    """Manages spawning, tracking, and collecting results
    from sub-agents."""

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        event_bus: EventBus,
        working_dir: Path,
        worktree_manager=None,
        model_name: str = "",
        mailbox: Mailbox | None = None,
        confirm_callback: ConfirmCallback | None = None,
    ): ...

    async def spawn(
        self,
        task: str,
        isolation: str = "none",     # "none" | "worktree"
        allowed_tools: list[str] | None = None,
        agent_type: str | None = None,
        agent_id: str | None = None,
        peers: list[tuple[str, str, str]] | None = None,
        name: str = "",
    ) -> str:
        """Spawn a sub-agent running in the background. Returns agent_id."""
        ...

    async def spawn_parallel(
        self,
        tasks: list[str],
        isolation: str = "none",
        allowed_tools: list[str] | None = None,
        agent_type: str | None = None,
        names: list[str] | None = None,
    ) -> list[str]:
        """Spawn multiple sub-agents concurrently. Ids are pre-generated
        so siblings can message each other via the mailbox."""
        ...

    async def spawn_background(
        self,
        tasks: list[str],
        isolation: str = "none",
        agent_type: str | None = None,
        names: list[str] | None = None,
        context_summary: str = "",
    ) -> list[str]:
        """Spawn sub-agents that notify 'main' via mailbox on completion.
        Returns agent ids immediately (non-blocking). Each agent's result
        is auto-delivered to the main conversation when it completes."""
        ...

    async def spawn_pane(
        self, task: str, name: str = "",
        agent_type: str | None = None, timeout: float = 900.0,
    ) -> str:
        """Spawn a sub-agent in a visible terminal pane (separate
        process, 6.4). Requires tmux / Windows Terminal."""
        ...

    async def wait(
        self, agent_id: str, timeout: float | None = None
    ) -> SubAgentResult: ...

    async def wait_all(
        self, agent_ids: list[str], timeout: float | None = None
    ) -> list[SubAgentResult]: ...

    def cancel(self, agent_id: str) -> None: ...
    def cancel_all(self) -> None: ...
    def list_active(self) -> list[str]: ...
    def get_status(self, agent_id: str) -> AgentPhase | None: ...
    def active_snapshots(self) -> list[AgentSnapshot]: ...
```

### 4.14 `core/team.py` -- 多 Agent 团队

```python
@dataclass
class TeamMember:
    name: str
    role: str                          # e.g. "frontend", "backend", "tester"
    allowed_tools: list[str] | None = None


@dataclass
class TeamConfig:
    name: str
    members: list[TeamMember] = field(default_factory=list)
    isolation: str = "none"            # "none" | "worktree"
    coordinator: bool = False  # P45: Planner pure-dispatch mode


@dataclass
class TeamRunReport:
    """Full record of one team run: the plan and per-step results."""
    task: str
    plan: Plan
    results: list[SubAgentResult] = field(default_factory=list)

    @property
    def success(self) -> bool: ...     # all steps succeeded
    def summary(self) -> str: ...      # human-readable per-step report


class AgentTeam:
    """Orchestrator-strategy team: decompose task, assign to members,
    collect results."""

    def __init__(
        self,
        config: TeamConfig,
        planner: Planner,
        subagent_manager: SubAgentManager,
    ): ...

    async def start(
        self, task: str, timeout: float | None = None
    ) -> TeamRunReport:
        """Run the full orchestration: decompose -> assign -> spawn ->
        collect. Steps run in dependency batches -- steps whose
        depends_on are all satisfied spawn in parallel; a step whose
        dependency failed is skipped as failed."""
        ...

    def stop(self) -> None:
        """Cancel all active sub-agents."""
        ...
```

### 4.15 `core/planner.py` -- 计划模式

职责：通过 LLM 将任务分解为结构化计划（PlanStep/Plan 数据模型见 3.2）。

```python
class Planner:
    """Decomposes tasks into structured plans using the LLM."""

    def __init__(
        self, llm: LLMProvider, max_steps: int = 5, coordinator: bool = False
    ): ...

    async def decompose(self, task: str, context: str = "") -> Plan:
        """Ask the LLM to break a task into subtasks (JSON array output,
        tolerates markdown fences). Sanitizes depends_on (no self/forward
        refs); if no step is marked writes_files, the last step gets it."""
        ...
```

`coordinator=True`（P45）时注入协调者前缀 prompt——Planner 只分解和分派，
全部文件操作交给 Worker，`max_steps` 提升到至少 8。

### 4.16 `core/mailbox.py` -- 跨 Agent 收件箱

职责：Agent 间消息传递。每个 Agent 一个 JSON 收件箱文件（共享目录 + 文件锁），
跨进程安全——同进程 SubAgent 和独立窗格 worker 进程都能收发。

```python
@dataclass
class MailMessage:
    sender: str
    recipient: str
    content: str
    timestamp: str = ""
    type: str = "text"               # text | request | response
    request_id: str = ""
    approve: bool | None = None
    read: bool = False


class Mailbox:
    def __init__(self, base_dir: Path): ...

    def register(self, agent_id: str, name: str = "") -> None: ...
    def unregister(self, agent_id: str) -> None: ...
    def resolve(self, recipient: str) -> str | None:  # id 或别名 -> id
        ...
    def send(
        self, sender: str, recipient: str, content: str,
        type: str = "text", request_id: str = "", approve: bool | None = None,
    ) -> bool: ...
    def drain(self, agent_id: str) -> list[MailMessage]: ...
    def has_pending(self, agent_id: str) -> bool:
        """Lockless read-only check for unread messages (no file locking).
        Used by _handle_background_delivery() to drain loop without
        sending synthetic messages when mailbox is empty."""
        ...
    def peers(self, exclude: str | None = None) -> list[str]: ...
    def reset_all(self) -> None: ...    # 新会话清掉上一会话留痕
```

### 4.17 `core/task_store.py` -- 持久化任务系统

职责：项目级磁盘任务列表（`.mini-agent/tasks.json`），`/todo` 命令与任务工具使用。

```python
@dataclass
class TaskRecord:
    id: str = ""                     # task_ + uuid[:8]，自动生成
    description: str = ""
    status: str = "pending"          # pending | in_progress | completed | failed
    blocked_by: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    tags: list[str] = field(default_factory=list)


class TaskStore:
    def __init__(self, project_dir: Path): ...

    def load(self) -> list[TaskRecord]: ...
    def save(self, tasks: list[TaskRecord]) -> None: ...
    def add(self, task: TaskRecord) -> None: ...
    def get(self, query: str) -> TaskRecord | None:   # id 前缀或描述模糊匹配
        ...
    def update(self, query: str, **fields) -> TaskRecord | None: ...
    def remove(self, query: str) -> bool: ...
    def clear_done(self) -> int: ...
    def find_unblocked_by(self, task_id: str) -> list[TaskRecord]: ...
```

### 4.18 `core/cost_tracker.py` -- 成本跟踪器

职责：订阅 LLMResponseEvent，按模型累计 token 用量并按 `[cost]` 配置计价。
两个时间范围：会话级（内存）和从始至终（总账文件 `~/.mini-agent/cost_ledger.json`）。
`_on_response` 在 `asyncio.Lock` 内执行读-改-写（并行子 Agent 共享 EventBus 可并发发射）。

```python
class CostTracker:
    def __init__(self, config: CostConfig, ledger_path: Path | None = None): ...

    def attach(self, bus) -> None: ...            # 订阅 LLMResponseEvent
    def total_cost(self) -> float: ...            # 会话累计成本
    def budget_status(self) -> tuple[float, str]: ...       # (占比, ok|warn|over)
    def total_budget_status(self) -> tuple[float, str]: ...
    def end_turn(self) -> tuple[float | None, dict[str, int]]: ...
    def summary_lines(self) -> list[str]: ...     # /cost 展示
    def flush_to_ledger(self) -> None: ...        # 退出时并入总账
    def reset_ledger(self) -> None: ...           # /cost reset
```

### 4.19 `extensions/plugin_loader.py` -- 插件生态 (P83)

职责：从两处发现并加载插件——pip 包（`mini_agent.plugins` entry-point 群组）和
本地插件目录（`plugin_dirs` 下的 `*.py` 文件）。插件模块实现四个可选钩子之一：

- `register(ctx: PluginContext)` -- 完全控制，优先于细粒度钩子
- `register_tools(registry: ToolRegistry)`
- `register_commands(registry: SlashCommandRegistry)`
- `register_skills(registry: SkillRegistry)`

```python
@dataclass
class PluginContext:
    tool_registry: ToolRegistry
    slash_commands: SlashCommandRegistry
    skill_registry: SkillRegistry
    event_bus: EventBus
    config: AgentConfig


@dataclass
class LoadedPlugin:
    name: str
    source: str          # "entry_point" 或插件文件路径
    # + 各类注册计数


def load_plugins(
    plugin_dirs: list[str | Path],
    ctx: PluginContext,
    disabled: list[str] | None = None,   # 按 entry-point 名或文件名去后缀匹配
) -> list[LoadedPlugin]: ...
```

### 4.20 `security/remote_confirm.py` -- 跨进程权限确认

职责：窗格 worker 进程（6.4）没有自己的 TUI——权限确认通过文件协议转发给父进程：
worker 写请求文件并轮询决策文件，父进程侧渲染 y/a/n 弹窗后写回决策。

```python
class RemoteConfirm:
    """File-based confirm callback for pane worker processes."""

    def __init__(
        self, workers_dir: Path, agent_id: str,
        poll_interval: float = 0.3, timeout: float = 120.0,
    ): ...

    async def __call__(self, prompt: str) -> bool | str:
        """Write a permission request file and poll for the parent's
        decision. Timeout -> deny."""
        ...


# 父进程侧 helper：
def read_request(workers_dir: Path, agent_id: str) -> dict | None: ...
def write_decision(
    workers_dir: Path, agent_id: str, request_id: str, decision: str
) -> None: ...
```

### 4.21 `security/sandbox/` -- OS 级沙箱

职责：将 bash 命令包裹进操作系统沙箱。由 `SecurityConfig.sandbox` 开关（默认开启），app.py 注入 bash 工具。
- **Linux**：bwrap（首选），不可用时自动降级 unshare（`unshare --mount --map-root-user`，util-linux 预装）。
- **macOS**：seatbelt（`sandbox-exec`）。
- **Windows 双模式**：管理员运行时用 Low Integrity 进程（`_low_integrity.py` helper，ctypes 降低 token 完整性，内核级，等同 bwrap/seatbelt）；非管理员不做文件保护——该限制仅文档说明（config-guide），不打启动警告（attrib 已禁用，会阻断 agent 自身文件写入）。

```python
@dataclass
class SandboxConfig:
    allow_write: list[str] = ...     # 可写路径白名单（工作目录、/tmp）
    deny_write: list[str] = ...      # 显式拒绝（如 ~/.mini-agent）
    network: bool = False


class Sandbox(ABC):
    @abstractmethod
    def wrap(self, command: str, config: SandboxConfig) -> str:
        """Rewrite a shell command to run inside the sandbox."""
        ...

    @abstractmethod
    def available(self) -> bool: ...


def create_sandbox() -> Sandbox | None:
    """Pick the platform implementation (bwrap / unshare / seatbelt / windows) or None."""
    ...
```

---

## 5. 数据流：用户消息在系统中的完整流转

以下展示一条用户消息如何端到端地流经系统的每一层。

```
User types message in terminal
         |
         v
+-------------------------------------------------------------------+
| 1. INTERACTION LAYER                                              |
|    InputHandler.get_user_input() -> raw text | _BG_INTERRUPT      |
|    (input line: bold theme.user_input + framing rules)            |
|    SlashCommandRegistry.is_slash_command(text)?                   |
|    +-- YES -> SlashCommandRegistry.execute() -> render result     |
|    +-- NO  -> Continue to engine                                  |
|    HookManager.run(USER_INPUT) -- BLOCK 可在到达 LLM 前拦截该轮       |
|    EventBus.emit(UserMessageEvent)                                |
+------------------------+------------------------------------------+
                         |
                         v
+------------------------------------------------------------------+
| 2. ENGINE LAYER -- AgentLoop.run(conversation)                    |
|                                                                   |
|    +--- ReAct Loop (every iteration) -----------------------+     |
|    |                                                        |     |
|    |  2a. MAIL: Mailbox.drain(agent_id)                     |     |
|    |      跨 Agent 消息以 USER 消息形式注入会话             |     |
|    |                                                        |     |
|    |  2b. THINK:                                            |     |
|    |      conversation.to_api_messages()                    |     |
|    |      plan_mode? -> 隐藏写工具 schema (_WRITE_TOOLS)    |     |
|    |      EventBus.emit(LLMRequestEvent)                    |     |
|    |      HookManager.run(PRE_LLM)  <- 记忆注入在此发生     |     |
|    |      ContextManager.check_and_compress() 每次调用前    |     |
|    |      ContextManager.ensure_fits() 溢出兜底强制截断     |     |
|    |      LLMProvider.stream(messages, tools) -> chunks     |     |
|    |        on_stream_delta / on_thinking_delta 回调直达 UI |     |
|    |        流式工具执行: IncrementalAssembler 组装完成的   |     |
|    |        调用立即提交执行 (写工具/需确认/询问延迟 ACT)  |     |
|    |      assemble_response() -> LLMResponse                |     |
|    |      EventBus.emit(LLMResponseEvent)                   |     |
|    |      HookManager.run(POST_LLM)                         |     |
|    |      finish_reason=="length"? -> max_tokens 翻倍重试   |     |
|    |      (最多 3 次)                                       |     |
|    |                                                        |     |
|    |  2c. CHECK: Tool calls in response?                    |     |
|    |      +-- NO -> self_verify 未触发过? 注入自检提示再来  |     |
|    |      |         一轮; 否则即为最终回答 -> break loop    |     |
|    |      +-- YES -> Continue to ACT                        |     |
|    |                                                        |     |
|    |  2d. ACT: _act(tool_calls) 两阶段执行                  |     |
|    |      Phase 1 (串行): 逐个权限预检                      |     |
|    |        PermissionManager -> GRANTED/DENIED             |     |
|    |        (PENDING 时弹确认框, 弹窗不可交错所以串行)      |     |
|    |        plan_mode 下写工具直接 DENIED                   |     |
|    |        EventBus.emit(PermissionCheckEvent)             |     |
|    |      Phase 2 (并行): asyncio.gather 执行全部 GRANTED   |     |
|    |        每个工具: EventBus.emit(ToolCallStartEvent)     |     |
|    |          HookManager.run(PRE_TOOL) block/confirm/modify|     |
|    |          Tool.execute(ctx, **args)                     |     |
|    |          ToolResultCache.maybe_spill() 超大输出溢写    |     |
|    |          HookManager.run(POST_TOOL)                    |     |
|    |          EventBus.emit(ToolCallEndEvent)               |     |
|    |      流式期间已提交的任务在此收集结果                  |     |
|    |                                                        |     |
|    |  2e. OBSERVE: Process results                          |     |
|    |      ToolResultCache.spill_batch() 聚合预算再溢写      |     |
|    |      Append ToolResult messages to conversation        |     |
|    |      ContextManager.check_and_compress()               |     |
|    |      _should_continue()? -> loop back to 2a            |     |
|    |                                                        |     |
|    +--------------------------------------------------------+     |
|                                                                   |
|    When loop ends:                                                |
|    EventBus.emit(TurnCompleteEvent) + HookManager.run(TURN_END)   |
+-------------------------------------------------------------------+
```

回合结束后的收尾发生在应用层（`app.py`）而非循环内部：

- **会话保存**：每轮回合结束后 `App` 强制自动保存会话（`_autosave(force=True)`）；斜杠命令后走 30s 节流的自动保存。回合进行中没有定时增量保存。
- **记忆提取**：`MemoryExtractor.maybe_extract` 注册在 `SESSION_END` hook 上，会话结束时执行一次，而不是每轮回合执行。
- **技能激活**：技能仅通过 `/skill` 斜杠命令显式激活，没有按用户输入自动触发的机制。
- **流式渲染**：LLM 输出通过 `on_stream_delta` / `on_thinking_delta` 直连回调送达 UI，不经过事件总线（每 chunk 发事件的开销不值得）。

---

## 6. 事件系统设计

### 6.1 事件总线 (`events/bus.py`)

```python
EventHandler = Callable[[Any], Awaitable[None]]


class EventBus:
    """Async publish-subscribe event bus for decoupling components."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: type, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""

    def on_any(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (for logging, debugging)."""

    def off(self, event_type: type, handler: EventHandler) -> None: ...

    def off_any(self, handler: EventHandler) -> None: ...

    async def emit(self, event: Event) -> None:
        """Dispatch to type handlers + global handlers concurrently."""
```

`emit` 通过 `asyncio.gather(..., return_exceptions=True)` **并发**分发给该事件类型的 handler 与全局 handler；单个 handler 抛异常不会打断分发，异常会被捕获并写入日志（坏 handler 不能炸掉 emit）。没有同步版 emit——所有发射点本身都在协程中。

### 6.2 事件类型 (`models/events.py`)

全部 14 个事件类型如下。注意事件字段刻意保持**扁平的基础类型**（str/int/bool/dict），不引用 LLMResponse、ToolResult 等富对象——事件是给观察者（trace、成本跟踪、监听器插件）消费的快照，不是数据通道。

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    """Base event. All events carry a timestamp."""
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# --- User Events ---
@dataclass
class UserMessageEvent(Event):
    content: str = ""
    is_slash_command: bool = False

# --- LLM Events ---
@dataclass
class LLMRequestEvent(Event):
    message_count: int = 0
    tool_count: int = 0
    estimated_tokens: int = 0

@dataclass
class LLMResponseEvent(Event):
    content: str = ""            # 截断预览（前 100 字符）
    has_tool_calls: bool = False
    tokens_used: int = 0
    # 输入/输出拆分 + 模型名 + 缓存命中——供成本跟踪 (P29)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

# --- Tool Events ---
@dataclass
class ToolCallStartEvent(Event):
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""

@dataclass
class ToolCallEndEvent(Event):
    tool_name: str = ""
    call_id: str = ""
    is_error: bool = False
    duration_ms: float = 0

# --- Permission Events ---
@dataclass
class PermissionCheckEvent(Event):
    """Emitted after each permission decision (for /trace)."""
    tool_name: str = ""
    scope: str = ""       # command / path / tool
    resource: str = ""
    decision: str = ""    # granted / denied
    reason: str = ""      # rule / session_grant / mode:xxx / user_confirm / dangerous
    matched_rule: str = ""  # 匹配的规则模式——供审计追踪

@dataclass
class PermissionRuleAddedEvent(Event):
    """Emitted when a permission rule is dynamically added at runtime."""
    scope: str = ""
    pattern: str = ""
    level: str = ""
    reason: str = ""

@dataclass
class PermissionRuleRemovedEvent(Event):
    """Emitted when a permission rule is dynamically removed at runtime."""
    scope: str = ""
    pattern: str = ""
    level: str = ""

# --- Agent Events ---
@dataclass
class AgentPhaseChangeEvent(Event):
    old_phase: str = ""
    new_phase: str = ""
    iteration: int = 0

@dataclass
class TurnCompleteEvent(Event):
    iteration_count: int = 0
    tools_called: int = 0
    tokens_used: int = 0

# --- SubAgent Events ---
@dataclass
class SubAgentSpawnEvent(Event):
    agent_id: str = ""
    task: str = ""

@dataclass
class SubAgentCompleteEvent(Event):
    agent_id: str = ""
    success: bool = True
    tokens_used: int = 0
    background: bool = False

@dataclass
class ContextSummaryStartEvent(Event):
    agent_count: int = 0

@dataclass
class ContextSummaryDoneEvent(Event):
    duration_ms: float = 0
    char_count: int = 0

# --- Session Events ---
@dataclass
class SessionStartEvent(Event):
    session_id: str = ""

@dataclass
class SessionEndEvent(Event):
    session_id: str = ""
```

不存在的事件说明：LLM 流式 chunk 走 UI 直连回调而非事件（见 §5）；LLM 错误在 Provider 内部重试后以异常抛出；上下文压缩、MCP 连接、技能激活等状态变化通过日志与 UI 提示呈现，没有对应事件类型。

---

## 7. LLM Provider 抽象层 -- 实现细节

### 7.1 共享基础设施（`llm/base.py` + `llm/token_counter.py`）

抽象基类只要求三个成员，另提供一个默认无操作的预热钩子：

```python
class LLMProvider(ABC):
    async def prepare(self) -> None:
        """Optional warmup before first use (e.g. context window probing).
        默认无操作——需要预热的 Provider 覆写它。"""

    @abstractmethod
    async def stream(self, messages, tools=None, **kwargs) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    @property
    @abstractmethod
    def context_window(self) -> int: ...
```

注意接口中**没有** `format_tools`：工具 schema 以 OpenAI function calling 格式在系统内流转，各 Provider 用内部方法 `_convert_tools` 转换为自家 API 格式，不对外暴露。

`base.py` 还提供模块级共享设施：

- **重试基础设施**：`RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 529}`；`MAX_HTTP_RETRIES = 5`（约 31 秒总耐心——限流常是持续配额窗口，实测 3 次快速重试扛不住）；`compute_retry_delay(attempt, retry_after)` 优先尊重服务端 `Retry-After` 头，否则指数退避带抖动（1s → 2s → 4s → 8s → 16s）。各 Provider 仅在**任何 chunk 产出之前**重试，流中断不重试。
- **`assemble_response(chunks)`**：把 StreamChunk 列表组装为完整 LLMResponse（拼接 content/thinking、按 index 组装工具调用增量、取 usage 最大值）。
- **`complete(llm, messages, ...)`**：非流式补全便捷函数 = stream + assemble 一次调用（供记忆提取、压缩等非交互场景使用）。

token 计数不属于任何 Provider，而是共享模块 `llm/token_counter.py`：tiktoken 为**可选依赖**，可用时精确计数（cl100k_base）；否则退回 **CJK 感知**估算——CJK 字符按 1 token/字、其余按 4 字符/token（纯 `len//4` 对中文低估约 4 倍，会导致压缩迟迟不触发）。结果带 LRU 缓存，另有 `truncate_to_tokens` 二分截断工具。

### 7.2 OpenAI Provider（`llm/openai_provider.py`）

```python
class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider (GPT, local servers, Azure, etc.)."""

    def __init__(self, config: LLMConfig) -> None:
        # httpx.AsyncClient 直连 -- 无 openai SDK 依赖
        ...

    async def stream(self, messages, tools=None, **kwargs) -> AsyncIterator[StreamChunk]:
        # SSE streaming; 内部 _convert_tools 转 function calling 格式
        ...

    def count_tokens(self, text: str) -> int:
        # 委托共享的 llm/token_counter.py
        ...

    async def prepare(self) -> None:
        # Probe GET {base_url}/models/{model} for the real context window (P42).
        # Recursively extracts context_window/context_length/max_context_length/
        # max_model_len/max_input_tokens from the response (any nesting depth).
        # Once per instance; silent fallback on failure.
        ...

    @property
    def context_window(self) -> int:
        # 3-tier fallback: probed value -> MODEL_CONTEXT_WINDOWS dict -> 128k
        ...
```

### 7.3 Anthropic Provider（`llm/anthropic_provider.py`）

```python
class AnthropicProvider(LLMProvider):
    """Claude API provider via Messages API with SSE streaming."""

    def __init__(self, config: LLMConfig) -> None:
        # httpx.AsyncClient 直连 Messages API (anthropic-version: 2023-06-01)
        ...

    async def stream(self, messages, tools=None, **kwargs) -> AsyncIterator[StreamChunk]:
        # SSE streaming with thinking blocks; 内部 _convert_tools 转 tool_use 格式
        ...

    def count_tokens(self, text: str) -> int:
        # 委托共享的 llm/token_counter.py（不调用 Anthropic 计数 API）
        ...

    @property
    def context_window(self) -> int: ...
```

**Prompt Caching**：每次请求打 3 个 `cache_control: {"type": "ephemeral"}` 标记——系统提示词、工具列表的最后一项、最后一条用户消息的内容。Anthropic 缓存到标记为止的所有前缀，后续请求命中缓存后输入 token 成本降约 90%。缓存命中数据经 `LLMResponseEvent` 的 `cache_read_input_tokens` / `cache_creation_input_tokens` 字段进入成本跟踪。

### 7.4 Provider 注册表 (`llm/registry.py`)

```python
class ProviderRegistry:
    """Factory for LLM providers."""

    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: type[LLMProvider]) -> None: ...

    @classmethod
    def create(cls, config: LLMConfig) -> LLMProvider:
        """Create a provider instance from config."""

    @classmethod
    def list_providers(cls) -> list[str]: ...

    @classmethod
    def create_for_role(cls, config: AgentConfig, role: str) -> LLMProvider:
        """为混编角色（"planner" / "worker"）创建 Provider：查
        config 的 {role}_profile 指向的 llm_profiles 条目，
        profile 未配置或不存在时回退主模型 config.llm。"""


# Auto-register built-in providers on module import
ProviderRegistry.register("openai", OpenAIProvider)
ProviderRegistry.register("anthropic", AnthropicProvider)
ProviderRegistry.register("openai-responses", OpenAIResponsesProvider)
```

第三个内置 Provider `openai-responses`（`llm/openai_responses_provider.py`）对接 OpenAI Responses API（o 系列推理模型），并定义了自己的异常类型：`LLMAuthenticationError`（key 无效）、`LLMRateLimitError`（带 `retry_after`）、`LLMNetworkError`（连接/超时失败）。外部代码可通过 `ProviderRegistry.register` 注册自定义 Provider。

---

## 8. 工具系统设计 -- 实现细节

### 8.1 内置工具示例（标准模式）

所有工具遵循相同的结构。以 `ReadFileTool` 作为参考实现：

```python
# tools/builtin/read_file.py

class ReadFileParams(BaseModel):
    """Pydantic model for read_file parameters (P46). Auto-generates ToolSchema."""
    file_path: str = Field(description="Path to the file to read")
    offset: int = Field(default=0, description="Line number to start reading from (0-based)")
    limit: int = Field(default=2000, description="Maximum number of lines to read")


class ReadFileTool(Tool):
    _name = "read_file"
    _description = "Read the contents of a file at the given path. ..."
    params_model = ReadFileParams  # schema auto-generated via _schema_from_model (P46/P47)

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        # 权限检查不在工具内部——由 Agent 循环管道的 _check_permission 统一评估
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 2000))

        if not file_path.is_file():
            return self.error_result("", f"File not found: {file_path}")

        max_size = ctx.config.tools.max_file_size
        if file_path.stat().st_size > max_size:
            return self.error_result(
                "", f"File too large (> {max_size} bytes): {file_path}"
            )

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return self.error_result("", f"Failed to read {file_path}: {e}")

        lines = content.splitlines()
        selected = lines[offset:offset + limit]
        numbered = "\n".join(
            f"{i + offset + 1:>6}\t{line}"
            for i, line in enumerate(selected)
        )
        return ToolResult(
            call_id="", name="read_file", output=numbered,
            metadata={"total_lines": len(lines), "shown": len(selected)},
        )
```

全部 20 个内置工具（`tools/builtin/__init__.py` 的 `ALL_BUILTIN_TOOLS`）：

| Tool | 用途 | 安全检查 |
|------|------|----------|
| `read_file` | 读取文件内容（带行号、offset/limit 分页） | path_guard read |
| `write_file` | 创建或覆写文件 | path_guard write |
| `edit_file` | 精确字符串替换编辑文件 | path_guard write |
| `delete_file` | 删除文件 | path_guard write |
| `bash` | 执行 shell 命令 | 命令白/黑名单，危险命令需确认 |
| `glob` | 按模式匹配查找文件 | path_guard read |
| `grep` | 按正则搜索文件内容 | path_guard read |
| `spawn_agents` | 派生并行子 Agent 执行任务 | 工具级规则 |
| `send_message` | 向其他 Agent 邮箱发送消息 | 工具级规则 |
| `wait_message` | 等待/接收邮箱消息 | 工具级规则 |
| `tool_search` | 搜索 MCP 服务器上可用的工具（懒发现） | 工具级规则 |
| `mcp_call` | 按名调用 MCP 工具（dispatch 模式入口） | 工具级规则 |
| `ask_user` | 向用户提结构化问题（自由文本或列选项） | 仅主 Agent 可用 |
| `exit_plan_mode` | LLM 完成计划后主动退出 plan 模式 | plan 模式中可用 |
| `task_create` | 在持久化任务板上创建任务 | 无限制 |
| `task_get` | 按 ID/前缀查询任务详情 | 无限制 |
| `task_list` | 列出任务板上所有任务 | 无限制 |
| `task_update` | 更新任务状态或描述 | 无限制 |
| `load_skill` | 激活已安装的技能（注入 prompt） | 无限制 |
| `install_skill` | 从路径或 git URL 安装技能 | 无限制 |

其中 `tool_search` + `mcp_call` 构成 MCP 的 **dispatch 模式**：不把每个 MCP 工具注册进 LLM 的工具列表（大量 MCP 工具会撑爆 schema 上下文），而是让 LLM 先用 `tool_search` 懒发现、再用 `mcp_call` 转发调用。

**Read-before-edit 强制（`tools/file_state_cache.py`）**：`FileStateCache` 记录每个被 `read_file` 读过的文件的 `mtime_ns`。`edit_file`（及覆盖已存在文件的 `write_file`）执行前过两道门——① 文件必须读过、② 读后 `mtime_ns` 未变——否则拒绝，防止基于陈旧内容或对未读文件的盲目修改。新建文件的 `write_file` 与 `delete_file` 豁免。缓存在 `ToolContext.file_state`，主 Agent 与每个 SubAgent 各持独立实例；成功编辑/写入后刷新条目，后续编辑无需重读。可通过 `[tools] enforce_read_before_edit = false` 关闭（默认 true，关闭时 `file_state=None` 门禁失效）。`ask_user`/`exit_plan_mode`/`task_*`/`load_skill`/`install_skill` 为 B1 流程工具（LLM 自主调用任务板/技能/计划审批/结构化提问）。

**自定义 Agent 类型（B3，`core/agent_type_loader.py`）**：用户可在 `~/.mini-agent/agents/` 或 `./.mini-agent/agents/` 放 `.md` 文件声明自定义 agent 类型。文件格式：YAML frontmatter（`name`/`description`/`allowed_tools`/`max_iterations`）+ body 作为 system_prompt 模板（支持 `{working_dir}/{platform}/{shell}/{iteration_budget}` 四个占位符）。app.py 启动时 `load_agent_types(config.agent_dirs)` 扫描并注册到 `AGENT_TYPES` 字典，消费侧（`get_agent_type`/`SubAgent`/`spawn_agents` 工具）零改动。优先级：项目 > 用户 > 内置（同名覆盖）。`spawn_agents` 工具 schema 的 `agent_type` 描述动态列举所有已注册类型。

### 8.2 MCP 工具适配器 (`tools/mcp/adapter.py`)

与 dispatch 模式相对的是**直接注册模式**：`MCPToolAdapter` 把 MCP 发现的工具包装为内部 `Tool` 注册进 ToolRegistry，工具名在构造时确定为 `mcp_{server}_{tool}`：

```python
class MCPToolAdapter(Tool):
    """Wraps an MCP-discovered tool as an internal Tool."""

    def __init__(
        self,
        server_name: str,
        tool_info: dict[str, Any],   # MCP 发现返回的原始 dict
        manager: MCPManager,
    ) -> None:
        self._server_name = server_name
        self._tool_info = tool_info
        self._manager = manager
        self._name = f"mcp_{server_name}_{tool_info.get('name', 'unknown')}"

    @property
    def schema(self) -> ToolSchema:
        # 从 tool_info["inputSchema"] 的 properties/required
        # 逐项构造 ToolParameter 列表  
        ...

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        original_name = self._tool_info.get("name", "")
        return await self._manager.call_tool(self._server_name, original_name, kwargs)
```

### 8.3 Hook 链集成

Hook 系统（`tools/hooks.py`）定义 11 个生命周期阶段（`HookStage`）：`STARTUP` / `SHUTDOWN` / `SESSION_START` / `SESSION_END` / `USER_INPUT` / `TURN_START` / `TURN_END` / `PRE_LLM` / `POST_LLM` / `PRE_TOOL` / `POST_TOOL`。Hook 返回值动作（`HookAction`）有四种：`CONTINUE` / `BLOCK` / `MODIFY` / `CONFIRM`。`HookManager.run` 按优先级顺序执行，遇 BLOCK 和 CONFIRM 短路返回，MODIFY 更新 `ctx.tool_args` 后继续链上后续 hook。

工具执行始终经过完整安全流水线（`_run_tool_pipeline`）：

```
ToolCall arrives
    |
    v
Permission check (若已在 _act 阶段预检过则跳过)
    | 0. 工具级门: check_tool(name) -- 显式 TOOL 规则直接判定
    |    (DENY 拦截; ALLOW 整体信任跳过资源检查; 无规则继续路由)
    | 1. 按工具类型路由: bash -> check_command,
    |    read_file/glob/grep -> check_path(read),
    |    write_file/edit_file/delete_file -> check_path(write)
    | DENIED -> return error ToolResult
    v
HookManager.run(PRE_TOOL, ctx)
    | BLOCK   -> return error ToolResult with hook reason
    | CONFIRM -> confirm_callback 弹 y/a/n 对话框
    |            (a="always" 本会话同 (工具,原因) 不再问; 拒绝 -> error)
    | MODIFY  -> update args from modified context
    v
Tool.execute(ctx, **validated_args)
    |  超大输出经 ToolResultCache.maybe_spill 溢写磁盘
    v
HookManager.run(POST_TOOL, ctx)
    | observe-only: 记日志、触发副作用
    v
Return ToolResult
```

PRE_TOOL 阶段的 BLOCK/CONFIRM 除了用 Python 注册 hook 外，还可通过**声明式 `[[hooks]]` TOML 规则**配置（`HookRule`）：按工具名 fnmatch 模式 + 可选参数子串/正则匹配，`action = "block"` 直接阻止，`action = "confirm"` 要求用户确认。CONFIRM 裁决在 agent_loop 中通过 `confirm_callback` 弹窗解决；无 UI 回调时安全默认为拒绝。声明式 confirm 规则还支持非交互预判 `would_confirm()`——流式工具执行用它把会弹窗的调用延迟到 `_act()`（见 §9.3）。

---

## 9. Agent Loop 设计 -- ReAct 状态机

### 9.1 状态机

```
                         +-----------+
               +-------->|   IDLE    |<---------------------------+
               |         +-----+-----+                            |
               |               | user_message received            |
               |               v                                  |
               |         +-----------+                            |
               |    +--->| THINKING  |  LLM streaming             |
               |    |    +-----+-----+                            |
               |    |          | LLM response complete            |
               |    |          v                                  |
               |    |    +----------------+                       |
               |    |    | has_tool_calls?|                       |
               |    |    +---+--------+--+                        |
               |    |   NO   |        | YES                       |
               |    |        |        v                           |
               |    |        | +--------------+                   |
               |    |        | | TOOL_CALLING |  execute tools    |
               |    |        | +------+-------+                   |
               |    |        |        | all tools complete        |
               |    |        |        v                           |
               |    |        | +-----------+                      |
               |    |        | | OBSERVING |  append results      |
               |    |        | +-----+-----+                      |
               |    |        |       |                            |
               |    |        |       v                            |
               |    |        | +------------------+               |
               |    |        | | should_continue? |               |
               |    |        | +---+----------+---+               |
               |    |   YES  |     |          | NO                |
               |    +--------+-----+          |                   |
               |                              v                   |
               |                      +------------+              |
               |                      | RESPONDING | final output |
               |                      +------+-----+              |
               |                             |                    |
               +-----------------------------+                    

    At any point:
    +-----------+         +--------------+
    |   ERROR   |         | TERMINATED   |
    +-----------+         +--------------+
    (recoverable)         (max iterations,
                           user cancel,
                           fatal error)
```

状态机之外，`run()` 每轮回合还编排了这些机制：

- **邮箱投递**：每次迭代开始先 `_deliver_mail()` 清空本 Agent 收件箱，跨 Agent 消息以 USER 消息形式注入会话（见 §5）。
- **自检提示（self_verify）**：LLM 首次给出无工具调用的最终回答且迭代数 > 1 时，注入一条自检提示（VERIFY_NUDGE）再跑一轮，给 LLM 一次机会核查未验证的断言；每回合只触发一次，回合结束后从会话历史中清理自检消息。
- **聚合溢写预算**：跟踪本回合累计工具结果字符数 `turn_result_chars`，每批结果经 `ToolResultCache.spill_batch(results, already_used=...)` 检查——单条阈值管不住"每条都不超、合计撑爆"的场景；溢写文件的读回结果豁免（再溢写会死循环）。
- **max_tokens 截断恢复（P44）**：响应 `finish_reason == "length"` 时翻倍 max_tokens 重试，最多 3 次，仍截断则保留最后一次结果；重试前取消截断尝试中流式提交的工具任务（参数可能在 JSON 中途被切断）。
- **计划模式**：`plan_mode` 下从发给 LLM 的工具 schema 中**隐藏**写工具（`_WRITE_TOOLS`），执行阶段再兜底 DENIED。
- **文件快照**：`write_file` / `edit_file` / `delete_file` 执行前快照文件修改前状态，供 `/undo` 恢复。

### 9.2 决策逻辑

`_should_continue` 是**同步方法**、不发事件，四重熔断：

```python
# core/agent_loop.py
def _should_continue(self) -> bool:
    """Decide whether to continue the ReAct loop."""
    # 熔断 1: 迭代上限
    if self._state.iteration >= self._state.max_iterations:
        return False
    if self._cancelled:
        return False
    # 熔断 2: 确认框被拒——被拒是"用户不想做"的强信号，
    # 继续只会让 LLM 找绕过路径；停下并回问用户（默认阈值 1，拒一次即停）
    if self._state.consecutive_confirm_denials >= self._config.max_consecutive_denials:
        self.stop_reason = "confirm_denied"
        return False
    # 熔断 3: 同一 工具+参数 签名连续调用 6 次及以上
    # （同一工具处理不同文件是正常批量工作，只有参数也相同才算死循环）
    recent = self._state.recent_tool_names[-6:]
    if len(recent) >= 6 and len(set(recent)) == 1:
        return False
    # 熔断 4: 最近 15 轮迭代每轮都出现同一工具
    # （iteration_tools 记录每轮迭代用到的工具名集合的滑动窗口——
    #   真死循环是每轮都调同一个工具；批量任务是一轮内并行调多次）
    window = self._state.iteration_tools[-15:]
    if len(window) >= 15:
        common = frozenset.intersection(*window)
        if common:
            return False
    return True
```

熔断 2 的计数器是 `AgentState.consecutive_confirm_denials`：统计**任何确认框被用户拒绝**——危险命令确认、项目外路径确认、hook（`[[hooks]] action=confirm`）确认，以权限判定 reason `user_confirm:no` + hook 确认被拒为准。确认框被拒 +1、确认框获准清零、未弹确认的调用中性不动（被拒之间的只读分析不重置计数）；计数器每回合重置。自动策略拒绝不计数：敏感路径拒绝（`path_guard:sensitive`）、显式 deny 规则、无 UI 默认拒绝仍只是跳过该次调用、任务继续，不触发熔断——那是策略在拦，不是用户当场说"别做"。触发后 `stop_reason="confirm_denied"`，Agent 返回一条回问用户如何处理的消息，app.py 据此显示独立警告。阈值 `max_consecutive_denials` 默认 1——拒一次即停；调大可给被拒后修正重试的空间。这与执行层封堵内联解释器绕过互补：执行层让绕过路径也弹确认，行为层让 Agent 在被拒后干脆停手。

上下文占用不参与终止判定——压缩与 `ensure_fits` 兜底截断（§9.1 / §5）保证上下文不会溢出，无需在此熔断。

### 9.3 两阶段并行工具执行 + 流式提前执行

当 LLM 在单次响应中返回多个工具调用时，`_act()` 分两阶段执行：

```python
async def _act(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
    """Phase 1: sequential permission pre-check (confirmations must not
    interleave). Phase 2: all GRANTED tools execute in parallel."""
    streaming = self._streaming_tasks   # 流式期间已提交的任务
    self._streaming_tasks = {}

    # --- Phase 1: 串行权限预检（流式已提交的跳过） ---
    decisions = []
    for tc in tool_calls:
        if tc.id in streaming:
            decisions.append(PermissionDecision.GRANTED)  # 已在执行
        elif self.plan_mode and tc.name in _WRITE_TOOLS:
            decisions.append(PermissionDecision.DENIED)   # 计划模式拒绝写
        else:
            decisions.append(await self._check_permission(tc))

    # --- Phase 2: 并行执行 / 收集流式结果 ---
    async def _run_one(i: int) -> ToolResult:
        tc = tool_calls[i]
        if tc.id in streaming:
            return await streaming[tc.id]          # 收集流式任务结果
        if decisions[i] == PermissionDecision.DENIED:
            return ToolResult(..., is_error=True)  # Permission denied
        return await self._execute_single_tool(tc, skip_permission=True)

    return list(await asyncio.gather(*(_run_one(i) for i in range(n))))
```

设计要点：

- **为什么两阶段**：权限确认弹窗不可交错，所以预检必须串行；预检通过后的执行才并行。执行已预检过权限，`skip_permission=True` 避免重复检查。
- **无 `return_exceptions`**：工具异常在 `_run_tool_pipeline` 内部就被捕获并包装为 `is_error=True` 的 ToolResult，gather 不会收到裸异常。
- **流式提前执行（streaming tool execution）**：开启 `streaming_tool_execution` 时，`_stream_once` 中的 `IncrementalAssembler` 在流式传输期间逐 chunk 组装工具调用，**一组装完成就 `asyncio.create_task` 提交执行**——工具 #1 执行时工具 #2 还在流式传输。以下调用被延迟到 `_act()`：①写工具（`_WRITE_TOOLS`：write_file/edit_file/delete_file）**无条件延迟**——截断响应（`finish_reason="length"`）会触发 max_tokens 重试，但已 eager 完成的副作用无法回滚（`task.cancel()` 对已完成任务是空操作）→ 重试再产出同一调用会双写/双删（A3 修复；同时覆盖计划模式的写工具拒绝）；②`PermissionManager.would_ask()` 判定会询问用户的；③`HookManager.would_confirm()` 判定会弹确认框的（弹窗不能和流式渲染交错）。`_act()` 对这些已提交的任务直接 `await` 收集结果。

---

## 10. 记忆系统设计

### 10.1 上下文窗口管理

```
Context Window (e.g. 128K tokens)
+--------------------------------------------------+
|  System Prompt + Memory Injection (~2K)           |  <- Always preserved
+--------------------------------------------------+
|  Compressed History Summary (~1-5K)               |  <- Grows with compressions
+--------------------------------------------------+
|                                                   |
|  Active Conversation Messages                     |  <- Most recent messages
|  (grows until compression_threshold)              |
|                                                   |
+--------------------------------------------------+
|  Reserved for LLM Response (~4K)                  |  <- max_tokens output
+--------------------------------------------------+
```

`ContextManager`（`memory/context.py`）跟踪 token 总量。计数优先使用 **API usage 锚点**：LLM 返回的 `usage` 是截至锚点消息的权威总量（连工具 schema 都包含在内），锚点之后新追加的消息才用本地估算——估算误差不再逐轮累积；压缩重排历史后锚点通过对象身份检查自动失效。

**双阈值 + 熔断器**（`context.py`）：

- 软阈值 `compression_threshold`（默认 0.75）触发常规压缩，受熔断器控制；
- 熔断器：连续 `compress_max_failures`（默认 3）次压缩无效（token 未下降）后，本会话跳过后续压缩，只警告一次；
- 硬阈值 `hard_compression_threshold`（默认 0.90）**绕过熔断器**强制压缩，防止上下文彻底爆掉。

压缩目标是单一值：`target = context_window * 0.5`。压缩前捕获最近一条用户消息（防止被摘要吞掉），压缩后重算总量并更新熔断计数。另有 `ensure_fits()` 最终兜底：请求前若仍超窗口，直接 SlidingWindow 强制截断防 API 400。

### 10.2 压缩策略级联

级联为**三级**，第 2 级有两个变体，按 `config.memory.llm_summarize`（默认 `True`）在 `app.py` 装配时二选一：

**第 1 级：DropToolResults** -- 把**保留窗口之外**的冗长工具输出截断为 `MAX_TOOL_OUTPUT=200` 字符 + 统计行（"N lines, M chars total, truncated"），保留工具调用结构。刻意不碰尾部：截断模型正在使用的工具结果会让它以为工具坏了，陷入越读越小的重读螺旋（真实终端实测烧掉 36 轮迭代）。

**第 2 级：LLMSummarizeOldest（LLM 变体，默认）或 SummarizeOldest（抽取式变体）** -- 把最旧的一批消息替换为一条 `compressed=True` 的 SYSTEM 摘要消息。LLM 变体失败时自动回退抽取式摘要——压缩链绝不能因网络错误中断。

**第 3 级：SlidingWindow** -- 兜底：只保留能放进预算的最近消息，并带三重防护——孤儿 tool result 丢弃（防 API 400）、任务锚点（绝不丢最近一条用户消息）、摘要锚点（绝不丢头部压缩摘要）。

保留窗口的分界不是按比例，而是 **token 驱动的 `_compute_keep_split`**：从尾部反向累计 token，满足 `MIN_KEEP_MESSAGES=5` 条且累计 ≥ 保留下限（`KEEP_RECENT_TOKENS=10K`）即停，累计超硬顶（`KEEP_MAX_TOKENS=40K`）强制停。下限/硬顶随 target 缩放（`min(10K, target//2)` / `min(40K, target)`）——小窗口下绝对常量会让摘要级数学上永远达不到目标。分界点还会前移避开 tool result（防孤儿导致 API 400）。

```python
class Compressor:
    """级联运行各压缩策略，直到达到目标。"""

    def __init__(self, strategies: list[CompressionStrategy] | None = None) -> None:
        self._strategies = strategies or [
            DropToolResults(),
            SummarizeOldest(),   # app.py 默认装配 LLMSummarizeOldest(llm)
            SlidingWindow(),
        ]

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        for strategy in self._strategies:
            total = ...  # 每级执行前重算 token 总量
            if total <= target_tokens:
                break
            await strategy.compress(conversation, target_tokens)  # 原地修改，无返回值
            # 每级后记录 compact_boundary（SlidingWindow 可能丢掉摘要，须尽早捕获）
```

注意与早期设计的差异：`Compressor` 不持有 LLM（LLM 由 `LLMSummarizeOldest` 策略自己持有）；`compress()` **原地修改** `conversation.messages` 并返回 `None`；每级执行前重算 token（而非依赖缓存值）。

**LLM 摘要的结构化 prompt**：要求模型先在 `<analysis>` 块简要梳理，再输出 `<summary>` 块，包含 9 个固定小节（Primary Request and Intent / Key Technical Concepts / Files and Code Sections / Errors and Fixes / Problem Solving / All User Messages / Pending Tasks / Current Work / Optional Next Step）。历史中嵌套的旧压缩摘要被声明为权威历史，必须完整传递。解析容错：`<summary>` 未闭合时抢救部分输出；完全没有标签时剥离 `<analysis>` 草稿，空结果触发抽取式回退。

**超长收缩重试**：摘要请求本身可能超模型窗口（400/413 或错误消息含 "context length" 等关键词判定）。此时进入独立于偶发失败重试（`SUMMARY_RETRIES=2`）的收缩循环：每轮丢弃最旧 20% 的可摘要消息（但绝不丢头部旧压缩摘要——它是更早全部历史的唯一记录）并把字符 cap（初始 `MAX_HISTORY_CHARS=24K`）缩 20%，最多 `MAX_SHRINKS=3` 轮，仍失败则回退抽取式摘要。摘要输出预算 `SUMMARY_MAX_TOKENS=8192`（混合推理模型会先烧几千 token 的 reasoning）。

### 10.3 压缩后恢复注入与溢写缓存

**恢复注入**（`context.py _inject_read_files`）：每次压缩后向摘要消息追加恢复上下文——(1) 用户最近一次请求（防 agent 压缩后忘记任务）；(2) 本会话已读文件路径清单（防重读）；(3) 最近至多 5 个文件的截断内容，总预算 `min(5*5000 token, window//4)` 随窗口缩放。旧恢复块先剥离再追加（防重复膨胀）。压缩边界 `compact_boundary`（摘要 + 已读文件 + 最近请求）随会话持久化，`/session load` 后通过 `adopt_boundary()` 恢复。

**溢写缓存**（`memory/tool_result_cache.py`）：压缩-重读膨胀问题的根治。超大工具结果不进对话，落盘到 `~/.mini-agent/cache/results/`，对话中只留 `PREVIEW_CHARS=2000` 字符预览 + 完整文件路径。两层防护：单条阈值 `spill_threshold_chars=50_000`；聚合预算 `aggregate_spill_chars=200_000`（单条都不超但合计撑爆时按大小降序强制溢写）。LLM 读回溢写文件的调用由 `is_spill_readback()` 识别并豁免（PathGuard 对缓存目录只读自动放行，见 §11.2）。

### 10.4 跨会话记忆存储

**Project memory** (`.mini-agent/memory.json` in project root):
```json
{
  "entries": [
    {
      "id": "mem_abc123",
      "content": "This project uses pytest with --tb=short for testing",
      "source": "extracted",
      "created_at": "<ISO8601 timestamp>",
      "tags": ["testing", "pytest"]
    }
  ]
}
```

**User memory** (`~/.mini-agent/memory/user_memory.json`):
```json
{
  "entries": [
    {
      "id": "mem_xyz789",
      "content": "User prefers type hints on all function signatures",
      "source": "user",
      "created_at": "<ISO8601 timestamp>",
      "tags": ["preferences", "python"]
    }
  ]
}
```

`MemoryEntry` 只有 `id / content / source / created_at / tags` 五个字段（`source` 取 `"project" | "user" | "extracted"`），没有相关性评分——相关性判断交给召回时的 LLM（见 10.5）。

### 10.5 记忆提取、召回与合并

**提取**（`memory/extraction.py`）：

```python
class MemoryExtractor:
    """通过 LLM 从对话中提取学习内容并持久化。"""

    def __init__(
        self,
        persistent_memory: PersistentMemory,
        llm: Any = None,
        consolidation_threshold: int = 20,
    ) -> None: ...

    async def maybe_extract(
        self,
        conversation: Conversation,
        project_dir: Path | None = None,
    ) -> list[MemoryEntry]:
        """用户消息 >= 5 条才触发（MIN_TURNS_FOR_EXTRACTION）。
        _extract_candidates: 取最近 20 条消息，用 JSON 输出 prompt 让 LLM
        提取 {content, category, tags}；只提取用户明确陈述/确认的事实。
        _deduplicate（同步方法）: 完全匹配 / 子串包含 / 词重叠相似度 >= 0.6
        三重去重后写入项目级或用户级存储。
        最后 _maybe_consolidate: 条目数 > 20 时触发合并。
        任何失败静默降级——提取绝不阻断退出。"""
        ...
```

**召回**（`memory/recall.py`，P52）：记忆条目超过 `recall_threshold`（默认 10）时，不再盲目注入前 N 条，而是用轻量 LLM 调用挑选与当前消息最相关的 top-k（默认 5）条。失败回退头部截断（`FALLBACK_LIMIT=10`）。

**合并**（`memory/consolidation.py`，P53）：词重叠去重只能捕捉表面相似性；条目超过阈值时，LLM 识别语义相关的组并各合并为一条（要求保留全部信息）。无合并或失败返回 `None`，调用方 no-op。

### 10.6 会话持久化

- **`memory/session_store.py`**：会话以 JSON 存于 `~/.mini-agent/sessions/`。元数据含 `closed_cleanly` 标志——启动时发现上次未干净退出的会话即提示崩溃恢复。`cleanup_stale(max_age_days=30)` 清理过期会话，但**保留**崩溃会话（它们可能还没被恢复过）。
- **`memory/file_snapshots.py`**：操作级 `/undo` 的文件快照。只保留最近 `KEEP_TURNS=5` 轮；单文件超 `MAX_SNAPSHOT_BYTES=30MB` 跳过快照（恢复时提示手动处理）。
- **`memory/project_context.py`**：启动时按优先级查找项目指令文件（`AGENT.md` → `CLAUDE.md` → `.mini-agent/instructions.md`，可经 `[context]` 配置），连同用户级 `~/.mini-agent/instructions.md` 注入 system prompt（默认 8000 字符截断）。

---

## 11. 安全模型

### 11.1 权限评估顺序

`PermissionManager.check()` 是通用入口，按请求的 `scope` 分发到三条管道（`security/permission.py`）：

- **COMMAND** → 命令管道：显式规则/会话授权 → 危险模式确认 → 默认模式；
- **PATH** → 路径管道：显式 DENY 规则 → PathGuard → 通用管道；
- **TOOL** → 通用管道：显式规则 → 会话授权 → 默认模式。

```
+---------------------------------------------------------------+
|              GENERIC PIPELINE (per-scope order)                |
|                                                                |
|  1. Explicit DENY rules -> immediately blocked                 |
|  2. Explicit ALLOW rules -> immediately granted                |
|  3. Session grants (user said "always" earlier) -> granted     |
|  4. Default mode:                                              |
|     - "allow" -> granted                                       |
|     - "ask"   -> prompt user (default)                         |
|     - "deny"  -> blocked (locked-down mode)                    |
+---------------------------------------------------------------+
```

**命令管道的关键细微差别**：`allow` 和 `ask` 模式都会**自动放行普通命令**——只有匹配危险模式的命令才弹确认框；`deny` 模式拒绝一切未被规则放行的命令。开启 `sandbox_auto_allow`（内核沙箱提供隔离）时，连危险命令也自动放行。

**危险命令模式**：`DANGEROUS_COMMAND_PATTERNS` 共 27 条正则，除经典破坏项（`rm`、`sudo`、`chmod 777`、`mkfs`、`dd if=`、Windows 的 `del`、`rmdir`、`rd`、`format`、`curl|sh`——删除类命令 rm/del/rmdir/rd **任意形态均拦截**：裸 `rmdir` 删空目录、`rm`/`del` 删单个文件也弹确认，不限于 `-rf`、`/s`、`/q`）外，还把 **git 写操作纳入 human-in-the-loop**：`git push / commit / reset / stash / rebase / checkout（-b 除外）/ restore / clean` 都需用户确认——提交与改写历史必须由用户主动发起。**内联解释器拦截**：`python -c`/`node -e`/`perl -e`/`ruby -e`/`sh -c`/`bash -c`/`powershell -Command`/`pwsh -c` 等内联代码执行一律标记为危险——堵住 A2 实测中 LLM 被拒危险命令后改用解释器绕过的向量。正则容忍选项变形（rm 长选项/标志后置、chmod 前置选项、`_GIT_PREFIX` 吞 git 全局选项如 `-C path`），堵住常见绕过。**写后执行检测**：`record_written_file()` 追踪本会话 agent 写过的文件，`is_executing_written_script()` 检测 `python script.py`/`cmd /c script.bat` 等执行写过的脚本时弹确认——堵住"先写 .py 文件再执行"的绕过路径。正则容忍选项变形（rm 长选项/标志后置、chmod 前置选项、`_GIT_PREFIX` 吞 git 全局选项如 `-C path`），堵住常见绕过。**诚实边界**：正则黑名单不可能穷尽——LLM 总能变形绕过签名（死循环实验已证），这是减速带而非围墙，命中后人工确认与迭代上限才是真护栏。沙箱默认开启（`sandbox=true`），三平台均提供 OS 级保护：Linux bwrap（unshare 自动后备）、macOS seatbelt、Windows 双模式（管理员 Low Integrity 内核级 / 非管理员无文件保护——限制仅文档说明、不打启动警告，attrib 已禁用）。

**路径管道的顺序刻意为之**：显式 DENY 规则在 PathGuard **之前**评估——否则 PathGuard 的项目内 ALLOW 会短路它们，用户对项目内路径写的 `deny = ["*/secrets/*"]` 会静默失效。

**流式预判 `would_ask()`**：非交互、无副作用地回答"这次调用会不会弹确认框"。供流式提前执行（§9.3）使用：不会弹窗的工具在 LLM 响应还在流式输出时就提前提交，会弹窗的延迟到流结束后（弹窗不能与流式渲染交错）。检查范围包括危险命令正则和写后执行检测。

**规则管理与持久化**：`add_rule() / remove_rule() / list_rules()` 支持运行时增删查（发射 `PermissionRuleAdded/RemovedEvent`）；`save_rule_to_file()` / `load_rule_files()` 读写用户级与项目级 `permissions.toml`，格式为三节两级：

```toml
[commands]
allow = ["docker build *"]
deny  = ["docker rm *"]
[paths]
allow = ["D:/shared/*"]
deny  = ["*/secrets/*"]
[tools]
allow = ["glob"]
deny  = ["delete_file"]
```

`/allow`、`/deny` 斜杠命令即通过这套 API 落盘。每次判定的依据记录在 `last_decision_reason` / `last_matched_rule`，供 `/trace` 展示。

### 11.2 路径守卫 (`security/path_guard.py`)

```python
class PathGuard:
    """将文件系统访问限制在允许的路径内。"""

    def __init__(
        self,
        tool_config: ToolConfig,        # allowed_paths / denied_paths
        security_config: SecurityConfig,
        project_dir: Path,
    ) -> None: ...

    def check(self, path: Path, operation: str = "read") -> PermissionLevel:
        """operation: 'read' | 'write'
        顺序：拒绝目录 -> 敏感文件 -> 项目目录 -> 溢写缓存(只读) -> 允许路径 -> ask
        """
        resolved = path.expanduser().resolve()

        for denied in self._denied_paths:          # 1. 拒绝目录 DENY
            ...
        if self.is_sensitive_file(resolved):        # 2. 敏感文件 DENY
            return PermissionLevel.DENY
        if ...project_dir...:                       # 3. 项目目录 ALLOW
            return PermissionLevel.ALLOW
        if operation == "read" and ...cache_root...:  # 4. 溢写缓存只读 ALLOW
            return PermissionLevel.ALLOW            #    (~/.mini-agent/cache/results)
        for allowed in self._allowed_paths:         # 5. 配置的允许路径 ALLOW
            ...
        return PermissionLevel.ASK                  # 6. 兜底询问
```

敏感文件模式 `SENSITIVE_FILE_PATTERNS`：`.env`、`.env.*`、`*.pem`、`*.key`、`id_rsa*`、`id_ed25519*`、`credentials*`、`*secret*`、`*.p12`、`*.pfx`。例外清单 `SENSITIVE_EXCEPTIONS`：`.env.example` / `.env.sample` / `.env.template` 是模板不是秘密，放行。

这份模式清单同时被 permission.py 的 `command_references_sensitive_file()` 复用：`PathGuard.is_sensitive_file` 只守 read_file/write_file/delete_file 三个文件工具，而 bash 通道曾对路径零检查——`type`/`cat`/`Get-Content`/`more .env` 会作普通命令被自动放行，绕过文件工具的敏感文件拦截并泄漏内容（真实验证实测泄漏过 API key）。现 bash 命令会被 token 化，任一 token 的 basename 命中敏感模式即路由到确认弹窗（reason=`sensitive_file_command`），拒绝时触发确认拒绝熔断。诚实边界同命令黑名单：变量展开 / 通配 / base64 拼接等混淆仍可逃逸——详见 tech-notes §90。

溢写缓存目录（`~/.mini-agent/cache/results`）只读自动放行是配套设计：超大工具结果落盘后占位文案会引导 LLM 读回，每次读回都弹权限框会废掉溢写机制；写入该目录仍走询问。

### 11.3 Worktree 工作树隔离 (`security/worktree.py`)

```python
class WorktreeManager:
    """Git worktree 的创建、跟踪与清理。"""

    def __init__(self, repo_dir: Path, base_dir: str = ".mini-agent/worktrees") -> None: ...

    async def create(self, branch_name: str, base_ref: str = "HEAD") -> Path:
        """git worktree add <base_dir>/<branch_name> -b <branch_name> <base_ref>
        创建后把依赖目录 node_modules/.venv/vendor 符号链接进新 worktree
        （P54，Agent 免重装依赖；Windows 无开发者模式缺符号链接权限时静默跳过）。"""
        ...

    async def remove(self, worktree_path: Path, force: bool = False) -> None: ...
    async def list(self) -> list[WorktreeInfo]: ...
    async def status(self, worktree_path: Path) -> WorktreeInfo: ...
    async def has_uncommitted_changes(self, worktree_path: Path) -> bool: ...
    async def cleanup_stale(self, max_age_days: int) -> list[str]: ...
    async def merge_back(self, branch_name: str, target_branch: str = "") -> MergeResult: ...


@dataclass
class WorktreeInfo:
    path: Path
    branch: str
    head_commit: str
    is_clean: bool


@dataclass
class MergeResult:
    success: bool
    conflicts: list[str] = field(default_factory=list)
    merged_branch: str = ""
    message: str = ""   # git 输出或失败原因
```

与早期设计的差异：`repo_dir` 在构造时绑定（方法不再重复传参）；worktree 统一放在仓库内的 `.mini-agent/worktrees/` 下；`merge_back` 按分支名合并并返回带 `message` 的结果。

### 11.4 跨进程权限确认 (`security/remote_confirm.py`)

窗格 Worker（§12.4）跑在独立进程里，没有父进程的确认弹窗。`RemoteConfirm` 用**文件协议**桥接：worker 侧把请求原子写入 `~/.mini-agent/workers/<agent_id>.perm-request.json`，然后轮询父进程写出的 `<agent_id>.perm-decision.json`；父进程侧（`SubAgentManager._collect_pane_result`）轮询到请求后弹自家确认框，把决定（`y`/`n`/`a`=always）写回。超时 120 秒未决则**默认拒绝**（安全兜底）。请求/决定文件均原子写入（临时文件 + rename），超时或取消时清理孤立文件。

### 11.5 审计日志 (`security/audit.py`)

合规审计器订阅 EventBus（工具调用起止、用户消息等），以 JSONL 追加写入。防篡改设计：每条记录携带 `hash = sha256(prev_hash + 规范化记录)` 的**哈希链**，篡改或删除任何一行都会破坏链条；`verify_chain()` 可重放校验（`/audit verify`）。并行工具执行下用锁保护链完整性。

### 11.6 OS 级沙箱 (`security/sandbox/`)

三平台全覆盖，默认开启（`SecurityConfig.sandbox = True`）：

- **Linux**：bubblewrap（`bwrap`，首选）——用户命名空间隔离、只读 rootfs；不可用时自动降级 `unshare --mount --map-root-user`（`unshare.py`，util-linux 预装）。
- **macOS**：Seatbelt（`sandbox-exec`）——SBPL deny-default profile。
- **Windows 双模式**（`windows.py`）：管理员运行时用 Low Integrity 进程（`_low_integrity.py` helper，ctypes 降低 token 完整性，内核级，等同 bwrap/seatbelt）；非管理员不做文件保护——该限制仅文档说明（config-guide），不打启动警告（attrib 已禁用，会阻断 agent 自身文件写入）。

`create_sandbox()` 探测可用实现并包装 bash 命令。`SandboxConfig` 声明可写路径（工作目录、`tempfile.gettempdir()`）和 `sandbox_network` 网络开关。启动时若后端不可用或降级，显示警告告知用户。配套配置 `sandbox_auto_allow`：沙箱已提供隔离时，权限层自动放行命令（含危险命令，见 11.1）。

---

## 12. 多 Agent 设计

### 12.1 子 Agent 派生

```
Main Agent (user-facing)
    |
    |  "Fix the auth bug and update the tests in parallel"
    |
    +---- spawn("fix auth bug in login.py", isolation="worktree")
    |         |
    |         +-- WorktreeManager.create("agent-<id>")
    |         +-- New AgentLoop with restricted tools
    |         +-- Runs independently in worktree directory
    |
    +---- spawn("update test_login.py tests", isolation="worktree")
    |         |
    |         +-- WorktreeManager.create("agent-<id>")
    |         +-- New AgentLoop with restricted tools
    |         +-- Runs independently in worktree directory
    |
    |  await wait_all([agent1_id, agent2_id])
    |
    +-- Collect SubAgentResults
    +-- Review changes, merge worktrees
    +-- Report to user
```

**Agent 类型系统**（`core/agent_types.py`）：SubAgent 有 4 种差异化类型，各自绑定专用 system prompt、工具集与迭代预算：

| 类型 | 工具集 | max_iterations | 用途 |
|------|--------|----------------|------|
| `explore` | 只读（read_file/glob/grep/bash/send_message/wait_message） | 30 | 代码库调研 |
| `plan` | 只读（同上） | 30 | 产出实现计划 |
| `worker` | 不限（默认类型） | 50 | 全能力执行 |
| `verify` | 只读（同上） | 20 | 验证，末尾输出 PASS/FAIL |

未指定类型时回退 `DEFAULT_AGENT_TYPE="worker"` 的提示词/工具，但**保留调用方的迭代预算**（P80）——`config.max_agent_iterations` 用户可配，不能被类型档案静默覆盖。类型工具列表与调用方 `allowed_tools` 取交集。

```python
# SubAgentManager.spawn（真实签名，无 parent_agent_id）
async def spawn(
    self,
    task: str,
    isolation: str = "none",              # "none" | "worktree"
    allowed_tools: list[str] | None = None,
    agent_type: str | None = None,        # explore | plan | worker | verify
    agent_id: str | None = None,          # spawn_parallel 预生成 id 用
    peers: list[tuple[str, str, str]] | None = None,  # (id, name, task)
    name: str = "",
) -> str:
    worktree_path = None
    if isolation == "worktree":
        branch = f"agent-{uuid.uuid4().hex[:8]}"
        worktree_path = await self._worktree_manager.create(branch)

    agent = SubAgent(task=task, ..., worktree_path=worktree_path,
                     agent_type=get_agent_type(agent_type) if agent_type else None,
                     mailbox=self.mailbox, agent_id=agent_id, peers=peers, name=name)
    handle = asyncio.create_task(agent.run())
    self._active[agent.agent_id] = _ActiveAgent(agent=agent, task_handle=handle, ...)
    await self._event_bus.emit(SubAgentSpawnEvent(agent_id=agent.agent_id, task=task))
    return agent.agent_id
```

`SubAgent` 构造时克隆工具注册表并**立即注销 `spawn_agents`**（递归防护：子 Agent 不能再派生子 Agent），可选接收 `permission_manager`（P82，子 Agent 也走权限评估），并拥有独立的溢写缓存目录（`cache/results/subagent_<id>`，结束时清理）。结果收集经 `wait()/wait_all()`，完成时发射 `SubAgentCompleteEvent`；熔断终止（迭代上限/取消）计为失败而非成功。事件命名为 `SubAgentSpawnEvent` / `SubAgentCompleteEvent`。

**后台模式**：`spawn_agents` 工具的 `background=true` 参数走 `SubAgentManager.spawn_background()`——立即返回 agent ids（不阻塞 LLM），每个 agent 由 notifier 协程 `_notify_on_complete` 等待，完成时经 mailbox 向 'main' 投递含结果的通知（截断 4000 字符）。`SubAgentCompleteEvent.background` 字段区分前/后台完成，app.py 订阅后终端提示并调用 `terminal.interrupt_input()` 中断输入等待——主循环收到 `_BG_INTERRUPT` 哨兵后自动 drain mailbox、注入合成消息、运行 `agent_loop.run()` 处理结果（无需用户手动输入）。TTY 路径用 `prompt_session.app.exit()` 中断并保存/恢复用户部分输入；非 TTY 路径用 `asyncio.wait(FIRST_COMPLETED)` 竞争。`Mailbox.has_pending()` 提供无锁只读查询，避免空消息时发合成消息。默认 `background=false` 保持阻塞语义（需要全部结果再继续的场景）。`/spawn --background <task>` 斜杠命令走 `spawn_background()` 路径，完成后自动投递结果（无需 `/spawn wait`）。

**摘要式上下文 fork**：`spawn_agents` 工具的 `inherit_context=true` 或 `/spawn --fork` 把父对话的 LLM 摘要注入子 agent system prompt 的 `[Inherited context ...]` 段——子 agent 出生时"知道"之前的讨论。摘要经 `memory/compressor.py` 的公开函数 `summarize_conversation()` 生成（复用 P67 的 9 节结构化摘要，LLM 失败回退提取式 digest），每次 spawn 调用生成一次、同批 agent 共享（冻结快照，回避 fork 一致性问题）。`context_summary` 参数透传 `spawn/spawn_parallel/spawn_background` 三层，与 `background` 模式可组合。摘要生成前后 `build_context_summary()` 发射 `ContextSummaryStartEvent`/`ContextSummaryDoneEvent`——app.py 订阅显示终端提示（"Summarizing conversation for context fork..." / "Context summary ready"），TraceRenderer 订阅在 `/trace on` 下显示 `ctx` 行。`background=true + inherit_context=true` 时摘要+spawn 整体放进后台 `asyncio.Task`，`execute()` 立即返回（消息列表浅拷贝防竞态）。`spawn_pane` 与 `/team` 未纳入。

### 12.2 Agent 团队协调 (`core/team.py`)

```python
@dataclass
class TeamConfig:
    name: str
    members: list[TeamMember] = field(default_factory=list)  # name/role/allowed_tools
    isolation: str = "none"      # "none" | "worktree"
    coordinator: bool = False    # 协调者模式：Planner 只分派，文件操作全归 Worker


class AgentTeam:
    """编排者策略团队：分解任务，分派给成员，收集结果。"""

    async def start(self, task: str, timeout: float | None = None) -> TeamRunReport:
        # 1. 扫描真实项目结构喂给 Planner（避免套用通用 web 模板）
        plan = await self._planner.decompose(task, context=...)
        # 2. 依赖分批循环
        while not plan.is_complete:
            batch = [依赖全部就绪的 pending 步骤]   # 无就绪步骤时兜底全跑（防循环依赖死锁）
            # 依赖失败的步骤直接标记 failed 跳过
            for step in ready:
                member = self._match_member(step.role)
                allowed_tools = member.allowed_tools if member else None
                if not step.writes_files:
                    allowed_tools = [剥离 write_file/edit_file/delete_file 后的工具名]  # 能力剥夺而非 prompt 自觉
                agent_id = await self._manager.spawn(
                    task=角色前缀 + step.description + self._build_dep_context(step, results),
                    isolation=self._config.isolation,
                    allowed_tools=allowed_tools,
                )
            batch_results = await self._manager.wait_all(agent_ids, timeout=timeout)
        return TeamRunReport(task=task, plan=plan, results=results)
```

关键机制：

- **依赖分批**：`PlanStep.depends_on` 声明依赖，依赖全部完成的步骤并行派生，依赖失败的步骤标记失败跳过；`_build_dep_context` 把依赖步骤的产出（截断至 4000 字符）拼进后续步骤的任务描述。
- **非写步骤强制只读**：`step.writes_files=False` 的步骤被剥夺 `write_file`/`edit_file`/`delete_file` 工具——能力移除而非 prompt 劝说。
- **协调者模式**：`TeamConfig.coordinator=True` 时 `Planner` 带 `_COORDINATOR_PREFIX`（纯分派：协调者自己不碰任何文件，全部委派给 Worker），且计划步数上限提升、给 Planner 更深的项目结构扫描。
- **强弱模型混编**：`ProviderRegistry.create_for_role(config, "planner"/"worker")` 按 `planner_profile` / `worker_profile`（指向命名 LLM 档案，见 §13）为规划和执行分别选模型——强模型规划、弱模型执行。

### 12.3 Agent 间通信

两条通道各司其职：

**EventBus（状态通道）**：所有 Agent 共享同一 EventBus 实例，`SubAgentSpawnEvent` / `SubAgentCompleteEvent` 等状态事件让编排者与 UI 实时感知进度（进度面板用 `active_snapshots()` 轮询快照）。

**Mailbox（内容通道，`core/mailbox.py`）**：跨 Agent 的实质消息传递。文件收件箱存于 `.mini-agent/mailboxes/`，读改写循环由 `O_EXCL` 锁文件保护（指数退避 + 抖动 + 陈旧锁接管 + 超时）——同进程与跨进程 Agent 通用。配套 `send_message` / `wait_message` 工具：

- 收件人可以是 `'main'`（编排者）、同伴 id/别名、或 `'*'`（广播）；
- `type='request'` 自动分配 request_id，对方以 `type='response'` 携带该 id 应答（可带 approve=true/false），构成请求/响应语义；
- `wait_message` 阻塞等待来信——"等待型"任务不再靠 shell sleep 忙等；
- `spawn_parallel()` **预生成全部 agent_id**，每个 Agent 的 system prompt（MAILBOX_NOTICE）直接列出同伴的 id、别名与任务摘要——兄弟 Agent 无需探测即可互发消息。

### 12.4 窗格 Worker（独立进程）

`SubAgentManager.spawn_pane(task, name, agent_type, timeout=900)` 把 SubAgent 跑在**可见终端窗格的独立进程**里（`core/spawn_backends.py`）：当前会话在 tmux 内则 `tmux split-window`，在 Windows Terminal 内则 `wt split-pane`（wt.exe 存在但不在 WT 会话内时降级弹新窗口）。协议文件（spec/result JSON）放在项目外的 `~/.mini-agent/workers/`——曾有 worker 的 LLM 在项目里读到自己的 spec，"好心"提前写了结果桩。

`core/worker.py` 的 `run_worker()` 是无头执行器：读 WorkerSpec、装配独立的 AgentLoop 与工具、跑完后**原子写出**结果 JSON。父进程轮询结果文件（schema + agent_id 双重校验，拒绝早产桩），并经 `RemoteConfirm` 文件协议（§11.4）中转 worker 的权限请求到自家确认框。窗格 worker 与进程内 Agent 共享同一 Mailbox 目录，wait/cancel/list 接口一致（`_PaneWorkerProxy` 顶替占位）。

### 12.5 远程/浏览器模式 (`remote/`)

P57。`remote/server.py` 的 `RemoteServer` 启动 WebSocket 服务器替代终端 UI：包装 `Application` 的 terminal 拦截 UI 调用，以 NDJSON 事件与浏览器双向通信（`GET /` 返回内置 HTML 页面，`/ws` 升级 WebSocket）。共享同一个 `Application` 实例——引擎、工具、权限、记忆全部复用，只换交互层。

---

## 13. 配置系统

### 13.1 分层配置

优先级栈共 7 层（低到高依次应用）：

```
Priority (highest to lowest):
+---------------------------------------------------------+
|  CLI arguments (--model, --provider, etc.)               |  <- Overrides all
+---------------------------------------------------------+
|  Named LLM profiles (MINI_AGENT_MODELS/PROFILES          |
|    + MINI_AGENT_PLANNER_PROFILE / _WORKER_PROFILE)       |  <- 强弱模型混编
+---------------------------------------------------------+
|  Environment variables (MINI_AGENT_MODEL, etc.)          |
+---------------------------------------------------------+
|  .env file (cwd, injected into os.environ, no overwrite) |
+---------------------------------------------------------+
|  Project config (.mini-agent/config.toml, from cwd)      |  <- Per-project
+---------------------------------------------------------+
|  User config (~/.mini-agent/config.toml)                 |  <- User defaults
+---------------------------------------------------------+
|  Built-in defaults (config/defaults.py)                  |  <- Fallback
+---------------------------------------------------------+
```

`.env` 层的语义是**注入 `os.environ` 且不覆盖已有变量**——已导出的环境变量始终赢过 `.env` 文件。命名 LLM 档案层解析 `MINI_AGENT_MODELS`（旧名 `MINI_AGENT_PROFILES`）声明的档案清单及各自的 provider/model/key 变量，`planner_profile` / `worker_profile` 指向其中的档案实现强弱模型混编（§12.2）。

### 13.2 配置加载器 (`config/loader.py`)

```python
class ConfigLoader:
    """从所有层级加载并合并配置。"""

    @staticmethod
    def load(cli_overrides: dict[str, Any] | None = None) -> AgentConfig:
        config = get_defaults()

        # 1. 用户级 TOML
        user_toml = Path.home() / ".mini-agent" / "config.toml"
        if user_toml.is_file():
            ConfigLoader._merge(config, ConfigLoader._load_toml(user_toml))

        # 2. 项目级 TOML（从 Path.cwd() 取，无 project_dir 参数）
        project_toml = Path.cwd() / ".mini-agent" / "config.toml"
        if project_toml.is_file():
            ConfigLoader._merge(config, ConfigLoader._load_toml(project_toml))

        # 3. .env 注入 os.environ（不覆盖已有变量）
        ConfigLoader._load_dotenv()

        # 4. 环境变量
        config = ConfigLoader._apply_env(config)

        # 5. 命名 LLM 档案（MINI_AGENT_MODELS / MINI_AGENT_PROFILES）
        ConfigLoader._load_profiles(config)

        # 6. 强弱模型混编
        config.planner_profile = os.environ.get("MINI_AGENT_PLANNER_PROFILE", "").strip()
        config.worker_profile = os.environ.get("MINI_AGENT_WORKER_PROFILE", "").strip()

        # 7. CLI 覆盖（最高优先级）
        if cli_overrides:
            config = ConfigLoader._apply_cli(config, cli_overrides)
        return config
```

内部方法分工：`_merge` 深合并 TOML 字典到 dataclass（其中 `[mcp.servers.*]` 由 `_merge_mcp` 特判——每个服务器名映射到一个 `MCPServerConfig`）；`_load_dotenv` 解析 cwd 下的 `.env`；`_apply_env` / `_apply_cli` 应用环境变量与 CLI 覆盖；`_load_profiles` 装载命名档案。

### 13.3 配置文件格式 (TOML)

```toml
# ~/.mini-agent/config.toml (user-level)

[llm]
provider = "anthropic"
model = "claude-sonnet-4-20250514"
temperature = 0.0

[tools]
bash_timeout = 120.0
denied_paths = ["~/.ssh", "~/.aws"]

[memory]
context_window = 200000
compression_threshold = 0.75
auto_extract = true

[security]
permission_mode = "ask"
allowed_commands = ["git *", "npm *", "python *", "uv *"]

[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"

[mcp.servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
transport = "stdio"
```

---

## 14. 扩展机制

### 14.1 技能包如何接入

一个技能包是一个包含 `SKILL.md` 文件的目录：

```
skills/
  code_review/
    SKILL.md           # Markdown with YAML front-matter
    review_prompt.txt  # Optional resource files
```

`SKILL.md` front-matter structure:
```yaml
---
name: code-review
description: Review code changes for bugs, style issues, and improvements
triggers:
  - "review"
  - "code review"
  - "/review"
tools:
  - read_file
  - glob
  - grep
  - bash
---
```

```markdown
# Code Review Skill

You are a code reviewer. Follow these steps:
1. Read the git diff...
[full prompt content follows]
```

**加载**：`SkillRegistry.load_all()` 扫描配置的技能目录，解析每个 `SKILL.md`，提取 front-matter 和正文，创建 `Skill` 对象。除文件加载外，`SkillRegistry.register(skill)` 提供程序化注册路径——插件的 `register_skills` 钩子（14.5）用它注入技能。另有 `install()/uninstall()` 支持从远端源安装技能包，`reload()` 热重载。

**激活**：仅通过 `/skill activate <name>` 手动激活——技能的 prompt 被追加到 system prompt，`/skill deactivate` 精确移除。`match_triggers()` 触发词匹配虽有实现但无调用方（未接线）；激活不做工具可用性校验、不加载资源文件。

**停用**：技能的 prompt 从 system prompt 中移除，资源释放。

### 14.2 斜杠命令如何接入

内置命令由 `extensions/builtin_commands.py` 的 `register_builtin_commands(app)` 集中注册——共 26 个可见命令（help/clear/status/model/compact/memory/session/tools/skill/plugins/trace/explain/audit/theme/plan/spawn/team/todo/cost/record/replay/undo/fork/allow/deny/exit），外加隐藏别名 `/quit`（等价 `/exit`）。

用户自定义命令通过**插件**的 `register_commands` 钩子注册（14.5）：

```python
# ~/.mini-agent/plugins/deploy.py
from mini_agent.extensions.slash_commands import SlashCommand

def register_commands(registry):
    async def deploy_handler(args: str) -> str:
        ...
    registry.register(SlashCommand(
        name="deploy",
        description="Deploy to staging",
        handler=deploy_handler,
    ))
```

### 14.3 MCP 服务器如何接入

MCP 服务器在配置中声明，启动时连接（或在首次使用时延迟连接）：

```python
# During Application.__init__ or on-demand
async def _connect_mcp_servers(self):
    for name, server_config in self.config.mcp.servers.items():
        await self.mcp_manager.connect_server(name, server_config)
        # MCPManager discovers tools via list_tools()
        # Creates MCPToolAdapter for each discovered tool
        # Registers adapted tools in ToolRegistry
        #   with "mcp_<server>_" prefix
```

MCP 连接不依赖任何 SDK：自研 JSON-RPC 传输层（`MCPTransport` 抽象 + `StdioTransport` / `HTTPTransport` 实现）同时处理 stdio 和 HTTP 传输。`MCPManager` 为每个配置的服务器维护一个 `MCPServerConnection` 实例。

### 14.4 Hook 如何接入

Hook 可通过配置文件声明或代码注册。配置格式是 `[[hooks]]` 数组表（`tools/hooks.py` 的 `parse_hook_rules` 解析、`register_hook_rules` 注册为 PRE_TOOL hook）：

```toml
# .mini-agent/config.toml
[[hooks]]
tool = "bash"                      # fnmatch 模式匹配工具名（默认 "*"）
arg = "command"                    # 可选：只检查此参数（省略则检查全部参数值）
regex = "rm -rf|sudo|> /dev/"      # 触发正则（也可用 contains 子串匹配）
reason = "This command looks dangerous."
action = "confirm"                 # "block"（默认）拒绝执行；"confirm" 弹 y/a/n 确认框
```

字段共 6 个：`tool` / `arg` / `contains` / `regex` / `reason` / `action`。`action = "block"` 直接拒绝并把 `reason` 回给 LLM；`action = "confirm"` 复用与权限系统相同的 y/a/n 确认弹窗。

或通过代码：

```python
async def dangerous_cmd_hook(ctx: HookContext) -> HookResult:
    if ctx.tool_name == "bash":
        cmd = ctx.tool_args.get("command", "")
        if any(p in cmd for p in ["rm -rf", "sudo", "> /dev/"]):
            return HookResult(
                action=HookAction.CONFIRM,
                reason=f"Dangerous command detected: {cmd}",
            )
    return HookResult(action=HookAction.CONTINUE)

hook_manager.register(HookStage.PRE_TOOL, dangerous_cmd_hook, priority=10)
```

### 14.5 插件生态 (P83)

`extensions/plugin_loader.py` 提供双通道插件发现：

1. **pip 包**：经 `mini_agent.plugins` entry-point 群组声明——

   ```toml
   # 插件包的 pyproject.toml
   [project.entry-points."mini_agent.plugins"]
   my_plugin = "my_plugin.hooks"
   ```

2. **本地文件**：放进 `plugin_dirs`（配置项）目录的普通 `.py` 文件——免打包，即放即用。

插件模块实现**四钩子契约**中的任意组合：

- `register(ctx: PluginContext)`：全控钩子，可触达工具/命令/技能注册表——存在时**优先**，其余三个钩子被忽略；
- `register_tools(registry: ToolRegistry)`
- `register_commands(registry: SlashCommandRegistry)`
- `register_skills(registry: SkillRegistry)`

安装插件即 opt-in；`disabled_plugins`（按 entry-point 名或文件名去后缀匹配）是关闭开关。导入错误与钩子异常被隔离并警告——坏插件不能拖垮启动。插件注册的工具**绕过 `enabled_tools` 白名单**（用户显式安装即授权）。

同目录下的 `extensions/event_listeners.py` 是更早的轻量监听器插件（P56 前身，仍可用）：`.py` 文件实现 `register(bus)`（全控订阅）或 `on_event(event)`（同步/异步皆可，订阅全部事件）即被加载，异常同样隔离。

---

## 15. 开发阶段

### 第 1 阶段：基础搭建（第 1-2 周）

**目标**：实现与 LLM 的可用对话，搭建基本项目结构。

构建顺序：
1. `pyproject.toml` -- project setup with uv, define `mini-agent` entry point
2. `models/message.py` -- Message, ToolCall, ToolResult, Conversation
3. `models/events.py` -- Event base class plus a few essential events
4. `events/bus.py` -- EventBus (simple async pub/sub)
5. `models/config.py` -- AgentConfig and sub-configs
6. `config/defaults.py` + `config/loader.py` -- Basic config loading
7. `llm/base.py` -- LLMProvider ABC, LLMResponse, StreamChunk
8. `llm/openai_provider.py` -- First working provider (OpenAI-compatible)
9. `llm/registry.py` -- ProviderRegistry
10. `ui/terminal.py` -- Minimal TUI (Rich console + prompt_toolkit input)
11. `ui/renderer.py` -- Basic streaming text renderer
12. `cli.py` + `__main__.py` -- Entry point
13. `app.py` -- Wire terminal + LLM provider, simple send/receive loop

**交付物**：`uv run mini-agent` 启动终端，用户输入消息，LLM 流式响应输出。多轮对话正常工作。

**依赖**：无 -- 这是引导层。

---

### 第 2 阶段：工具系统 + Agent Loop（第 3-4 周）

**目标**：Agent 能够自主使用工具。

构建顺序：
1. `tools/base.py` -- Tool ABC, ToolRegistry, ToolSchema, ToolContext
2. `tools/builtin/read_file.py` -- First tool
3. `tools/builtin/bash.py` -- Second tool (high-leverage)
4. `tools/builtin/write_file.py`
5. `tools/builtin/edit_file.py`
6. `tools/builtin/glob_tool.py`
7. `tools/builtin/grep.py`
8. `core/agent_state.py` -- AgentState, AgentPhase
9. `core/agent_loop.py` -- Full ReAct loop
10. `ui/terminal.py` -- Extend: tool call rendering, spinners, confirmations

注：此阶段的 6 个内置工具最终扩至 20 个（`delete_file`、`spawn_agents`、`send_message`、`wait_message`、`tool_search`、`mcp_call` 在后续阶段加入）。

**交付物**：Agent 能接收如"读取 README 并总结"的任务，自主调用 ReadFile，处理结果并回答。多步工具链正常运行。

**依赖**：第 1 阶段完成。

---

### 第 3 阶段：安全 + Hook（第 5 周）

**目标**：带权限控制的安全工具执行。

构建顺序：
1. `models/permissions.py` -- Permission types
2. `security/permission.py` -- PermissionManager
3. `security/path_guard.py` -- PathGuard
4. `tools/hooks.py` -- HookManager, HookContext, built-in hooks
6. Wire hooks into agent loop (pre/post tool, pre/post LLM)
7. `ui/terminal.py` -- Extend: permission confirmation dialogs

**交付物**：危险 bash 命令触发确认弹窗。敏感文件被拦截。Hook 能拦截和修改工具调用。

**依赖**：第 2 阶段完成。

---

### 第 4 阶段：记忆 + 上下文管理（第 6-7 周）

**目标**：长对话正常工作，会话可持久化，记忆跨会话保留。

构建顺序：
1. `llm/token_counter.py` -- Per-provider token counting
2. `memory/context.py` -- ContextManager
3. `memory/compressor.py` -- Compression strategies
4. `memory/session_store.py` -- Session serialization/deserialization
5. `memory/persistent.py` -- PersistentMemory (project + user)
6. `memory/extraction.py` -- MemoryExtractor
7. `/compact` slash command
8. `/memory` slash command
9. `/session` slash command (save, list, load, delete, tag, untag, tags)

**交付物**：长对话自动压缩且不丢失关键上下文。会话可保存和恢复。关键记忆跨会话持久化。

**依赖**：第 1-3 阶段完成。

---

### 第 5 阶段：扩展协议（第 8-9 周）

**目标**：技能包、斜杠命令和 MCP 集成可用。

构建顺序：
1. `extensions/slash_commands.py` -- SlashCommandRegistry + built-in commands
2. `extensions/skills.py` -- SkillRegistry, skill loading from SKILL.md
3. `tools/mcp/transport.py` -- Stdio and HTTP transport
4. `tools/mcp/client.py` -- MCPManager
5. `tools/mcp/adapter.py` -- MCPToolAdapter
6. `extensions/event_listeners.py` -- Event listener plugin loader
6b. `extensions/plugin_loader.py` -- Plugin ecosystem: entry-point + dir discovery, register hooks
7. Built-in skill packs -- 4 个（code_review、init_project、offline-ollama、teach-mode）
8. `llm/anthropic_provider.py` -- Second LLM provider (Claude)

**交付物**：用户可挂载 MCP 服务器并使用其工具。技能包经 `/skill` 命令手动激活。所有斜杠命令可用。OpenAI 和 Anthropic 两种后端均可工作。

**依赖**：第 1-4 阶段完成。

---

### 第 6 阶段：多 Agent（第 10-12 周）

**目标**：子 Agent 和 Agent 团队实现并行工作。

构建顺序：
1. `security/worktree.py` -- WorktreeManager
2. `core/subagent.py` -- SubAgent, SubAgentManager
3. `core/agent_types.py` -- 差异化 Agent 类型（explore/plan/worker/verify）
4. `core/planner.py` -- Plan mode (structured task decomposition)
5. `core/team.py` -- AgentTeam, TeamConfig
6. `core/mailbox.py` -- 跨 Agent 收件箱（send_message/wait_message）
7. `core/spawn_backends.py` + `core/worker.py` -- 窗格 Worker（tmux / Windows Terminal 独立进程）
8. `remote/` -- WebSocket 远程/浏览器模式
9. UI for monitoring multiple agents
10. Worktree merge and conflict resolution

**交付物**：Agent 能在 worktree 中派生子 Agent，并行执行任务，收集和合并结果。Agent 团队能协调完成大型项目。

**依赖**：所有前置阶段完成。

---

### 第 7 阶段：打磨 + 测试（第 13-14 周）

**目标**：达到生产级质量。

1. Comprehensive unit tests for all modules
2. Integration tests for MCP, agent loop, session persistence
3. Error handling audit -- graceful failures everywhere
4. Performance optimization (streaming latency, token counting caches)
5. `ui/themes.py` -- Theme system
6. `ui/components.py` -- Reusable UI components
7. Documentation, README, contributing guide
8. `ui/input_handler.py` -- Key bindings, vi mode, completions

**交付物**：经过全面测试、文档完善、打磨精细的 TUI Agent。

---

## 关键架构决策与原理

**1. 工具采用组合优于继承。** 所有工具仅需实现 `Tool` ABC 的两个成员（`schema` 属性和 `execute` 方法），没有深层类继承。MCP 工具通过 `MCPToolAdapter` 适配为相同接口。这使工具注册表保持简洁：一个名称到 `Tool` 的扁平字典。

**2. EventBus 作为集成骨架。** 各层不直接相互调用（避免循环依赖），而是通过 EventBus 让任意组件发射事件、任意组件订阅。TraceRenderer 订阅 8 种事件实现 `/trace` 实时观测；AuditLogger 订阅 `ToolCallStartEvent`/`ToolCallEndEvent` 写审计日志；CostTracker 订阅 `LLMResponseEvent` 计费。流式渲染是唯一例外——走 `on_stream_delta` 直连回调（低延迟路径），不经过总线。实现全面解耦。

**3. 全异步到底。** 所有 I/O 操作（LLM 调用、工具执行、MCP 调用、文件 I/O）均为异步。这使得通过 `asyncio.gather()` 并行执行工具成为可能，并在长时间操作期间保持 UI 响应。prompt_toolkit 的异步支持（`run_async()`）可自然集成。

**4. dataclass 优先的数据模型。** 核心数据结构使用 `@dataclass`（多数为 `frozen=True` 以保证不可变）。Pydantic 仅用于工具参数定义（`params_model`，P46/P47，自动生成 JSON Schema + 类型校验）；配置验证走 dataclass + 分层覆盖（`config/loader.py`），未引入 Pydantic（早期设想的 `config/schema.py` 未实现且无需求）。其余模型不使用 Pydantic 以保持依赖图精简。

**5. Provider 抽象使用直接 HTTP。** LLM Provider 使用 `httpx.AsyncClient`，而非依赖供应商 SDK（`openai`、`anthropic`）。这消除了重量级的传递依赖，完全掌控流式行为，并且轻松支持任何 OpenAI 兼容端点。供应商 SDK 可作为可选安装项，用于更精确的 token 计数。

**6. 安全不是可选项。** 权限系统在每次工具调用执行前进行评估。路径守卫默认阻止访问敏感目录。Hook 链允许在每个生命周期点拦截操作。这些都内嵌在 Agent Loop 核心中，而非事后补丁。

**7. 五种扩展机制各司其职。** 斜杠命令用于用户快捷操作（命令式）；技能包用于领域特定的 Agent 行为（增强 Agent）；MCP 服务器用于外部工具集成（扩展工具库）；事件监听器用于旁路观察（订阅事件流，不介入执行）；插件生态（P83）用于打包分发前三者的组合（entry-point / 本地目录双通道发现）。五者互不重叠、互不竞争。

**8. 压缩优先于截断。** 当上下文变长时，系统先尝试智能压缩（摘要、精简工具输出），再兜底截断。这保持了简单滑动窗口会破坏的推理连贯性。

---

### 实现关键文件

- `src/mini_agent/core/agent_loop.py` -- ReAct 循环是整个系统的核心；所有其他组件的存在都是为它服务
- `src/mini_agent/llm/base.py` -- LLM Provider 抽象定义了所有 AI 能力所依赖的契约
- `src/mini_agent/tools/base.py` -- Tool ABC、ToolRegistry 和 ToolContext 定义了所有工具（内置和 MCP）的注册与执行方式
- `src/mini_agent/events/bus.py` -- EventBus 是连接所有层而不产生循环依赖的集成骨架
- `src/mini_agent/app.py` -- Application 编排器装配所有层并管理完整生命周期