"""Spawn agents tool -- LLM autonomously delegates tasks to sub-agents.
派生代理工具——LLM 自主将任务委派给子代理并行执行。"""

from __future__ import annotations

from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema


class SpawnAgentsTool(Tool):
    """Lets the LLM spawn independent sub-agents for parallel work.
    允许 LLM 派生独立子代理进行并行工作。"""

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="spawn_agents",
            description=(
                "Spawn independent sub-agents to execute tasks in parallel. "
                "Each sub-agent has its own tools and conversation context. "
                "Returns a combined report of all sub-agent results."
            ),
            parameters=[
                ToolParameter(
                    name="tasks",
                    type="array",
                    description="List of task descriptions, one per sub-agent",
                ),
                ToolParameter(
                    name="isolated",
                    type="boolean",
                    description="Run each sub-agent in a Git worktree",
                    required=False,
                    default=False,
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        mgr = ctx.subagent_manager
        if mgr is None:
            return self.error_result("", "spawn_agents is not available in sub-agent context")

        tasks: list[str] = kwargs["tasks"]
        if not tasks:
            return self.error_result("", "No tasks provided")

        isolation = "worktree" if kwargs.get("isolated") else "none"

        ids = await mgr.spawn_parallel(tasks, isolation=isolation)
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
