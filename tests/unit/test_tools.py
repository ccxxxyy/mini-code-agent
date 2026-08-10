"""Tests for the tool system and builtin tools. 工具系统与内置工具的测试。"""

import sys
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from mini_agent.tools.base import (
    ToolParameter,
    ToolRegistry,
    ToolSchema,
    _resolve_refs,
    _schema_from_model,
)
from mini_agent.tools.builtin import (
    BashTool,
    DeleteFileTool,
    EditFileTool,
    GlobTool,
    GrepTool,
    ReadFileTool,
    SpawnAgentsTool,
    WriteFileTool,
)

pytestmark = pytest.mark.asyncio

# --- ToolRegistry ---


def test_registry_register_and_get():
    registry = ToolRegistry()
    tool = ReadFileTool()
    registry.register(tool)
    assert registry.get("read_file") is tool
    assert registry.get("nonexistent") is None


def test_registry_schemas():
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    schemas = registry.get_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "read_file"
    assert "file_path" in schemas[0]["function"]["parameters"]["properties"]
    assert "file_path" in schemas[0]["function"]["parameters"]["required"]
    assert "offset" not in schemas[0]["function"]["parameters"]["required"]


def test_registry_clone_is_independent():
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    clone = registry.clone()
    clone.unregister("read_file")
    assert registry.get("read_file") is not None
    assert clone.get("read_file") is None


def test_registry_filter():
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    allowed = registry.filter(allowed=["read_file"])
    assert len(allowed) == 1
    denied = registry.filter(denied=["read_file"])
    assert all(t.schema.name != "read_file" for t in denied)


def test_validate_args_missing_required():
    tool = ReadFileTool()
    with pytest.raises(ValueError, match="file_path"):
        tool.validate_args({})


def test_validate_args_fills_defaults():
    tool = ReadFileTool()
    validated = tool.validate_args({"file_path": "/tmp/x"})
    assert validated["offset"] == 0
    assert validated["limit"] == 2000


# --- Pydantic Schema generation (P46) ---


def test_pydantic_schema_generation():
    tool = ReadFileTool()
    s = tool.schema
    assert s.name == "read_file"
    assert "file" in s.description.lower()
    js = s.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert set(props.keys()) == {"file_path", "offset", "limit"}
    assert "file_path" in req
    assert props["file_path"]["type"] == "string"
    assert "offset" not in req
    assert props["offset"]["default"] == 0
    assert props["offset"]["type"] == "integer"


def test_pydantic_schema_json_output():
    tool = ReadFileTool()
    js = tool.schema.to_json_schema()
    assert js["type"] == "function"
    assert js["function"]["name"] == "read_file"
    props = js["function"]["parameters"]["properties"]
    assert "file_path" in props
    assert props["offset"]["type"] == "integer"
    assert "file_path" in js["function"]["parameters"]["required"]
    assert "offset" not in js["function"]["parameters"]["required"]


def test_pydantic_validate_args_type_coercion():
    tool = ReadFileTool()
    result = tool.validate_args({"file_path": "/tmp/x", "offset": "5", "limit": "100"})
    assert result["offset"] == 5
    assert result["limit"] == 100
    assert isinstance(result["offset"], int)


def test_pydantic_validate_args_missing_required():
    tool = ReadFileTool()
    with pytest.raises(ValueError):
        tool.validate_args({})


def test_handwritten_schema_still_works():
    tool = BashTool()
    assert tool.params_model is None
    s = tool.schema
    assert s.name == "bash"
    assert any(p.name == "command" for p in s.parameters)
    validated = tool.validate_args({"command": "echo hi"})
    assert validated["command"] == "echo hi"
    assert validated["timeout"] == 120


def test_registry_mixed_pydantic_and_handwritten():
    registry = ToolRegistry()
    registry.register(ReadFileTool())  # Pydantic
    registry.register(BashTool())  # handwritten
    schemas = registry.get_schemas()
    assert len(schemas) == 2
    names = {s["function"]["name"] for s in schemas}
    assert names == {"read_file", "bash"}
    for s in schemas:
        assert s["type"] == "function"
        assert "properties" in s["function"]["parameters"]


