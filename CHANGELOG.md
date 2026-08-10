# Changelog

## Unreleased

### Fixed 修复

- **bash GBK output mojibake** — subprocess output now decoded strict UTF-8 → active codepage/GBK → UTF-8 replace (three-tier), so Chinese CMD error messages render correctly. bash 子进程输出三级解码，中文 CMD 错误信息不再乱码。
- **LLM autonomous git commands** — all git state-changing commands (commit/push/reset/stash/rebase/checkout/restore/clean) now require user confirmation (human-in-the-loop), plus CRITICAL system prompt rules. 全部 git 状态修改命令需用户确认 + system prompt 红线。
- **Git Bash (mintty) instant exit** — piped stdin detected via isatty(), falls back to plain input mode (no completion menu; use `winpty mini` for the full experience). mintty 管道 stdin 自动降级朴素输入，`winpty mini` 可获完整体验。
- **Surrogates crash on GBK usernames** — lone surrogate chars (\udcXX) from GBK paths no longer crash the API request; messages are sanitized before JSON encoding. GBK 用户名路径产生的孤立代理字符不再崩 API 请求。

### Added 新增

- **Compression-reread inflation root fix** — two-layer defense: tool results >50K chars spill to disk (conversation keeps a 500-char preview); after compression the summary carries a "files already read" list so the LLM does not re-read them. Configurable via `[memory] spill_threshold_chars` (0 = off). 压缩-重读膨胀根治：大工具结果溢写磁盘 + 压缩后注入已读文件清单。
- **`/memory delete`** — delete memories by ID or content keyword; ambiguous matches list candidates instead of deleting. 按 ID/关键词删除记忆，多匹配时列出候选。
- **Same-tool per-iteration fuse** — second circuit breaker layer: a tool name appearing in every one of the last 8 iterations (args ignored) stops the loop; parallel batch reads within few iterations are unaffected. same-tool 按轮熔断（连续 8 轮每轮出现即停，一轮内并行批量不误杀）。

