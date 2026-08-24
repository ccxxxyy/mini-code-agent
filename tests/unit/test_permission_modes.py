"""Tests for the permission mode matrix: default / accept-edits / plan / bypass.
权限模式矩阵测试：default / accept-edits / plan / bypass。

Deny rules and sensitive-path denials must hold in EVERY mode -- modes only
relax (or tighten) what would otherwise prompt the user.
deny 规则和敏感路径拒绝在所有模式下有效——模式只放宽（或收紧）询问部分。
"""

from pathlib import Path

import pytest

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionMode,
    PermissionRule,
    PermissionScope,
)
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    d = tmp_path / "project"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def path_guard(project_dir: Path) -> PathGuard:
    return PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=project_dir,
    )


def make_pm(path_guard, mode: PermissionMode, confirm=None) -> PermissionManager:
    pm = PermissionManager(
        config=SecurityConfig(denied_commands=[]),
        path_guard=path_guard,
        confirm_callback=confirm,
    )
    pm.mode = mode
    return pm


async def _deny_confirm(_prompt: str) -> bool:
    raise AssertionError("must not prompt in this mode 此模式下不应弹窗")


# --- bypass ---


async def test_bypass_grants_dangerous_command(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS, confirm=_deny_confirm)
    assert await pm.check_command("sudo rm -rf /tmp/x") == PermissionDecision.GRANTED
    assert pm.last_decision_reason == "mode:bypass"


async def test_bypass_grants_outside_project_write(path_guard, tmp_path):
    pm = make_pm(path_guard, PermissionMode.BYPASS, confirm=_deny_confirm)
    outside = tmp_path / "other" / "file.txt"
    assert await pm.check_path(outside, "write") == PermissionDecision.GRANTED
    assert pm.last_decision_reason == "mode:bypass"


async def test_bypass_still_respects_deny_rule(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS)
    pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND, pattern="git push*", level=PermissionLevel.DENY
        )
    )
    assert await pm.check_command("git push origin main") == PermissionDecision.DENIED


async def test_bypass_still_denies_sensitive_path(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS)
    ssh_key = Path("~/.ssh/id_rsa").expanduser()
    assert await pm.check_path(ssh_key, "read") == PermissionDecision.DENIED
    assert pm.last_decision_reason == "path_guard:sensitive"


async def test_bypass_would_ask_false_for_dangerous(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS)
    assert pm.would_ask("bash", {"command": "sudo whoami"}) is False


async def test_bypass_sensitive_file_command_still_asks(path_guard):
    """`type .env` via bash must NOT be silently opened by bypass -- the
    sensitive-file check is ordered before the mode short-circuit (real-run
    verified leak before this ordering).
    bypass 不能静默放行 `type .env`——敏感文件检查排在模式短路之前
    （真实运行实测过泄漏）。"""
    asked = {}

    async def confirm(prompt: str) -> bool:
        asked["hit"] = True
        return False

    pm = make_pm(path_guard, PermissionMode.BYPASS, confirm=confirm)
    assert await pm.check_command("type .env") == PermissionDecision.DENIED
    assert asked.get("hit") is True
    assert pm.last_decision_reason == "user_confirm:no"


async def test_bypass_sensitive_file_command_no_ui_denied(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS)
    assert await pm.check_command("cat ~/.ssh/id_rsa") == PermissionDecision.DENIED


async def test_bypass_would_ask_true_for_sensitive_file_command(path_guard):
    pm = make_pm(path_guard, PermissionMode.BYPASS)
    assert pm.would_ask("bash", {"command": "type .env"}) is True


# --- accept-edits ---


async def test_accept_edits_grants_outside_project_write(path_guard, tmp_path):
    pm = make_pm(path_guard, PermissionMode.ACCEPT_EDITS, confirm=_deny_confirm)
    outside = tmp_path / "other" / "file.txt"
    assert await pm.check_path(outside, "write") == PermissionDecision.GRANTED
    assert pm.last_decision_reason == "mode:accept-edits"


