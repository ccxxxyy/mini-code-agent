"""MCP client -- manages server connections and tool discovery.
MCP 客户端——管理服务器连接与工具发现。"""

from __future__ import annotations

from typing import Any

from mini_agent.models.config import MCPServerConfig
from mini_agent.models.message import ToolResult
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.mcp.adapter import MCPToolAdapter
from mini_agent.tools.mcp.transport import MCPTransport, StdioTransport


class MCPServerConnection:
    """A connection to a single MCP server. 到单个 MCP 服务器的连接。"""

    def __init__(self, name: str, transport: MCPTransport) -> None:
        self.name = name
        self.transport = transport
        self.tools: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        """Send initialize request and discover tools. 发送 initialize 请求并发现工具。"""
        await self.transport.send(
            {
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "mini-code-agent", "version": "0.2.0"},
                },
            }
        )
        await self.transport.send({"method": "notifications/initialized", "params": {}})

        tools_response = await self.transport.send(
            {
                "method": "tools/list",
                "params": {},
            }
        )
        self.tools = tools_response.get("result", {}).get("tools", [])

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on this server. 调用此服务器上的工具。"""
        response = await self.transport.send(
            {
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
        )
        return response.get("result", {})


class MCPManager:
    """Manages multiple MCP server connections. 管理多个 MCP 服务器连接。"""

    def __init__(self) -> None:
        self._connections: dict[str, MCPServerConnection] = {}

    async def connect_server(
        self,
        name: str,
        config: MCPServerConfig,
        tool_registry: ToolRegistry,
    ) -> int:
        """Connect to an MCP server, discover tools, register them.

        Returns the number of tools discovered.

        连接到 MCP 服务器，发现工具并注册它们。
        返回发现的工具数量。
        """
        if config.transport == "stdio":
            transport: MCPTransport = StdioTransport(
                command=config.command,
                args=config.args,
                env=config.env or None,
            )
        elif config.transport in ("http", "sse"):
            if not config.url:
                raise ValueError(f"MCP server '{name}' needs a url for HTTP transport")
            from mini_agent.tools.mcp.transport import HTTPTransport

            transport = HTTPTransport(config.url, headers=config.headers or None)
        else:
            raise ValueError(f"Unsupported transport: {config.transport}")
        await transport.start()

        conn = MCPServerConnection(name, transport)
        await conn.initialize()
        self._connections[name] = conn

        for tool_info in conn.tools:
            adapter = MCPToolAdapter(
                server_name=name,
                tool_info=tool_info,
                manager=self,
            )
            tool_registry.register(adapter)

        return len(conn.tools)

    async def disconnect_server(self, name: str) -> None:
        conn = self._connections.pop(name, None)
        if conn:
            await conn.transport.close()

    async def disconnect_all(self) -> None:
        for name in list(self._connections):
            await self.disconnect_server(name)

    def list_servers(self) -> list[str]:
        return list(self._connections.keys())

    def list_server_tools(self, server_name: str) -> list[dict[str, Any]]:
        conn = self._connections.get(server_name)
        return conn.tools if conn else []

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> ToolResult:
        """Proxy a tool call to the appropriate MCP server.
        将工具调用代理到对应的 MCP 服务器。"""
        conn = self._connections.get(server_name)
        if not conn:
            return ToolResult(
                call_id="",
                name=tool_name,
                output=f"MCP server not connected: {server_name}",
                is_error=True,
            )

        try:
            result = await conn.call_tool(tool_name, arguments)
            content = result.get("content", [])
            text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
            output = "\n".join(text_parts) or str(result)
            is_error = result.get("isError", False)
            return ToolResult(call_id="", name=tool_name, output=output, is_error=is_error)
        except Exception as e:
            return ToolResult(
                call_id="",
                name=tool_name,
                output=f"MCP tool call failed: {e}",
                is_error=True,
            )
