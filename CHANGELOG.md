# Changelog

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

- P1-P21: 21 development phases completed (see README.md for full list)
- 298 tests, zero external dependencies for testing
- 7 built-in tools (read/write/edit/bash/glob/grep/spawn_agents)
- Multi-agent orchestration (/spawn, /team, spawn_agents tool)
- Mechanism experiments (compression A/B, strong/weak model mixing)
- Session auto-save with crash recovery
- Theme system (default/dark/light)
- TOML configuration (user-level + project-level)
- Audit logging with hash-chain tamper detection
