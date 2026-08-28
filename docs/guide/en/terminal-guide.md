# Terminal Usage Guide — How to Open Each Terminal on Each OS, and Compatibility

> 中文版 (Chinese version): [../terminal-guide.md](../terminal-guide.md)

Mini-Code-Agent is a terminal tool, and the experience varies by terminal. This document explains which terminals are available on each system, how to open them, their compatibility levels, and known issues.

## Launch Methods Overview

Depending on how you installed, there are several launch commands:

| Install method | Launch command | Notes |
|----------|----------|------|
| `pip install mini-code-agent` | `mini` or `mini-agent` | Globally available, launch from any directory |
| Source + uv | `uv run mini` or `uv run mini-agent` | Run inside the project directory |
| Source + python | `python -m mini_agent` | Run directly with the Python interpreter |

Additional arguments (common to all methods):
```bash
mini --model deepseek-chat           # Specify model
mini --remote                        # Remote/browser mode
mini --remote --port 9000            # Custom port
mini --remote --remote-token secret  # With authentication
mini --help                          # View all arguments
```

The examples for each terminal below all use `mini`; for source installs, replace with `uv run mini`.

---

## 1. Windows

### 1. Windows Terminal

**Compatibility level**: Perfect — all features available.

**How to open**:
- Search "Terminal" in the Start menu
- Or Win+X → "Terminal" (default on Windows 11)
- Or right-click any folder → "Open in Terminal"

```powershell
mini                           # After pip install
mini-agent                     # Same as above (alias)
uv run mini                    # Source install (inside project directory)
python -m mini_agent           # Directly with Python
```

### 2. PowerShell

**Compatibility level**: Perfect — all features available.

**How to open**:
- Win+R → type `powershell` → Enter
- Or search "PowerShell" in the Start menu

```powershell
mini                           # After pip install
uv run mini                    # Source install
python -m mini_agent           # Directly with Python
```

### 3. CMD (Command Prompt)

**Compatibility level**: Perfect — all features available (built-in UTF-8 hardening).

**How to open**:
- Win+R → type `cmd` → Enter
- Or search "cmd" in the Start menu

```cmd
mini                           &:: After pip install
uv run mini                    &:: Source install
python -m mini_agent           &:: Directly with Python
```

**Known behavior and optimizations**:
- On Chinese Windows, CMD defaults to code page 936 (GBK) — the program has built-in UTF-8 hardening, so special characters display correctly
- If you still encounter display issues, run `chcp 65001` to switch to UTF-8 before starting mini
- For a permanent improvement: switch to Windows Terminal

### 4. Git Bash (MINGW64/mintty)

