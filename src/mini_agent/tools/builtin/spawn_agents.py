"""Spawn agents tool -- LLM autonomously delegates tasks to sub-agents.
派生代理工具——LLM 自主将任务委派给子代理并行执行。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.core.agent_types import AGENT_TYPES
from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext


def _agent_type_description() -> str:
    """Build agent_type field description from the live AGENT_TYPES registry.
    从当前注册表动态生成 agent_type 字段描述。"""
    parts = []
    for t in sorted(AGENT_TYPES.values(), key=lambda d: d.name):
        desc = t.description or t.name
        parts.append(f"'{t.name}' ({desc})")
    return "Agent type: " + ", ".join(parts)


class SpawnAgentsParams(BaseModel):
    """Pydantic model for spawn_agents parameters. Auto-generates ToolSchema."""

    tasks: list[str] = Field(description="List of task descriptions, one per sub-agent")
    names: list[str] | None = Field(
        default=None,
        description=(
            "Optional short role names, one per task (e.g. ['explorer', 'summarizer']). "
            "Agents can then message each other by name instead of hex id."
        ),
    )
    isolated: bool = Field(
        default=False,
        description="Run each sub-agent in a Git worktree",
    )
    agent_type: str | None = Field(
        default=None,
        description=(
            "Agent type: 'explore' (read-only research), 'plan' (read-only planning), "
            "'worker' (full tools, default), 'verify' (read-only, PASS/FAIL judgment)"
        ),
    )
    background: bool = Field(
        default=False,
        description=(
            "Run in background: returns immediately with agent ids instead of "
            "blocking. Each agent's result is delivered to you as a message "
            "when it completes -- continue with other work meanwhile."
        ),
    )
    inherit_context: bool = Field(
        default=False,
        description=(
            "Inherit conversation context: each sub-agent's system prompt "
            "includes an LLM-generated summary of the discussion so far. Use "
            "when the task refers to things discussed earlier (e.g. 'implement "
            "what we discussed'). Costs one extra LLM call to summarize."
        ),
    )


class SpawnAgentsTool(Tool):
    """Lets the LLM spawn independent sub-agents for parallel work.
    允许 LLM 派生独立子代理进行并行工作。"""

    _name = "spawn_agents"

    category = ToolCategory.EXECUTE
    _description = (
        "Spawn independent sub-agents to execute tasks in parallel. "
        "Each sub-agent has its own tools and conversation context. "
        "Returns a combined report of all sub-agent results. "
        "IMPORTANT: by default this call BLOCKS until all sub-agents finish, "
        "so tasks that must run concurrently (e.g. agents that message each "
        "other via send_message) MUST be passed in ONE call -- separate calls "
        "run sequentially and cannot communicate. Sub-agents spawned together "
        "are told each other's agent ids and can exchange messages mid-task. "
        "Set background=true to return immediately instead: each agent's "
        "result arrives later as a '[Background agent ...]' message. "
        "Set inherit_context=true when the task refers to the current "
        "discussion -- sub-agents then receive a summary of it."
    )
    params_model = SpawnAgentsParams

    @property
    def schema(self):
        base = super().schema
        props = base.raw_parameters and base.raw_parameters.get("properties", {})
        if props and "agent_type" in props:
            props["agent_type"]["description"] = _agent_type_description()
        return base

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        mgr = ctx.subagent_manager
        if mgr is None:
            return self.error_result("", "spawn_agents is not available in sub-agent context")

        # Plan mode: spawning is allowed ONLY when the manager propagates the
        # permission stack -- child views carry the parent's PLAN mode, so
        # sub-agents can research but their writes are denied at the
        # permission layer. Without a gate, any spawn is a read-only escape
        # hatch (ungated sub-agents can write files).
        # plan 模式：仅当管理器传播权限栈时允许派生——子视图携带父级 PLAN
        # 模式，子 agent 可研究但写操作在权限层被拒。无门禁时任何派生都是
        # 只读逃逸口（无门子 agent 可写文件）。
        if (
            ctx.agent_loop_ref is not None
            and ctx.agent_loop_ref.get_plan_mode()
            and not mgr.has_permission_gate
        ):
            return self.error_result(
                "",
                "Plan mode is read-only: spawn_agents is disabled here because "
                "sub-agents would run WITHOUT a permission gate. Present your "
                "plan and get user approval via exit_plan_mode first.",
            )

        tasks: list[str] = kwargs["tasks"]
        if not tasks:
            return self.error_result("", "No tasks provided")

        names: list[str] | None = kwargs.get("names")
        if names is not None:
            if len(names) != len(tasks):
                return self.error_result(
                    "", f"names length ({len(names)}) must match tasks ({len(tasks)})"
                )
            cleaned = [n.strip() for n in names]
            if len(set(cleaned)) != len(cleaned) or any(n in ("main", "*") for n in cleaned):
                return self.error_result("", "names must be unique and must not be 'main' or '*'")
            names = cleaned

        isolation = "worktree" if kwargs.get("isolated") else "none"
        agent_type = kwargs.get("agent_type")

        # Fork-style context inheritance: summarize the parent
        # conversation once, inject into every spawned agent's system prompt.
        # background + inherit_context: defer both summary and spawn to a
        # background task so execute() returns instantly.
        # 摘要式上下文继承：父对话摘要一次，注入每个子 agent 的 system prompt。
        # background + inherit_context：摘要和 spawn 整体放后台，execute 立即返回。
        context_summary = ""
        if kwargs.get("inherit_context") and ctx.session is not None:
            if kwargs.get("background"):
                import asyncio
                import logging

                _log = logging.getLogger(__name__)
                msgs_snapshot = list(ctx.session.conversation.messages)

                async def _deferred_fork_spawn() -> None:
                    try:
                        summary = await mgr.build_context_summary(msgs_snapshot)
                        await mgr.spawn_background(
                            tasks,
                            isolation=isolation,
                            agent_type=agent_type,
                            names=names,
                            context_summary=summary,
                        )
                    except Exception as exc:
                        _log.warning("deferred fork spawn failed: %s", exc, exc_info=True)

                task = asyncio.create_task(_deferred_fork_spawn())
                mgr._notify_tasks.add(task)
                task.add_done_callback(mgr._notify_tasks.discard)
                return ToolResult(
                    call_id="",
                    name="spawn_agents",
                    output=(
                        f"Spawning {len(tasks)} background agent(s) with context fork "
                        "— summary is generating in the background. You will receive "
                        "'[Background agent ...]' messages when each one completes."
                    ),
                )
            context_summary = await mgr.build_context_summary(ctx.session.conversation.messages)

        # Background mode (no inherit_context): fire-and-forget, results
        # arrive as mailbox messages on completion
        # 后台模式（无 inherit_context）：立即返回，完成后经 mailbox 通知
        if kwargs.get("background"):
            try:
                ids = await mgr.spawn_background(
                    tasks,
                    isolation=isolation,
                    agent_type=agent_type,
                    names=names,
                    context_summary=context_summary,
                )
            except ValueError as e:
                return self.error_result("", str(e))
            id_list = ", ".join(ids)
            return ToolResult(
                call_id="",
                name="spawn_agents",
                output=(
                    f"Spawned {len(ids)} background agent(s): {id_list}. "
                    "You will receive a '[Background agent ...]' message from "
                    "each one when it completes -- continue with other work."
                ),
            )

        try:
            ids = await mgr.spawn_parallel(
                tasks,
                isolation=isolation,
                agent_type=agent_type,
                names=names,
                context_summary=context_summary,
            )
        except ValueError as e:
            return self.error_result("", str(e))
        results = await mgr.wait_all(ids, timeout=300)

        lines: list[str] = []
        for r in results:
            status = "OK" if r.success else "FAILED"
            lines.append(f"[{status}] {r.task[:80]}")
            if r.output:
                lines.append(f"  {r.output[:500]}")
            if r.error:
                lines.append(f"  Error: {r.error}")

        summary = "\n\n".join(lines) or "No results"
        passed = sum(1 for r in results if r.success)
        header = f"Sub-agent results: {passed}/{len(results)} succeeded\n\n"
        return ToolResult(
            call_id="",
            name="spawn_agents",
            output=header + summary,
        )
