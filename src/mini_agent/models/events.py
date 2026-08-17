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
    # Input/output split + model name for cost tracking (P29)
    # 输入/输出拆分 + 模型名——供成本跟踪
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


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


@dataclass
class PermissionCheckEvent(Event):
    """Emitted after each permission decision (for /trace).
    每次权限判定后发射（用于 /trace）。
    """

    tool_name: str = ""
    scope: str = ""  # command / path / tool
    resource: str = ""
    decision: str = ""  # granted / denied
    reason: str = ""  # rule / session_grant / mode:xxx / user_confirm / dangerous
    matched_rule: str = ""  # matched rule pattern for audit trail 匹配的规则模式——供审计追踪


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


# --- SubAgent Events ---


@dataclass
class SubAgentSpawnEvent(Event):
    agent_id: str = ""
    task: str = ""


@dataclass
class SubAgentCompleteEvent(Event):
    agent_id: str = ""
    success: bool = True
    tokens_used: int = 0


# --- Session Events ---


@dataclass
class SessionStartEvent(Event):
    session_id: str = ""


@dataclass
class SessionEndEvent(Event):
    session_id: str = ""
