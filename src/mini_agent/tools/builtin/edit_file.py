"""EditFile tool -- exact string replacement in a file.
EditFile 工具——在文件中进行精确字符串替换。"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext


class EditFileParams(BaseModel):
    """Pydantic model for edit_file parameters (P46). Auto-generates ToolSchema."""

    file_path: str = Field(
        description="Path to the file to edit (absolute or relative to working dir)"
    )
    old_text: str = Field(description="Exact text to find and replace")
    new_text: str = Field(description="Text to replace old_text with")
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences (default false: exactly one match)",
    )


class EditFileTool(Tool):
    _name = "edit_file"
    _description = (
        "Replace an exact string in a file with a new string. "
        "old_text must appear exactly once in the file unless replace_all is true."
    )
    params_model = EditFileParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        file_path = Path(kwargs["file_path"])
        if not file_path.is_absolute():
            file_path = ctx.working_dir / file_path
        old_text = kwargs["old_text"]
        new_text = kwargs["new_text"]
        replace_all = bool(kwargs.get("replace_all", False))

        if not file_path.is_file():
            return self.error_result("", f"File not found: {file_path}")

        if old_text == new_text:
            return self.error_result("", "old_text and new_text are identical")

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            return self.error_result("", f"Failed to read {file_path}: {e}")

        count = content.count(old_text)
        if count == 0:
            return self.error_result("", f"old_text not found in {file_path}")
        if count > 1 and not replace_all:
            return self.error_result(
                "",
                f"old_text appears {count} times in {file_path}. "
                "Provide more context to make it unique, or set replace_all=true.",
            )

        if replace_all:
            new_content = content.replace(old_text, new_text)
            replaced = count
        else:
            new_content = content.replace(old_text, new_text, 1)
            replaced = 1

        try:
            file_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            return self.error_result("", f"Failed to write {file_path}: {e}")

        old_lines = [line + "\n" for line in content.splitlines()]
        new_lines = [line + "\n" for line in new_content.splitlines()]
        diff_lines = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"a/{file_path.name}",
                tofile=f"b/{file_path.name}",
                n=3,
            )
        )
        diff_text = "".join(diff_lines)

        return ToolResult(
            call_id="",
            name="edit_file",
            output=f"Replaced {replaced} occurrence(s) in {file_path}",
            metadata={"replacements": replaced, "diff": diff_text},
        )
