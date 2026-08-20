# Mini-Code-Agent

[![PyPI version](https://img.shields.io/pypi/v/mini-code-agent)](https://pypi.org/project/mini-code-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-974%20passed-brightgreen)]()

**A terminal-based coding agent** inspired by Claude Code — built from scratch in Python, fully open-source, and designed to be readable.

[中文文档 (Chinese)](README-zh.md)

---

## Why Mini-Code-Agent?

| | Claude Code | Mini-Code-Agent |
|---|---|---|
| **Cost model** | Subscription or API | Any provider pay-per-token — built-in `/cost` dashboard |
| **Conversation control** | Server-side | Local data ownership — `/undo` + `/fork` + `/record` + `/replay` |
| **Extensibility** | Closed | Open tools/hooks/skills/MCP |
| **Transparency** | Black box | `/trace` shows every decision in real time |
| **Codebase** | Proprietary | ~16,500 lines of readable Python, MIT licensed |

## Features

🔧 **12 Built-in Tools** — read/write/edit/delete files, bash, glob, grep, spawn agents, send/wait message, tool_search, mcp_call

🤖 **Multi-Agent** — `/spawn` parallel agents, `/spawn --pane` visible terminal-pane workers (tmux / Windows Terminal, separate processes), `/team` auto-planned orchestration, strong/weak model mixing, cross-agent mailbox messaging (send_message / wait_message)

💰 **Cost Dashboard** — per-model input/output pricing, session + all-time ledger, budget warnings at 80%/100%

⏪ **Undo & Fork** — `/undo` rolls back conversation AND file changes; `/fork` branches into a new session

🎬 **Record & Replay** — `/record` captures tool sequences, `/replay` re-runs them with zero LLM calls + `{{template}}` variables

🧠 **Memory** — LLM auto-extracts preferences at session end, injects them next session; manual `/memory add` too

📋 **Persistent Tasks** — `/todo` with dependency tracking (`--after`), survives restarts

🔌 **MCP Protocol** — stdio + HTTP + SSE transport, connect any MCP-compatible tool server via config; `loading = "dispatch"` for lazy discovery

🔒 **OS Sandbox** — Linux bubblewrap + macOS seatbelt kernel-level isolation (optional `[security] sandbox = true`)

🎨 **Themes** — dark/light/default, markdown heading colors follow theme

🔍 **Transparency** — `/trace` shows every agent decision in real time (phases, permissions, tool timing, LLM metadata)

📚 **Teaching & Audit** — `/explain` shows why each tool is called; `/audit` logs all actions with hash-chain tamper detection

💾 **Session Management** — auto-save with crash recovery, `/session tag`/`list --tag` classification, `/fork` branching

🌳 **Worktree Isolation** — `/spawn --isolated` runs agents in separate git worktrees (parallel file changes don't conflict)

📄 **Context-Aware** — auto-reads `CLAUDE.md` / `AGENT.md` project instructions at startup; `@file` inline references with Tab completion

## Quick Start

### Install

```bash
pip install mini-code-agent
```

Or from source:

```bash
git clone https://github.com/ccxxxyy/mini-code-agent.git
cd mini-code-agent
uv sync
uv run mini
```

### Configure

Set your LLM API key (any OpenAI-compatible provider):

```bash
# Environment variable
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.deepseek.com/v1"  # optional: non-OpenAI provider

# Or .env file (auto-loaded)
echo 'OPENAI_API_KEY=sk-...' > .env

# Or CLI
mini --api-key "sk-..." --base-url "https://api.deepseek.com/v1" --model "deepseek-chat"
```

### Run

```bash
mini          # start the agent
mini --help   # see all options
```

See [docs/guide/en/terminal-guide.md](docs/guide/en/terminal-guide.md) for how to open each terminal per OS and their compatibility levels.

### Remote / Browser Mode

Use the agent from a browser instead of the terminal — works on remote servers, iPads, or any device with a browser.

```bash
# 1. Install with remote support
pip install mini-code-agent[remote]
# Or from source:
uv sync --extra remote

# 2. Start in remote mode (from any working directory)
cd /path/to/your/project
mini --remote

# 3. Open browser
#    Terminal shows: Browser: http://localhost:8765
#    Open that URL in your browser
```

The agent works on whatever directory you run the command from — just like terminal mode.

**Running from any directory** (if installed globally):

```bash
# Global install (once)
cd /path/to/mini-code-agent
uv tool install . --extra remote

# Then use anywhere
cd ~/my-project
mini-agent --remote
# Browser: http://localhost:8765
```

**Custom host/port:**

```bash
mini --remote --host 0.0.0.0 --port 9000
# Browser: http://0.0.0.0:9000

# With token authentication:
mini --remote --remote-token "my-secret"
# Browser: http://localhost:8765?token=my-secret
```

## Commands

| Command | What it does |
|---|---|
| `/help` | List all commands |
| `/status` | Session info (model, tokens, cost) |
| `/model [name]` | View or switch LLM model |
| `/cost [turns\|reset]` | Cost dashboard: per-model breakdown, budget tracking |
| `/todo [add\|done\|start\|fail\|delete\|clear]` | Persistent task list with dependency graph |
| `/undo [N]` | Roll back N turns — files restored too |
| `/fork [N]` | Branch conversation into a new session |
| `/record start\|stop\|cancel\|list\|delete` | Record tool call sequences |
| `/replay <name> [k=v ...]` | Replay recorded sequence with template variables |
| `/plan [on\|off]` | Toggle read-only plan mode (write tools disabled) |
| `/tools` | List all registered tools (built-in + MCP) |
| `/spawn <task>` | Dispatch background sub-agent (`--type`, `--pane` visible terminal pane, `--wait` block for result) |
| `/team <task>` | Auto-plan and parallel-execute with sub-agents |
| `/trace [on\|off]` | Show agent internals (phases, permissions, timing) |
| `/explain [on\|off]` | Show tool usage explanations |
| `/audit [on\|off\|verify]` | Audit logging with hash-chain integrity |
| `/theme [dark\|light\|default]` | Switch color theme |
| `/memory [add\|delete\|consolidate\|export\|import]` | View, add, delete, consolidate, export or import memories |
| `/session save\|list\|load\|delete\|tag\|untag\|tags` | Session management (tag for classification, list --tag to filter) |
| `/skill [list\|activate\|deactivate\|install\|uninstall\|reload]` | Manage skill packs |
| `/plugins` | List loaded plugins (tools/commands/skills each registered) |
| `/allow [remove] <command\|path\|tool> <pattern> [--save]` | Manage ALLOW permission rules (runtime, `--save` persists to TOML) |
| `/deny [remove] <command\|path\|tool> <pattern> [--save]` | Manage DENY permission rules (runtime, `--save` persists to TOML) |
| `/compact` | Compress conversation history |
| `/clear` | Clear conversation |
| `/exit` | Exit |

Full syntax, flags and examples for every command: [docs/guide/en/commands-guide.md](docs/guide/en/commands-guide.md)

## Configuration

All settings via `~/.mini-agent/config.toml` (user) or `.mini-agent/config.toml` (project):

```toml
[llm]
model = "deepseek-chat"
provider = "openai"       # "openai" | "openai-responses" (o1/o3/o4-mini) | "anthropic"
temperature = 0.0

[cost]
budget = 5.0
[cost.pricing.deepseek-chat]
input = 2.0
output = 8.0

[mcp.servers.github]
url = "http://localhost:8080/mcp"
transport = "http"
headers = { Authorization = "Bearer ghp_..." }
```

See [config.toml.example](config.toml.example) for all options. Full guide: [docs/guide/en/config-guide.md](docs/guide/en/config-guide.md).

## Architecture

```
mini-code-agent/
├── src/mini_agent/
│   ├── core/        # Agent loop, state, sub-agents, teams, planner, mailbox, pane worker, cost tracker, task store, tool recorder, agent types, spawn backends
│   ├── tools/       # 12 built-in tools + MCP protocol (stdio/HTTP/SSE, eager/dispatch) + hook system
│   ├── memory/      # Context compression (4-stage cascade), persistent memory, session store, extraction, recall, consolidation, file snapshots, spill cache, project context
│   ├── security/    # Permissions, path guard, audit, OS sandbox (bwrap/seatbelt), worktree isolation, remote confirm (cross-process)
│   ├── ui/          # Rich terminal, streaming renderer, input handler, components, themes, trace, teach, progress board, double-Esc watcher
│   ├── remote/      # WebSocket server + browser UI (--remote mode, disconnect queuing)
│   ├── extensions/  # Slash commands (26), skills (4 built-in), hooks (11 stages), event listener + tool/command/skill plugins
│   ├── llm/         # Provider abstraction: OpenAI Chat Completions + Responses API + Anthropic, token counter
│   ├── events/      # EventBus — async pub/sub decoupling all layers (5 subscribers, 17 subscriptions)
│   ├── config/      # Layered config loading (TOML + env + CLI), shell/platform detection
│   └── models/      # Dataclasses (messages, events, config, sessions, permissions)
├── tests/           # 974 tests, 80%+ coverage
├── skills/          # 4 built-in skill packs
├── experiments/     # 10 mechanism experiments (compression A/B, model mixing, deadlock induction, circuit breaker)
├── examples/        # Example plugins (drop into ./.mini-agent/plugins or declare a mini_agent.plugins entry point)
└── docs/            # 18 documentation files: 14 topic docs + 4 English guide translations (guide/en/)
```

**Design philosophy**: Five layers (UI → Engine → Tools → Memory → Security) + remote/extensions/llm/config/models, decoupled via EventBus. All I/O is async. Zero vendor SDK — just httpx.

## S01–S20 Coverage

This project implements **19 of 20** mechanisms from the [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) harness checklist. See [docs/agent-architecture.md](docs/agent-architecture.md) for a deep dive into what each layer solves and why.

✅ S01 Agent Loop · S02 Tool Use · S03 Permission · S04 Hooks · S05 Planning · S06 Subagent · S07 Skill Loading · S08 Context Compression · S09 Memory · S10 System Prompt · S11 Error Recovery · S12 Task System · S13 Background Tasks · S15 Agent Teams · S16 Team Protocols · S17 Autonomous Agents · S18 Worktree Isolation · S19 MCP Plugin · S20 Comprehensive Agent

⬚ S14 Cron Scheduler — intentionally skipped (OS-level cron/Task Scheduler is more appropriate for a terminal tool)

## Development

```bash
uv sync --extra dev
uv run pytest tests/           # 974 tests
uv run ruff check src/ tests/  # lint
uv run ruff format src/ tests/ # format
```

See [docs/tasks.md](docs/tasks.md) for the full development history (P1–P83, 83 phases).

## Publishing to PyPI

```bash
git tag v1.1.0
git push origin v1.1.0
# GitHub Actions auto-publishes via Trusted Publisher
```

First-time setup: register at [pypi.org](https://pypi.org), add Trusted Publisher for `ccxxxyy/mini-code-agent` → `publish.yml`.

## License

[MIT](LICENSE)
