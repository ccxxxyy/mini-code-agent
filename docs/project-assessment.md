# Mini-Code-Agent 项目现状分析

> 基于 v1.1.0 代码库的诚实审计。所有结论附代码证据（文件路径 + 行号）。

---

## 一、优势

### 1.1 极简依赖，零 SDK

运行时仅 4 个依赖：`rich`、`prompt-toolkit`、`httpx`、`pydantic`。没有任何 LLM 厂商 SDK（Anthropic/OpenAI），全部用 httpx 直连 HTTP API。好处是不受 SDK 破坏性更新影响、安装快、用户可审计所有代码。对比 mewcode 的 7 个运行时依赖，这是真实的差异化优势。

**证据**：`pyproject.toml` dependencies 节仅 4 项。

### 1.2 测试密度高

1379 个测试，3065 个 assert 语句（平均每个测试 2.2 个断言）。零 TODO/FIXME 在测试代码中。测试用 `conftest.py` 的 `_isolate_home` fixture 自动重定向 `Path.home()`，确保不污染真实用户目录。

安全相关测试特别扎实：70+ 个权限断言，覆盖 deny 规则穿透、cmd /c 解包、写后执行检测、熔断器行为等。回归测试带注释说明守护的是哪个 bug。

**证据**：`tests/conftest.py:12-26`（隔离 fixture）、`tests/unit/test_tool_categories.py`（640 行安全测试）。

### 1.3 架构分层清晰

五层架构（ui → core → tools → memory → security）通过 EventBus 解耦。经验证：

- `core/` 零导入 `ui/`（干净的依赖方向）
- `security/` 零导入 `ui/`
- EventBus 消费方全部是纯订阅者（Trace/Audit/Teach/Recorder/Cost），Agent 循环完全不知道它们的存在
- EventBus 正确吞咽 handler 异常（`return_exceptions=True` + 日志），一个订阅者崩溃不影响主流程

**证据**：`events/bus.py:48-51`、`core/` 目录 grep `mini_agent.ui` 零命中。

### 1.4 文档体量大且中英双语

18 个文档文件，约 18000 行。分为用户指南（4 个主题 × 中英双语 = 8 个文件）和内部文档（spec/tech-notes/tasks/checklist 等 10 个文件）。tech-notes 记录了每个设计决策的前因后果，是真正的决策日志而非事后补写。

### 1.5 安全边界诚实标注

项目在多处用"诚实边界"标注已知限制：正则黑名单不可能穷尽（`permission.py:54-59`）、Windows 非管理员无文件保护（`sandbox/windows.py:55-63`）、敏感文件检测可被混淆绕过（`permission.py:164-168`）。不声称做不到的事，这比隐瞒限制好。

### 1.6 LLM 重试与降级设计

三个 Provider 共享统一的重试基础设施：5 次指数退避（1/2/4/8/16s + jitter）、尊重 Retry-After 头、仅重试可恢复状态码（429/500/502/503/529）。流式中断不重试（避免重复输出）是正确的设计决策。`max_tokens` 截断时自动翻倍重试最多 3 次。

**证据**：`llm/base.py:91-112`、`agent_loop.py:487`。

---

## 二、不足

### 2.1 组合根臃肿：`Application.__init__` 433 行

`app.py` 的构造函数长达 433 行（124-557 行），在里面装配了 20+ 个子系统。这不是"组合根"该有的大小——它把装配逻辑、回调注册、事件订阅、UI 回调绑定全部堆在一个方法里。没有工厂函数或 builder 拆分。结果是这个文件 1298 行，且没有对应的单元测试文件。

**证据**：`app.py:124-557`。

**✅ 已修复**：`__init__` 拆为 16 个 `_setup_*`/`_wire_*` 装配方法，本体压缩为 25 行的按依赖顺序调用清单；公开构造接口与全部 `self.*` 属性名不变。新增 `tests/unit/test_app.py` 10 个装配测试补上单元测试缺口。详见 tech-notes §117。

