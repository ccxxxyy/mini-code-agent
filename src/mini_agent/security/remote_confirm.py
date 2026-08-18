"""File-based remote permission callback for pane workers.
基于文件的远程权限回调——供窗格 worker 使用。

The worker side writes a request file and polls for the parent's decision
file. The parent (SubAgentManager._collect_pane_result) uses the read/write
helpers to relay the request through its own confirm callback.
worker 侧写请求文件并轮询父进程的决策文件。父进程
（SubAgentManager._collect_pane_result）通过辅助函数中转到自己的确认回调。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)


class RemoteConfirm:
    """File-based confirm callback for pane worker processes.
    窗格 worker 进程用的基于文件的确认回调。"""

    def __init__(
        self,
        workers_dir: Path,
        agent_id: str,
        poll_interval: float = 0.3,
        timeout: float = 120.0,
    ) -> None:
        self._workers_dir = workers_dir
        self._agent_id = agent_id
        self._poll_interval = poll_interval
        self._timeout = timeout

    async def __call__(self, prompt: str) -> bool | str:
        """Write a permission request and poll for the parent's decision.
        写权限请求文件并轮询父进程的决策。"""
        request_id = uuid.uuid4().hex[:8]
        req_path = self._workers_dir / f"{self._agent_id}.perm-request.json"
        dec_path = self._workers_dir / f"{self._agent_id}.perm-decision.json"

        _atomic_write(
            req_path,
            {
                "request_id": request_id,
                "agent_id": self._agent_id,
                "prompt": prompt,
                "status": "pending",
            },
        )

        deadline = time.monotonic() + self._timeout
        try:
            while time.monotonic() < deadline:
                if dec_path.is_file():
                    try:
                        data = json.loads(dec_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        data = None
                    if isinstance(data, dict) and data.get("request_id") == request_id:
                        decision = data.get("decision", "n")
                        if decision == "a":
                            return "always"
                        return decision == "y"
                await asyncio.sleep(self._poll_interval)
        finally:
            req_path.unlink(missing_ok=True)
            dec_path.unlink(missing_ok=True)

        logger.warning(
            "Permission request timed out for worker %s: %s",
            self._agent_id,
            prompt[:80],
        )
        return False


def read_request(workers_dir: Path, agent_id: str) -> dict | None:
    """Read a pending permission request file. Returns None if absent/malformed.
    读取待处理的权限请求文件。不存在或格式错则返回 None。"""
    path = workers_dir / f"{agent_id}.perm-request.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("status") == "pending":
            return data
    except (OSError, ValueError):
        pass
    return None


def write_decision(workers_dir: Path, agent_id: str, request_id: str, decision: str) -> None:
    """Write a permission decision file (atomic).
    原子写权限决策文件。"""
    path = workers_dir / f"{agent_id}.perm-decision.json"
    _atomic_write(path, {"request_id": request_id, "decision": decision})


def _atomic_write(path: Path, payload: dict) -> None:
    """Atomic JSON write via tmp + replace. 原子 JSON 写入。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
