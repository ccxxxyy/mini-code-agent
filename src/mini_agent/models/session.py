"""Session management types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from mini_agent.models.message import Conversation


@dataclass
class SessionMetadata:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    project_dir: Path | None = None
    model: str = ""
    total_turns: int = 0
    total_tokens_used: int = 0
    tags: list[str] = field(default_factory=list)


@dataclass
class Session:
    """A complete agent session that can be persisted and restored."""

    metadata: SessionMetadata = field(default_factory=SessionMetadata)
    conversation: Conversation = field(default_factory=Conversation)
