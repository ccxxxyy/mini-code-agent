# Terminal Output Sources and Configuration Guide

> 中文版 (Chinese version): [../output-guide.md](../output-guide.md)

This document explains the **source component**, **trigger condition**, and **how to toggle** every line of terminal output that Mini-Code-Agent produces within a single conversation turn.

---

## 1. The Complete Output Flow of a Turn

After the user enters a message, the terminal may show the following outputs in order (chronological):

```
> change hello to goodbye in a.txt         ← ① user input (prompt_toolkit)

  ╭─ edit_file ...                          ← ② streaming tool-assembly hint
  trace [12:03:01] iter 1 idle -> thinking  ← ③ trace line (when /trace on)
  trace [12:03:01] llm  request 2 msgs      ← ③
╭── Teach: edit_file ──────────────────╮    ← ④ teaching panel (when /explain on)
│ Why this tool: ...                   │
╰──────────────────────────────────────╯
  trace [12:03:02] llm  response 1082 tokens ← ③
  ╭─ edit_file ...                          ← ② or ⑤ tool call line
  │  file_path=a.txt, old_text=hello...     ← ⑤ argument summary line
  trace [12:03:02] perm path a.txt -> GRANTED ← ③
  trace [12:03:02] tool edit_file start     ← ③
  trace [12:03:02] tool edit_file done 1ms  ← ③
  ╰─ ✓ 1 lines, 42 chars                   ← ⑥ tool result line
  - hello world                             ← ⑦ diff preview (edit_file only)
  + goodbye world                           ← ⑦

Changed hello to goodbye in a.txt.         ← ⑨ LLM streaming reply (Markdown)

  files changed this turn:                  ← ⑩ file change summary
    ~ a.txt                                 ← ⑩

  tokens: 3307 this turn / 3307 total       ← ⑪ token statistics line
```

Legend for the annotations above: ① user input (prompt_toolkit) / ② streaming tool-assembly hint / ③ trace lines (when `/trace on`) / ④ teaching panel (when `/explain on`) / ⑤ tool call line and argument summary line / ⑥ tool result line / ⑦ diff preview (edit_file only) / ⑨ LLM streaming reply (Markdown rendering) / ⑩ file change summary / ⑪ token statistics line.

---

## 2. Source and Toggle for Each Output

### ① User Input Prompt `> `

| Item | Description |
|---|---|
| Source | `ui/input_handler.py` `create_prompt_session` → prompt_toolkit `message=HTML("<prompt>> </prompt>")` |
| Color | Follows theme `theme.primary` (`/theme dark` changes the color) |
| How to disable | Cannot be disabled (you could not type without it) |

### ② Streaming Tool-Assembly Hint `╭─ tool_name ...`

| Item | Description |
|---|---|
| Source | `app.py` `_on_tool_assembling` callback ← `agent_loop.py` `on_tool_call_assembling` |
| Trigger | When the LLM streams a tool_call_delta carrying a tool name (first occurrence) |
| Purpose | Lets the user know which tool the LLM is calling while the JSON arguments are still being assembled |
| How to disable | Delete the line `self.agent_loop.on_tool_call_assembling = _on_tool_assembling` in `app.py` |

### ③ Trace Lines `trace [HH:MM:SS] ...`

| Item | Description |
|---|---|
| Source | `ui/trace.py` `TraceRenderer` (EventBus subscriber) |
| Trigger | After `/trace on` is enabled, one line is printed per event (phase switch / permission / tool / LLM / turn) |
| Includes | Phase switches (iter), permission decisions (perm), tool lifecycle (tool start/done), LLM request/response (llm), turn summary (turn) |
| Toggle | `/trace on` to enable, `/trace off` to disable, `/trace` to toggle |
| Effect when off | Zero output (short-circuited by `if not self.enabled: return` inside the handler) |

### ④ Tool Usage Explanation Panel `Teach: tool_name`

| Item | Description |
|---|---|
| Source | `ui/teach.py` `TeachRenderer` (EventBus subscriber) |
| Trigger | After `/explain on` is enabled, an explanation panel is printed before each tool call |
| Includes | Why this tool was chosen / the actual arguments passed / what each argument means — helps understand the Agent's decision process |
| Toggle | `/explain on` to enable, `/explain off` to disable |
| Use case | Enable when you want to know "why did the Agent call this tool instead of that one"; keep it off for daily use (off by default) |

### ⑤ Tool Call Line `╭─ tool_name args...`

| Item | Description |
|---|---|
| Source | `ui/terminal.py` `show_tool_call` (triggered by the `agent_loop.on_tool_start` callback) |
| Trigger | Each time tool execution starts |
| Content | `╭─ tool name + argument preview` (arguments truncated at 60 characters) |
| How to disable | Set `self.agent_loop.on_tool_start` to `None` in `app.py` |
| Note | If ② has already shown the tool name, ⑤ only prints the argument summary line `│ args...` without repeating `╭─` |

