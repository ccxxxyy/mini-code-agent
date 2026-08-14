"""File-based mailbox for cross-agent messaging (6.2 + 6.4).
基于文件的跨 Agent 消息队列——每个 Agent 一个 JSON 收件箱。

Agents exchange messages mid-run instead of only returning final results.
Since 6.4 (multi-backend spawn) agents may live in SEPARATE PROCESSES
(tmux / Windows Terminal panes), so every read-modify-write cycle is
guarded by an O_EXCL lock file with exponential backoff, jitter, stale-lock
takeover and a hard timeout (adapted from mewcode's ``_with_lock``).
Writes go through temp-file + os.replace so plain readers never observe a
partial file. The agent registry (id -> name) also lives on disk
(``_registry.json``) so a worker process can resolve peers registered by
the parent process.
自 6.4 起 Agent 可能跑在独立进程（tmux / Windows Terminal 窗格），所有
读改写循环都由 O_EXCL 锁文件保护（指数退避 + 抖动 + 陈旧锁接管 + 超时），
写入走临时文件 + os.replace 原子替换，纯读永不见半截文件。注册表
（id -> 别名）同样落盘，worker 进程能解析父进程注册的同伴。

Wake-up note: mewcode pushes tmux send-keys to wake idle teammates; mini
workers are one-shot tasks that poll via wait_message (0.5s), so no push
channel is needed -- cross-process delivery latency is bounded by the poll
interval. 唤醒说明：mini 的 worker 靠 wait_message 轮询（0.5s）跨进程
收信，无需推送通道，投递延迟上界即轮询间隔。

Messages carry an optional structured protocol (P58.4):
type=text/request/response with request_id correlation and an approve
verdict. Drained messages are marked read and kept on disk for audit
within the session; a new SubAgentManager wipes stale inbox files.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Message types: plain text, a question expecting a reply, or the reply
# 消息类型：普通文本 / 期待回复的请求 / 对请求的应答
VALID_MESSAGE_TYPES = frozenset({"text", "request", "response"})

# Give up acquiring a lock after this many seconds -- the caller must know
# the message was NOT delivered rather than silently dropping it.
# 抢锁超时上限——到点抛异常让调用方知道消息没写进去，不能静默丢。
LOCK_TIMEOUT = 5.0
# A lock file older than this is considered abandoned by a crashed holder.
# 锁文件超过此秒数视为持有者已崩溃，可强行接管。
STALE_LOCK_AGE = 10.0
# Backoff ceiling so high contention doesn't back off forever.
# 退避上限，高并发下不会越退越久。
MAX_LOCK_BACKOFF = 0.08

_REGISTRY_NAME = "_registry.json"


@dataclass
class MailMessage:
    """A single message between agents. Agent 间的一条消息。"""

    sender: str
    recipient: str
    content: str
    timestamp: str = ""
    type: str = "text"
    request_id: str = ""
    approve: bool | None = None
    read: bool = False

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="seconds")


class Mailbox:
    """Per-agent JSON inbox files under a shared directory, safe across
    processes. 共享目录下每个 Agent 一个 JSON 收件箱文件，跨进程安全。"""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir

    @property
    def base_dir(self) -> Path:
        return self._base

    # ── paths ────────────────────────────────────────────────────

    def _inbox_path(self, agent_id: str) -> Path:
        return self._base / f"{agent_id}.json"

    def _registry_path(self) -> Path:
        return self._base / _REGISTRY_NAME

    # ── cross-process file lock 跨进程文件锁 ─────────────────────

    def _with_lock(self, path: Path, fn):
        """Run *fn* while holding ``<path>.lock``. O_EXCL creation is the
        atomic primitive; backoff grows exponentially with jitter so
        colliding processes don't wake in lockstep; stale locks from
        crashed holders are taken over.
        持有 ``<path>.lock`` 期间执行 fn。O_EXCL 创建是原子原语；退避
        指数增长且带抖动，避免多进程同刻醒来反复对撞；崩溃者遗留的
        陈旧锁会被接管。"""
        lock = Path(f"{path}.lock")
        deadline = time.monotonic() + LOCK_TIMEOUT
        backoff = 0.005
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > STALE_LOCK_AGE:
                        lock.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"mailbox: could not acquire {lock.name} within {LOCK_TIMEOUT}s"
                    )
                time.sleep(backoff + random.uniform(0, backoff))
                backoff = min(backoff * 2, MAX_LOCK_BACKOFF)
        try:
            return fn()
        finally:
            lock.unlink(missing_ok=True)

    # ── registry (id -> name), on disk 磁盘注册表 ────────────────

    def _read_registry(self) -> dict[str, str]:
        path = self._registry_path()
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            agents = data.get("agents", {})
            return {str(k): str(v) for k, v in agents.items()}
        except (OSError, ValueError, TypeError):
            return {}

    def _write_registry(self, agents: dict[str, str]) -> None:
        _atomic_write(self._registry_path(), {"agents": agents})

    # ── lifecycle ────────────────────────────────────────────────

    def register(self, agent_id: str, name: str = "") -> None:
        """Create a fresh, empty inbox and record the agent (with optional
        name alias) in the on-disk registry. Always resets the inbox so
        stale messages from a previous session are never delivered.
        创建全新空收件箱并将 Agent（可带别名）写入磁盘注册表——总是
        重置收件箱，避免上一会话残留消息被投递。"""
        if agent_id == "_registry":
            raise ValueError("agent_id '_registry' is reserved")
        self._base.mkdir(parents=True, exist_ok=True)

        def _add() -> None:
            agents = self._read_registry()
            agents[agent_id] = name
            self._write_registry(agents)

        self._with_lock(self._registry_path(), _add)
        inbox = self._inbox_path(agent_id)
        self._with_lock(inbox, lambda: _atomic_write(inbox, {"messages": []}))

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from the registry. The inbox file is KEPT on
        disk as an audit trail for this session (wiped by reset_all on the
        next session). 从注册表移除 Agent；收件箱文件保留作会话内审计。"""
        if not self._registry_path().is_file():
            return

        def _drop() -> None:
            agents = self._read_registry()
            agents.pop(agent_id, None)
            self._write_registry(agents)

        self._with_lock(self._registry_path(), _drop)

    def reset_all(self) -> None:
        """Wipe all inbox files, lock remnants and the registry
        (start-of-session cleanup). 清空全部收件箱/锁残留/注册表。"""
        if not self._base.is_dir():
            return
        for f in self._base.glob("*.json"):
            f.unlink(missing_ok=True)
        for f in self._base.glob("*.lock"):
            f.unlink(missing_ok=True)

    # ── resolution 解析 ──────────────────────────────────────────

    def resolve(self, recipient: str) -> str | None:
        """Resolve a recipient (agent id or name alias) to a registered id.
        将收件人（id 或别名）解析为已注册的 agent id。"""
        agents = self._read_registry()
        if recipient in agents:
            return recipient
        for aid, name in agents.items():
            if name and name == recipient:
                return aid
        return None

    def peers(self, exclude: str | None = None) -> list[str]:
        """Registered agent ids, optionally excluding one (usually self).
        已注册的 Agent id 列表，可排除指定 id（通常是自己）。"""
        return sorted(a for a in self._read_registry() if a != exclude)

    def name_of(self, agent_id: str) -> str:
        """Return the name alias for an id, or '' if unnamed.
        返回 id 对应的别名，无别名返回空串。"""
        return self._read_registry().get(agent_id, "")

    def describe_peers(self, exclude: str | None = None) -> str:
        """Human/LLM-friendly recipient listing: "name (id)" or bare id.
        对 LLM 友好的收件人列表："别名 (id)" 或裸 id。"""
        agents = self._read_registry()
        parts = []
        for aid in sorted(agents):
            if aid == exclude:
                continue
            name = agents[aid]
            parts.append(f"{name} ({aid})" if name else aid)
        return ", ".join(parts) if parts else "(none)"

    # ── messaging 收发 ───────────────────────────────────────────

    def send(
        self,
        sender: str,
        recipient: str,
        content: str,
        type: str = "text",
        request_id: str = "",
        approve: bool | None = None,
    ) -> bool:
        """Append a message to the recipient's inbox (by id or name).
        Returns False for unknown recipients.
        追加消息到收件人收件箱（id 或别名）；无法解析返回 False。"""
        target = self.resolve(recipient)
        if target is None:
            return False
        path = self._inbox_path(target)
        message = MailMessage(
            sender=sender,
            recipient=target,
            content=content,
            type=type,
            request_id=request_id,
            approve=approve,
        )

        def _append() -> None:
            messages = self._read(path)
            messages.append(message)
            _atomic_write(path, {"messages": [asdict(m) for m in messages]})

        self._with_lock(path, _append)
        return True

    def broadcast(
        self,
        sender: str,
        content: str,
        type: str = "text",
        request_id: str = "",
        approve: bool | None = None,
    ) -> list[str]:
        """Send to every registered agent except the sender. Returns the
        recipient ids. 发给除发送者外的所有已注册 Agent，返回收件人列表。"""
        recipients = self.peers(exclude=sender)
        for agent_id in recipients:
            self.send(sender, agent_id, content, type=type, request_id=request_id, approve=approve)
        return recipients

    def drain(self, agent_id: str) -> list[MailMessage]:
        """Return unread messages and mark them read. Messages stay in the
        file as an audit trail. 返回未读消息并标记已读；消息留盘供审计。"""
        if agent_id not in self._read_registry():
            return []
        path = self._inbox_path(agent_id)
        unread: list[MailMessage] = []

        def _mark() -> None:
            messages = self._read(path)
            for m in messages:
                if not m.read:
                    m.read = True
                    unread.append(m)
            if unread:
                _atomic_write(path, {"messages": [asdict(m) for m in messages]})

        self._with_lock(path, _mark)
        return unread

    @staticmethod
    def _read(path: Path) -> list[MailMessage]:
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [MailMessage(**m) for m in data.get("messages", [])]
        except (OSError, ValueError, TypeError):
            return []


def _atomic_write(path: Path, data: dict) -> None:
    """Write JSON via temp file + os.replace so readers never see a partial
    file. 临时文件 + os.replace 原子写，读者永不见半截文件。"""
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
