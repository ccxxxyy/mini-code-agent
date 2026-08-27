"""Tool system foundation: Tool ABC, ToolRegistry, ToolContext.
工具系统基础：Tool 抽象基类、ToolRegistry、ToolContext。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.models.session import Session

if TYPE_CHECKING:
    from mini_agent.core.subagent import SubAgentManager


@dataclass
class ToolParameter:
    """Schema for a single tool parameter. 单个工具参数的 schema。"""

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


@dataclass
class ToolSchema:
    """JSON Schema-like description of a tool. 工具的类 JSON Schema 描述。"""

    name: str
    description: str
    parameters: list[ToolParameter]
    raw_parameters: dict[str, Any] | None = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format. 转换为 OpenAI function calling 格式。"""
        if self.raw_parameters is not None:
            return {
                "type": "function",
                "function": {
                    "name": self.name,
                    "description": self.description,
                    "parameters": self.raw_parameters,
                },
            }
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            prop: dict[str, Any] = {
                "type": p.type,
                "description": p.description,
            }
            if p.enum:
                prop["enum"] = p.enum
            if p.default is not None:
                prop["default"] = p.default
            properties[p.name] = prop
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }


@dataclass
class ToolContext:
    """Context passed to every tool execution. 传递给每次工具执行的上下文。"""

    working_dir: Path
    session: Session
    event_bus: EventBus
    config: AgentConfig
    subagent_manager: SubAgentManager | None = None
    mcp_manager: Any = None
    # Cross-agent messaging: shared Mailbox + this agent's identity
    # 跨 Agent 消息：共享 Mailbox + 本 Agent 身份
    mailbox: Any = None
    agent_id: str = "main"
    # Process tools: task board, plan-mode control, structured user questions
    # 流程工具：任务板、计划模式控制、结构化用户提问
    task_store: Any = None
    agent_loop_ref: Any = None  # SimpleNamespace(get_plan_mode, set_plan_mode)
    ask_user_callback: Any = None  # async (question, choices) -> str
    skill_registry: Any = None  # extensions/skills.py SkillRegistry
    file_state: Any = None  # tools/file_state_cache.py FileStateCache (read-before-edit)


def _resolve_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline all $ref pointers and strip Pydantic metadata (title).
    内联所有 $ref 引用并去除 Pydantic 元数据（title）。"""
    defs = schema.get("$defs", {})

    def _resolve(node: Any, seen: frozenset[str] = frozenset()) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                if ref_name in defs and ref_name not in seen:
                    resolved = _resolve(defs[ref_name], seen | {ref_name})
                    extra = {k: v for k, v in node.items() if k != "$ref"}
                    if extra:
                        resolved = {**resolved, **extra}
                    return resolved
                return node
            return {k: _resolve(v, seen) for k, v in node.items() if k not in ("title", "$defs")}
        if isinstance(node, list):
            return [_resolve(item, seen) for item in node]
        return node

    return _resolve(schema)


def _schema_from_model(name: str, description: str, model: type) -> ToolSchema:
    """Build a ToolSchema from a Pydantic BaseModel.
    从 Pydantic BaseModel 自动生成 ToolSchema。"""
    raw_schema = model.model_json_schema()
    resolved = _resolve_refs(raw_schema)
    return ToolSchema(
        name=name,
        description=description,
        parameters=[],
        raw_parameters=resolved,
    )


class Tool(ABC):
    """Base class for all tools (builtin + MCP-adapted).
    所有工具的基类（内置工具 + MCP 适配工具）。"""

    params_model: type | None = None
    _name: str = ""
    _description: str = ""
    # Side-effect class for the permission mode matrix (mode × category).
    # Conservative default: tools that don't declare one are treated as
    # EXTERNAL (plan mode denies them). 权限模式矩阵的副作用类别；未声明的
    # 工具保守默认 EXTERNAL（plan 模式拒绝）。
    category: ToolCategory = ToolCategory.EXTERNAL
    # True for tools that open a user dialog (ask_user, exit_plan_mode):
    # they must never eager-execute mid-stream -- a dialog cannot interleave
    # with live rendering (real-run: ask_user's prompt was buried by trace
    # lines because it fired while the LLM was still streaming).
    # 会打开用户对话框的工具（ask_user、exit_plan_mode）为 True：绝不能在
    # 流式期间抢先执行——对话框不能和流式渲染交错（实测：ask_user 在流
    # 未结束时弹出，提示符被 trace 行淹没）。
    opens_dialog: bool = False

    @property
    def schema(self) -> ToolSchema:
        """Return the tool's schema. Auto-generated from params_model when
        available; subclasses without params_model must override.
        返回工具 schema。有 params_model 时自动生成；否则子类必须覆盖。"""
        if self.params_model is not None:
            return _schema_from_model(self._name, self._description, self.params_model)
        raise NotImplementedError("Tool must define params_model or override schema")

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        """Execute the tool with given arguments. Returns result.
        使用给定参数执行工具。返回执行结果。"""
        ...

    def validate_args(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments against schema. Uses Pydantic when params_model
        is set; falls back to manual validation otherwise.
        有 params_model 时用 Pydantic 校验（含类型转换）；否则走手动校验。"""
        if self.params_model is not None:
            try:
                validated = self.params_model(**kwargs)
                return validated.model_dump()
            except Exception as e:
                raise ValueError(str(e)) from e
        schema = self.schema
        validated_dict: dict[str, Any] = {}
        for p in schema.parameters:
            if p.name in kwargs:
                validated_dict[p.name] = kwargs[p.name]
            elif p.required:
                raise ValueError(f"Missing required parameter '{p.name}' for tool '{schema.name}'")
            elif p.default is not None:
                validated_dict[p.name] = p.default
        return validated_dict

    def error_result(self, call_id: str, message: str) -> ToolResult:
        """Helper to build an error ToolResult. 构建错误 ToolResult 的辅助方法。"""
        return ToolResult(
            call_id=call_id,
            name=self.schema.name,
            output=message,
            is_error=True,
        )


class ToolRegistry:
    """Central registry of all available tools. 所有可用工具的中央 registry。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.schema.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get_schemas(self) -> list[dict[str, Any]]:
        """Return all tool schemas in OpenAI function calling format.
        以 OpenAI function calling 格式返回所有工具 schema。"""
        return [t.schema.to_json_schema() for t in self._tools.values()]

    def clone(self) -> ToolRegistry:
        """Create an independent copy (for sub-agents). 创建独立副本（供子 Agent 使用）。"""
        new = ToolRegistry()
        new._tools = dict(self._tools)
        return new

    def filter(
        self,
        allowed: list[str] | None = None,
        denied: list[str] | None = None,
    ) -> list[Tool]:
        tools = self.list_tools()
        if allowed is not None:
            tools = [t for t in tools if t.schema.name in allowed]
        if denied:
            tools = [t for t in tools if t.schema.name not in denied]
        return tools