### ⑥ Tool Result Line `╰─ ✓ N lines, M chars`

| Item | Description |
|---|---|
| Source | `ui/terminal.py` `show_tool_result` (triggered by the `agent_loop.on_tool_end` callback, signature `(self, name: str, output: str, is_error: bool = False, metadata: dict | None = None)`) |
| Trigger | Each time tool execution finishes |
| Success | `╰─ ✓ line count, char count` (green ✓) |
| Failure | `╰─ ✗ error preview` (red ✗, truncated at 300 characters) |
| How to disable | Set `self.agent_loop.on_tool_end` to `None` in `app.py` |

### ⑦ Diff Preview (edit_file only)

| Item | Description |
|---|---|
| Source | `ui/terminal.py` `_render_diff` (inside `show_tool_result`, detects `metadata["diff"]`) |
| Trigger | When edit_file succeeds and the metadata contains a diff |
| Content | Deleted lines: `white on dark_red` full-line background; added lines: `white on dark_green` full-line background (Rich named colors, Windows-compatible) |
| How to disable | Delete the diff-generating code block in `edit_file.py` (about 10 lines), or `return` early in `terminal.py` `_render_diff` |

### ⑧ LLM Reasoning Process (Thinking)

| Item | Description |
|---|---|
| Source | `ui/terminal.py` `feed_thinking` (triggered by the `agent_loop.on_thinking_delta` callback) |
| Trigger | When the LLM returns reasoning_content / thinking deltas (reasoning models such as DeepSeek R1, o1/o3) |
| Style | dim italic (faint italics), written token-by-token directly to the terminal (bypassing the Live buffer) |
| How to disable | Set `self.agent_loop.on_thinking_delta` to `None` in `app.py` |

### ⑨ LLM Streaming Reply (Markdown Rendering)

