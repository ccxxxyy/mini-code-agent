"""Tests for user-defined permission rule files.
用户自定义权限规则文件的测试。"""

from pathlib import Path

import pytest

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import PermissionDecision
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager

pytestmark = pytest.mark.asyncio


def make_pm(tmp_path: Path, mode: str = "ask", confirm=None) -> tuple[PermissionManager, Path]:
    project = tmp_path / "proj"
    project.mkdir(exist_ok=True)
    guard = PathGuard(
        tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project
    )
    pm = PermissionManager(
        config=SecurityConfig(permission_mode=mode), path_guard=guard, confirm_callback=confirm
    )
    return pm, project


def write_rules(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


async def test_user_file_command_allow(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    f = write_rules(tmp_path / "user.toml", '[commands]\nallow = ["git push *"]\n')
    n = pm.load_rule_files(user_file=f)
    assert n == 1
    # Dangerous command normally asks; explicit allow rule resolves it
    # 危险命令原本要确认；显式 allow 规则直接放行
    assert await pm.check_command("git push origin main") == PermissionDecision.GRANTED


async def test_project_file_command_deny(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    f = write_rules(tmp_path / "proj.toml", '[commands]\ndeny = ["docker rm *"]\n')
    pm.load_rule_files(project_file=f)
    assert await pm.check_command("docker rm my-container") == PermissionDecision.DENIED


async def test_both_files_merge(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    u = write_rules(tmp_path / "u.toml", '[commands]\nallow = ["npm run *"]\n')
    p = write_rules(tmp_path / "p.toml", '[commands]\ndeny = ["npm publish *"]\n')
    n = pm.load_rule_files(user_file=u, project_file=p)
    assert n == 2
    assert await pm.check_command("npm run build") == PermissionDecision.GRANTED
    assert await pm.check_command("npm publish --tag latest") == PermissionDecision.DENIED


async def test_missing_files_noop(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    n = pm.load_rule_files(user_file=tmp_path / "nope1.toml", project_file=tmp_path / "nope2.toml")
    assert n == 0


async def test_malformed_toml_skipped(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    f = write_rules(tmp_path / "bad.toml", "this is [ not valid toml {{{")
    n = pm.load_rule_files(user_file=f)
    assert n == 0  # skipped with warning, no crash 警告后跳过不崩


async def test_path_deny_applies_inside_project(tmp_path: Path):
    """The PathGuard project-dir ALLOW must NOT bypass explicit deny rules.
    PathGuard 项目内放行不得绕过显式 deny 规则。"""
    pm, project = make_pm(tmp_path)
    f = write_rules(tmp_path / "r.toml", '[paths]\ndeny = ["*secrets*"]\n')
    pm.load_rule_files(user_file=f)

    in_project_secret = project / "secrets" / "api.txt"
    assert await pm.check_path(in_project_secret) == PermissionDecision.DENIED
    # Normal in-project path still allowed 正常项目内路径仍放行
    assert await pm.check_path(project / "main.py") == PermissionDecision.GRANTED


async def test_would_ask_consistent_with_deny(tmp_path: Path):
    pm, project = make_pm(tmp_path)
    f = write_rules(tmp_path / "r.toml", '[paths]\ndeny = ["*secrets*"]\n')
    pm.load_rule_files(user_file=f)
    # Deny resolves without prompting -> would_ask False
    # 显式拒绝无需弹窗 -> would_ask 为 False
    assert not pm.would_ask("read_file", {"file_path": str(project / "secrets" / "x.txt")})


async def test_deny_beats_allow_same_command(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    f = write_rules(
        tmp_path / "r.toml",
        '[commands]\nallow = ["docker *"]\ndeny = ["docker rm *"]\n',
    )
    pm.load_rule_files(user_file=f)
    assert await pm.check_command("docker build .") == PermissionDecision.GRANTED
    assert await pm.check_command("docker rm x") == PermissionDecision.DENIED


async def test_rule_source_in_reason(tmp_path: Path):
    pm, _ = make_pm(tmp_path)
    f = write_rules(tmp_path / "r.toml", '[commands]\ndeny = ["evil *"]\n')
    pm.load_rule_files(project_file=f)
    await pm.check_command("evil command")
    assert "rule:command:evil *" in pm.last_decision_reason
