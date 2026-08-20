# Command Reference (Slash Commands Guide)

> 中文版 (Chinese version): [../commands-guide.md](../commands-guide.md)

Complete syntax, parameters and examples for all 26 visible commands. Slash commands execute locally with zero token consumption (except those that trigger LLM calls, such as `/compact` and `/team`, all of which are marked). Typing `/` pops up an alphabetically sorted dropdown completion menu.

> For the source and toggles of each output line, see output-guide.md; for configuration options, see config-guide.md.

---

## 1. Session and Status

### /status
Show session status. No parameters.
Output: model, provider, platform, turn count, token usage, cost/budget, context usage, message count, session ID, project directory.

### /clear
Clear conversation history (system prompt and memory injection are preserved). No parameters.

### /compact
Manually compress conversation history (triggers the four-level compression cascade: DropToolResults → LLMSummarizeOldest → SummarizeOldest → SlidingWindow). No parameters. **Calls the LLM** (when using the LLM summarization strategy).

### /session — Session Management
```
/session save              # Save the current session
/session list              # List saved sessions (newest first)
/session list --tag <name> # Filter saved sessions by tag
/session load <id>         # Load a session (id may be a prefix from list)
/session delete <id>       # Delete a session
/session tag <name>        # Add a tag to the current session
/session untag <name>      # Remove a tag from the current session
/session tags              # Show all tags of the current session
```
Shows usage when called without parameters. Tags can be used to categorize sessions (e.g. `#bug-fix`, `#refactor`); use `--tag` with list to filter by tag. Sessions are stored in `~/.mini-agent/sessions/`; normally closed sessions older than `session_cleanup_days` (default 30 days) are automatically cleaned up at startup.

### /undo [N]
Roll back the most recent N turns (default 1) — **both conversation and files are rolled back** (file snapshots are only kept for the last 5 turns; files modified by bash commands cannot be recovered).
```
/undo        # Roll back 1 turn
/undo 3      # Roll back 3 turns
```

### /fork [N]
Deep-copy the current conversation into a new session branch (optionally roll back N turns before forking).
```
/fork        # Fork from the current state
/fork 2      # Roll back 2 turns, then fork
```

### /exit (alias /quit)
Exit. You can also type `exit` / `quit` directly.

---

## 2. Model and Cost

### /model [name]
Without parameters: shows the current model, the list of available providers (`openai`/`anthropic`/`openai-responses`) and switchable profiles. With a parameter: hot-switch to a named profile (profiles are defined via the environment variable `MINI_AGENT_MODELS` + `MODEL_<NAME>_*`, see config-guide).
```
/model            # Show current model + available providers + profiles
/model smart      # Switch to the smart profile
```
Note: switching to a named profile **also switches** the provider (e.g. from openai to anthropic). A bare model name (matching no profile) keeps the current provider and key.

### /cost [turns|reset]
```
/cost             # Cost dashboard: per-model breakdown for this session + cumulative ledger + budget progress
/cost turns       # Per-turn token/cost breakdown
/cost reset       # Reset the cumulative ledger (in-session data unaffected)
```
Unit prices must be configured under `[cost.pricing.<model-name>]`; otherwise amounts remain 0.

---

## 3. SubAgent and Multi-Agent

### /spawn — SubAgent Dispatch (the most complex command in this section)

**Dispatch**:
```
/spawn <task>                     # Dispatch a single SubAgent in the background, returns immediately
/spawn -p <task1> | <task2>       # Dispatch multiple in parallel (separated by |)
/spawn --isolated <task>          # Run in a separate git worktree (file isolation)
/spawn --type <t> <task>          # Specify type: explore/plan/worker(default)/verify
/spawn --pane <task>              # Run in a visible terminal pane (separate process, watch live)
/spawn --wait <task>              # Dispatch + progress panel + result in one command
/spawn --pane --wait <task>       # Combined: open a pane + block for the result
```

**Collection and management**:
```
/spawn list                       # List active SubAgents (id + phase)
/spawn wait                       # Wait for all to finish (multiple results show an overview table + numbered sections)
/spawn wait <id>                  # Wait for a specific agent
/spawn cancel [id]                # Cancel a specific agent / all agents
```

Parameter details:
| Parameter | Description |
|---|---|
| `--pane` | Requires a tmux session, a Windows Terminal session (split pane), or any terminal with wt.exe installed (falls back to a new tab in the shared mini-agents window). Fails with a clear error when no backend is available |
| `--wait` | Blocks until completion (900-second cap) while showing a progress panel; without it, use the two-stage collection via `/spawn wait` |
| `--isolated` | Each agent gets its own dedicated worktree; results come with merge hints |
| `--type` | explore/plan/verify use a read-only toolset, worker gets all tools. When unspecified, falls back to the default worker type profile (P80) but keeps the configured `max_agent_iterations` iteration budget; when explicitly specified, adopts the type profile's budget (worker=50/verify=20, etc.) |

Notes:
- Tasks that need to communicate with each other (send_message/wait_message) must be **dispatched in a single `-p` call**; separate dispatches run serially
- A pane worker's report is fully relayed back to the main window; delivered files it mentions are listed in bright orange
- Results that complete after the wait timeout (900s) become orphans; you can manually check `~/.mini-agent/workers/<id>.result.json`
- The more specific the task, the fewer tokens it costs — vague "analyze the whole project"-level tasks were measured to consume 0.7–1.8M tokens

### /team <task> [--isolated] [--coordinator]
LLM automatically decomposes the task → matches team members by role → executes in parallel → aggregates a report. **Calls the LLM**.
```
/team Add a smoke test suite to the project
/team --coordinator --isolated Refactor the logging module    # pure-scheduling Planner + worktree isolation
```

