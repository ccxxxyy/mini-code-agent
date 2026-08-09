# Mini-Code-Agent

[![PyPI version](https://img.shields.io/pypi/v/mini-code-agent)](https://pypi.org/project/mini-code-agent/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-480%20passed-brightgreen)]()

**A terminal-based coding agent** inspired by Claude Code — built from scratch in Python, fully open-source, and designed to be readable.

[中文文档 (Chinese)](README-zh.md)

---

## Why Mini-Code-Agent?

| | Claude Code | Mini-Code-Agent |
|---|---|---|
| **Cost model** | Subscription ($) | Pay-per-token — built-in cost dashboard (`/cost`) |
| **Conversation control** | Server-side, no undo | Local — `/undo` rollback + `/fork` branching |
| **Extensibility** | Closed | Open tools/hooks/skills/MCP |
| **Transparency** | Black box | `/trace` shows every decision in real time |
| **Codebase** | Proprietary | ~4,600 lines of readable Python, MIT licensed |

## Features

🔧 **8 Built-in Tools** — read/write/edit/delete files, bash, glob, grep, spawn agents

🤖 **Multi-Agent** — `/spawn` parallel agents, `/team` auto-planned orchestration, strong/weak model mixing

💰 **Cost Dashboard** — per-model input/output pricing, session + all-time ledger, budget warnings at 80%/100%

⏪ **Undo & Fork** — `/undo` rolls back conversation AND file changes; `/fork` branches into a new session

🎬 **Record & Replay** — `/record` captures tool sequences, `/replay` re-runs them with zero LLM calls + `{{template}}` variables

🧠 **Memory** — LLM auto-extracts preferences at session end, injects them next session; manual `/memory add` too

📋 **Persistent Tasks** — `/todo` with dependency tracking (`--after`), survives restarts

🔌 **MCP Protocol** — stdio + HTTP transport, connect any MCP-compatible tool server via config

🎨 **Themes** — dark/light/default, markdown heading colors follow theme

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

See [docs/terminal-guide.md](docs/terminal-guide.md) for how to open each terminal per OS and their compatibility levels.

## Commands

| Command | What it does |
|---|---|
| `/help` | List all commands |
| `/status` | Session info (model, tokens, cost) |
| `/model [name]` | View or switch LLM model |
| `/cost [turns\|reset]` | Cost dashboard: per-model breakdown, budget tracking |
| `/todo [add\|done\|start\|delete\|clear]` | Persistent task list with dependency graph |
| `/undo [N]` | Roll back N turns — files restored too |
| `/fork [N]` | Branch conversation into a new session |
| `/record start\|stop\|cancel\|list\|delete` | Record tool call sequences |
| `/replay <name> [k=v ...]` | Replay recorded sequence with template variables |
| `/spawn <task>` | Dispatch background sub-agent |
| `/team <task>` | Auto-plan and parallel-execute with sub-agents |
| `/trace [on\|off]` | Show agent internals (phases, permissions, timing) |
| `/explain [on\|off]` | Show tool usage explanations |
| `/audit [on\|off\|verify]` | Audit logging with hash-chain integrity |
| `/theme [dark\|light\|default]` | Switch color theme |
| `/memory [add\|delete <text>]` | View, add or delete persistent memories |
| `/session save\|list\|load\|delete` | Session management |
| `/skill [activate\|deactivate]` | Manage skill packs |
| `/compact` | Compress conversation history |
| `/clear` | Clear conversation |
| `/exit` | Exit |

## Configuration

All settings via `~/.mini-agent/config.toml` (user) or `.mini-agent/config.toml` (project):

```toml
[llm]
model = "deepseek-chat"
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

See [config.toml.example](config.toml.example) for all options. Full guide: [docs/config-guide.md](docs/config-guide.md).

## Architecture

```
mini-code-agent/
├── src/mini_agent/
│   ├── core/        # Agent loop, sub-agents, teams, planner, cost tracker
│   ├── tools/       # 8 built-in tools + MCP protocol (stdio + HTTP)
│   ├── memory/      # Context compression, persistent memory, file snapshots
│   ├── security/    # Permissions, path guard, git worktree isolation
│   ├── ui/          # Rich terminal rendering, themes, prompt toolkit
│   ├── extensions/  # Slash commands, skills, hooks
│   ├── llm/         # Provider abstraction (OpenAI-compatible)
│   ├── config/      # Layered config loading (TOML + env + CLI)
│   └── models/      # Dataclasses (messages, events, config, sessions)
├── tests/           # 480 tests, 83%+ coverage
├── skills/          # 4 built-in skill packs
├── experiments/     # 3 mechanism experiments (compression A/B, model mixing, deadlock induction)
└── docs/            # 12 documentation files (incl. agent-architecture.md, comparison-mewcode.md)
```

**Design philosophy**: Five layers (UI → Engine → Tools → Memory → Security) decoupled via EventBus. All I/O is async. Zero vendor SDK dependency — just httpx.

## S01–S20 Coverage

This project implements **19 of 20** mechanisms from the [learn-claude-code](https://github.com/shareAI-lab/learn-claude-code) harness checklist. See [docs/agent-architecture.md](docs/agent-architecture.md) for a deep dive into what each layer solves and why.

✅ S01 Agent Loop · S02 Tool Use · S03 Permission · S04 Hooks · S05 Planning · S06 Subagent · S07 Skill Loading · S08 Context Compression · S09 Memory · S10 System Prompt · S11 Error Recovery · S12 Task System · S13 Background Tasks · S15 Agent Teams · S16 Team Protocols · S17 Autonomous Agents · S18 Worktree Isolation · S19 MCP Plugin · S20 Comprehensive Agent

⬚ S14 Cron Scheduler — intentionally skipped (OS-level cron/Task Scheduler is more appropriate for a terminal tool)

## Development

```bash
uv sync --extra dev
uv run pytest tests/           # 480 tests
uv run ruff check src/ tests/  # lint
uv run ruff format src/ tests/ # format
```

See [docs/tasks.md](docs/tasks.md) for the full development history (P1–P40, 40 phases).

## Publishing to PyPI

```bash
git tag v1.0.0
git push origin v1.0.0
# GitHub Actions auto-publishes via Trusted Publisher
```

First-time setup: register at [pypi.org](https://pypi.org), add Trusted Publisher for `ccxxxyy/mini-code-agent` → `publish.yml`.

## License

[MIT](LICENSE)
