"""Session persistence -- save/load/list/delete sessions as JSON files."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult
from mini_agent.models.session import Session, SessionMetadata

DEFAULT_SESSION_DIR = "~/.mini-agent/sessions"


class SessionStore:
    """Manages session persistence on disk."""

    def __init__(self, session_dir: str = DEFAULT_SESSION_DIR) -> None:
        self._dir = Path(session_dir).expanduser()

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    async def save(self, session: Session) -> Path:
        """Save session to disk. Returns the file path."""
        self._ensure_dir()
        session.metadata.last_active = datetime.now()
        data = _serialize_session(session)
        path = self._path_for(session.metadata.session_id)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    async def load(self, session_id: str) -> Session | None:
        """Load a session by ID. Returns None if not found."""
        path = self._path_for(session_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return _deserialize_session(data)
        except (json.JSONDecodeError, KeyError):
            return None

    async def list_sessions(self) -> list[dict[str, Any]]:
        """List all saved sessions (metadata only, sorted newest first)."""
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
                    }
                )
            except (json.JSONDecodeError, KeyError):
                continue
        sessions.sort(key=lambda s: s.get("last_active", ""), reverse=True)
        return sessions

    async def delete(self, session_id: str) -> bool:
        """Delete a session file. Returns True if deleted."""
        path = self._path_for(session_id)
        if path.is_file():
            path.unlink()
            return True
        return False


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
        },
        "conversation": {
            "system_prompt": session.conversation.system_prompt,
            "messages": [_serialize_message(m) for m in session.conversation.messages],
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
    )

    conv_data = data.get("conversation", {})
    conv = Conversation(system_prompt=conv_data.get("system_prompt", ""))
    for md in conv_data.get("messages", []):
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
