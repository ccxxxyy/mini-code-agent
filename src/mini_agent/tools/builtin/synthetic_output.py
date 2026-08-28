"""SyntheticOutput tool — sub-agents return structured JSON to the caller.
SyntheticOutput 工具——子 Agent 以结构化 JSON 向调用方返回结果。"""

from __future__ import annotations

import json
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext, ToolSchema


class SyntheticOutputTool(Tool):
    _name = "synthetic_output"
    category = ToolCategory.READ
    _description = (
        "Return structured data as your final output. Pass any JSON-serializable "
        "keyword arguments; they are stored verbatim and forwarded to the caller "
        "as a machine-readable result (no natural-language parsing needed)."
    )

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self._name,
            description=self._description,
            parameters=[],
            raw_parameters={
                "type": "object",
                "additionalProperties": True,
            },
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(
            call_id="",
            name=self._name,
            output=json.dumps(kwargs, ensure_ascii=False, default=str),
        )
