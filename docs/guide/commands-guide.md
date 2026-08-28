# 命令参考（Slash Commands Guide）

> English version: [en/commands-guide.md](en/commands-guide.md)

全部 27 个可见命令的完整语法、参数与示例。斜杠命令在本地执行、零 token 消耗（`/compact`、`/team` 等会触发 LLM 调用的除外，均已标注）。输入 `/` 弹出按字母排序的下拉补全菜单。

> 各行输出的来源与开关见 output-guide.md；配置项见 config-guide.md。

---

## 一、会话与状态

### /status
显示会话状态。无参数。
输出：模型、Provider、平台、轮数、token 用量、成本/预算、上下文占用、消息数、会话 ID、项目目录。

### /clear
清空对话历史（system prompt 与记忆注入保留）。无参数。
**注意**：/clear 不更换会话 ID——清空后继续对话，自动保存会**覆盖**该会话在盘上的旧历史。想从零开始且保留当前会话的完整历史：用 `/session new`（一条命令：旧会话完整存盘 + 换新 ID 另起）。

### /compact
手动压缩对话历史（触发四级压缩级联：DropToolResults → LLMSummarizeOldest → SummarizeOldest → SlidingWindow）。无参数。**会调用 LLM**（LLM 摘要策略时）。
手动压缩与自动压缩走同一管道——恢复附件（用户请求/已读文件/技能状态）与压缩边界字段一并写入，`/session save` 后这些状态可随会话恢复。

### /session — 会话管理
```
/session save              # 保存当前会话
/session new               # 另起全新会话（当前会话完整存盘，可 load 回来）
/session list              # 列出已保存会话（最新在前，默认只显示最近 20 条）
/session list --page 2     # 翻页：显示第 21~40 条（尾行提示当前页/总页数/下一页）
/session list --all        # 显示全部（不截断，优先于 --page）
/session list --tag <name> # 按标签过滤（可与 --page / --all 组合）
/session load <id>         # 加载指定会话（id 可用 list 里的前缀）
/session delete <id>       # 删除指定会话
/session tag <name>        # 给当前会话添加标签
/session untag <name>      # 移除当前会话标签
/session tags              # 查看当前会话所有标签
```
`load` 恢复完整对话（含工具调用）与 system prompt；若会话经历过压缩（存在压缩边界），一并恢复已读文件清单、用户最近请求与**技能激活状态**（`/skill` 的 `[ACTIVE]` 标记、deactivate 均恢复正常，prompt 不重复注入）。  
无参数时显示用法。标签可用于分类会话（如 `#bug-fix`、`#refactor`），列出时带 `--tag` 按标签过滤。会话存 `~/.mini-agent/sessions/`，超过 `session_cleanup_days`（默认 30 天）的已正常关闭会话启动时自动清理（未正常关闭的不清理——它们是崩溃恢复候选）。

**`/session new` 原理**：对当前会话做三件事——① **完整存盘**：全部消息/工具记录/system prompt/压缩边界原样写入它自己的 JSON 文件，之后新会话用**新 ID**写**另一个文件**，旧文件不会再被碰；② **标记正常关闭**（closed_cleanly=True）：主动离开不是崩溃，不标记的话下次启动会被崩溃检测误判弹恢复；③ **空会话跳过存盘**：一条消息都没有时不落盘（避免空 JSON 垃圾文件），但新会话照样另起。新会话保留 system prompt（指令/记忆注入，与 /clear 语义一致）、继承 model 与 project_dir。返回提示含旧会话 ID——`/session load <前缀>` 随时回去。

**三个"重新开始"命令的区别**：

| 命令 | 行为 | 适用场景 |
|---|---|---|
| `/session new` | 旧会话存盘关闭 → 换新 ID 空白开始 | 想从零开始（含误恢复处置）——推荐 |
| `/fork [N]` | 旧会话存盘关闭 → 新 ID 但**深拷贝全部历史**（可先回滚 N 轮） | 带着历史分叉试另一条路 |
| `/clear` | **不换 ID**，原地清空内存消息 | 只想清屏继续同一会话——注意覆盖坑（见 /clear） |

一句话：`/clear` 是"擦黑板"（黑板还是那块，盘上旧照片会被新照片覆盖），`/fork` 是"复印一份接着写"，`/session new` 是"旧本子收进抽屉、开新本子"。

