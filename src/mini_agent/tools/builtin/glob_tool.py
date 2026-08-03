"""Glob tool -- find files by name pattern.
Glob 工具——按文件名模式查找文件。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

MAX_RESULTS = 500
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea", ".vscode"}


class GlobTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="glob",
            description=(
                "Find files matching a glob pattern (e.g. '**/*.py', 'src/**/*.ts'). "
                "Returns matching file paths sorted by modification time (newest first)."
            ),
            parameters=[
                ToolParameter(
                    name="pattern",
                    type="string",
                    description="Glob pattern to match files against",
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Directory to search in (default: working directory)",
                    required=False,
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        pattern = kwargs["pattern"]
        base = Path(kwargs.get("path") or ctx.working_dir)
        if not base.is_absolute():
            base = ctx.working_dir / base

        if not base.is_dir():
            return self.error_result("", f"Directory not found: {base}")

        try:
            matches = [
                p
                for p in base.glob(pattern)
                if p.is_file() and not any(part in IGNORED_DIRS for part in p.parts)
            ]
        except (OSError, ValueError) as e:
            return self.error_result("", f"Glob failed: {e}")

        matches.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        truncated = len(matches) > MAX_RESULTS
        matches = matches[:MAX_RESULTS]

        if not matches:
            output = f"No files found matching '{pattern}' in {base}"
        else:
            output = "\n".join(str(p) for p in matches)
            if truncated:
                output += f"\n... (truncated to {MAX_RESULTS} results)"

        return ToolResult(
            call_id="",
            name="glob",
            output=output,
            metadata={"count": len(matches), "truncated": truncated},
        )
