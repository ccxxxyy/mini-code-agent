"""Grep tool -- search file contents with regex.
Grep 工具——用正则表达式搜索文件内容。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from mini_agent.models.message import ToolResult
from mini_agent.models.permissions import ToolCategory
from mini_agent.tools.base import Tool, ToolContext

MAX_MATCHES = 200
MAX_FILE_BYTES = 5_000_000
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea", ".vscode"}


class GrepParams(BaseModel):
    """Pydantic model for grep parameters. Auto-generates ToolSchema."""

    pattern: str = Field(description="Regular expression pattern to search for")
    path: str | None = Field(
        default=None,
        description="Directory or file to search in (default: working directory)",
    )
    include: str | None = Field(
        default=None,
        description="Glob filter for file names, e.g. '*.py' (default: all files)",
    )
    context: int = Field(
        default=0,
        description="Number of context lines to show before/after each match",
    )


class GrepTool(Tool):
    _name = "grep"
    category = ToolCategory.READ
    _description = (
        "Search file contents using a regular expression. "
        "Returns matching lines with file path and line number."
    )
    params_model = GrepParams

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        pattern = kwargs["pattern"]
        base = Path(kwargs.get("path") or ctx.working_dir)
        if not base.is_absolute():
            base = ctx.working_dir / base
        include = kwargs.get("include")
        context_lines = int(kwargs.get("context", 0))

        try:
            regex = re.compile(pattern)
        except re.error as e:
            return self.error_result("", f"Invalid regex pattern: {e}")

        if base.is_file():
            files = [base]
        elif base.is_dir():
            glob_pattern = f"**/{include}" if include else "**/*"
            try:
                files = [
                    p
                    for p in base.glob(glob_pattern)
                    if p.is_file() and not any(part in IGNORED_DIRS for part in p.parts)
                ]
            except (OSError, ValueError) as e:
                return self.error_result("", f"File scan failed: {e}")
        else:
            return self.error_result("", f"Path not found: {base}")

        matches: list[str] = []
        files_with_matches = 0
        for f in files:
            try:
                if f.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            file_matched = False
            all_lines = text.splitlines()
            for lineno, line in enumerate(all_lines, 1):
                if regex.search(line):
                    if context_lines > 0:
                        lo = max(0, lineno - 1 - context_lines)
                        hi = min(len(all_lines), lineno + context_lines)
                        for ci in range(lo, hi):
                            prefix = ":" if ci == lineno - 1 else "-"
                            display = all_lines[ci].strip()
                            if len(display) > 200:
                                display = display[:200] + "..."
                            matches.append(f"{f}:{ci + 1}{prefix} {display}")
                    else:
                        display = line.strip()
                        if len(display) > 200:
                            display = display[:200] + "..."
                        matches.append(f"{f}:{lineno}: {display}")
                    file_matched = True
                    if len(matches) >= MAX_MATCHES:
                        break
            if file_matched:
                files_with_matches += 1
            if len(matches) >= MAX_MATCHES:
                break

        if not matches:
            output = f"No matches for '{pattern}'"
        else:
            output = "\n".join(matches)
            if len(matches) >= MAX_MATCHES:
                output += f"\n... (truncated to {MAX_MATCHES} matches)"

        return ToolResult(
            call_id="",
            name="grep",
            output=output,
            metadata={"matches": len(matches), "files": files_with_matches},
        )
