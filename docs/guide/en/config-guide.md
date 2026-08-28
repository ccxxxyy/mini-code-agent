# Complete Guide to Configuration Files and Context Files

> 中文版 (Chinese version): [../config-guide.md](../config-guide.md)

This document explains **all** configuration files and context files that Mini-Code-Agent reads: what each file does, where it lives, how to modify it, and the default behavior when you don't.

---

## 1. Overview: Three Kinds of Files

The files read by the program fall into three categories, **fundamentally different in nature**:

| Category | Consumed by | Content | Examples |
|---|---|---|---|
| **Configuration files** | The program | Behavior parameters (model/timeout/theme) | `config.toml`, `.env` |
| **Context files** | The LLM | Natural-language instructions (project conventions/personal preferences) | `CLAUDE.md`, `instructions.md` |
| **Data files** | Read/written automatically by the program | Memory/sessions/audit (users normally don't edit them by hand) | `memory.json`, `sessions/` |

How to tell them apart: **changing a configuration file affects how the program runs; changing a context file affects how the LLM answers**.

---

## 2. Full File Inventory

### Configuration files (program behavior)

| File | Level | Priority | Description |
|---|---|---|---|
| `~/.mini-agent/config.toml` | User-level | Low | Default settings shared by all projects |
| `<project>/.mini-agent/config.toml` | Project-level | Medium | Specific to this project, overrides user-level |
| `<project>/.env` | Project-level | Higher | Sensitive values like API keys (gitignored, never committed) |
| Environment variables (`MINI_AGENT_*` / `OPENAI_*`) | Session-level | High | Temporary overrides |
| CLI arguments (`--model` etc.) | Single launch | Highest | One-off overrides |

There is also a **permission rules file** `permissions.toml` (user-level `~/.mini-agent/` + project-level `<project>/.mini-agent/`, both levels stack), which is independent of config.toml (it cannot be merged due to the `[tools]` section name conflict) — see the "Permission Rules File" section below for details.

The project root provides three template files to copy from: `config.toml.example`, `permissions.toml.example`, `.env.example`.

**Full precedence chain** (right overrides left):

```
Built-in defaults → user config.toml → project config.toml → .env → environment variables → CLI arguments
```

### Context files (LLM instructions)

| File | Level | Description |
|---|---|---|
| `<project>/AGENT.md` | Project-level | Project conventions, priority #1 (widely used community standard) |
| `<project>/CLAUDE.md` | Project-level | Project conventions, priority #2 (Claude Code ecosystem compatibility) |
| `<project>/.mini-agent/instructions.md` | Project-level | Project conventions, priority #3 (specific to this tool) |
| `~/.mini-agent/instructions.md` | User-level | Global personal instructions (e.g. "answer in Chinese"), which **coexist** with project instructions (both are injected) |

**The three project-level files are "pick one of three"**: search stops at the first non-empty file found by priority; no merging.
**User-level and project-level "coexist"**: both are injected into the system prompt.

### Data files (managed automatically)

| File | Level | Description |
|---|---|---|
| `~/.mini-agent/.theme` | User-level | Theme preference written by the `/theme` command |
| `~/.mini-agent/memory/user_memory.json` | User-level | Cross-project memory (auto extraction on SESSION_END + `/memory add`) |
| `<project>/.mini-agent/memory.json` | Project-level | Project memory |
| `~/.mini-agent/sessions/` | User-level | Session persistence (auto-save/crash recovery); properly closed sessions older than `session_cleanup_days` (default 30) days and crashed sessions older than `crashed_session_cleanup_days` (default 40) days are cleaned up at startup |
| `~/.mini-agent/audit.jsonl` | User-level | Audit log (after `/audit on` is enabled) |
| `~/.mini-agent/recordings/` | User-level | Tool-chain recordings (saved by `/record`, read by `/replay`) |
| `~/.mini-agent/cost_ledger.json` | User-level | Cumulative cost ledger (written automatically each turn; `/cost reset` zeroes it after confirmation and resets the start date — deleting the file is equivalent) |
| `<project>/.mini-agent/tasks.json` | Project-level | Persistent task list (managed via `/todo`, retained across sessions; hand-editing the JSON also works) |
| `<project>/.mini-agent/undo_snapshots/` | Project-level | Undo file snapshots (**temporary** — cleared automatically when the session ends) |
| `~/.mini-agent/input_history` | User-level | Cross-session input history (↑ key browses history, written automatically) |

### Component Lifecycle at a Glance

Different data lives for different durations. Understanding lifecycles avoids the confusion of "why did it disappear / why is it still here":

| Data | Lifecycle | After a crash |
|---|---|---|
| Conversation history | Within the session (force-persisted every turn) | Recoverable (prompt at startup) |
| Undo file snapshots | Within the session, and only the last N turns are kept (`undo_keep_turns`, default 5) | Lost (undo is a within-session operation by design) |
| Steps of an **in-progress** recording (not stopped) | In memory — within the session | **Lost**, must re-record |
| **Saved** recording files | Permanent on disk | Unaffected |
| Template variable values (`/replay x k=v`) | **Single replay** — discarded after use, never persisted nor added to the session | — |
| Memory / theme / configuration | Permanent on disk | Unaffected |

Key point: **recording files are stateless static templates** — `{{variable}}` placeholders always remain verbatim in the file; substitution during replay happens only in memory (at the instant the tool call is constructed). So switching sessions, crash recovery, or replaying the same recording from multiple terminal windows simultaneously all behave identically and never interfere with each other.

### Cross-Component Interaction Points

Three interactions worth knowing about (all benign by design, but slightly subtle in behavior):

1. **Replay × undo snapshots**: files modified by `/replay` do enter the current session's undo snapshots — `/undo` can revert a replay's file changes. But a replay does not consume a conversation turn; if you have another conversation turn after the replay and then `/undo`, it reverts that conversation turn, and the replay's changes are not included.
2. **Replay × LLM awareness**: replay results do not enter the conversation history — the LLM does not know what files `/replay` changed. Asking it to work on related files afterwards may proceed from stale knowledge; remind it to re-read the files when necessary (same applies after `/undo`).
3. **Recording × replay anti-nesting**: if `/replay` is executed while a recording is in progress, the replayed calls are **not** recorded (suspended protection) — the recording contains only operations the LLM actually executed.

---

## 3. Quick Start: Using mini-agent in Any Directory

By default, the API key only takes effect in a project directory that has a `.env` file. To launch `mini` in **any directory**, do **any one** of the following:

### Method 1: Set System Environment Variables (recommended — set once, works forever)

**Windows (PowerShell)**:

```powershell
# Set the API key (required)
[System.Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-your-key", "User")

# If using a third-party API (DeepSeek, Zhipu, SiliconFlow, etc.), also set the base URL
[System.Environment]::SetEnvironmentVariable("OPENAI_BASE_URL", "https://your-api-host/v1", "User")

# Optional: set the default model
[System.Environment]::SetEnvironmentVariable("MINI_AGENT_MODEL", "deepseek-chat", "User")
```

**Restart the terminal** after setting for changes to take effect. From then on, running `mini` in any directory will start normally.

**macOS / Linux**:

```bash
# Add to ~/.bashrc or ~/.zshrc
echo 'export OPENAI_API_KEY="sk-your-key"' >> ~/.bashrc
echo 'export OPENAI_BASE_URL="https://your-api-host/v1"' >> ~/.bashrc
echo 'export MINI_AGENT_MODEL="deepseek-chat"' >> ~/.bashrc
source ~/.bashrc
```

### Method 2: User-Level Configuration File (shared across projects, never committed to git)

Create `~/.mini-agent/config.toml`:

```bash
# Windows
mkdir "%USERPROFILE%\.mini-agent"
# macOS / Linux
mkdir -p ~/.mini-agent
```

Write the content:

```toml
[llm]
api_key = "sk-your-key"
base_url = "https://your-api-host/v1"
model = "deepseek-chat"
```

### Method 3: Project-Level .env File (current project only)

Create a `.env` file in the target project's root directory:

```bash
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://your-api-host/v1
MINI_AGENT_MODEL=deepseek-chat
```

> **Precedence reminder**: CLI arguments > environment variables > .env > project config.toml > user config.toml > defaults. Higher priority overrides lower priority.

### Verifying the Configuration

Run in the target directory:

```bash
mini --version    # Confirm installation succeeded
mini              # Launch the Agent
```

If you still get the "API key not configured" error, check:
1. Whether the terminal has been restarted (environment variables require a terminal restart to take effect)
2. Whether the environment variable name is spelled correctly (`OPENAI_API_KEY`, not `OPENAI_KEY`)
3. Whether a higher-priority configuration is overriding it (e.g. an empty value set in `.env`)

---

## 4. config.toml Usage Guide

### Creating It

The project root has a template `config.toml.example`; copy it and uncomment as needed:

```bash
# User-level (recommended for personal preferences)
copy config.toml.example "%USERPROFILE%\.mini-agent\config.toml"    # Windows
cp config.toml.example ~/.mini-agent/config.toml                     # macOS/Linux

# Project-level (recommended for team conventions, can be committed to git)
mkdir .mini-agent && copy config.toml.example .mini-agent\config.toml
```

### All Configurable Sections

```toml
[llm]
provider = "openai"          # "openai" (Chat Completions) | "openai-responses" (Responses API, o1/o3/o4-mini) | "anthropic"
model = "deepseek-chat"      # Model name (default "gpt-4o")
api_key = "sk-..."           # API key (recommended to put in .env instead of here)
base_url = "https://api.deepseek.com/v1"  # API endpoint (default None, uses the Provider's built-in endpoint)
temperature = 0.0
max_tokens = 4096            # Per-response cap; on truncation, automatically doubles and retries up to 3 times (P44) — this value is the retry starting point
timeout = 120.0
thinking = false             # Request-side extended thinking: Anthropic thinking param / Responses reasoning param (tech-notes §110); can also enable via MINI_AGENT_THINKING or per-profile MODEL_<NAME>_THINKING; tune Responses effort via extra = {reasoning_effort = "high"} (default medium); per-scenario examples in "Thinking Stream Configuration in Detail" below
# extra = {}                 # Extra parameters passed through to the API (e.g. top_p, stop, or enable_thinking = true for qwen hybrid reasoning models); core fields (model/messages) cannot be overridden

[tools]
bash_timeout = 120.0         # bash command timeout (seconds)
max_file_size = 10000000     # File read cap (bytes)
enabled_tools = ["read_file", "write_file", "edit_file", "delete_file", "bash", "glob", "grep", "spawn_agents", "send_message", "wait_message", "tool_search", "mcp_call", "ask_user", "exit_plan_mode", "task_create", "task_get", "task_list", "task_update", "load_skill", "install_skill"]
allowed_paths = []           # Extra allowed paths outside the project (default empty)
denied_paths = ["~/.ssh", "~/.aws", "~/.gnupg"]   # Paths forbidden to access
enforce_read_before_edit = true  # Read-before-edit gate : edit/overwrite-write requires a prior read with no external change since; false disables

[memory]
context_window = 128000      # Context window token count (used to trigger compression; overflow fallback separately uses the real window value the Provider auto-detects from the API, P42)
compression_threshold = 0.75 # Soft threshold (compress at 75%, governed by the circuit breaker)
hard_compression_threshold = 0.90 # Hard threshold (force compression at 90%, bypassing the circuit breaker)
auto_extract = true          # Automatically extract memory at session end
spill_threshold_chars = 50000 # Tool results exceeding this many characters are spilled to disk keeping only a preview (0 = disabled) — prevents large files from blowing up the context
aggregate_spill_chars = 200000 # Per-turn cumulative tool-result character budget: when exceeded, force spill in descending size order (0 = disabled) — prevents "each one under the limit, but their total blows up"
session_cleanup_days = 30    # Properly closed sessions older than this are cleaned up at startup (0 = disabled)
crashed_session_cleanup_days = 40  # Crashed sessions older than this are also cleaned up (0 = keep forever) — longer than 30 days because crash sessions have recovery value
compress_max_failures = 3    # Compression circuit breaker: skip after N consecutive ineffective compressions (0 = disabled) — prevents infinite loops when the already-read-files list gets too long
llm_summarize = true         # LLM semantic summary compression (enabled by default); false falls back to extractive truncation (no LLM call)
undo_keep_turns = 5          # /undo file snapshots: keep the last N turns — raise for deeper file rollback
recall_threshold = 10        # Enable LLM selective recall when memory count exceeds this (inject all when ≤ threshold)
recall_top_k = 5             # Maximum number of entries the LLM picks during selective recall
recall_timeout = 8.0         # Recall prefetch timeout in seconds — selection runs in parallel with the main LLM call (no first-token latency added); on timeout, head entries are injected instead
consolidation_threshold = 20 # Automatically run LLM semantic consolidation when memory count exceeds this (0 = disabled)
auto_consolidate = true      # Background consolidation at startup: memories are merged invisibly when both gates pass (lock guards concurrency, failures roll back)
consolidate_min_hours = 24.0 # Background consolidation gate 1: hours since the last run
consolidate_min_sessions = 5 # Background consolidation gate 2: new sessions active since the last run
# persistent_memory_dir = "~/.mini-agent/memory"     # User-level memory directory
# project_memory_file = ".mini-agent/memory.json"    # Project-level memory file

[security]
permission_mode = "ask"      # "allow" (allow everything) | "ask" (prompt) | "deny" (deny everything)
approval_mode = "default"    # Session-level permission mode at startup: "default" (dangerous commands /
                             # paths outside the project prompt) | "accept-edits" (file writes auto-approved;
                             # dangerous commands / out-of-project reads still prompt) | "plan" (read-only
                             # plan mode) | "bypass" (everything auto-approved except DENY rules and
                             # sensitive paths). Invalid values warn and fall back to default; switch at
                             # runtime with /mode. enable_plan_mode = true is equivalent to
                             # approval_mode = "plan" and takes precedence.
allowed_commands = ["git *", "uv *"]   # Confirmation-free command whitelist (default empty); a match is allowed through (including dangerous commands)
denied_commands = ["rm -rf /", "sudo", "curl|sh", "wget|sh"]   # Unconditional deny list (default values); a match is rejected
# Note: denied_commands is glob exact-match rejection. There are also 26 hard-coded regexes (DANGEROUS_COMMAND_PATTERNS)
# used for confirmation dialogs (rm -rf/sudo/chmod 777/mkfs/dd/git push/commit/reset/stash/rebase/checkout/
# restore/clean/Windows del/rmdir/format/curl|sh/wget|sh/python -c/node -e/perl -e/ruby -e/
# sh -c/bash -c/powershell -Command/pwsh -c) — these are not configurable, but can be
# allowed via allowed_commands or made confirmation-free via sandbox_auto_allow.
worktree_base_dir = ".mini-agent/worktrees"  # Git worktree isolation directory
worktree_max_age_days = 7    # Clean worktrees older than this many days are cleaned up automatically at startup (0 = disabled)
sandbox = true               # OS-level sandbox (Linux bwrap/unshare / macOS seatbelt / Windows dual-mode), on by default
sandbox_auto_allow = false   # Dangerous commands skip confirmation under the sandbox (deny rules still block)
sandbox_network = false      # Allow network access inside the sandbox

[context]                    # Context awareness (P25)
instruction_files = ["AGENT.md", "CLAUDE.md", ".mini-agent/instructions.md"]
                             # Project instruction file names and priority (list order = priority, first hit is used)
user_instructions_file = "~/.mini-agent/instructions.md"   # User-level global instructions path
max_chars = 8000             # Per-file truncation length (characters, applied after expansion)
max_include_depth = 5        # @-include recursive expansion max depth (0 to disable)

[cost]                       # Cost dashboard (P29)
budget = 5.0                 # Session budget cap (yuan), 0 = unlimited (default 0)
total_budget = 50.0          # Cumulative ledger budget cap (yuan), 0 = unlimited (default 0)
currency = "¥"
[cost.pricing.deepseek-chat] # Per-model pricing (yuan per million tokens)
input = 2.0
output = 8.0
# cache_read = 0.5            # Optional: cache read price (billed at input price if unset)
# cache_creation = 3.0        # Optional: cache creation price (billed at input price if unset)

# Top-level configuration (belongs to no section; note it must be written before all [sections] and [[hooks]] to count as top-level)
max_agent_iterations = 80    # Maximum ReAct loop iterations (shared by the main loop and SubAgents without an explicit type;
                             # when /spawn --type explicitly selects a type, the type profile's budget is adopted, see P80)
max_consecutive_denials = 1  # Stop the turn and ask the user after N consecutive confirm-dialog denials
                             # (dangerous command / path outside project / hook confirm; default 1 = one denial stops
                             # the goal; raise it to allow corrected retries after a denial. Prevents bypass hunting)
theme = "default"            # "default" | "dark" | "light"
collapse_tool_calls = false  # Collapse read-only tools (read_file/glob/grep) called >=2 times in the
                             # same round into a one-line "✓ Done (N tool uses · Xs)" summary;
                             # default false (full per-call lines), set true to opt in
streaming_tool_execution = true  # During streaming, start executing a tool call as soon as it is fully assembled (false waits for the stream to end)
enable_plan_mode = false     # Enter read-only plan mode at startup (/plan on|off switches at runtime);
                             # equivalent to [security].approval_mode = "plan" and takes precedence
# self_verify = false        # Experimental: LLM automatically verifies tool results
# planner_profile = ""       # LLM Profile name used by the /team Planner (empty = use the main model)
# worker_profile = ""        # LLM Profile name used by SubAgent workers (empty = use the main model)
skill_dirs = ["./skills", "~/.mini-agent/skills"]
                             # Skill pack directories: each subdirectory contains a SKILL.md (YAML front matter + prompt body)
listener_dirs = ["./.mini-agent/listeners", "~/.mini-agent/listeners"]
                             # Event listener plugin directories: every *.py file in the directory is a plugin,
                             # defining register(bus) (subscribe to specific events) or on_event(event) (auto-subscribe to all events;
                             # sync/async both work). Plugin exceptions are isolated and logged, never affecting the main flow. Used for stats/debugging,
                             # e.g. dumping all events to a JSONL file. Files starting with an underscore are skipped.
plugin_dirs = ["./.mini-agent/plugins", "~/.mini-agent/plugins"]
                             # Plugin directories: every *.py file in the directory is a plugin (names starting with `_` are skipped),
                             # which may define register(ctx) (full-control hook — if defined, it takes priority and only it runs) or
                             # the dedicated hooks register_tools(registry) / register_commands(registry) /
                             # register_skills(registry) to register tools/slash commands/skills.
                             # pip package plugins do not use this directory; instead declare an entry point inside the package:
                             #   [project.entry-points."mini_agent.plugins"]
                             #   my_plugin = "my_pkg.plugin"
                             # Load order: entry points first, directories second; on name collision the directory file yields and a warning is emitted.
                             # Exceptions are isolated at three layers (import/hook/runtime); a bad plugin never affects the main flow.
                             # Plugin tools are not constrained by the [tools].enabled_tools whitelist (installing is opting in).
                             # See examples/plugins/word_count_plugin.py for a sample plugin; /plugins lists loaded plugins.
# disabled_plugins = ["some_plugin"]
                             # Disable plugins: matched by entry-point name or file name (without the .py suffix)

# Declarative Hook rules — on match, reject the tool execution (default) or show a confirmation dialog; reason is returned to the LLM
# Multiple [[hooks]] entries can be written; invalid entries are skipped with a warning and never block startup
[[hooks]]
tool = "write_file"          # Tool name fnmatch pattern ("bash", "write_*", default "*" for all)
arg = "file_path"            # Optional: only check this parameter (by default all parameter values are checked)
contains = "docs/spec"       # Optional: trigger only when the parameter value contains this substring (by default applies to all calls of that tool)
reason = "docs/spec.md is read-only by project policy"   # Rejection reason; the LLM receives it and adjusts its strategy

[[hooks]]
tool = "bash"
contains = "curl"
reason = "External downloads are forbidden by project policy"

[[hooks]]
tool = "bash"
regex = 'rm\s+-rf'           # Optional: re.search regex (when given together with contains, both must match; invalid regexes are skipped with a warning)
reason = "Destructive deletion is forbidden by project policy"

[[hooks]]
tool = "bash"
contains = "git push"
action = "confirm"           # Optional: "block" (default) rejects directly; "confirm" shows a y/a/n confirmation dialog
reason = "push affects the remote repository"

# MCP servers
[mcp.servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
transport = "stdio"                  # "stdio" (subprocess) | "http" (remote) | "sse"
loading = "eager"                    # "eager" (default) | "native" (Anthropic native defer) | "dispatch" (on-demand search + call)

# [mcp.servers.remote-api]
# url = "http://localhost:8080/mcp"
# transport = "http"
# headers = { Authorization = "Bearer your-token-here" }   # Optional auth headers
# loading = "dispatch"               # Lazy loading for many tools; use "native" on official Anthropic endpoint (auto-fallback to dispatch elsewhere)
```

### Custom Agent Types

Place `.md` files in `.mini-agent/agents/` (project-level) or `~/.mini-agent/agents/` (user-level) to define custom agent types for `/spawn --type <name>` and the `spawn_agents` tool. **One `.md` file = one type**; create multiple files for multiple types.

**Full example** (`.mini-agent/agents/reviewer.md`):

```markdown
---
name: reviewer
description: Code review specialist
allowed_tools:
  - read_file
  - glob
  - grep
  - bash
max_iterations: 25
---
You are a code review agent. Read code and report issues.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}
Budget: {iteration_budget} rounds.
```

**Frontmatter fields**:

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | — | Type identifier, used in `/spawn --type <name>`. Only lowercase letters, digits, underscores, hyphens (`[a-z0-9_-]+`) |
| `description` | No | `""` | One-line description shown in the `spawn_agents` tool schema for the LLM to choose from |
| `allowed_tools` | No | All tools | Whitelist of tools this agent type can use. **Omit to allow all 20 built-in tools.** One per line, format `  - tool_name` |
| `max_iterations` | No | `30` | Max iteration rounds (think-act loop cap); agent is force-stopped when exceeded |

**Values for `allowed_tools`** (pick from the 20 built-in tools in `[tools] enabled_tools`):

| Tool name | Purpose | Read-only |
|---|---|---|
| `read_file` | Read file contents | Yes |
| `glob` | Search filenames by pattern | Yes |
| `grep` | Search file contents by regex | Yes |
| `bash` | Execute shell commands | Depends |
| `write_file` | Create/overwrite files | No |
| `edit_file` | Exact text replacement in files | No |
| `delete_file` | Delete files | No |
| `spawn_agents` | Spawn sub-agents (unavailable inside sub-agents) | — |
| `send_message` | Send message to another agent | — |
| `wait_message` | Wait for a message from another agent | — |
| `tool_search` | Search MCP tools | Yes |
| `mcp_call` | Call an MCP tool | Depends |
| `ask_user` | Ask the user a question | — |
| `exit_plan_mode` | Request to exit plan mode (requires user approval; rejection stays read-only) | — |
| `task_create` / `task_get` / `task_list` / `task_update` | Task board CRUD | — |
| `load_skill` / `install_skill` | Load/install skills | — |

**Typical combinations**: read-only review agents use `[read_file, glob, grep, bash]`; full-capability workers omit the field entirely (omit = all tools).

**Body (everything after the `---` delimiter)** is the system prompt template sent to the agent. It supports 4 placeholders, auto-replaced at runtime:

| Placeholder | Replaced with | Example |
|---|---|---|
| `{working_dir}` | Agent's working directory (absolute path) | `D:\Projects\my-app` |
| `{platform}` | OS platform | `win32` / `linux` / `darwin` |
| `{shell}` | Current shell type | `cmd` / `bash` / `zsh` |
| `{iteration_budget}` | The `max_iterations` value | `25` |

Do not use `{xxx}` placeholders other than these 4 — the file will be rejected on load. To include literal braces (e.g. in JSON examples), escape them as `{{` `}}`.

**Usage**:

```bash
/spawn --type reviewer review src/main.py      # specify on the command line
```

Or let the LLM choose autonomously (the `spawn_agents` tool's `agent_type` field automatically lists all registered types including custom ones).

**Priority**: project > user > builtin (explore/plan/worker/verify). Same name overrides. Loaded at startup; when custom types are found, the terminal shows `Loaded N custom agent type(s)`.

**Directory config** (usually no need to change — defaults cover common scenarios):

```toml
agent_dirs = ["~/.mini-agent/agents", "./.mini-agent/agents"]
```

### Read-Before-Edit Gate

`[tools] enforce_read_before_edit` (default `true`) controls a file-safety gate: `edit_file` and `write_file` overwriting an **existing** file only proceed when — ① the file was read via `read_file` earlier in this session, and ② it has not been changed externally since that read (mtime comparison). Purpose: prevent the LLM from blindly modifying files based on imagined or stale content. Creating new files with write and `delete_file` are exempt.

Error messages returned when blocked (the LLM normally self-corrects by reading first — no manual intervention needed):

- `File has not been read yet. Read it first before editing (read-before-edit safety).` — the file was never read
- `File has been modified since it was last read. Read it again before editing (content may be stale).` — changed externally after the read (you edited it, a git operation touched it, etc.)

To disable (project-level `.mini-agent/config.toml` or user-level `~/.mini-agent/config.toml`, restart to apply):

```toml
[tools]
enforce_read_before_edit = false
```

Note: the gate only governs the `edit_file`/`write_file` tools — `sed` and similar commands inside bash bypass it (command risk is handled by the permission system); the main agent and each sub-agent keep independent read records. Design rationale: `docs/tech-notes.md` §84.

### Multi-Model Profiles (Environment Variable Configuration)

Preconfigure multiple sets of model parameters and switch at runtime with a single `/model` command. All defined via environment variables:

```bash
# Define two Profiles: fast and strong
MINI_AGENT_MODELS=fast,strong

# fast Profile parameters
MODEL_FAST_MODEL=deepseek-chat
MODEL_FAST_API_KEY=sk-fast-key
MODEL_FAST_BASE_URL=https://api.deepseek.com/v1

# strong Profile parameters (Provider can be switched)
MODEL_STRONG_MODEL=claude-sonnet-4-20250514
MODEL_STRONG_PROVIDER=anthropic
MODEL_STRONG_API_KEY=sk-ant-strong-key
```

At runtime:
```
/model           # List all available Profiles
/model fast      # Switch to fast (DeepSeek)
/model strong    # Switch to strong (Claude)
```

**Mixing strong and fast models** — Planner uses the strong model for planning, Worker uses the fast model for execution:
```bash
MINI_AGENT_PLANNER_PROFILE=strong    # /team's Planner uses the strong Profile
MINI_AGENT_WORKER_PROFILE=fast       # SubAgent workers use the fast Profile
```

### Thinking Stream (Extended Thinking) Configuration in Detail

The thinking stream is the model's reasoning process before the answer, rendered as dim italics ahead of the response text (tech-notes §110). **Whether you can see it, and what to configure, depends on the model type and protocol**:

| Model type | Examples | Default behavior | Required config |
|---|---|---|---|
| Always-thinking | deepseek-reasoner, DeepSeek R1 | Emits thinking automatically, always visible | **None** |
| Anthropic protocol | Claude family, vendor endpoints built for Claude Code | Official Claude: **no thinking** (must be enabled explicitly); third-party endpoints follow their own defaults (measured: deepseek's Anthropic endpoint thinks by default) | `thinking = true` (required for official Claude) |
| OpenAI Responses (o-series) | o1 / o3 / o4-mini | Reasons internally but no summary streams back (invisible) | `thinking = true` |
| Param-gated (hybrid reasoning) | qwen3 family, GLM thinking variants | Follows the server/gateway default | `extra = {enable_thinking = true/false}` |
| Non-reasoning | deepseek-chat, gpt-4o | No thinking capability | **Config has no effect** (the model can't think) |

**Scenario 1: Enable thinking for Anthropic-protocol models** (official Claude / Anthropic-compatible gateways)

```toml
# .mini-agent/config.toml
[llm]
provider = "anthropic"
model = "claude-sonnet-4-5-20250929"
thinking = true              # request body automatically carries the thinking param
```

The budget is adaptive, no tuning needed: opus/sonnet >= 4.6 send `budget_tokens: 0` (the model decides its own thinking amount); others send `max(1024, max_tokens − 1)`. Thinking-block signatures round-trip across turns automatically.

Equivalent environment variable form (`.env`):

```bash
MINI_AGENT_PROVIDER=anthropic
MINI_AGENT_MODEL=claude-sonnet-4-5-20250929
MINI_AGENT_THINKING=true     # accepts 1/true/yes/on (case-insensitive)
```

**Scenario 2: Enable thinking for o1/o3 Responses models + tune reasoning effort**

```toml
[llm]
provider = "openai-responses"
model = "o3"
thinking = true                            # reasoning summaries stream back as the thinking stream
extra = {reasoning_effort = "high"}        # optional: low/medium/high (some newer models also accept minimal), default medium
```

**Scenario 3: Thinking switch for qwen hybrid reasoning models** (OpenAI-compatible mode)

```toml
[llm]
model = "qwen3.6-plus"
extra = {enable_thinking = true}     # force on (some gateways default to on; setting it removes the dependency on gateway defaults)
# extra = {enable_thinking = false}  # force off — saves output tokens, but reasoning quality drops
```

Note this uses `extra`, not `thinking` — `thinking` only applies to the Anthropic/Responses protocols; qwen's switch is a vendor-specific field in the OpenAI-compatible request body, passed through via `extra`. Measured reference: with thinking off, qwen3.6-plus answers "which is bigger, 9.11 or 9.9" WRONG.

**Scenario 4: Mix per Profile** — fast non-thinking model for daily work, switch to a thinking profile for hard problems

```bash
# .env
MINI_AGENT_MODELS=fast,think

MODEL_FAST_MODEL=deepseek-chat               # daily: fast, cheap, no thinking

MODEL_THINK_MODEL=claude-sonnet-4-5-20250929 # hard problems: switch via /model think
MODEL_THINK_PROVIDER=anthropic
MODEL_THINK_API_KEY=sk-ant-xxxx
MODEL_THINK_THINKING=true                    # only this profile thinks
```

When `MODEL_<NAME>_THINKING` is unset, the profile inherits the main config's `thinking` value.

**Scenario 5: Configure nothing (default)**

`thinking = false`, `extra = {}` — the request carries no thinking params whatsoever, everything follows the server default: always-thinking models stay visible, Anthropic/Responses don't think, hybrid models follow the gateway.

**Cost note**: thinking counts as output tokens (Anthropic bills it at the output rate) and delays the first answer token. For budget-sensitive setups, enable it only on a hard-problem profile (Scenario 4), or explicitly turn it off for hybrid models (Scenario 3).

### When Changes Take Effect

After editing config.toml, **restart `mini` for changes to take effect** (read once at startup, no hot reload).

### Cost Budget Details ([cost] section)

Two budgets work independently, both checked **at the end of every conversation turn**:

| Config key | Scope | How to reset |
|---|---|---|
| `budget` | This session (mini startup → /exit or closing the window) | Reset automatically on restart |
| `total_budget` | Cumulative ledger (from first use until now, across sessions and projects) | Reset manually via `/cost reset` |

**Warning thresholds** (same for both budgets, hard-coded, not configurable):

| Usage ratio | Behavior |
|---|---|
| < 80% | Silent, no prompts of any kind |
| ≥ 80% | Yellow warning line: `Session budget warning: ¥4.12 / ¥5.00 (82%)` |
| ≥ 100% | Red warning line: `⚠ Cumulative total budget exceeded: ¥51.30 / ¥50.00` |

Warnings only, no blocking — the LLM keeps working after the overage; whether to stop is your call. If both budgets cross the line at the same time, each emits its own warning.

**How to change budgets**: edit the `[cost]` section of `~/.mini-agent/config.toml` (if the file does not exist, copy it from `config.toml.example` first), change the `budget` / `total_budget` values, and restart `mini`. Setting to 0 or deleting the line = unlimited.

**Note**: budgets are computed on monetary amounts, so **you must configure `[cost.pricing.<model-name>]` prices first** — with no prices, cost is always 0 and budgets will never trigger.

### Hook Rule Details ([[hooks]] section)

**What it does**: without writing a single line of Python, declare via configuration "which tool calls should be rejected, require confirmation, trigger a command, or emit a notification". Four action types:

- `action = "block"` (default) — a match means the call is **not executed**; the LLM receives `Blocked by hook: <reason>` and adjusts its strategy (switches approach or informs the user) instead of blindly retrying
- `action = "confirm"` — a match pops a y/a/n confirmation dialog for you to decide: y allows once, a stops asking for the same rule within this session, n rejects (the LLM receives `Denied by user: <reason>` and the **Agent stops the current goal** to ask you how to proceed — one denial stops by default; tune with `max_consecutive_denials`)
- `action = "command"` — executes a shell command (specified in the `command` field); when `event = "pre_tool"`, a non-zero exit code **blocks the tool call** (the LLM receives `Blocked by hook: <command stdout or reason>`); when `event = "post_tool"`, it is fire-and-forget (non-zero exit does not block; any stdout is displayed as a terminal notification)
- `action = "notify"` — prints a one-line notification in the terminal (specified in the `message` field); does not block or require confirmation

**Where to write it**: user-level `~/.mini-agent/config.toml` (effective across projects) or project-level `.mini-agent/config.toml` (this project only).
**Layer semantics (careful)**: when the project level defines `[[hooks]]`, it **wholesale replaces** the user-level rule list (no merging) — to have both take effect, copy the user-level rules into the project level.

**All fields**:

| Field | Required | Default | Description |
|---|---|---|---|
| `tool` | No | `"*"` | Tool name fnmatch pattern: `"bash"` exact, `"write_*"` prefix family, `"*"` all tools |
| `arg` | No | Empty | Only check this parameter's value (e.g. `"file_path"`); by default **all** parameter values are checked |
| `contains` | No | Empty | Trigger only when the parameter value contains this substring |
| `regex` | No | Empty | Trigger only when the parameter value matches this regex via `re.search`; invalid regexes are **skipped with a warning**, never blocking startup |
| `condition` | No | Empty | Condition expression — when set, **takes priority over** the four fixed fields `tool`/`arg`/`contains`/`regex`; available fields: `tool` (tool name), `args.<key>` (parameter value); operators `==`, `!=`, `=~` (regex via `re.search`), `~=` (glob via `fnmatch`); combine with `and`/`or` (**no mixing** in one expression) |
| `reason` | Recommended | Auto-generated | Rejection/confirmation reason — returned verbatim to the LLM for block, also shown in the confirm dialog. Spell out "why + what to do instead" for best results. Not used by notify (use `message` instead) |
| `action` | No | `"block"` | `"block"` rejects directly; `"confirm"` shows a y/a/n confirmation dialog (a = stop asking for the same rule within this session); `"command"` executes a command (PRE_TOOL: non-zero exit code blocks the tool; POST_TOOL: fire-and-forget); `"notify"` prints a terminal notification line; other values are skipped with a warning |
| `event` | No | `"pre_tool"` | `pre_tool` (default) or `post_tool`; other values are skipped with a warning |
| `command` | No | Empty | Shell command template for `action = "command"`; supports template variables (see below) |
| `command_timeout` | No | `30` | Command timeout in seconds (only effective when `action = "command"`) |
| `message` | No | Empty | Notification message template for `action = "notify"`; supports template variables (see below) |
| `reject` | No | `true` | Currently only `true` is supported; `false` is skipped with a warning |

**Matching semantics**:
- Neither `contains` nor `regex` written = **all calls** of that tool trigger (block equals disabling the tool, but with an explanation)
- Both `contains` and `regex` written = triggers only when **both match** (AND)
- Multiple `[[hooks]]` rules = any single match triggers (OR); block and confirm rules can be mixed
- Matching compares parameter values after `str()`, so numeric/boolean parameters also match

**TOML syntax caveats**:
1. `[[hooks]]` must be written **after** all top-level keys (`max_agent_iterations`, `theme`, etc.) — a top-level key appearing after `[[hooks]]` gets absorbed into that rule entry and corrupts parsing
2. Use **single quotes** for the `regex` value (TOML literal string): `regex = 'rm\s+-rf'` — inside double quotes `\s` is an illegal escape and raises an error

**Template variables**: the `command` and `message` fields support the following variables, expanded automatically at runtime:

| Variable | Description |
|---|---|
| `$TOOL_NAME` | Current tool name |
| `$TOOL_ARGS.<key>` | Tool parameter value (e.g. `$TOOL_ARGS.file_path`, `$TOOL_ARGS.command`) |
| `$TOOL_ARGS` | All parameters as JSON (without a dot, returns the full JSON object) |
| `$EVENT` | Event stage (`pre_tool` or `post_tool`) |
| `$RESULT` | Tool output text (only has a value when `event = "post_tool"`) |
| `$RESULT_ERROR` | Whether the tool errored: `"true"` or `"false"` (only when `event = "post_tool"`) |

**Condition expressions**: when the `condition` field is non-empty, it **takes priority over** the four fixed fields `tool`/`arg`/`contains`/`regex` for determining whether the rule triggers. Syntax examples:

```toml
# Equivalent to tool="bash" + contains="git push" but more flexible
condition = "tool == 'bash' and args.command =~ 'git push'"

# OR combination — any tool triggers
condition = "tool == 'bash' or tool == 'delete_file'"

# Multi-condition AND
condition = "tool == 'bash' and args.command =~ 'git push' and args.command =~ '--force'"
```

Operators: `==` (equal), `!=` (not equal), `=~` (regex match via `re.search`), `~=` (glob match via `fnmatch`). Combine with `and` (all must match) or `or` (any match). **Cannot mix** `and` and `or` in the same expression — split into separate `[[hooks]]` rules when needed.

**Verifying it works**: seeing `Loaded N hook rule(s) from config` at startup means it loaded; have the Agent trip a rule — a block rule shows the error `Blocked by hook: <your reason>`, a confirm rule pops the confirmation dialog (after rejection the LLM receives `Denied by user: <your reason>`), a command rule check the command output log, a notify rule check the terminal notification line.

**Common recipes**:

```toml
# Directory read-only lock
[[hooks]]
tool = "write_file"
arg = "file_path"
contains = "docs/spec"
reason = "docs/spec.md is read-only by project policy; contact the maintainer to modify it"

# Forbid external downloads
[[hooks]]
tool = "bash"
contains = "curl"
reason = "External downloads are forbidden by project policy"

# Block destructive deletion (regex guards against variants without false-positives like echo 'rm-rf')
[[hooks]]
tool = "bash"
regex = 'rm\s+-rf'
reason = "Destructive deletion is forbidden by project policy"

# Forbid pushing straight to the main branch (AND: it is a push AND carries --force or targets main)
[[hooks]]
tool = "bash"
contains = "git push"
regex = '--force|main'
reason = "Force-push / direct push to main is forbidden; go through a PR"

# Disable a tool entirely (with an explanation, so the LLM changes course instead of retrying)
[[hooks]]
tool = "delete_file"
reason = "This project forbids the Agent from deleting files; ask the user to delete them manually"

# Anti-leak across all tools (tool omitted = *, checks every parameter of every tool)
[[hooks]]
contains = "internal.corp.com"
reason = "Intranet addresses are not allowed to appear in tool calls"

# Sensitive operations require human confirmation (not disabled, but asks you every time; press a to stop asking this session)
[[hooks]]
tool = "bash"
contains = "git push"
action = "confirm"
reason = "push affects the remote repository"

# Auto-format .py files after writing (post_tool stage, failure doesn't block the write)
[[hooks]]
event = "post_tool"
condition = "tool == 'write_file' and args.file_path =~ '\\.py$'"
action = "command"
command = "ruff format $TOOL_ARGS.file_path"
command_timeout = 15

# Syntax-check .py files after writing (post_tool, warning only — does not block)
[[hooks]]
event = "post_tool"
condition = "tool == 'write_file' and args.file_path =~ '\\.py$'"
action = "command"
command = "python -c \"import ast; ast.parse(open('$TOOL_ARGS.file_path').read()); print('syntax OK')\""

# Print a notification line after every bash call (for auditing/observing)
[[hooks]]
event = "post_tool"
tool = "bash"
action = "notify"
message = "[hook] bash done: $TOOL_ARGS.command"

# Use condition expressions instead of fixed fields — flexible combinations
[[hooks]]
condition = "tool == 'bash' and args.command =~ 'git push' and args.command =~ '--force'"
action = "block"
reason = "force push is forbidden; go through a PR"
```

**Boundaries**: the configuration layer handles "reject" (block), "force confirm" (confirm), "execute command" (command), and "terminal notification" (notify) — all declarative, no Python required. Rewriting parameters (MODIFY) requires writing a Python Hook or an EventBus subscriber — see docs/agent-architecture.md S04. The confirm decision dialog is executed by the main Agent's terminal; SubAgents (spawn_agents) do not load `[[hooks]]` rules and have no confirmation UI — code-registered CONFIRM hooks always safely reject when there is no UI.

---

## 5. Context File Usage Guide

### Project Instructions (AGENT.md / CLAUDE.md / .mini-agent/instructions.md)

**What they do**: write your project conventions there and the LLM knows them from startup, so you never have to explain them in every conversation.

**What to write**: build/test commands, directory layout conventions, code style, architectural highlights. Example:

```markdown
# My Project

## Common Commands
- Test: uv run pytest tests/
- Lint: uv run ruff check src/

## Conventions
- Full type annotations, line-length 100
- Tests go in tests/unit/ and tests/integration/
```

**Default lookup logic** (without changing configuration):

```
Search the project root in order: AGENT.md → CLAUDE.md → .mini-agent/instructions.md
First non-empty file found → injected into the system prompt → startup shows "context: loaded <filename>"
None of the three exist → silently skipped (no prompt at all)
Over 8000 characters → truncated and annotated "(truncated)"
```

**Changing file names/priority**: edit the `instruction_files` list in the `[context]` section of config.toml:

```toml
[context]
instruction_files = ["MY_RULES.md"]        # Only recognize this one file
# Or reorder to prioritize CLAUDE.md:
# instruction_files = ["CLAUDE.md", "AGENT.md"]
```

**When it takes effect**: read once at startup. After editing an instruction file's content, restart `mini`.

### User-Level Global Instructions (~/.mini-agent/instructions.md)

**What it does**: personal preferences across all projects — injected no matter which directory `mini` is launched in.

**What to write**: language preference, answering style, and other instructions unrelated to any specific project. Example:

```markdown
- Always answer in Chinese
- Keep answers concise; don't repeat my question
```

**Relationship with project instructions**: they **coexist** — both are injected (user-level first, project-level after), not either-or.

**Changing the path**: `user_instructions_file` in the `[context]` section of config.toml:

```toml
[context]
user_instructions_file = "~/my-notes/ai-rules.md"
```

### @-include Recursive Inclusion

**Purpose**: combine project rules spread across multiple files into a single instruction entry point — no need to cram everything into one AGENT.md. Each referenced file is maintained independently; edit any of them and restart mini for it to take effect.

**Syntax**: in an instruction file (AGENT.md / CLAUDE.md / instructions.md), write `@./relative/path` or `@~/home/path` **on its own line**. At startup, that line is replaced with the referenced file's content. Inline occurrences (e.g. `see @./doc.md for details` in running text) are NOT expanded.

**Example** — AGENT.md as an index, individual rule files maintained separately:

```markdown
# Project rules

@./docs/code-style.md
@./docs/testing-rules.md
@~/.mini-agent/global-rules.md
```

After starting mini, the system prompt will contain the full content of all three files (as if they were inlined into AGENT.md).

**Path resolution**:

- `@./path` — relative to the **directory of the including file** (not the project root). E.g. if `docs/rules.md` contains `@./sub/detail.md`, it resolves to `docs/sub/detail.md`
- `@~/path` — relative to the user's home directory. Good for cross-project rules

**Nesting**: referenced files can contain their own `@./` directives, expanded recursively up to depth 5 (`[context] max_include_depth`, set 0 to disable entirely).

**Error handling**:

- File not found → inserts `<!-- include not found: ./path -->` comment, does not break the rest
- Circular include (A references B, B references A) → inserts `<!-- circular include: ./path -->` comment, no infinite loop
- Expanded content exceeds `max_chars` → truncated normally

**Typical use cases**:

| Scenario | Approach |
|---|---|
| Large team project | Different roles maintain separate rule files; AGENT.md just indexes them |
| Monorepo | Root AGENT.md includes each sub-project's rules as needed |
| Personal cross-project rules | `@~/.mini-agent/global-rules.md` avoids duplicating rules in every project |
| User-level instructions | `~/.mini-agent/instructions.md` also supports @-include |

**Note**: some IDEs may show lint warnings for `@./` syntax in instruction files (e.g. "import path outside project root") — this is a false positive from the IDE's static analysis and does not affect mini-agent.

---

## 6. FAQ

**Q: config.toml and CLAUDE.md are both "project-level" — what's the difference?**
A: config.toml holds parameters read by the **program** (changes affect program behavior, e.g. timeout/theme); CLAUDE.md is natural language read by the **LLM** (changes affect the LLM's answers, program behavior unchanged).

**Q: What happens if a project has both AGENT.md and CLAUDE.md?**
A: Only AGENT.md is read (higher priority wins); CLAUDE.md is ignored. Not merging is deliberate — it avoids the LLM being torn when the two files conflict.

**Q: What does `@./path` mean in an instruction file?**
A: **@-include recursive inclusion** — a line containing only `@./relative/path.md` or `@~/home/path.md` is replaced at startup with the referenced file's content (relative paths resolve from the including file's directory, not the project root). Nested includes are expanded recursively up to depth 5 (`[context] max_include_depth`, set 0 to disable). Circular includes and missing files produce `<!-- circular include: ... -->` / `<!-- include not found: ... -->` comment markers without affecting the rest. Inline occurrences (e.g. `see @./doc.md for details`) are NOT expanded.

Example AGENT.md:
```markdown
# Project rules
@./docs/code-style.md
@./docs/testing-rules.md
@~/.mini-agent/global-rules.md
```

**Q: Why did the LLM not react after I edited CLAUDE.md?**
A: Instruction files are read once at startup; restart `mini` after editing.

**Q: Where should the API key go?**
A: The `.env` file (already gitignored) or environment variables. Do **not** put it in config.toml — a project-level config.toml could get committed to git and leak.

**Q: How do I confirm instruction injection succeeded?**
A: At startup, look for the `context: loaded <filename>` line; or ask the LLM a question only answerable from the instruction file (e.g. the project's test command) — if it answers correctly without calling any tool, injection succeeded.

**Q: Memory (memory.json) and instruction files (instructions.md) both get injected — what's the difference?**
A: Instruction files are static conventions **you hand-write**, injected at startup; memory is dynamic accumulation **auto-extracted by the LLM** (also addable manually via `/memory add`), injected before every LLM call. The former suits stable rules; the latter suits preferences discovered mid-session.

---

## 7. Automatic Memory Extraction in Detail

The memory system is **fully automatic** — no switch to flip, enabled by default.

### Workflow

```
During conversation you state a preference/convention ("I like concise comments", "this project uses uv", etc.)
  ↓ Exit via /exit or closing the window
SESSION_END hook → LLM analyzes the last 20 messages → extract → dedupe → save to disk
  ↓ Next launch of mini (any time, even after rebooting the machine)
PRE_LLM hook → memory read automatically → injected into system prompt → the LLM "knows" from turn one
```

### What Gets Extracted (the LLM's filtering rules)

| Category | Extracted | Not extracted |
|---|---|---|
| **preference** | "I like concise code comments" | "Hello" (greetings) |
| **convention** | "This project uses uv to manage dependencies" | "Help me look at this bug" (task details) |
| **fact** | "Python version requirement is 3.11+" | "OK thanks" (filler words) |
| — | — | Suggestions the LLM itself made (only what the **user** said is extracted) |

### Filtering Conditions (three layers)

**Layer 1: threshold** — fewer than 5 user messages in this session → extraction is not triggered (too short to be worthwhile).

**Layer 2: deduplication** — new extractions are compared against existing memory; hitting any one condition discards them:
- Exactly identical (case-insensitive)
- Existing memory contains the new extraction (substring)
- Over 60% word overlap (prevents "same thing reworded" — e.g. "always use type hints on functions" and "use type hints on all functions always" are the same thing)

**Layer 3: LLM prompt rules** — the LLM is told to extract only what the user explicitly said, skip transient content, keep each entry self-contained and readable, 1-2 sentences, and return empty when nothing is worth remembering.

### Storage and Lifetime

| Item | Description |
|---|---|
| Storage locations | `~/.mini-agent/memory/user_memory.json` (cross-project) + `<project>/.mini-agent/memory.json` (project-level) |
| Lifetime | **Permanent** — the file stays on disk until deleted |
| Injection | Automatically injected into the system prompt before every LLM call (≤10 entries: all injected; >10 entries: the LLM picks the 5 most relevant) |
| Manual add | `/memory add I like such-and-such` (takes effect immediately, no need to wait for exit) |
| View | `/memory` |
| Delete | `/memory delete <ID or keyword>` (the ID can be copied from the `/memory` list, or match by content keyword) |

### Disabling / Debugging

If auto extraction quality is poor (a weak model's misunderstanding producing garbage memory), turn it off in config.toml:

```toml
[memory]
auto_extract = false   # After disabling, use /memory add to add manually instead
```

For debugging, run `/memory` before `/exit` to see what was extracted last time; if unsatisfied, hand-edit the JSON file to remove entries.

### Differences from CLAUDE.md (Context Awareness)

| | CLAUDE.md / AGENT.md | Memory (memory.json) |
|---|---|---|
| Source | Hand-written by you | Auto-extracted by the LLM + `/memory add` |
| Nature of content | Stable project rules | Dynamically accumulated preferences |
| Injection timing | Once at startup | Before every LLM call |
| Scope | This project | Cross-project (user-level) or this project (project-level) |
| How to modify | Edit the md file | Automatic / `/memory add` / edit the JSON |

**The two coexist and complement each other** — CLAUDE.md holds stable rules like "this project uses uv, tests go in tests/"; memory records personal preferences like "the user likes concise comments".

---

## 8. Permission Rules File (permissions.toml)

Customize which commands/paths/tools are allowed through without confirmation and which are unconditionally rejected — without touching code.

**Location** (two levels, both effective simultaneously):

| File | Scope |
|---|---|
| `~/.mini-agent/permissions.toml` | User-level — all projects |
| `<project>/.mini-agent/permissions.toml` | Project-level — current project only |

**Format** (see `permissions.toml.example` in the project root for a full example):

```toml
[commands]
allow = ["git push origin dev", "docker build *"]   # Allowed without confirmation (dangerous commands too)
deny = ["docker rm *"]                               # Unconditionally rejected

[paths]
allow = ["D:/shared/workspace/*"]    # Allow paths outside the project (outside-project paths require confirmation by default)
deny = ["*secrets*", "*.key"]        # Deny access (blocked even for paths inside the project)

[tools]
allow = ["glob"]           # Trust the tool wholesale (skips command/path-level checks, use with caution)
deny = ["delete_file"]     # Block the entire tool outright
```

**Precedence**: `deny rules > allow rules > built-in defaults` (dangerous-command confirmation / sensitive-path rejection / inside-project allowance). deny wins above all — even a path inside the project gets blocked.

**What command deny rules match, and their boundary**: a command-scope deny rule matches more than the literal command — wrapped and chained forms hit too: `cmd /c "ping x"` and `echo hi & ping x` both match a `ping*` rule (cmd /c / cmd /k / powershell -Command / sh -c prefixes are unwrapped; segments split on `&;|` after blanking quoted spans; quoted data never false-denies; allow rules are NOT unwrapped). This is defense in depth, not a wall: deep obfuscation (`p^ing` escaping, env-var indirection, base64 encoding) cannot be exhaustively caught at the pattern layer — the layered guarantee is that obfuscation carriers themselves (cmd /c, powershell -EncodedCommand, etc.) sit on the dangerous-command list and always require confirmation, and the OS sandbox is the final wall. Deny rules express policy intent; they do not replace the sandbox.

**Sub-agent boundary**: deny rules bind every agent in the session (spawned sub-agents included, live). Sub-agents have no confirm UI, however — anything that would prompt (dangerous commands etc.) is denied fail-safe rather than asked; if a dangerous operation needs human approval, run it via the main agent.

**Built-in path protection** (PathGuard, no configuration needed, fixed in code):

Evaluation order (first match decides):
1. `denied_paths` (`~/.ssh`/`~/.aws`/`~/.gnupg`, configurable in config.toml) → hard reject
2. Sensitive filename patterns (`.env`/`.env.*`/`*.pem`/`*.key`/`id_rsa*`/`id_ed25519*`/`credentials*`/`*secret*`/`*.p12`/`*.pfx`, 10 kinds in total) → hard reject (blocked even inside the project); `.env.example`/`.env.sample`/`.env.template` are exempt
3. Inside the project directory → auto allow
4. Paths in `allowed_paths` (configurable in config.toml) → auto allow
5. None of the above matches → ask the user (when `permission_mode = "ask"`)

> **bash channel also covers sensitive files**: this PathGuard sensitive-file protection only guards the `read_file`/`write_file`/`delete_file` tools. bash commands used to skip path checks entirely — `type .env`/`cat ~/.ssh/id_rsa`/`Get-Content credentials.json` sailed through as normal commands, bypassing the file-tool block and printing the contents (a real API key leaked during verification). Now permission.py's `command_references_sensitive_file()` tokenizes a bash command and, if any token's basename matches the same sensitive-file patterns above, routes it to a **confirmation** (decision reason `sensitive_file_command`); a denial trips the confirm-denial breaker. Honest boundary, same as the dangerous-command blacklist: obfuscated paths (env vars like `$SECRET`, wildcards, base64/echo concatenation) can still slip through — see docs/tech-notes.md §90.

**Tool-level rules (P79)**: the `[tools]` section matches by tool name (glob supported) and is evaluated **before** command/path checks — `deny` blocks the entire tool outright; `allow` trusts the tool wholesale, skipping subsequent resource checks (`allow = ["bash"]` means even dangerous commands are no longer confirmed — use with caution); tools with no matching rule go through command/path checks as usual.

**Matching syntax**: glob style. `git *` matches `git status` but not `github`; `*secrets*` matches any path containing secrets.

**Verifying it works**: after `/trace on`, trigger a relevant operation; the trace line shows `rule:<scope>:<pattern>` as the decision basis.

**When changes take effect**: restart mini (loaded once at startup). Or use the `/allow` `/deny` commands at runtime to add rules live — rules with the `--save` flag are written to the project-level permissions.toml and load automatically next startup. The permission confirmation dialog also asks a one-line follow-up after `a` — answer y to persist to the same file (default: session-only).

**Runtime management** (P78/P79):
```
/allow command "docker *"          # Allow all docker commands for this session
/deny path "*/secrets/*"           # Deny secrets paths for this session
/deny tool delete_file             # Block the delete_file tool for this session
/allow command "npm *" --save      # Allow and persist to .mini-agent/permissions.toml
/deny                              # List all current DENY rules
```

---

## 9. OS-Level Sandbox (sandbox)

Kernel-level isolation of the execution environment for bash commands — even a command that passes permission checks can only operate within a restricted scope.

**Supported platforms**:

| Platform | Backend | Installation |
|---|---|---|
| Linux | bubblewrap (bwrap), auto-fallback to unshare if unavailable | bwrap: `sudo apt install bubblewrap` or `yum install bubblewrap`; unshare: pre-installed (util-linux) |
| macOS | Seatbelt (sandbox-exec) | Bundled with the system (`/usr/bin/sandbox-exec`) |
| Windows | Dual-mode: admin Low Integrity process (kernel-level) / non-admin no file protection (documented only, no startup warning) | Built-in (ctypes); see file permissions table below |

**Enabling**:

```toml
# config.toml
[security]
sandbox = true               # Turn on the sandbox
sandbox_auto_allow = false    # Optional: dangerous commands skip confirmation under the sandbox
sandbox_network = false       # Optional: allow network access
```

**File permissions inside the sandbox** (fixed in code, not user-configurable):

**Linux/macOS (bwrap/seatbelt)** — process-level isolation, entire filesystem read-only:

| Path | Permission |
|---|---|
| Working directory (project directory) | Read-write |
| System temp directory (`tempfile.gettempdir()`, cross-platform) | Read-write |
| `~/.mini-agent` | Read-only (prevents commands from tampering with configuration) |
| The rest of the entire filesystem | Read-only |

On Linux, when bwrap is unavailable, the sandbox automatically falls back to `unshare --mount --map-root-user` (pre-installed via util-linux), providing similar mount-namespace isolation.

**Windows admin mode (Low Integrity process)** — kernel-level isolation, equivalent to bwrap/seatbelt:

| Path | Permission |
|---|---|
| Working directory (project directory) | Read-write |
| System temp directory | Read-write |
| The rest of the filesystem | **Kernel-enforced non-writable** (Low Integrity token cannot write Medium/High integrity objects) |

Uses ctypes to lower the subprocess token integrity (`_low_integrity.py` helper), providing kernel-level protection equivalent to bwrap/seatbelt.

**Windows non-admin mode (no file protection)** — attrib has been disabled (it blocks the agent's own file writes):

Non-admin mode applies no file protection and prints no startup warning (this limitation is documented here only, to avoid noise on every launch). Only admin Low Integrity mode provides real sandbox isolation.

**How sandbox_auto_allow works with permissions.toml**:

```
Command arrives
  ↓
① permissions.toml deny rule? → reject (the sandbox can't save it either)
  ↓
② permissions.toml allow rule / session grant? → allow
  ↓
③ Dangerous command (27 regexes, including inline interpreters)?
     sandbox_auto_allow=true → allow (sandbox as backstop)
     sandbox_auto_allow=false → confirmation dialog
  ↓
④ Execution: sandbox present → isolated execution (Linux/macOS: read-only rootfs; Windows admin: Low Integrity kernel-level isolation)
       no sandbox → executed as-is
```

- **permissions.toml** governs "whether this command should be executed"
- **sandbox** governs "which files it can touch during execution"
- **deny rules trump everything**, nothing bypasses them — sandbox_auto_allow does not affect them

**Verifying it works**: after `/trace on`, execute a command; the trace line shows `sandbox_auto_allow` as the decision basis (when confirmation is skipped under the sandbox).

> **⚠ Security Boundary (applies to all three platforms)**
>
> **When `sandbox=false`** (now off by default -- sandbox is on): all three platforms have only regex + confirmation dialogs as protection. If the LLM is denied `rm -rf`, it can switch to `python -c "shutil.rmtree(...)"` to bypass (common inline interpreters have been added to the dangerous patterns; writing a `.py` file and running it is caught by the write-then-execute detection).
>
> **When `sandbox=true`**:
> - **Linux**: bwrap (or unshare fallback) provides kernel-level read-only filesystem. Even if the LLM bypasses regex, it cannot write to protected paths. This is the strongest protection.
> - **macOS**: seatbelt provides kernel-level read-only filesystem, equivalent to Linux bwrap.
> - **Windows admin**: Low Integrity process provides kernel-level isolation, equivalent to bwrap/seatbelt.
> - **Windows non-admin**: No file protection (this limitation is documented here only; no startup warning is printed). attrib has been disabled because it blocks the agent's own file writes. Only admin Low Integrity provides real protection.
>
> **Read-leak boundary**: the sandbox governs "what can be written," not "what can be read" — a Low Integrity process can still read Medium-integrity objects. Leaking a sensitive file (`.env`/keys/credentials) via bash `type`/`cat`/`Get-Content` is caught by the command-layer `command_references_sensitive_file()` confirmation (see §8's "bash channel also covers sensitive files" note), not by the sandbox. Same speed bump: obfuscated paths can still slip through.
>
> **Bottom line**: Denying a command ≠ the operation is impossible. The sandbox narrows the writable scope, regex + confirmation dialogs + write-then-execute detection prevent common mistakes, but without sandbox or with Windows non-admin sandbox, deliberate LLM bypass cannot be fully prevented.

---

*Related docs: terminal output explained in output-guide.md, how to open terminals per OS and compatibility in terminal-guide.md, capability matrix in docs/capabilities.md, architecture internals in docs/agent-architecture.md.*
