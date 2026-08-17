# 命令参考（Slash Commands Guide）

全部 22 个可见命令的完整语法、参数与示例。斜杠命令在本地执行、零 token 消耗（`/compact`、`/team` 等会触发 LLM 调用的除外，均已标注）。输入 `/` 弹出按字母排序的下拉补全菜单。

> 各行输出的来源与开关见 output-guide.md；配置项见 config-guide.md。

---

## 会话与状态

### /status
显示会话状态。无参数。
输出：模型、Provider、平台、轮数、token 用量、成本/预算、上下文占用、消息数、会话 ID、项目目录。

### /clear
清空对话历史（system prompt 与记忆注入保留）。无参数。

### /compact
手动压缩对话历史（触发三级压缩级联）。无参数。**会调用 LLM**（摘要策略时）。

### /session — 会话管理
```
/session save              # 保存当前会话
/session list              # 列出已保存会话（最新在前）
/session list --tag <name> # 按标签过滤已保存会话
/session load <id>         # 加载指定会话（id 可用 list 里的前缀）
/session delete <id>       # 删除指定会话
/session tag <name>        # 给当前会话添加标签
/session untag <name>      # 移除当前会话标签
/session tags              # 查看当前会话所有标签
```
无参数时显示用法。标签可用于分类会话（如 `#bug-fix`、`#refactor`），列出时带 `--tag` 按标签过滤。会话存 `~/.mini-agent/sessions/`，超过 `session_cleanup_days`（默认 30 天）的已正常关闭会话启动时自动清理。

### /undo [N]
回滚最近 N 轮（默认 1）——**对话与文件双回滚**（文件快照仅保留最近 5 轮；bash 命令修改的文件无法恢复）。
```
/undo        # 回滚 1 轮
/undo 3      # 回滚 3 轮
```

### /fork [N]
把当前对话深拷贝为新会话分支（可先回滚 N 轮再分叉）。
```
/fork        # 从当前状态分叉
/fork 2      # 回滚 2 轮后分叉
```

### /exit（别名 /quit）
退出。也可直接输入 `exit` / `quit`。

---

## 模型与成本

### /model [name]
无参数：显示当前模型、可用 Provider 列表（`openai`/`anthropic`/`openai-responses`）与可切换档案。带参数：热切换到命名档案（档案通过环境变量 `MINI_AGENT_MODELS` + `MODEL_<NAME>_*` 定义，见 config-guide）。
```
/model            # 查看当前模型 + 可用 Provider + 档案
/model smart      # 切换到 smart 档案
```
注意：`/model` 切换的是模型名和 API key 等参数，不切换 provider。要从 Chat Completions 切换到 Responses API（o1/o3），需在 config.toml 里改 `provider = "openai-responses"`，重启生效。

### /cost [turns|reset]
```
/cost             # 成本仪表盘：本会话分模型明细 + 累计总账 + 预算进度
/cost turns       # 逐轮 token/成本明细
/cost reset       # 清零累计总账（会话内数据不受影响）
```
需在 `[cost.pricing.<模型名>]` 配置单价，否则金额恒为 0。

---

## SubAgent 与多 Agent

### /spawn — SubAgent 派发（本节最复杂的命令）

**派发**：
```
/spawn <task>                     # 后台派发单个 SubAgent，立即返回
/spawn -p <task1> | <task2>       # 并行派发多个（| 分隔）
/spawn --isolated <task>          # 在独立 git worktree 中运行（文件隔离）
/spawn --type <t> <task>          # 指定类型：explore/plan/worker(默认)/verify
/spawn --pane <task>              # 在可见终端窗格运行（独立进程，实时观看）
/spawn --wait <task>              # 派发+进度面板+结果一条命令完成
/spawn --pane --wait <task>       # 组合：弹窗格 + 阻塞等结果
```

**收集与管理**：
```
/spawn list                       # 列出活跃 SubAgent（id + 阶段）
/spawn wait                       # 等待全部完成（多结果显示总览表+编号分节）
/spawn wait <id>                  # 等待指定 agent
/spawn cancel [id]                # 取消指定/全部
```

参数说明：
| 参数 | 说明 |
|---|---|
| `--pane` | 需要 tmux 会话、Windows Terminal 会话（分屏）或装有 wt.exe 的任意终端（降级为共享窗口 mini-agents 的新标签页）。无可用后端时明确报错 |
| `--wait` | 阻塞至完成（上限 900 秒），期间显示进度面板；不加则用 `/spawn wait` 二段式收集 |
| `--isolated` | 每个 agent 独占 worktree，结果附合并提示 |
| `--type` | explore/plan/verify 为只读工具集，worker 全工具 |

