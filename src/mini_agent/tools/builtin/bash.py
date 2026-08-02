"""Bash tool -- execute shell commands."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

MAX_OUTPUT_CHARS = 30_000


class BashTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="bash",
            description=(
                "Execute a shell command and return its stdout/stderr. "
                "Runs in the working directory. Use for running programs, "
                "git commands, package managers, etc."
            ),
            parameters=[
                ToolParameter(
                    name="command",
                    type="string",
                    description="The shell command to execute",
                ),
                ToolParameter(
                    name="timeout",
                    type="integer",
                    description="Timeout in seconds (default 120)",
                    required=False,
                    default=120,
                ),
            ],
        )

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        command = kwargs["command"]
        timeout = float(kwargs.get("timeout", ctx.config.tools.bash_timeout))

        try:
            if sys.platform == "win32":
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(ctx.working_dir),
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(ctx.working_dir),
                    executable="/bin/bash",
                )
        except OSError as e:
            return self.error_result("", f"Failed to start command: {e}")

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return self.error_result("", f"Command timed out after {timeout}s: {command}")

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")

        parts: list[str] = []
        if stdout:
            parts.append(stdout.rstrip())
        if stderr:
            parts.append(f"[stderr]\n{stderr.rstrip()}")
        output = "\n".join(parts) or "(no output)"

        if len(output) > MAX_OUTPUT_CHARS:
            output = output[:MAX_OUTPUT_CHARS] + f"\n... (truncated, {len(output)} chars total)"

        exit_code = proc.returncode or 0
        if exit_code != 0:
            output = f"{output}\n[exit code: {exit_code}]"

        return ToolResult(
            call_id="",
            name="bash",
            output=output,
            is_error=exit_code != 0,
            metadata={"exit_code": exit_code},
        )
