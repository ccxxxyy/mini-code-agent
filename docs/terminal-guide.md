# 终端使用指南——各系统各终端的打开方法与兼容性

Mini-Code-Agent 是终端工具，体验因终端而异。本文档说明各系统下有哪些终端、怎么打开、各自的兼容等级和已知问题。

---

## 一、Windows

### 1. Windows Terminal

**兼容等级**：完美——全功能（补全菜单/主题色/emoji/双 Esc/流式渲染）。

**打开方法**：
- 开始菜单搜索 "Terminal" 或 "终端"
- 或 Win+X → "终端"（Windows 11 默认）
- 或右键任意文件夹 → "在终端中打开"

```
mini        ← 直接运行
```

### 2. PowerShell

**兼容等级**：良好——全功能可用，默认编码通常正常。

**打开方法**：
- Win+R → 输入 `powershell` → 回车
- 或开始菜单搜索 "PowerShell"

```powershell
mini
```

### 3. CMD（命令提示符）

**兼容等级**：可用——功能齐全。

**打开方法**：
- Win+R → 输入 `cmd` → 回车
- 或开始菜单搜索 "cmd"

```cmd
mini
```

**已知情况与优化**：
- 中文 Windows 的 CMD 默认代码页 936（GBK）——程序已内置 UTF-8 加固，特殊字符正常显示
- 如仍遇到显示问题，运行 `chcp 65001` 切换到 UTF-8 后再启动 mini
- 想永久改善：换用 Windows Terminal

### 4. Git Bash（MINGW64/mintty）

**兼容等级**：降级可用——能正常对话，但**无补全菜单、无底部工具栏、无双 Esc**（mintty 的 stdin 是管道，prompt_toolkit 驱动不了）。

**打开方法**：
- 安装 Git for Windows 后，开始菜单搜 "Git Bash"
- 或右键文件夹 → "Git Bash Here"

```bash
mini            # 朴素输入模式（自动降级）
winpty mini     # 推荐：winpty 桥接出真控制台，恢复全功能
```

**已知问题**：
- 直接 `mini` 会进入朴素输入模式（只有 `> ` 提示符，无补全）——这是自动降级，不是故障
- **用 `winpty mini` 可获得和 CMD 相同的完整体验**（winpty 是 Git Bash 自带的）

### Windows 终端兼容性总表

| 终端 | 补全菜单 | 主题色 | 双 Esc | emoji | 推荐度 |
|---|---|---|---|---|---|
| Windows Terminal | ✅ | ✅ 全彩 | ✅ | ✅ | ⭐⭐⭐ |
| PowerShell | ✅ | ✅ | ✅ | ✅ | ⭐⭐ |
| CMD | ✅ | ✅（旧机器 16 色近似） | ✅ | 视字体（有 ASCII 降级） | ⭐⭐ |
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
mini
```

### 2. iTerm2（第三方，推荐）

**兼容等级**：完美——分屏/搜索/回放等增强功能。

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
mini
```

### 2. SSH 远程会话

**兼容等级**：完美——SSH 分配伪终端（pty），所有功能正常。

```bash
ssh user@host
mini
```

注意：`ssh user@host mini`（不进 shell 直接跑命令）不分配 pty，会进入朴素输入模式；用 `ssh -t user@host mini` 强制分配。

### 3. tmux / screen

**兼容等级**：完美——终端复用器完整转发所有能力。


