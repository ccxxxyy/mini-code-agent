"""WriteFile tool -- write content to a file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class WriteFileParams(BaseModel):
    """Pydantic model for write_file parameters (P46). Auto-generates ToolSchema."""

    file_path: str = Field(
        description="Path to the file to write (absolute or relative to working dir)"
    )
    content: str = Field(description="Content to write to the file")


class WriteFileTool(Tool):
    _name = "write_file"
    _description = (
        "Write content to a file. Creates the file (and parent directories) "
        "if it doesn't exist, overwrites if it does."
    )
    params_model = WriteFileParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path
        content = kwargs["content"]

        existed = file_path.exists()

        # Read-before-edit gate : overwriting an existing file requires
        # having read it first (creating a new file is exempt -- nothing to
        # clobber). Prevents blind overwrite of unread/externally-changed files.
        # 编辑前必读门：覆盖已存在文件须先读过（新建豁免——无内容可覆盖）；
        # 防止盲目覆盖未读或被外部改动的文件。
        if existed and ctx.file_state is not None:
            ok, err = ctx.file_state.check(file_path)
            if not ok:
                return self.error_result("", err)

        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        except OSError as e:
            return self.error_result("", f"Failed to write {file_path}: {e}")

        # Refresh cache after write 写入后刷新缓存
        if ctx.file_state is not None:
            ctx.file_state.update(file_path)

        action = "Overwrote" if existed else "Created"
        line_count = content.count("\n") + (1 if content and not content.endswith("\n") else 0)
        byte_count = len(content.encode("utf-8"))
        return ToolResult(
            call_id="",
            name="write_file",
            output=f"{action} {file_path} ({line_count} lines, {byte_count} bytes)",
            metadata={"existed": existed, "bytes_written": byte_count},
        )
