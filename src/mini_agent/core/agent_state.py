"""Agent state machine types. Agent 状态机类型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from mini_agent.models.message import ToolCall, ToolResult


class AgentPhase(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    OBSERVING = "observing"
    RESPONDING = "responding"
    ERROR = "error"
    TERMINATED = "terminated"


@dataclass
class AgentState:
    """Mutable state of an agent loop instance. Agent 循环实例的可变状态。"""

    phase: AgentPhase = AgentPhase.IDLE
    iteration: int = 0
    max_iterations: int = 50
    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    recent_tool_names: list[str] = field(default_factory=list)
    last_tool_results: list[ToolResult] = field(default_factory=list)

    @property
    def is_terminal(self) -> bool:
        return self.phase in (AgentPhase.TERMINATED, AgentPhase.ERROR)

    def transition(self, new_phase: AgentPhase) -> AgentPhase:
        old = self.phase
        self.phase = new_phase
        return old

    def record_tool_call(self, name: str) -> None:
        self.recent_tool_names.append(name)
        if len(self.recent_tool_names) > 12:
            self.recent_tool_names = self.recent_tool_names[-12:]
