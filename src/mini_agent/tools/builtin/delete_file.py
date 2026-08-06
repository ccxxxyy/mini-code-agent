"""DeleteFile tool -- delete a single file. DeleteFile 工具——删除单个文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema


class DeleteFileTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="delete_file",
            description=(
                "Delete a single file. Fails if the path is a directory "
                "or the file does not exist. Prefer this over shell rm/del."
            ),
            parameters=[
                ToolParameter(
                    name="file_path",
                    type="string",
                    description="Path to the file to delete (absolute or relative to working dir)",
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path

        if file_path.is_dir():
            return self.error_result("", f"Refusing to delete directory: {file_path}")
        if not file_path.is_file():
            return self.error_result("", f"File not found: {file_path}")

        try:
            file_path.unlink()
        except OSError as e:
            return self.error_result("", f"Failed to delete {file_path}: {e}")

        return ToolResult(
            call_id="",
            name="delete_file",
            output=f"Deleted {file_path}",
            metadata={"deleted": True},
        )
