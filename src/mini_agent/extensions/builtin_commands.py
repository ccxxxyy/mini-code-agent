"""Built-in slash commands. 内置斜杠命令。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from mini_agent.extensions.slash_commands import SlashCommand
from mini_agent.llm.registry import ProviderRegistry

if TYPE_CHECKING:
    from mini_agent.app import Application

# Command handler signature 命令处理函数签名
HandlerFn = Callable[[str, Any], Awaitable[str]]


def register_builtin_commands(app: Application) -> None:
    """Register all built-in slash commands. 注册所有内置斜杠命令。"""
    reg = app.slash_commands

    reg.register(
        SlashCommand(
            name="help",
            description="Show all available commands",
            handler=_make_help(app),
        )
    )
    reg.register(
        SlashCommand(
            name="clear",
            description="Clear conversation history",
            handler=_make_clear(app),
        )
    )
    reg.register(
        SlashCommand(
            name="status",
            description="Show session status (model, turns, tokens)",
            handler=_make_status(app),
        )
    )
    reg.register(
        SlashCommand(
            name="model",
            description="Show or switch model (usage: /model [name])",
            handler=_make_model(app),
        )
    )
    reg.register(
        SlashCommand(
            name="compact",
            description="Manually compress conversation history",
            handler=_make_compact(app),
        )
    )
    reg.register(
        SlashCommand(
            name="memory",
            description="Show or add memory (usage: /memory [add <text>])",
            handler=_make_memory(app),
        )
    )
    reg.register(
        SlashCommand(
            name="session",
            description="Session management (usage: /session [list|save|load <id>|delete <id>])",
            handler=_make_session(app),
        )
    )
    reg.register(
        SlashCommand(
            name="tools",
            description="List all registered tools",
            handler=_make_tools(app),
        )
    )
    reg.register(
        SlashCommand(
            name="skill",
            description="Manage skills (usage: /skill [list|activate <name>|deactivate <name>])",
            handler=_make_skill(app),
        )
    )
    reg.register(
        SlashCommand(
            name="trace",
            description="Toggle agent internals trace (usage: /trace [on|off])",
            handler=_make_trace(app),
        )
    )
    reg.register(
        SlashCommand(
            name="explain",
            description="Toggle teaching mode (usage: /explain [on|off])",
            handler=_make_explain(app),
        )
    )
    reg.register(
        SlashCommand(
            name="audit",
            description="Audit logging (usage: /audit [on|off|verify])",
            handler=_make_audit(app),
        )
    )
    reg.register(
        SlashCommand(
            name="spawn",
            description="SubAgent dispatch (usage: /spawn <task> | /spawn list|wait|cancel)",
            handler=_make_spawn(app),
        )
    )
    reg.register(
        SlashCommand(
            name="team",
            description="Team orchestration (usage: /team <task> [--isolated])",
            handler=_make_team(app),
        )
    )
    reg.register(
        SlashCommand(
            name="quit",
            description="Exit the agent",
            handler=_make_quit(),
            hidden=True,
        )
    )
    reg.register(
        SlashCommand(
            name="exit",
            description="Exit the agent",
            handler=_make_quit(),
        )
    )


def _make_help(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        cmds = app.slash_commands.list_commands()
        lines = ["**Available Commands 可用命令：**", ""]
        for c in sorted(cmds, key=lambda x: x.name):
            lines.append(f"  `/{c.name}` — {c.description}")
        return "\n".join(lines)

    return handler


def _make_clear(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        system_prompt = app.session.conversation.system_prompt
        app.session.conversation.messages.clear()
        app.session.conversation.total_tokens = 0
        app.session.conversation.system_prompt = system_prompt
        return "Conversation cleared."

    return handler


def _make_status(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        import sys

        meta = app.session.metadata
        cm = app.context_manager
        cm.update_total(app.session.conversation)
        platform = "Windows" if sys.platform == "win32" else sys.platform
        lines = [
            "**Session Status 会话状态：**",
            f"  Model: {meta.model}",
            f"  Provider: {app.config.llm.provider}",
            f"  Platform: {platform}",
            f"  Turns: {meta.total_turns}",
            f"  Tokens used: {meta.total_tokens_used}",
            f"  Context: {cm.total_tokens}/{cm.max_tokens} ({cm.usage_ratio:.0%})",
            f"  Messages: {len(app.session.conversation.messages)}",
            f"  Session ID: {meta.session_id}",
        ]
        if meta.project_dir:
            lines.append(f"  Project: {meta.project_dir}")
        return "\n".join(lines)

    return handler


def _make_model(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        arg = args.strip()

        # No args: show current model + switchable models
        # 无参数：显示当前模型和可切换模型列表
        if not arg:
            lines = [f"当前 LLM: {app.config.llm.model} ({app.config.llm.provider})"]
            if app.config.llm_profiles:
                lines.append("")
                lines.append("**可切换模型 (用 /model <名称> 切换):**")
                for name, p in app.config.llm_profiles.items():
                    current = " ← 当前" if p.model == app.config.llm.model else ""
                    lines.append(f"  `{name}` — {p.model} ({p.provider}){current}")
            else:
                lines.append("提示: 在 .env 中配置 MINI_AGENT_MODELS 可定义多个可切换模型")
            return "\n".join(lines)

        # Named model match: switch full config (model+key+url+provider)
        # 匹配模型名称：切换完整配置（模型+密钥+地址+Provider）
        if arg in app.config.llm_profiles:
            app.switch_llm_profile(arg)
            return f"已切换到 `{arg}`: {app.config.llm.model} ({app.config.llm.provider})"

        # Fallback: treat as a raw model name (same provider/key)
        # 兜底: 作为裸模型名处理（沿用当前 provider 和密钥）
        app.config.llm.model = arg
        app.session.metadata.model = arg
        from mini_agent.llm.registry import ProviderRegistry

        app._llm = ProviderRegistry.create(app.config.llm)
        app.agent_loop._llm = app._llm
        return f"模型已切换为: {arg}"

    return handler


def _make_compact(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        cm = app.context_manager
        cm.update_total(app.session.conversation)
        before = cm.total_tokens
        before_msgs = len(app.session.conversation.messages)

        if cm._compressor is None:
            return "No compressor configured."

        target = int(cm.max_tokens * 0.5)
        await cm._compressor.compress(app.session.conversation, target)
        cm.update_total(app.session.conversation)

        after = cm.total_tokens
        after_msgs = len(app.session.conversation.messages)
        return f"Compressed: {before_msgs} → {after_msgs} messages, {before} → {after} tokens"

    return handler


def _make_memory(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.memory.persistent import MemoryEntry, PersistentMemory

        pm = PersistentMemory()
        project_dir = app.session.metadata.project_dir

        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "add" and len(parts) > 1:
            entry = MemoryEntry(content=parts[1], source="user")
            if project_dir:
                await pm.add_project_memory(project_dir, entry)
                return f"Added project memory: {parts[1]}"
            else:
                await pm.add_user_memory(entry)
                return f"Added user memory: {parts[1]}"

        # Default: list memories
        entries = []
        if project_dir:
            entries += await pm.load_project_memory(project_dir)
        entries += await pm.load_user_memory()

        if not entries:
            return "No memories stored. Use `/memory add <text>` to add one."

        lines = [f"**Memories 记忆 ({len(entries)})：**"]
        for e in entries:
            tags = f" [{', '.join(e.tags)}]" if e.tags else ""
            lines.append(f"  [{e.source}] {e.content}{tags}")
        return "\n".join(lines)

    return handler


def _make_session(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        store = app.session_store
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "save":
            path = await store.save(app.session)
            return f"Session saved: {path}"

        if subcmd == "list":
            sessions = await store.list_sessions()
            if not sessions:
                return "No saved sessions."
            lines = ["**Saved Sessions 已保存的会话：**"]
            for s in sessions:
                lines.append(
                    f"  {s['session_id'][:12]}... "
                    f"model={s['model']} turns={s['total_turns']} "
                    f"last={s['last_active'][:19]}"
                )
            return "\n".join(lines)

        if subcmd == "load" and len(parts) > 1:
            sid = parts[1].strip()
            sessions = await store.list_sessions()
            match = None
            for s in sessions:
                if s["session_id"].startswith(sid):
                    match = s["session_id"]
                    break
            if not match:
                return f"Session not found: {sid}"
            loaded = await store.load(match)
            if not loaded:
                return f"Failed to load session: {match}"
            app._adopt_session(loaded)
            return (
                f"Session loaded: {match[:12]}... "
                f"({loaded.metadata.total_turns} turns, "
                f"{len(loaded.conversation.messages)} messages, "
                f"model={loaded.metadata.model})"
            )

        if subcmd == "delete" and len(parts) > 1:
            sid = parts[1].strip()
            deleted = await store.delete(sid)
            return f"Deleted: {sid}" if deleted else f"Not found: {sid}"

        return "Usage: /session save | /session list | /session load <id> | /session delete <id>"

    return handler


def _make_tools(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        tools = app.tool_registry.list_tools()
        if not tools:
            return "No tools registered."
        lines = [f"**Registered Tools 已注册工具 ({len(tools)})：**"]
        for t in sorted(tools, key=lambda x: x.schema.name):
            lines.append(f"  `{t.schema.name}` — {t.schema.description[:80]}")
        return "\n".join(lines)

    return handler


def _make_skill(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        sr = app.skill_registry
        parts = args.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""

        if subcmd == "activate" and len(parts) > 1:
            name = parts[1].strip()
            if sr.activate(name, app.session.conversation):
                return f"Skill activated: {name}"
            return f"Skill not found: {name}"

        if subcmd == "deactivate" and len(parts) > 1:
            name = parts[1].strip()
            if sr.deactivate(name, app.session.conversation):
                return f"Skill deactivated: {name}"
            return f"Skill not active or not found: {name}"

        # Default: list skills
        skills = sr.list_skills()
        if not skills:
            return "No skills loaded."
        lines = [f"**Skills 技能包 ({len(skills)})：**"]
        for s in sorted(skills, key=lambda x: x.name):
            active = " [ACTIVE]" if sr.is_active(s.name) else ""
            lines.append(f"  `{s.name}` — {s.description}{active}")
        return "\n".join(lines)

    return handler


def _make_trace(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        arg = args.strip().lower()
        if arg == "on":
            app.trace_renderer.enabled = True
        elif arg == "off":
            app.trace_renderer.enabled = False
        else:
            # Toggle 切换
            app.trace_renderer.enabled = not app.trace_renderer.enabled
        state = "ON 开启" if app.trace_renderer.enabled else "OFF 关闭"
        return f"Trace mode: {state}"

    return handler


def _make_explain(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        tr = app.teach_renderer
        arg = args.strip().lower()

        if arg == "on":
            tr.enabled = True
        elif arg == "off":
            tr.enabled = False
        else:
            tr.enabled = not tr.enabled

        state = "ON" if tr.enabled else "OFF"
        return f"Teaching mode: {state}"

    return handler


def _make_audit(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.security.audit import verify_chain

        al = app.audit_logger
        arg = args.strip().lower()

        if arg == "verify":
            ok, count, detail = verify_chain(al.log_path)
            if ok:
                return f"Audit chain VERIFIED 完整性验证通过: {count} entries, no tampering."
            return (
                f"Audit chain BROKEN 完整性验证失败: {detail} "
                f"({count} entries verified before failure)"
            )

        if arg == "on":
            al.set_enabled(True)
        elif arg == "off":
            al.set_enabled(False)
        else:
            al.set_enabled(not al.enabled)

        state = "ON 开启（跨重启持久）" if al.enabled else "OFF 关闭"
        info = f"  Log: {al.log_path}\n  Entries: {al.entry_count}"
        return f"Audit mode: {state}\n{info}"

    return handler


def _make_spawn(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        mgr = app.subagent_manager
        raw = args.strip()

        if not raw:
            return (
                "Usage:\n"
                "  `/spawn <task>` — dispatch a single SubAgent\n"
                "  `/spawn -p <task1> | <task2>` — parallel dispatch\n"
                "  `/spawn --isolated <task>` — run in git worktree\n"
                "  `/spawn list` — show active agents\n"
                "  `/spawn wait [id]` — wait for result\n"
                "  `/spawn cancel [id]` — cancel agent(s)"
            )

        # --- Subcommands ---
        first = raw.split()[0].lower()

        if first == "list":
            active = mgr.list_active()
            if not active:
                return "No active SubAgents."
            lines = [f"**Active SubAgents ({len(active)}):**"]
            for aid in active:
                phase = mgr.get_status(aid)
                lines.append(f"  `{aid}` — {phase or 'unknown'}")
            return "\n".join(lines)

        if first == "wait":
            from mini_agent.ui.board import SubAgentBoard

            board = SubAgentBoard(app.terminal.console, mgr)
            parts = raw.split(maxsplit=1)
            agent_id = parts[1].strip() if len(parts) > 1 else ""
            if agent_id:
                result = await board.run_while(mgr.wait(agent_id, timeout=300))
                return _format_agent_result(result)
            results = await board.run_while(mgr.wait_all(timeout=300))
            if not results:
                return "No agents to wait for."
            return "\n\n".join(_format_agent_result(r) for r in results)

        if first == "cancel":
            parts = raw.split(maxsplit=1)
            agent_id = parts[1].strip() if len(parts) > 1 else ""
            if agent_id:
                mgr.cancel(agent_id)
                return f"Cancelled: `{agent_id}`"
            mgr.cancel_all()
            return "All SubAgents cancelled."

        # --- Spawn ---
        isolation = "none"
        task_text = raw
        if "--isolated" in task_text:
            isolation = "worktree"
            task_text = task_text.replace("--isolated", "").strip()

        if task_text.startswith("-p "):
            tasks = [t.strip() for t in task_text[3:].split("|") if t.strip()]
            if not tasks:
                return "No tasks provided. Use: `/spawn -p task1 | task2`"
            ids = await mgr.spawn_parallel(tasks, isolation=isolation)
            lines = [f"Spawned {len(ids)} SubAgents:"]
            for aid, task in zip(ids, tasks):
                lines.append(f"  `{aid}` — {task[:60]}")
            lines.append("Use `/spawn wait` to collect results.")
            return "\n".join(lines)

        if not task_text:
            return "No task provided."
        agent_id = await mgr.spawn(task_text, isolation=isolation)
        return (
            f"SubAgent spawned: `{agent_id}`\n"
            f"  Task: {task_text[:80]}\n"
            f"  Isolation: {isolation}\n"
            "Use `/spawn wait {id}` or `/spawn wait` to collect result."
        )

    return handler


def _format_agent_result(r) -> str:
    status = "PASS" if r.success else "FAIL"
    lines = [
        f"**[{status}] Agent `{r.agent_id}`**",
        f"  Task: {r.task[:80]}",
        f"  Tokens: {r.tokens_used} | Tools: {r.tool_calls_made}",
    ]
    if r.output:
        lines.append(f"  Output: {r.output[:200]}")
    if r.error:
        lines.append(f"  Error: {r.error}")
    return "\n".join(lines)


def _make_team(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.core.planner import Planner
        from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember

        raw = args.strip()
        if not raw:
            return (
                "Usage: `/team <task description>` [--isolated]\n"
                "Decomposes the task via Planner, runs SubAgents in parallel, "
                "and returns a summary report."
            )

        isolation = "none"
        task_text = raw
        if "--isolated" in task_text:
            isolation = "worktree"
            task_text = task_text.replace("--isolated", "").strip()

        planner_llm = ProviderRegistry.create_for_role(app.config, "planner")
        planner = Planner(llm=planner_llm, max_steps=5)

        team = AgentTeam(
            config=TeamConfig(
                name="adhoc",
                members=[TeamMember(name="worker", role="generalist")],
                isolation=isolation,
            ),
            planner=planner,
            subagent_manager=app.subagent_manager,
        )

        from mini_agent.ui.board import SubAgentBoard

        board = SubAgentBoard(app.terminal.console, app.subagent_manager)
        try:
            report = await board.run_while(team.start(task_text, timeout=300))
        except Exception as e:
            return f"Team execution failed: {e}"

        status = "SUCCESS" if report.success else "PARTIAL FAILURE"
        tokens = sum(r.tokens_used for r in report.results)
        header = f"**Team Run [{status}]** — {len(report.plan.steps)} steps, {tokens} tokens"
        return f"{header}\n\n{report.summary()}"

    return handler


def _make_quit() -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        raise SystemExit(0)

    return handler
