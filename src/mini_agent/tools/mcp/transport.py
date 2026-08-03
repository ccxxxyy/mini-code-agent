"""MCP transport abstractions -- stdio and HTTP.
MCP transport 抽象——stdio 与 HTTP。"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any


class MCPTransport(ABC):
    """Abstract transport for MCP server communication.
    用于 MCP 服务器通信的抽象 transport。"""

    @abstractmethod
    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC message and return the response. 发送 JSON-RPC 消息并返回响应。"""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the transport connection. 关闭 transport 连接。"""
        ...


class StdioTransport(MCPTransport):
    """Communicate with an MCP server via stdin/stdout of a child process.
    通过子进程的 stdin/stdout 与 MCP 服务器通信。"""

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._command = command
        self._args = args or []
        self._env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def start(self) -> None:
        """Start the MCP server subprocess. 启动 MCP 服务器子进程。"""
        import os

        merged_env = dict(os.environ)
        if self._env:
            merged_env.update(self._env)

        cmd = [self._command, *self._args]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )

    async def send(self, message: dict[str, Any]) -> dict[str, Any]:
        """Send JSON-RPC message via stdin, read response from stdout.
        通过 stdin 发送 JSON-RPC 消息，从 stdout 读取响应。"""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("Transport not started")

        self._request_id += 1
        message.setdefault("jsonrpc", "2.0")
        message.setdefault("id", self._request_id)

        data = json.dumps(message) + "\n"
        self._proc.stdin.write(data.encode("utf-8"))
        await self._proc.stdin.drain()

        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30.0)
        if not line:
            raise RuntimeError("MCP server closed connection")

        return json.loads(line.decode("utf-8"))

    async def close(self) -> None:
        if self._proc:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except TimeoutError:
                self._proc.kill()
            self._proc = None
