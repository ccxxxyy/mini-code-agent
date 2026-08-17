"""Built-in slash commands. 内置斜杠命令。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mini_agent.extensions.slash_commands import MARKDOWN_RESULT, SlashCommand
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
            description=(
                "Memory management (usage: /memory "
                "[add|delete <text>|consolidate|export [dir]|import <dir>])"
            ),
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
            description="Manage skills (/skill [list|activate|deactivate|install|uninstall])",
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
            name="theme",
            description="Switch theme (usage: /theme [default|dark|light])",
            handler=_make_theme(app),
        )
    )
    reg.register(
        SlashCommand(
            name="plan",
            description="Toggle plan mode — read-only (usage: /plan [on|off])",
            handler=_make_plan(app),
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
            name="todo",
            description="Task list with dependencies (usage: /todo [add|done|start|delete|clear])",
            handler=_make_todo(app),
        )
    )
    reg.register(
        SlashCommand(
            name="cost",
            description="Cost dashboard: session + all-time spend (usage: /cost [turns|reset])",
            handler=_make_cost(app),
        )
    )
    reg.register(
        SlashCommand(
            name="record",
            description="Record tool calls (usage: /record start <name>|stop|cancel|list|delete)",
            handler=_make_record(app),
        )
    )
    reg.register(
        SlashCommand(
            name="replay",
            description="Replay a recorded tool sequence without LLM (usage: /replay <name>)",
            handler=_make_replay(app),
        )
    )
    reg.register(
        SlashCommand(
            name="undo",
            description="Roll back the last N turns (usage: /undo [N], default 1)",
            handler=_make_undo(app),
        )
    )
    reg.register(
        SlashCommand(
            name="fork",
            description="Branch into a new session (usage: /fork [N] to roll back N turns first)",
            handler=_make_fork(app),
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


def _make_todo(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.core.task_store import AmbiguousTaskError, TaskRecord

        store = app.task_store
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else ""

        def _fmt_ambiguous(err: AmbiguousTaskError) -> str:
            lines = [f"Ambiguous prefix '{err.query}', matches:"]
            for m in err.matches:
                lines.append(f"  {m.id[:12]}  {m.description[:40]}")
            return "\n".join(lines)

        if sub == "add":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: /todo add <description> [--after <id>]"
            desc_raw = parts[1].strip()
            blocked: list[str] = []
            if "--after" in desc_raw:
                desc_part, _, after_part = desc_raw.partition("--after")
                desc_raw = desc_part.strip()
                for raw_id in after_part.split(","):
                    aid = raw_id.strip()
                    if not aid:
                        continue
                    try:
                        match = store.get(aid)
                    except AmbiguousTaskError as e:
                        return _fmt_ambiguous(e)
                    if match:
                        blocked.append(match.id)
                    else:
                        return f"Task not found: {aid}"
            task = TaskRecord(description=desc_raw, blocked_by=blocked)
            store.add(task)
            all_tasks = store.load()
            short = store.min_unique_prefix(task.id, all_tasks)
            dep_note = ""
            if blocked:
                dep_note = (
                    " [blocked by: "
                    + ", ".join(store.min_unique_prefix(b, all_tasks) for b in blocked)
                    + "]"
                )
            return f"Added: {short} {task.description}{dep_note}"

        if sub in ("done", "start", "fail"):
            if len(parts) < 2:
                return f"Usage: /todo {sub} <id>"
            tid = parts[1].strip()
            status_map = {"done": "completed", "start": "in_progress", "fail": "failed"}
            new_status = status_map[sub]
            try:
                updated = store.update(tid, status=new_status)
            except AmbiguousTaskError as e:
                return _fmt_ambiguous(e)
            if not updated:
                return f"Task not found: {tid}"
            all_tasks = store.load()
            short = store.min_unique_prefix(updated.id, all_tasks)
            lines = [f"{short} → {new_status}"]
            if sub == "done":
                unblocked = store.find_unblocked_by(updated.id)
                for u in unblocked:
                    lines.append(
                        f"  unblocked: {store.min_unique_prefix(u.id, all_tasks)}"
                        f" {u.description[:40]}"
                    )
            if sub == "start" and updated.blocked_by:
                done_ids = {t.id for t in all_tasks if t.status in ("completed", "failed")}
                pending_deps = [b for b in updated.blocked_by if b not in done_ids]
                if pending_deps:
                    dep_shorts = ", ".join(
                        store.min_unique_prefix(b, all_tasks) for b in pending_deps
                    )
                    lines.append(f"  ⚠ still blocked by: {dep_shorts}")
            return "\n".join(lines)

        if sub == "delete":
            if len(parts) < 2:
                return "Usage: /todo delete <id>"
            tid = parts[1].strip()
            try:
                removed = store.remove(tid)
            except AmbiguousTaskError as e:
                return _fmt_ambiguous(e)
            return "Deleted." if removed else f"Task not found: {tid}"

        if sub == "clear":
            removed = store.clear_done()
            return f"Cleared {removed} completed/failed task(s)."

        # default: list 默认列出
        tasks = store.load()
        if not tasks:
            return "No tasks. /todo add <description> to create one."
        groups: dict[str, list[TaskRecord]] = {
            "pending": [],
            "in_progress": [],
            "completed": [],
            "failed": [],
        }
        for t in tasks:
            groups.get(t.status, groups["pending"]).append(t)
        if app.terminal.console.options.legacy_windows:
            labels = {
                "pending": "[ ] pending",
                "in_progress": "[~] in_progress",
                "completed": "[x] completed",
                "failed": "[!] failed",
            }
        else:
            labels = {
                "pending": "⏳ pending",
                "in_progress": "🔄 in_progress",
                "completed": "✅ completed",
                "failed": "❌ failed",
            }
        lines = ["**Tasks 任务列表：**"]
        for status in ("pending", "in_progress", "completed", "failed"):
            items = groups[status]
            if not items:
                continue
            lines.append(f"\n  {labels[status]}:")
            for t in items:
                short = store.min_unique_prefix(t.id, tasks)
                dep = ""
                if t.blocked_by:
                    dep = (
                        " [blocked by: "
                        + ", ".join(store.min_unique_prefix(b, tasks) for b in t.blocked_by)
                        + "]"
                    )
                tag = f" #{' #'.join(t.tags)}" if t.tags else ""
                lines.append(f"    {short}  {t.description}{dep}{tag}")
        return "\n".join(lines)

    return handler


def _make_cost(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        tracker = app.cost_tracker
        sub = args.strip().lower()

        if sub == "reset":
            if await app.terminal.ask_yes_no("重置从始至终的成本总账？(会话内统计不受影响)"):
                tracker.reset_ledger()
                return "All-time cost ledger reset. 总账已清零。"
            return "Cancelled."

        if sub == "turns":
            lines = ["**Per-turn Cost 逐轮成本（本会话）：**", ""]
            lines.extend(tracker.turn_lines())
            return "\n".join(lines)

        lines = ["**Cost Dashboard 成本仪表盘：**", ""]
        lines.extend(tracker.summary_lines())
        if not tracker.has_pricing:
            lines.append("")
            lines.append(
                "  (no pricing configured -- add a [cost] section to config.toml "
                "to see money amounts; see config.toml.example)"
            )
        return "\n".join(lines)

    return handler


def _make_record(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        rec = app.tool_recorder
        parts = args.strip().split(None, 1)
        sub = parts[0].lower() if parts else ""

        if sub == "start":
            if len(parts) < 2 or not parts[1].strip():
                return "Usage: /record start <name>"
            if rec.is_recording:
                return f"Already recording '{rec.recording_name}'. Stop or cancel it first."
            name = parts[1].strip().replace(" ", "_")
            rec.start(name)
            return (
                f"Recording '{name}' -- all successful tool calls from now on "
                f"will be captured. /record stop to save."
            )

        if sub == "stop":
            if not rec.is_recording:
                return "Not recording. /record start <name> to begin."
            name = rec.recording_name
            count, path = rec.stop()
            return f"Saved recording '{name}': {count} step(s) -> {path}"

        if sub == "cancel":
            if not rec.is_recording:
                return "Not recording."
            name = rec.recording_name
            rec.cancel()
            return f"Recording '{name}' discarded."

        if sub == "delete":
            if len(parts) < 2:
                return "Usage: /record delete <name>"
            name = parts[1].strip()
            return (
                f"Deleted recording '{name}'."
                if rec.delete(name)
                else f"Recording not found: {name}"
            )

        # default: list 默认列出
        items = rec.list_recordings()
        status = f"Recording now: '{rec.recording_name}'\n" if rec.is_recording else ""
        if not items:
            return status + "No saved recordings. /record start <name> to begin."
        lines = [status + "**Saved Recordings 已保存的录制：**"]
        for it in items:
            lines.append(f"  {it['name']} -- {it['steps']} step(s), {it['created_at']}")
        lines.append("\nReplay with /replay <name>")
        return "\n".join(lines)

    return handler


def _make_replay(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.core.tool_recorder import (
            builtin_variables,
            find_placeholders,
            render_template,
        )
        from mini_agent.models.message import ToolCall

        parts = args.strip().split()
        if not parts:
            return "Usage: /replay <name> [var=value ...]  (see /record list)"
        name = parts[0]
        rec_data = app.tool_recorder.load(name)
        if rec_data is None:
            return f"Recording not found: {name}"
        steps = rec_data.get("steps", [])
        if not steps:
            return f"Recording '{name}' has no steps."

        # Template variables: built-ins + user-supplied k=v pairs
        # 模板变量：内置变量 + 用户提供的 k=v
        variables = builtin_variables()
        for pair in parts[1:]:
            if "=" in pair:
                k, _, v = pair.partition("=")
                variables[k.strip()] = v

        missing = find_placeholders(steps) - set(variables)
        if missing:
            return (
                f"Missing template variable(s): {', '.join(sorted(missing))}\n"
                f"Usage: /replay {name} " + " ".join(f"{m}=<value>" for m in sorted(missing))
            )

        app.tool_recorder.suspended = True  # don't re-record the replay 防自录
        lines = [f"Replaying '{name}' ({len(steps)} steps):"]
        try:
            for i, step in enumerate(steps, 1):
                rendered_args = render_template(step["args"], variables)
                tc = ToolCall(id=f"replay-{i}", name=step["tool"], arguments=rendered_args)
                result = await app.agent_loop._execute_single_tool(tc)
                status = "FAILED" if result.is_error else "ok"
                lines.append(f"  [{i}/{len(steps)}] {step['tool']} ... {status}")
                if result.is_error:
                    lines.append(f"  Stopped: {result.output[:150]}")
                    break
        finally:
            app.tool_recorder.suspended = False
        return "\n".join(lines)

    return handler


def _make_undo(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.models.message import Role

        n = int(args.strip()) if args.strip().isdigit() else 1
        if n < 1:
            return "Usage: /undo [N] (N >= 1)"
        conv = app.session.conversation
        user_idxs = [i for i, m in enumerate(conv.messages) if m.role == Role.USER]
        if not user_idxs:
            return "Nothing to undo: conversation is empty."
        if len(user_idxs) < n:
            return f"Cannot undo {n} turn(s): only {len(user_idxs)} turn(s) in history."
        cut = user_idxs[-n]
        undone = conv.messages[cut]
        removed = len(conv.messages) - cut
        del conv.messages[cut:]
        app.context_manager.update_total(conv)
        app.session.metadata.total_turns = max(0, app.session.metadata.total_turns - n)

        # Restore files modified in the undone turns 恢复被撤销轮次修改的文件
        file_report: list[str] = []
        store = getattr(app.agent_loop, "snapshot_store", None)
        if store:
            turn_id = app.agent_loop.current_turn_id
            undo_ids = [t for t in range(turn_id - n + 1, turn_id + 1) if t > 0]
            file_report = store.restore_turns(undo_ids)
            app.agent_loop.current_turn_id = max(0, turn_id - n)

        preview = (undone.content or "")[:60]
        lines = [
            f"Rolled back {n} turn(s), removed {removed} message(s).",
            f'Undone: "{preview}"',
        ]
        if file_report:
            lines.append("Files restored 文件已恢复:")
            lines.extend(f"  - {r}" for r in file_report)
        lines.append(f"Context is now {app.context_manager.total_tokens} tokens.")
        return "\n".join(lines)

    return handler


def _make_fork(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        import copy

        from mini_agent.models.message import Role
        from mini_agent.models.session import Session

        n = int(args.strip()) if args.strip().isdigit() else 0
        old_id = app.session.metadata.session_id

        new_conv = copy.deepcopy(app.session.conversation)
        rolled = 0
        if n > 0:
            user_idxs = [i for i, m in enumerate(new_conv.messages) if m.role == Role.USER]
            if len(user_idxs) < n:
                return f"Cannot fork with rollback {n}: only {len(user_idxs)} turn(s) in history."
            del new_conv.messages[user_idxs[-n] :]
            rolled = n

        # Save the original line as cleanly closed -- we are deliberately
        # leaving it, so it must not trigger crash detection on next startup.
        # 原线标记为正常关闭再存盘——是主动离开，不能触发下次启动的崩溃检测。
        app.session.metadata.closed_cleanly = True
        await app.session_store.save(app.session)

        new_session = Session(conversation=new_conv)
        new_session.metadata.model = app.session.metadata.model
        new_session.metadata.project_dir = app.session.metadata.project_dir
        new_session.metadata.total_turns = sum(1 for m in new_conv.messages if m.role == Role.USER)
        # Inherit cumulative token spend: the branch carries the history it copied
        # 继承累计 token 消费——分支带走了对话历史，账单也应一起带走
        new_session.metadata.total_tokens_used = app.session.metadata.total_tokens_used
        app._adopt_session(new_session)
        await app.session_store.save(new_session)

        note = f" (rolled back {rolled} turn(s))" if rolled else ""
        return (
            f"Forked to new session {new_session.metadata.session_id}{note}.\n"
            f"Original session {old_id} saved -- return with /session load {old_id[:8]}"
        )

    return handler


def _make_clear(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        system_prompt = app.session.conversation.system_prompt
        app.session.conversation.messages.clear()
        app.session.conversation.total_tokens = 0
        app.session.conversation.system_prompt = system_prompt
        return "Conversation cleared."

    return handler


def _cost_status_line(app: Application) -> str:
    """One-line cost summary for /status. /status 里的单行成本摘要。"""
    tracker = app.cost_tracker
    if not tracker.has_pricing:
        return "  Cost: (no pricing configured -- see /cost)"
    cur = tracker.currency
    line = f"  Cost: {cur}{tracker.total_cost:.4f}"
    if tracker.budget > 0:
        line += f" / budget {cur}{tracker.budget:.2f}"
    return line


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
            _cost_status_line(app),
            f"  Context: {cm.total_tokens}/{cm.max_tokens} ({cm.usage_ratio:.0%})"
            f"  soft={cm._threshold:.0%} hard={cm._hard_threshold:.0%}"
            f"  breaker={cm._compress_failures}/{cm._max_compress_failures or '∞'}",
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
            await app._llm.prepare()
            return f"已切换到 `{arg}`: {app.config.llm.model} ({app.config.llm.provider})"

        # Fallback: treat as a raw model name (same provider/key)
        # 兜底: 作为裸模型名处理（沿用当前 provider 和密钥）
        app.config.llm.model = arg
        app.session.metadata.model = arg
        from mini_agent.llm.registry import ProviderRegistry

        app._llm = ProviderRegistry.create(app.config.llm)
        app.agent_loop._llm = app._llm
        app.agent_loop.model_name = arg  # cost attribution 成本归属
        await app._llm.prepare()
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

        if subcmd == "consolidate":
            from mini_agent.memory.consolidation import MemoryConsolidator

            if project_dir:
                entries = await pm.load_project_memory(project_dir)
            else:
                entries = await pm.load_user_memory()
            if len(entries) < 2:
                return "Nothing to merge (need at least 2 memories)."
            merged = await MemoryConsolidator(app._llm).consolidate(entries)
            if merged is None:
                return "Nothing to merge — no semantically related entries found."
            if project_dir:
                await pm.save_project_memory(project_dir, merged)
            else:
                await pm.save_user_memory(merged)
            return f"Merged {len(entries)} entries into {len(merged)}."

        if subcmd == "export":
            from mini_agent.memory.interop import export_memories

            project_entries = await pm.load_project_memory(project_dir) if project_dir else []
            user_entries = await pm.load_user_memory()
            all_export = project_entries + user_entries
            if not all_export:
                return "No memories to export."
            scopes = {e.id: "project" for e in project_entries}
            scopes.update({e.id: "user" for e in user_entries})
            if len(parts) > 1:
                dest = Path(parts[1]).expanduser()
            elif project_dir:
                dest = project_dir / ".mini-agent" / "memory-export"
            else:
                dest = Path("~/.mini-agent/memory-export").expanduser()
            paths = export_memories(all_export, dest, scopes)
            return f"Exported {len(paths) - 1} memories to {dest} (+ MEMORY.md index)"

        if subcmd == "import":
            from mini_agent.memory.interop import import_memories

            if len(parts) < 2:
                return "Usage: /memory import <dir>"
            src = Path(parts[1]).expanduser()
            if not src.is_dir():
                return f"Not a directory: {src}"
            imported = import_memories(src)
            if not imported:
                return f"No memory files found in {src}"

            existing_ids: set[str] = set()
            if project_dir:
                existing_ids |= {e.id for e in await pm.load_project_memory(project_dir)}
            existing_ids |= {e.id for e in await pm.load_user_memory()}

            added = skipped = 0
            for entry, scope in imported:
                if entry.id in existing_ids:
                    skipped += 1
                    continue
                # Route by recorded storage scope; files without one (foreign
                # formats) default to the project store when available.
                # 按记录的存储作用域路由；无作用域的文件（外来格式）默认进
                # 项目存储（若有）。
                if scope == "user" or not project_dir:
                    await pm.add_user_memory(entry)
                else:
                    await pm.add_project_memory(project_dir, entry)
                existing_ids.add(entry.id)
                added += 1
            note = f" ({skipped} duplicate(s) skipped)" if skipped else ""
            return f"Imported {added} memories from {src}{note}"

        if subcmd == "delete" and len(parts) > 1:
            query = parts[1]
            all_entries: list[MemoryEntry] = []
            if project_dir:
                all_entries += await pm.load_project_memory(project_dir)
            all_entries += await pm.load_user_memory()

            exact = [e for e in all_entries if e.id == query or e.id.startswith(query)]
            if len(exact) == 1:
                if project_dir:
                    await pm.delete_project_memory(project_dir, exact[0].id)
                await pm.delete_user_memory(exact[0].id)
                c = exact[0].content
                preview = c[:60] + "..." if len(c) > 60 else c
                return f"Deleted ({exact[0].id}): {preview}"

            q = query.lower()
            fuzzy = [e for e in all_entries if q in e.content.lower()]
            if len(fuzzy) == 1:
                if project_dir:
                    await pm.delete_project_memory(project_dir, fuzzy[0].id)
                await pm.delete_user_memory(fuzzy[0].id)
                c = fuzzy[0].content
                preview = c[:60] + "..." if len(c) > 60 else c
                return f"Deleted ({fuzzy[0].id}): {preview}"

            matches = exact if len(exact) > 1 else fuzzy
            if matches:
                lines = [
                    f"Found {len(matches)} matches for '{query}', use exact ID to delete:",
                ]
                for e in matches:
                    c = e.content
                    p = c[:50] + "..." if len(c) > 50 else c
                    lines.append(f"  `{e.id}` [{e.source}] {p}")
                return "\n".join(lines)

            return f"No memory matching '{query}'. Use `/memory` to see all entries."

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
            lines.append(f"  `{e.id}` [{e.source}] {e.content}{tags}")
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
            # Leaving the current session deliberately -- mark it cleanly
            # closed so it won't trigger crash detection on next startup.
            # 主动离开当前会话——标记正常关闭，避免下次启动误报崩溃。
            if app.session.conversation.messages:
                app.session.metadata.closed_cleanly = True
                try:
                    await store.save(app.session)
                except OSError:
                    pass
            loaded.metadata.closed_cleanly = False  # live again 恢复后重新算进行中
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

        if subcmd == "install" and len(parts) > 1:
            source = parts[1].strip()
            target = Path.home() / ".mini-agent" / "skills"
            try:
                name = await sr.install(source, target)
                return f"Installed skill: **{name}**"
            except ValueError as e:
                return f"Install failed: {e}"

        if subcmd == "uninstall" and len(parts) > 1:
            name = parts[1].strip()
            target = Path.home() / ".mini-agent" / "skills"
            if sr.uninstall(name, target):
                return f"Uninstalled skill: {name}"
            return f"Skill not found in user directory: {name}"

        if subcmd == "reload":
            loaded, lost = sr.reload(app.session.conversation)
            msg = f"Reloaded {loaded} skill(s)."
            if lost:
                msg += f"\n  Lost (no longer on disk): {', '.join(lost)}"
            return msg

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


def _make_theme(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.ui.themes import THEMES, get_theme

        arg = args.strip().lower()

        if not arg:
            current = app.terminal.theme.name
            lines = ["**Available themes 可用主题：**", ""]
            for name in sorted(THEMES):
                mark = " ← current" if name == current else ""
                lines.append(f"  `{name}`{mark}")
            return "\n".join(lines)

        new_theme = get_theme(arg)
        if arg not in THEMES:
            return f"Unknown theme: `{arg}`. Available: {', '.join(sorted(THEMES))}"

        app.terminal.set_theme(new_theme)
        app.trace_renderer.theme = new_theme
        app.teach_renderer.theme = new_theme

        theme_path = Path.home() / ".mini-agent" / ".theme"
        try:
            theme_path.parent.mkdir(parents=True, exist_ok=True)
            theme_path.write_text(arg, encoding="utf-8")
        except OSError:
            pass

        return f"Theme switched to: `{arg}` (persisted across restarts)"

    return handler


_PLAN_MODE_PROMPT = (
    "\n\n[PLAN MODE] You are in read-only planning mode. "
    "You can ONLY use read_file, glob, grep, bash for research. "
    "write_file, edit_file, delete_file are disabled. "
    "Analyze and plan, do NOT attempt to modify files."
)


def _make_plan(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        loop = app.agent_loop
        sub = args.strip().lower()

        if sub in ("", "on"):
            loop.plan_mode = True
            conv = app.session.conversation
            if _PLAN_MODE_PROMPT not in (conv.system_prompt or ""):
                conv.system_prompt = (conv.system_prompt or "") + _PLAN_MODE_PROMPT
            return "Plan mode **ON** — write tools disabled (read-only)."

        if sub == "off":
            loop.plan_mode = False
            conv = app.session.conversation
            if conv.system_prompt:
                conv.system_prompt = conv.system_prompt.replace(_PLAN_MODE_PROMPT, "")
            return "Plan mode **OFF** — all tools re-enabled."

        return "Usage: `/plan [on|off]` — toggle read-only planning mode."

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
                "  `/spawn --pane <task>` — run in a visible terminal pane "
                "(tmux/WT session: split pane; wt installed elsewhere: tab in "
                "a shared window)\n"
                "  `/spawn --wait <task>` — dispatch AND block for the result "
                "in one command (combines with --pane)\n"
                "  `/spawn --type <name> <task>` — use agent type "
                "(explore/plan/worker/verify)\n"
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

            board = SubAgentBoard(app.terminal.console, mgr, theme=app.terminal.theme)
            parts = raw.split(maxsplit=1)
            agent_id = parts[1].strip() if len(parts) > 1 else ""
            if agent_id:
                result = await board.run_while(mgr.wait(agent_id, timeout=900))
                return MARKDOWN_RESULT + _format_agent_result(result)
            results = await board.run_while(mgr.wait_all(timeout=900))
            if not results:
                return "No agents to wait for."
            if len(results) == 1:
                return MARKDOWN_RESULT + _format_agent_result(results[0])
            return MARKDOWN_RESULT + _format_agent_results_overview(results)

        if first == "cancel":
            parts = raw.split(maxsplit=1)
            agent_id = parts[1].strip() if len(parts) > 1 else ""
            if agent_id:
                mgr.cancel(agent_id)
                return f"Cancelled: `{agent_id}`"
            mgr.cancel_all()
            return "All SubAgents cancelled."

        # --- Spawn ---
        import re

        isolation = "none"
        task_text = raw
        if "--isolated" in task_text:
            isolation = "worktree"
            task_text = task_text.replace("--isolated", "").strip()

        pane = False
        if "--pane" in task_text:
            pane = True
            task_text = task_text.replace("--pane", "").strip()

        auto_wait = False
        if "--wait" in task_text:
            auto_wait = True
            task_text = task_text.replace("--wait", "").strip()

        agent_type_name: str | None = None
        type_match = re.search(r"--type[= ](\S+)", task_text)
        if type_match:
            agent_type_name = type_match.group(1)
            task_text = task_text[: type_match.start()] + task_text[type_match.end() :]
            task_text = task_text.strip()

        try:
            if pane:
                if not task_text:
                    return "No task provided."
                agent_id = await mgr.spawn_pane(task_text, agent_type=agent_type_name)
                if auto_wait:
                    from mini_agent.ui.board import SubAgentBoard

                    board = SubAgentBoard(app.terminal.console, mgr, theme=app.terminal.theme)
                    result = await board.run_while(mgr.wait(agent_id, timeout=900))
                    return MARKDOWN_RESULT + _format_agent_result(result)
                return (
                    f"SubAgent spawned in terminal pane: `{agent_id}`\n"
                    f"  Task: {task_text[:80]}\n"
                    "Watch it work in the new pane. "
                    "Use `/spawn wait` to collect the result."
                )

            if auto_wait and task_text and not task_text.startswith("-p "):
                from mini_agent.ui.board import SubAgentBoard

                agent_id = await mgr.spawn(
                    task_text, isolation=isolation, agent_type=agent_type_name
                )
                board = SubAgentBoard(app.terminal.console, mgr, theme=app.terminal.theme)
                result = await board.run_while(mgr.wait(agent_id, timeout=900))
                return MARKDOWN_RESULT + _format_agent_result(result)

            if task_text.startswith("-p "):
                tasks = [t.strip() for t in task_text[3:].split("|") if t.strip()]
                if not tasks:
                    return "No tasks provided. Use: `/spawn -p task1 | task2`"
                ids = await mgr.spawn_parallel(
                    tasks, isolation=isolation, agent_type=agent_type_name
                )
                lines = [f"Spawned {len(ids)} SubAgents:"]
                for aid, task in zip(ids, tasks):
                    lines.append(f"  `{aid}` — {task[:60]}")
                lines.append("Use `/spawn wait` to collect results.")
                return "\n".join(lines)

            if not task_text:
                return "No task provided."
            agent_id = await mgr.spawn(task_text, isolation=isolation, agent_type=agent_type_name)
            type_info = f"  Type: {agent_type_name}\n" if agent_type_name else ""
            return (
                f"SubAgent spawned: `{agent_id}`\n"
                f"  Task: {task_text[:80]}\n"
                f"{type_info}"
                f"  Isolation: {isolation}\n"
                "Use `/spawn wait {id}` or `/spawn wait` to collect result."
            )
        except ValueError as e:
            return str(e)

    return handler


def _format_agent_results_overview(results) -> str:
    """Multi-agent wait output: an overview table first, then one clearly
    numbered section per report -- worker outputs contain their own
    headings/rules and blur together without hard boundaries.
    多 Agent 等待输出：先总览表，再逐份编号分节——worker 输出自带
    标题/分隔线，没有硬边界会糊成一片。"""
    passed = sum(1 for r in results if r.success)
    lines = [
        f"# 结果总览：{passed}/{len(results)} 成功",
        "",
        "| # | Agent | 状态 | Tokens | Tools | 任务 |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        status = "PASS" if r.success else "FAIL"
        task_preview = " ".join(r.task.split())[:36]
        lines.append(
            f"| {i} | `{r.agent_id}` | {status} | {r.tokens_used:,} "
            f"| {r.tool_calls_made} | {task_preview} |"
        )
    for i, r in enumerate(results, 1):
        lines += ["", "---", "", f"# 报告 {i}/{len(results)}", ""]
        lines.append(_format_agent_result(r))
    return "\n".join(lines)


def _extract_deliverables(output: str) -> list[str]:
    """File names mentioned in the output that actually exist in the
    working directory -- these are the worker's deliverables. Mentions of
    source files elsewhere in the tree don't resolve from cwd and drop out.
    输出中提到且真实存在于工作目录的文件名——即 worker 的交付物；
    分析正文里提到的源码文件从 cwd 解析不到，自然被过滤。"""
    import re

    pattern = re.compile(r"[\w\-./\\]{2,}\.(?:md|txt|json|py|html|csv|ya?ml|log)\b")
    seen: list[str] = []
    for match in pattern.finditer(output):
        name = match.group(0).lstrip("./\\")
        if name not in seen and (Path.cwd() / name).is_file():
            seen.append(name)
    return seen[:8]


def _format_agent_result(r) -> str:
    """Markdown-friendly result block: metadata as a list, the worker's
    output as its own section so its headers/tables render properly.
    Markdown 友好的结果块：元数据用列表，worker 输出独立成段——
    其内部的标题/表格才能正确渲染。"""
    status = "PASS" if r.success else "FAIL"
    lines = [
        f"**[{status}] Agent `{r.agent_id}`**",
        "",
        f"- Task: {r.task[:80]}",
        f"- Tokens: {r.tokens_used} | Tools: {r.tool_calls_made}",
    ]
    deliverables = _extract_deliverables(r.output or "")
    if deliverables:
        lines.append("- 交付文件: " + ", ".join(f"`{f}`" for f in deliverables))
    if r.error:
        lines.append(f"- Error: {r.error}")
    if r.worktree_path:
        branch = r.worktree_path.name
        lines.append(f"- Worktree: {r.worktree_path}")
        lines.append(f"- Merge with: `git merge {branch}` (then clean up the worktree)")
    if r.output:
        # The output IS the deliverable -- never amputate the answer.
        # Only guard against pathological megabyte outputs.
        # 输出就是交付物——不截断答案，只防病态超大输出。
        output = r.output
        if len(output) > 8000:
            output = output[:8000] + f"\n... (truncated, {len(r.output)} chars total)"
        lines.append("")
        lines.append(output)
    return "\n".join(lines)


def _make_team(app: Application) -> HandlerFn:
    async def handler(args: str, ctx: Any) -> str:
        from mini_agent.core.planner import Planner
        from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember

        raw = args.strip()
        if not raw:
            return (
                "Usage: `/team <task description>` [--isolated] [--coordinator]\n"
                "Decomposes the task via Planner, runs SubAgents in parallel, "
                "and returns a summary report.\n"
                "--coordinator: Planner only decomposes and assigns, Workers do all file ops."
            )

        isolation = "none"
        coordinator = False
        task_text = raw
        for flag, setter in [("--isolated", "isolation"), ("--coordinator", "coordinator")]:
            if flag in task_text:
                if setter == "isolation":
                    isolation = "worktree"
                else:
                    coordinator = True
                task_text = task_text.replace(flag, "").strip()

        planner_llm = ProviderRegistry.create_for_role(app.config, "planner")
        planner = Planner(llm=planner_llm, max_steps=5, coordinator=coordinator)

        team = AgentTeam(
            config=TeamConfig(
                name="adhoc",
                members=[TeamMember(name="worker", role="generalist")],
                isolation=isolation,
                coordinator=coordinator,
            ),
            planner=planner,
            subagent_manager=app.subagent_manager,
        )

        from mini_agent.ui.board import SubAgentBoard

        board = SubAgentBoard(app.terminal.console, app.subagent_manager, theme=app.terminal.theme)
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
