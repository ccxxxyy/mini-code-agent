"""Agent Teams -- coordinate multiple agents on a shared project.
Agent 团队——协调多个 Agent 协作处理同一项目。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mini_agent.core.planner import Plan, Planner
from mini_agent.core.subagent import SubAgentManager, SubAgentResult


@dataclass
class TeamMember:
    name: str
    role: str  # e.g. "backend", "frontend", "tester" 例如“后端”“前端”“测试”
    allowed_tools: list[str] | None = None


@dataclass
class TeamConfig:
    name: str
    members: list[TeamMember] = field(default_factory=list)
    isolation: str = "none"  # "none" | "worktree" 隔离模式：无 | worktree


@dataclass
class TeamRunReport:
    task: str
    plan: Plan
    results: list[SubAgentResult] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.results) and all(r.success for r in self.results)

    def summary(self) -> str:
        lines = [f"Team run for: {self.task}", ""]
        for step, result in zip(self.plan.steps, self.results):
            status = "OK" if result.success else f"FAILED ({result.error})"
            lines.append(f"  [{status}] {step.description[:80]}")
            if result.output:
                lines.append(f"      → {result.output[:150]}")
        return "\n".join(lines)


class AgentTeam:
    """Orchestrator-strategy team: decompose task, assign to members, collect.
    编排者策略团队：分解任务，分派给成员，收集结果。
    """

    def __init__(
        self,
        config: TeamConfig,
        planner: Planner,
        subagent_manager: SubAgentManager,
    ) -> None:
        self._config = config
        self._planner = planner
        self._manager = subagent_manager

    def _match_member(self, role: str) -> TeamMember | None:
        """Find a team member matching the suggested role. 查找与建议角色匹配的团队成员。"""
        role_lower = role.lower()
        for member in self._config.members:
            if member.role.lower() in role_lower or role_lower in member.role.lower():
                return member
        return self._config.members[0] if self._config.members else None

    async def start(self, task: str, timeout: float | None = None) -> TeamRunReport:
        """Run the full orchestration: decompose -> assign -> spawn -> collect.
        运行完整编排流程：分解 -> 分派 -> 派生 -> 收集。

        1. Planner decomposes the task into subtasks
           Planner 将任务分解为子任务
        2. Each subtask is matched to a team member (by role)
           每个子任务按角色匹配到一个团队成员
        3. Sub-agents spawn in parallel (optionally in worktrees)
           SubAgent 并行派生（可选在 worktree 中隔离）
        4. Wait for all results and compile a report
           等待所有结果并汇总成报告
        """
        plan = await self._planner.decompose(task)

        agent_ids: list[str] = []
        for step in plan.steps:
            member = self._match_member(step.role)
            allowed_tools = member.allowed_tools if member else None
            step.status = "in_progress"
            agent_id = await self._manager.spawn(
                task=self._build_subtask_prompt(step, member),
                isolation=self._config.isolation,
                allowed_tools=allowed_tools,
            )
            agent_ids.append(agent_id)

        results = await self._manager.wait_all(agent_ids, timeout=timeout)

        for step, result in zip(plan.steps, results):
            step.status = "completed" if result.success else "failed"
            step.result = result.output or (result.error or "")

        return TeamRunReport(task=task, plan=plan, results=results)

    def stop(self) -> None:
        """Cancel all running team members. 取消所有运行中的团队成员。"""
        self._manager.cancel_all()

    @staticmethod
    def _build_subtask_prompt(step, member: TeamMember | None) -> str:
        role_line = f"You are acting as the {member.role} specialist.\n" if member else ""
        return f"{role_line}Subtask: {step.description}"