**Compatibility level**: Degraded mode — conversation works normally, but **no completion menu, no bottom toolbar, no Esc shortcuts (double-Esc interrupt / single-Esc board detach / Esc-at-prompt re-attach), no shift+tab mode cycling** (mintty's stdin is a pipe, which prompt_toolkit cannot drive).

**How to open**:
- After installing Git for Windows, search "Git Bash" in the Start menu
- Or right-click a folder → "Git Bash Here"

```bash
mini                    # Plain input mode (automatic fallback)
winpty mini             # Recommended: winpty bridges to a real console, restoring full functionality
winpty uv run mini      # Source install + winpty
```

**Known issues**:
- Running `mini` directly enters plain input mode (only a `> ` prompt, no completion) — this is an automatic fallback, not a malfunction
- **Use `winpty mini` to get the same full experience as CMD** (winpty ships with Git Bash)

### 5. VS Code / JetBrains Built-in Terminal

**Compatibility level**: Perfect — same as the host terminal (Windows Terminal / CMD, etc.).

**How to open**: Ctrl+\` (VS Code) or Alt+F12 (JetBrains).

### Windows Terminal Compatibility Summary

| Terminal | Completion menu | Theme colors | Double Esc | emoji | Recommendation |
|---|---|---|---|---|---|
| Windows Terminal | ✅ | ✅ Full color | ✅ | ✅ | ⭐⭐⭐ |
| PowerShell | ✅ | ✅ | ✅ | ✅ | ⭐⭐ |
| CMD | ✅ | ✅ (Rich auto-fallback) | ✅ | Unicode symbols (requires UTF-8 code page) | ⭐⭐ |
| Git Bash directly | ❌ Plain input | ✅ | ❌ | ✅ | ⭐ |
| Git Bash + winpty | ✅ | ✅ | ✅ | ✅ | ⭐⭐ |

---

## 2. macOS

### 1. Terminal.app (Built into the System)

**Compatibility level**: Perfect.

**How to open**:
- Cmd+Space (Spotlight) → type "Terminal" → Enter
- Or Launchpad → Other → Terminal
- Or Finder → Applications → Utilities → Terminal

```bash
mini                           # After pip install
mini-agent                     # Same as above (alias)
uv run mini                    # Source install
python3 -m mini_agent          # macOS uses python3
pip3 install mini-code-agent   # macOS pip install uses pip3
```

### 2. iTerm2 (Third-Party, Recommended)

**Compatibility level**: Perfect.

**How to open**:
- Download and install from https://iterm2.com, or `brew install --cask iterm2`
- Cmd+Space → "iTerm"

### 3. VS Code Built-in Terminal

**Compatibility level**: Perfect.

**How to open**: In VS Code, Ctrl+` (backtick) or menu Terminal → New Terminal.

---

## 3. Linux

### 1. Distribution Default Terminal

**Compatibility level**: Perfect (GNOME Terminal / Konsole / xfce4-terminal, etc. all work).

**How to open**:
- Ubuntu/GNOME: Ctrl+Alt+T, or search "Terminal" in Activities
- KDE: Application menu → Konsole
- Generic: search "terminal" in the application list

```bash
mini                           # After pip install
mini-agent                     # Same as above (alias)
uv run mini                    # Source install
python3 -m mini_agent          # Linux usually uses python3
pip install mini-code-agent    # pip install (pipx or a virtual environment is recommended)
```

### 2. SSH Remote Sessions

**Compatibility level**: Perfect — SSH allocates a pseudo-terminal (pty), all features work normally.

```bash
ssh user@host              # SSH login first
mini                       # Launch inside the remote shell

ssh -t user@host mini      # One step (-t forces pty allocation)
```

Note: `ssh user@host mini` (without `-t`) does not allocate a pty and will enter plain input mode.

Remote servers can also use browser mode instead of SSH:
```bash
ssh user@host
mini --remote --host 0.0.0.0   # Launch on the remote, open http://REMOTE_IP:8765 in a local browser
```

### 3. tmux / screen

**Compatibility level**: Perfect — terminal multiplexers forward all capabilities completely.

```bash
tmux                       # Enter tmux first
mini                       # Launch inside tmux; /spawn --pane available (split-window panes)

screen                     # Or use screen
mini
```

---

## 4. Cross-Platform: VS Code / JetBrains Built-in Terminal

**Compatibility level**: Perfect — IDE built-in terminals are essentially the host system's terminal emulator, all features available.

**How to open**:
- VS Code: Ctrl+\` (backtick) or menu Terminal → New Terminal
- JetBrains (PyCharm/IntelliJ): Alt+F12 or the bottom Terminal tab

`/spawn --pane` requires extra conditions inside IDE terminals: Windows needs wt.exe installed (a separate Windows Terminal window pops up); macOS/Linux must be running inside tmux.

---

## 5. Remote/Browser Mode

Does not depend on terminal capabilities — start a WebSocket server via `--remote` and use it in any browser.

```bash
mini --remote                    # Launch, open http://localhost:8765 in a browser
mini --remote --port 9000        # Custom port
mini --remote --remote-token x   # With authentication
```

Suitable scenarios: remote servers (no GUI), iPad/phone, or any environment with a poor terminal experience. See config-guide.md and the Remote section of README.md for details.

---

## 6. `/spawn --pane` Terminal Pane Requirements

`/spawn --pane` runs a subagent in a separate terminal pane and requires specific terminal support:

| Environment | Behavior |
|------|------|
| Inside a tmux session | `tmux split-window` split pane (does not steal focus) |
| Inside a Windows Terminal session | `wt split-pane` split pane |
| wt.exe installed but not in a WT session | Falls back to `wt -w mini-agents new-tab` (opens a tab in a shared window) |
| None of the above available | Errors out; use in-process `/spawn` instead (without `--pane`) |
