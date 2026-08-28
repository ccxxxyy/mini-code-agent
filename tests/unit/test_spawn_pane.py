"""Tests for pane spawn backends and the worker protocol (6.4).
窗格 spawn 后端与 worker 协议的测试。"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from mini_agent.core import spawn_backends
from mini_agent.core.spawn_backends import (
    SpawnBackendError,
    build_worker_argv,
    detect_pane_backend,
    spawn_pane,
)
from mini_agent.core.subagent import SubAgentManager
from mini_agent.core.worker import WorkerSpec, run_worker
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from tests.mocks import MockLLM

pytestmark = pytest.mark.asyncio


# --- backend detection 后端探测 ---


async def test_detect_backend_tmux(monkeypatch):
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,1234,0")
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert detect_pane_backend() == "tmux"


async def test_detect_backend_wt(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setenv("WT_SESSION", "abc-123")
    monkeypatch.setattr(spawn_backends.sys, "platform", "win32")
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: f"C:/apps/{name}.exe")
    assert detect_pane_backend() == "wt"


async def test_detect_backend_none(monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: None)
    assert detect_pane_backend() == ""


async def test_detect_backend_wt_window_fallback(monkeypatch):
    """wt installed but NOT inside a WT session -> degrade to new window.
    装了 wt 但不在 WT 会话内 -> 降级弹新窗口。"""
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(spawn_backends.sys, "platform", "win32")
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: f"C:/apps/{name}.exe")
    assert detect_pane_backend() == "wt-window"


async def test_spawn_wt_window_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0
            stderr = ""

        return R()

    monkeypatch.setattr(spawn_backends.subprocess, "run", fake_run)
    spawn_pane("wt-window", title="agent z", argv=["python", "-m", "mini_agent"], cwd="C:/proj")
    assert calls[0][:5] == ["wt", "-w", "mini-agents", "new-tab", "--title"]


async def test_detect_backend_tmux_env_but_no_binary(monkeypatch):
    monkeypatch.setenv("TMUX", "x")
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: None)
    monkeypatch.delenv("WT_SESSION", raising=False)
    assert detect_pane_backend() == ""


# --- pane command construction 窗格命令构造 ---


async def test_build_worker_argv():
    argv = build_worker_argv("C:/x/spec.json")
    assert argv[0] == sys.executable
    assert argv[1:] == ["-m", "mini_agent", "--worker", "C:/x/spec.json"]


async def test_spawn_pane_wt_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0
            stderr = ""

        return R()

    monkeypatch.setattr(spawn_backends.subprocess, "run", fake_run)
    spawn_pane("wt", title="agent x", argv=["python", "-m", "mini_agent"], cwd="C:/proj")
    assert calls[0][:4] == ["wt", "-w", "0", "split-pane"]
    assert "--title" in calls[0] and "agent x" in calls[0]
    assert calls[0][-3:] == ["python", "-m", "mini_agent"]


async def test_spawn_pane_tmux_command(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)

        class R:
            returncode = 0
            stderr = ""

        return R()

    monkeypatch.setattr(spawn_backends.subprocess, "run", fake_run)
    spawn_pane("tmux", title="agent y", argv=["python", "-m", "mini_agent"], cwd="/proj")
    assert calls[0][:3] == ["tmux", "split-window", "-d"]
    assert "/proj" in calls[0]


async def test_spawn_pane_unknown_backend():
    with pytest.raises(SpawnBackendError):
        spawn_pane("iterm-nope", title="t", argv=["x"], cwd=".")


async def test_spawn_pane_failure_raises(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stderr = "no session"

        return R()

    monkeypatch.setattr(spawn_backends.subprocess, "run", fake_run)
    with pytest.raises(SpawnBackendError, match="no session"):
        spawn_pane("wt", title="t", argv=["x"], cwd=".")


# --- WorkerSpec roundtrip ---


async def test_worker_spec_roundtrip(tmp_path):
    spec = WorkerSpec(
        task="count files",
        agent_id="a1b2c3d4",
        result_path=str(tmp_path / "r.json"),
        mailbox_dir=str(tmp_path / "mb"),
        working_dir=str(tmp_path),
        name="counter",
        peers=[["x1", "peer", "other task"]],
        hold_seconds=0,
    )
    path = tmp_path / "spec.json"
    spec.dump(path)
    loaded = WorkerSpec.load(path)
    assert loaded == spec


# --- worker end-to-end (in-process, MockLLM) worker 全链路 ---


async def test_run_worker_writes_result_and_registers_mailbox(tmp_path, monkeypatch):
    """run_worker: reads spec -> runs SubAgent -> writes result JSON; the
    shared mailbox registry sees the worker come and go.
    worker 全链路：读 spec -> 跑 SubAgent -> 写结果；共享注册表可见其注册注销。"""
    from mini_agent.config import loader as loader_mod
    from mini_agent.core.mailbox import Mailbox
    from mini_agent.llm import registry as reg_mod

    config = AgentConfig()
    config.self_verify = False
    monkeypatch.setattr(loader_mod.ConfigLoader, "load", staticmethod(lambda **kw: config))
    monkeypatch.setattr(
        reg_mod.ProviderRegistry, "create", staticmethod(lambda cfg: MockLLM(text="Task finished."))
    )

    mailbox_dir = tmp_path / "mailboxes"
    mb = Mailbox(mailbox_dir)
    mb.register("main")

    result_path = tmp_path / "workers" / "a1b2c3d4.result.json"
    spec = WorkerSpec(
        task="say done",
        agent_id="a1b2c3d4",
        name="painter",
        result_path=str(result_path),
        mailbox_dir=str(mailbox_dir),
        working_dir=str(tmp_path),
        hold_seconds=0,
    )
    spec_path = tmp_path / "spec.json"
    spec.dump(spec_path)

    exit_code = await run_worker(str(spec_path))
    assert exit_code == 0
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["success"] is True
    assert "Task finished." in data["output"]
    assert data["agent_id"] == "a1b2c3d4"
    # Worker unregistered itself on finish 结束后自行注销
    assert "a1b2c3d4" not in mb.peers()


# --- SubAgentManager.spawn_pane 管理器接线 ---


def make_manager(tmp_path) -> SubAgentManager:
    return SubAgentManager(
        llm=MockLLM(text="Task finished."),
        tool_registry=ToolRegistry(),
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )


async def test_spawn_pane_requires_backend(tmp_path, monkeypatch):
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("WT_SESSION", raising=False)
    monkeypatch.setattr(spawn_backends.shutil, "which", lambda name: None)
    mgr = make_manager(tmp_path)
    with pytest.raises(ValueError, match="No pane backend"):
        await mgr.spawn_pane("do something")


async def test_spawn_pane_collects_result_file(tmp_path, monkeypatch):
    """Manager writes the spec, opens a pane (mocked), then collects the
    result file the worker (simulated) writes.
    管理器写 spec、开窗格（mock），收集 worker（模拟）写出的结果文件。"""

    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")
    opened = {}

    def fake_open(backend, title, argv, cwd):
        opened["backend"] = backend
        opened["argv"] = argv
        # Simulate the worker process: write the result file the parent polls
        # 模拟 worker 进程：写出父进程轮询的结果文件
        spec = WorkerSpec.load(argv[-1])
        Path(spec.result_path).write_text(
            json.dumps(
                {
                    "agent_id": spec.agent_id,
                    "task": spec.task,
                    "success": True,
                    "output": "pane worker report",
                    "error": None,
                    "tool_calls_made": 2,
                    "tokens_used": 123,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", fake_open)

    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("inspect the repo", name="inspector")
    assert agent_id in mgr.list_active()
    assert opened["backend"] == "wt"
    # Spec file exists and carries identity 规格文件存在且带身份
    spec = WorkerSpec.load(opened["argv"][-1])
    assert spec.name == "inspector"
    assert spec.mailbox_dir == str(mgr.mailbox.base_dir)

    result = await mgr.wait(agent_id, timeout=10)
    assert result.success
    assert result.output == "pane worker report"
    assert result.tokens_used == 123
    assert agent_id not in mgr.list_active()


async def test_spawn_pane_timeout_when_no_result(tmp_path, monkeypatch):
    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")
    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", lambda *a, **k: None)
    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("never finishes", timeout=1.2)
    result = await mgr.wait(agent_id, timeout=10)
    assert not result.success
    assert "timed out" in (result.error or "")


async def test_spawn_pane_cancel(tmp_path, monkeypatch):
    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")
    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", lambda *a, **k: None)
    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("long task", timeout=60)
    await asyncio.sleep(0)
    mgr.cancel(agent_id)
    result = await mgr.wait(agent_id, timeout=10)
    assert not result.success


async def test_pane_proxy_supports_board_rendering(tmp_path, monkeypatch):
    """Regression: proxy.status must be a REAL AgentPhase member -- the
    /spawn wait progress board reads status/snapshots and once crashed on
    AgentPhase.ACTING (nonexistent), silently killing the app.
    回归：proxy.status 必须是真实存在的 AgentPhase 成员——进度面板读
    status/快照，曾因不存在的 ACTING 崩溃并无声退出整个应用。"""
    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")
    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", lambda *a, **k: None)
    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("long job", timeout=30)

    # The exact calls the board makes while waiting 面板等待期间的调用路径
    from mini_agent.core.agent_state import AgentPhase

    assert mgr.get_status(agent_id) in list(AgentPhase)
    snapshots = mgr.active_snapshots()
    assert snapshots[0].agent_id == agent_id
    assert snapshots[0].phase in {p.value for p in AgentPhase}

    mgr.cancel(agent_id)
    await mgr.wait(agent_id, timeout=10)


# --- LLM 429/5xx retry (exposed by parallel pane workers) 限流重试 ---


async def test_stream_retries_on_429_then_succeeds(monkeypatch):
    """4 parallel workers on one API key exposed this: a single 429 killed
    the worker with 0 tokens. The provider must back off and retry.
    并行 worker 暴露的缺陷：一次 429 就让 worker 零产出死亡——Provider
    必须退避重试。"""
    import httpx

    from mini_agent.llm.openai_provider import OpenAIProvider
    from mini_agent.models.config import LLMConfig

    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) <= 2:
            return httpx.Response(429, headers={"retry-after": "0"})
        sse = (
            'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, content=sse.encode())

    provider = OpenAIProvider(LLMConfig(api_key="k", base_url="http://test/v1"))
    provider._probe_attempted = True  # skip /models probe 跳过窗口探测
    provider._client = httpx.AsyncClient(
        base_url="http://test/v1", transport=httpx.MockTransport(handler)
    )

    chunks = [c async for c in provider.stream([{"role": "user", "content": "hi"}])]
    assert len(attempts) == 3  # 2 rate-limited + 1 success 两次限流一次成功
    assert any(c.delta == "ok" for c in chunks)


async def test_stream_gives_up_after_max_retries(monkeypatch):
    import httpx

    from mini_agent.llm.base import MAX_HTTP_RETRIES
    from mini_agent.llm.openai_provider import OpenAIProvider
    from mini_agent.models.config import LLMConfig

    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(429, headers={"retry-after": "0"})

    provider = OpenAIProvider(LLMConfig(api_key="k", base_url="http://test/v1"))
    provider._probe_attempted = True
    provider._client = httpx.AsyncClient(
        base_url="http://test/v1", transport=httpx.MockTransport(handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        async for _ in provider.stream([{"role": "user", "content": "hi"}]):
            pass
    assert len(attempts) == MAX_HTTP_RETRIES + 1  # initial + retries 首次+重试


async def test_run_worker_crash_still_writes_failure_result(tmp_path, monkeypatch):
    """Regression: a worker that crashes before finishing must STILL write
    a failure result file -- otherwise the parent can only time out while
    the crash reason vanishes with the closing pane.
    回归：worker 中途崩溃也必须写出失败结果文件——否则父进程只能干等
    超时，崩溃原因随窗格关闭消失。"""
    from mini_agent.config import loader as loader_mod

    def boom(**kw):
        raise RuntimeError("config exploded")

    monkeypatch.setattr(loader_mod.ConfigLoader, "load", staticmethod(boom))

    result_path = tmp_path / "w.result.json"
    spec = WorkerSpec(
        task="anything",
        agent_id="deadbeef",
        result_path=str(result_path),
        mailbox_dir=str(tmp_path / "mb"),
        working_dir=str(tmp_path),
        hold_seconds=0,
    )
    spec_path = tmp_path / "spec.json"
    spec.dump(spec_path)

    exit_code = await run_worker(str(spec_path))
    assert exit_code == 1
    data = json.loads(result_path.read_text(encoding="utf-8"))
    assert data["success"] is False
    assert "worker crashed" in data["error"]
    assert "config exploded" in data["error"]


async def test_collector_rejects_stub_result_files(tmp_path, monkeypatch):
    """Regression: a worker's LLM once found its own spec inside the project
    and prematurely wrote a stub result itself -- the parent collected it
    (Tokens: 0) and the real result was orphaned. The collector must reject
    files missing the full run_worker schema or with a wrong agent_id.
    回归：worker 的 LLM 曾读到自己的 spec 并提前自己写了结果桩，父进程
    捡走了它（Tokens: 0），真结果成孤儿。收集器必须拒绝缺字段/身份不符的文件。"""
    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")

    result_holder = {}

    def fake_open(backend, title, argv, cwd):
        spec = WorkerSpec.load(argv[-1])
        result_holder["path"] = Path(spec.result_path)
        result_holder["agent_id"] = spec.agent_id
        # An LLM-written stub: valid JSON but missing token/tool fields
        # LLM 写的桩：合法 JSON 但缺 token/工具字段
        result_holder["path"].write_text(
            json.dumps({"success": True, "output": "premature stub"}),
            encoding="utf-8",
        )

    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", fake_open)
    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("big analysis", timeout=30)

    # Give the collector a few polls: the stub must NOT be accepted
    # 给收集器几轮轮询：桩不能被接受
    await asyncio.sleep(1.2)
    assert agent_id in mgr.list_active()

    # The real worker's complete result arrives -> accepted immediately
    # 真 worker 的完整结果到达 -> 立即被接受
    result_holder["path"].write_text(
        json.dumps(
            {
                "agent_id": result_holder["agent_id"],
                "task": "big analysis",
                "success": True,
                "output": "real report",
                "error": None,
                "tool_calls_made": 61,
                "tokens_used": 1070342,
            }
        ),
        encoding="utf-8",
    )
    result = await mgr.wait(agent_id, timeout=10)
    assert result.output == "real report"
    assert result.tokens_used == 1070342


async def test_collector_rejects_wrong_agent_id(tmp_path, monkeypatch):
    monkeypatch.setattr("mini_agent.core.spawn_backends.detect_pane_backend", lambda: "wt")
    holder = {}

    def fake_open(backend, title, argv, cwd):
        spec = WorkerSpec.load(argv[-1])
        holder["path"] = Path(spec.result_path)
        holder["path"].write_text(
            json.dumps(
                {
                    "agent_id": "someone-else",
                    "task": "x",
                    "success": True,
                    "output": "impostor",
                    "error": None,
                    "tool_calls_made": 1,
                    "tokens_used": 1,
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr("mini_agent.core.spawn_backends.spawn_pane", fake_open)
    mgr = make_manager(tmp_path)
    agent_id = await mgr.spawn_pane("task", timeout=1.5)
    result = await mgr.wait(agent_id, timeout=10)
    assert not result.success  # impostor rejected -> times out 冒名文件被拒->超时
    assert "timed out" in (result.error or "")


async def test_deliverable_extraction(tmp_path, monkeypatch):
    """Result blocks list files the worker actually created (existing in
    cwd), colored via inline code -- mentions of non-existent paths drop.
    结果块列出 worker 真实创建的交付文件；不存在的路径提及被过滤。"""
    from mini_agent.extensions.builtin_commands import _extract_deliverables

    monkeypatch.chdir(tmp_path)
    (tmp_path / "report.md").write_text("x", encoding="utf-8")
    output = "报告已写入 report.md。核实了 agent_loop.py:504 与 ghost.md 的内容。"
    files = _extract_deliverables(output)
    assert files == ["report.md"]  # ghost.md 与 agent_loop.py 不存在于 cwd -> 过滤
