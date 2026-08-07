# 终端输出来源与配置指南

本文档说明 Mini-Code-Agent 在一轮对话中每一行终端输出的**来源组件**、**触发条件**和**开关方法**。

---

## 一、一轮对话的完整输出流程

用户输入一条消息后，终端依次可能出现以下输出（按时间顺序）：

```
> 帮我把 a.txt 里的 hello 改成 goodbye     ← ① 用户输入（prompt_toolkit）

  ╭─ edit_file ...                          ← ② Streaming 工具组装提示
  trace [12:03:01] iter 1 idle -> thinking  ← ③ Trace 行（/trace on 时）
  trace [12:03:01] llm  request 2 msgs      ← ③
╭── Teach: edit_file ──────────────────╮    ← ④ 教学面板（/explain on 时）
│ Why this tool: ...                   │
╰──────────────────────────────────────╯
  trace [12:03:02] llm  response 1082 tokens ← ③
  ╭─ edit_file ...                          ← ② 或 ⑤ 工具调用行
  │  file_path=a.txt, old_text=hello...     ← ⑤ 参数摘要行
  trace [12:03:02] perm path a.txt -> GRANTED ← ③
  trace [12:03:02] tool edit_file start     ← ③
  trace [12:03:02] tool edit_file done 1ms  ← ③
  ╰─ ✓ 1 lines, 42 chars                   ← ⑥ 工具结果行
  - hello world                             ← ⑦ Diff 预览（edit_file 专属）
  + goodbye world                           ← ⑦

已把 a.txt 中的 hello 改为 goodbye。       ← ⑧ LLM 流式回复（Markdown 渲染）

  files changed this turn:                  ← ⑩ 文件变更汇总
    ~ a.txt                                 ← ⑩

  tokens: 3307 this turn / 3307 total       ← ⑨ Token 统计行
```

---

## 二、每个输出的来源与开关

### ① 用户输入提示符 `> `

| 项 | 说明 |
|---|---|
| 来源 | `ui/input_handler.py` `create_prompt_session` → prompt_toolkit `message="> "` |
| 颜色 | 跟随主题 `theme.primary`（`/theme dark` 可换色） |
| 关闭方法 | 不可关闭（关了没法输入） |

### ② Streaming 工具组装提示 `╭─ tool_name ...`

| 项 | 说明 |
|---|---|
| 来源 | `app.py` `_on_tool_assembling` 回调 ← `agent_loop.py` `on_tool_call_assembling` |
| 触发 | LLM 流式返回 tool_call_delta 且携带工具名时（首次出现） |
| 作用 | 让用户在 JSON 参数组装期间就知道 LLM 在调哪个工具 |
| 关闭方法 | `app.py` 中删除 `self.agent_loop.on_tool_call_assembling = _on_tool_assembling` 这行 |

### ③ Trace 行 `trace [HH:MM:SS] ...`

| 项 | 说明 |
|---|---|
| 来源 | `ui/trace.py` `TraceRenderer`（EventBus 订阅者） |
| 触发 | `/trace on` 开启后，每个事件（阶段切换/权限/工具/LLM/轮次）打一行 |
| 包含 | 阶段切换（iter）、权限判定（perm）、工具生命周期（tool start/done）、LLM 请求/响应（llm）、轮次汇总（turn） |
| 开关 | `/trace on` 开启，`/trace off` 关闭，`/trace` 切换 |
| 关闭后效果 | 零输出（handler 内 `if not self.enabled: return` 短路） |

### ④ 工具使用说明面板 `Teach: tool_name`

| 项 | 说明 |
|---|---|
| 来源 | `ui/teach.py` `TeachRenderer`（EventBus 订阅者） |
| 触发 | `/explain on` 开启后，每次工具调用前打印一个说明面板 |
| 包含 | 为什么选这个工具 / 实际传入的参数 / 各参数的含义——帮助理解 Agent 决策过程 |
| 开关 | `/explain on` 开启，`/explain off` 关闭 |
| 用途 | 想知道"Agent 为什么调这个工具而不是那个"时开启；日常使用关闭（默认关） |

### ⑤ 工具调用行 `╭─ tool_name args...`

| 项 | 说明 |
|---|---|
| 来源 | `ui/terminal.py` `show_tool_call`（被 `agent_loop.on_tool_start` 回调触发） |
| 触发 | 每次工具执行开始时 |
| 内容 | `╭─ 工具名 参数预览`（参数截断 60 字符） |
| 关闭方法 | `app.py` 中将 `self.agent_loop.on_tool_start` 设为 `None` |
| 注意 | 如果 ② 已显示过工具名，⑤ 只打参数摘要行 `│ args...` 不重复 `╭─` |

### ⑥ 工具结果行 `╰─ ✓ N lines, M chars`

| 项 | 说明 |
|---|---|
| 来源 | `ui/terminal.py` `show_tool_result`（被 `agent_loop.on_tool_end` 回调触发） |
| 触发 | 每次工具执行完成时 |
| 成功 | `╰─ ✓ 行数, 字符数`（绿色 ✓） |
| 失败 | `╰─ ✗ 错误预览`（红色 ✗，截断 300 字符） |
| 关闭方法 | `app.py` 中将 `self.agent_loop.on_tool_end` 设为 `None` |

### ⑦ Diff 预览（edit_file 专属）

