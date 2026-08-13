"""File-based mailbox for cross-agent messaging (6.2).
基于文件的跨 Agent 消息队列——每个 Agent 一个 JSON 收件箱。

Agents (main + sub-agents) exchange messages mid-run instead of only
returning final results. All agents run in one asyncio event loop, and
每个 send/drain 内部无 await，因此单文件读改写对事件循环是原子的，
无需文件锁。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class MailMessage:
    """A single message between agents. Agent 间的一条消息。"""

    sender: str
    recipient: str
    content: str
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat(timespec="seconds")


class Mailbox:
    """Per-agent JSON inbox files under a shared directory.
    共享目录下每个 Agent 一个 JSON 收件箱文件。"""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._registered: set[str] = set()

    def _inbox_path(self, agent_id: str) -> Path:
        return self._base / f"{agent_id}.json"

    def register(self, agent_id: str) -> None:
        """Create a fresh, empty inbox for an agent. Always resets so stale
        messages from a previous session are never delivered.
        为 Agent 创建全新空收件箱——总是重置，避免上一会话残留消息被投递。"""
        self._base.mkdir(parents=True, exist_ok=True)
        self._registered.add(agent_id)
        self._write(self._inbox_path(agent_id), [])

    def unregister(self, agent_id: str) -> None:
        """Remove an agent's inbox (undelivered messages are dropped).
        移除 Agent 收件箱（未读消息丢弃）。"""
        self._registered.discard(agent_id)
        self._inbox_path(agent_id).unlink(missing_ok=True)

    def send(self, sender: str, recipient: str, content: str) -> bool:
        """Append a message to the recipient's inbox. Returns False for
        unknown recipients. 追加消息到收件人收件箱；收件人未注册返回 False。"""
        if recipient not in self._registered:
            return False
        path = self._inbox_path(recipient)
        messages = self._read(path)
        messages.append(MailMessage(sender=sender, recipient=recipient, content=content))
        self._write(path, messages)
        return True

    def drain(self, agent_id: str) -> list[MailMessage]:
        """Read and clear an agent's inbox. 读取并清空 Agent 收件箱。"""
        if agent_id not in self._registered:
            return []
        path = self._inbox_path(agent_id)
        messages = self._read(path)
        if messages:
            self._write(path, [])
        return messages

    def peers(self, exclude: str | None = None) -> list[str]:
        """Registered agent ids, optionally excluding one (usually self).
        已注册的 Agent id 列表，可排除指定 id（通常是自己）。"""
        return sorted(a for a in self._registered if a != exclude)

    @staticmethod
    def _read(path: Path) -> list[MailMessage]:
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [MailMessage(**m) for m in data.get("messages", [])]
        except (OSError, ValueError, TypeError):
            return []

    @staticmethod
    def _write(path: Path, messages: list[MailMessage]) -> None:
        data = {"messages": [asdict(m) for m in messages]}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
