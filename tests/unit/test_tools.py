"""Tests for the tool system and builtin tools."""

import sys

import pytest

from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import (
    BashTool,
    EditFileTool,
    GlobTool,
    GrepTool,
    ReadFileTool,
    WriteFileTool,
)

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
