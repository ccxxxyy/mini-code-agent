# 终端使用指南——各系统各终端的打开方法与兼容性

> English version: [en/terminal-guide.md](en/terminal-guide.md)

Mini-Code-Agent 是终端工具，体验因终端而异。本文档说明各系统下有哪些终端、怎么打开、各自的兼容等级和已知问题。

## 启动方式汇总

根据安装方式不同，有多种启动命令：

| 安装方式 | 启动命令 | 说明 |
|----------|----------|------|
| `pip install mini-code-agent` | `mini` 或 `mini-agent` | 全局可用，任意目录启动 |
| 源码 + uv | `uv run mini` 或 `uv run mini-agent` | 在项目目录内运行 |
| 源码 + python | `python -m mini_agent` | 直接用 Python 解释器运行 |

附加参数（所有方式通用）：
```bash
mini --model deepseek-chat           # 指定模型
mini --remote                        # 远程/浏览器模式
mini --remote --port 9000            # 自定义端口
mini --remote --remote-token secret  # 带认证
mini --help                          # 查看全部参数
```

以下各终端的示例统一用 `mini`，源码安装请替换为 `uv run mini`。

---

## 一、Windows

### 1. Windows Terminal

**兼容等级**：完美——全功能可用。

**打开方法**：
- 开始菜单搜索 "Terminal" 或 "终端"
- 或 Win+X → "终端"（Windows 11 默认）
- 或右键任意文件夹 → "在终端中打开"

```powershell
mini                           # pip 安装后
mini-agent                     # 同上（别名）
uv run mini                    # 源码安装（在项目目录内）
python -m mini_agent           # 直接用 Python
```

### 2. PowerShell

**兼容等级**：完美——全功能可用。

**打开方法**：
- Win+R → 输入 `powershell` → 回车
- 或开始菜单搜索 "PowerShell"

```powershell
mini                           # pip 安装后
uv run mini                    # 源码安装
python -m mini_agent           # 直接用 Python
```

### 3. CMD（命令提示符）

**兼容等级**：完美——全功能可用（程序内置 UTF-8 加固）。

**打开方法**：
- Win+R → 输入 `cmd` → 回车
- 或开始菜单搜索 "cmd"

```cmd
mini                           &:: pip 安装后
uv run mini                    &:: 源码安装
python -m mini_agent           &:: 直接用 Python
```

**已知情况与优化**：
- 中文 Windows 的 CMD 默认代码页 936（GBK）——程序已内置 UTF-8 加固，特殊字符正常显示
- 如仍遇到显示问题，运行 `chcp 65001` 切换到 UTF-8 后再启动 mini
- 想永久改善：换用 Windows Terminal

### 4. Git Bash（MINGW64/mintty）

**兼容等级**：降级可用——能正常对话，但**无补全菜单、无底部工具栏、无 Esc 快捷键（双 Esc 中断/单 Esc 面板转后台/空提示符 Esc 重新附着）、无 shift+tab 模式循环**（mintty 的 stdin 是管道，prompt_toolkit 驱动不了）。

**打开方法**：
- 安装 Git for Windows 后，开始菜单搜 "Git Bash"
- 或右键文件夹 → "Git Bash Here"

```bash
mini                    # 朴素输入模式（自动降级）
winpty mini             # 推荐：winpty 桥接出真控制台，恢复全功能
winpty uv run mini      # 源码安装 + winpty
```

**已知问题**：
- 直接 `mini` 会进入朴素输入模式（只有 `> ` 提示符，无补全）——这是自动降级，不是故障
- **用 `winpty mini` 可获得和 CMD 相同的完整体验**（winpty 是 Git Bash 自带的）

### 5. VS Code / JetBrains 内置终端

**兼容等级**：完美——等同于宿主终端（Windows Terminal / CMD 等）。

