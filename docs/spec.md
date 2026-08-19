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
│       │   ├── builtin/             # 12 core tools
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
│       │   │   └── mcp_call.py      # MCP tool invocation
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
│       │       └── seatbelt.py      # macOS sandbox-exec backend
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
│   ├── unit/                        # 57 unit test files, 953 tests
│   │   ├── test_agent_loop.py
│   │   ├── test_permissions.py
│   │   ├── test_remote_confirm.py
│   │   ├── ...                      # (57 files total)
│   └── integration/                 # 4 integration test files
│       ├── test_mcp_client.py
│       ├── test_agent_e2e.py
│       ├── test_session_persistence.py
│       └── test_worktree.py
│
├── docs/                            # 15 个专题文档
│   ├── spec.md                      # 完整架构规格说明（本文档，设计基线）
│   ├── agent-architecture.md        # 五层架构详解与模块交互图
│   ├── capabilities.md              # 功能全景与验收状态总览
│   ├── checklist.md                 # 分阶段验收清单（P1-P82 逐项打勾）
│   ├── commands-guide.md            # 25 个斜杠命令完整语法与示例
│   ├── comparison-config-cc.md      # 配置系统对比：mini vs Claude Code
│   ├── comparison-mewcode.md        # 功能对照：mini vs mewcode-python
│   ├── config-guide.md              # 配置文件与上下文文件完全指南
│   ├── output-guide.md              # 终端输出格式与样式说明
│   ├── positioning.md               # 项目定位与技术亮点
│   ├── roadmap.md                   # 开发路线图与里程碑
│   ├── tasks.md                     # 开发任务全记录（P1-P82）
│   ├── tech-notes.md                # 技术笔记（实现细节与决策记录）
│   ├── terminal-guide.md            # 各系统终端打开方法与兼容性
│   └── todo-code-quality.md         # 代码质量待做清单与扩展点跟踪
│
└── skills/                          # Built-in skill packs (shipped with project)
    ├── code_review/
    │   └── SKILL.md
    ├── init_project/
    │   └── SKILL.md
    ├── offline-ollama/
    │   └── SKILL.md
    └── teach-mode/
        └── SKILL.md
