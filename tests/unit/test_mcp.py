"""Tests for MCP client -- adapter and registry integration. MCP 客户端测试——适配器与注册表集成。"""

import pytest

from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.mcp.adapter import MCPToolAdapter

pytestmark = pytest.mark.asyncio


class FakeMCPManager:
    """Fake manager for testing MCPToolAdapter without real servers.
    用于在没有真实服务器的情况下测试 MCPToolAdapter 的伪造管理器。"""

    def __init__(self, response_output: str = "tool result", is_error: bool = False):
        self._output = response_output
        self._is_error = is_error
        self.calls: list[tuple[str, str, dict]] = []

    async def call_tool(self, server_name, tool_name, arguments):
        from mini_agent.models.message import ToolResult

        self.calls.append((server_name, tool_name, arguments))
        return ToolResult(
            call_id="",
            name=tool_name,
            output=self._output,
            is_error=self._is_error,
        )


SAMPLE_TOOL_INFO = {
    "name": "get_issue",
    "description": "Get a GitHub issue by number",
    "inputSchema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Repository owner"},
            "repo": {"type": "string", "description": "Repository name"},
            "number": {"type": "integer", "description": "Issue number"},
        },
        "required": ["owner", "repo", "number"],
    },
}


def test_adapter_schema():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(server_name="github", tool_info=SAMPLE_TOOL_INFO, manager=mgr)

    schema = adapter.schema
    assert schema.name == "mcp_github_get_issue"
    assert "GitHub issue" in schema.description
    param_names = {p.name for p in schema.parameters}
    assert param_names == {"owner", "repo", "number"}
    required_names = {p.name for p in schema.parameters if p.required}
    assert required_names == {"owner", "repo", "number"}


def test_adapter_json_schema():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(server_name="github", tool_info=SAMPLE_TOOL_INFO, manager=mgr)

    js = adapter.schema.to_json_schema()
    assert js["type"] == "function"
    assert js["function"]["name"] == "mcp_github_get_issue"
    assert "owner" in js["function"]["parameters"]["properties"]


async def test_adapter_execute(tool_context):
    mgr = FakeMCPManager(response_output="Issue #42: Fix bug")
    adapter = MCPToolAdapter(server_name="github", tool_info=SAMPLE_TOOL_INFO, manager=mgr)

    result = await adapter.execute(tool_context, owner="user", repo="project", number=42)
    assert not result.is_error
    assert "Issue #42" in result.output
    assert mgr.calls == [
        ("github", "get_issue", {"owner": "user", "repo": "project", "number": 42})
    ]


async def test_adapter_error(tool_context):
    mgr = FakeMCPManager(response_output="Server error", is_error=True)
    adapter = MCPToolAdapter(server_name="github", tool_info=SAMPLE_TOOL_INFO, manager=mgr)

    result = await adapter.execute(tool_context, owner="x", repo="y", number=1)
    assert result.is_error


def test_adapter_registers_in_registry():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(server_name="github", tool_info=SAMPLE_TOOL_INFO, manager=mgr)

    registry = ToolRegistry()
    registry.register(adapter)
    assert registry.get("mcp_github_get_issue") is adapter

    schemas = registry.get_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "mcp_github_get_issue" in names


def test_adapter_optional_params():
    tool_info = {
        "name": "search",
        "description": "Search",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["query"],
        },
    }
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(server_name="test", tool_info=tool_info, manager=mgr)

    schema = adapter.schema
    query_param = next(p for p in schema.parameters if p.name == "query")
    limit_param = next(p for p in schema.parameters if p.name == "limit")
    assert query_param.required is True
    assert limit_param.required is False


# --- HTTPTransport + MCPManager HTTP branch ---


async def test_http_transport_send(monkeypatch):
    import httpx

    from mini_agent.tools.mcp.transport import HTTPTransport

    t = HTTPTransport("http://fake/mcp")

    async def mock_post(self, url, **kwargs):
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    await t.start()
    resp = await t.send({"method": "tools/list"})
    assert resp["result"]["tools"] == []
    await t.close()


async def test_http_transport_error(monkeypatch):
    import httpx

    from mini_agent.tools.mcp.transport import HTTPTransport

    t = HTTPTransport("http://fake/mcp")

    async def mock_post(self, url, **kwargs):
        return httpx.Response(500, text="Internal Server Error", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    await t.start()
    with pytest.raises(httpx.HTTPStatusError):
        await t.send({"method": "tools/list"})
    await t.close()


async def test_http_transport_lifecycle():
    from mini_agent.tools.mcp.transport import HTTPTransport

    t = HTTPTransport("http://fake/mcp")
    await t.start()
    assert t._client is not None
    await t.close()
    assert t._client is None


async def test_connect_server_http_missing_url():
    from mini_agent.models.config import MCPServerConfig
    from mini_agent.tools.mcp.client import MCPManager

    mgr = MCPManager()
    cfg = MCPServerConfig(transport="http", url="")
    with pytest.raises(ValueError, match="needs a url"):
        await mgr.connect_server("bad", cfg, ToolRegistry())


async def test_connect_server_selects_http(monkeypatch):
    import httpx

    from mini_agent.models.config import MCPServerConfig
    from mini_agent.tools.mcp.client import MCPManager

    init_response = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05"}}
    tools_response = {"jsonrpc": "2.0", "id": 3, "result": {"tools": []}}
    call_count = 0

    async def mock_post(self, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return httpx.Response(200, json=init_response, request=httpx.Request("POST", url))
        return httpx.Response(200, json=tools_response, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)

    mgr = MCPManager()
    cfg = MCPServerConfig(transport="http", url="http://fake/mcp")
    count = await mgr.connect_server("test", cfg, ToolRegistry())
    assert count == 0  # no tools discovered 没有工具
    assert "test" in mgr._connections
    await mgr.disconnect_all()
