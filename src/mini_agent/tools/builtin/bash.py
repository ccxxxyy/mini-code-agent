"""Bash tool -- execute shell commands."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import Tool, ToolContext, ToolParameter, ToolSchema

MAX_OUTPUT_CHARS = 30_000


def _decode_console_bytes(data: bytes) -> str:
    """Decode subprocess output with Windows codepage fallback.
    CMD on Chinese Windows emits GBK (cp936) error messages -- plain UTF-8
    decoding turns them into mojibake. Try UTF-8 strictly first, then the
    active console codepage, then UTF-8 with replacement as last resort.
    解码子进程输出——中文 Windows 的 CMD 用 GBK 输出错误信息，纯 UTF-8
    解码会乱码。先严格试 UTF-8，再试控制台活动代码页，最后 UTF-8 容错兜底。
    """
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    if sys.platform == "win32":
        import locale

        for enc in (locale.getpreferredencoding(False), "gbk"):
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
    return data.decode("utf-8", errors="replace")


class BashTool(Tool):
    sandbox = None  # Sandbox | None — injected by app.py when enabled app.py 启用时注入
    sandbox_config = None  # SandboxConfig | None

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

        if self.sandbox and self.sandbox_config and self.sandbox.available():
            command = self.sandbox.wrap(command, self.sandbox_config)

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

        stdout = _decode_console_bytes(stdout_b)
        stderr = _decode_console_bytes(stderr_b)

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