### 2.2 最大文件零测试覆盖：`builtin_commands.py` 1815 行

所有 28 个斜杠命令的处理逻辑堆在一个文件里，是全项目最大的文件。没有对应的 `test_builtin_commands.py`。命令行为只通过集成测试间接覆盖——部分命令完全没有测试覆盖。

**证据**：`extensions/builtin_commands.py`（1815 行）、`tests/` 目录无 `test_builtin_commands.py`。

**✅ 已修复**：新增 `tests/unit/test_builtin_commands.py` 45 个测试，直接覆盖此前零覆盖的 18 个命令处理函数（clear/model/compact/tools/plugins/trace/explain/audit/theme/plan/mode/allow/deny/quit/exit/session/memory/skill/spawn 信息子命令）。已有专门测试文件的命令（undo/fork/todo/cost/record/replay/help/status）不重复。详见 tech-notes §118。

### 2.3 异步方法内的同步文件 I/O

所有文件工具（read_file/write_file/edit_file/grep）在 `async def execute()` 里用同步的 `Path.read_text()` / `Path.write_text()`。这在事件循环线程上阻塞 I/O。grep 工具最严重：遍历目录树，逐文件同步读取全部内容到内存（最大 5MB/文件），再 `.splitlines()` 产生第二份拷贝。大型代码库可能读数百 MB，全程阻塞事件循环。

SessionStore 同理：`list_sessions()` 同步读取每个会话 JSON 文件提取元数据。

**证据**：`tools/builtin/grep.py:82-83`、`tools/builtin/read_file.py:51`、`memory/session_store.py:59-76`。

**✅ 已修复**：全部阻塞文件 I/O 经 `asyncio.to_thread` 移出事件循环——grep/glob 的目录遍历+逐文件读取循环整体提取为 `_scan()` 同步方法下放线程；read_file/write_file/edit_file 的 `read_text`/`write_text` 逐调用包装；SessionStore 的 save/load/list_sessions/delete/cleanup_stale 全部下放（读循环提取为 `_list_sessions_sync`/`_cleanup_stale_sync`）。新增 4 个事件循环不阻塞回归测试（threading.Event 确定性验证）。详见 tech-notes §119。

### 2.4 测试基础设施重复：MockLLM 复制了 11 份

项目有一致的 MockLLM 模式（脚本化的 StreamChunk 序列），但在至少 11 个测试文件中各自独立定义了几乎相同的 MockLLM 类，而不是放在 conftest.py 或共享 fixture 里。新增测试需要再复制一份。

**证据**：`test_agent_loop.py`、`test_subagent.py`、`test_board.py`、`test_file_changes.py`、`test_headless.py`、`test_hooks_lifecycle.py`、`test_mailbox.py`、`test_spawn_agents_tool.py`、`test_spawn_pane.py`、`test_spawn_team.py`、`test_tool_parallel.py` 各有独立 MockLLM。

**✅ 已修复**：新增 `tests/mocks.py` 统一实现（scripts 脚本重放 + text/delay/error 参数覆盖全部变体，公开 `call_count`），实际消除 13 处定义（评估列出的 11 处 + `test_extension_points.py` 嵌套类 + `test_tool_categories.py` 非 ABC 版本），3 个跨文件导入方（test_hooks/test_streaming_execution/test_tool_result_cache 原从 test_agent_loop 导入）同步改从共享模块导入。功能特化的 SummaryMockLLM/TeamMockLLM/_MockLLM 不并入。16 文件 −350/+49 行，1438 测试数量不变全过。详见 tech-notes §120。

### 2.5 覆盖率门禁未接入 CI

`pyproject.toml` 配了 `fail_under = 80`，但 CI 的 pytest 命令（`.github/workflows/ci.yml`）没有 `--cov` 参数，覆盖率从未实际收集和检查。这个门禁是摆设。

**证据**：`.github/workflows/ci.yml` 的 test 步骤：`uv run pytest tests/ -v`（无 `--cov`）。

