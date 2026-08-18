"""Headless worker mode -- run one SubAgent task in a separate process (6.4).
无头 worker 模式——在独立进程中运行单个 SubAgent 任务。

A pane backend (tmux / Windows Terminal) launches
``mini-agent --worker <spec.json>`` in a visible pane. The worker builds a
minimal stack (LLM + tools + shared-directory Mailbox), streams its progress
to the pane's stdout, writes the final result as JSON to ``result_path`` for
the parent process to collect, then holds the pane open briefly so the user
can read the tail output.
窗格后端在可见窗格里启动 worker：读取任务描述文件，搭最小栈（LLM + 工具 +
共享目录 Mailbox），进度流式打到窗格 stdout，结果写 JSON 供父进程收集，
结束后短暂停留让用户看清尾部输出。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkerSpec:
    """Task description handed from the parent process via a JSON file.
    父进程通过 JSON 文件移交的任务描述。"""

    task: str
    agent_id: str
    result_path: str
    mailbox_dir: str
    working_dir: str = "."
    name: str = ""
    agent_type: str = ""
    allowed_tools: list[str] | None = None
    # (peer_id, peer_name, peer_task) triples, same as SubAgent peers
    peers: list[list[str]] = field(default_factory=list)
    # Seconds to keep the pane open after finishing 结束后窗格停留秒数
    hold_seconds: float = 5.0

    @classmethod
    def load(cls, path: str | Path) -> WorkerSpec:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**data)

    def dump(self, path: str | Path) -> None:
        from dataclasses import asdict

        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8"
        )


async def run_worker(spec_path: str) -> int:
    """Entry point for ``mini-agent --worker``. Returns the process exit
    code (0 = task succeeded). ANY crash still writes a failure result
    file -- otherwise the parent can only time out while the crash reason
    vanishes with the closing pane.
    ``--worker`` 的入口。任何崩溃都要写出失败结果文件——否则父进程只能
    干等超时，而崩溃原因随窗格关闭消失。"""
    spec = WorkerSpec.load(spec_path)
    try:
        return await _run_worker_inner(spec)
    except Exception as e:
        import traceback

        traceback.print_exc()
        _write_result(
            spec.result_path,
            {
                "agent_id": spec.agent_id,
                "task": spec.task,
                "success": False,
                "output": "",
                "error": f"worker crashed: {type(e).__name__}: {e}",
                "tool_calls_made": 0,
                "tokens_used": 0,
            },
        )
        print(f"\n[worker {spec.name or spec.agent_id}] CRASHED: {e}", flush=True)
        await asyncio.sleep(max(0.0, spec.hold_seconds))
        return 1


async def _run_worker_inner(spec: WorkerSpec) -> int:
    from mini_agent.config.loader import ConfigLoader
    from mini_agent.core.mailbox import Mailbox
    from mini_agent.core.subagent import SubAgent
    from mini_agent.events.bus import EventBus
    from mini_agent.llm.registry import ProviderRegistry
    from mini_agent.security.path_guard import PathGuard
    from mini_agent.security.permission import PermissionManager
    from mini_agent.security.remote_confirm import RemoteConfirm
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS

    config = ConfigLoader.load()  # env vars (API key) inherited from parent
    llm = ProviderRegistry.create(config.llm)

    registry = ToolRegistry()
    for tool_class in ALL_BUILTIN_TOOLS:
        tool = tool_class()
        if tool.schema.name in config.tools.enabled_tools:
            registry.register(tool)

    # Permission stack: file-based confirm relayed through the parent process
    # 权限栈：基于文件的确认，通过父进程中转
    workers_dir = Path(spec.result_path).parent
    event_bus = EventBus()
    path_guard = PathGuard(
        tool_config=config.tools,
        security_config=config.security,
        project_dir=Path(spec.working_dir),
    )
    remote_confirm = RemoteConfirm(workers_dir, spec.agent_id)
    permission_manager = PermissionManager(
        config=config.security,
        path_guard=path_guard,
        confirm_callback=remote_confirm,
        event_bus=event_bus,
    )
    permission_manager.load_rule_files(
        user_file=Path.home() / ".mini-agent" / "permissions.toml",
        project_file=Path(spec.working_dir) / ".mini-agent" / "permissions.toml",
    )

    mailbox = Mailbox(Path(spec.mailbox_dir))
    header = f"[worker {spec.name or spec.agent_id}]"
    print(f"{header} task: {spec.task}", flush=True)

    agent = SubAgent(
        task=spec.task,
        llm=llm,
        tool_registry=registry,
        config=config,
        event_bus=event_bus,
        working_dir=Path(spec.working_dir),
        allowed_tools=spec.allowed_tools,
        model_name=config.llm.model,
        agent_type=None if not spec.agent_type else _resolve_type(spec.agent_type),
        mailbox=mailbox,
        agent_id=spec.agent_id,
        peers=[tuple(p) for p in spec.peers] or None,
        name=spec.name,
        permission_manager=permission_manager,
    )
    # Pane visibility: stream LLM text and tool activity to stdout
    # 窗格可见性：LLM 文本与工具活动流式打到 stdout
    agent._loop.on_stream_delta = lambda delta: print(delta, end="", flush=True)
    agent._loop.on_tool_start = lambda tc: print(f"\n{header} tool: {tc.name}", flush=True)

    result = await agent.run()

    _write_result(
        spec.result_path,
        {
            "agent_id": result.agent_id,
            "task": result.task,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "tool_calls_made": result.tool_calls_made,
            "tokens_used": result.tokens_used,
        },
    )

    status = "OK" if result.success else f"FAILED: {result.error}"
    print(
        f"\n{header} done ({status}), result written. Pane closes in {spec.hold_seconds:.0f}s...",
        flush=True,
    )
    await asyncio.sleep(max(0.0, spec.hold_seconds))
    return 0 if result.success else 1


def _write_result(result_path: str, payload: dict) -> None:
    """Atomic result write (temp + replace). 原子写结果文件。"""
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _resolve_type(name: str):
    from mini_agent.core.agent_types import get_agent_type

    return get_agent_type(name)