# --- ReadFile ---


async def test_read_file(tool_context):
    f = tool_context.working_dir / "hello.txt"
    f.write_text("line one\nline two\n", encoding="utf-8")

    result = await ReadFileTool().execute(tool_context, file_path=str(f))
    assert not result.is_error
    assert "line one" in result.output
    assert result.metadata["total_lines"] == 2


async def test_read_file_not_found(tool_context):
    result = await ReadFileTool().execute(tool_context, file_path="missing.txt")
    assert result.is_error
    assert "not found" in result.output.lower()


async def test_read_file_offset_limit(tool_context):
    f = tool_context.working_dir / "many.txt"
    f.write_text("\n".join(f"line {i}" for i in range(100)), encoding="utf-8")

    result = await ReadFileTool().execute(tool_context, file_path=str(f), offset=10, limit=5)
    assert not result.is_error
    assert "line 10" in result.output
    assert "line 15" not in result.output


# --- WriteFile ---


async def test_write_file_creates(tool_context):
    target = tool_context.working_dir / "sub" / "new.txt"
    result = await WriteFileTool().execute(tool_context, file_path=str(target), content="hello")
    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "hello"
    assert "Created" in result.output


async def test_write_file_overwrites(tool_context):
    target = tool_context.working_dir / "exists.txt"
    target.write_text("old", encoding="utf-8")
    result = await WriteFileTool().execute(tool_context, file_path=str(target), content="new")
    assert not result.is_error
    assert target.read_text(encoding="utf-8") == "new"
    assert "Overwrote" in result.output


# --- EditFile ---


async def test_edit_file_single_replace(tool_context):
    f = tool_context.working_dir / "code.py"
    f.write_text("x = 1\ny = 2\n", encoding="utf-8")

    result = await EditFileTool().execute(
        tool_context, file_path=str(f), old_text="x = 1", new_text="x = 42"
    )
    assert not result.is_error
    assert "x = 42" in f.read_text(encoding="utf-8")


async def test_edit_file_ambiguous_match(tool_context):
    f = tool_context.working_dir / "dup.txt"
    f.write_text("aaa\naaa\n", encoding="utf-8")

    result = await EditFileTool().execute(
        tool_context, file_path=str(f), old_text="aaa", new_text="bbb"
    )
    assert result.is_error
    assert "2 times" in result.output


async def test_edit_file_replace_all(tool_context):
    f = tool_context.working_dir / "dup.txt"
    f.write_text("aaa\naaa\n", encoding="utf-8")

    result = await EditFileTool().execute(
        tool_context, file_path=str(f), old_text="aaa", new_text="bbb", replace_all=True
    )
    assert not result.is_error
    assert f.read_text(encoding="utf-8") == "bbb\nbbb\n"


async def test_edit_file_not_found_text(tool_context):
    f = tool_context.working_dir / "x.txt"
    f.write_text("content", encoding="utf-8")

    result = await EditFileTool().execute(
        tool_context, file_path=str(f), old_text="missing", new_text="y"
    )
    assert result.is_error


async def test_edit_file_returns_diff_in_metadata(tool_context):
    f = tool_context.working_dir / "diff_test.py"
    f.write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")

    result = await EditFileTool().execute(
        tool_context, file_path=str(f), old_text="y = 2", new_text="y = 42"
    )
    assert not result.is_error
    assert "diff" in result.metadata
    diff = result.metadata["diff"]
    assert "-y = 2" in diff
    assert "+y = 42" in diff
    assert "@@" in diff


# --- Bash ---


async def test_bash_echo(tool_context):
    result = await BashTool().execute(tool_context, command="echo hello")
    assert not result.is_error
    assert "hello" in result.output
    assert result.metadata["exit_code"] == 0


async def test_bash_nonzero_exit(tool_context):
    cmd = "exit 3" if sys.platform != "win32" else "cmd /c exit 3"
    result = await BashTool().execute(tool_context, command=cmd)
    assert result.is_error
    assert result.metadata["exit_code"] == 3


