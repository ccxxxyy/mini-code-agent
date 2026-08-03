"""Event types for the event bus system. 事件总线系统的事件类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Event:
    """Base event. All events carry a timestamp. 基础事件。所有事件都携带时间戳。"""

    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


# --- User Events ---


@dataclass
class UserMessageEvent(Event):
    content: str = ""
    is_slash_command: bool = False


# --- LLM Events ---


@dataclass
class LLMRequestEvent(Event):
    message_count: int = 0
    tool_count: int = 0
    estimated_tokens: int = 0


@dataclass
class LLMStreamChunkEvent(Event):
    delta: str = ""


@dataclass
class LLMResponseEvent(Event):
    content: str = ""
    has_tool_calls: bool = False
    tokens_used: int = 0


@dataclass
class LLMErrorEvent(Event):
    error: str = ""
    retryable: bool = False


# --- Tool Events ---


@dataclass
class ToolCallStartEvent(Event):
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass
class ToolCallEndEvent(Event):
    tool_name: str = ""
    call_id: str = ""
    is_error: bool = False
    duration_ms: float = 0


# --- Agent Events ---


@dataclass
class AgentPhaseChangeEvent(Event):
    old_phase: str = ""
    new_phase: str = ""
    iteration: int = 0


@dataclass
class TurnCompleteEvent(Event):
    iteration_count: int = 0
    tools_called: int = 0
    tokens_used: int = 0


# --- Session Events ---


@dataclass
class SessionStartEvent(Event):
    session_id: str = ""


@dataclass
class SessionEndEvent(Event):
    session_id: str = ""
