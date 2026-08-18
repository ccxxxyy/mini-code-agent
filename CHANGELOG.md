# Changelog

## Unreleased

### Added 新增

- **Default agent type wired (P80)** — `DEFAULT_AGENT_TYPE` (extension point #10) now backs untyped sub-agent spawns: `SubAgent.__init__` falls back to the `worker` type's prompt/tool logic instead of a near-duplicate inline `SUBAGENT_SYSTEM_PROMPT` (deleted). Untyped spawns keep the user-tunable `config.max_agent_iterations` budget (not silently clamped to the worker profile's 50); explicit `--type` opt-in still adopts the full type profile. 4 new tests, 938 total; real-LLM verified via `experiments/verify_default_agent_type.py`. 默认 Agent 类型接线（扩展点 #10）：未指定类型的 SubAgent 回退 worker 档案（删除重复内联 prompt），保留用户可配迭代预算；显式选类型仍采纳类型完整档案。
- **Tool-level permissions + universal check entry (P79)** — `PermissionScope.TOOL` (extension point #9) wired end to end: a tool-level gate runs before command/path checks for every tool call — a TOOL deny rule blocks the tool outright, a TOOL allow rule trusts it wholesale (skips resource checks, so even dangerous commands stop confirming), no match falls through to the existing routing. `/allow`/`/deny` accept the `tool` scope and `permissions.toml` gains a `[tools]` section (load + `--save`); `would_ask()` resolves tool rules without prompting. `PermissionManager.check()` (extension point #15) refactored into a true universal entry that dispatches by scope — COMMAND requests get dangerous-pattern confirmation, PATH requests go through PathGuard, instead of both silently bypassing them. `/allow remove` / `/deny remove` subcommands delete session rules by exact scope+pattern+level (TOML-sourced rules reload on next start); `[scope]` in command output is now escaped so markdown stops swallowing it as a reference link. 22 new tests, 934 total; real-LLM verified via `experiments/verify_tool_permission.py` (4 phases). 工具级权限与通用检查入口（扩展点 #9/#15 接入，issue #175）：工具门先于命令/路径检查（deny 拦工具、allow 整体信任、无匹配落回资源检查）；`/allow` `/deny` 支持 tool scope 和 `remove` 子命令，permissions.toml 新增 `[tools]` 节；`check()` 重构为按 scope 分发的真正通用入口（COMMAND 走危险确认、PATH 走 PathGuard）；输出 `[scope]` 转义修复。
- **Runtime permission rule management (P78)** — `PermissionManager.add_rule()` (extension point #3) enhanced from a one-liner stub to a full runtime API: validates empty patterns, deduplicates by scope+pattern+level, emits `PermissionRuleAddedEvent` via EventBus. New `remove_rule()` (with `PermissionRuleRemovedEvent`), `list_rules()`, and `save_rule_to_file()` (TOML persistence). `/allow` and `/deny` slash commands for interactive rule management (`/allow command "docker *"`, `--save` to persist to `.mini-agent/permissions.toml`). Internal callers (`_load_rules_from_config`, `load_rule_files`) unified through `add_rule(_silent=True)`. 13 new tests, 912 total. 运行时权限规则管理（扩展点 #3 接入）：add_rule 增强（校验/去重/事件）+ remove_rule/list_rules/save_rule_to_file + `/allow` `/deny` 斜杠命令（`--save` 持久化到 TOML）；内部加载统一走 add_rule。
- **Four mid-level extension points wired (P77)** — (1) `ToolRegistry.filter()` now used in `AgentTeam.start()` (non-writer steps) and `SubAgent.__init__` (tool whitelist), replacing ad-hoc list comprehensions; (2) `Plan.is_complete` drives the team loop (`while not plan.is_complete` replaces manual pending-list tracking); (3) `SessionMetadata.tags` wired with `/session tag`/`untag`/`tags` subcommands and `/session list --tag <name>` filtering (tags survive save/load, displayed in session list); (4) `PermissionRequest.tool_name` populated by `check_path(tool_name=tc.name)` so permission decisions carry the originating tool name for audit. 四个中级扩展点接入：ToolRegistry.filter 替代手动过滤、Plan.is_complete 驱动团队循环、SessionMetadata.tags 会话标签命令、PermissionRequest.tool_name 权限审计工具名。
- **Three extension points wired (P76)** — (1) `/model` now shows available providers via `ProviderRegistry.list_providers()`; (2) `UserMessageEvent.is_slash_command` set to `True` for slash commands, consumed by `AuditLogger` (audit trail) and `TraceRenderer` (trace display with `[slash]` tag); (3) `LLMRequestEvent.estimated_tokens` filled from `ContextManager.total_tokens`, displayed in trace as `~N tok`. 三个扩展点接入：`/model` 显示可用 Provider 列表；斜杠命令事件标记 + 审计记录 + trace 显示；LLM 请求预估 token 填值 + trace 显示。

### Changed 变更

- **`Conversation.slice_window()` removed (P81)** — extension points #5/#16 resolved by deletion (they were duplicate rows for the same method): zero production callers, superseded by ContextManager/Compressor, and hazardous as-is (uncounted messages pass at zero cost so the budget never applies; tail slicing can orphan tool_use/tool_result pairs, which strict APIs reject with 400). Fixing it would duplicate `_compute_keep_split`. 删除 `Conversation.slice_window()`（拓展点 #5/#16 为同一方法的重复行）：零调用方、被 ContextManager/Compressor 取代、自身语义有坑（未计数消息零成本通过、可切断工具对），修好等于重抄保留窗口逻辑。
- **LLM streaming call extraction (#158)** — moved `assemble_response()` from `llm/openai_provider.py` to `llm/base.py` (it operates on base types, not provider-specific); added standalone `complete(llm, messages, ...)` function that wraps stream + assemble in one call; replaced 5 duplicated stream+assemble loops (extraction, recall, consolidation, compressor, planner) with `complete()`. `agent_loop._stream_once()` unchanged (has its own mid-stream callbacks). LLM 流式调用抽取：`assemble_response()` 移至 base.py，新增 `complete()` 一次调用封装流式收集+组装，5 处重复调用点已简化。
- **Forgotten code wiring (P75, #160)** — six pieces of written-but-never-wired code connected: (1) `LLMResponse.model` set after `assemble_response`; (2) `CostTracker` cache-aware pricing via `cache_read`/`cache_creation` fields (avoids overcharging cached input); (3) `enable_plan_mode` config read at startup (default changed to `False`); (4) `on_thinking_delta` terminal callback (DeepSeek R1 reasoning now renders in dim italic); (5) `PermissionRequest.matched_rule` flows to `AuditLogger` via `PermissionCheckEvent`; (6) `ContextManager.count_message()` per-tool-call +3 overhead (dead `count_message_tokens`/`count_messages_tokens` deleted). 遗忘代码接入（6 处）：LLMResponse.model 赋值、CostTracker 缓存 token 差异化计费、enable_plan_mode 配置读取、on_thinking_delta 终端渲染、matched_rule 审计日志、精确 token 计数 + 死函数清理。

### Fixed 修复

- **Compression pipeline defect chain (P69–P72)** — four defects exposed by real-terminal verification: Stage 1 no longer truncates tool results inside the keep window (the model perceived broken tools and spiraled into re-reads, 36 iterations → 4); the recovery-attachment budget scales with the context window (a 54K attachment pinned small windows); SlidingWindow anchors the freshly created summary so tail-based truncation never deletes it; the extractive digest strips baked-on recovery attachments before re-digesting (17K file dumps drowned planted conventions). 压缩链路缺陷链修复：Stage 1 尊重保留窗口（防重读螺旋）、恢复附件预算随窗口缩放、SlidingWindow 摘要锚点（不再删刚生成的摘要）、digest 剥离恢复附件（防源码转储淹没约定）。
- **Spill cache permission popups** — reading back the agent's own spill files (`~/.mini-agent/cache/results/`) no longer prompts for confirmation (read-only auto-allow; writes still ask). The spill placeholder invites the LLM to read these files, so prompting on every read-back defeated the mechanism. 溢写缓存只读自动放行：读回自家溢写文件不再弹权限框（写入仍询问）。
- **Prompt label pollution after confirmation** — the permission dialog reused the main input's PromptSession; prompt_toolkit makes the passed message the session's new default, so after the first confirmation the main prompt permanently showed "allow? [y/a/n] >". Now uses a temporary session. 权限框污染主提示符修复：confirm() 改用临时 PromptSession。
- **Circuit breaker warning spam** — the compression circuit breaker warned on every check (twice per iteration) once open; now warns once on open and resets after an effective compression. 压缩熔断器警告刷屏修复：开启只警告一次。
- **bash GBK output mojibake** — subprocess output now decoded strict UTF-8 → active codepage/GBK → UTF-8 replace (three-tier), so Chinese CMD error messages render correctly. bash 子进程输出三级解码，中文 CMD 错误信息不再乱码。
- **LLM autonomous git commands** — all git state-changing commands (commit/push/reset/stash/rebase/checkout/restore/clean) now require user confirmation (human-in-the-loop), plus CRITICAL system prompt rules. 全部 git 状态修改命令需用户确认 + system prompt 红线。
- **Git Bash (mintty) instant exit** — piped stdin detected via isatty(), falls back to plain input mode (no completion menu; use `winpty mini` for the full experience). mintty 管道 stdin 自动降级朴素输入，`winpty mini` 可获完整体验。
- **Surrogates crash on GBK usernames** — lone surrogate chars (\udcXX) from GBK paths no longer crash the API request; messages are sanitized before JSON encoding. GBK 用户名路径产生的孤立代理字符不再崩 API 请求。

### Added 新增

- **Event listener plugins (`EventBus.on_any`, #166)** — drop a `.py` file into a `listener_dirs` directory (default `./.mini-agent/listeners` + `~/.mini-agent/listeners`) to observe all bus events with zero code changes: define `register(bus)` (full control) or `on_event(event)` (sync or async, auto-registered globally). Plugin import/registration/handler errors are isolated and logged, never breaking the agent; `EventBus.emit` now logs handler exceptions (previously swallowed) and `off_any()` added. 事件监听插件：`listener_dirs` 目录下的 *.py 零代码接入全局事件监听（`register(bus)` 或 `on_event(event)` 契约），异常全隔离；emit 补 handler 异常日志，新增 off_any()。
- **Confirm hook rules (`HookAction.CONFIRM`, #167)** — `[[hooks]]` config rules accept `action = "confirm"`: matching tool calls pop the y/a/n confirmation dialog instead of being rejected outright (y = allow once, a = never ask again this session for the same rule, n = deny with `Denied by user: <reason>` returned to the LLM). Resolution lives in the agent loop via an injected `terminal.confirm` callback (hooks hold no UI reference); no callback = safe deny; dialogs are lock-serialized against parallel tool execution, and streaming tool execution defers would-confirm calls until after the stream. Real-LLM verified (approve / deny / always paths). 确认型 hook 规则：`[[hooks]]` 新增 `action = "confirm"`，命中弹 y/a/n 确认框（a = 本会话同规则不再问，n 拒绝并回传原因给 LLM）；裁决由 agent loop 经注入回调执行，无 UI 安全拒绝，弹窗加锁防并行交错，流式执行预判延迟；真实 LLM 三路径验证。
- **Summary prompt-too-long shrink retry (P73)** — when the summarize request itself is rejected as too large (HTTP 400/413 or length keywords in the error), drop the oldest 20% of summarizable messages AND shrink the char cap 20%, then retry (max 3 shrink rounds, budget independent of transient retries); a prior compression summary at the head is never dropped; once shrinks are exhausted, fall back to the extractive digest immediately instead of re-sending the identical oversized request. Real-API verified end to end (genuine 400 → 2 shrinks → 9-section summary). 摘要 prompt 超长收缩重试：400/413 识别后丢最旧 20% 消息 + cap 缩 20% 重试（≤3 轮，与偶发重试预算独立），头部旧摘要绝不丢，穷尽立即回退不重复相同请求；真实 API 全管道验证。
- **LLM structured summary + retry (P67/P72)** — the summarize prompt now demands an `<analysis>` scratchpad plus a 9-section `<summary>` block (only the summary is injected); transient failures retry twice before the extractive fallback; prior summaries are carried forward whole with recovery attachments stripped. LLM 结构化摘要：analysis 草稿 + 9 节 summary（只注入 summary 块）；偶发失败先重试 2 次再回退；旧摘要整条前传并剥离恢复附件。
- **Token-driven keep window (P68)** — the compression keep-boundary is computed by accumulated tokens (floor 10K / min 5 messages / cap 40K, all scaling with the compression target) instead of a fixed 6 messages. token 驱动的保留窗口：按累计 token 计算保留边界（随压缩目标缩放），替代固定 6 条。
- **Aggregate tool result budget** — when a turn's cumulative tool-result chars exceed `aggregate_spill_chars` (default 200K, 0 = off), the largest results are force-spilled to disk largest-first until back under budget. Three supporting mechanisms: spill-file read-backs are exempt (anti-loop), preview enlarged 500→2000 chars, results no longer than the preview are never spilled. Spill placeholder now includes the spill file path for offset/limit re-reads. 聚合工具结果预算：单轮累计超 200K 字符时按大小降序强制溢写，含读回豁免/预览 2000/小结果豁免三配套；占位文案带溢写文件路径供精读。
- **Memory export/import** — `/memory export [dir]` writes each memory as a standalone .md file (YAML frontmatter: id/source/scope/created_at/tags) plus a MEMORY.md index; `/memory import <dir>` imports with id dedup and restores project/user scope from frontmatter. Tolerant parsing accepts plain .md and mewcode-style files. 记忆导出/导入：导出为独立 .md（YAML 前置元数据 + MEMORY.md 索引），导入按 id 去重、按 scope 还原项目/用户作用域，容错解析外来格式。
- **Compression tool-pair alignment** — the summarize keep-boundary backs up to the tool-pair head so tool_use/tool_result pairs are never split (strict APIs reject orphans with 400); SlidingWindow drops leading orphan tool results. 压缩工具对对齐：keep 边界回退到工具对头部不切断配对，SlidingWindow 丢弃开头孤儿 tool result。
- **Compression circuit breaker** — after N consecutive ineffective compressions (tokens did not decrease), `check_and_compress()` skips further attempts. Prevents wasted compression cycles when `_inject_read_files` cancels out compression gains (e.g., 150+ read files). `ensure_fits()` hard fallback unaffected. Config: `compress_max_failures = 3` (0 = off). 压缩熔断器：连续 N 次压缩无效后跳过，防止已读文件列表抵消压缩收益时的死循环；ensure_fits 兜底不受影响。
- **Compression-reread inflation root fix** — two-layer defense: tool results >50K chars spill to disk (conversation keeps a 2000-char preview incl. the spill file path); after compression the summary carries a "files already read" list so the LLM does not re-read them. Configurable via `[memory] spill_threshold_chars` (0 = off). 压缩-重读膨胀根治：大工具结果溢写磁盘 + 压缩后注入已读文件清单。
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
- **Plan mode read-only** — `/plan [on|off]` toggles physical read-only enforcement: write tool schemas hidden from LLM + execution blocked as double safety. System prompt injection on toggle. Plan 模式只读：`/plan` 切换物理只读——写工具 schema 隐藏 + 执行拦截双保险。
- **Hook lifecycle expansion** — HookStage grows to 11 stages, all actually fired: new STARTUP/SHUTDOWN/TURN_START/TURN_END + wired up previously-dead POST_LLM/SESSION_START/USER_INPUT. USER_INPUT supports BLOCK to intercept a turn. Hook 事件类型扩充：11 个阶段全部实际触发——新增 4 个生命周期阶段 + 接线 3 个已定义未触发的；USER_INPUT 支持拦截输入。
- **Tool search / lazy loading** — MCP servers can use `loading = "dispatch"` to keep tools out of the LLM context; the LLM discovers them via `tool_search` and invokes them via `mcp_call`. Two new builtin tools (10 total). 工具搜索/延迟加载：MCP dispatch 模式不注册 schema，LLM 通过 tool_search 按需搜索 + mcp_call 按需调用。
- **Selective memory recall** — when stored memories exceed `recall_threshold` (10), a lightweight LLM call picks the `recall_top_k` (5) most relevant entries to inject instead of head-truncating. Fail-safe fallback to the old behavior on any error. 选择性记忆召回：记忆超过阈值时 LLM 挑选最相关的注入，失败静默回退。
- **Memory consolidation** — when memories exceed `consolidation_threshold` (20), an LLM merges semantically related entries into one (keeps newest timestamp, unions tags). Also available manually via `/memory consolidate`. Fail-safe no-op on any error. 记忆合并：超阈值时 LLM 语义合并相关记忆（保留最新时间戳、tags 并集），也可 `/memory consolidate` 手动触发。
- **Worktree lifecycle** — new worktrees auto-symlink `node_modules`/`.venv`/`vendor` (skip reinstalls); stale clean worktrees older than `worktree_max_age_days` (7) are removed at startup (dirty ones kept); `/spawn wait` shows the worktree path with a `git merge` hint. Worktree 生命周期：依赖目录符号链接、过期干净 worktree 启动清理（脏的保留）、结果显示合并提示。
- **Skill install/uninstall** — `/skill install <path_or_url>` installs a skill from a local directory or git URL into `~/.mini-agent/skills/` with SKILL.md validation (auto-cleanup on failure); `/skill uninstall <name>` removes by name. Skill 安装/卸载：从本地路径或 git URL 安装 skill，验证格式后自动清理失败项。
- **Skill hot reload** — `/skill reload` rescans disk, updates active skill prompts in-place (strips old, injects new), and reports lost skills whose files were deleted. `load_all()` now clears before rescan so stale entries don't accumulate. Skill 热重载：`/skill reload` 重扫描磁盘，自动更新活跃 skill 的 prompt，报告磁盘已删除的 skill。
- **Remote/Browser mode** — `--remote` starts a WebSocket + HTTP server; open `http://localhost:8766` in a browser to use the agent remotely. 12-type NDJSON protocol, embedded dark-theme UI with Markdown rendering (h1-h4, lists, tables, links, bare URLs, images), thinking indicator, permission dialogs (Allow/Always/Deny with click feedback), history replay on refresh, HTTP-based cancel and permission (bypasses WS blocking), optional token auth (`--remote-token`), multi-client broadcast. Optional dependency: `websockets` (`uv sync --extra remote`). 远程/浏览器模式：WebSocket + HTTP 双服务器，12 种事件协议，嵌入式深色主题 UI（Markdown/表格/列表/链接/图片），Thinking 指示器，权限对话框，刷新恢复历史，HTTP 取消/权限端点，可选 token 认证（`--remote-token`），多客户端广播。

### Fixed 修复（P36 实战补修）

- **Task anchor in truncation** — SlidingWindow now always keeps the latest user message; a long turn (one question + dozens of tool results) could push the question out of the window, leaving the LLM asking "what did you want?". 截断保任务锚点：最近一条用户消息永不丢弃。
- **Respond in user's language** — system prompt now instructs the LLM to always answer in the language the user writes in. 系统提示要求用用户的语言回答。

### Experiments 实验

- **Deadlock induction** — 5 scenarios × 2 arms testing triple fuse under real LLM. Key finding: iteration limit is the only reliable hard fuse; same-tool-6x never triggered (LLM varies arguments each time). 死循环诱导实验：迭代上限是唯一可靠硬熔断，same-tool-6x 从未触发。
- **Circuit breaker verification** — 5-phase real-LLM test: normal compression / 150-file read_files triggers natural breaker / ensure_fits fallback / disabled control group / new-session recovery. 压缩熔断器验证：5 阶段真实 LLM 实验。

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
