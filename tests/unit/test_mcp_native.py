"""Tests for MCP native lazy loading mode (defer_loading).
MCP native 延迟加载模式测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig, LLMConfig, MCPConfig, MCPServerConfig
from mini_agent.models.message import Conversation, Message, Role, ToolResult
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry, ToolSchema
from mini_agent.tools.mcp.adapter import MCPToolAdapter
from mini_agent.tools.mcp.client import MCPManager

pytestmark = pytest.mark.asyncio

SAMPLE_TOOL_INFO = {
    "name": "get_issue",
    "description": "Get a GitHub issue",
    "inputSchema": {
        "type": "object",
        "properties": {
            "owner": {"type": "string", "description": "Owner"},
            "number": {"type": "integer", "description": "Number"},
        },
        "required": ["owner", "number"],
    },
}


class FakeMCPManager:
    async def call_tool(self, server_name, tool_name, arguments):
        return ToolResult(call_id="", name=tool_name, output="ok")


# --- ToolResult content_blocks ---


def test_tool_result_content_blocks_default():
    tr = ToolResult(call_id="c1", name="t", output="hello")
    assert tr.content_blocks is None


def test_tool_result_content_blocks_set():
    blocks = [{"type": "tool_reference", "tool_name": "mcp_gh_get_issue"}]
    tr = ToolResult(call_id="c1", name="t", output="hello", content_blocks=blocks)
    assert tr.content_blocks == blocks


def test_to_api_messages_includes_content_blocks():
    blocks = [{"type": "tool_reference", "tool_name": "mcp_gh_get_issue"}]
    tr = ToolResult(call_id="c1", name="t", output="text", content_blocks=blocks)
    conv = Conversation()
    conv.append(Message(role=Role.TOOL, tool_result=tr))
    api = conv.to_api_messages()
    assert api[0]["content_blocks"] == blocks


def test_to_api_messages_no_content_blocks_when_none():
    tr = ToolResult(call_id="c1", name="t", output="text")
    conv = Conversation()
    conv.append(Message(role=Role.TOOL, tool_result=tr))
    api = conv.to_api_messages()
    assert "content_blocks" not in api[0]


# --- ToolSchema defer_loading ---


def test_tool_schema_defer_loading_default():
    schema = ToolSchema(name="test", description="d", parameters=[])
    js = schema.to_json_schema()
    assert "defer_loading" not in js


def test_tool_schema_defer_loading_true():
    schema = ToolSchema(name="test", description="d", parameters=[], defer_loading=True)
    js = schema.to_json_schema()
    assert js["defer_loading"] is True
    assert js["type"] == "function"


def test_tool_schema_defer_loading_with_raw_parameters():
    schema = ToolSchema(
        name="test",
        description="d",
        parameters=[],
        raw_parameters={"type": "object", "properties": {}},
        defer_loading=True,
    )
    js = schema.to_json_schema()
    assert js["defer_loading"] is True


# --- MCPToolAdapter deferred ---


def test_adapter_deferred_false_by_default():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(server_name="gh", tool_info=SAMPLE_TOOL_INFO, manager=mgr)
    assert adapter.should_defer is False
    assert adapter.schema.defer_loading is False


def test_adapter_deferred_true():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(
        server_name="gh", tool_info=SAMPLE_TOOL_INFO, manager=mgr, deferred=True
    )
    assert adapter.should_defer is True
    assert adapter.schema.defer_loading is True


def test_adapter_deferred_json_schema():
    mgr = FakeMCPManager()
    adapter = MCPToolAdapter(
        server_name="gh", tool_info=SAMPLE_TOOL_INFO, manager=mgr, deferred=True
    )
    js = adapter.schema.to_json_schema()
    assert js["defer_loading"] is True
    assert js["function"]["name"] == "mcp_gh_get_issue"


# --- connect_server native mode ---


class FakeTransport:
    async def start(self):
        pass

    async def send(self, msg):
        if msg.get("method") == "tools/list":
            return {"result": {"tools": [SAMPLE_TOOL_INFO]}}
        return {"result": {}}

    async def close(self):
        pass


async def test_connect_server_native_dual_registration(monkeypatch):
    from mini_agent.tools.mcp import client as c_mod

    monkeypatch.setattr(c_mod, "StdioTransport", lambda **kw: FakeTransport())

    mgr = MCPManager()
    registry = ToolRegistry()
    cfg = MCPServerConfig(command="fake", loading="native")
    count = await mgr.connect_server("gh", cfg, registry)

    assert count == 1
    tool = registry.get("mcp_gh_get_issue")
    assert tool is not None
    assert tool.should_defer is True
    assert "gh" in mgr._dispatch_tools
    assert len(mgr._dispatch_tools["gh"]) == 1


async def test_connect_server_eager_no_defer(monkeypatch):
    from mini_agent.tools.mcp import client as c_mod

    monkeypatch.setattr(c_mod, "StdioTransport", lambda **kw: FakeTransport())

    mgr = MCPManager()
    registry = ToolRegistry()
    cfg = MCPServerConfig(command="fake", loading="eager")
    await mgr.connect_server("gh", cfg, registry)

    tool = registry.get("mcp_gh_get_issue")
    assert tool is not None
    assert tool.should_defer is False
    assert "gh" not in mgr._dispatch_tools


async def test_connect_server_dispatch_not_in_registry(monkeypatch):
    from mini_agent.tools.mcp import client as c_mod

    monkeypatch.setattr(c_mod, "StdioTransport", lambda **kw: FakeTransport())

    mgr = MCPManager()
    registry = ToolRegistry()
    cfg = MCPServerConfig(command="fake", loading="dispatch")
    await mgr.connect_server("gh", cfg, registry)

    assert registry.get("mcp_gh_get_issue") is None
    assert len(mgr._dispatch_tools["gh"]) == 1


# --- AnthropicProvider _convert_tools ---


def test_convert_tools_with_defer_loading():
    from mini_agent.llm.anthropic_provider import AnthropicProvider

    tools = [
        {
            "type": "function",
            "function": {
                "name": "mcp_gh_get_issue",
                "description": "Get issue",
                "parameters": {"type": "object", "properties": {}},
            },
            "defer_loading": True,
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read file",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    result = AnthropicProvider._convert_tools(tools)
    assert result[0]["defer_loading"] is True
    assert "defer_loading" not in result[1]
    assert result[0]["name"] == "mcp_gh_get_issue"


def test_convert_tools_without_defer_loading():
    from mini_agent.llm.anthropic_provider import AnthropicProvider

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]
    result = AnthropicProvider._convert_tools(tools)
    assert "defer_loading" not in result[0]


# --- AnthropicProvider _split_system content_blocks ---


def test_split_system_tool_result_with_content_blocks():
    from mini_agent.llm.anthropic_provider import AnthropicProvider

    messages = [
        {
            "role": "tool",
            "tool_call_id": "tc1",
            "content": "human readable text",
            "content_blocks": [
                {"type": "tool_reference", "tool_name": "mcp_gh_get_issue"},
            ],
        }
    ]
    _, api_msgs = AnthropicProvider._split_system(messages)
    assert len(api_msgs) == 1
    tool_result = api_msgs[0]["content"][0]
    assert tool_result["type"] == "tool_result"
    assert isinstance(tool_result["content"], list)
    assert tool_result["content"][0]["type"] == "tool_reference"


def test_split_system_tool_result_without_content_blocks():
    from mini_agent.llm.anthropic_provider import AnthropicProvider

    messages = [
        {
            "role": "tool",
            "tool_call_id": "tc1",
            "content": "plain text result",
        }
    ]
    _, api_msgs = AnthropicProvider._split_system(messages)
    tool_result = api_msgs[0]["content"][0]
    assert tool_result["content"] == "plain text result"


# --- ToolSearchTool native mode ---


def _make_native_ctx(tmp_path: Path) -> ToolContext:
    config = AgentConfig(
        llm=LLMConfig(provider="anthropic", api_key="test"),
        mcp=MCPConfig(
            servers={
                "gh": MCPServerConfig(command="fake", loading="native"),
            }
        ),
    )
    mgr = MCPManager()
    mgr._dispatch_tools["gh"] = [SAMPLE_TOOL_INFO]
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=config,
        mcp_manager=mgr,
    )


def _make_dispatch_ctx(tmp_path: Path) -> ToolContext:
    config = AgentConfig(
        llm=LLMConfig(provider="openai", api_key="test"),
        mcp=MCPConfig(
            servers={
                "gh": MCPServerConfig(command="fake", loading="dispatch"),
            }
        ),
    )
    mgr = MCPManager()
    mgr._dispatch_tools["gh"] = [SAMPLE_TOOL_INFO]
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=config,
        mcp_manager=mgr,
    )


async def test_tool_search_native_returns_tool_reference(tmp_path):
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    ctx = _make_native_ctx(tmp_path)
    tool = ToolSearchTool()
    result = await tool.execute(ctx, query="issue")
    assert result.content_blocks is not None
    assert len(result.content_blocks) == 1
    assert result.content_blocks[0]["type"] == "tool_reference"
    assert result.content_blocks[0]["tool_name"] == "mcp_gh_get_issue"
    assert "Found 1 tool" in result.output


async def test_tool_search_dispatch_returns_text(tmp_path):
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    ctx = _make_dispatch_ctx(tmp_path)
    tool = ToolSearchTool()
    result = await tool.execute(ctx, query="issue")
    assert result.content_blocks is None
    assert "get_issue" in result.output
    assert "Found 1 tool" in result.output


# --- Auto-fallback: native -> dispatch for non-Anthropic ---


def test_is_native_capable_anthropic_official():
    from mini_agent.app import Application

    config = AgentConfig(
        llm=LLMConfig(provider="anthropic", api_key="test", base_url="https://api.anthropic.com")
    )
    app = Application.__new__(Application)
    app.config = config
    assert app._is_native_capable() is True


def test_is_native_capable_anthropic_no_url():
    from mini_agent.app import Application

    config = AgentConfig(llm=LLMConfig(provider="anthropic", api_key="test"))
    app = Application.__new__(Application)
    app.config = config
    assert app._is_native_capable() is True


def test_is_native_capable_openai():
    from mini_agent.app import Application

    config = AgentConfig(llm=LLMConfig(provider="openai", api_key="test"))
    app = Application.__new__(Application)
    app.config = config
    assert app._is_native_capable() is False


def test_is_native_capable_third_party_gateway():
    from mini_agent.app import Application

    config = AgentConfig(
        llm=LLMConfig(
            provider="anthropic",
            api_key="test",
            base_url="https://dashscope.aliyuncs.com/compatible-mode",
        )
    )
    app = Application.__new__(Application)
    app.config = config
    assert app._is_native_capable() is False


# --- _adjust_mcp_meta_tools ---


def test_adjust_mcp_meta_tools_eager_removes_both():
    from mini_agent.app import Application
    from mini_agent.tools.builtin.mcp_call import MCPCallTool
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    app = Application.__new__(Application)
    app.tool_registry = ToolRegistry()
    app.tool_registry.register(ToolSearchTool())
    app.tool_registry.register(MCPCallTool())
    app._effective_mcp_modes = {"gh": "eager"}

    app._adjust_mcp_meta_tools()
    assert app.tool_registry.get("tool_search") is None
    assert app.tool_registry.get("mcp_call") is None


def test_adjust_mcp_meta_tools_native_keeps_search():
    from mini_agent.app import Application
    from mini_agent.tools.builtin.mcp_call import MCPCallTool
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    app = Application.__new__(Application)
    app.tool_registry = ToolRegistry()
    app.tool_registry.register(ToolSearchTool())
    app.tool_registry.register(MCPCallTool())
    app._effective_mcp_modes = {"gh": "native"}

    app._adjust_mcp_meta_tools()
    assert app.tool_registry.get("tool_search") is not None
    assert app.tool_registry.get("mcp_call") is None


def test_adjust_mcp_meta_tools_dispatch_keeps_both():
    from mini_agent.app import Application
    from mini_agent.tools.builtin.mcp_call import MCPCallTool
    from mini_agent.tools.builtin.tool_search import ToolSearchTool

    app = Application.__new__(Application)
    app.tool_registry = ToolRegistry()
    app.tool_registry.register(ToolSearchTool())
    app.tool_registry.register(MCPCallTool())
    app._effective_mcp_modes = {"gh": "dispatch"}

    app._adjust_mcp_meta_tools()
    assert app.tool_registry.get("tool_search") is not None
    assert app.tool_registry.get("mcp_call") is not None