**打开方法**：Ctrl+\`（VS Code）或 Alt+F12（JetBrains）。

### Windows 终端兼容性总表

| 终端 | 补全菜单 | 主题色 | 双 Esc | emoji | 推荐度 |
|---|---|---|---|---|---|
| Windows Terminal | ✅ | ✅ 全彩 | ✅ | ✅ | ⭐⭐⭐ |
| PowerShell | ✅ | ✅ | ✅ | ✅ | ⭐⭐ |
| CMD | ✅ | ✅（Rich 自动降级） | ✅ | Unicode 符号（需 UTF-8 代码页） | ⭐⭐ |
| Git Bash 直接运行 | ❌ 朴素输入 | ✅ | ❌ | ✅ | ⭐ |
| Git Bash + winpty | ✅ | ✅ | ✅ | ✅ | ⭐⭐ |

---

## 二、macOS

### 1. Terminal.app（系统自带）

**兼容等级**：完美。

**打开方法**：
- Cmd+Space（聚焦搜索）→ 输入 "Terminal" 或 "终端" → 回车
- 或 启动台 → 其他 → 终端
- 或 访达 → 应用程序 → 实用工具 → 终端

```bash
mini                           # pip 安装后
mini-agent                     # 同上（别名）
uv run mini                    # 源码安装
python3 -m mini_agent          # macOS 用 python3
pip3 install mini-code-agent   # macOS pip 安装用 pip3
```

### 2. iTerm2（第三方，推荐）

**兼容等级**：完美。

**打开方法**：
- 从 https://iterm2.com 下载安装，或 `brew install --cask iterm2`
- Cmd+Space → "iTerm"

### 3. VS Code 内置终端

**兼容等级**：完美。

**打开方法**：VS Code 中 Ctrl+`（反引号）或菜单 Terminal → New Terminal。

---

## 三、Linux

### 1. 发行版自带终端

**兼容等级**：完美（GNOME Terminal / Konsole / xfce4-terminal 等均可）。

**打开方法**：
- Ubuntu/GNOME：Ctrl+Alt+T，或活动搜索 "Terminal"
- KDE：应用菜单 → Konsole
- 通用：应用列表搜 "terminal"

```bash
mini                           # pip 安装后
mini-agent                     # 同上（别名）
uv run mini                    # 源码安装
python3 -m mini_agent          # Linux 通常用 python3
pip install mini-code-agent    # pip 安装（建议用 pipx 或虚拟环境）
```

### 2. SSH 远程会话

**兼容等级**：完美——SSH 分配伪终端（pty），所有功能正常。

```bash
ssh user@host              # 先 SSH 登录
mini                       # 在远程 shell 里启动

ssh -t user@host mini      # 一步到位（-t 强制分配 pty）
```

注意：`ssh user@host mini`（不带 `-t`）不分配 pty，会进入朴素输入模式。

远程服务器也可用浏览器模式替代 SSH：
```bash
ssh user@host
mini --remote --host 0.0.0.0   # 在远程启动，本地浏览器打开 http://远程IP:8765
```

### 3. tmux / screen

**兼容等级**：完美——终端复用器完整转发所有能力。

```bash
tmux                       # 先进入 tmux
mini                       # 在 tmux 内启动，/spawn --pane 可用（split-window 分屏）

screen                     # 或用 screen
mini
```

---

## 四、跨平台：VS Code / JetBrains 内置终端

**兼容等级**：完美——IDE 内置终端本质是宿主系统的终端模拟器，全功能可用。

**打开方法**：
- VS Code：Ctrl+\`（反引号）或菜单 Terminal → New Terminal
- JetBrains（PyCharm/IntelliJ）：Alt+F12 或底部 Terminal 标签

`/spawn --pane` 在 IDE 终端内需要额外条件：Windows 需安装 wt.exe（会弹出独立 Windows Terminal 窗口）；macOS/Linux 需在 tmux 内运行。

---

## 五、远程/浏览器模式

不依赖终端能力——通过 `--remote` 启动 WebSocket 服务器，在任意浏览器中使用。

```bash
mini --remote                    # 启动，浏览器打开 http://localhost:8765
mini --remote --port 9000        # 自定义端口
mini --remote --remote-token x   # 带认证
```

适用场景：远程服务器（无 GUI）、iPad/手机、或任何终端体验不佳的环境。详见 config-guide.md 和 README.md 的 Remote 章节。

---

## 六、`/spawn --pane` 终端窗格要求

`/spawn --pane` 在独立终端窗格中运行子代理，需要特定终端支持：

| 环境 | 行为 |
|------|------|
| tmux 会话内 | `tmux split-window` 分屏（不抢焦点） |
| Windows Terminal 会话内 | `wt split-pane` 分屏 |
| 装了 wt.exe 但不在 WT 会话内 | 降级为 `wt -w mini-agents new-tab`（弹共享窗口标签页） |
| 以上都不可用 | 报错，需改用进程内 `/spawn`（无 `--pane`） |