**崩溃恢复**：启动时若检测到本项目最新的未正常关闭会话——终端模式弹 yes/no 询问（拒绝则标记已关闭不再问）；**远程模式（--remote）自动恢复不询问**（启动时无客户端可问），浏览器连上即看到完整历史。
**远程模式误恢复处置**（自动恢复了不想要的会话时）：
- 想从零开始：`/session new`——误恢复的会话完整存盘，一条命令安全另起
- 想切到别的会话：`/session load <id>`——同样无损
- **不要直接 `/clear` 后继续对话**：/clear 不换会话 ID，之后的自动保存会覆盖盘上旧历史（见 /clear 的注意）

**远程模式的界面同步**：`/session new`、`/session load`、`/fork` 换掉会话后，服务器检测到会话对象变化，向所有浏览器广播 `history_reset` 事件（清空聊天区）并重放新会话的历史——浏览器显示的和服务器实际工作的会话永远一致。

### /undo [N] [--code-only | --conv-only]
回滚最近 N 轮（默认 1）——默认**对话与文件双回滚**。两个可选标志（互斥）做选择性恢复：`--code-only` 仅恢复文件、对话保留（讨论有价值但改动要扔）；`--conv-only` 仅回滚对话、文件保持现状（改动是对的但对话跑偏，被撤销轮次的快照随之丢弃，之后无法再恢复这些文件）。
```
/undo                  # 回滚 1 轮（对话 + 文件）
/undo 3                # 回滚 3 轮
/undo --code-only      # 仅还原最近 1 轮的文件改动，对话不动
/undo 2 --conv-only    # 仅回滚最近 2 轮对话，文件保持现状
```
文件快照默认保留最近 5 轮（`[memory] undo_keep_turns` 可调大）；回滚范围覆盖超出保留窗口的轮次时会输出警告（该部分文件改动未恢复）；bash 命令修改的文件无法恢复。

### /fork [N]
把当前对话深拷贝为新会话分支（可先回滚 N 轮再分叉）。
```
/fork        # 从当前状态分叉
/fork 2      # 回滚 2 轮后分叉
```

### /exit（别名 /quit）
退出。也可直接输入 `exit` / `quit`。

---

## 二、模型与成本

### /model [name]
无参数：显示当前模型、可用 Provider 列表（`openai`/`anthropic`/`openai-responses`）与可切换档案。带参数：热切换到命名档案（档案通过环境变量 `MINI_AGENT_MODELS` + `MODEL_<NAME>_*` 定义，见 config-guide）。
```
/model            # 查看当前模型 + 可用 Provider + 档案
/model smart      # 切换到 smart 档案
```
注意：切换到命名档案时会**同时切换** provider（如从 openai 切到 anthropic）。裸模型名（不匹配任何档案）则沿用当前 provider 和密钥。

### /cost [turns|reset]
```
/cost             # 成本仪表盘：本会话分模型明细 + 累计总账 + 预算进度
/cost turns       # 逐轮 token/成本明细
/cost reset       # 清零累计总账（会话内数据不受影响）
```
需在 `[cost.pricing.<模型名>]` 配置单价，否则金额恒为 0。

---

## 三、SubAgent 与多 Agent

### /spawn — SubAgent 派发（本节最复杂的命令）

**派发**：
```
/spawn <task>                     # 后台派发单个 SubAgent，立即返回
/spawn -p <task1> | <task2>       # 并行派发多个（| 分隔）
/spawn --isolated <task>          # 在独立 git worktree 中运行（文件隔离）
/spawn --type <t> <task>          # 指定类型：explore/plan/worker(默认)/verify
/spawn --fork <task>              # 继承当前对话摘要（任务引用了之前讨论时用）
/spawn --pane <task>              # 在可见终端窗格运行（独立进程，实时观看）
/spawn --wait <task>              # 阻塞式：派发+进度面板+结果一条命令完成（面板期间按 Esc 转后台）
/spawn --background <task>        # no-op 别名（自动投递已是默认行为）
/spawn --pane --wait <task>       # 组合：弹窗格 + 阻塞等结果
```

