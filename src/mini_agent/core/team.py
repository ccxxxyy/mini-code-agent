"""Agent Teams -- coordinate multiple agents on a shared project.
Agent 团队——协调多个 Agent 协作处理同一项目。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from mini_agent.core.planner import Plan, Planner
from mini_agent.core.subagent import SubAgentManager, SubAgentResult

logger = logging.getLogger(__name__)

# Tools stripped from non-writer steps 非写文件步骤被剥夺的工具
_WRITE_TOOLS = {"write_file", "edit_file"}

# Noise directories excluded from the structure scan 结构扫描排除的噪音目录
_SCAN_IGNORE = {".git", ".venv", "node_modules", "__pycache__", ".mini-agent", "dist", ".idea"}


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
    coordinator: bool = False  # Coordinator mode: Planner only decomposes, Workers do all file ops


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

        Steps run in dependency batches: steps whose depends_on are all
        satisfied spawn in parallel; dependent steps wait for the previous
        batch. A step whose dependency failed is skipped as failed.
        步骤按依赖分批执行：依赖全部满足的步骤并行派生；有依赖的步骤等待
        前一批完成。依赖失败的步骤直接标记失败跳过。
        """
        # Feed the planner the real project layout so it does not assume
        # a generic web-app structure 给 Planner 真实项目结构，避免套用通用 web 模板
        deep = self._config.coordinator  # coordinator needs richer context 协调者需要更丰富的上下文
        context = self._scan_project_structure(
            depth=3 if deep else 2, max_lines=120 if deep else 80
        )
        plan = await self._planner.decompose(task, context=context)

        results_by_index: dict[int, SubAgentResult] = {}
        pending = list(plan.steps)

        while pending:
            # Steps whose dependencies are all resolved 依赖已全部解决的步骤
            batch = [s for s in pending if all(d in results_by_index for d in s.depends_on)]
            if not batch:
                batch = pending[:]  # circular/invalid deps: run all 循环依赖兜底：全部执行

            ready: list = []
            for step in batch:
                failed_deps = [d for d in step.depends_on if not results_by_index[d].success]
                if failed_deps:
                    step.status = "failed"
                    step.result = f"Skipped: dependency step(s) {failed_deps} failed"
                    results_by_index[step.index] = SubAgentResult(
                        agent_id="",
                        task=step.description,
                        success=False,
                        output="",
                        error=step.result,
                    )
                else:
                    ready.append(step)

            agent_ids: list[str] = []
            for step in ready:
                member = self._match_member(step.role)
                allowed_tools = member.allowed_tools if member else None
                # Enforce read-only for non-writer steps: strip write tools
                # so prompts can't be ignored -- capability removal, not persuasion
                # 非写文件步骤强制只读：剥夺写工具能力，而非依赖 prompt 自觉
                if not step.writes_files:
                    base = allowed_tools or [
                        t.schema.name for t in self._manager._tools.list_tools()
                    ]
                    allowed_tools = [t for t in base if t not in _WRITE_TOOLS]
                step.status = "in_progress"
                dep_context = self._build_dep_context(step, results_by_index)
                agent_id = await self._manager.spawn(
                    task=self._build_subtask_prompt(step, member) + dep_context,
                    isolation=self._config.isolation,
                    allowed_tools=allowed_tools,
                )
                agent_ids.append(agent_id)

            if agent_ids:
                batch_results = await self._manager.wait_all(agent_ids, timeout=timeout)
                for step, result in zip(ready, batch_results):
                    step.status = "completed" if result.success else "failed"
                    step.result = result.output or (result.error or "")
                    results_by_index[step.index] = result

            pending = [s for s in pending if s.index not in results_by_index]

        results = [results_by_index[s.index] for s in plan.steps]
        return TeamRunReport(task=task, plan=plan, results=results)

    def stop(self) -> None:
        """Cancel all running team members. 取消所有运行中的团队成员。"""
        self._manager.cancel_all()

    def _scan_project_structure(self, depth: int = 2, max_lines: int = 80) -> str:
        """Directory scan for planner context. Coordinator mode uses deeper scan.
        供 Planner 参考的目录扫描。Coordinator 模式用更深扫描。"""
        root = self._manager._working_dir
        lines = [f"Project root: {root}", f"Structure ({depth} levels):"]
        self._scan_dir(root, lines, depth, indent=1)
        return "\n".join(lines[:max_lines])

    def _scan_dir(self, path, lines: list[str], depth: int, indent: int) -> None:
        if depth <= 0:
            return
        prefix = "  " * indent
        try:
            for entry in sorted(path.iterdir())[:20]:
                if entry.name in _SCAN_IGNORE or entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    lines.append(f"{prefix}{entry.name}/")
                    self._scan_dir(entry, lines, depth - 1, indent + 1)
                else:
                    lines.append(f"{prefix}{entry.name}")
        except OSError:
            logger.debug("team dir scan failed", exc_info=True)
            pass

    @staticmethod
    def _build_subtask_prompt(step, member: TeamMember | None) -> str:
        role_line = f"You are acting as the {member.role} specialist.\n" if member else ""
        return f"{role_line}Subtask: {step.description}"

    @staticmethod
    def _build_dep_context(step, results_by_index: dict[int, SubAgentResult]) -> str:
        """Pass dependency outputs to a dependent step. 把依赖步骤的产出传给后续步骤。"""
        if not step.depends_on:
            return ""
        parts = ["\n\nOutput from completed dependency steps:"]
        for d in step.depends_on:
            result = results_by_index.get(d)
            if result and result.output:
                parts.append(f"--- Step {d} report ---\n{result.output[:4000]}")
        return "\n".join(parts)
