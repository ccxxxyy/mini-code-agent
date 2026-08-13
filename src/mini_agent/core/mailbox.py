"""File-based mailbox for cross-agent messaging (6.2).
基于文件的跨 Agent 消息队列——每个 Agent 一个 JSON 收件箱。

Agents (main + sub-agents) exchange messages mid-run instead of only
returning final results. All agents run in one asyncio event loop, and
每个 send/drain 内部无 await，因此单文件读改写对事件循环是原子的，
无需文件锁。跨进程场景（6.4 多后端 spawn）需先补文件锁——见
comparison-mewcode.md 6.2 架构边界。

Messages carry an optional structured protocol (P58.4, adapted from
mewcode): type=text/request/response with request_id correlation and an
approve verdict. Drained messages are marked read and kept on disk for
audit within the session; a new SubAgentManager wipes stale inbox files.
消息支持结构化协议（type/request_id/approve）；drain 标记已读并留盘供
会话内审计，新会话由 SubAgentManager 统一清理陈旧收件箱文件。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

# Message types: plain text, a question expecting a reply, or the reply
# 消息类型：普通文本 / 期待回复的请求 / 对请求的应答
VALID_MESSAGE_TYPES = frozenset({"text", "request", "response"})


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
    """Per-agent JSON inbox files under a shared directory.
    共享目录下每个 Agent 一个 JSON 收件箱文件。"""

    def __init__(self, base_dir: Path) -> None:
        self._base = base_dir
        self._registered: set[str] = set()
        # Human-readable alias -> agent id 人类可读别名 -> agent id
        self._names: dict[str, str] = {}

    def _inbox_path(self, agent_id: str) -> Path:
        return self._base / f"{agent_id}.json"

    def register(self, agent_id: str, name: str = "") -> None:
        """Create a fresh, empty inbox for an agent, optionally with a
        human-readable name alias. Always resets so stale messages from a
        previous session are never delivered.
        为 Agent 创建全新空收件箱（可带人类可读别名）——总是重置，
        避免上一会话残留消息被投递。"""
        self._base.mkdir(parents=True, exist_ok=True)
        self._registered.add(agent_id)
        if name:
            self._names[name] = agent_id
        self._write(self._inbox_path(agent_id), [])

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from the registry. The inbox file is KEPT on
        disk as an audit trail for this session (wiped by reset_all on the
        next session). 从注册表移除 Agent；收件箱文件保留作会话内审计
        （下个会话由 reset_all 清理）。"""
        self._registered.discard(agent_id)
        self._names = {n: a for n, a in self._names.items() if a != agent_id}

    def reset_all(self) -> None:
        """Wipe all inbox files (start-of-session cleanup).
        清空全部收件箱文件（会话启动时清理）。"""
        if not self._base.is_dir():
            return
        for f in self._base.glob("*.json"):
            f.unlink(missing_ok=True)

    def resolve(self, recipient: str) -> str | None:
        """Resolve a recipient (agent id or name alias) to a registered id.
        将收件人（id 或别名）解析为已注册的 agent id。"""
        if recipient in self._registered:
            return recipient
        return self._names.get(recipient)

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
        messages = self._read(path)
        messages.append(
            MailMessage(
                sender=sender,
                recipient=target,
                content=content,
                type=type,
                request_id=request_id,
                approve=approve,
            )
        )
        self._write(path, messages)
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
        recipients = [a for a in sorted(self._registered) if a != sender]
        for agent_id in recipients:
            self.send(sender, agent_id, content, type=type, request_id=request_id, approve=approve)
        return recipients

    def drain(self, agent_id: str) -> list[MailMessage]:
        """Return unread messages and mark them read. Messages stay in the
        file as an audit trail. 返回未读消息并标记已读；消息留盘供审计。"""
        if agent_id not in self._registered:
            return []
        path = self._inbox_path(agent_id)
        messages = self._read(path)
        unread = [m for m in messages if not m.read]
        if unread:
            for m in unread:
                m.read = True
            self._write(path, messages)
        return unread

    def peers(self, exclude: str | None = None) -> list[str]:
        """Registered agent ids, optionally excluding one (usually self).
        已注册的 Agent id 列表，可排除指定 id（通常是自己）。"""
        return sorted(a for a in self._registered if a != exclude)

    def name_of(self, agent_id: str) -> str:
        """Return the name alias for an id, or '' if unnamed.
        返回 id 对应的别名，无别名返回空串。"""
        for name, aid in self._names.items():
            if aid == agent_id:
                return name
        return ""

    def describe_peers(self, exclude: str | None = None) -> str:
        """Human/LLM-friendly recipient listing: "name (id)" or bare id.
        对 LLM 友好的收件人列表："别名 (id)" 或裸 id。"""
        parts = []
        for aid in self.peers(exclude=exclude):
            name = self.name_of(aid)
            parts.append(f"{name} ({aid})" if name else aid)
        return ", ".join(parts) if parts else "(none)"

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