### /plan [on|off]
Toggle read-only plan mode (write-type tools disabled). Without parameters, shows the current state.

---

## 4. Observability and Debugging

### /trace [on|off]
Show the agent's internal state in real time: ReAct phase transitions, permission decisions (including the matched rule), tool durations, LLM token metadata.

### /explain [on|off]
Teaching mode: prints an explanatory panel before each tool call (why this tool is used / what the parameters mean).

### /audit [on|off|verify]
```
/audit on        # Start recording all tool calls to ~/.mini-agent/audit.jsonl (hash chain)
/audit off       # Stop
/audit verify    # Verify hash chain integrity (detect tampering)
```

### /allow — Add ALLOW permission rules at runtime
```
/allow                            # List all current ALLOW rules
/allow command "docker *"         # Allow all docker commands
/allow path "D:/shared/*"         # Allow read/write on the given path
/allow tool bash                  # Trust the bash tool entirely (skips command-level checks, use with caution)
/allow command "npm *" --save     # Allow and persist to .mini-agent/permissions.toml
/allow remove tool bash           # Remove an ALLOW rule from the current session
```
The scope must be `command`, `path` or `tool`; patterns use glob matching.
The `tool` scope matches by tool name and is evaluated before command/path checks: allow trusts the tool entirely (dangerous commands are no longer confirmed either); deny blocks the entire tool outright.
Without `--save`, rules only apply to the current session; with `--save`, they are written to the project-level permissions.toml and loaded automatically after restart.
Duplicate rules are automatically deduplicated and will not be added twice.

### /deny — Add DENY permission rules at runtime
```
/deny                             # List all current DENY rules
/deny command "rm -rf *"          # Deny all rm -rf commands
/deny path "*/secrets/*"          # Deny access to secrets paths
/deny tool delete_file            # Block the delete_file tool outright
/deny path "*.pem" --save         # Deny and persist
/deny remove tool delete_file     # Remove a DENY rule from the current session
```
Same syntax as `/allow`. DENY takes priority over ALLOW (evaluation order: DENY → ALLOW → session authorization → default mode).
`remove` only removes rules from the current session's rule table (exact scope+pattern+level match); rules from permissions.toml will still be loaded on the next startup — edit the file itself to remove them.

### /tools
List all registered tools (built-in + MCP, including search hints in dispatch mode). No parameters.

---

## 5. Memory and Tasks

### /memory — Cross-session Memory
```
/memory                      # View all memories
/memory add <content>        # Add manually
/memory delete <content>     # Delete by content
/memory consolidate          # LLM semantic merge of related memories (calls the LLM)
/memory export [dir]         # Export as .md files (YAML front matter + MEMORY.md index)
/memory import <dir>         # Import from a .md directory (dedupe by id, restore scope)
```

### /todo — Persistent Task List (survives restarts)
```
/todo                        # List tasks
/todo add <desc>             # Add
/todo add <desc> --after <id>  # Add with declared dependencies (comma-separated for multiple)
/todo start <id>             # Mark in progress (refused if blocked by dependencies)
/todo done <id>              # Mark done
/todo fail <id>              # Mark failed
/todo delete <id>            # Delete
/todo clear                  # Clear all
```
IDs support prefix matching; an ambiguous prefix (matching multiple tasks) raises an error and lists all matches. IDs shown in the list are automatically truncated to the shortest unique prefix.

---

## 6. Recording and Replay

### /record — Record a tool-call sequence
```
/record start <name>         # Start recording (subsequent tool calls are recorded)
/record stop                 # Stop and save to ~/.mini-agent/recordings/
/record cancel               # Abandon the current recording
/record list                 # List saved recordings
/record delete <name>        # Delete
```
Note: tool calls inside SubAgents are not recorded; recording state lives in memory, so a crash loses any recording not yet stopped.

### /replay <name> [var=value ...]
Replay a recorded tool sequence with zero LLM calls, with `{{variable}}` template substitution support:
```
/replay deploy-check
/replay scaffold name=my_module     # Fills {{name}} in the recording
```
When variables are missing, all required variable names are listed. Replay results do not enter the conversation history (the LLM does not know what the replay changed).

---

## 7. Extensions

### /skill — Skill Pack Management
```
/skill                       # List all skill packs and activation status
/skill activate <name>       # Activate (prompt injected into system prompt)
/skill deactivate <name>     # Deactivate (exact removal)
/skill install <path_or_url> # Install: copy a local directory / clone a git URL
/skill uninstall <name>      # Uninstall
/skill reload                # Hot-reload the skills directory (no restart needed after editing SKILL.md)
```

### /plugins
List loaded plugins and the tools/commands/skills each has registered. No parameters.
Plugins can be installed in two ways: drop a `.py` file into `./.mini-agent/plugins` (or `~/.mini-agent/plugins`),
or pip-install a package that declares the `mini_agent.plugins` entry point. The `disabled_plugins` config option can disable plugins.

### /theme [default|dark|light]
Switch the color theme and persist it to `~/.mini-agent/.theme`. Without parameters, shows the current theme.

### /help
List all commands (alphabetically sorted).

---

## 8. General Behavior

- Commands execute locally; mistyping a command name shows all available commands
- An exception thrown by a command handler does not kill the session (shows "Command failed: ..." and continues)
- Report-style output (/spawn wait) goes through Markdown rendering (tables/headings/bright-orange filenames); status-style output (/status /cost) keeps plain-text aligned layout
- All commands are equally available in remote browser mode (`--remote`)