async def test_accept_edits_still_asks_dangerous_command(path_guard):
    asked = {}

    async def confirm(prompt: str) -> bool:
        asked["prompt"] = prompt
        return False

    pm = make_pm(path_guard, PermissionMode.ACCEPT_EDITS, confirm=confirm)
    assert await pm.check_command("sudo whoami") == PermissionDecision.DENIED
    assert "sudo whoami" in asked["prompt"]


async def test_accept_edits_read_still_asks(path_guard, tmp_path):
    """Reads outside the project keep prompting -- only edits are accepted.
    项目外读仍询问——accept-edits 只放宽写。"""
    asked = {}

    async def confirm(prompt: str) -> bool:
        asked["hit"] = True
        return True

    pm = make_pm(path_guard, PermissionMode.ACCEPT_EDITS, confirm=confirm)
    outside = tmp_path / "other" / "file.txt"
    assert await pm.check_path(outside, "read") == PermissionDecision.GRANTED
    assert asked.get("hit") is True


async def test_accept_edits_still_denies_sensitive_write(path_guard, project_dir):
    pm = make_pm(path_guard, PermissionMode.ACCEPT_EDITS)
    assert await pm.check_path(project_dir / ".env", "write") == PermissionDecision.DENIED


async def test_accept_edits_would_ask_false_for_write(path_guard, tmp_path):
    pm = make_pm(path_guard, PermissionMode.ACCEPT_EDITS)
    outside = str(tmp_path / "other" / "file.txt")
    assert pm.would_ask("write_file", {"file_path": outside}) is False
    assert pm.would_ask("read_file", {"file_path": outside}) is True


# --- plan ---


async def test_plan_denies_bash_write_commands(path_guard):
    """The read-only guarantee covers the bash channel: write-form commands
    (redirects / file-mutating commands) are denied outright.
    只读保证覆盖 bash 通道：写形态命令（重定向/改文件命令）直接拒绝。"""
    pm = make_pm(path_guard, PermissionMode.PLAN, confirm=_deny_confirm)
    for cmd in (
        "echo HELLO> a.txt",
        "echo x >> log.txt",
        "mkdir newdir",
        "copy a.txt b.txt",
        "move a b",
        "del a.txt",
        "git diff > out.txt",
    ):
        assert await pm.check_command(cmd) == PermissionDecision.DENIED, cmd
        assert pm.last_decision_reason == "mode:plan"


async def test_plan_allows_readonly_bash_commands(path_guard):
    """Read-only commands stay usable for research -- including redirects
    that discard output (>nul / >/dev/null / 2>&1).
    只读命令仍可用于研究——含丢弃输出的重定向（>nul / >\\/dev\\/null / 2>&1）。"""
    pm = make_pm(path_guard, PermissionMode.PLAN, confirm=_deny_confirm)
    for cmd in (
        "type a.txt",
        "dir /b",
        "git status",
        "echo hello",
        "type a.txt 2>nul",
        "grep -r foo . 2>/dev/null",
    ):
        assert await pm.check_command(cmd) == PermissionDecision.GRANTED, cmd


async def test_default_bash_write_commands_unaffected(path_guard):
    pm = make_pm(path_guard, PermissionMode.DEFAULT, confirm=_deny_confirm)
    assert await pm.check_command("echo HELLO> a.txt") == PermissionDecision.GRANTED
    assert await pm.check_command("mkdir newdir") == PermissionDecision.GRANTED


async def test_plan_would_ask_false_for_bash_write(path_guard):
    pm = make_pm(path_guard, PermissionMode.PLAN)
    assert pm.would_ask("bash", {"command": "echo x > f.txt"}) is False