### 2.6 Windows 平台无 CI 覆盖

项目有大量 Windows 特定代码（EscWatcher msvcrt 分支、junction 回退、sandbox Low Integrity 模式、终端 GBK 解码、mintty 适配），但 CI 只在 `ubuntu-latest` 跑。Windows 上的回归只能靠开发者手动验证。

**证据**：`.github/workflows/ci.yml` 的 `runs-on: ubuntu-latest`。

### 2.7 类型系统漏洞：`ToolContext` 六字段 `Any`

`tools/base.py:97-108` 的 `ToolContext` 有 7 个字段声明为 `Any`：`mcp_manager`、`mailbox`、`task_store`、`agent_loop_ref`、`ask_user_callback`、`skill_registry`、`file_state`。只有 `subagent_manager` 用了 `TYPE_CHECKING` 条件导入的正确类型。其余 6 个字段使得静态类型检查完全失效。

### 2.8 全类型注解无实际校验

项目声称"全类型注解"（CLAUDE.md），但 CI 不跑 mypy 或 pyright。`ToolContext` 的 `Any` 字段问题在类型检查下会立即暴露。没有类型检查门禁，类型注解只是注释性质。

### 2.9 魔法数字散落各模块

分散在各模块中的魔法数字，例如：
- bash 输出截断 `MAX_OUTPUT_CHARS = 30000`（`bash.py:14`）
- grep 匹配上限 `MAX_MATCHES = 200`（`grep.py:17`）
- 自动保存间隔 `AUTOSAVE_INTERVAL = 30.0`（`app.py:57`）
- 后台通知截断 `NOTIFY_MAX_CHARS = 4000`（`subagent.py:719`）
- 压缩保留参数 `KEEP_RECENT_TOKENS = 10000` 等（`compressor.py:130-133`）
- 面板刷新率 `_REFRESH_INTERVAL = 0.25`（`board.py:26`）

这些值对不同使用场景可能需要调整，但目前只能改源码。

### 2.10 敏感文件检测覆盖面不足

`security/path_guard.py:11-22` 的敏感文件模式缺少常见的凭证文件：`.npmrc`（npm 认证 token）、`.pypirc`（PyPI 密码）、`.netrc`、`.git-credentials`、`authorized_keys`、Docker 配置等。

### 2.11 Anthropic 官方端点从未实测

代码就绪但从未用真实 Anthropic API key 测试过。只在第三方兼容网关（阿里云 MaaS + deepseek-v4-pro）上验证。签名密码学校验和 prompt cache 命中统计未验证。

**证据**：`docs/roadmap.md:839`。

### 2.12 废弃 API 残留

4 处使用了 Python 3.10 起废弃的 `asyncio.get_event_loop()`（`terminal.py:196`、`agent_loop.py:606`、`permission.py:272,291`），应改为 `asyncio.get_running_loop()`。

---

## 三、总体评价

**这是一个工程完成度很高的个人项目**。1379 个测试、18000 行文档、21 个工具、4 个依赖——在"可读的 Agent 参考实现"这个定位上是成立的。安全层的诚实边界标注、EventBus 的解耦设计、零 SDK 的依赖策略都是经过思考的决策。

**主要的技术债务集中在两个方向**：

1. **大文件拆分**：`app.py`（1298 行）和 `builtin_commands.py`（1815 行）需要拆分。前者的 `__init__` 应该提取工厂函数（✅ 已完成——拆为 16 个装配方法，见 §2.1 与 tech-notes §117）；后者应该按命令分文件或分组。
2. **CI 补全**：覆盖率门禁实际启用、Windows 矩阵、类型检查。这三项是低成本高收益的改进。

同步 I/O 问题已修复（✅ 见 §2.3 与 tech-notes §119）：文件工具与 SessionStore 的阻塞 I/O 均经 `asyncio.to_thread` 移出事件循环，大型代码库上 grep 扫描不再阻塞其他并发任务（如流式输出、ESC 中断监听）。
