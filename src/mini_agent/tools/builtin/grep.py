"""Grep tool -- search file contents with regex."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

MAX_MATCHES = 200
MAX_FILE_BYTES = 5_000_000
IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea", ".vscode"}


class GrepTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="grep",
            description=(
                "Search file contents using a regular expression. "
                "Returns matching lines with file path and line number."
            ),
            parameters=[
                ToolParameter(
                    name="pattern",
                    type="string",
                    description="Regular expression pattern to search for",
                ),
                ToolParameter(
                    name="path",
                    type="string",
                    description="Directory or file to search in (default: working directory)",
                    required=False,
                ),
                ToolParameter(
                    name="include",
                    type="string",
                    description="Glob filter for file names, e.g. '*.py' (default: all files)",
                    required=False,
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        pattern = kwargs["pattern"]
        base = Path(kwargs.get("path") or ctx.working_dir)
        if not base.is_absolute():
            base = ctx.working_dir / base
        include = kwargs.get("include")

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
            for lineno, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
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