async def test_plan_quoted_gt_is_not_a_write(path_guard):
    """A `>` inside quotes is data, not a redirect -- read-only commands
    like findstr/awk/git-pretty must not be denied in plan mode.
    引号内的 `>` 是数据不是重定向——findstr/awk/git pretty 类只读命令
    不得在 plan 模式被误拦。"""
    pm = make_pm(path_guard, PermissionMode.PLAN, confirm=_deny_confirm)
    for cmd in (
        'git log --pretty="a>b"',
        'awk "$1 > 5" data.txt',
        'findstr ">" file.txt',
        "grep '>' file.txt",
    ):
        assert await pm.check_command(cmd) == PermissionDecision.GRANTED, cmd


async def test_plan_unbalanced_quote_still_denied(path_guard):
    """Unbalanced quotes are not stripped -- err toward deny.
    不成对引号不剥离——宁可误拦。"""
    pm = make_pm(path_guard, PermissionMode.PLAN)
    assert await pm.check_command('echo x > "a.txt') == PermissionDecision.DENIED


async def test_cmd_slash_c_is_dangerous(path_guard):
    """cmd /c inline execution joins the inline-interpreter dangerous list:
    a quoted redirect inside it survives quote-stripping via this prompt.
    cmd /c 内联执行纳入内联解释器危险清单：引号内重定向经此弹确认兜底。"""
    pm = make_pm(path_guard, PermissionMode.PLAN)
    # No UI -> dangerous prompt denies (quoted write cannot slip through)
    assert await pm.check_command('cmd /c "echo x > a.txt"') == PermissionDecision.DENIED
    assert pm.last_decision_reason in ("dangerous_command", "no_ui:default_deny")
    pm.mode = PermissionMode.DEFAULT
    assert await pm.check_command('cmd.exe /C "dir"') == PermissionDecision.DENIED


async def test_plan_denies_write_even_in_project(path_guard, project_dir):
    pm = make_pm(path_guard, PermissionMode.PLAN)
    target = project_dir / "src" / "main.py"
    assert await pm.check_path(target, "write") == PermissionDecision.DENIED
    assert pm.last_decision_reason == "mode:plan"


async def test_plan_allows_read_in_project(path_guard, project_dir):
    pm = make_pm(path_guard, PermissionMode.PLAN)
    target = project_dir / "src" / "main.py"
    assert await pm.check_path(target, "read") == PermissionDecision.GRANTED


async def test_plan_would_ask_false_for_write(path_guard, tmp_path):
    pm = make_pm(path_guard, PermissionMode.PLAN)
    outside = str(tmp_path / "other" / "file.txt")
    assert pm.would_ask("write_file", {"file_path": outside}) is False


# --- default: behavior unchanged ---


async def test_default_dangerous_command_asks(path_guard):
    asked = {}

    async def confirm(prompt: str) -> bool:
        asked["hit"] = True
        return True

    pm = make_pm(path_guard, PermissionMode.DEFAULT, confirm=confirm)
    assert await pm.check_command("sudo whoami") == PermissionDecision.GRANTED
    assert asked.get("hit") is True


async def test_default_outside_write_asks(path_guard, tmp_path):
    asked = {}

    async def confirm(prompt: str) -> bool:
        asked["hit"] = True
        return False

    pm = make_pm(path_guard, PermissionMode.DEFAULT, confirm=confirm)
    outside = tmp_path / "other" / "file.txt"
    assert await pm.check_path(outside, "write") == PermissionDecision.DENIED
    assert asked.get("hit") is True


# --- mode enum / config parsing ---


def test_mode_values():
    assert PermissionMode("default") is PermissionMode.DEFAULT
    assert PermissionMode("accept-edits") is PermissionMode.ACCEPT_EDITS
    assert PermissionMode("plan") is PermissionMode.PLAN
    assert PermissionMode("bypass") is PermissionMode.BYPASS
    with pytest.raises(ValueError):
        PermissionMode("yolo")


def test_default_manager_mode_is_default(path_guard):
    pm = PermissionManager(config=SecurityConfig(), path_guard=path_guard)
    assert pm.mode is PermissionMode.DEFAULT
