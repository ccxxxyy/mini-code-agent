"""Application orchestrator -- wires all layers together. 应用编排器——将所有层级组装在一起。"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from mini_agent.config import detect_shell
from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.subagent import SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.extensions.builtin_commands import register_builtin_commands
from mini_agent.extensions.skills import SkillRegistry
from mini_agent.extensions.slash_commands import MARKDOWN_RESULT, SlashCommandRegistry
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import (
    Compressor,
    DropToolResults,
    LLMSummarizeOldest,
    SlidingWindow,
)
from mini_agent.memory.context import ContextManager
from mini_agent.memory.session_store import SessionStore
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import (
    SessionEndEvent,
    SessionStartEvent,
    UserMessageEvent,
)
from mini_agent.models.message import Message, Role
from mini_agent.models.session import Session
from mini_agent.security.audit import AuditLogger
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.security.worktree import WorktreeManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS
from mini_agent.tools.hooks import (
    HookAction,
    HookContext,
    HookManager,
    HookResult,
    HookStage,
    register_hook_rules,
)
from mini_agent.ui.teach import TeachRenderer
from mini_agent.ui.terminal import Terminal
from mini_agent.ui.trace import TraceRenderer

logger = logging.getLogger(__name__)

# Minimum seconds between automatic session saves 两次自动保存之间的最小间隔秒数
AUTOSAVE_INTERVAL = 30.0

SYSTEM_PROMPT = """You are a helpful coding agent running in a terminal (Mini-Code-Agent).
You are powered by the LLM model: {model}
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

When asked what model or LLM you are, answer with the model name above -- \
do not guess based on your training data.

You have access to tools for reading/writing/editing files, running shell commands, \
and searching the codebase (glob for file names, grep for file contents).

