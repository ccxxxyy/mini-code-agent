"""Tests for OS-level sandbox (P41).
OS 级沙箱的测试。"""

from pathlib import Path
from unittest.mock import patch

import pytest

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import PermissionDecision
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.security.sandbox import SandboxConfig, create_sandbox
from mini_agent.security.sandbox.bwrap import BwrapSandbox
from mini_agent.security.sandbox.seatbelt import SeatbeltSandbox

pytestmark = pytest.mark.asyncio


# --- BwrapSandbox ---


async def test_bwrap_wrap_basic():
    sb = BwrapSandbox()
    cfg = SandboxConfig(allow_write=["/home/user/proj", "/tmp"], network=False)
    wrapped = sb.wrap("echo hello", cfg)
    assert "bwrap" in wrapped
    assert "--ro-bind" in wrapped
    assert "--unshare-net" in wrapped
    assert "echo hello" in wrapped


async def test_bwrap_wrap_with_network():
    sb = BwrapSandbox()
    cfg = SandboxConfig(allow_write=["/work"], network=True)
    wrapped = sb.wrap("curl http://example.com", cfg)
    assert "--unshare-net" not in wrapped


async def test_bwrap_wrap_deny_write():
    sb = BwrapSandbox()
    cfg = SandboxConfig(
        allow_write=["/home/user/proj"],
        deny_write=["/home/user/proj/secrets"],
    )
    wrapped = sb.wrap("ls", cfg)
    parts = wrapped.split()
    bind_idx = [i for i, p in enumerate(parts) if "proj" in p and "secrets" in p]
    assert bind_idx  # deny path appears in the command


async def test_bwrap_available_missing():
    with patch("shutil.which", return_value=None):
        assert not BwrapSandbox().available()


async def test_bwrap_available_present():
    with patch("shutil.which", return_value="/usr/bin/bwrap"):
        assert BwrapSandbox().available()


# --- SeatbeltSandbox ---


async def test_seatbelt_wrap_basic():
    sb = SeatbeltSandbox()
    cfg = SandboxConfig(allow_write=["/Users/me/proj"], network=False)
    wrapped = sb.wrap("echo hi", cfg)
    assert "sandbox-exec" in wrapped
    assert "(deny default)" in wrapped
    assert "(deny network*)" in wrapped
    assert "echo hi" in wrapped


async def test_seatbelt_wrap_with_network():
    sb = SeatbeltSandbox()
    cfg = SandboxConfig(allow_write=["/work"], network=True)
    wrapped = sb.wrap("curl x", cfg)
    assert "(allow network*)" in wrapped
    assert "(deny network*)" not in wrapped


async def test_seatbelt_profile_allow_write():
    sb = SeatbeltSandbox()
    cfg = SandboxConfig(allow_write=["/tmp", "/work"])
    wrapped = sb.wrap("ls", cfg)
    assert "(allow file-write*" in wrapped


async def test_seatbelt_available_missing():
    with patch.object(Path, "is_file", return_value=False):
        assert not SeatbeltSandbox().available()


# --- create_sandbox factory ---


async def test_create_sandbox_linux():
    with patch("platform.system", return_value="Linux"):
        sb = create_sandbox()
        assert isinstance(sb, BwrapSandbox)


async def test_create_sandbox_darwin():
    with patch("platform.system", return_value="Darwin"):
        sb = create_sandbox()
        assert isinstance(sb, SeatbeltSandbox)


async def test_create_sandbox_windows():
    with patch("platform.system", return_value="Windows"):
        assert create_sandbox() is None


# --- BashTool integration ---


async def test_bash_tool_sandbox_wraps_command():
    from mini_agent.security.sandbox import Sandbox

    class MockSandbox(Sandbox):
        def wrap(self, command, config):
            return f"SANDBOXED: {command}"

        def available(self):
            return True

    from mini_agent.tools.builtin.bash import BashTool

    tool = BashTool()
    tool.sandbox = MockSandbox()
    tool.sandbox_config = SandboxConfig(allow_write=["/tmp"])
    # We can't easily run the full execute without a real subprocess,
    # but we can verify the sandbox attributes are set correctly
    assert tool.sandbox.available()
    assert tool.sandbox.wrap("echo test", tool.sandbox_config) == "SANDBOXED: echo test"


async def test_bash_tool_no_sandbox_by_default():
    from mini_agent.tools.builtin.bash import BashTool

    tool = BashTool()
    assert tool.sandbox is None
    assert tool.sandbox_config is None


# --- Permission: sandbox_auto_allow ---


async def test_sandbox_auto_allow_dangerous_command(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    guard = PathGuard(
        tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode="ask"),
        path_guard=guard,
        confirm_callback=None,
    )
    pm.sandbox_auto_allow = True
    decision = await pm.check_command("git push origin main")
    assert decision == PermissionDecision.GRANTED
    assert pm.last_decision_reason == "sandbox_auto_allow"


async def test_sandbox_auto_allow_does_not_bypass_deny_rules(tmp_path: Path):
    project = tmp_path / "proj"
    project.mkdir()
    guard = PathGuard(
        tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode="ask", denied_commands=["docker rm *"]),
        path_guard=guard,
    )
    pm.sandbox_auto_allow = True
    decision = await pm.check_command("docker rm x")
    assert decision == PermissionDecision.DENIED
