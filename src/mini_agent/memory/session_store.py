"""Session persistence -- save/load/list/delete sessions as JSON files.
session 持久化——以 JSON 文件形式保存/加载/列出/删除 session。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult
from mini_agent.models.session import Session, SessionMetadata

log = logging.getLogger(__name__)

DEFAULT_SESSION_DIR = "~/.mini-agent/sessions"


class SessionStore:
    """Manages session persistence on disk. 管理磁盘上的 session 持久化。"""

    def __init__(self, session_dir: str = DEFAULT_SESSION_DIR) -> None:
        self._dir = Path(session_dir).expanduser()

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    async def save(self, session: Session) -> Path:
        """Save session to disk. Returns the file path. 将 session 保存到磁盘。返回文件路径。"""
        session.metadata.last_active = datetime.now()
        data = _serialize_session(session)
        path = self._path_for(session.metadata.session_id)

        def _write() -> None:
            self._ensure_dir()
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        await asyncio.to_thread(_write)
        return path

    async def load(self, session_id: str) -> Session | None:
        """Load a session by ID. Returns None if not found.
        按 ID 加载 session。未找到时返回 None。"""
        path = self._path_for(session_id)

        def _read() -> dict[str, Any] | None:
            if not path.is_file():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

        try:
            data = await asyncio.to_thread(_read)
            if data is None:
                return None
            return _deserialize_session(data)
        except (json.JSONDecodeError, KeyError):
            log.debug("session load failed", exc_info=True)
            return None

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions (metadata only, sorted newest first).
        列出所有已保存的 session（仅元数据，按最新在前排序）。"""
        return await asyncio.to_thread(self._list_sessions_sync)

    def _list_sessions_sync(self) -> list[dict[str, Any]]:
        self._ensure_dir()
        sessions = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meta = data.get("metadata", {})
                sessions.append(
                    {
                        "session_id": meta.get("session_id", f.stem),
                        "model": meta.get("model", ""),
                        "total_turns": meta.get("total_turns", 0),
                        "last_active": meta.get("last_active", ""),
                        "project_dir": meta.get("project_dir", ""),
                        "closed_cleanly": meta.get("closed_cleanly", True),
                        "tags": meta.get("tags", []),
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue
        sessions.sort(key=lambda s: s.get("last_active", ""), reverse=True)
        return sessions

    async def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted.
        删除一个 session 文件。删除成功返回 True。"""
        path = self._path_for(session_id)

        def _delete() -> bool:
            if path.is_file():
                path.unlink()
                return True
            return False

        return await asyncio.to_thread(_delete)

    async def cleanup_stale(self, max_age_days: int = 30, crashed_max_age_days: int = 0) -> int:
        """Delete stale sessions. Normally-closed sessions older than
        *max_age_days* are removed; crashed sessions (closed_cleanly=False)
        older than *crashed_max_age_days* are also removed (0 = keep forever).
        Returns the total number of sessions removed.
        删除过期会话。正常关闭超过 max_age_days 天的删除；崩溃会话超过
        crashed_max_age_days 天的也删除（0 = 永久保留）。返回总删除数。"""
        if max_age_days <= 0 and crashed_max_age_days <= 0:
            return 0
        return await asyncio.to_thread(self._cleanup_stale_sync, max_age_days, crashed_max_age_days)

    def _cleanup_stale_sync(self, max_age_days: int, crashed_max_age_days: int) -> int:
        self._ensure_dir()
        clean_cutoff = datetime.now() - timedelta(days=max_age_days) if max_age_days > 0 else None
        crashed_cutoff = (
            datetime.now() - timedelta(days=crashed_max_age_days)
            if crashed_max_age_days > 0
            else None
        )
        removed = 0
        for f in list(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                meta = data.get("metadata", {})
                last_active = meta.get("last_active", "")
                if not last_active:
                    continue
                ts = datetime.fromisoformat(last_active)
                is_clean = meta.get("closed_cleanly", True)
                if is_clean and clean_cutoff and ts < clean_cutoff:
                    f.unlink()
                    removed += 1
                elif not is_clean and crashed_cutoff and ts < crashed_cutoff:
                    f.unlink()
                    removed += 1
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        if removed:
            log.debug("Cleaned up %d stale session(s)", removed)
        return removed


def _serialize_session(session: Session) -> dict[str, Any]:
    meta = session.metadata
    return {
        "metadata": {
            "session_id": meta.session_id,
            "created_at": meta.created_at.isoformat(),
            "last_active": meta.last_active.isoformat(),
            "project_dir": str(meta.project_dir) if meta.project_dir else None,
            "model": meta.model,
            "total_turns": meta.total_turns,
            "total_tokens_used": meta.total_tokens_used,
            "tags": meta.tags,
            "closed_cleanly": meta.closed_cleanly,
        },
        "conversation": {
            "system_prompt": session.conversation.system_prompt,
            "messages": [_serialize_message(m) for m in session.conversation.messages],
            **(
                {"compact_boundary": session.conversation.compact_boundary}
                if session.conversation.compact_boundary
                else {}
            ),
        },
    }


def _serialize_message(msg: Message) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": msg.id,
        "role": msg.role.value,
        "content": msg.content,
        "timestamp": msg.timestamp.isoformat(),
        "token_count": msg.token_count,
        "compressed": msg.compressed,
    }
    if msg.tool_calls:
        d["tool_calls"] = [
            {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in msg.tool_calls
        ]
    if msg.tool_result:
        d["tool_result"] = {
            "call_id": msg.tool_result.call_id,
            "name": msg.tool_result.name,
            "output": msg.tool_result.output,
            "is_error": msg.tool_result.is_error,
        }
    return d


def _deserialize_session(data: dict[str, Any]) -> Session:
    meta_data = data["metadata"]
    meta = SessionMetadata(
        session_id=meta_data["session_id"],
        created_at=datetime.fromisoformat(meta_data["created_at"]),
        last_active=datetime.fromisoformat(meta_data["last_active"]),
        project_dir=Path(meta_data["project_dir"]) if meta_data.get("project_dir") else None,
        model=meta_data.get("model", ""),
        total_turns=meta_data.get("total_turns", 0),
        total_tokens_used=meta_data.get("total_tokens_used", 0),
        tags=meta_data.get("tags", []),
        # Old files without the flag default to True (no false crash alarm)
        # 旧文件无此字段时默认 True（不误报崩溃）
        closed_cleanly=meta_data.get("closed_cleanly", True),
    )

    conv_data = data.get("conversation", {})
    boundary = conv_data.get("compact_boundary")
    conv = Conversation(system_prompt=conv_data.get("system_prompt", ""))

    if boundary:
        conv.compact_boundary = boundary
        from mini_agent.llm.token_counter import count_tokens as _count

        summary_msg = Message(role=Role.SYSTEM, content=boundary["summary"], compressed=True)
        summary_msg.token_count = _count(boundary["summary"]) + 4
        conv.append(summary_msg)

    for md in conv_data.get("messages", []):
        # With a boundary, skip compressed SYSTEM messages (covered by boundary summary)
        # 有边界时跳过已压缩的 SYSTEM 消息（已被边界摘要覆盖）
        if boundary and md.get("compressed", False) and md.get("role") == "system":
            continue
        tool_calls = [
            ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
            for tc in md.get("tool_calls", [])
        ]
        tool_result = None
        if "tool_result" in md and md["tool_result"]:
            tr = md["tool_result"]
            tool_result = ToolResult(
                call_id=tr["call_id"],
                name=tr["name"],
                output=tr["output"],
                is_error=tr.get("is_error", False),
            )
        msg = Message(
            id=md.get("id", ""),
            role=Role(md["role"]),
            content=md.get("content", ""),
            tool_calls=tool_calls,
            tool_result=tool_result,
            timestamp=datetime.fromisoformat(md["timestamp"])
            if md.get("timestamp")
            else datetime.now(),
            token_count=md.get("token_count"),
            compressed=md.get("compressed", False),
        )
        conv.append(msg)

    return Session(metadata=meta, conversation=conv)