| 项 | 说明 |
|---|---|
| 来源 | `ui/terminal.py` `_render_diff`（在 `show_tool_result` 内，检测 `metadata["diff"]`） |
| 触发 | edit_file 成功且 metadata 含 diff 时 |
| 内容 | 删除行：红色文字 + 深红整行背景 `#3d0000`；新增行：绿色文字 + 深绿整行背景 `#002d00` |
| 关闭方法 | `edit_file.py` 中删除生成 diff 的代码块（约 10 行），或 `terminal.py` `_render_diff` 里 `return` 提前退出 |

### ⑧ LLM 流式回复（Markdown 渲染）

| 项 | 说明 |
|---|---|
| 来源 | `ui/renderer.py` `StreamRenderer`（Rich Live + Markdown） |
| 触发 | LLM 返回 text delta 时（非 tool_call 的文本输出） |
| 机制 | `on_stream_start` → Live 启动；`on_stream_delta` → 逐段提交式渲染；`on_stream_end` → Live 关闭 |
| 关闭方法 | 不可关闭（关了就看不到 LLM 的回答） |

### ⑨ Token 统计行

| 项 | 说明 |
|---|---|
| 来源 | `app.py` `_handle_turn` → `self.terminal.show_info(f"tokens: {turn} this turn / {total} total")` |
| 触发 | 每轮对话完成后（agent_loop.run 返回后） |
| 内容 | 配置价格后带金额 `tokens: 6373 this turn (¥0.0089) / 13215 total (¥0.0182)` |
| 关闭方法 | `app.py` `_handle_turn` 中注释掉 `self.terminal.show_info(...)` 那行 |

### ⑩ 文件变更汇总

| 项 | 说明 |
|---|---|
| 来源 | `ui/terminal.py` `show_file_changes`（`app.py` `_handle_turn` 在 token 统计前调用） |
| 触发 | 本轮有 write_file/edit_file/delete_file 成功执行时（bash 的文件变更不跟踪） |
| 内容 | `files changed this turn:` + 每个文件一行（`+ 路径` 绿=新建，`~ 路径` 黄=修改，`- 路径` 红=删除） |
| 关闭方法 | `app.py` `_handle_turn` 中删除 `show_file_changes` 调用行 |

### ⑪ 预算警告行

| 项 | 说明 |
|---|---|
| 来源 | `app.py` `_show_budget_warning`（每轮结束、token 统计行之后） |
| 触发 | 会话预算（budget）或累计总预算（total_budget）已用 ≥80% |
| 内容 | ≥80% 黄色 `会话预算警告: ¥4.12 / ¥5.00 (82%)`；≥100% 红色 `⚠ 累计总预算超支: ...`；两种预算独立检查可能各出一条 |
| 关闭方法 | config.toml [cost] 段删掉 budget/total_budget 或设 0 |

---

## 三、非对话轮次的输出

| 输出 | 来源 | 触发 |
|---|---|---|
| 欢迎标题 `Mini-Code-Agent vX.X.X` | `terminal.py` `show_welcome` | 启动时 |
| 恢复提示 `检测到未正常关闭的会话...` | `app.py` `_maybe_restore_session` | 启动时检测到崩溃会话 |
| 斜杠命令输出 | `builtin_commands.py` 各 handler 返回的字符串 | 输入 `/xxx` 时 |
| SubAgent 进度面板 | `ui/board.py` `SubAgentBoard` Rich Live Table | `/spawn wait` 或 `/team` 期间 |
| 权限确认弹窗 | `terminal.py` `confirm` | 危险命令/项目外路径 |
| `Goodbye!` | `app.py` `run()` finally | 正常退出时 |
| `Interrupted.` | `app.py` `_handle_turn` except | Ctrl+C / 双 Esc 中断时 |

---

## 四、快速配置参考

| 想要的效果 | 操作 |
|---|---|
| **看到 Agent 内部工作过程** | `/trace on` |
| **关闭内部过程只看结果** | `/trace off`（默认） |
| **看到工具调用前的使用说明** | `/explain on` |
| **关闭工具使用说明** | `/explain off`（默认） |
| **开启审计日志落盘** | `/audit on`（终端无可见输出，写入 `~/.mini-agent/audit.jsonl`） |
| **验证审计日志完整性** | `/audit verify` |
| **切换颜色主题** | `/theme dark` / `/theme light` / `/theme default` |
| **查看所有命令** | `/help` |

---

## 五、输出层架构

```
用户输入  ─→  app.py _handle_turn
                │
                ├─→ agent_loop.run()
                │     │
                │     ├─→ _think()  ─→ on_stream_start/delta/end ─→ StreamRenderer (⑧)
                │     │               on_tool_call_assembling     ─→ console.print (②)
                │     │
                │     ├─→ _act()   ─→ on_tool_start              ─→ show_tool_call (⑤)
                │     │               tool.execute()
                │     │               on_tool_end                 ─→ show_tool_result (⑥⑦)
                │     │
                │     └─→ EventBus.emit()  ─→ TraceRenderer (③)
                │                           ─→ TeachRenderer (④)
                │                           ─→ AuditLogger (无可见输出)
                │
                └─→ show_info("tokens: ...") (⑨)
```

**核心原则**：agent_loop 不直接 print——所有输出通过**回调**（on_xxx）或**EventBus 订阅者**间接到达终端。这意味着任何输出都可以通过设回调为 None 或 detach 订阅者来关闭，不需要改 agent_loop 代码。