async def test_bash_timeout(tool_context):
    if sys.platform == "win32":
        cmd = "ping -n 30 127.0.0.1 >nul"
    else:
        cmd = "sleep 30"
    result = await BashTool().execute(tool_context, command=cmd, timeout=1)
    assert result.is_error
    assert "timed out" in result.output.lower()


# --- Glob ---


async def test_glob_finds_files(tool_context):
    (tool_context.working_dir / "a.py").write_text("", encoding="utf-8")
    (tool_context.working_dir / "b.py").write_text("", encoding="utf-8")
    (tool_context.working_dir / "c.txt").write_text("", encoding="utf-8")

    result = await GlobTool().execute(tool_context, pattern="*.py")
    assert not result.is_error
    assert result.metadata["count"] == 2
    assert "a.py" in result.output


async def test_glob_no_match(tool_context):
    result = await GlobTool().execute(tool_context, pattern="*.nonexistent")
    assert not result.is_error
    assert "No files found" in result.output


# --- Grep ---


async def test_grep_finds_matches(tool_context):
    f = tool_context.working_dir / "code.py"
    f.write_text("def foo():\n    pass\n\ndef bar():\n    pass\n", encoding="utf-8")

    result = await GrepTool().execute(tool_context, pattern=r"def \w+")
    assert not result.is_error
    assert result.metadata["matches"] == 2
    assert "foo" in result.output


async def test_grep_include_filter(tool_context):
    (tool_context.working_dir / "x.py").write_text("TODO fix", encoding="utf-8")
    (tool_context.working_dir / "y.txt").write_text("TODO fix", encoding="utf-8")

    result = await GrepTool().execute(tool_context, pattern="TODO", include="*.py")
    assert result.metadata["matches"] == 1


async def test_grep_context_lines(tool_context):
    f = tool_context.working_dir / "ctx.txt"
    f.write_text("before\ntarget\nafter\n", encoding="utf-8")

    result = await GrepTool().execute(tool_context, pattern="target", context=1)
    assert not result.is_error
    assert "before" in result.output
    assert "target" in result.output
    assert "after" in result.output


async def test_grep_invalid_regex(tool_context):
    result = await GrepTool().execute(tool_context, pattern="[invalid")
    assert result.is_error


# --- Pydantic schema for all other tools (P46) ---


def test_write_file_pydantic_schema():
    tool = WriteFileTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert js["function"]["name"] == "write_file"
    assert set(props.keys()) == {"file_path", "content"}
    assert "file_path" in req and "content" in req


def test_edit_file_pydantic_schema():
    tool = EditFileTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert js["function"]["name"] == "edit_file"
    assert set(props.keys()) == {"file_path", "old_text", "new_text", "replace_all"}
    assert "replace_all" not in req
    assert props["replace_all"]["default"] is False


def test_glob_pydantic_schema():
    tool = GlobTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert js["function"]["name"] == "glob"
    assert set(props.keys()) == {"pattern", "path"}
    assert "pattern" in req
    assert "path" not in req


def test_grep_pydantic_schema():
    tool = GrepTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert js["function"]["name"] == "grep"
    assert set(props.keys()) == {"pattern", "path", "include", "context"}
    assert props["context"]["default"] == 0


def test_delete_file_pydantic_schema():
    tool = DeleteFileTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert js["function"]["name"] == "delete_file"
    assert set(props.keys()) == {"file_path"}
    assert "file_path" in req


def test_spawn_agents_pydantic_schema():
    tool = SpawnAgentsTool()
    assert tool.params_model is not None
    js = tool.schema.to_json_schema()
    props = js["function"]["parameters"]["properties"]
    req = js["function"]["parameters"]["required"]
    assert js["function"]["name"] == "spawn_agents"
    assert set(props.keys()) == {"tasks", "isolated"}
    assert "tasks" in req
    assert props["tasks"]["type"] == "array"
    assert props["tasks"]["items"]["type"] == "string"


