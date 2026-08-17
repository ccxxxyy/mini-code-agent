"""SubAgent dispatch -- delegate tasks to independent agents running in parallel.
SubAgent 分发——将任务委派给并行运行的独立 Agent。
"""

from __future__ import annotations

import asyncio
import copy
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from mini_agent.config import detect_shell
from mini_agent.core.agent_loop import AgentLoop
from mini_agent.core.agent_state import AgentPhase
from mini_agent.core.agent_types import AgentTypeDefinition, get_agent_type
from mini_agent.core.mailbox import Mailbox
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

MAILBOX_NOTICE = """

You are agent {self_label}.{peers_line} Incoming messages from other agents \
appear as "[Message from agent '<id>']" (or [Request ...] / [Response ...]) \
and may contain findings or coordination requests -- take them into account. \
Use the send_message tool to message 'main' (the orchestrator), a peer (by \
name or id), or '*' (broadcast to all) mid-task when you have findings worth \
sharing; otherwise just finish and report normally. Always use the EXACT \
names/ids listed above -- never invent ids like 'agent-2' or 'subagent_1'.
When you need an ANSWER from a peer, send type='request' (a request_id is \
assigned); the peer replies with type='response' and that request_id \
(optionally approve=true/false).
If your task says to WAIT for information from another agent, use the \
wait_message tool -- it blocks until a message arrives. Do NOT finish \
early or busy-wait with shell sleeps: once you finish, your inbox is \
closed and peers can no longer reach you.
If send_message to a peer fails because it already finished, send your \
message to 'main' instead so the information is not lost."""


def _task_snippet(task: str, limit: int = 80) -> str:
    """One-line task preview for peer listings. 同伴列表用的单行任务摘要。"""
    flat = " ".join(task.split())
    return flat[:limit] + ("..." if len(flat) > limit else "")


def _intersect_tools(
    type_tools: tuple[str, ...] | None,
    caller_tools: list[str] | None,
) -> list[str] | None:
    """Intersect agent-type tool list with caller-specified tool list.
    取 agent type 工具列表与调用方工具列表的交集。"""
    if type_tools is None:
        return caller_tools
    if caller_tools is None:
        return list(type_tools)
    return [t for t in type_tools if t in caller_tools]


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
        agent_type: AgentTypeDefinition | None = None,
        mailbox: Mailbox | None = None,
        agent_id: str | None = None,
        peers: list[tuple[str, str, str]] | None = None,
        name: str = "",
    ) -> None:
        self.agent_id = agent_id or uuid.uuid4().hex[:8]
        self.name = name
        self.task = task
        self._worktree_path = worktree_path
        self._mailbox = mailbox
        effective_dir = worktree_path or working_dir

        if agent_type is not None:
            effective_config = copy.copy(config)
            effective_config.max_agent_iterations = agent_type.max_iterations
            effective_tools = _intersect_tools(agent_type.allowed_tools, allowed_tools)
            prompt_template = agent_type.system_prompt
        else:
            effective_config = config
            effective_tools = allowed_tools
            prompt_template = SUBAGENT_SYSTEM_PROMPT

        registry = tool_registry.clone()
        registry.unregister("spawn_agents")
        if effective_tools is not None:
            keep = {t.schema.name for t in registry.filter(allowed=effective_tools)}
            for tool in registry.list_tools():
                if tool.schema.name not in keep:
                    registry.unregister(tool.schema.name)

        tool_context = ToolContext(
            working_dir=effective_dir,
            session=Session(),
            event_bus=event_bus,
            config=effective_config,
            mailbox=mailbox,
            agent_id=self.agent_id,
        )

        self._loop = AgentLoop(
            llm=llm,
            tool_registry=registry,
            event_bus=event_bus,
            config=effective_config,
            tool_context=tool_context,
        )
        self._loop.model_name = model_name
        if mailbox is not None:
            mailbox.register(self.agent_id, name=name)
            self._loop.mailbox = mailbox
            self._loop.agent_id = self.agent_id

        from mini_agent.memory.tool_result_cache import ToolResultCache

        self._result_cache = ToolResultCache(
            Path.home() / ".mini-agent" / "cache" / "results" / f"subagent_{self.agent_id}",
            threshold_chars=effective_config.memory.spill_threshold_chars,
            aggregate_chars=effective_config.memory.aggregate_spill_chars,
        )
        self._loop.result_cache = self._result_cache

        platform = f"{sys.platform} ({'Windows' if sys.platform == 'win32' else 'Unix'})"
        shell = detect_shell()
        system_prompt = prompt_template.format(
            working_dir=effective_dir,
            platform=platform,
            shell=shell,
            iteration_budget=effective_config.max_agent_iterations,
        )
        if mailbox is not None and registry.get("send_message") is not None:
            peers_line = ""
            if peers:
                peer_bits = "; ".join(
                    (
                        f"'{pname}' (id {pid}, task: {_task_snippet(ptask)})"
                        if pname
                        else f"'{pid}' (task: {_task_snippet(ptask)})"
                    )
                    for pid, pname, ptask in peers
                )
                peers_line = f" Peer agents running alongside you: {peer_bits}."
            self_label = f"'{name}' (id '{self.agent_id}')" if name else f"'{self.agent_id}'"
            system_prompt += MAILBOX_NOTICE.format(self_label=self_label, peers_line=peers_line)
        self._conversation = Conversation(system_prompt=system_prompt)
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
            if self._mailbox is not None:
                self._mailbox.unregister(self.agent_id)


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


