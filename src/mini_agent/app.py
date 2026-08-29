"""Application orchestrator -- wires all layers together. 应用编排器——将所有层级组装在一起。"""

from __future__ import annotations

import asyncio
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
from mini_agent.memory.recall import RecallPrefetcher
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
a draft followed by corrections. If you cannot verify, say "unverified".
- IMPORTANT: When the user explicitly states they only want to discuss / \
not to make changes ("先不要动手" / "只讨论" / "let's just discuss" / \
"don't make changes yet"), that constraint remains in effect until the \
user gives an EXPLICIT action instruction ("开始动手" / "执行" / \
"go ahead" / "do it" / "make the changes"). Ambiguous confirmations \
like "对" / "嗯" / "好" / "right" / "ok" / "yes" only acknowledge \
understanding -- they do NOT lift the constraint. When in doubt, ask: \
"现在可以动手了吗？ / Ready to proceed with changes?\""""

_PLAN_MODE_PROMPT = (
    "\n\n[PLAN MODE] You are in read-only planning mode. "
    "You can ONLY use read_file, glob, grep, bash for research. "
    "write_file, edit_file, delete_file are disabled. "
    "Analyze and plan, do NOT attempt to modify files."
)


class Application:
    """Main application -- agent conversation loop. 主应用——Agent 对话循环。"""

    def __init__(self, config: AgentConfig) -> None:
        """Composition root: each _setup_* wires ONE subsystem; calls run in
        dependency order (later steps use attributes set by earlier ones).
        组合根：每个 _setup_* 只装配一个子系统；按依赖顺序调用
        （后面的步骤使用前面步骤设置的属性）。"""
        self.config = config
        self.event_bus = EventBus()
        self._working_dir = Path.cwd()

        self._setup_terminal()
        self._setup_session()
        self._setup_llm_and_tools()
        self._setup_security()
        self._setup_hooks()
        self._setup_memory()
        self._setup_agent_loop()
        self._setup_subagents()
        self._setup_event_notifications()
        self._setup_process_tools()
        self._setup_observers()
        self._setup_services()
        self._setup_startup_mode()
        self._setup_extensions()
        self._wire_terminal()
        self._wire_agent_callbacks()

    def _setup_terminal(self) -> None:
        """Theme preference + terminal renderer. 主题偏好 + 终端渲染器。"""
        # Load persisted theme preference 加载持久化的主题偏好
        from mini_agent.ui.themes import get_theme

        theme_path = Path.home() / ".mini-agent" / ".theme"
        if theme_path.is_file():
            try:
                self.config.theme = theme_path.read_text(encoding="utf-8").strip() or "default"
            except OSError:
                pass
        self.terminal = Terminal(theme=get_theme(self.config.theme))
        self.terminal.collapse_tool_calls = self.config.collapse_tool_calls

    def _setup_session(self) -> None:
        """Session + system prompt + instruction-file injection.
        会话 + 系统提示词 + 指令文件注入。"""
        self.session = Session()
        platform = f"{sys.platform} ({'Windows' if sys.platform == 'win32' else 'Unix'})"
        self.session.conversation.system_prompt = SYSTEM_PROMPT.format(
            model=self.config.llm.model,
            working_dir=self._working_dir,
            platform=platform,
            shell=detect_shell(),
        )
        self.session.metadata.model = self.config.llm.model
        self.session.metadata.project_dir = self._working_dir

        # Context awareness: auto-inject project/user instruction files
        # 上下文感知：自动注入项目/用户指令文件
        from mini_agent.memory.project_context import (
            load_project_instructions,
            load_user_instructions,
        )

        self._context_file_loaded: str | None = None
        marker = "\n\n--- Project instructions ---\n"
        parts: list[str] = []
        ctx = self.config.context
        user_inst = load_user_instructions(
            ctx.user_instructions_file, ctx.max_chars, ctx.max_include_depth
        )
        if user_inst:
            parts.append("[user instructions]\n" + user_inst)
        proj = load_project_instructions(
            self._working_dir, ctx.instruction_files, ctx.max_chars, ctx.max_include_depth
        )
        if proj:
            self._context_file_loaded = proj[0]
            parts.append(f"[{proj[0]}]\n{proj[1]}")
        if parts and marker not in self.session.conversation.system_prompt:
            self.session.conversation.system_prompt += marker + "\n\n".join(parts)

    def _setup_llm_and_tools(self) -> None:
        """LLM provider + tool registry + ToolContext.
        LLM Provider + 工具 registry + 工具上下文。"""
        self._llm = ProviderRegistry.create(self.config.llm)

        # Tool registry with all builtin tools 包含所有内置工具的工具 registry
        self.tool_registry = ToolRegistry()
        for tool_class in ALL_BUILTIN_TOOLS:
            tool = tool_class()  # type: ignore[abstract]
            if tool.schema.name in self.config.tools.enabled_tools:
                self.tool_registry.register(tool)

        from mini_agent.tools.file_state_cache import FileStateCache

        self._tool_context = ToolContext(
            working_dir=self._working_dir,
            session=self.session,
            event_bus=self.event_bus,
            config=self.config,
            file_state=(FileStateCache() if self.config.tools.enforce_read_before_edit else None),
        )

    def _setup_security(self) -> None:
        """Path guard + permission manager + OS sandbox.
        路径守卫 + 权限管理器接入终端确认 + OS 级沙箱。"""
        path_guard = PathGuard(
            tool_config=self.config.tools,
            security_config=self.config.security,
            project_dir=self._working_dir,
        )

        # Permission dialogs offer the persist follow-up ("a" -> save rule?);
        # hook/sub-agent confirms reuse the plain dialog without it.
        # 权限弹窗带持久化追问（a 后问是否存规则）；hook/子 agent 确认
        # 复用无追问的普通弹窗。
        async def _confirm_with_persist(prompt: str) -> bool | str:
            return await self.terminal.confirm(prompt, offer_persist=True)

        self.permission_manager = PermissionManager(
            config=self.config.security,
            path_guard=path_guard,
            confirm_callback=_confirm_with_persist,
            event_bus=self.event_bus,
        )
        self.permission_manager.working_dir = self._working_dir
        pm = self.permission_manager
        pm.shared_written_files = pm._session_written_files
        self.permission_manager.load_rule_files(
            user_file=Path.home() / ".mini-agent" / "permissions.toml",
            project_file=self._working_dir / ".mini-agent" / "permissions.toml",
        )

        # OS-level sandbox (Linux bwrap/unshare / macOS seatbelt / Windows admin
        # Low Integrity; non-admin = no file protection, no startup warning)
        # OS 级沙箱（Linux bwrap/unshare / macOS seatbelt / Windows 管理员 Low
        # Integrity；非管理员无文件保护、不打启动警告）
        self.sandbox_warning: str | None = None
        if self.config.security.sandbox:
            import platform
            import tempfile

            from mini_agent.security.sandbox import SandboxConfig, create_sandbox

            os_sandbox = create_sandbox()
            if os_sandbox and os_sandbox.available():
                sb_config = SandboxConfig(
                    allow_write=[str(self._working_dir), tempfile.gettempdir()],
                    deny_write=[str(Path.home() / ".mini-agent")],
                    network=self.config.security.sandbox_network,
                )
                bash_tool = self.tool_registry.get("bash")
                if bash_tool:
                    bash_tool.sandbox = os_sandbox  # type: ignore[attr-defined]
                    bash_tool.sandbox_config = sb_config  # type: ignore[attr-defined]
                if self.config.security.sandbox_auto_allow:
                    self.permission_manager.sandbox_auto_allow = True
            else:
                system = platform.system()
                if system == "Linux":
                    self.sandbox_warning = (
                        "[sandbox] sandbox=true but neither bubblewrap nor unshare "
                        "is available — sandbox is NOT active. "
                        "Install: sudo apt install bubblewrap"
                    )
                elif system == "Windows":
                    self.sandbox_warning = (
                        "[sandbox] sandbox=true but sandbox backend unavailable — "
                        "sandbox is NOT active."
                    )
                else:
                    self.sandbox_warning = (
                        "[sandbox] sandbox=true but no backend available — sandbox is NOT active."
                    )

    def _setup_hooks(self) -> None:
        """Hook manager: builtin lifecycle hooks + declarative config rules.
        Hook 管理器：内置生命周期 hook + 声明式配置规则。"""
        self.hook_manager = HookManager()
        self._register_builtin_hooks()
        # Declarative rules from `[[hooks]]` config (block/confirm/command/notify)
        # `[[hooks]]` 配置的声明式规则（阻止/确认/命令/通知）
        n_rules = register_hook_rules(
            self.hook_manager,
            self.config.hooks,
            command_runner=self._run_hook_command,
            notify_callback=self.terminal.show_info,
        )
        if n_rules:
            self.terminal.show_info(f"Loaded {n_rules} hook rule(s) from config")

    def _setup_memory(self) -> None:
        """Context manager + compressor + session store + background-worker
        fields. 上下文管理器 + 压缩器 + 会话存储 + 后台工作件字段。"""
        self.context_manager = ContextManager(self.config.memory)
        if self.config.memory.llm_summarize:
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
        # Memory subsystem background workers: startup consolidation task and
        # parallel recall prefetch (tech-notes §111)
        # 记忆子系统后台工作件：启动整固任务与并行召回预取
        self._consolidation_task: asyncio.Task | None = None
        self._recall_prefetcher: RecallPrefetcher | None = None

    def _setup_agent_loop(self) -> None:
        """Agent loop + undo snapshots + oversized-result spill cache.
        Agent 循环 + 撤销快照 + 超大结果溢写缓存。"""
        self.agent_loop = AgentLoop(
            llm=self._llm,
            tool_registry=self.tool_registry,
            event_bus=self.event_bus,
            config=self.config,
            tool_context=self._tool_context,
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
            self._working_dir / ".mini-agent" / "undo_snapshots",
            keep_turns=self.config.memory.undo_keep_turns,
        )

        # Spill oversized tool results to disk (compression-reread fix)
        # 超大工具结果溢写磁盘（压缩-重读膨胀根治）
        from mini_agent.memory.tool_result_cache import ToolResultCache

        self.result_cache = ToolResultCache(
            Path.home() / ".mini-agent" / "cache" / "results" / self.session.metadata.session_id,
            threshold_chars=self.config.memory.spill_threshold_chars,
            aggregate_chars=self.config.memory.aggregate_spill_chars,
        )
        self.agent_loop.result_cache = self.result_cache

    def _setup_subagents(self) -> None:
        """Worktree + sub-agent manager + cross-agent mailbox (/spawn, /team).
        Worktree + 子 Agent 管理器 + 跨 Agent 收件箱（/spawn、/team）。"""
        self.worktree_manager = WorktreeManager(
            repo_dir=self._working_dir,
            symlink_dirs=self.config.security.worktree_symlink_dirs,
        )
        worker_llm = ProviderRegistry.create_for_role(self.config, "worker")
        worker_profile = self.config.llm_profiles.get(self.config.worker_profile)
        worker_model = worker_profile.model if worker_profile else self.config.llm.model
        self.subagent_manager = SubAgentManager(
            llm=worker_llm,
            tool_registry=self.tool_registry,
            config=self.config,
            event_bus=self.event_bus,
            working_dir=self._working_dir,
            worktree_manager=self.worktree_manager,
            model_name=worker_model,
            confirm_callback=self.terminal.confirm,
            permission_manager=self.permission_manager,
        )

        # Inject SubAgentManager into ToolContext so spawn_agents tool can use it
        # 注入 SubAgentManager 到 ToolContext，供 spawn_agents 工具使用
        self._tool_context.subagent_manager = self.subagent_manager

        # Cross-agent mailbox: main agent inbox + send_message tool access
        # 跨 Agent 收件箱：主 Agent 收件箱 + send_message 工具接入
        self.mailbox = self.subagent_manager.mailbox
        self.mailbox.register("main")
        self._tool_context.mailbox = self.mailbox
        self.agent_loop.mailbox = self.mailbox

    def _setup_event_notifications(self) -> None:
        """Terminal notices for background-agent completion and context
        summarization. 后台 agent 完成与上下文摘要的终端提示订阅。"""
        from mini_agent.models.events import SubAgentCompleteEvent

        # Background agent completion notice : terminal hint when a
        # background-spawned agent finishes (result itself arrives via mailbox)
        # 后台 agent 完成提示：终端提醒（结果本身经 mailbox 注入下一轮对话）
        async def _on_background_complete(event: SubAgentCompleteEvent) -> None:
            if event.background:
                status = "finished" if event.success else "FAILED"
                self.terminal.show_info(
                    f"Background agent {event.agent_id} {status} — processing result..."
                )
                self.terminal.interrupt_input()

        self.event_bus.on(SubAgentCompleteEvent, _on_background_complete)

        from mini_agent.models.events import ContextSummaryDoneEvent, ContextSummaryStartEvent

        async def _on_ctx_summary_start(event: ContextSummaryStartEvent) -> None:
            self.terminal.show_info("Summarizing conversation for context fork...")

        async def _on_ctx_summary_done(event: ContextSummaryDoneEvent) -> None:
            self.terminal.show_info(
                f"Context summary ready ({event.duration_ms / 1000:.1f}s, {event.char_count} chars)"
            )

        self.event_bus.on(ContextSummaryStartEvent, _on_ctx_summary_start)
        self.event_bus.on(ContextSummaryDoneEvent, _on_ctx_summary_done)

    def _setup_process_tools(self) -> None:
        """Process tools: expose plan-mode control + ask_user callback.
        流程工具：暴露计划模式控制 + 结构化提问回调。"""
        import types as _types

        from mini_agent.models.permissions import PermissionMode

        self._tool_context.agent_loop_ref = _types.SimpleNamespace(
            get_plan_mode=lambda: self.agent_loop.plan_mode,
            # Route through the mode switch so leaving plan mode also resets
            # the permission matrix. 经模式切换器走——退出 plan 同步复位权限矩阵。
            set_plan_mode=lambda v: self.set_permission_mode(
                PermissionMode.PLAN if v else PermissionMode.DEFAULT
            ),
        )
        self._tool_context.ask_user_callback = self.terminal.ask_structured

    def _setup_observers(self) -> None:
        """Pure event-bus subscribers: trace/teach renderers, audit logger,
        tool recorder, cost tracker. 纯事件订阅者：trace/教学渲染器、
        审计日志、工具录制器、成本跟踪器。"""
        theme = self.terminal.theme

        # Trace renderer: /trace shows agent internals in real time
        # Trace 渲染器：/trace 实时展示 Agent 内部状态
        self.trace_renderer = TraceRenderer(self.terminal.console, theme=theme)
        self.trace_renderer.attach(self.event_bus)

        # Teach renderer: /explain shows tool explanations
        # 教学渲染器：/explain 显示工具解释
        self.teach_renderer = TeachRenderer(self.terminal.console, theme=theme)
        self.teach_renderer.attach(self.event_bus)

        # Audit logger: /audit writes tool calls to JSONL
        # 审计日志：/audit 将工具调用写入 JSONL
        self.audit_logger = AuditLogger(Path.home() / ".mini-agent")
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
            self.config.cost, ledger_path=Path.home() / ".mini-agent" / "cost_ledger.json"
        )
        self.cost_tracker.attach(self.event_bus)
        self.agent_loop.model_name = self.config.llm.model

    def _setup_services(self) -> None:
        """MCP manager + persistent task store. MCP 管理器 + 持久化任务系统。"""
        # MCP manager: connects remote tool servers at startup
        # MCP 管理器：启动时连接远程工具服务器
        from mini_agent.tools.mcp.client import MCPManager

        self.mcp_manager = MCPManager()
        self._tool_context.mcp_manager = self.mcp_manager

        # Persistent task system (S12): /todo command 持久化任务系统
        from mini_agent.core.task_store import TaskStore

        self.task_store = TaskStore(self._working_dir)
        self._tool_context.task_store = self.task_store

    def _setup_startup_mode(self) -> None:
        """Startup permission mode: [security].approval_mode, or plan when
        enable_plan_mode is set (back-compat).
        启动权限模式：[security].approval_mode；enable_plan_mode 兼容旧配置。"""
        from mini_agent.models.permissions import PermissionMode

        try:
            startup_mode = PermissionMode(self.config.security.approval_mode)
        except ValueError:
            logger.warning(
                "invalid approval_mode %r (valid: %s) — using default",
                self.config.security.approval_mode,
                "/".join(m.value for m in PermissionMode),
            )
            startup_mode = PermissionMode.DEFAULT
        if self.config.enable_plan_mode:
            startup_mode = PermissionMode.PLAN
        self.set_permission_mode(startup_mode)

    def _setup_extensions(self) -> None:
        """Skills, custom agent types, event listeners, slash commands,
        plugins. 技能、自定义 Agent 类型、事件监听插件、斜杠命令、插件生态。"""
        self.skill_registry = SkillRegistry(skill_dirs=[Path(d) for d in self.config.skill_dirs])
        self.skill_registry.load_all()
        self._tool_context.skill_registry = self.skill_registry
        # Recovery attachment includes skill state after compression
        # 压缩恢复附件包含技能状态
        self.context_manager.set_skill_provider(
            lambda: (self.skill_registry.invoked_names, self.skill_registry.active_names)
        )

        # Custom agent types: load *.md definitions from agent_dirs
        # 自定义 Agent 类型：从 agent_dirs 加载 *.md 定义
        from mini_agent.core.agent_type_loader import load_agent_types

        n_agent_types = load_agent_types(self.config.agent_dirs)
        if n_agent_types:
            self.terminal.show_info(f"Loaded {n_agent_types} custom agent type(s)")

        # Event listener plugins: external code observing all bus events
        # 事件监听插件：外部代码监听总线全部事件（统计/调试）
        from mini_agent.extensions.event_listeners import load_event_listeners

        self.loaded_listeners = load_event_listeners(self.config.listener_dirs, self.event_bus)
        if self.loaded_listeners:
            self.terminal.show_info(
                f"Loaded {len(self.loaded_listeners)} event listener(s): "
                + ", ".join(self.loaded_listeners)
            )

        # Slash commands
        self.slash_commands = SlashCommandRegistry()
        register_builtin_commands(self)

        # Plugin ecosystem: pip packages / local files registering
        # tools, commands, skills -- loaded before completion wiring so
        # plugin commands land in the `/` dropdown.
        # 插件生态：pip 包 / 本地文件注册工具、命令、技能——在补全接线前
        # 加载，让插件命令进入 `/` 下拉。
        from mini_agent.extensions.plugin_loader import PluginContext, load_plugins

        plugin_ctx = PluginContext(
            tool_registry=self.tool_registry,
            slash_commands=self.slash_commands,
            skill_registry=self.skill_registry,
            event_bus=self.event_bus,
            config=self.config,
        )
        self.loaded_plugins = load_plugins(
            self.config.plugin_dirs, plugin_ctx, self.config.disabled_plugins
        )
        if self.loaded_plugins:
            self.terminal.show_info(
                f"Loaded {len(self.loaded_plugins)} plugin(s): "
                + ", ".join(p.name for p in self.loaded_plugins)
            )

    def _wire_terminal(self) -> None:
        """Prompt-side wiring: completions, toolbar, mode cycler, Esc behavior.
        输入侧接线：补全、底部工具栏、权限模式循环、Esc 行为。"""
        # Wire slash command completions + @file completions to terminal
        # 将斜杠命令补全 + @文件补全接入终端
        self.terminal.set_working_dir(self._working_dir)
        self.terminal.set_slash_commands(
            [(c.name, c.description) for c in self.slash_commands.list_commands()]
        )

        # Bottom toolbar: show current LLM under the input line
        # 底部工具栏：在输入框下方显示当前 LLM
        self.terminal.set_toolbar_provider(self._toolbar_text)

        # shift+tab cycles the permission mode at the prompt
        # 输入提示符按 shift+tab 循环切换权限模式
        self.terminal.set_mode_cycler(self._cycle_permission_mode)

        # Esc at an empty prompt re-attaches an Esc-detached agent board
        # (submits "/spawn wait"); no detached group = Esc stays inert.
        # 空提示符按 Esc 重新附着转后台的面板（自动提交 /spawn wait）；
        # 无转后台组时 Esc 保持原样无动作。
        self.terminal.set_esc_command_provider(
            lambda: "/spawn wait" if self.subagent_manager.has_adopted_waits else None
        )

        # Double-Esc interrupt watcher 双 Esc 中断监听器
        from mini_agent.ui.esc_watcher import EscWatcher

        self._esc_watcher = EscWatcher()

    def _wire_agent_callbacks(self) -> None:
        """Agent-loop -> terminal rendering callbacks: streaming, thinking,
        tool-call display. Agent 循环 → 终端渲染回调：流式输出、思考过程、
        工具调用展示。"""

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

        from mini_agent.ui.terminal import _COLLAPSIBLE_TOOLS

        def _on_tool_assembling(name: str) -> None:
            # Read-only tools skip the early print: they render inside the
            # collapsible group at on_tool_start (a direct print here would
            # land outside the group and break the collapse).
            # 只读工具跳过提前直打：它们在 on_tool_start 时进入折叠组渲染
            # （这里直打会落在组外，破坏折叠）。
            if name in _COLLAPSIBLE_TOOLS and self.terminal.collapse_tool_calls:
                return
            if name not in _assembling_shown:
                _assembling_shown.add(name)
                self.terminal.flush_tool_group()
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
        """Bottom toolbar content: current model + switchable model count +
        permission mode (always shown so the active mode is never a guess).
        底部工具栏内容：当前模型 + 可切换模型数量 + 权限模式
        （始终显示，当前模式一目了然）。
        """
        text = f"LLM: {self.config.llm.model} ({self.config.llm.provider})"
        if len(self.config.llm_profiles) > 1:
            text += f"  |  {len(self.config.llm_profiles)} models, /model to switch"
        text += f"  |  mode: {self.permission_manager.mode.value}"
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
        if self.sandbox_warning:
            self.terminal.show_info(self.sandbox_warning)
        # Probe context window before the first turn's overflow check
        # 启动时预热探测上下文窗口，让首轮溢出检查就用上真实值
        await self._llm.prepare()
        await self._connect_mcp_servers()
        # Stale worktree cleanup: clean worktrees older than N days
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
        mem = self.config.memory
        if mem.session_cleanup_days > 0 or mem.crashed_session_cleanup_days > 0:
            try:
                n = await self.session_store.cleanup_stale(
                    mem.session_cleanup_days, mem.crashed_session_cleanup_days
                )
                if n:
                    self.terminal.show_info(f"Cleaned {n} stale session(s)")
            except Exception:
                logger.debug("stale session cleanup failed", exc_info=True)
                pass
        # Background memory consolidation: time + session-count gated, runs
        # invisibly while the user works (tech-notes §111)
        # 后台记忆整固：时间+会话数双门槛，用户工作时无感运行
        self.start_background_consolidation()
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

        from mini_agent.ui.terminal import _BG_INTERRUPT

        try:
            while True:
                try:
                    user_input = await self.terminal.get_user_input()
                except EOFError:
                    break
                except KeyboardInterrupt:
                    break

                if user_input is _BG_INTERRUPT:
                    await self._handle_background_delivery()
                    continue

                assert isinstance(user_input, str)
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
                    await self._process_pending_deliveries()
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
            # Stop background memory workers before teardown 收尾前停掉记忆后台工作件
            await self.stop_background_consolidation()
            if self._recall_prefetcher is not None:
                self._recall_prefetcher.cancel()
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
        self._effective_mcp_modes: dict[str, str] = {}
        for name, srv_cfg in self.config.mcp.servers.items():
            try:
                effective_cfg = srv_cfg
                if srv_cfg.loading == "native" and not self._is_native_capable():
                    from dataclasses import replace

                    effective_cfg = replace(srv_cfg, loading="dispatch")
                    self.terminal.show_info(
                        f"MCP: {name} native mode not supported by "
                        f"{self.config.llm.provider}, falling back to dispatch"
                    )
                count = await self.mcp_manager.connect_server(
                    name, effective_cfg, self.tool_registry
                )
                self._effective_mcp_modes[name] = effective_cfg.loading
                self.terminal.show_info(f"MCP: {name} connected ({count} tools)")
            except Exception as e:
                self.terminal.show_error(f"MCP: {name} failed: {e}")
        self._adjust_mcp_meta_tools()

    def _is_native_capable(self) -> bool:
        if self.config.llm.provider != "anthropic":
            return False
        base_url = (self.config.llm.base_url or "https://api.anthropic.com").rstrip("/")
        return "api.anthropic.com" in base_url

    def _adjust_mcp_meta_tools(self) -> None:
        modes = set(self._effective_mcp_modes.values()) if self._effective_mcp_modes else set()
        needs_search = bool(modes & {"dispatch", "native"})
        needs_call = "dispatch" in modes
        if not needs_search and self.tool_registry.get("tool_search"):
            self.tool_registry.unregister("tool_search")
        if not needs_call and self.tool_registry.get("mcp_call"):
            self.tool_registry.unregister("mcp_call")

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

    def start_background_consolidation(self) -> None:
        """Launch the gated background consolidation task once (terminal and
        remote modes both call this at startup; no-op when disabled or
        already running). 启动门槛化后台整固任务（终端与远程模式共用；
        已禁用或已在跑则 no-op）。"""
        if not self.config.memory.auto_consolidate:
            return
        if self._consolidation_task is not None and not self._consolidation_task.done():
            return
        self._consolidation_task = asyncio.create_task(self._background_consolidate())

    async def stop_background_consolidation(self) -> None:
        """Cancel a still-running consolidation task; never raises.
        取消仍在运行的整固任务；绝不抛异常。"""
        if self._consolidation_task is not None and not self._consolidation_task.done():
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except (asyncio.CancelledError, Exception):
                pass

    async def _background_consolidate(self) -> None:
        """Run gated memory consolidation in the background; never raises.
        后台运行门槛化记忆整固；绝不抛异常。"""
        try:
            from mini_agent.memory.consolidation import ConsolidationScheduler
            from mini_agent.memory.persistent import PersistentMemory

            scheduler = ConsolidationScheduler(
                PersistentMemory(),
                self.session_store,
                self._llm,
                min_hours=self.config.memory.consolidate_min_hours,
                min_sessions=self.config.memory.consolidate_min_sessions,
            )
            outcomes = await scheduler.run_once(self.session.metadata.project_dir)
            logger.debug("background consolidation outcomes: %s", outcomes)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("background consolidation failed", exc_info=True)

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
                        # Selective recall, prefetched in parallel with
                        # the main LLM call: the first round fires the task
                        # and proceeds unblocked; later rounds await the
                        # selection (usually already done); timeout/failure
                        # degrades to head-truncation
                        # 选择性召回，与主 LLM 调用并行预取：首轮发射任务后
                        # 直接放行；后续轮 await 结果（通常已完成）；
                        # 超时/失败降级头部截断
                        last_user = next(
                            (
                                m.content
                                for m in reversed(app.session.conversation.messages)
                                if m.role == Role.USER and m.content
                            ),
                            "",
                        )
                        if app._recall_prefetcher is None:
                            app._recall_prefetcher = RecallPrefetcher(
                                app._llm, timeout=mem_cfg.recall_timeout
                            )
                        selected = await app._recall_prefetcher.poll(
                            entries, last_user, top_k=mem_cfg.recall_top_k
                        )
                        if selected is None:
                            return HookResult()
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

    async def _run_hook_command(self, command: str, timeout: float) -> tuple[int, str]:
        """Execute a hook command directly — no interactive confirmation.
        Hook commands are user-configured in config.toml; prompting the
        user to approve their own config makes no sense and confuses UX
        (the dialog appears inside the tool block, looking like a tool
        permission check).  Only explicit DENY rules block hook commands.
        执行 hook 命令——不弹交互式确认。hook 命令是用户自己写在
        config.toml 的，再弹确认框问用户没有道理且混淆 UX。
        仅显式 DENY 规则可阻止 hook 命令。"""
        import asyncio
        from asyncio.subprocess import PIPE, STDOUT

        from mini_agent.models.permissions import PermissionScope

        if self.permission_manager._deny_rule_matches(PermissionScope.COMMAND, command):
            logger.warning("hook command denied by rule: %s", command)
            return (-1, "denied by rule")

        cwd = str(self.session.metadata.project_dir or Path.cwd())
        proc = await asyncio.create_subprocess_shell(command, stdout=PIPE, stderr=STDOUT, cwd=cwd)
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace").strip() if stdout else ""
            return (proc.returncode or 0, output)
        except TimeoutError:
            proc.kill()
            return (-1, "command timed out")

    def _adopt_session(self, loaded: Session) -> None:
        """Switch the app to a loaded session (fixes stale ToolContext ref).
        切换到已加载的会话（同步修复 ToolContext 的过期引用）。"""
        self.session = loaded
        self._tool_context.session = loaded
        # Reset recall prefetch: the pending selection was keyed to the old
        # session's message 重置召回预取：未完成的挑选是按旧会话消息算的
        if self._recall_prefetcher is not None:
            self._recall_prefetcher.cancel()
            self._recall_prefetcher = None
        self.context_manager.reset_state()
        self.context_manager.adopt_boundary(loaded.conversation)
        # Restore skill registry state from the boundary -- WITHOUT
        # re-injecting prompts (the restored system_prompt already has them)
        # 从边界恢复技能注册表状态——不重注入 prompt
        # （恢复的 system_prompt 已含）
        adopted = self.context_manager.adopted_skills
        if adopted:
            self.skill_registry.restore_state(*adopted)
        self.context_manager.update_total(loaded.conversation)

    async def _find_crashed_session(self) -> dict | None:
        """Find the newest crashed session of this project (metadata dict).
        查找本项目最新的未正常关闭会话（返回元数据 dict，无则 None）。"""
        try:
            sessions = await self.session_store.list_sessions()
        except OSError:
            return None
        cwd = str(Path.cwd())
        crashed = [
            s
            for s in sessions
            if not s.get("closed_cleanly", True)
            and str(s.get("project_dir", "")) == cwd
            and s["session_id"] != self.session.metadata.session_id
        ]
        return crashed[0] if crashed else None  # newest first 已按最新在前排序

    async def _maybe_restore_session(self) -> None:
        """On startup, offer to restore the most recent crashed session.
        启动时检测最近未正常关闭的会话并提示恢复。"""
        latest = await self._find_crashed_session()
        if latest is None:
            return
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

    def set_permission_mode(self, mode) -> None:
        """Switch the session permission mode; keeps the loop's plan-mode
        flag AND the plan system-prompt marker in sync (every entry point --
        /mode, /plan, shift+tab cycle, exit_plan tool -- goes through here).
        切换会话权限模式；同步 loop 的 plan 标志与 plan 系统提示词
        （/mode、/plan、shift+tab 循环、exit_plan 工具全部经此入口）。"""
        import asyncio

        from mini_agent.models.events import PermissionModeChangedEvent
        from mini_agent.models.permissions import PermissionMode

        old = self.permission_manager.mode
        self.permission_manager.mode = mode
        self.agent_loop.plan_mode = mode is PermissionMode.PLAN
        conv = self.session.conversation
        if mode is PermissionMode.PLAN:
            if _PLAN_MODE_PROMPT not in (conv.system_prompt or ""):
                conv.system_prompt = (conv.system_prompt or "") + _PLAN_MODE_PROMPT
        elif conv.system_prompt and _PLAN_MODE_PROMPT in conv.system_prompt:
            conv.system_prompt = conv.system_prompt.replace(_PLAN_MODE_PROMPT, "")
        if old is not mode:
            event = PermissionModeChangedEvent(old_mode=old.value, new_mode=mode.value)
            try:
                asyncio.get_running_loop().create_task(self.event_bus.emit(event))
            except RuntimeError:
                pass  # startup: no loop yet, initial mode needs no event 启动期无事件循环

    def _cycle_permission_mode(self) -> str:
        """Advance to the next permission mode (shift+tab at the prompt).
        Returns the new mode's name for toolbar display.
        切到下一个权限模式（输入提示符按 shift+tab）。返回新模式名。"""
        from mini_agent.models.permissions import PermissionMode

        order = [
            PermissionMode.DEFAULT,
            PermissionMode.ACCEPT_EDITS,
            PermissionMode.PLAN,
            PermissionMode.BYPASS,
        ]
        current = self.permission_manager.mode
        nxt = order[(order.index(current) + 1) % len(order)] if current in order else order[0]
        self.set_permission_mode(nxt)
        return nxt.value

    async def _handle_turn(self, user_input: str) -> None:
        from mini_agent.ui.input_handler import expand_at_refs

        if "@" in user_input:
            user_input = expand_at_refs(user_input, self._tool_context.working_dir)

        await self.event_bus.emit(UserMessageEvent(content=user_input))

        self.session.conversation.append(Message(role=Role.USER, content=user_input))
        self.session.metadata.total_turns += 1
        await self._run_agent_and_report()

    async def _process_pending_deliveries(self) -> None:
        """Process background results delivered WHILE a slash command ran
        (e.g. an agent finishing during a /spawn wait re-attach race) --
        they would otherwise sit in the mailbox until the next input wait
        (real-run: "why is there no result" after the re-attach race).
        处理斜杠命令执行期间投递的后台结果（如 re-attach 竞态中 agent
        恰好完成）——否则要等到下次输入等待才被处理
        （实测：竞态提示后用户问"为什么没有结果"）。"""
        if self.mailbox.has_pending("main"):
            await self._handle_background_delivery()

    async def _handle_background_delivery(self) -> None:
        """Process mailbox results from completed background agents.
        Loop until no more pending messages (another agent may complete
        while we are processing the first one).
        处理已完成的后台 agent 经 mailbox 投递的结果。循环直到无更多待处理
        消息（处理第一个结果期间可能又有 agent 完成）。"""
        while self.mailbox.has_pending("main"):
            self.session.conversation.append(
                Message(
                    role=Role.USER,
                    content=(
                        "[System notification] Background agent(s) have completed. "
                        "Their results are now available in your inbox. "
                        "Process them and report to the user."
                    ),
                )
            )
            self.session.metadata.total_turns += 1
            await self._run_agent_and_report()
            await self._autosave(force=True)

    async def _run_agent_and_report(self) -> None:
        """Run the agent loop and display post-turn stats.
        执行 agent loop 并显示轮次统计。"""
        try:
            await self.agent_loop.run(self.session.conversation)
            self.terminal.flush_tool_group()
            if self.agent_loop.stopped_early:
                if self.agent_loop.stop_reason == "confirm_denied":
                    self.terminal.show_error(
                        "⚠ Agent stopped: you denied an action that required "
                        "confirmation. It stopped instead of looking for a "
                        "workaround. Tell it how to proceed, or drop the goal."
                    )
                else:
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
            self.terminal.flush_tool_group()
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
