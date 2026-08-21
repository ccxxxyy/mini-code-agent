"""Spawn agents tool -- LLM autonomously delegates tasks to sub-agents.
派生代理工具——LLM 自主将任务委派给子代理并行执行。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mini_agent.core.agent_types import AGENT_TYPES
from mini_agent.models.message import ToolResult
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
    """Pydantic model for spawn_agents parameters (P46). Auto-generates ToolSchema."""

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


class SpawnAgentsTool(Tool):
    """Lets the LLM spawn independent sub-agents for parallel work.
    允许 LLM 派生独立子代理进行并行工作。"""

    _name = "spawn_agents"
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
        "result arrives later as a '[Background agent ...]' message."
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

        # Background mode : fire-and-forget, results arrive as mailbox
        # messages on completion 后台模式：立即返回，完成后经 mailbox 通知
        if kwargs.get("background"):
            try:
                ids = await mgr.spawn_background(
                    tasks, isolation=isolation, agent_type=agent_type, names=names
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
                tasks, isolation=isolation, agent_type=agent_type, names=names
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