Guidelines:
- ALWAYS respond in the same language the user writes in. If the user asks \
in Chinese, answer in Chinese; if in English, answer in English. This applies \
to ALL your text output, including explanations between tool calls.
- Only use tools when the task actually requires them (reading/changing files, \
running commands). For simple questions, conversation, or anything you already \
know (including your own model name above), answer directly WITHOUT any tool calls.
- Use tools to accomplish tasks. Don't guess file contents -- read them.
- Break complex tasks into steps: search, read, then modify.
- Be concise in your final answers. Use markdown formatting.
- When quoting file content that itself contains ``` code fences, wrap the \
quote in a FOUR-backtick fence (````) so the inner fences render correctly. \
Better yet, prefer summarizing over quoting entire files verbatim.
- When editing files, read them first to understand the context.
- Report errors honestly. If a tool fails, explain what went wrong.
- For multiple independent subtasks, use the spawn_agents tool to \
run them in parallel via sub-agents. Each sub-agent has its own \
tools but cannot spawn further sub-agents. Sub-agent results are \
returned as a combined report.
- IMPORTANT: Use platform-appropriate shell commands. \
On Windows use dir/type/findstr/where, NOT ls/cat/grep/which.
- CRITICAL: NEVER run git commit, git push, git stash, git reset, \
git rebase, or any git command that modifies repository state or \
history, unless the user EXPLICITLY asked for that exact operation \
in their current message. Answering a question is never a reason \
to commit. Read-only git commands (status/log/diff) are fine.
- Stay on the user's actual request. Do not expand a simple question \
into project auditing, committing work, or cleaning up files the \
user did not mention.
- Verify before you claim: run a test before asserting it passes/fails, \
count items before stating a number, read a function before describing its \
signature. State each fact only ONCE in your final answer — never output \
a draft followed by corrections. If you cannot verify, say "unverified".\""""


class Application:
    """Main application -- agent conversation loop. 主应用——Agent 对话循环。"""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.event_bus = EventBus()

        # Load persisted theme preference 加载持久化的主题偏好
        from mini_agent.ui.themes import get_theme

        theme_path = Path.home() / ".mini-agent" / ".theme"
        if theme_path.is_file():
            try:
                config.theme = theme_path.read_text(encoding="utf-8").strip() or "default"
            except OSError:
                pass
        active_theme = get_theme(config.theme)

        self.terminal = Terminal(theme=active_theme)
        self.session = Session()

        working_dir = Path.cwd()
        platform = f"{sys.platform} ({'Windows' if sys.platform == 'win32' else 'Unix'})"
        shell = detect_shell()
        self.session.conversation.system_prompt = SYSTEM_PROMPT.format(
            model=config.llm.model,
            working_dir=working_dir,
            platform=platform,
            shell=shell,
        )
        self.session.metadata.model = config.llm.model
        self.session.metadata.project_dir = working_dir

        # Context awareness: auto-inject project/user instruction files
        # 上下文感知：自动注入项目/用户指令文件
        from mini_agent.memory.project_context import (
            load_project_instructions,
            load_user_instructions,
        )

        self._context_file_loaded: str | None = None
        _marker = "\n\n--- Project instructions ---\n"
        _parts: list[str] = []
        _user_inst = load_user_instructions(
            config.context.user_instructions_file, config.context.max_chars
        )
        if _user_inst:
            _parts.append("[user instructions]\n" + _user_inst)
        _proj = load_project_instructions(
            working_dir, config.context.instruction_files, config.context.max_chars
        )
        if _proj:
            self._context_file_loaded = _proj[0]
            _parts.append(f"[{_proj[0]}]\n{_proj[1]}")
        if _parts and _marker not in self.session.conversation.system_prompt:
            self.session.conversation.system_prompt += _marker + "\n\n".join(_parts)

        self._llm = ProviderRegistry.create(config.llm)

        # Tool registry with all builtin tools 包含所有内置工具的工具 registry
        self.tool_registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            tool = tool_class()
            if tool.schema.name in config.tools.enabled_tools:
                self.tool_registry.register(tool)

        tool_context = ToolContext(
            working_dir=working_dir,
            session=self.session,
            event_bus=self.event_bus,
            config=config,
        )
        self._tool_context = tool_context

        # Security: path guard + permission manager wired to terminal confirm
        # 安全：路径守卫 + 权限管理器接入终端确认
        path_guard = PathGuard(
            tool_config=config.tools,
            security_config=config.security,
            project_dir=working_dir,
        )
        self.permission_manager = PermissionManager(
            config=config.security,
            path_guard=path_guard,
            confirm_callback=self.terminal.confirm,
            event_bus=self.event_bus,
        )
        # User-defined permission rules 用户自定义权限规则文件
        self.permission_manager.load_rule_files(
            user_file=Path.home() / ".mini-agent" / "permissions.toml",
            project_file=working_dir / ".mini-agent" / "permissions.toml",
        )

        # OS-level sandbox (Linux bwrap / macOS seatbelt)
        # OS 级沙箱（Linux bwrap / macOS seatbelt）
        if config.security.sandbox:
            from mini_agent.security.sandbox import SandboxConfig, create_sandbox

            os_sandbox = create_sandbox()
            if os_sandbox and os_sandbox.available():
                sb_config = SandboxConfig(
                    allow_write=[str(working_dir), "/tmp"],
                    deny_write=[str(Path.home() / ".mini-agent")],
                    network=config.security.sandbox_network,
                )
                bash_tool = self.tool_registry.get("bash")
                if bash_tool:
                    bash_tool.sandbox = os_sandbox
                    bash_tool.sandbox_config = sb_config
                if config.security.sandbox_auto_allow:
                    self.permission_manager.sandbox_auto_allow = True

        self.hook_manager = HookManager()
        self._register_builtin_hooks()
        # Declarative rejection rules from `[[hooks]]` config (7.2)
        # `[[hooks]]` 配置的声明式拒绝规则
        n_rules = register_hook_rules(self.hook_manager, config.hooks)
        if n_rules:
            self.terminal.show_info(f"Loaded {n_rules} hook rule(s) from config")

        # Memory: context manager + compressor + session store
        # 记忆：上下文管理器 + 压缩器 + 会话存储
        self.context_manager = ContextManager(config.memory)
        if config.memory.llm_summarize:
            compressor = Compressor(
                strategies=[
                    DropToolResults(),
                    LLMSummarizeOldest(self._llm),
                    SlidingWindow(),
                ]
            )
        else:
            compressor = Compressor()
        self.context_manager.set_compressor(compressor)
        self.session_store = SessionStore()
        self._last_autosave: float = 0.0

        self.agent_loop = AgentLoop(
            llm=self._llm,
            tool_registry=self.tool_registry,
            event_bus=self.event_bus,
            config=config,
            tool_context=tool_context,
            permission_manager=self.permission_manager,
            hook_manager=self.hook_manager,
            context_manager=self.context_manager,
        )
        # CONFIRM hooks resolve through the same y/a/n dialog as permissions
        # CONFIRM hook 复用与权限确认相同的 y/a/n 弹窗
        self.agent_loop.confirm_callback = self.terminal.confirm

        # File snapshots for operation-level /undo 文件快照——操作级撤销
        from mini_agent.memory.file_snapshots import FileSnapshotStore

        self.agent_loop.snapshot_store = FileSnapshotStore(
            working_dir / ".mini-agent" / "undo_snapshots"
        )

        # Spill oversized tool results to disk (compression-reread fix)
        # 超大工具结果溢写磁盘（压缩-重读膨胀根治）
        from mini_agent.memory.tool_result_cache import ToolResultCache

        self.result_cache = ToolResultCache(
            Path.home() / ".mini-agent" / "cache" / "results" / self.session.metadata.session_id,
            threshold_chars=config.memory.spill_threshold_chars,
            aggregate_chars=config.memory.aggregate_spill_chars,
        )
        self.agent_loop.result_cache = self.result_cache

        # SubAgent + Worktree: /spawn and /team use these
        # SubAgent + Worktree：/spawn 和 /team 命令使用
        self.worktree_manager = WorktreeManager(repo_dir=working_dir)
        worker_llm = ProviderRegistry.create_for_role(config, "worker")
        worker_profile = config.llm_profiles.get(config.worker_profile)
        worker_model = worker_profile.model if worker_profile else config.llm.model
        self.subagent_manager = SubAgentManager(
            llm=worker_llm,
            tool_registry=self.tool_registry,
            config=config,
            event_bus=self.event_bus,
            working_dir=working_dir,
            worktree_manager=self.worktree_manager,
            model_name=worker_model,
            confirm_callback=self.terminal.confirm,
        )

        # Inject SubAgentManager into ToolContext so spawn_agents tool can use it
        # 注入 SubAgentManager 到 ToolContext，供 spawn_agents 工具使用
        tool_context.subagent_manager = self.subagent_manager

        # Cross-agent mailbox: main agent inbox + send_message tool access
        # 跨 Agent 收件箱：主 Agent 收件箱 + send_message 工具接入
        self.mailbox = self.subagent_manager.mailbox
        self.mailbox.register("main")
        tool_context.mailbox = self.mailbox
        self.agent_loop.mailbox = self.mailbox

        # Trace renderer: /trace shows agent internals in real time
        # Trace 渲染器：/trace 实时展示 Agent 内部状态
        self.trace_renderer = TraceRenderer(self.terminal.console, theme=active_theme)
        self.trace_renderer.attach(self.event_bus)

        # Teach renderer: /explain shows tool explanations
        # 教学渲染器：/explain 显示工具解释
        self.teach_renderer = TeachRenderer(self.terminal.console, theme=active_theme)
        self.teach_renderer.attach(self.event_bus)

        # Audit logger: /audit writes tool calls to JSONL
        # 审计日志：/audit 将工具调用写入 JSONL
        audit_dir = Path.home() / ".mini-agent"
        self.audit_logger = AuditLogger(audit_dir)

        # MCP manager: connects remote tool servers at startup
        # MCP 管理器：启动时连接远程工具服务器
        from mini_agent.tools.mcp.client import MCPManager

        self.mcp_manager = MCPManager()
        self._tool_context.mcp_manager = self.mcp_manager

        # Persistent task system (S12): /todo command 持久化任务系统
        from mini_agent.core.task_store import TaskStore

        self.task_store = TaskStore(working_dir)
        self.audit_logger.attach(self.event_bus)

        # Tool recorder: /record captures tool calls, /replay re-runs them
        # 工具录制器：/record 捕获工具调用，/replay 重放
        from mini_agent.core.tool_recorder import ToolRecorder

        self.tool_recorder = ToolRecorder(Path.home() / ".mini-agent" / "recordings")
        self.tool_recorder.attach(self.event_bus)

        # Cost tracker: per-model token usage priced via [cost] config
        # 成本跟踪器：按模型计价 token 用量
        from mini_agent.core.cost_tracker import CostTracker

        self.cost_tracker = CostTracker(
            config.cost, ledger_path=Path.home() / ".mini-agent" / "cost_ledger.json"
        )
        self.cost_tracker.attach(self.event_bus)
        self.agent_loop.model_name = config.llm.model
        self.agent_loop.plan_mode = config.enable_plan_mode

        # Skill system
        self.skill_registry = SkillRegistry(skill_dirs=[Path(d) for d in config.skill_dirs])
        self.skill_registry.load_all()

        # Event listener plugins: external code observing all bus events
        # 事件监听插件：外部代码监听总线全部事件（统计/调试）
        from mini_agent.extensions.event_listeners import load_event_listeners

        self.loaded_listeners = load_event_listeners(config.listener_dirs, self.event_bus)
        if self.loaded_listeners:
            self.terminal.show_info(
                f"Loaded {len(self.loaded_listeners)} event listener(s): "
                + ", ".join(self.loaded_listeners)
            )

        # Slash commands
        self.slash_commands = SlashCommandRegistry()
        register_builtin_commands(self)

        # Wire slash command completions + @file completions to terminal
        # 将斜杠命令补全 + @文件补全接入终端
        self.terminal.set_working_dir(working_dir)
        self.terminal.set_slash_commands(
            [(c.name, c.description) for c in self.slash_commands.list_commands()]
        )

        # Bottom toolbar: show current LLM under the input line
        # 底部工具栏：在输入框下方显示当前 LLM
        self.terminal.set_toolbar_provider(self._toolbar_text)

        # Double-Esc interrupt watcher 双 Esc 中断监听器
        from mini_agent.ui.esc_watcher import EscWatcher

        self._esc_watcher = EscWatcher()

        # Wire agent loop callbacks to terminal rendering 将 Agent 循环回调接入终端渲染
        def _on_stream_start() -> None:
            self._esc_watcher.start()
            self.terminal.start_stream()

        def _on_stream_delta(delta: str) -> None:
            if self._esc_watcher.triggered:
                self.agent_loop.cancel()
            self.terminal.feed_stream(delta)

        def _on_stream_end(_full_text: str = "") -> None:
            self._esc_watcher.stop()
            self.terminal.finish_stream()

        def _on_thinking_delta(delta: str) -> None:
            if self._esc_watcher.triggered:
                self.agent_loop.cancel()
            self.terminal.feed_thinking(delta)

        self.agent_loop.on_stream_start = _on_stream_start
        self.agent_loop.on_stream_delta = _on_stream_delta
        self.agent_loop.on_stream_end = _on_stream_end
        self.agent_loop.on_thinking_delta = _on_thinking_delta

        # Streaming tool call assembly: show tool name as soon as LLM starts
        # generating its arguments, before the full JSON is assembled.
        # 流式工具调用组装：LLM 开始生成参数时立即显示工具名，无需等 JSON 组装完。
        _assembling_shown: set[str] = set()

        def _on_tool_assembling(name: str) -> None:
            if name not in _assembling_shown:
                _assembling_shown.add(name)
                p = self.terminal.theme.primary
                self.terminal.console.print(
                    f"\n  [dim]╭─[/dim] [{p}]{name}[/{p}] [dim]...[/dim]",
                    highlight=False,
                )

        def _on_tool_start(tc) -> None:
            if tc.name in _assembling_shown:
                # Already shown during assembly — just print args summary
                # 组装期间已显示工具名——只补充参数摘要
                arg_preview = ", ".join(
                    f"{k}={self.terminal._truncate_value(v)}" for k, v in tc.arguments.items()
                )
                if arg_preview:
                    self.terminal.console.print(f"  [dim]│  {arg_preview}[/dim]", highlight=False)
            else:
                self.terminal.show_tool_call(tc.name, tc.arguments)

        def _on_tool_end(tr, _duration_ms=0.0) -> None:
            _assembling_shown.discard(tr.name)
            self.terminal.show_tool_result(tr.name, tr.output, tr.is_error, tr.metadata)

        self.agent_loop.on_tool_call_assembling = _on_tool_assembling
        self.agent_loop.on_tool_start = _on_tool_start
        self.agent_loop.on_tool_end = _on_tool_end

    def _toolbar_text(self) -> str:
        """Bottom toolbar content: current model + switchable model count.
        底部工具栏内容：当前模型 + 可切换模型数量。
        """
        text = f"LLM: {self.config.llm.model} ({self.config.llm.provider})"
        if len(self.config.llm_profiles) > 1:
            text += f"  |  {len(self.config.llm_profiles)} models, /model to switch"
        return text

    def switch_llm_profile(self, name: str) -> bool:
        """Switch the active LLM to a named profile. Returns True on success.
        切换当前 LLM 到指定命名档案。成功返回 True。
        """
        profile = self.config.llm_profiles.get(name)
        if profile is None:
            return False
        old_model = self.config.llm.model
        self.config.llm = profile
        self.session.metadata.model = profile.model
        self._llm = ProviderRegistry.create(profile)
        self.agent_loop._llm = self._llm
        self.agent_loop.model_name = profile.model  # cost attribution 成本归属
        # Update model name in system prompt so the LLM self-identifies correctly
        # 同步更新 system prompt 中的模型名，让 LLM 正确自我认知
        self.session.conversation.system_prompt = self.session.conversation.system_prompt.replace(
            f"powered by the LLM model: {old_model}",
            f"powered by the LLM model: {profile.model}",
        )
        return True

    async def run(self) -> None:
        try:
            await self.hook_manager.run(
                HookContext(
                    stage=HookStage.STARTUP,
                    metadata={"session_id": self.session.metadata.session_id},
                )
            )
        except Exception:
            logger.warning("hook fire failed: startup", exc_info=True)
            pass
        self.terminal.show_welcome()
        # Probe context window before the first turn's overflow check
        # 启动时预热探测上下文窗口，让首轮溢出检查就用上真实值
        await self._llm.prepare()
        await self._connect_mcp_servers()
        # Stale worktree cleanup (P54): clean worktrees older than N days
        # 过期 worktree 清理：清除超龄的干净 worktree
        if self.config.security.worktree_max_age_days > 0:
            try:
                removed = await self.worktree_manager.cleanup_stale(
                    self.config.security.worktree_max_age_days
                )
                if removed:
                    self.terminal.show_info(f"Cleaned {len(removed)} stale worktree(s)")
            except Exception:
                logger.debug("worktree cleanup failed", exc_info=True)
                pass
        # Stale session cleanup (9.1): remove sessions older than N days
        # 过期会话清理：删除超龄的已正常关闭会话
        if self.config.memory.session_cleanup_days > 0:
            try:
                n = await self.session_store.cleanup_stale(self.config.memory.session_cleanup_days)
                if n:
                    self.terminal.show_info(f"Cleaned {n} stale session(s)")
            except Exception:
                logger.debug("stale session cleanup failed", exc_info=True)
                pass
        await self._maybe_restore_session()
        await self.event_bus.emit(SessionStartEvent(session_id=self.session.metadata.session_id))
        try:
            await self.hook_manager.run(
                HookContext(
                    stage=HookStage.SESSION_START,
                    metadata={
                        "session_id": self.session.metadata.session_id,
                        "model": self.config.llm.model,
                    },
                )
            )
        except Exception:
            logger.warning("hook fire failed: session-init", exc_info=True)
            pass

        try:
            while True:
                try:
                    user_input = await self.terminal.get_user_input()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in ("exit", "quit"):
                    break

                # Slash command dispatch 斜杠命令分发
                if self.slash_commands.is_slash_command(user_input):
                    await self.event_bus.emit(
                        UserMessageEvent(content=user_input, is_slash_command=True)
                    )
                    try:
                        result = await self.slash_commands.execute(user_input, self)
                        if result:
                            self.terminal.console.print()
                            if result.startswith(MARKDOWN_RESULT):
                                from rich.markdown import Markdown
                                from rich.theme import Theme

                                # Agent reports opt into Markdown rendering
                                # (headers/tables); inline code (file names,
                                # agent ids) pops in bright orange.
                                # Agent 报告显式选择 Markdown 渲染；行内代码
                                # （文件名/agent id）亮橙色凸显。
                                with self.terminal.console.use_theme(
                                    Theme({"markdown.code": "bold orange1"})
                                ):
                                    self.terminal.console.print(
                                        Markdown(result.removeprefix(MARKDOWN_RESULT))
                                    )
                            else:
                                # Plain-text layouts (/status, /cost) verbatim
                                # 纯文本版式原样打印
                                self.terminal.console.print(result)
                            self.terminal.console.print()
                    except SystemExit:
                        break
                    except Exception as e:
                        # A buggy command must not kill the whole session
                        # 命令自身的 bug 不能炸掉整个会话
                        self.terminal.show_error(f"Command failed: {type(e).__name__}: {e}")
                    finally:
                        await self._autosave()
                    continue

                # USER_INPUT hook: can block a turn before it reaches the LLM
                # USER_INPUT hook：可在输入到达 LLM 前拦截该轮
                try:
                    input_result = await self.hook_manager.run(
                        HookContext(
                            stage=HookStage.USER_INPUT,
                            metadata={"input_text": user_input},
                        )
                    )
                    if input_result.action == HookAction.BLOCK:
                        self.terminal.show_info(input_result.reason or "Input blocked by hook")
                        continue
                except Exception:
                    logger.warning("hook fire failed: pre-input", exc_info=True)
                    pass

                await self._handle_turn(user_input)
                # Force save after every completed turn: conversation data is
                # tiny (KBs) and the 30s throttle window would lose the last
                # turn on a hard kill. Throttling still applies to slash
                # commands above.
                # 每轮对话后强制存盘：对话数据只有几 KB，30 秒节流窗口会让
                # 硬杀进程丢掉最后一轮。斜杠命令仍走节流。
                await self._autosave(force=True)
        finally:
            await self.event_bus.emit(SessionEndEvent(session_id=self.session.metadata.session_id))
            # SESSION_END hook: auto-extract memories, cleanup, etc.
            # SESSION_END hook：自动提取记忆、清理等
            try:
                await self.hook_manager.run(
                    HookContext(
                        stage=HookStage.SESSION_END,
                        metadata={"session_id": self.session.metadata.session_id},
                    )
                )
            except Exception:
                logger.warning("hook fire failed: session-end", exc_info=True)
                pass
            self.session.metadata.closed_cleanly = True
            await self._autosave(force=True)
            if self.agent_loop.snapshot_store:
                self.agent_loop.snapshot_store.clear()
            if self.agent_loop.result_cache:
                self.agent_loop.result_cache.cleanup()
            await self.mcp_manager.disconnect_all()
            try:
                await self.hook_manager.run(
                    HookContext(
                        stage=HookStage.SHUTDOWN,
                        metadata={"session_id": self.session.metadata.session_id},
                    )
                )
            except Exception:
                logger.warning("hook fire failed: shutdown", exc_info=True)
                pass
            self.terminal.show_info("Goodbye!")

    async def _connect_mcp_servers(self) -> None:
        """Connect MCP servers listed in config (async — needs event loop).
        连接 config 中列出的 MCP 服务器（异步——需要事件循环）。"""
        if not self.config.mcp.servers:
            return
        for name, srv_cfg in self.config.mcp.servers.items():
            try:
                count = await self.mcp_manager.connect_server(name, srv_cfg, self.tool_registry)
                self.terminal.show_info(f"MCP: {name} connected ({count} tools)")
            except Exception as e:
                self.terminal.show_error(f"MCP: {name} failed: {e}")

    def _show_budget_warning(self) -> None:
        """Show budget warning lines when spend crosses 80%/100%.
        成本超过预算 80%/100% 时显示警告行（会话预算和总账预算分别检查）。"""
        cur = self.cost_tracker.currency
        e = self.terminal.theme.error
        w = self.terminal.theme.warning

        ratio, level = self.cost_tracker.budget_status()
        if level != "ok":
            spent = f"{cur}{self.cost_tracker.total_cost:.4f}"
            cap = f"{cur}{self.cost_tracker.budget:.2f}"
            if level == "over":
                msg = f"⚠ 会话预算超支: {spent} / {cap}"
                self.terminal.console.print(f"  [bold {e}]{msg}[/bold {e}]")
            else:
                msg = f"会话预算警告: {spent} / {cap} ({ratio * 100:.0f}%)"
                self.terminal.console.print(f"  [{w}]{msg}[/{w}]")

        t_ratio, t_level = self.cost_tracker.total_budget_status()
        if t_level != "ok":
            spent = f"{cur}{self.cost_tracker.all_time_cost:.4f}"
            cap = f"{cur}{self.cost_tracker.total_budget:.2f}"
            if t_level == "over":
                msg = f"⚠ 累计总预算超支: {spent} / {cap}"
                self.terminal.console.print(f"  [bold {e}]{msg}[/bold {e}]")
            else:
                msg = f"累计总预算警告: {spent} / {cap} ({t_ratio * 100:.0f}%)"
                self.terminal.console.print(f"  [{w}]{msg}[/{w}]")

    async def _autosave(self, force: bool = False) -> None:
        """Throttled auto-save; failures are silent (retried next turn).
        节流的自动保存；失败静默（下轮重试）。"""
        # Don't persist sessions with no conversation yet 无对话内容不落盘
        if not self.session.conversation.messages:
            return
        now = time.monotonic()
        if not force and now - self._last_autosave < AUTOSAVE_INTERVAL:
            return
        try:
            await self.session_store.save(self.session)
            self._last_autosave = now
        except OSError:
            logger.warning("autosave failed", exc_info=True)
            pass

    def _register_builtin_hooks(self) -> None:
        """Register default lifecycle hooks. 注册默认生命周期 hook。"""
        from mini_agent.memory.extraction import MemoryExtractor
        from mini_agent.memory.persistent import PersistentMemory

        app = self  # closure capture 闭包捕获

        async def _pre_llm_inject_memory(ctx: HookContext) -> HookResult:
            pm = PersistentMemory()
            entries: list = []
            if app.session.metadata.project_dir:
                entries += await pm.load_project_memory(app.session.metadata.project_dir)
            entries += await pm.load_user_memory()
            if entries and app.session.conversation.messages:
                marker = "\n\n--- Relevant memories ---\n"
                sp = app.session.conversation.system_prompt
                if marker not in sp:
                    mem_cfg = app.config.memory
                    if len(entries) > mem_cfg.recall_threshold:
                        # Selective recall: LLM picks the most relevant (P52)
                        # 选择性召回：LLM 挑选最相关的记忆
                        from mini_agent.memory.recall import MemoryRecall

                        last_user = next(
                            (
                                m.content
                                for m in reversed(app.session.conversation.messages)
                                if m.role == Role.USER and m.content
                            ),
                            "",
                        )
                        recall = MemoryRecall(app._llm)
                        selected = await recall.select_relevant(
                            entries, last_user, top_k=mem_cfg.recall_top_k
                        )
                    else:
                        selected = entries[:10]
                    if selected:
                        memory_text = "\n".join(f"- {e.content}" for e in selected)
                        app.session.conversation.system_prompt = sp + marker + memory_text
            return HookResult()

        async def _session_end_extract_memory(ctx: HookContext) -> HookResult:
            if not app.config.memory.auto_extract:
                return HookResult()
            try:
                pm = PersistentMemory()
                extractor = MemoryExtractor(
                    pm,
                    app._llm,
                    consolidation_threshold=app.config.memory.consolidation_threshold,
                )
                await extractor.maybe_extract(
                    app.session.conversation, app.session.metadata.project_dir
                )
            except Exception:
                logger.warning("hook fire failed: memory extraction", exc_info=True)
                pass
            return HookResult()

        self.hook_manager.register(HookStage.PRE_LLM, _pre_llm_inject_memory)
        self.hook_manager.register(HookStage.SESSION_END, _session_end_extract_memory)

    def _adopt_session(self, loaded: Session) -> None:
        """Switch the app to a loaded session (fixes stale ToolContext ref).
        切换到已加载的会话（同步修复 ToolContext 的过期引用）。"""
        self.session = loaded
        self._tool_context.session = loaded
        self.context_manager.adopt_boundary(loaded.conversation)
        self.context_manager.update_total(loaded.conversation)

    async def _maybe_restore_session(self) -> None:
        """On startup, offer to restore the most recent crashed session.
        启动时检测最近未正常关闭的会话并提示恢复。"""
        try:
            sessions = await self.session_store.list_sessions()
        except OSError:
            return
        cwd = str(Path.cwd())
        crashed = [
            s
            for s in sessions
            if not s.get("closed_cleanly", True)
            and str(s.get("project_dir", "")) == cwd
            and s["session_id"] != self.session.metadata.session_id
        ]
        if not crashed:
            return
        latest = crashed[0]  # newest first 已按最新在前排序
        prompt = (
            f"检测到未正常关闭的会话（{latest['total_turns']} 轮, "
            f"{str(latest['last_active'])[:19]}）。恢复它吗？"
        )
        if await self.terminal.ask_yes_no(prompt):
            loaded = await self.session_store.load(latest["session_id"])
            if loaded:
                loaded.metadata.closed_cleanly = False  # live again 恢复后重新算进行中
                self._adopt_session(loaded)
                self.terminal.show_info(
                    f"会话已恢复: {latest['session_id'][:12]}... "
                    f"({latest['total_turns']} 轮, {len(loaded.conversation.messages)} 条消息)"
                )
                return
            self.terminal.show_error(f"恢复失败: 无法加载 {latest['session_id']}")
        # Declined or failed: mark closed so we don't ask again
        # 拒绝或失败：标记已关闭，避免每次启动重复询问
        stale = await self.session_store.load(latest["session_id"])
        if stale:
            stale.metadata.closed_cleanly = True
            try:
                await self.session_store.save(stale)
            except OSError:
                logger.debug("stale session mark-clean failed", exc_info=True)
                pass

    async def _handle_turn(self, user_input: str) -> None:
        from mini_agent.ui.input_handler import expand_at_refs

        if "@" in user_input:
            user_input = expand_at_refs(user_input, self._tool_context.working_dir)

        await self.event_bus.emit(UserMessageEvent(content=user_input))

        self.session.conversation.append(Message(role=Role.USER, content=user_input))
        self.session.metadata.total_turns += 1

        try:
            await self.agent_loop.run(self.session.conversation)
            if self.agent_loop.stopped_early:
                self.terminal.show_error(
                    "⚠ Agent stopped early (iteration/loop limit reached). "
                    "Try a more specific question to reduce tool calls."
                )
            self.terminal.show_file_changes(self.agent_loop.last_turn_file_changes)
            turn_tokens = self.agent_loop.last_turn_tokens
            self.session.metadata.total_tokens_used += turn_tokens
            turn_cost, _ = self.cost_tracker.end_turn()
            cur = self.cost_tracker.currency
            cost_part = f" ({cur}{turn_cost:.4f})" if turn_cost else ""
            total_part = (
                f" ({cur}{self.cost_tracker.total_cost:.4f})"
                if self.cost_tracker.has_pricing
                else ""
            )
            self.terminal.show_info(
                f"tokens: {turn_tokens} this turn{cost_part}"
                f" / {self.session.metadata.total_tokens_used} total{total_part}"
            )
            self._show_budget_warning()
            self.cost_tracker.flush_to_ledger()
            self.terminal.console.print()
        except KeyboardInterrupt:
            self.agent_loop.cancel()
            self.terminal.show_info("Interrupted.")
            self.terminal.console.print()
        except Exception as e:
            self.terminal.show_error(_friendly_error(e))


def _friendly_error(e: Exception) -> str:
    """Convert raw exceptions to actionable user messages.
    将原始异常转换为可操作的用户提示。
    """
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        status = e.response.status_code
        if status == 401:
            return "API key 无效或未设置 (401)。请检查 .env 中的 OPENAI_API_KEY。"
        if status == 402:
            return "账户余额不足 (402)。请检查你的 API 账户。"
        if status == 429:
            return "请求过于频繁或配额耗尽 (429)。请稍后重试。"
        if status >= 500:
            return f"API 服务端错误 ({status})。请稍后重试。"
        return f"API 请求失败 ({status}): {e}"
    if isinstance(e, httpx.ConnectError):
        return "无法连接到 API 服务器。请检查网络或 OPENAI_BASE_URL 配置。"
    if isinstance(e, httpx.TimeoutException):
        return "API 请求超时。请检查网络或稍后重试。"
    return str(e)
