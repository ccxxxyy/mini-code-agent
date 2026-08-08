# Changelog

## Unreleased

### Fixed 修复

- **bash GBK output mojibake** — subprocess output now decoded strict UTF-8 → active codepage/GBK → UTF-8 replace (three-tier), so Chinese CMD error messages render correctly. bash 子进程输出三级解码，中文 CMD 错误信息不再乱码。
- **LLM autonomous git commands** — all git state-changing commands (commit/push/reset/stash/rebase/checkout/restore/clean) now require user confirmation (human-in-the-loop), plus CRITICAL system prompt rules. 全部 git 状态修改命令需用户确认 + system prompt 红线。
- **Git Bash (mintty) instant exit** — piped stdin detected via isatty(), falls back to plain input mode (no completion menu; use `winpty mini` for the full experience). mintty 管道 stdin 自动降级朴素输入，`winpty mini` 可获完整体验。
- **Surrogates crash on GBK usernames** — lone surrogate chars (\udcXX) from GBK paths no longer crash the API request; messages are sanitized before JSON encoding. GBK 用户名路径产生的孤立代理字符不再崩 API 请求。

### Experiments 实验

- **Deadlock induction** — 5 scenarios × 2 arms testing triple fuse under real LLM. Key finding: iteration limit is the only reliable hard fuse; same-tool-6x never triggered (LLM varies arguments each time). 死循环诱导实验：迭代上限是唯一可靠硬熔断，same-tool-6x 从未触发。

### Docs 文档

- New `docs/terminal-guide.md` — how to open each terminal per OS (Windows/macOS/Linux), compatibility levels, troubleshooting table. 新增各系统终端指南。

## v1.0.0

### Interface Freeze 接口冻结

The following ABCs and type aliases are now **stable**. Their method
signatures will not change without a major version bump.

#### Tool (`tools/base.py`)

```python
class Tool(ABC):
    @property
    @abstractmethod
    def schema(self) -> ToolSchema: ...

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult: ...
```

#### LLMProvider (`llm/base.py`)

```python
class LLMProvider(ABC):
    @abstractmethod
    async def stream(
        self, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None, **kwargs: Any
    ) -> AsyncIterator[StreamChunk]: ...

    @abstractmethod
    def count_tokens(self, text: str) -> int: ...

    @property
    @abstractmethod
    def context_window(self) -> int: ...
```

#### HookFn (`tools/hooks.py`)

```python
HookFn = Callable[[HookContext], Awaitable[HookResult]]
```

#### CompressionStrategy (`memory/compressor.py`)

```python
class CompressionStrategy(ABC):
    @abstractmethod
    async def compress(
        self, conversation: Conversation, target_tokens: int
    ) -> None: ...
```

### Supporting Types 支撑类型

These dataclasses are part of the stable interface:

- `ToolSchema`, `ToolParameter`, `ToolContext`, `ToolResult`
- `StreamChunk`, `TokenUsage`, `LLMResponse`, `ToolCallDelta`
- `HookContext`, `HookResult`, `HookAction`, `HookStage`
- `Conversation`, `Message`, `ToolCall`

### What "frozen" means 冻结的含义

- Method signatures (names, parameter types, return types) will not change
- New **optional** parameters may be added with defaults
- New methods may be added to ABCs (existing ones won't change)
- Breaking changes require a major version bump (2.0.0)

### Features 功能

- P1-P34: 34 development phases completed (see README.md for full list)
- 425 tests, zero external dependencies for testing
- Per-turn file change summary (+created / ~modified / -deleted)
- Colored diff preview for edit_file (full-width background highlight)
- 8 built-in tools (read/write/edit/delete/bash/glob/grep/spawn_agents)
- Multi-agent orchestration (/spawn, /team, spawn_agents tool)
- Mechanism experiments (compression A/B, strong/weak model mixing)
- Session auto-save with crash recovery
- Theme system (default/dark/light)
- TOML configuration (user-level + project-level)
- Audit logging with hash-chain tamper detection
- Cost dashboard: per-model pricing, session + all-time ledger, dual budgets with 80%/100% warnings (/cost, /cost turns, /cost reset)