class _PaneWorkerProxy:
    """Stands in for SubAgent in the active table when the real agent runs
    in a separate terminal pane process (6.4). Provides just the interface
    the manager touches: cancel/status/task/agent_id/_conversation.
    当真实 Agent 跑在独立窗格进程时，在活跃表里顶替 SubAgent——只提供
    管理器用到的接口。"""

    def __init__(self, agent_id: str, task: str) -> None:
        self.agent_id = agent_id
        self.task = task
        self._conversation = Conversation(system_prompt="")
        self._cancelled = False

    @property
    def status(self) -> AgentPhase:
        return AgentPhase.TOOL_CALLING

    def cancel(self) -> None:
        # Best effort: the pane process is not force-killed, but the
        # collector task stops waiting for it. 尽力而为：不强杀窗格进程，
        # 只让收集任务停止等待。
        self._cancelled = True


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
        mailbox: Mailbox | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tool_registry
        self._config = config
        self._event_bus = event_bus
        self._working_dir = working_dir
        self._worktree_manager = worktree_manager
        self._model_name = model_name
        self._active: dict[str, _ActiveAgent] = {}
        if mailbox is None:
            mailbox = Mailbox(working_dir / ".mini-agent" / "mailboxes")
            # Fresh session owns the default mailbox: wipe last session's
            # audit files 新会话拥有默认收件箱：清掉上一会话的审计留痕
            mailbox.reset_all()
        self.mailbox = mailbox

    async def spawn(
        self,
        task: str,
        isolation: str = "none",
        allowed_tools: list[str] | None = None,
        agent_type: str | None = None,
        agent_id: str | None = None,
        peers: list[tuple[str, str, str]] | None = None,
        name: str = "",
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

        type_def = get_agent_type(agent_type) if agent_type else None
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
            agent_type=type_def,
            mailbox=self.mailbox,
            agent_id=agent_id,
            peers=peers,
            name=name,
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
        agent_type: str | None = None,
        names: list[str] | None = None,
    ) -> list[str]:
        """Spawn multiple sub-agents concurrently. Returns agent_ids.
        并发派生多个 SubAgent，返回 agent_id 列表。

        Ids are pre-generated so each agent's MAILBOX_NOTICE can name its
        peers (with optional human-readable names) -- siblings can message
        each other without discovery.
        id 预生成，MAILBOX_NOTICE 直接告知同伴 id（可带人类可读别名）——
        兄弟 Agent 无需探测即可互发消息。
        """
        if names is not None and len(names) != len(tasks):
            raise ValueError(f"names length ({len(names)}) must match tasks ({len(tasks)})")
        effective_names = names or ["" for _ in tasks]
        ids = [uuid.uuid4().hex[:8] for _ in tasks]
        for task, agent_id, name in zip(tasks, ids, effective_names):
            await self.spawn(
                task,
                isolation=isolation,
                allowed_tools=allowed_tools,
                agent_type=agent_type,
                agent_id=agent_id,
                name=name,
                peers=[
                    (pid, pname, pt)
                    for pid, pname, pt in zip(ids, effective_names, tasks)
                    if pid != agent_id
                ],
            )
        return ids

    async def spawn_pane(
        self,
        task: str,
        name: str = "",
        agent_type: str | None = None,
        timeout: float = 900.0,
    ) -> str:
        """Spawn a sub-agent in a visible terminal pane (separate process,
        6.4). Requires an active tmux / Windows Terminal session; raises
        ValueError otherwise. Returns agent_id -- wait/cancel/list work the
        same as in-process agents.
        在可见终端窗格（独立进程）中派生 SubAgent。需要当前会话跑在
        tmux / Windows Terminal 里，否则抛 ValueError。"""
        from mini_agent.core.spawn_backends import (
            SpawnBackendError,
            build_worker_argv,
            detect_pane_backend,
        )
        from mini_agent.core.spawn_backends import spawn_pane as open_pane
        from mini_agent.core.worker import WorkerSpec

        backend = detect_pane_backend()
        if not backend:
            raise ValueError(
                "No pane backend available -- run inside tmux or Windows Terminal, "
                "or use in-process spawn"
            )

        agent_id = uuid.uuid4().hex[:8]
        # Protocol files live OUTSIDE the working dir: a worker's LLM once
        # found its own spec (with result_path) inside the project, helpfully
        # wrote a premature result itself, and the parent collected the stub.
        # 协议文件放在工作目录之外：曾有 worker 的 LLM 在项目里读到自己的
        # spec（含 result_path），"好心"提前自己写了结果，父进程捡走了早产桩。
        workers_dir = Path.home() / ".mini-agent" / "workers"
        workers_dir.mkdir(parents=True, exist_ok=True)
        spec_path = workers_dir / f"{agent_id}.spec.json"
        result_path = workers_dir / f"{agent_id}.result.json"

        WorkerSpec(
            task=task,
            agent_id=agent_id,
            name=name,
            working_dir=str(self._working_dir),
            mailbox_dir=str(self.mailbox.base_dir),
            result_path=str(result_path),
            agent_type=agent_type or "",
        ).dump(spec_path)

        try:
            open_pane(
                backend,
                title=f"agent {name or agent_id}",
                argv=build_worker_argv(str(spec_path)),
                cwd=str(self._working_dir),
            )
        except SpawnBackendError as e:
            spec_path.unlink(missing_ok=True)
            raise ValueError(f"Pane spawn failed: {e}") from e

        proxy = _PaneWorkerProxy(agent_id, task)
        handle = asyncio.create_task(self._collect_pane_result(proxy, task, result_path, timeout))
        self._active[agent_id] = _ActiveAgent(
            agent=proxy, task_handle=handle, started_at=time.monotonic()
        )
        await self._event_bus.emit(SubAgentSpawnEvent(agent_id=agent_id, task=task))
        return agent_id

    async def _collect_pane_result(
        self, proxy: _PaneWorkerProxy, task: str, result_path: Path, timeout: float
    ) -> SubAgentResult:
        """Poll for the worker's result file (written atomically by the
        worker process). 轮询 worker 进程原子写出的结果文件。"""
        required = {
            "agent_id",
            "task",
            "success",
            "output",
            "error",
            "tool_calls_made",
            "tokens_used",
        }
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not proxy._cancelled:
            if result_path.is_file():
                try:
                    data = json.loads(result_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = None
                # Schema + identity check: only accept a COMPLETE result
                # written by run_worker, not a stub something else produced
                # Schema + 身份校验：只接受 run_worker 写出的完整结果，
                # 拒绝其他来源的桩文件
                if (
                    isinstance(data, dict)
                    and required.issubset(data.keys())
                    and data.get("agent_id") == proxy.agent_id
                ):
                    return SubAgentResult(
                        agent_id=proxy.agent_id,
                        task=task,
                        success=bool(data.get("success")),
                        output=str(data.get("output", "")),
                        error=data.get("error"),
                        tool_calls_made=int(data.get("tool_calls_made", 0)),
                        tokens_used=int(data.get("tokens_used", 0)),
                    )
            await asyncio.sleep(0.5)
        reason = "Cancelled" if proxy._cancelled else "Pane worker timed out (no result file)"
        return SubAgentResult(
            agent_id=proxy.agent_id, task=task, success=False, output="", error=reason
        )

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
        except asyncio.CancelledError:
            # The agent's own task was cancelled (via cancel()); waiting for
            # it should report that, not blow up the waiter.
            # Agent 自身任务被 cancel()——等待方应得到结果而非被炸。
            if not entry.task_handle.cancelled():
                raise
            result = SubAgentResult(
                agent_id=agent_id,
                task=entry.agent.task,
                success=False,
                output="",
                error="Cancelled",
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