**默认即后台自动投递**：`/spawn <task>` 派发后立即返回，agent 完成时结果自动投递到主对话（中断输入等待、drain mailbox、触发 agent loop），无需 `/spawn wait`。想阻塞等结果用 `--wait`；阻塞等待中途反悔按一次 Esc 即转后台（agent 不中断，结果改为自动投递）。

**两种拿结果方式对比**（两者都不需要事后手动收集，区别在等待方式与输出形态）：

| | 期间你能干嘛 | 结果怎么出现 | 输出形态 | 结果进对话历史吗 |
|---|---|---|---|---|
| 默认（自动投递） | 能继续打字、干别的 | 跑完后自动弹出 | 经主 LLM 转述（投递上限 4000 字符） | **进**——可追问、让 LLM 基于结果继续干活 |
| `--wait` / `/spawn wait` | 不能，终端卡住等（显示进度面板） | 等完的瞬间直接打印 | 未转述的完整原文（8000 字符内不截断） | **不进**——斜杠命令本地执行，LLM 不知道这个结果 |

选择建议：想让 LLM 接着处理结果 → 用默认；只想自己看完整原文 → 用 `--wait`。

**`--wait`（flag）与 `wait`（子命令）不是一回事**——一个派发新任务，一个不派发任何东西：

| | `/spawn --wait <任务>` | `/spawn wait [id]` |
|---|---|---|
| 后面跟什么 | **必须跟任务内容** | 不跟任务（最多跟 agent id） |
| 做什么 | 派发一个**新** agent 并原地阻塞等它（一步到位） | **不派发**——只等"之前已派发、还在跑"的 agent |
| 什么时候用 | 派发那一刻就知道"不拿到结果干不了下一步" | ① 收 `--pane` 的结果（刚性场景：子窗格是独立进程，不走自动投递，必须手动收）② 默认派发后中途改主意要等——能用，但结果会出现两次（自动投递照旧发生），不推荐 |

类比：默认 = **点外卖**（下单就走，送到敲门）；`--wait` = **堂食**（点单坐店里等）；`wait` 子命令 = **下了外卖单又跑去店里柜台等**。日常只需要默认和 `--wait` 两个；`wait` 子命令基本只在用了 `--pane` 之后才需要。

**Esc 转后台与重新附着**：`--wait` / `/spawn wait` 的进度面板期间**单击 Esc** 即转后台——agent 不中断继续跑，面板收起并提示 `Moved to background`，完成后结果自动投递进对话（同默认派发）。转后台后**在空的输入提示符按一次 Esc 即重新附着**（等价于自动提交 `/spawn wait`；输入框有内容或补全菜单打开时 Esc 保持原职责），也可手动输 `/spawn wait`（或 `/spawn wait <id>`）：面板回来继续显示进度，等到结果直接打印（后台投递自动取消，不会出现两份）；再按 Esc 又回后台，可反复切换。极小概率在重新附着的瞬间 agent 恰好完成且投递已发出，此时命令会如实提示"结果已投递到收件箱"——结果不会丢，命令结束后立即由 LLM 处理并打印。

已知边界（均为实测确认的设计取舍）：
- **面板期间打字会被丢弃**：面板不是输入框，Esc 之外的按键被监听器静默消费（不回显、不缓存）；想输命令先 Esc 出来
- **面板出现后 0.3 秒内的 Esc 无效**：防误触观察窗会把它当启动噪声排掉，稍等再按一次即可
- **空提示符 Esc 有约半秒判定延迟**：Esc 是组合键序列前缀，prompt_toolkit 需等待消歧——按下后稍候，属正常
- **按 Esc 后立即打字的误触**：存在转后台组时，空提示符按 Esc 又马上打字（如按 Esc 取消输入法候选再输入），Esc 会先触发重新附着、后打的字落到下一个提示符——重附手势就是"空提示符按 Esc"，打字前留半秒即可避开

**收集与管理**：
```
/spawn list                       # 列出活跃 SubAgent（id + 阶段）
/spawn wait                       # 等已在跑的全部 agent（不派发新任务；多结果显示总览表）
                                  # 若有 Esc 转后台的等待组，优先重新附着到它
/spawn wait <id>                  # 等指定的已在跑 agent（主要用于收 --pane 结果 / 重新附着）
/spawn cancel [id]                # 取消指定/全部
```

