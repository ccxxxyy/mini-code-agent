"""Tests for tool_search and mcp_call tools + dispatch mode.
工具搜索/延迟加载的测试。"""

from __future__ import annotations

import pytest

from mini_agent.models.message import ToolResult
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.mcp.client import MCPManager

pytestmark = pytest.mark.asyncio

SAMPLE_TOOLS = [
    {
        "name": "get_issue",
        "description": "Get a GitHub issue by number",
        "inputSchema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "number": {"type": "integer"},
            },
            "required": ["owner", "repo", "number"],
        },
    },
    {
        "name": "create_pr",
        "description": "Create a pull request",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_repos",
        "description": "List repositories for an org",
        "inputSchema": {"type": "object", "properties": {"org": {"type": "string"}}},
    },
]


class FakeConnection:
    def __init__(self, name: str, tools: list[dict]):
        self.name = name
        self.tools = tools
        self.transport = FakeTransport()


class FakeTransport:
    async def start(self):
        pass

    async def close(self):
        pass


def make_mgr_with_dispatch(tools: list[dict], server: str = "github") -> MCPManager:
    mgr = MCPManager()
    mgr._dispatch_tools[server] = tools
    mgr._connections[server] = FakeConnection(server, tools)
    return mgr


# --- search_tools ---


def test_search_finds_by_name():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("issue")
    assert len(results) == 1
    assert results[0]["name"] == "get_issue"
    assert results[0]["server"] == "github"


def test_search_finds_by_description():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("pull request")
    assert len(results) == 1
    assert results[0]["name"] == "create_pr"


def test_search_no_match():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("database")
    assert results == []


def test_search_case_insensitive():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("ISSUE")
    assert len(results) == 1
    assert results[0]["name"] == "get_issue"


def test_search_returns_parameters():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("issue")
    assert "parameters" in results[0]
    assert results[0]["parameters"]["type"] == "object"


def test_search_multiple_matches():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    results = mgr.search_tools("get")
    assert len(results) == 1
    results2 = mgr.search_tools("")
    assert len(results2) == 3


# --- list_dispatch_tools ---


def test_list_dispatch_tools():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    tools = mgr.list_dispatch_tools()
    assert len(tools) == 3
    assert all("server" in t and "name" in t and "description" in t for t in tools)


def test_list_dispatch_tools_empty():
    mgr = MCPManager()
    assert mgr.list_dispatch_tools() == []


# --- dispatch mode in connect_server ---


def test_dispatch_mode_not_in_registry():
    mgr = MCPManager()
    registry = ToolRegistry()
    mgr._dispatch_tools["test"] = SAMPLE_TOOLS
    schemas = registry.get_schemas()
    assert len(schemas) == 0


def test_eager_mode_tools_in_registry():
    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    assert len(mgr._dispatch_tools.get("github", [])) == 3
    registry = ToolRegistry()
    assert len(registry.get_schemas()) == 0


# --- MCPCallTool ---


async def test_mcp_call_executes():
    from mini_agent.tools.builtin.mcp_call import MCPCallTool

    class MockMCPManager:
        async def call_tool(self, server: str, tool: str, arguments: dict) -> ToolResult:
            return ToolResult(
                call_id="", name=tool, output=f"Called {server}/{tool} with {arguments}"
            )

    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext

    ctx = ToolContext(
        working_dir=__import__("pathlib").Path.cwd(),
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        mcp_manager=MockMCPManager(),
    )
    tool = MCPCallTool()
    result = await tool.execute(ctx, server="github", tool="get_issue", arguments={"number": 1})
    assert not result.is_error
    assert "Called github/get_issue" in result.output


# --- ToolSearchTool ---


async def test_tool_search_tool_returns_results():
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    ctx = ToolContext(
        working_dir=__import__("pathlib").Path.cwd(),
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        mcp_manager=mgr,
    )
    tool = ToolSearchTool()
    result = await tool.execute(ctx, query="issue")
    assert not result.is_error
    assert "get_issue" in result.output
    assert "Found 1 tool" in result.output


async def test_tool_search_no_results():
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.session import Session
    from mini_agent.tools.base import ToolContext
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    mgr = make_mgr_with_dispatch(SAMPLE_TOOLS)
    ctx = ToolContext(
        working_dir=__import__("pathlib").Path.cwd(),
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        mcp_manager=mgr,
    )
    tool = ToolSearchTool()
    result = await tool.execute(ctx, query="nonexistent")
    assert "No tools matching" in result.output
    assert "get_issue" in result.output
