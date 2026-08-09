"""SubAgent dispatch -- delegate tasks to independent agents running in parallel.
SubAgent 分发——将任务委派给并行运行的独立 Agent。
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.agent_state import AgentPhase
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider
from mini_agent.models.config import AgentConfig
from mini_agent.models.events import SubAgentCompleteEvent, SubAgentSpawnEvent
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry

SUBAGENT_SYSTEM_PROMPT = """You are a focused sub-agent working on a single delegated task.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

Complete the task using the available tools, then give a concise final report.
Do not ask questions -- make reasonable decisions autonomously.
Your final message is your report back to the orchestrator.
Respond in the same language the task is written in (Chinese task -> Chinese report).

BUDGET: you have roughly {iteration_budget} think-act rounds before you are \
force-stopped. Plan your tool usage: prioritize the most important \
files/actions first, sample instead of reading everything, and when the \
budget is running low, STOP exploring and write out your findings/deliverables \
immediately. A partial deliverable is far better than being cut off with \
nothing written.

Rules:
- Write ALL output files inside the working directory shown above, using \
relative paths (e.g. "report.md"). NEVER write to /tmp or other absolute \
paths outside the working directory.
- Use platform-appropriate shell commands. On Windows use dir/type/findstr, \
NOT ls/cat/grep.
- If a file or resource the task mentions does not exist, report that fact \
and stop -- do NOT retry in a loop."""


@dataclass
class SubAgentResult:
    agent_id: str
    task: str
    success: bool
    output: str
    tool_calls_made: int = 0
    tokens_used: int = 0
    worktree_path: Path | None = None
    error: str | None = None


class SubAgent:
    """An independent agent that runs a single task in isolation.
    在隔离环境中执行单个任务的独立 Agent。
    """

    def __init__(
        self,
        task: str,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        event_bus: EventBus,
        working_dir: Path,
        worktree_path: Path | None = None,
        allowed_tools: list[str] | None = None,
        model_name: str = "",
    ) -> None:
        self.agent_id = uuid.uuid4().hex[:8]
        self.task = task
        self._worktree_path = worktree_path
        effective_dir = worktree_path or working_dir

        # Independent tool registry (clone; optionally filtered)
        # 独立的工具 registry（克隆副本；可按需过滤）
        registry = tool_registry.clone()
        # Recursion guard: sub-agents cannot spawn further sub-agents
        # 递归防护：子代理不能再派生子代理
        registry.unregister("spawn_agents")
        if allowed_tools is not None:
            for tool in registry.list_tools():
                if tool.schema.name not in allowed_tools:
                    registry.unregister(tool.schema.name)

        tool_context = ToolContext(
            working_dir=effective_dir,
            session=Session(),
            event_bus=event_bus,
            config=config,
        )

        self._loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            event_bus=event_bus,
            config=config,
            tool_context=tool_context,
        )
        self._loop.model_name = model_name  # cost attribution 成本归属

        # Spill oversized tool results (sub-agents have no ContextManager,
        # so this is their only protection against context bloat)
        # 超大工具结果溢写（子代理没有 ContextManager——这是它们防上下文膨胀的唯一保护）
        from mini_agent.memory.tool_result_cache import ToolResultCache

        self._result_cache = ToolResultCache(
            Path.home() / ".mini-agent" / "cache" / "results" / f"subagent_{self.agent_id}",
            threshold_chars=config.memory.spill_threshold_chars,
        )
        self._loop.result_cache = self._result_cache

        platform = f"{sys.platform} ({'Windows' if sys.platform == 'win32' else 'Unix'})"
        shell = os.environ.get("SHELL", "cmd.exe" if sys.platform == "win32" else "/bin/bash")
        self._conversation = Conversation(
            system_prompt=SUBAGENT_SYSTEM_PROMPT.format(
                working_dir=effective_dir,
                platform=platform,
                shell=shell,
                iteration_budget=config.max_agent_iterations,
            )
        )
        self._conversation.append(Message(role=Role.USER, content=task))

    @property
    def status(self) -> AgentPhase:
        return self._loop.state.phase

    def cancel(self) -> None:
        self._loop.cancel()

    async def run(self) -> SubAgentResult:
        try:
            output = await self._loop.run(self._conversation)
            tool_calls = sum(len(m.tool_calls) for m in self._conversation.messages)
            # Circuit-breaker termination is a failure, not a completed task
            # 熔断终止是失败，不算任务完成
            stopped = self._loop.stopped_early
            return SubAgentResult(
                agent_id=self.agent_id,
                task=self.task,
                success=not stopped,
                output=output,
                tool_calls_made=tool_calls,
                tokens_used=self._loop.last_turn_tokens,
                worktree_path=self._worktree_path,
                error="Stopped early (iteration limit or cancellation)" if stopped else None,
            )
        except Exception as e:
            return SubAgentResult(
                agent_id=self.agent_id,
                task=self.task,
                success=False,
                output="",
                worktree_path=self._worktree_path,
                error=str(e),
            )
        finally:
            self._result_cache.cleanup()


@dataclass
class AgentSnapshot:
    """Point-in-time view of an active sub-agent (for progress display).
    活跃 SubAgent 的即时快照（用于进度展示）。"""

    agent_id: str
    task: str
    phase: str
    tool_calls: int
    elapsed_seconds: float


@dataclass
class _ActiveAgent:
    agent: SubAgent
    task_handle: asyncio.Task = field(repr=False)
    started_at: float = 0.0


class SubAgentManager:
    """Manages spawning, tracking, and collecting results from sub-agents.
    管理 SubAgent 的派生、跟踪与结果收集。
    """

    def __init__(
        self,
        llm: LLMProvider,
        tool_registry: ToolRegistry,
        config: AgentConfig,
        event_bus: EventBus,
        working_dir: Path,
        worktree_manager=None,
        model_name: str = "",
    ) -> None:
        self._llm = llm
        self._tools = tool_registry
        self._config = config
        self._event_bus = event_bus
        self._working_dir = working_dir
        self._worktree_manager = worktree_manager
        self._model_name = model_name
        self._active: dict[str, _ActiveAgent] = {}

    async def spawn(
        self,
        task: str,
        isolation: str = "none",
        allowed_tools: list[str] | None = None,
    ) -> str:
        """Spawn a sub-agent running in the background. Returns agent_id.
        派生一个后台运行的 SubAgent，返回 agent_id。
        """
        worktree_path: Path | None = None
        if isolation == "worktree":
            if self._worktree_manager is None:
                raise ValueError("Worktree isolation requested but no WorktreeManager provided")
            branch = f"agent-{uuid.uuid4().hex[:8]}"
            worktree_path = await self._worktree_manager.create(branch)

        agent = SubAgent(
            task=task,
            llm=self._llm,
            tool_registry=self._tools,
            config=self._config,
            event_bus=self._event_bus,
            working_dir=self._working_dir,
            worktree_path=worktree_path,
            allowed_tools=allowed_tools,
            model_name=self._model_name,
        )
        handle = asyncio.create_task(agent.run())
        self._active[agent.agent_id] = _ActiveAgent(
            agent=agent, task_handle=handle, started_at=time.monotonic()
        )
        await self._event_bus.emit(SubAgentSpawnEvent(agent_id=agent.agent_id, task=task))
        return agent.agent_id

    async def spawn_parallel(
        self,
        tasks: list[str],
        isolation: str = "none",
        allowed_tools: list[str] | None = None,
    ) -> list[str]:
        """Spawn multiple sub-agents concurrently. Returns agent_ids.
        并发派生多个 SubAgent，返回 agent_id 列表。
        """
        ids = []
        for task in tasks:
            ids.append(await self.spawn(task, isolation=isolation, allowed_tools=allowed_tools))
        return ids

    async def wait(self, agent_id: str, timeout: float | None = None) -> SubAgentResult:
        """Wait for a specific sub-agent to complete. 等待指定的 SubAgent 完成。"""
        entry = self._active.get(agent_id)
        if entry is None:
            return SubAgentResult(
                agent_id=agent_id,
                task="",
                success=False,
                output="",
                error=f"Unknown agent: {agent_id}",
            )
        try:
            result = await asyncio.wait_for(entry.task_handle, timeout=timeout)
        except TimeoutError:
            entry.agent.cancel()
            result = SubAgentResult(
                agent_id=agent_id,
                task=entry.agent.task,
                success=False,
                output="",
                error="Timed out",
            )
        finally:
            self._active.pop(agent_id, None)
        await self._event_bus.emit(
            SubAgentCompleteEvent(
                agent_id=result.agent_id,
                success=result.success,
                tokens_used=result.tokens_used,
            )
        )
        return result

    async def wait_all(
        self, agent_ids: list[str] | None = None, timeout: float | None = None
    ) -> list[SubAgentResult]:
        """Wait for all (or specified) sub-agents to complete.
        等待全部（或指定的）SubAgent 完成。
        """
        ids = agent_ids if agent_ids is not None else list(self._active.keys())
        results = await asyncio.gather(*(self.wait(aid, timeout=timeout) for aid in ids))
        return list(results)

    def cancel(self, agent_id: str) -> None:
        entry = self._active.get(agent_id)
        if entry:
            entry.agent.cancel()
            entry.task_handle.cancel()

    def cancel_all(self) -> None:
        for agent_id in list(self._active):
            self.cancel(agent_id)

    def list_active(self) -> list[str]:
        return list(self._active.keys())

    def get_status(self, agent_id: str) -> AgentPhase | None:
        entry = self._active.get(agent_id)
        return entry.agent.status if entry else None

    def active_snapshots(self) -> list[AgentSnapshot]:
        """Point-in-time snapshots of all active agents (for progress board).
        所有活跃 agent 的即时快照（用于进度面板）。"""
        now = time.monotonic()
        snapshots: list[AgentSnapshot] = []
        for entry in self._active.values():
            agent = entry.agent
            tool_calls = sum(len(m.tool_calls) for m in agent._conversation.messages)
            snapshots.append(
                AgentSnapshot(
                    agent_id=agent.agent_id,
                    task=agent.task,
                    phase=agent.status.value,
                    tool_calls=tool_calls,
                    elapsed_seconds=now - entry.started_at,
                )
            )
        return snapshots