参数说明：

| 参数 | 说明 |
|---|---|
| `--pane` | 需要 tmux 会话、Windows Terminal 会话（分屏）或装有 wt.exe 的任意终端（降级为共享窗口 mini-agents 的新标签页）。无可用后端时明确报错 |
| `--wait` | 阻塞至完成（上限 900 秒），期间显示进度面板并内联返回完整格式化结果；不加则默认后台自动投递 |
| `--isolated` | 每个 agent 独占 worktree，结果附合并提示 |
| `--background` | **no-op 别名**（向后兼容保留）：自动投递已是无 flag 时的默认行为 |
| `--type` | explore/plan/verify 为只读工具集，worker 全工具。不指定时回退默认 worker 类型档案（P80），但保留配置的 `max_agent_iterations` 迭代预算；显式指定则采纳类型档案预算（worker=50/verify=20 等） |

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
现在通过统一的权限模式切换实现：`on` 等价于 `/mode plan`，`off` 等价于 `/mode default`。

### /mode [name]
查看或切换会话级权限模式。无参数显示当前模式及全部模式说明。
```
/mode                # 显示当前模式 + 四种模式说明
/mode accept-edits   # 切换到 accept-edits（别名 acceptedits/accept_edits 也可）
/mode bypass         # 切换到 bypass（别名 bypasspermissions 也可，切换时显示警告）
```
**快捷键**：在输入提示符按 **shift+tab** 即按 default → accept-edits → plan → bypass → default 顺序循环切换，无需输命令；当前模式看底部工具栏 `mode:` 字段。快捷键与 `/mode`、`/plan` 完全等价（plan 系统提示词同步注入/移除）。
四种模式：

| 模式 | 行为 |
|---|---|
| `default` | 默认行为：危险命令 / 项目外路径弹窗确认 |
| `accept-edits` | 文件写入自动放行（项目内外均是）；危险命令仍确认；项目外读取仍确认 |
| `plan` | 只读计划模式：写类工具禁用 + bash 写形态命令（重定向/mkdir/copy/move/del 等）拒绝 + WRITE/EXTERNAL 类别工具（install_skill/MCP）拒绝；可派研究 agent（子 agent 继承权限栈，写照样被拒），即原 `/plan on` |
| `bypass` | 全部自动放行——但显式 DENY 规则和敏感路径（`~/.ssh`、`.env` 等）例外 |

注意：DENY 规则和敏感路径在**所有模式**下都生效，bypass 也不例外。  
切换进出 plan 模式会同步计划模式系统提示词；`exit_plan_mode` 工具需**用户批准计划**（yes/no 提问）后才退出 plan 模式并重置为 default——LLM 不能自行解除只读限制，拒绝则保持 plan 模式。  
模式切换对**运行中的子 agent 即时生效**（子 agent 的权限视图实时委托主会话模式）。  
启动时的默认模式可通过 config.toml 的 `[security] approval_mode` 配置（见配置指南）。

---

## 四、观测与调试

### /trace [on|off]
实时显示 Agent 内部状态：ReAct 阶段切换、权限判定（含命中规则）、工具耗时、LLM token 元信息。无参数只显示当前状态不改变。

### /explain [on|off]
教学模式：每次工具调用前打印教学面板（为什么用这个工具/参数含义）。无参数只显示当前状态不改变。

### /audit [on|off|verify]
```
/audit on        # 开始记录所有工具调用到 ~/.mini-agent/audit.jsonl（哈希链）
/audit off       # 停止
/audit verify    # 校验哈希链完整性（检测篡改）
```