| Item | Description |
|---|---|
| Source | `ui/renderer.py` `StreamRenderer` (Rich Live + Markdown) |
| Trigger | When the LLM returns text deltas (text output that is not a tool_call) |
| Mechanism | `on_stream_start` → Live starts; `on_stream_delta` → chunk-by-chunk commit-style rendering; `on_stream_end(full_text)` → Live closes |
| How to disable | Cannot be disabled (you would not see the LLM's answer) |

### ⑩ File Change Summary

| Item | Description |
|---|---|
| Source | `ui/terminal.py` `show_file_changes` (called by `app.py` `_handle_turn` before token statistics) |
| Trigger | When write_file/edit_file/delete_file executed successfully in this turn (file changes made by bash are not tracked) |
| Content | `files changed this turn:` + one line per file (`+ path` green = created, `~ path` yellow = modified, `- path` red = deleted) |
| How to disable | Delete the `show_file_changes` call line in `app.py` `_handle_turn` |

### ⑪ Token Statistics Line

| Item | Description |
|---|---|
| Source | `app.py` `_handle_turn` → `self.terminal.show_info(f"tokens: {turn} this turn / {total} total")` |
| Trigger | After each conversation turn completes (after the file change summary) |
| Content | With pricing configured, amounts are included: `tokens: 6373 this turn (¥0.0089) / 13215 total (¥0.0182)` |
| How to disable | Comment out the `self.terminal.show_info(...)` line in `app.py` `_handle_turn` |

### ⑫ Budget Warning Line

| Item | Description |
|---|---|
| Source | `app.py` `_show_budget_warning` (at the end of each turn, after the token statistics line) |
| Trigger | Session budget (budget) or cumulative total budget (total_budget) usage reaches ≥80% |
| Content | ≥80% yellow `Session budget warning: ¥4.12 / ¥5.00 (82%)`; ≥100% red `⚠ Cumulative total budget exceeded: ...`; the two budgets are checked independently, so both lines may appear |
| How to disable | Remove budget/total_budget from the [cost] section of config.toml, or set them to 0 |

---

## 3. Outputs Outside Conversation Turns

| Output | Source | Trigger |
|---|---|---|
| Welcome banner `Mini-Code-Agent vX.X.X` | `terminal.py` `show_welcome` | At startup |
| `context: loaded <filename>` | `app.py` startup | When the project instruction file (AGENT.md/CLAUDE.md) is injected successfully |
| `Loaded N hook rule(s) from config` | `app.py` startup | When config.toml contains `[[hooks]]` rules |
| `Loaded N event listener(s): xxx` | `app.py` startup | When listener_dirs contains *.py plugins |
| `Loaded N plugin(s): xxx` | `app.py` startup | When plugin_dirs contains *.py plugins or packages with the `mini_agent.plugins` entry point are installed (P83); use `/plugins` for details |
| `[sandbox] ...` sandbox status hint | `app.py` startup | Only when sandbox=true and the backend is genuinely unavailable (e.g. Linux with neither bwrap nor unshare); no longer printed for Windows non-admin (the no-file-protection limitation is documented in the config guide only); not shown when the backend is active |
| `MCP: xxx connected (N tools)` | `app.py` startup | When an MCP server connects successfully |
| `Cleaned N stale session(s)` | `app.py` startup | When stale sessions are auto-cleaned |
| `Cleaned N stale worktree(s)` | `app.py` startup | When stale worktrees are auto-cleaned |
| Restore prompt `A session that did not shut down cleanly was detected...` | `app.py` `_maybe_restore_session` | When a crashed session is detected at startup |
| Slash command output | Strings returned by each handler in `builtin_commands.py`; plain text is printed as-is by default, output carrying the `MARKDOWN_RESULT` sentinel (spawn reports) goes through Markdown rendering, inline code (filenames / agent ids) in bright orange | When `/xxx` is entered |
| SubAgent progress board | `ui/board.py` `SubAgentBoard` Rich Live Table | During `/spawn wait` or `/team` |
| Multi-agent result overview table + `Report i/N` sections + deliverable file lines | `builtin_commands.py` `_format_agent_results_overview` / `_extract_deliverables` | When `/spawn wait` receives multiple results |
| Worker pane output (task header / tool lines / streaming answer / linger countdown) | `core/worker.py` direct stdout printing | Inside the pane of `/spawn --pane` |
| `Background agent xxx finished — result will be delivered to the conversation next turn` | `app.py` subscriber of `SubAgentCompleteEvent` (B4) | When a background agent spawned via `spawn_agents background=true` completes; the result itself is injected into the conversation via mailbox on the next iteration |
| Permission confirmation dialog | `terminal.py` `confirm` | When a dangerous command / path outside the project / a `[[hooks]]` confirm rule is hit |
| Thinking reasoning process (dim italic) | `terminal.py` `feed_thinking` | When reasoning models (DeepSeek R1, o1/o3) output reasoning_content |
| `Goodbye!` | `app.py` `run()` finally | On normal exit |
| `Interrupted.` | `app.py` `_handle_turn` except | On Ctrl+C / double-Esc interrupt |

---

## 4. Quick Configuration Reference

| Desired effect | Action |
|---|---|
| **See the Agent's internal workings** | `/trace on` |
| **Hide internals and only see results** | `/trace off` (default) |
| **See usage explanations before tool calls** | `/explain on` |
| **Turn off tool usage explanations** | `/explain off` (default) |
| **Enable audit logging to disk** | `/audit on` (no visible terminal output; written to `~/.mini-agent/audit.jsonl`) |
| **Verify audit log integrity** | `/audit verify` |
| **Switch color theme** | `/theme dark` / `/theme light` / `/theme default` |
| **View loaded plugin details** | `/plugins` (expanded version of the startup line `Loaded N plugin(s)`: tools/commands/skills registered by each plugin) |
| **Disable a plugin (remove it from the startup line)** | Set top-level `disabled_plugins = ["<name>"]` in config.toml, or move the file out of the plugin_dirs directory |
| **View all commands** | `/help` |

---

## 5. Output Layer Architecture

```
user input  ─→  app.py _handle_turn
                │
                ├─→ agent_loop.run()
                │     │
                │     ├─→ _think()  ─→ on_thinking_delta          ─→ feed_thinking (⑧)
                │     │               on_stream_start/delta/end   ─→ StreamRenderer (⑨)
                │     │               on_tool_call_assembling     ─→ console.print (②)
                │     │
                │     ├─→ _act()   ─→ on_tool_start              ─→ show_tool_call (⑤)
                │     │               tool.execute()
                │     │               on_tool_end                 ─→ show_tool_result (⑥⑦)
                │     │
                │     └─→ EventBus.emit()  ─→ TraceRenderer (③)
                │                           ─→ TeachRenderer (④)
                │                           ─→ AuditLogger (no visible output)
                │
                └─→ show_file_changes (⑩) → show_info("tokens: ...") (⑪) → budget_warning (⑫)
```


**Core principle**: agent_loop never prints directly — all output reaches the terminal indirectly via **callbacks** (on_xxx) or **EventBus subscribers**. This means any output can be turned off by setting the callback to None or detaching the subscriber, without modifying agent_loop code.

---

## Appendix: Terminal Environment Differences

Output and input behavior differs across terminals (Windows Terminal / CMD / PowerShell / Git Bash / macOS / Linux). For how to open each terminal on each OS, compatibility levels, and troubleshooting, see [terminal-guide.md](terminal-guide.md).
