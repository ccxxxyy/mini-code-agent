"""WriteFile tool -- write content to a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema


class WriteFileTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="write_file",
            description=(
                "Write content to a file. Creates the file (and parent directories) "
                "if it doesn't exist, overwrites if it does."
            ),
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to the file to write (absolute or relative to working dir)",
                ),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Content to write to the file",
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path
        content = kwargs["content"]

        existed = file_path.exists()

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        except OSError as e:
            return self.error_result("", f"Failed to write {file_path}: {e}")

        action = "Overwrote" if existed else "Created"
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        byte_count = len(content.encode("utf-8"))
        return ToolResult(
            call_id="",
            name="write_file",
            output=f"{action} {file_path} ({line_count} lines, {byte_count} bytes)",
            metadata={"existed": existed, "bytes_written": byte_count},
        )
