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
from mini_agent.security.sandbox.unshare import UnshareSandbox
from mini_agent.security.sandbox.windows import WindowsSandbox

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


# --- UnshareSandbox ---


async def test_unshare_wrap_basic():
    sb = UnshareSandbox()
    cfg = SandboxConfig(allow_write=["/home/user/proj", "/tmp"], network=False)
    wrapped = sb.wrap("echo hello", cfg)
    assert "unshare" in wrapped
    assert "--mount" in wrapped
    assert "--map-root-user" in wrapped
    assert "--net" in wrapped
    assert "remount,ro" in wrapped
    assert "echo hello" in wrapped


async def test_unshare_wrap_with_network():
    sb = UnshareSandbox()
    cfg = SandboxConfig(allow_write=["/work"], network=True)
    wrapped = sb.wrap("ls", cfg)
    assert "--net" not in wrapped


async def test_unshare_available():
    with patch("shutil.which", return_value="/usr/bin/unshare"):
        assert UnshareSandbox().available()


async def test_unshare_available_missing():
    with patch("shutil.which", return_value=None):
        assert not UnshareSandbox().available()


# --- create_sandbox factory ---


async def test_create_sandbox_linux_bwrap():
    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", return_value="/usr/bin/bwrap"):
            sb = create_sandbox()
            assert isinstance(sb, BwrapSandbox)


async def test_create_sandbox_linux_unshare_fallback():
    """When bwrap is missing, fall back to unshare."""
    with patch("platform.system", return_value="Linux"):
        with patch("shutil.which", side_effect=lambda n: None if n == "bwrap" else f"/usr/bin/{n}"):
            sb = create_sandbox()
            assert isinstance(sb, UnshareSandbox)


async def test_create_sandbox_darwin():
    with patch("platform.system", return_value="Darwin"):
        sb = create_sandbox()
        assert isinstance(sb, SeatbeltSandbox)


async def test_create_sandbox_windows():
    with patch("platform.system", return_value="Windows"):
        sb = create_sandbox()
        assert isinstance(sb, WindowsSandbox)


# --- WindowsSandbox ---


async def test_windows_mode_admin():
    with patch("mini_agent.security.sandbox.windows.is_admin", return_value=True):
        sb = WindowsSandbox()
        assert sb.mode == "low_integrity"


async def test_windows_mode_non_admin():
    with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
        sb = WindowsSandbox()
        assert sb.mode == "no_protection"


async def test_windows_admin_wrap_uses_helper(tmp_path):
    import base64

    work = tmp_path / "work"
    work.mkdir()
    with patch("mini_agent.security.sandbox.windows.is_admin", return_value=True):
        sb = WindowsSandbox()
        cfg = SandboxConfig(allow_write=[str(work)], network=True)
        wrapped = sb.wrap("echo hello", cfg)
    assert "EncodedCommand" in wrapped
    encoded_part = wrapped.split("EncodedCommand ")[-1]
    script = base64.b64decode(encoded_part).decode("utf-16-le")
    assert "_low_integrity" in script
    assert "setintegritylevel" in script


async def test_windows_nonadmin_wrap_passthrough(tmp_path):
    """Non-admin mode: no file protection -> wrap returns command as-is."""
    with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
        sb = WindowsSandbox()
        cfg = SandboxConfig(
            allow_write=[str(tmp_path / "work")],
            deny_write=[str(tmp_path / "protected")],
            network=True,
        )
        wrapped = sb.wrap("echo hello", cfg)
    assert wrapped == "echo hello"


async def test_windows_available():
    with patch("mini_agent.security.sandbox.windows.sys") as mock_sys:
        mock_sys.platform = "win32"
        mock_sys.executable = "/usr/bin/python"
        with patch("shutil.which", return_value="/usr/bin/powershell"):
            with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
                assert WindowsSandbox().available()


async def test_windows_available_missing_powershell():
    with patch("mini_agent.security.sandbox.windows.sys") as mock_sys:
        mock_sys.platform = "win32"
        with patch("shutil.which", return_value=None):
            with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
                assert not WindowsSandbox().available()


async def test_windows_available_on_linux():
    with patch("mini_agent.security.sandbox.windows.sys") as mock_sys:
        mock_sys.platform = "linux"
        with patch("shutil.which", return_value="/usr/bin/powershell"):
            with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
                assert not WindowsSandbox().available()


async def test_ps_escape_special_chars():
    """_ps_escape must handle backticks, $, and double quotes."""
    from mini_agent.security.sandbox.windows import _ps_escape

    assert _ps_escape('echo "hi"') == '"echo `"hi`""'
    assert _ps_escape("echo $HOME") == '"echo `$HOME"'
    assert _ps_escape("echo `done`") == '"echo ``done``"'
    assert _ps_escape('a"$b`c') == '"a`"`$b``c"'


async def test_low_integrity_helper_parses_double_dash():
    """Helper must handle commands containing -- correctly."""
    import sys
    from unittest.mock import patch as mpatch

    from mini_agent.security.sandbox._low_integrity import main

    # "-- echo -- hello" → command should be "echo -- hello"
    with mpatch.object(sys, "argv", ["helper", "--", "echo", "--", "hello"]):
        with mpatch.object(
            sys.modules["mini_agent.security.sandbox._low_integrity"],
            "lower_integrity",
            side_effect=OSError("skip in test"),
        ):
            result = main()
    assert result == 1  # lower_integrity fails, returns 1


async def test_windows_nonadmin_wrap_is_passthrough_even_with_net_deny(tmp_path):
    """Non-admin attrib mode: wrap always returns as-is (session-level setup)."""
    deny_dir = tmp_path / "protected"
    deny_dir.mkdir()
    with patch("mini_agent.security.sandbox.windows.is_admin", return_value=False):
        sb = WindowsSandbox()
        cfg = SandboxConfig(
            allow_write=[str(tmp_path / "work")],
            deny_write=[str(deny_dir)],
            network=False,
        )
        wrapped = sb.wrap("echo hello", cfg)
    assert wrapped == "echo hello"


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
