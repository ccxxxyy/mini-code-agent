"""Tests for file-based remote permission confirm (pane workers).
窗格 worker 的基于文件远程权限确认测试。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from mini_agent.security.remote_confirm import (
    RemoteConfirm,
    read_request,
    write_decision,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
def workers_dir(tmp_path: Path) -> Path:
    d = tmp_path / "workers"
    d.mkdir()
    return d


async def test_remote_confirm_writes_request_file(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-1", poll_interval=0.05, timeout=0.3)

    async def answer_after_delay():
        await asyncio.sleep(0.1)
        req = read_request(workers_dir, "agent-1")
        assert req is not None
        assert req["agent_id"] == "agent-1"
        assert req["status"] == "pending"
        assert "prompt" in req
        write_decision(workers_dir, "agent-1", req["request_id"], "y")

    asyncio.create_task(answer_after_delay())
    result = await rc("Allow bash access to: rm -rf /")
    assert result is True


async def test_remote_confirm_always_returns_always(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-2", poll_interval=0.05, timeout=0.5)

    async def answer():
        await asyncio.sleep(0.1)
        req = read_request(workers_dir, "agent-2")
        assert req is not None
        write_decision(workers_dir, "agent-2", req["request_id"], "a")

    asyncio.create_task(answer())
    result = await rc("Allow?")
    assert result == "always"


async def test_remote_confirm_deny(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-3", poll_interval=0.05, timeout=0.5)

    async def answer():
        await asyncio.sleep(0.1)
        req = read_request(workers_dir, "agent-3")
        write_decision(workers_dir, "agent-3", req["request_id"], "n")

    asyncio.create_task(answer())
    result = await rc("Allow?")
    assert result is False


async def test_remote_confirm_timeout_denies(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-4", poll_interval=0.05, timeout=0.2)
    result = await rc("Allow?")
    assert result is False


async def test_remote_confirm_cleans_up_files(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-5", poll_interval=0.05, timeout=0.5)

    async def answer():
        await asyncio.sleep(0.1)
        req = read_request(workers_dir, "agent-5")
        write_decision(workers_dir, "agent-5", req["request_id"], "y")

    asyncio.create_task(answer())
    await rc("Allow?")
    assert not (workers_dir / "agent-5.perm-request.json").exists()
    assert not (workers_dir / "agent-5.perm-decision.json").exists()


async def test_remote_confirm_timeout_cleans_request(workers_dir: Path):
    rc = RemoteConfirm(workers_dir, "agent-6", poll_interval=0.05, timeout=0.15)
    await rc("Allow?")
    assert not (workers_dir / "agent-6.perm-request.json").exists()


def test_read_request_returns_none_for_missing(workers_dir: Path):
    assert read_request(workers_dir, "nonexistent") is None


def test_read_request_returns_none_for_malformed(workers_dir: Path):
    path = workers_dir / "bad.perm-request.json"
    path.write_text("not json", encoding="utf-8")
    assert read_request(workers_dir, "bad") is None


def test_write_decision_atomic(workers_dir: Path):
    write_decision(workers_dir, "agent-7", "req-abc", "y")
    path = workers_dir / "agent-7.perm-decision.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["request_id"] == "req-abc"
    assert data["decision"] == "y"


async def test_wrong_request_id_ignored(workers_dir: Path):
    """Decision with mismatched request_id is ignored until timeout."""
    rc = RemoteConfirm(workers_dir, "agent-8", poll_interval=0.05, timeout=0.3)

    async def answer_wrong():
        await asyncio.sleep(0.1)
        write_decision(workers_dir, "agent-8", "wrong-id", "y")

    asyncio.create_task(answer_wrong())
    result = await rc("Allow?")
    assert result is False
