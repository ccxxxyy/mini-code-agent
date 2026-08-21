"""ReadFile tool -- read file contents with line numbers.
ReadFile 工具——读取文件内容并附带行号。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class ReadFileParams(BaseModel):
    """Pydantic model for read_file parameters (P46). Auto-generates ToolSchema."""

    file_path: str = Field(
        description="Path to the file to read (absolute or relative to working dir)"
    )
    offset: int = Field(default=0, description="Line number to start reading from (0-based)")
    limit: int = Field(default=2000, description="Maximum number of lines to read")


class ReadFileTool(Tool):
    _name = "read_file"
    _description = (
        "Read the contents of a file at the given path. "
        "Returns file content with line numbers. "
        "Use offset/limit for large files."
    )
    params_model = ReadFileParams

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

        # Record for read-before-edit enforcement 记录以支持编辑前必读
        if ctx.file_state is not None:
            ctx.file_state.record(file_path)

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
