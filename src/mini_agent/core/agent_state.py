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
    # Distinct tool names used per iteration (sliding window of 8) --
    # a real loop calls the same tool every iteration; a batch job calls
    # it many times within ONE iteration, which is fine
    # 每轮迭代用到的工具名集合（滑窗 8）——真死循环是每轮都调同一个工具；
    # 批量任务是一轮内并行调多次，这是正常的
    iteration_tools: list[frozenset[str]] = field(default_factory=list)

    def record_iteration_tools(self, names: set[str]) -> None:
        self.iteration_tools.append(frozenset(names))
        if len(self.iteration_tools) > 8:
            self.iteration_tools = self.iteration_tools[-8:]

    @property
    def is_terminal(self) -> bool:
        return self.phase in (AgentPhase.TERMINATED, AgentPhase.ERROR)

    def transition(self, new_phase: AgentPhase) -> AgentPhase:
        old = self.phase
        self.phase = new_phase
        return old

    def record_tool_call(self, name: str, args_key: str = "") -> None:
        # Store name+args signature: same tool on DIFFERENT files is normal
        # batch work; only identical repeated calls indicate a real loop
        # 记录 名称+参数 签名：同一工具处理不同文件是正常批量工作，
        # 只有完全相同的重复调用才是真死循环
        self.recent_tool_names.append(f"{name}({args_key})" if args_key else name)
        if len(self.recent_tool_names) > 12:
            self.recent_tool_names = self.recent_tool_names[-12:]