- **Anthropic prompt caching** — three `cache_control: ephemeral` markers (system prompt, last tool, last user message) enable API-side caching; subsequent requests pay ~10% for cached input tokens. Cache hit/creation stats parsed into `TokenUsage`. Anthropic prompt 缓存：三处标记启用 API 侧缓存，后续请求缓存命中部分计费约 10%。
- **Streaming tool execution** — tool calls execute the moment they finish assembling mid-stream (tool #1 runs while tool #2 still streams); tools needing confirmation are deferred until after the stream. Toggle: `streaming_tool_execution` (default on). 流式工具执行：工具调用组装完成即执行，需确认的延迟到流后；可配置关闭。
- **@file inline references** — type `@README.md` in your message to auto-inline the file content (10KB cap, Tab completion with directory drilling). Saves a round-trip LLM read_file call. @文件内联引用：输入 `@文件名` 自动内联内容（10KB 上限，Tab 补全支持子目录），省掉一轮 read_file 调用。
- **Permission rule files** — user-defined allow/deny rules in `~/.mini-agent/permissions.toml` (user) and `.mini-agent/permissions.toml` (project); DENY > ALLOW > built-in defaults. Also fixes PATH deny rules being bypassed by the project-dir allow shortcut. 权限规则文件：用户级/项目级 TOML 自定义 allow/deny 规则；修复项目内路径 deny 被短路的盲区。
- **OS-level sandbox** — Linux bubblewrap (bwrap) + macOS Seatbelt (sandbox-exec) kernel isolation for bash commands: read-only rootfs with writable working dir + /tmp. `sandbox_auto_allow` skips confirmation for dangerous commands (kernel provides isolation), but explicit deny rules still block. Config: `[security] sandbox = true`. OS 级沙箱：Linux bwrap + macOS Seatbelt 内核隔离——只读文件系统 + 可写工作目录。
- **Context window API probing** — OpenAI provider probes GET `{base_url}/models/{model}` at startup and after `/model` switch (new `LLMProvider.prepare()` hook, no-op by default) to discover the real context window; recursively extracts 5 field-name variants (context_window/context_length/max_context_length/max_model_len/max_input_tokens) at any nesting depth. Silent fallback: probed → built-in table → 128k. New models work without code changes. 上下文窗口 API 探测：启动/切换模型时经 prepare() 钩子自动从 API 获取真实窗口，递归提取 5 种字段名，失败静默回退内置表 → 128k。
- **Token counting accuracy** — API usage anchoring: the LLM-reported usage total (which covers tool schemas estimation cannot see) anchors the conversation count; only messages after the anchor are estimated, so error no longer accumulates. CJK-aware estimation replaces bare len//4 (real-API test: Chinese was underestimated 56% — the dangerous direction, compression never fired). Also fixes assistant token_count storing total_tokens (N-fold double counting) and Anthropic's split usage events being overwritten during assembly. Token 计数精度：API usage 锚点 + CJK 感知估算（中文原低估 56%），并修复 total_tokens 重复计数与 Anthropic usage 事件覆盖两个 bug。
- **max_tokens recovery** — when a response is cut off (finish_reason "length"), the request retries with a doubled max_tokens (up to 3 times, 4096 → 32768), keeping the last result if still truncated. Anthropic's stop_reason="max_tokens" is normalized to "length" so recovery works for both providers. Mid-stream tool tasks from the truncated attempt are cancelled (their JSON args may be cut off). max_tokens 恢复：回答截断时翻倍重试（最多 3 次），仍截断保留最后结果；Anthropic 归一化 + 截断尝试的流式工具任务取消。
- **Coordinator mode** — `/team --coordinator` restricts the Planner to pure task decomposition: coordinator prompt prefix ("you ONLY decompose and assign"), max_steps relaxed to 8 (cannot self-patch, needs finer granularity), and project scan deepened to 3 levels/120 lines (richer context since the coordinator cannot read files itself). Workers retain full tool access. Coordinator 模式：Planner 纯调度（prompt 强化 + max_steps 放宽 + 扫描加深），Workers 不受影响。
- **Pydantic Schema generation** — 7 core tools now auto-generate JSON schemas from Pydantic BaseModels (ReadFile, WriteFile, EditFile, DeleteFile, Glob, Grep, SpawnAgents). Reduces boilerplate, adds type safety (automatic string→int coercion), and ensures schema stays in sync with parameter validation. BashTool kept hand-written for backward compatibility; Tool.schema can still be overridden. Pydantic 自动生成 schema：7 个核心工具从 Pydantic 类定义生成 JSON schema，减少重复，类型安全（自动字符串转数字），schema 与校验自动同步。
- **Pydantic Schema full enhancement** — `_schema_from_model()` rewritten as raw JSON Schema passthrough: `$ref/$defs` resolution, `title` stripping, full support for Optional/anyOf, array items, nested models, Field constraints, Literal, dict, default values, circular ref protection. Pydantic Schema 全面增强：raw passthrough 直通完整 JSON Schema，支持 Optional/数组/嵌套模型/约束/Literal/dict/默认值。
- **Agent Type Definition** — `AgentTypeDefinition` frozen dataclass with 4 built-in types (explore/plan/worker/verify); SubAgent/SubAgentManager/SpawnAgentsTool accept `agent_type` parameter; `/spawn --type <name>` flag. Each type defines: system prompt, tool whitelist, iteration cap. Agent 类型定义：4 种内置类型（explore/plan/worker/verify），SubAgent 差异化配置（prompt/工具白名单/迭代上限）。

### Fixed 修复（P36 实战补修）

- **Task anchor in truncation** — SlidingWindow now always keeps the latest user message; a long turn (one question + dozens of tool results) could push the question out of the window, leaving the LLM asking "what did you want?". 截断保任务锚点：最近一条用户消息永不丢弃。
- **Respond in user's language** — system prompt now instructs the LLM to always answer in the language the user writes in. 系统提示要求用用户的语言回答。

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
