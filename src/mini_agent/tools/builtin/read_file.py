"""ReadFile tool -- read file contents with line numbers.
ReadFile 工具——读取文件内容并附带行号。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema


class ReadFileTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="read_file",
            description=(
                "Read the contents of a file at the given path. "
                "Returns file content with line numbers. "
                "Use offset/limit for large files."
            ),
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to the file to read (absolute or relative to working dir)",
                ),
                ToolParameter(
                    name="offset",
                    type="integer",
                    description="Line number to start reading from (0-based)",
                    required=False,
                    default=0,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Maximum number of lines to read",
                    required=False,
                    default=2000,
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path
        offset = int(kwargs.get("offset", 0))
        limit = int(kwargs.get("limit", 2000))

        if not file_path.is_file():
            return self.error_result("", f"File not found: {file_path}")

        max_size = ctx.config.tools.max_file_size
        if file_path.stat().st_size > max_size:
            return self.error_result("", f"File too large (> {max_size} bytes): {file_path}")

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return self.error_result("", f"Failed to read {file_path}: {e}")

        lines = content.splitlines()
        selected = lines[offset : offset + limit]
        numbered = "\n".join(f"{i + offset + 1:>6}\t{line}" for i, line in enumerate(selected))

        if not numbered:
            numbered = "(empty file)" if not lines else "(offset beyond end of file)"

        return ToolResult(
            call_id="",
            name="read_file",
            output=numbered,
            metadata={"total_lines": len(lines), "shown": len(selected)},
        )
