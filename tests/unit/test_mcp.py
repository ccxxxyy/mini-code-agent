"""Tests for MCP client -- adapter and registry integration."""

from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.mcp.adapter import MCPToolAdapter


class FakeMCPManager:
    """Fake manager for testing MCPToolAdapter without real servers."""

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