### /allow — 运行时添加 ALLOW 权限规则
```
/allow                            # 列出当前所有 ALLOW 规则
/allow command "docker *"         # 允许所有 docker 命令
/allow path "D:/shared/*"         # 允许读写指定路径
/allow tool bash                  # 整体信任 bash 工具（跳过命令级检查，慎用）
/allow command "npm *" --save     # 允许并持久化到 .mini-agent/permissions.toml
/allow remove tool bash           # 移除本会话中的 ALLOW 规则
```
scope 必须是 `command`、`path` 或 `tool`，pattern 使用 glob 匹配。  
`tool` scope 按工具名匹配，在命令/路径检查之前评估：allow 整体信任该工具（危险命令也不再确认）；deny 直接拦截整个工具。  
`command` 类 allow 规则只匹配命令本体，不像 deny 那样解包 `cmd /c` 等包装形态（扩大 deny 是收紧、扩大 allow 是放松）。  
**子 agent 注意**：LLM 发出的实际命令可能与你预期不同——Windows 上可能包在 `cmd /c` 里，或用 `python3` 而非 `python`。如果 `/allow command "python -c *"` 对子 agent 不生效，试 `/allow command "*python*-c *"` 覆盖包装形态，或用 `/allow tool bash` 整体信任 bash（跳过所有命令级检查，慎用）。  
不带 `--save` 只在当前会话生效；带 `--save` 写入项目级 permissions.toml，重启后自动加载。
另一条持久化入口：权限确认弹窗按 `a` 后会追问一行 `save permanently (project permissions.toml)? [y/N]`——回 `y` 等价于对该确切命令/路径执行了 `/allow ... --save`（默认回车不写盘，仅会话级）。  
重复规则自动去重，不会重复添加。

### /deny — 运行时添加 DENY 权限规则
```
/deny                             # 列出当前所有 DENY 规则
/deny command "rm -rf *"          # 拒绝所有 rm -rf 命令
/deny path "*/secrets/*"          # 拒绝访问 secrets 路径
/deny tool delete_file            # 直接拦截 delete_file 工具
/deny path "*.pem" --save         # 拒绝并持久化
/deny remove tool delete_file     # 移除本会话中的 DENY 规则
```
语法与 `/allow` 相同。DENY 优先级高于 ALLOW（评估顺序：DENY → ALLOW → 会话授权 → 默认模式）。  
`command` 类 deny 规则匹配包装与串联形态：`cmd /c "ping x"`、`echo hi & ping x` 都命中 `ping*`（引号内数据不误拒；匹配范围与边界详见配置指南"权限规则文件"章节）。  
deny 规则对会话内**所有 agent 实时生效**——包括正在运行的 spawn 子 agent；trace 中显示为 `rule:<scope>:<pattern> (来源)`。  
`remove` 只移除当前会话规则表中的规则（scope+pattern+level 精确匹配）；来自 permissions.toml 的规则下次启动仍会加载，需编辑文件本身。

### /tools
列出所有已注册工具（内置 + MCP，含 dispatch/native 模式的搜索提示）。无参数。

---

## 五、记忆与任务

### /memory — 跨会话记忆
```
/memory                      # 查看全部记忆
/memory add <内容>           # 手动添加
/memory delete <内容>        # 按内容删除
/memory consolidate          # LLM 语义合并相关记忆（会调用 LLM）
/memory export [目录]        # 导出为 .md 文件（YAML 前置元数据 + MEMORY.md 索引）
/memory import <目录>        # 从 .md 目录导入（按 id 去重，按 scope 还原作用域）
```

**自动记忆行为（无需任何命令，默认全开）**：

- **自动提取**：会话结束时（exit / 关闭）LLM 从对话中提取值得跨会话记住的事实，写入项目级或用户级记忆（`[memory] auto_extract = false` 关闭）。
- **自动召回**：每个会话把记忆注入 system prompt。记忆 ≤10 条全部注入；>10 条时用 LLM 挑选与你当前消息最相关的 ≤5 条——挑选与主 LLM 调用**并行**跑（不增加首 token 延迟），超时 8 秒降级注入头部条目。注意：>10 条时本回合**第一次** LLM 调用还没有记忆（挑选刚发射），从第二次调用（工具回合后）或下一回合起保证注入。阈值经 `recall_threshold` / `recall_top_k` / `recall_timeout` 配置。
- **自动整固（后台节律）**：每次启动（终端与 `--remote` 均生效）检查双门槛——距上次整固 ≥24 小时**且**期间有 ≥5 个会话——满足则后台用 LLM 把语义相关的记忆合并去重，全程无感、不打扰输出；锁文件防多实例并发，保存失败自动回滚。门槛经 `consolidate_min_hours` / `consolidate_min_sessions` 配置，`auto_consolidate = false` 关闭。另有独立的阈值触发（记忆 >20 条时随会话结束提取一起合并）与手动 `/memory consolidate`。
- **观察它在工作**：`~/.mini-agent/memory/consolidation_state.json` 记录每个作用域上次整固时间——文件里出现 `user` / `project:...` 键即说明整固尝试过（门槛未满足时文件可能只是空 `{}`）。想立刻看到一次触发：临时把两个门槛设为 `0.0` 和 `1`，启动两次即可（会真实合并记忆，验完记得删配置恢复默认节律）。注意合并是一次真实 LLM 调用（记忆多时可达十几秒），启动后立刻退出会取消本次整固——state 未记录，下次启动自然重试，不丢节律。

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

