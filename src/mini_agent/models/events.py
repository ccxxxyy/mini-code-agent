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
class LLMResponseEvent(Event):
    content: str = ""
    has_tool_calls: bool = False
    tokens_used: int = 0
    # Input/output split + model name for cost tracking
    # 输入/输出拆分 + 模型名——供成本跟踪
    prompt_tokens: int = 0
    completion_tokens: int = 0
    model: str = ""
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0
    # Latency instrumentation 延迟埋点
    # ttft_ms: request sent -> first chunk carrying payload (delta / thinking /
    # tool_call_deltas). Empty role-only preamble chunks do NOT count, so this
    # measures time-to-first-*token*, not time-to-first-HTTP-frame. 0 when the
    # stream yielded no payload (cancelled / error / non-streaming provider).
    # ttft_ms：请求发出 → 首个带载荷的 chunk（正文/思考/工具调用增量）。
    # 只含 role 的空前导 chunk 不计，故测的是首 token 而非首个 HTTP 帧。
    # 流未产出任何载荷时为 0（取消/出错/非流式 Provider）。
    ttft_ms: float = 0
    # Full stream wall time: request sent -> stream exhausted.
    # 整个流的墙钟时长：请求发出 → 流结束。
    stream_duration_ms: float = 0


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


@dataclass
class PermissionRuleAddedEvent(Event):
    """Emitted when a permission rule is dynamically added at runtime.
    运行时动态添加权限规则时发射。"""

    scope: str = ""
    pattern: str = ""
    level: str = ""
    reason: str = ""


@dataclass
class PermissionRuleRemovedEvent(Event):
    """Emitted when a permission rule is dynamically removed at runtime.
    运行时动态移除权限规则时发射。"""

    scope: str = ""
    pattern: str = ""
    level: str = ""


@dataclass
class PermissionModeChangedEvent(Event):
    """Emitted when the session permission mode switches (/mode, /plan,
    exit_plan_mode). 会话权限模式切换时发射（/mode、/plan、exit_plan_mode）。"""

    old_mode: str = ""
    new_mode: str = ""


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
    # True when spawned via spawn_background -- completion is delivered
    # to 'main' as a mailbox notification 后台派生的完成经 mailbox 通知 main
    background: bool = False


@dataclass
class ContextSummaryStartEvent(Event):
    """Fork-style context summarization began (LLM call in progress).
    fork 式上下文摘要开始（LLM 调用进行中）。"""

    agent_count: int = 0


@dataclass
class ContextSummaryDoneEvent(Event):
    """Fork-style context summarization finished.
    fork 式上下文摘要完成。"""

    duration_ms: float = 0
    char_count: int = 0


# --- Session Events ---


@dataclass
class SessionStartEvent(Event):
    session_id: str = ""


@dataclass
class SessionEndEvent(Event):
    session_id: str = ""