注意事项：
- 需要相互通信（send_message/wait_message）的任务必须**一次 `-p` 派发**，分次派发是串行的
- pane worker 的报告完整回传主窗口；提到的交付文件以亮橙色列出
- wait 超时（900s）后完成的结果成孤儿，可手动查 `~/.mini-agent/workers/<id>.result.json`
- 任务写得越具体越省 token——模糊的"分析整个项目"级任务实测消耗 0.7–1.8M tokens

### /team <task> [--isolated] [--coordinator]
LLM 自动分解任务 → 按角色匹配团队成员 → 并行执行 → 汇总报告。**会调用 LLM**。
```
/team 给项目补一套冒烟测试
/team --coordinator --isolated 重构日志模块    # 纯调度 Planner + worktree 隔离
```

### /plan [on|off]
切换只读计划模式（写类工具禁用）。无参数显示当前状态。

---

## 观测与调试

### /trace [on|off]
实时显示 Agent 内部状态：ReAct 阶段切换、权限判定（含命中规则）、工具耗时、LLM token 元信息。

### /explain [on|off]
教学模式：每次工具调用前打印教学面板（为什么用这个工具/参数含义）。

### /audit [on|off|verify]
```
/audit on        # 开始记录所有工具调用到 ~/.mini-agent/audit.jsonl（哈希链）
/audit off       # 停止
/audit verify    # 校验哈希链完整性（检测篡改）
```

### /tools
列出所有已注册工具（内置 + MCP，含 dispatch 模式的搜索提示）。无参数。

---

## 记忆与任务

### /memory — 跨会话记忆
```
/memory                      # 查看全部记忆
/memory add <内容>           # 手动添加
/memory delete <内容>        # 按内容删除
/memory consolidate          # LLM 语义合并相关记忆（会调用 LLM）
/memory export [目录]        # 导出为 .md 文件（YAML 前置元数据 + MEMORY.md 索引）
/memory import <目录>        # 从 .md 目录导入（按 id 去重，按 scope 还原作用域）
```

### /todo — 持久化任务清单（重启不丢）
```
/todo                        # 列出任务
/todo add <描述>             # 添加
/todo add <描述> --after <id>  # 添加并声明依赖（可逗号分隔多个）
/todo start <id>             # 标记进行中（被依赖阻塞时会拒绝）
/todo done <id>              # 标记完成
/todo fail <id>              # 标记失败
/todo delete <id>            # 删除
/todo clear                  # 清空
```
id 可用前缀匹配；歧义前缀（匹配多个任务）会报错并列出所有匹配项。列表显示的 ID 已自动截取最短唯一前缀。

---

## 录制与回放

### /record — 录制工具调用序列
```
/record start <name>         # 开始录制（之后的工具调用被记录）
/record stop                 # 停止并保存到 ~/.mini-agent/recordings/
/record cancel               # 放弃本次录制
/record list                 # 列出已保存录制
/record delete <name>        # 删除
```
注意：SubAgent 内部的工具调用不录制；录制状态在内存，崩溃丢失未 stop 的录制。

### /replay <name> [var=value ...]
零 LLM 调用重放录制的工具序列，支持 `{{变量}}` 模板替换：
```
/replay deploy-check
/replay scaffold name=my_module     # 填充录制中的 {{name}}
```
缺变量时会列出需要的全部变量名。回放结果不进对话历史（LLM 不知道回放改了什么）。

---

## 扩展

### /skill — 技能包管理
```
/skill                       # 列出全部技能包及激活状态
/skill activate <name>       # 激活（prompt 注入 system prompt）
/skill deactivate <name>     # 停用（精确移除）
/skill install <path_or_url> # 安装：本地目录复制 / git URL 克隆
/skill uninstall <name>      # 卸载
/skill reload                # 热重载技能目录（改完 SKILL.md 不用重启）
```

### /theme [default|dark|light]
切换配色主题并持久化到 `~/.mini-agent/.theme`。无参数显示当前主题。

### /help
列出全部命令（字母排序）。

---

## 通用行为

- 命令在本地执行，输错命令名会提示全部可用命令
- 命令 handler 抛异常不会杀死会话（显示 "Command failed: ..." 后继续）
- 报告类输出（/spawn wait）走 Markdown 渲染（表格/标题/亮橙文件名），状态类输出（/status /cost）保持纯文本对齐版式
- 远程浏览器模式（`--remote`）下所有命令同样可用