## 六、录制与回放

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

## 七、扩展

### /skill — 技能包管理
```
/skill                       # 列出全部技能包及激活状态
/skill activate <name>       # 激活（prompt 注入 system prompt）
/skill deactivate <name>     # 停用（精确移除）
/skill install <path_or_url> # 安装：本地目录复制 / git URL 克隆
/skill uninstall <name>      # 卸载
/skill reload                # 热重载技能目录（改完 SKILL.md 不用重启）
```

### /plugins
列出已加载插件及各自注册的工具/命令/技能。无参数。
插件两种安装方式：`.py` 文件放入 `./.mini-agent/plugins`（或 `~/.mini-agent/plugins`），
或 pip 安装声明了 `mini_agent.plugins` entry point 的包。`disabled_plugins` 配置可禁用。

### /theme [default|dark|light]
切换配色主题并持久化到 `~/.mini-agent/.theme`。无参数显示当前主题。

### /help
列出全部命令（字母排序）。

---

## 八、命令效果的持久化范围

设置类命令分两档：**会话级**（重启即失效，回到配置文件的启动值）和**持久化**（写盘，跨会话生效）。

会话级（重启失效）：

| 命令 | 说明 |
|---|---|
| `/allow` `/deny`（不带 `--save`） | 规则只存会话内存；`/deny remove` 也只删会话内规则——TOML 里的下次启动仍会加载 |
| `/mode` | 重启回到 `[security] approval_mode` 配置值 |
| `/plan` | 同上（`enable_plan_mode` 配置控制启动值） |
| `/trace` `/explain` | 开关不落盘 |
| `/model` | 切换 LLM Profile 仅本会话 |
| `/audit on/off` | 开关是会话级（审计日志文件本身持久） |
| `/skill activate/deactivate` | 激活状态注入 system prompt；`/session save` 后若会话经历过压缩（存在压缩边界），`load` 时激活状态随边界恢复（prompt 不重注入），否则 prompt 仍在但注册表激活状态丢失 |
| 确认弹窗的 `a`（always） | 会话授权，重启清空 |

持久化（写盘位置）：

| 命令 | 落盘位置 |
|---|---|
| `/allow` `/deny` **--save** | 项目 `.mini-agent/permissions.toml`（每次启动自动加载） |
| `/theme` | `~/.mini-agent/.theme` |
| `/memory add` | 项目 `.mini-agent/memory.json` / 用户 `~/.mini-agent/memory/` |
| `/session save/tag` | `~/.mini-agent/sessions/` |
| `/todo` | 项目 `.mini-agent/tasks.json` |
| `/record` | `~/.mini-agent/recordings/` |

另有两类启动加载的磁盘扩展（非命令创建，天然持久）：自定义 agent 类型（`./.mini-agent/agents/*.md`、`~/.mini-agent/agents/*.md`）、事件监听插件（`./.mini-agent/listeners/*.py`、`~/.mini-agent/listeners/*.py`）、工具/命令插件（`plugin_dirs`）。**`.mini-agent/` 整个目录在 .gitignore 中**——permissions.toml、memory.json、自定义 agent/listener 等都不会被提交或推送到远程仓库；想与团队共享需主动移出该目录或调整 .gitignore。

---

## 九、通用行为

- 命令在本地执行，输错命令名会提示全部可用命令
- 命令 handler 抛异常不会杀死会话（显示 "Command failed: ..." 后继续）
- 报告类输出（/spawn --wait、/spawn wait）走 Markdown 渲染（表格/标题/亮橙文件名），状态类输出（/status /cost）保持纯文本对齐版式
- 远程浏览器模式（`--remote`）下所有命令同样可用
