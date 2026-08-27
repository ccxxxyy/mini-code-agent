"""Tests for background consolidation cadence (tech-notes §111).
后台整固节律测试——双门槛 + 锁 + 回滚。"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from mini_agent.llm.base import StreamChunk
from mini_agent.memory.consolidation import ConsolidationScheduler
from mini_agent.memory.persistent import MemoryEntry, PersistentMemory

pytestmark = pytest.mark.asyncio


class _MockLLM:
    def __init__(self, response: str):
        self._response = response
        self.calls = 0

    async def stream(self, messages: list[dict], **kwargs: Any):
        self.calls += 1
        yield StreamChunk(delta=self._response)
        yield StreamChunk(finish_reason="stop")


class _FakeSessionStore:
    def __init__(self, sessions: list[dict[str, Any]]):
        self._sessions = sessions

    async def list_sessions(self) -> list[dict[str, Any]]:
        return self._sessions


def _sessions(n: int, project_dir: str = "", hours_ago: float = 1.0) -> list[dict[str, Any]]:
    ts = (datetime.now() - timedelta(hours=hours_ago)).isoformat()
    return [
        {"session_id": f"s{i}", "last_active": ts, "project_dir": project_dir} for i in range(n)
    ]


def _merge_response() -> str:
    return json.dumps([{"merge_ids": ["mem_a", "mem_b"], "merged_content": "merged fact"}])


def _make_memory(tmp_path: Path) -> PersistentMemory:
    return PersistentMemory(user_memory_dir=str(tmp_path / "user_mem"))


async def _seed_user_entries(pm: PersistentMemory) -> None:
    await pm.save_user_memory(
        [
            MemoryEntry(id="mem_a", content="likes tabs", created_at="2026-01-01T00:00:00"),
            MemoryEntry(id="mem_b", content="prefers tabs", created_at="2026-01-02T00:00:00"),
        ]
    )


def _scheduler(
    pm: PersistentMemory,
    sessions: list[dict[str, Any]],
    llm: Any,
    **kwargs: Any,
) -> ConsolidationScheduler:
    kwargs.setdefault("min_hours", 24.0)
    kwargs.setdefault("min_sessions", 5)
    return ConsolidationScheduler(pm, _FakeSessionStore(sessions), llm, **kwargs)


async def test_first_run_with_enough_sessions_merges(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(5), llm).run_once()
    assert outcomes["user"] == "merged"
    entries = await pm.load_user_memory()
    assert [e.content for e in entries] == ["merged fact"]


async def test_gated_when_too_few_sessions(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(4), llm).run_once()
    assert outcomes["user"] == "gated"
    assert llm.calls == 0


async def test_gated_when_last_run_too_recent(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    state_path = tmp_path / "user_mem" / ConsolidationScheduler.STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    recent = (datetime.now() - timedelta(hours=1)).isoformat()
    state_path.write_text(json.dumps({"user": recent}), encoding="utf-8")
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(10), llm).run_once()
    assert outcomes["user"] == "gated"
    assert llm.calls == 0


async def test_gated_when_no_new_sessions_since_last_run(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    state_path = tmp_path / "user_mem" / ConsolidationScheduler.STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    old = (datetime.now() - timedelta(hours=48)).isoformat()
    state_path.write_text(json.dumps({"user": old}), encoding="utf-8")
    # 10 sessions, but all older than last_run 会话都早于上次整固
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(10, hours_ago=72), llm).run_once()
    assert outcomes["user"] == "gated"
    assert llm.calls == 0


async def test_lock_held_skips(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    lock = tmp_path / "user_mem" / ConsolidationScheduler.LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(datetime.now().isoformat(), encoding="utf-8")
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(5), llm).run_once()
    assert outcomes == {"lock": "held"}
    assert llm.calls == 0
    assert lock.is_file()  # foreign lock not removed 别人的锁不删


async def test_stale_lock_taken_over(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    lock = tmp_path / "user_mem" / ConsolidationScheduler.LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("old", encoding="utf-8")
    stale = time.time() - ConsolidationScheduler.LOCK_MAX_AGE_SECONDS - 60
    os.utime(lock, (stale, stale))
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(5), llm).run_once()
    assert outcomes["user"] == "merged"
    assert not lock.is_file()  # released after run 运行后释放


async def test_lock_released_after_run(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    await _scheduler(pm, _sessions(5), _MockLLM(_merge_response())).run_once()
    assert not (tmp_path / "user_mem" / ConsolidationScheduler.LOCK_FILE).is_file()


async def test_rollback_on_save_failure(tmp_path: Path):
    seed = _make_memory(tmp_path)
    await _seed_user_entries(seed)
    original = seed.user_memory_path().read_text(encoding="utf-8")

    class _FailingSaveMemory(PersistentMemory):
        async def save_user_memory(self, entries: list[MemoryEntry]) -> None:
            # Corrupt then fail -- rollback must restore 先写坏再失败——回滚须复原
            self.user_memory_path().write_text("corrupt", encoding="utf-8")
            raise OSError("disk full")

    pm = _FailingSaveMemory(user_memory_dir=str(tmp_path / "user_mem"))
    outcomes = await _scheduler(pm, _sessions(5), _MockLLM(_merge_response())).run_once()
    assert outcomes["user"] == "rolled_back"
    assert pm.user_memory_path().read_text(encoding="utf-8") == original


async def test_attempt_recorded_even_when_nothing_merges(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    llm = _MockLLM("[]")  # LLM finds nothing to merge 无可合并
    sched = _scheduler(pm, _sessions(5), llm)
    outcomes = await sched.run_once()
    assert outcomes["user"] == "no_merge"
    assert llm.calls == 1
    # Second run gated by the recorded attempt 第二次被已记录的尝试拦住
    outcomes2 = await sched.run_once()
    assert outcomes2["user"] == "gated"
    assert llm.calls == 1


async def test_too_few_entries_skips_llm(tmp_path: Path):
    pm = _make_memory(tmp_path)
    await pm.save_user_memory([MemoryEntry(id="mem_a", content="only one")])
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, _sessions(5), llm).run_once()
    assert outcomes["user"] == "too_few"
    assert llm.calls == 0


async def test_project_scope_counts_only_project_sessions(tmp_path: Path):
    pm = _make_memory(tmp_path)
    project_dir = tmp_path / "proj"
    (project_dir / ".mini-agent").mkdir(parents=True)
    await pm.save_project_memory(
        project_dir,
        [
            MemoryEntry(id="mem_a", content="uses pytest"),
            MemoryEntry(id="mem_b", content="tests with pytest"),
        ],
    )
    # 5 sessions belong to another project 5 个会话属于别的项目
    sessions = _sessions(5, project_dir=str(tmp_path / "other"))
    llm = _MockLLM(_merge_response())
    outcomes = await _scheduler(pm, sessions, llm).run_once(project_dir)
    key = f"project:{project_dir.resolve().as_posix()}"
    assert outcomes[key] == "gated"
    # Same 5 sessions on this project pass the gate 本项目 5 个会话则放行
    sessions = _sessions(5, project_dir=str(project_dir))
    outcomes = await _scheduler(pm, sessions, llm).run_once(project_dir)
    assert outcomes[key] == "merged"


async def test_project_merge_writes_project_file(tmp_path: Path):
    pm = _make_memory(tmp_path)
    project_dir = tmp_path / "proj"
    (project_dir / ".mini-agent").mkdir(parents=True)
    await pm.save_project_memory(
        project_dir,
        [
            MemoryEntry(id="mem_a", content="uses pytest"),
            MemoryEntry(id="mem_b", content="tests with pytest"),
        ],
    )
    llm = _MockLLM(_merge_response())
    await _scheduler(pm, _sessions(5, project_dir=str(project_dir)), llm).run_once(project_dir)
    entries = await pm.load_project_memory(project_dir)
    assert [e.content for e in entries] == ["merged fact"]


# --- Application start/stop helpers (terminal & remote shared wiring) ---
# Application 启动/停止助手（终端与远程共用接线）


class _StubApp:
    """Minimal attribute surface for the unbound Application methods.
    为解绑调用 Application 方法准备的最小属性面。"""

    def __init__(self, auto_consolidate: bool = True):
        from types import SimpleNamespace

        self.config = SimpleNamespace(memory=SimpleNamespace(auto_consolidate=auto_consolidate))
        self._consolidation_task = None
        self.runs = 0

    async def _background_consolidate(self):
        self.runs += 1
        await asyncio.sleep(30)  # long-running until cancelled 长跑直到被取消


def _app_methods():
    from mini_agent.app import Application

    return Application.start_background_consolidation, Application.stop_background_consolidation


async def test_start_creates_task_when_enabled():
    start, stop = _app_methods()
    app = _StubApp(auto_consolidate=True)
    start(app)
    assert app._consolidation_task is not None
    await asyncio.sleep(0.01)
    assert app.runs == 1
    await stop(app)
    assert app._consolidation_task.cancelled()


async def test_start_noop_when_disabled():
    start, _ = _app_methods()
    app = _StubApp(auto_consolidate=False)
    start(app)
    assert app._consolidation_task is None


async def test_start_twice_no_duplicate_task():
    start, stop = _app_methods()
    app = _StubApp(auto_consolidate=True)
    start(app)
    task = app._consolidation_task
    start(app)
    assert app._consolidation_task is task  # still the same task 仍是同一个任务
    await stop(app)


async def test_stop_noop_when_never_started():
    _, stop = _app_methods()
    app = _StubApp(auto_consolidate=True)
    await stop(app)  # must not raise 不得抛异常
    assert app._consolidation_task is None


async def test_cancel_mid_llm_releases_lock(tmp_path: Path):
    """Cancelling the task mid-LLM-call must still release the lock
    (run_once's finally). 任务在 LLM 调用中被取消也必须释放锁。"""

    class _HangingLLM:
        async def stream(self, messages: list[dict], **kwargs: Any):
            await asyncio.sleep(30)
            yield  # pragma: no cover

    pm = _make_memory(tmp_path)
    await _seed_user_entries(pm)
    sched = _scheduler(pm, _sessions(5), _HangingLLM())
    task = asyncio.create_task(sched.run_once())
    await asyncio.sleep(0.05)  # let it acquire the lock and reach the LLM call
    lock = tmp_path / "user_mem" / ConsolidationScheduler.LOCK_FILE
    assert lock.is_file()  # held mid-run 运行中锁被持有
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert not lock.is_file()  # finally released it 取消后 finally 已释放