def test_pydantic_schema_all_tools_json_format():
    """Verify all Pydantic tools generate valid JSON schema format."""
    tools = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        GlobTool(),
        GrepTool(),
        DeleteFileTool(),
        SpawnAgentsTool(),
    ]
    for tool in tools:
        js = tool.schema.to_json_schema()
        assert js["type"] == "function"
        assert "function" in js
        assert "name" in js["function"]
        assert "parameters" in js["function"]
        assert "properties" in js["function"]["parameters"]
        assert "required" in js["function"]["parameters"]


# --- Enhanced schema generation (complex types) ---


def test_optional_type_schema():
    class M(BaseModel):
        name: str
        tag: str | None = None

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert "tag" in props
    assert "anyOf" in props["tag"]
    types = {opt["type"] for opt in props["tag"]["anyOf"]}
    assert types == {"string", "null"}


def test_array_items_schema():
    class M(BaseModel):
        names: list[str]
        counts: list[int] = []

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert props["names"]["type"] == "array"
    assert props["names"]["items"]["type"] == "string"
    assert props["counts"]["type"] == "array"
    assert props["counts"]["items"]["type"] == "integer"


def test_nested_model_schema():
    class Inner(BaseModel):
        value: int

    class Outer(BaseModel):
        item: Inner

    js = _schema_from_model("t", "d", Outer).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert "item" in props
    assert props["item"]["type"] == "object"
    assert props["item"]["properties"]["value"]["type"] == "integer"
    assert "$ref" not in str(props)


def test_constrained_field_schema():
    class M(BaseModel):
        age: int = Field(ge=0, le=150)
        name: str = Field(min_length=1, max_length=100)

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert props["age"]["minimum"] == 0
    assert props["age"]["maximum"] == 150
    assert props["name"]["minLength"] == 1
    assert props["name"]["maxLength"] == 100


def test_literal_type_schema():
    class M(BaseModel):
        mode: Literal["fast", "slow"]

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert props["mode"]["enum"] == ["fast", "slow"]


def test_default_in_json_output():
    class M(BaseModel):
        limit: int = 10
        tag: str = "default"

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert props["limit"]["default"] == 10
    assert props["tag"]["default"] == "default"


def test_resolve_refs_direct():
    schema = {
        "type": "object",
        "title": "Root",
        "properties": {
            "item": {"$ref": "#/$defs/Item"},
        },
        "$defs": {
            "Item": {
                "type": "object",
                "title": "Item",
                "properties": {"x": {"type": "integer"}},
                "required": ["x"],
            },
        },
        "required": ["item"],
    }
    resolved = _resolve_refs(schema)
    assert "$defs" not in resolved
    assert "title" not in resolved
    assert resolved["properties"]["item"]["type"] == "object"
    assert resolved["properties"]["item"]["properties"]["x"]["type"] == "integer"
    assert "title" not in resolved["properties"]["item"]


def test_dict_type_schema():
    class M(BaseModel):
        metadata: dict[str, int]

    js = _schema_from_model("t", "d", M).to_json_schema()
    props = js["function"]["parameters"]["properties"]
    assert props["metadata"]["type"] == "object"
    assert props["metadata"]["additionalProperties"]["type"] == "integer"


def test_manual_schema_emits_defaults():
    schema = ToolSchema(
        name="t",
        description="d",
        parameters=[ToolParameter(name="x", type="integer", description="", default=42)],
    )
    js = schema.to_json_schema()
    assert js["function"]["parameters"]["properties"]["x"]["default"] == 42


def test_resolve_refs_circular():
    schema = {
        "type": "object",
        "properties": {"node": {"$ref": "#/$defs/Node"}},
        "$defs": {
            "Node": {
                "type": "object",
                "properties": {"child": {"$ref": "#/$defs/Node"}},
            },
        },
    }
    resolved = _resolve_refs(schema)
    node = resolved["properties"]["node"]
    assert node["type"] == "object"
    assert node["properties"]["child"] == {"$ref": "#/$defs/Node"}