```

---

## 2. 分层架构图

```
+-------------------------------------------------------------------+
|                    INTERACTION LAYER (ui/)                        |
|                                                                   |
|  +----------+ +----------+ +------------+ +-----------------+     |
|  | Terminal  | | Renderer | |   Input    | |   Slash Cmds    |    |
|  |  (Rich)  | |(Markdown | |  Handler   | |  + Skills       |     |
|  |          | | Streaming| |(PromptTk)  | |                 |     |
|  +----+-----+ +----+-----+ +-----+------+ +-------+---------+     |
|       |            |             |                 |              |
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
|  |  +----------+  +------------+  +----------------------+   |    |
|  |  | Planner  |  | SubAgent   |  |   Agent Teams        |   |    |
|  |  |(Plan Mode|  | Dispatch   |  |  (Coordination)      |   |    |
|  |  +----------+  +------------+  +----------------------+   |    |
|  +----------+------------------------------------------------+    |
|             |                                                     |
|  +----------v------------------------------------------------+    |
|  |              LLM Provider Abstraction (llm/)              |    |
|  |   +----------+  +------------+  +------------------+      |    |
|  |   | OpenAI   |  | Anthropic  |  |  Custom Provider |      |    |
|  |   +----------+  +------------+  +------------------+      |    |
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
|  +--------------+ +--------------------------------------+        |
|  | Session Store| |      Memory Extraction               |        |
|  +--------------+ +--------------------------------------+        |
|                                                                   |
+-------------------------------------------------------------------+
|                    SECURITY LAYER (security/)                     |
|                                                                   |
|  +--------------+ +--------------+ +----------------------+       |
|  | Permission   | |  Path Guard  | |   Worktree Isolation |       |
|  |  Manager     | |              | |                      |       |
|  +--------------+ +--------------+ +----------------------+       |
|  +--------------+ +------------------------------------------+    |
|  |   Audit      | |   OS Sandbox (bwrap / seatbelt)          |    |
|  +--------------+ +------------------------------------------+    |
+-------------------------------------------------------------------+
```

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

    def append(self, message: Message) -> None: ...
    def to_api_messages(self) -> list[dict[str, Any]]: ...
    def get_messages_by_role(self, role: Role) -> list[Message]: ...
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
    PLANNING = "planning"            # Plan mode decomposition
    ERROR = "error"                  # Recoverable error state
    TERMINATED = "terminated"        # Agent loop ended


@dataclass
class AgentState:
    """Mutable state of an agent loop instance."""
    phase: AgentPhase = AgentPhase.IDLE
    iteration: int = 0              # Current ReAct loop iteration
    max_iterations: int = 50        # Hard cap (AgentConfig overrides to 80)
    last_tool_results: list[ToolResult] = field(default_factory=list)
    error: Exception | None = None
    plan: list[PlanStep] | None = None         # Active plan (plan mode)
    parent_agent_id: str | None = None         # If this is a sub-agent
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.phase in (AgentPhase.TERMINATED, AgentPhase.ERROR)

    def transition(self, new_phase: AgentPhase) -> None:
        """Validates and executes a state transition."""
        ...


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
```

### 3.3 会话 (`models/session.py`)

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SessionMetadata:
    session_id: str                  # UUID
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

    def serialize(self) -> dict: ...
    @classmethod
    def deserialize(cls, data: dict) -> Session: ...
```

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


@dataclass
class SecurityConfig:
    permission_mode: str = "ask"          # allow | ask | deny
    allowed_commands: list[str] = field(default_factory=list)
    denied_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /", "sudo", "curl|sh", "wget|sh"
    ])
    worktree_base_dir: str = ".mini-agent/worktrees"


@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    tools: ToolConfig = field(default_factory=ToolConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    max_agent_iterations: int = 80
    enable_plan_mode: bool = False  # 启动时是否开启 plan 模式（app.py 读取此值赋给 agent_loop.plan_mode）
    skill_dirs: list[str] = field(default_factory=lambda: [
        "./skills", "~/.mini-agent/skills"
    ])
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
    MCP = "mcp"              # Permission for an MCP server action
    NETWORK = "network"      # Permission for network access


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
    # self.context_manager: ContextManager
    # self.session: Session
    # self.agent_loop: AgentLoop
    # self.terminal: Terminal
    # self.mcp_manager: MCPManager
    # self.skill_registry: SkillRegistry
    # self.slash_commands: SlashCommandRegistry
```

### 4.2 `core/agent_loop.py` -- ReAct Agent Loop (主循环)

职责：编排 think-act-observe 循环。接收用户消息，调用 LLM，分发工具调用，收集结果，循环直到 LLM 产生最终回答或达到上限。

```python
class AgentLoop:
    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        context_manager: ContextManager,
        permission_manager: PermissionManager,
        event_bus: EventBus,
        config: AgentConfig,
    ): ...

    async def run(self, user_message: str) -> AsyncIterator[Event]:
        """Execute the full ReAct loop for a user message. Yields events."""
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

    async def _observe(self, results: list[ToolResult]) -> None:
        """Append tool results to conversation, check context limits."""
        ...

    async def _should_continue(self) -> bool:
        """Check iteration limits, token budgets, user cancellation."""
        ...

    def cancel(self) -> None:
        """Cancel the running loop (user interrupt)."""
        ...
```

### 4.3 `llm/base.py` -- LLM Provider 抽象层

职责：定义所有 LLM Provider 实现的统一接口。处理流式响应、工具调用解析、token 计数。

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""
    delta: str = ""                       # Text content delta
    tool_call_delta: ToolCallDelta | None = None
    finish_reason: str | None = None      # "stop", "tool_calls", "length"
    usage: TokenUsage | None = None       # Only on final chunk


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
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class LLMResponse:
    """Completed LLM response (assembled from stream or non-streaming)."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    finish_reason: str = "stop"
    model: str = ""
    thinking: str = ""                    # Extended thinking content (Claude)
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract base for all LLM providers."""

    def __init__(self, config: LLMConfig): ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion -- yields chunks as they arrive."""
        ...

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens for the given text using this provider's tokenizer."""
        ...

    @abstractmethod
    def format_tools(self, tools: list[Tool]) -> list[dict[str, Any]]:
        """Convert internal Tool objects to this provider's tool format."""
        ...

    async def prepare(self) -> None:
        """Optional warmup before first use (e.g. context window probing).
        Default: no-op. 首次使用前的可选预热（如上下文窗口探测），默认无操作。"""

# Module-level helpers (llm/base.py):
# assemble_response(chunks) -- assemble StreamChunk list into LLMResponse
# complete(llm, messages, tools, **kwargs) -- stream + assemble in one call
# Both are standalone functions, not methods -- works with duck-typed LLM objects.

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window size for the configured model."""
        ...
```

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
    permission_manager: PermissionManager
    config: AgentConfig


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


class ToolRegistry:
    """Central registry of all available tools."""

    def __init__(self): ...
        # self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None: ...
    def unregister(self, name: str) -> None: ...
    def get(self, name: str) -> Tool: ...
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
    PRE_TOOL = "pre_tool"            # Before tool execution
    POST_TOOL = "post_tool"          # After tool execution
    PRE_LLM = "pre_llm"             # Before LLM call
    POST_LLM = "post_llm"           # After LLM response
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    USER_INPUT = "user_input"        # After user submits message


@dataclass
class HookContext:
    stage: HookStage
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_result: ToolResult | None = None
    message: Message | None = None
    session: Session | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HookAction(StrEnum):
    CONTINUE = "continue"            # Proceed normally
    BLOCK = "block"                  # Block the operation
    MODIFY = "modify"                # Proceed with modified context
    CONFIRM = "confirm"              # Ask user for confirmation


@dataclass
class HookResult:
    action: HookAction
    modified_context: HookContext | None = None
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
        Short-circuits on BLOCK. Returns final result."""
        ...
```

### 4.6 `tools/mcp/client.py` -- MCP 客户端

职责：管理与 MCP 服务器的连接，发现工具，代理工具调用。使用 MCP Python SDK v2 的 `Client` 高级 API。

```python
class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(
        self, config: MCPConfig, tool_registry: ToolRegistry, event_bus: EventBus
    ): ...

    async def connect_server(
        self, name: str, server_config: MCPServerConfig
    ) -> None:
        """Connect to an MCP server, discover its tools, register them."""
        ...

    async def disconnect_server(self, name: str) -> None: ...
    async def disconnect_all(self) -> None: ...
    def list_servers(self) -> list[str]: ...
    def list_server_tools(self, server_name: str) -> list[ToolSchema]: ...

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

    def __init__(
        self,
        config: MemoryConfig,
        llm_provider: LLMProvider,
        compressor: Compressor,
        event_bus: EventBus,
    ): ...

    def add_message(self, message: Message) -> None:
        """Add a message and update token counts."""
        ...

    def get_messages_for_api(self) -> list[dict[str, Any]]:
        """Return messages that fit within the context window."""
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
    def tokens_remaining(self) -> int: ...
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

    async def search_memory(
        self, query: str, scope: str = "all"
    ) -> list[MemoryEntry]: ...


@dataclass
class MemoryEntry:
    id: str
    content: str                      # The memorized fact/learning
    source: str                       # "project" | "user" | "extracted"
    created_at: datetime = field(default_factory=datetime.now)
    tags: list[str] = field(default_factory=list)
    relevance_score: float = 1.0      # For search ranking
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
    def load_rules_from_config(self, config: SecurityConfig) -> None: ...

    async def check(self, request: PermissionRequest) -> PermissionDecision:
        """Evaluate a permission request. May emit
        UserConfirmRequired event."""
        ...

    async def check_path(
        self, path: Path, operation: str
    ) -> PermissionDecision:
        """Convenience: check file path access permission."""
        ...

    async def check_command(self, command: str) -> PermissionDecision:
        """Convenience: check bash command permission."""
        ...

    def grant_session_permission(
        self, scope: PermissionScope, pattern: str
    ) -> None:
        """User granted permission for remainder of session."""
        ...
```

### 4.10 `ui/terminal.py` -- TUI 终端应用

```python
class Terminal:
    """Main terminal UI -- Rich for rendering, Prompt Toolkit for input."""

    def __init__(self, event_bus: EventBus, config: AgentConfig): ...

    async def run(self) -> None:
        """Main UI event loop."""
        ...

    async def get_user_input(self) -> str:
        """Prompt for user input (multi-line, history, completions)."""
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
    """A loadable skill pack: prompt + tools + resources."""
    name: str
    description: str
    prompt: str                        # System prompt addition
    trigger_patterns: list[str]        # When to auto-suggest this skill
    tools: list[str]                   # Tool names this skill needs
    resources: dict[str, str]          # Name -> content of resource files
    source_path: Path | None = None


class SkillRegistry:
    """Discovers, loads, and manages skill packs."""

    def __init__(self, skill_dirs: list[Path], event_bus: EventBus): ...

    async def load_all(self) -> None:
        """Scan skill directories and load all valid skill packs."""
        ...

    def get(self, name: str) -> Skill | None: ...
    def list_skills(self) -> list[Skill]: ...

    async def activate(
        self, name: str, conversation: Conversation
    ) -> None:
        """Activate a skill -- inject its prompt and make its tools
        available."""
        ...

    async def deactivate(self, name: str) -> None: ...
    def match_triggers(self, user_message: str) -> list[Skill]: ...
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

    # Built-in commands registered in __init__ (25 visible + 1 hidden):
    # /help, /clear, /status, /model, /compact, /memory, /session,
    # /plan, /tools, /skill, /allow, /deny, /exit, /undo, /fork,
    # /trace, /explain, /audit, /theme, /spawn, /team, /todo,
    # /cost, /record, /replay, /quit (hidden alias for /exit)
```

### 4.13 `core/subagent.py` -- 子 Agent 分发

```python
class SubAgent:
    """An independent agent that runs in isolation
    (possibly in a worktree)."""

    def __init__(
        self,
        task: str,
        parent_agent_id: str,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        event_bus: EventBus,
        worktree_path: Path | None = None,
    ): ...

    @property
    def agent_id(self) -> str: ...
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
    tool_calls_made: int
    tokens_used: int
    worktree_path: Path | None = None
    error: str | None = None


class SubAgentManager:
    """Manages spawning, tracking, and collecting results
    from sub-agents."""

    def __init__(self, config: AgentConfig, event_bus: EventBus): ...

    async def spawn(
        self,
        task: str,
        parent_agent_id: str,
        isolation: str = "none",     # "none" | "worktree"
    ) -> str:
        """Spawn a sub-agent. Returns agent_id."""
        ...

    async def spawn_parallel(
        self,
        tasks: list[str],
        parent_agent_id: str,
        isolation: str = "none",
    ) -> list[str]:
        """Spawn multiple sub-agents in parallel."""
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
```

### 4.14 `core/team.py` -- 多 Agent 团队

```python
@dataclass
class TeamMember:
    name: str
    role: str                          # e.g. "frontend", "backend", "tester"
    system_prompt_addition: str = ""
    allowed_tools: list[str] | None = None
    worktree_branch: str = ""


@dataclass
class TeamConfig:
    name: str
    members: list[TeamMember]
    coordination_strategy: str = "orchestrator"
    # orchestrator | peer | pipeline
    coordinator: bool = False  # P45: Planner pure-dispatch mode


class AgentTeam:
    """Coordinates multiple agents working on a shared project."""

    def __init__(
        self,
        config: TeamConfig,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        subagent_manager: SubAgentManager,
        event_bus: EventBus,
    ): ...

    async def start(self, task: str) -> None:
        """Start the team on a task. Orchestrator decomposes
        and assigns."""
        ...

    async def coordinate(self) -> None:
        """Orchestrator loop -- monitor progress, resolve conflicts,
        merge results."""
        ...

    async def stop(self) -> list[SubAgentResult]: ...
    def status(self) -> dict[str, AgentPhase]: ...
```

---

## 5. 数据流：用户消息在系统中的完整流转

以下展示一条用户消息如何端到端地流经系统的每一层。

```
User types message in terminal
         |
         v
+------------------------------------------------------------------+
| 1. INTERACTION LAYER                                              |
|    InputHandler.get_user_input() -> raw text                      |
|    SlashCommandRegistry.is_slash_command(text)?                   |
|    +-- YES -> SlashCommandRegistry.execute() -> render result     |
|    +-- NO  -> Continue to engine                                  |
|    SkillRegistry.match_triggers(text) -> auto-activate skills     |
|    EventBus.emit(UserMessageEvent)                                |
+------------------------+--------- --------------------------------+
                         |
                         v
+------------------------------------------------------------------+
| 2. ENGINE LAYER -- AgentLoop.run(user_message)                    |
|                                                                   |
|    +--- ReAct Loop ------------------------------------------+    |
|    |                                                         |    |
|    |  2a. THINK: Build messages for API                      |    |
|    |      ContextManager.get_messages_for_api()              |    |
|    |      MemoryManager injects relevant memories            |    |
|    |      HookManager.run(PRE_LLM)                           |    |
|    |      LLMProvider.stream(messages, tools) -> chunks      |    |
|    |      EventBus.emit(LLMStreamChunkEvent) per chunk       |    |
|    |      Terminal.render_stream() <- UI shows live          |    |
|    |      Assemble full LLMResponse                          |    |
|    |      HookManager.run(POST_LLM)                          |    |
|    |                                                         |    |
|    |  2b. CHECK: Tool calls in response?                     |    |
|    |      +-- NO  -> Stream is final answer -> break loop    |    |
|    |      +-- YES -> Continue to ACT                         |    |
|    |                                                         |    |
|    |  2c. ACT: Execute tool calls                            |    |
|    |      For each ToolCall:                                 |    |
|    |        PermissionManager.check(request)                 |    |
|    |        +-- DENIED  -> ToolResult(is_error=True)         |    |
|    |        +-- PENDING -> Terminal.confirm() -> GRANT/DENY  |    |
|    |        +-- GRANTED -> proceed                           |    |
|    |        HookManager.run(PRE_TOOL)                        |    |
|    |        ToolRegistry.get(name).execute(ctx, **args)      |    |
|    |        HookManager.run(POST_TOOL)                       |    |
|    |        EventBus.emit(ToolResultEvent)                   |    |
|    |      Independent tool calls run via asyncio.gather()    |    |
|    |                                                         |    |
|    |  2d. OBSERVE: Process results                           |    |
|    |      Append ToolResult messages to conversation         |    |
|    |      ContextManager.check_and_compress() if needed      |    |
|    |      Increment iteration counter                        |    |
|    |      _should_continue()? -> loop back to THINK          |    |
|    |                                                         |    |
|    +---------------------------------------------------------+    |
|                                                                   |
|    When loop ends:                                                |
|    ContextManager.add_message(assistant_response)                 |
|    MemoryExtraction.maybe_extract(conversation)                   |
|    SessionStore.auto_save(session)                                |
|    EventBus.emit(TurnCompleteEvent)                               |
+-------------------------------------------------------------------+
```

---

## 6. 事件系统设计

### 6.1 事件总线 (`events/bus.py`)

```python
import asyncio
from collections import defaultdict
from typing import Any, Callable, Awaitable, Type


EventHandler = Callable[["Event"], Awaitable[None]]  # type: ignore


class EventBus:
    """Async publish-subscribe event bus. Thread-safe for asyncio."""

    def __init__(self) -> None:
        self._handlers: dict[Type[Event], list[EventHandler]] = defaultdict(list)
        self._global_handlers: list[EventHandler] = []

    def on(self, event_type: Type[Event], handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        ...

    def on_any(self, handler: EventHandler) -> None:
        """Subscribe to ALL events (for logging, debugging)."""
        ...

    def off(
        self, event_type: Type[Event], handler: EventHandler
    ) -> None: ...

    async def emit(self, event: Event) -> None:
        """Emit an event to all registered handlers. Non-blocking."""
        ...

    def emit_sync(self, event: Event) -> None:
        """Schedule event emission without awaiting (fire-and-forget)."""
        ...
```

### 6.2 事件类型 (`models/events.py`)

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
class LLMStreamChunkEvent(Event):
    delta: str = ""
    tool_call_delta: ToolCallDelta | None = None

@dataclass
class LLMResponseEvent(Event):
    response: LLMResponse | None = None

@dataclass
class LLMErrorEvent(Event):
    error: str = ""
    retryable: bool = False

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
    result: ToolResult | None = None
    duration_ms: float = 0

# --- Agent Events ---
@dataclass
class AgentPhaseChangeEvent(Event):
    old_phase: AgentPhase | None = None
    new_phase: AgentPhase | None = None
    iteration: int = 0

@dataclass
class TurnCompleteEvent(Event):
    iteration_count: int = 0
    tools_called: int = 0
    tokens_used: int = 0

# --- Context Events ---
@dataclass
class ContextCompressionEvent(Event):
    old_token_count: int = 0
    new_token_count: int = 0
    messages_compressed: int = 0
    strategy_used: str = ""

@dataclass
class ContextOverflowEvent(Event):
    current_tokens: int = 0
    max_tokens: int = 0

# --- Permission Events ---
@dataclass
class PermissionRequestEvent(Event):
    request: PermissionRequest | None = None

@dataclass
class PermissionDecisionEvent(Event):
    request: PermissionRequest | None = None
    decision: PermissionDecision | None = None

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

# --- Session Events ---
@dataclass
class SessionStartEvent(Event):
    session_id: str = ""

@dataclass
class SessionEndEvent(Event):
    session_id: str = ""

# --- SubAgent Events ---
@dataclass
class SubAgentSpawnedEvent(Event):
    agent_id: str = ""
    task: str = ""
    parent_id: str = ""

@dataclass
class SubAgentCompletedEvent(Event):
    agent_id: str = ""
    result: SubAgentResult | None = None

# --- MCP Events ---
@dataclass
class MCPServerConnectedEvent(Event):
    server_name: str = ""
    tools_discovered: int = 0

@dataclass
class MCPServerDisconnectedEvent(Event):
    server_name: str = ""

# --- Skill Events ---
@dataclass
class SkillActivatedEvent(Event):
    skill_name: str = ""

@dataclass
class SkillDeactivatedEvent(Event):
    skill_name: str = ""
```

---

## 7. LLM Provider 抽象层 -- 实现细节

### 7.1 OpenAI Provider（`llm/openai_provider.py`）

```python
class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider (GPT, local servers, Azure, etc.)."""

    def __init__(self, config: LLMConfig) -> None:
        # Uses httpx.AsyncClient directly -- no openai SDK dependency
        # OR uses openai package if installed
        ...

    async def stream(
        self, messages, tools=None, **kwargs
    ) -> AsyncIterator[StreamChunk]: ...

    def count_tokens(self, text: str) -> int:
        # Uses tiktoken for accurate counts
        ...

    def format_tools(self, tools: list[Tool]) -> list[dict]:
        # Converts to OpenAI function calling format:
        # {"type": "function", "function": {"name": ..., "parameters": ...}}
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

### 7.2 Anthropic Provider（`llm/anthropic_provider.py`）

```python
class AnthropicProvider(LLMProvider):
    """Claude API provider with extended thinking support."""

    def __init__(self, config: LLMConfig) -> None:
        # Uses httpx.AsyncClient for Messages API
        ...

    async def stream(
        self, messages, tools=None, **kwargs
    ) -> AsyncIterator[StreamChunk]:
        # Handle SSE streaming with thinking blocks
        ...

    def count_tokens(self, text: str) -> int:
        # Uses anthropic token counting API or estimation
        ...

    def format_tools(self, tools: list[Tool]) -> list[dict]:
        # Converts to Anthropic tool_use format:
        # {"name": ..., "description": ..., "input_schema": ...}
        ...

    @property
    def context_window(self) -> int: ...
```

### 7.3 Provider 注册表 (`llm/registry.py`)

```python
class ProviderRegistry:
    """Factory for LLM providers."""

    _providers: dict[str, Type[LLMProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_class: Type[LLMProvider]) -> None: ...

    @classmethod
    def create(cls, config: LLMConfig) -> LLMProvider:
        """Create a provider instance from config."""
        ...

    @classmethod
    def list_providers(cls) -> list[str]: ...


# Auto-register built-in providers on module import
ProviderRegistry.register("openai", OpenAIProvider)
ProviderRegistry.register("anthropic", AnthropicProvider)
```

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
        file_path = Path(kwargs["file_path"])
        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit", 2000)

        # Security: check path permissions
        decision = await ctx.permission_manager.check_path(file_path, "read")
        if decision == PermissionDecision.DENIED:
            return ToolResult(
                call_id="", name="read_file",
                output=f"Permission denied: {file_path}",
                is_error=True,
            )

        try:
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            selected = lines[offset:offset + limit]
            numbered = "\n".join(
                f"{i + offset + 1:>6}\t{line}"
                for i, line in enumerate(selected)
            )
            return ToolResult(
                call_id="", name="read_file", output=numbered,
                metadata={"total_lines": len(lines)},
            )
        except Exception as e:
            return ToolResult(
                call_id="", name="read_file",
                output=str(e), is_error=True,
            )
```

All ten built-in tools:

| Tool | Key Parameters | Security Check |
|------|---------------|----------------|
| `ReadFileTool` | file_path, offset, limit | path_guard read |
| `WriteFileTool` | file_path, content | path_guard write, confirm overwrite |
| `EditFileTool` | file_path, old_text, new_text | path_guard write |
| `BashTool` | command, timeout, working_dir | command allowlist/denylist, confirm dangerous |
| `GlobTool` | pattern, path | path_guard read |
| `GrepTool` | pattern, path, include | path_guard read |

### 8.2 MCP 工具适配器 (`tools/mcp/adapter.py`)

```python
class MCPToolAdapter(Tool):
    """Wraps an MCP-discovered tool as an internal Tool."""

    def __init__(
        self,
        server_name: str,
        mcp_tool: MCPToolInfo,
        mcp_manager: MCPManager,
    ):
        self._server_name = server_name
        self._mcp_tool = mcp_tool
        self._mcp_manager = mcp_manager

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=f"mcp_{self._server_name}_{self._mcp_tool.name}",
            description=self._mcp_tool.description or "",
            parameters=self._convert_params(self._mcp_tool.input_schema),
        )

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        result = await self._mcp_manager.call_tool(
            self._server_name, self._mcp_tool.name, kwargs
        )
        return result
```

### 8.3 Hook 链集成

工具执行始终经过 Hook 链：

```
ToolCall arrives
    |
    v
PermissionManager.check()
    | DENIED -> return error ToolResult
    | PENDING -> Terminal.confirm() -> grant or deny
    v
HookManager.run(PRE_TOOL, ctx)
    | BLOCK -> return error ToolResult with hook reason
    | MODIFY -> update args from modified context
    v
Tool.execute(ctx, **args)
    |
    v
HookManager.run(POST_TOOL, ctx)
    | can log, modify result, or trigger side effects
    v
Return ToolResult
```

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

### 9.2 决策逻辑

```python
# Inside AgentLoop

async def _should_continue(self) -> bool:
    """Decide whether to continue the ReAct loop."""
    state = self._state

    # Hard stop: max iterations
    if state.iteration >= state.max_iterations:
        await self._event_bus.emit(AgentPhaseChangeEvent(
            new_phase=AgentPhase.TERMINATED,
            metadata={"reason": "max_iterations_reached"},
        ))
        return False

    # Hard stop: user cancelled
    if self._cancelled:
        return False

    # Hard stop: context overflow after compression
    if self._context_manager.usage_ratio > 0.95:
        return False

    # Deduplication guard: detect infinite loops
    recent_calls = [
        tc.name for tc in state.last_tool_results[-6:]
    ]
    if len(recent_calls) >= 6 and len(set(recent_calls)) == 1:
        # Same tool called 6+ times in a row -- likely stuck
        return False

    return True
```

### 9.3 并行工具执行

当 LLM 在单次响应中返回多个工具调用时，独立的调用将并行执行：

```python
async def _act(self, tool_calls: list[ToolCall]) -> list[ToolResult]:
    """Execute tool calls, parallelizing independent calls."""
    tasks = []
    for tc in tool_calls:
        tasks.append(self._execute_single_tool(tc))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tool_results = []
    for tc, result in zip(tool_calls, results):
        if isinstance(result, Exception):
            tool_results.append(ToolResult(
                call_id=tc.id, name=tc.name,
                output=f"Tool execution error: {result}",
                is_error=True,
            ))
        else:
            tool_results.append(result)

    return tool_results
```

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

### 10.2 压缩策略级联

当 `usage_ratio >= compression_threshold`（默认 0.75）时触发：

**第 1 级：精简工具输出** -- 用缩略摘要替换冗长的工具输出（文件内容、命令输出），保留工具调用结构。目标：降至 60%。

**第 2 级：摘要最旧消息** -- 取最旧的 40% 消息，使用 LLM 生成摘要消息替换原始消息。目标：降至 50%。

**第 3 级：滑动窗口** -- 如果仍然超限，仅保留能放入窗口的最近 N 条消息，在前面添加被丢弃内容的摘要。这是兜底方案。

```python
class Compressor:
    def __init__(
        self,
        llm: LLMProvider,
        strategies: list[CompressionStrategy] | None = None,
    ):
        self._llm = llm
        self._strategies = strategies or [
            DropToolResults(),
            SummarizeOldest(llm=llm),
            SlidingWindow(),
        ]

    async def compress(
        self, conversation: Conversation, target_tokens: int
    ) -> Conversation:
        current = conversation
        for strategy in self._strategies:
            if current.total_tokens <= target_tokens:
                break
            current = await strategy.compress(
                current.messages, target_tokens
            )
        return current
```

### 10.3 跨会话记忆存储

**Project memory** (`.mini-agent/memory.json` in project root):
```json
{
  "entries": [
    {
      "id": "mem_abc123",
      "content": "This project uses pytest with --tb=short for testing",
      "source": "extracted",
      "created_at": "2026-08-01T10:30:00",
      "tags": ["testing", "pytest"],
      "relevance_score": 0.95
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
      "created_at": "2026-07-15T08:00:00",
      "tags": ["preferences", "python"],
      "relevance_score": 1.0
    }
  ]
}
```

### 10.4 记忆提取 (`memory/extraction.py`)

```python
class MemoryExtractor:
    """Automatically extracts learnings from conversations."""

    def __init__(
        self,
        llm: LLMProvider,
        persistent_memory: PersistentMemory,
    ): ...

    async def maybe_extract(
        self,
        conversation: Conversation,
        project_dir: Path | None,
    ) -> list[MemoryEntry]:
        """Analyze conversation for extractable learnings.
        Called at end of turn when conversation is substantial.
        Only triggers after 5+ turns or when session ends.
        Uses LLM with extraction prompt to identify:
          - Project conventions discovered
          - User preferences observed
          - Technical facts about the codebase
        Deduplicates against existing memories."""
        ...

    async def _build_extraction_prompt(
        self, conversation: Conversation
    ) -> str: ...

    async def _deduplicate(
        self,
        new_entries: list[MemoryEntry],
        existing: list[MemoryEntry],
    ) -> list[MemoryEntry]: ...
```

---

## 11. 安全模型

### 11.1 权限评估顺序

```
+---------------------------------------------------------------+
|                    PERMISSION EVALUATION ORDER                 |
|                                                                |
|  1. Explicit DENY rules -> immediately blocked                 |
|  2. Explicit ALLOW rules -> immediately granted                |
|  3. Session grants (user said "yes" earlier) -> granted        |
|  4. Default mode:                                              |
|     - "allow" -> granted (development mode, no prompts)        |
|     - "ask"   -> prompt user (default, safe)                   |
|     - "deny"  -> blocked (locked-down mode)                    |
+---------------------------------------------------------------+
```

### 11.2 路径守卫 (`security/path_guard.py`)

```python
class PathGuard:
    """Restricts file system access to allowed paths."""

    def __init__(self, config: SecurityConfig): ...

    def check(self, path: Path, operation: str) -> PermissionLevel:
        """Check if a path is allowed for the given operation.
        operation: 'read' | 'write' | 'execute'
        """
        resolved = path.resolve()

        # Always deny: sensitive directories
        for denied in self._denied_paths:
            if resolved.is_relative_to(denied):
                return PermissionLevel.DENY

        # Always allow: project directory and below
        if (self._project_dir
                and resolved.is_relative_to(self._project_dir)):
            return PermissionLevel.ALLOW

        # Explicitly allowed paths
        for allowed in self._allowed_paths:
            if resolved.is_relative_to(allowed):
                return PermissionLevel.ALLOW

        # Default: ask
        return PermissionLevel.ASK

    def is_sensitive_file(self, path: Path) -> bool:
        """Check if file matches sensitive patterns
        (.env, credentials, keys)."""
        sensitive_patterns = [
            ".env", ".env.*", "*.pem", "*.key", "id_rsa*",
            "credentials*", "*secret*", "*.p12", "*.pfx",
        ]
        ...
```

### 11.3 Worktree 工作树隔离 (`security/worktree.py`)

```python
class WorktreeManager:
    """Manages git worktree creation, tracking, and cleanup."""

    def __init__(self, config: SecurityConfig, event_bus: EventBus): ...

    async def create(
        self,
        repo_dir: Path,
        branch_name: str,
        base_ref: str = "HEAD",
    ) -> Path:
        """Create a new worktree. Returns the worktree path.
        Runs: git worktree add <base>/<branch_name> -b <branch_name>
        """
        ...

    async def remove(
        self, worktree_path: Path, force: bool = False
    ) -> None:
        """Remove a worktree. Checks for uncommitted changes first."""
        ...

    async def list(self, repo_dir: Path) -> list[WorktreeInfo]: ...

    async def merge_back(
        self,
        worktree_path: Path,
        target_branch: str = "main",
    ) -> MergeResult: ...


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
```

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
    |         +-- WorktreeManager.create(repo, "fix-auth-bug")
    |         +-- New AgentLoop with restricted tools
    |         +-- Runs independently in worktree directory
    |
    +---- spawn("update test_login.py tests", isolation="worktree")
    |         |
    |         +-- WorktreeManager.create(repo, "update-tests")
    |         +-- New AgentLoop with restricted tools
    |         +-- Runs independently in worktree directory
    |
    |  await wait_all([agent1_id, agent2_id])
    |
    +-- Collect SubAgentResults
    +-- Review changes, merge worktrees
    +-- Report to user
```

### 12.2 Agent 团队协调

```python
class AgentTeam:
    """Multi-agent team for large cross-domain projects."""

    async def start(self, task: str) -> None:
        """
        Coordination strategy: "orchestrator"

        1. Orchestrator (main agent) receives the task
        2. Orchestrator decomposes task using plan mode
        3. For each subtask, orchestrator spawns a team member
           with role-appropriate system prompt and tool set
        4. Team members work in isolated worktrees
        5. Orchestrator monitors progress via events
        6. When members complete, orchestrator reviews and merges
        7. If conflicts arise, orchestrator resolves or asks user
        """
        # Decompose
        plan = await self._planner.decompose(
            task, self._config.members
        )

        # Assign to members
        for step in plan:
            member = self._match_member(step)
            await self._subagent_manager.spawn(
                task=step.description,
                parent_agent_id=self._orchestrator_id,
                isolation="worktree",
            )

        # Monitor and coordinate
        await self.coordinate()
```

### 12.3 Agent 间通信

Agent 之间通过 EventBus 通信。主 Agent 订阅 `SubAgentCompletedEvent` 和 `SubAgentSpawnedEvent`。每个子 Agent 拥有独立的 AgentLoop，但共享同一个 EventBus 实例，因此编排者能实时接收状态更新。

```python
# In SubAgentManager
async def spawn(self, task, parent_agent_id, isolation="none") -> str:
    agent_id = uuid.uuid4().hex[:8]

    # Set up worktree if requested
    worktree_path = None
    if isolation == "worktree":
        worktree_path = await self._worktree_manager.create(
            self._repo_dir,
            branch_name=f"agent-{agent_id}",
        )

    # Create isolated tool registry (copy, not reference)
    agent_tools = self._tool_registry.clone()

    # Create sub-agent with its own loop
    subagent = SubAgent(
        task=task,
        parent_agent_id=parent_agent_id,
        llm=self._llm_provider,        # Can share the provider
        tool_registry=agent_tools,
        config=self._config,
        event_bus=self._event_bus,      # Shared event bus
        worktree_path=worktree_path,
    )

    # Run in background task
    self._active[agent_id] = asyncio.create_task(subagent.run())
    await self._event_bus.emit(SubAgentSpawnedEvent(
        agent_id=agent_id,
        task=task,
        parent_id=parent_agent_id,
    ))
    return agent_id
```

---

## 13. 配置系统

### 13.1 分层配置

```
Priority (highest to lowest):
+------------------------------------------------+
|  CLI arguments (--model, --provider, etc.)      |  <- Overrides all
+------------------------------------------------+
|  Environment variables (MINI_AGENT_MODEL, etc.) |
+------------------------------------------------+
|  .env file (project root, auto-loaded)          |
+------------------------------------------------+
|  Project config (.mini-agent/config.toml)       |  <- Per-project
+------------------------------------------------+
|  User config (~/.mini-agent/config.toml)        |  <- User defaults
+------------------------------------------------+
|  Built-in defaults (config/defaults.py)         |  <- Fallback
+------------------------------------------------+
```

### 13.2 配置加载器 (`config/loader.py`)

```python
class ConfigLoader:
    """Loads and merges configuration from all layers."""

    @staticmethod
    def load(
        cli_args: dict[str, Any] | None = None,
        project_dir: Path | None = None,
    ) -> AgentConfig:
        """Load configuration with full layer merging."""
        # 1. Start with defaults
        config = _load_defaults()

        # 2. Merge user config
        user_config_path = Path.home() / ".mini-agent" / "config.toml"
        if user_config_path.exists():
            config = _merge(config, _load_toml(user_config_path))

        # 3. Merge project config
        if project_dir:
            project_config_path = (
                project_dir / ".mini-agent" / "config.toml"
            )
            if project_config_path.exists():
                config = _merge(config, _load_toml(project_config_path))

        # 4. Merge environment variables
        config = _merge_env(config)

        # 5. Merge CLI arguments (highest priority)
        if cli_args:
            config = _merge_cli(config, cli_args)

        return config

    @staticmethod
    def _merge(base: AgentConfig, overlay: dict) -> AgentConfig:
        """Deep-merge overlay dict onto base config dataclass."""
        ...
```

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

**加载**：`SkillRegistry.load_all()` 扫描配置的技能目录，解析每个 `SKILL.md`，提取 front-matter 和正文，创建 `Skill` 对象。

**激活**：当用户输入触发词或 `/skill code-review` 时，技能的 prompt 被追加到 system prompt 中。其所需工具会被验证可用。附加的资源文件被加载到上下文中。

**停用**：技能的 prompt 从 system prompt 中移除，资源释放。

### 14.2 斜杠命令如何接入

内置命令在 `SlashCommandRegistry.__init__()` 中注册。用户自定义命令可通过配置文件添加：

```toml
# .mini-agent/config.toml
[slash_commands.deploy]
description = "Deploy to staging"
handler = "bash"
command = "git push origin main && ./deploy.sh staging"
confirm = true
```

或通过代码注册：

```python
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

MCP Python SDK v2 提供了一个高级 `Client` 类，同时处理 stdio 和 HTTP 传输。`MCPManager` 对其进行封装，为每个配置的服务器维护一个 `Client` 实例。

### 14.4 Hook 如何接入

Hook 可通过代码注册或配置文件声明：

```toml
# Config-based hook
[hooks.pre_tool.dangerous_command_guard]
stage = "pre_tool"
tool = "bash"
action = "confirm"
pattern = "rm|sudo|chmod|chown|mkfs|dd"
message = "This command looks dangerous. Proceed?"
```

> **实现注记**：实际落地的配置格式是 `[[hooks]]` 数组表（字段：tool/arg/contains/regex/reason/action），语义与本节设计一致——`action = "block"`（默认）拒绝执行，`action = "confirm"` 弹 y/a/n 确认框。见 config-guide.md "Hook 规则详解"。

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
7. Built-in skill packs (code_review, init_project)
8. `llm/anthropic_provider.py` -- Second LLM provider (Claude)

**交付物**：用户可挂载 MCP 服务器并使用其工具。技能包根据触发词自动激活。所有斜杠命令可用。OpenAI 和 Anthropic 两种后端均可工作。

**依赖**：第 1-4 阶段完成。

---

### 第 6 阶段：多 Agent（第 10-12 周）

**目标**：子 Agent 和 Agent 团队实现并行工作。

构建顺序：
1. `security/worktree.py` -- WorktreeManager
2. `core/subagent.py` -- SubAgent, SubAgentManager
3. `core/planner.py` -- Plan mode (structured task decomposition)
4. `core/team.py` -- AgentTeam, TeamConfig
5. UI for monitoring multiple agents
6. Worktree merge and conflict resolution

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

**2. EventBus 作为集成骨架。** 各层不直接相互调用（避免循环依赖），而是通过 EventBus 让任意组件发射事件、任意组件订阅。UI 订阅 `LLMStreamChunkEvent` 实现实时渲染；记忆系统订阅 `TurnCompleteEvent` 触发记忆提取；安全层订阅 `ToolCallStartEvent` 进行审计日志。实现全面解耦。

**3. 全异步到底。** 所有 I/O 操作（LLM 调用、工具执行、MCP 调用、文件 I/O）均为异步。这使得通过 `asyncio.gather()` 并行执行工具成为可能，并在长时间操作期间保持 UI 响应。prompt_toolkit 的异步支持（`run_async()`）可自然集成。

**4. dataclass 优先的数据模型。** 核心数据结构使用 `@dataclass`（多数为 `frozen=True` 以保证不可变）。Pydantic 用于两个场景：工具参数定义（`params_model`，P46/P47，自动生成 JSON Schema + 类型校验）和配置验证（`config/schema.py`）。其余模型不使用 Pydantic 以保持依赖图精简。

**5. Provider 抽象使用直接 HTTP。** LLM Provider 使用 `httpx.AsyncClient`，而非依赖供应商 SDK（`openai`、`anthropic`）。这消除了重量级的传递依赖，完全掌控流式行为，并且轻松支持任何 OpenAI 兼容端点。供应商 SDK 可作为可选安装项，用于更精确的 token 计数。

**6. 安全不是可选项。** 权限系统在每次工具调用执行前进行评估。路径守卫默认阻止访问敏感目录。Hook 链允许在每个生命周期点拦截操作。这些都内嵌在 Agent Loop 核心中，而非事后补丁。

**7. 三种扩展机制各司其职。** 斜杠命令用于用户快捷操作（命令式）；技能包用于领域特定的 Agent 行为（增强 Agent）；MCP 服务器用于外部工具集成（扩展工具库）。三者互不重叠、互不竞争。

**8. 压缩优先于截断。** 当上下文变长时，系统先尝试智能压缩（摘要、精简工具输出），再兜底截断。这保持了简单滑动窗口会破坏的推理连贯性。

---

### 实现关键文件

- `src/mini_agent/core/agent_loop.py` -- ReAct 循环是整个系统的核心；所有其他组件的存在都是为它服务
- `src/mini_agent/llm/base.py` -- LLM Provider 抽象定义了所有 AI 能力所依赖的契约
- `src/mini_agent/tools/base.py` -- Tool ABC、ToolRegistry 和 ToolContext 定义了所有工具（内置和 MCP）的注册与执行方式
- `src/mini_agent/events/bus.py` -- EventBus 是连接所有层而不产生循环依赖的集成骨架
- `src/mini_agent/app.py` -- Application 编排器装配所有层并管理完整生命周期