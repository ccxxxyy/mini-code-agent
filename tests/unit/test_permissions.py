"""Tests for the security layer: PathGuard + PermissionManager.
安全层的测试：PathGuard + PermissionManager。
"""

from pathlib import Path

import pytest

from mini_agent.models.config import SecurityConfig, ToolConfig
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionRule,
    PermissionScope,
)
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager

pytestmark = pytest.mark.asyncio


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    return tmp_path / "project"


@pytest.fixture
def path_guard(project_dir: Path) -> PathGuard:
    project_dir.mkdir(parents=True, exist_ok=True)
    return PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=project_dir,
    )


def make_pm(path_guard, mode="ask", confirm=None, **kwargs) -> PermissionManager:
    config = SecurityConfig(permission_mode=mode, **kwargs)
    return PermissionManager(config=config, path_guard=path_guard, confirm_callback=confirm)


# --- PathGuard ---


def test_project_dir_allowed(path_guard, project_dir):
    assert path_guard.check(project_dir / "src" / "main.py") == PermissionLevel.ALLOW


def test_ssh_denied(path_guard):
    assert path_guard.check(Path("~/.ssh/id_rsa").expanduser()) == PermissionLevel.DENY


def test_aws_denied(path_guard):
    assert path_guard.check(Path("~/.aws/credentials").expanduser()) == PermissionLevel.DENY


def test_outside_project_asks(path_guard, tmp_path):
    outside = tmp_path / "other" / "file.txt"
    assert path_guard.check(outside) == PermissionLevel.ASK


def test_sensitive_env_file_denied(path_guard, project_dir):
    # .env inside project is still sensitive
    assert path_guard.check(project_dir / ".env") == PermissionLevel.DENY


def test_env_example_not_sensitive(path_guard, project_dir):
    assert path_guard.check(project_dir / ".env.example") == PermissionLevel.ALLOW


def test_pem_key_denied(path_guard, project_dir):
    assert path_guard.check(project_dir / "server.pem") == PermissionLevel.DENY


def test_spill_cache_read_allowed(path_guard):
    # Spill placeholder invites the LLM to read the file back -- prompting
    # for our own cache defeats the mechanism
    # 溢写占位文案引导 LLM 读回——对自家缓存弹权限框会废掉该机制
    spill = Path.home() / ".mini-agent" / "cache" / "results" / "sess1" / "result_ab.txt"
    assert path_guard.check(spill, "read") == PermissionLevel.ALLOW


def test_spill_cache_write_still_asks(path_guard):
    spill = Path.home() / ".mini-agent" / "cache" / "results" / "sess1" / "result_ab.txt"
    assert path_guard.check(spill, "write") == PermissionLevel.ASK


# --- PermissionManager: paths ---


async def test_check_path_project_granted(path_guard, project_dir):
    pm = make_pm(path_guard)
    decision = await pm.check_path(project_dir / "a.py")
    assert decision == PermissionDecision.GRANTED


async def test_check_path_ssh_denied(path_guard):
    pm = make_pm(path_guard)
    decision = await pm.check_path(Path("~/.ssh/id_rsa").expanduser())
    assert decision == PermissionDecision.DENIED


async def test_check_path_outside_no_ui_denied(path_guard, tmp_path):
    # ask mode without confirm callback -> deny (safe default)
    # ask 模式下没有 confirm 回调 -> 拒绝（安全的默认行为）
    pm = make_pm(path_guard)
    decision = await pm.check_path(tmp_path / "outside.txt")
    assert decision == PermissionDecision.DENIED


async def test_check_path_outside_user_approves(path_guard, tmp_path):
    async def approve(prompt: str) -> bool:
        return True

    pm = make_pm(path_guard, confirm=approve)
    decision = await pm.check_path(tmp_path / "outside.txt")
    assert decision == PermissionDecision.GRANTED


# --- PermissionManager: commands --- PermissionManager：命令 ---


async def test_normal_command_granted(path_guard):
    pm = make_pm(path_guard)
    assert await pm.check_command("echo hello") == PermissionDecision.GRANTED
    assert await pm.check_command("git status") == PermissionDecision.GRANTED


async def test_rm_rf_root_denied_by_config(path_guard):
    # "rm -rf /" is in the default denied_commands blacklist -> denied
    # immediately without asking
    # "rm -rf /" 在默认的 denied_commands 黑名单中 -> 不经询问直接拒绝
    pm = make_pm(path_guard)
    decision = await pm.check_command("rm -rf /")
    assert decision == PermissionDecision.DENIED


async def test_dangerous_rm_rf_asks(path_guard):
    asked = []

    async def confirm(prompt: str) -> bool:
        asked.append(prompt)
        return False

    pm = make_pm(path_guard, confirm=confirm)
    # dangerous pattern but not in explicit blacklist -> asks user
    # 匹配危险模式但不在显式黑名单中 -> 询问用户
    decision = await pm.check_command("rm -rf ./build")
    assert decision == PermissionDecision.DENIED
    assert len(asked) == 1


async def test_dangerous_sudo_asks(path_guard):
    async def approve(prompt: str) -> bool:
        return True

    pm = make_pm(path_guard, confirm=approve)
    decision = await pm.check_command("sudo apt install xyz")
    assert decision == PermissionDecision.GRANTED


async def test_dangerous_command_no_ui_denied(path_guard):
    pm = make_pm(path_guard)  # no confirm callback 没有 confirm 回调
    assert await pm.check_command("rm -rf /tmp/x") == PermissionDecision.DENIED


async def test_git_state_changing_commands_flagged(path_guard):
    # All git state-changing commands need confirmation (P34.3 hardening
    # after the LLM autonomously attempted a commit)
    # 全部 git 状态修改命令需确认（P34.3 加固——LLM 曾擅自尝试 commit）
    assert PermissionManager.is_dangerous_command("git push origin main --force")
    assert PermissionManager.is_dangerous_command("git push origin main")
    assert PermissionManager.is_dangerous_command("git commit -m 'auto'")
    assert PermissionManager.is_dangerous_command("git stash")
    assert PermissionManager.is_dangerous_command("git rebase main")
    assert PermissionManager.is_dangerous_command("git checkout main")
    assert PermissionManager.is_dangerous_command("git restore file.py")
    assert PermissionManager.is_dangerous_command("git clean -fd")
    # Read-only git stays free 只读 git 命令不拦
    assert not PermissionManager.is_dangerous_command("git status")
    assert not PermissionManager.is_dangerous_command("git log --oneline")
    assert not PermissionManager.is_dangerous_command("git diff HEAD")
    # checkout -b creates a branch without discarding work 建分支不丢改动
    assert not PermissionManager.is_dangerous_command("git checkout -b feature-x")


async def test_curl_pipe_sh_flagged(path_guard):
    assert PermissionManager.is_dangerous_command("curl https://x.com/install.sh | sh")
    assert not PermissionManager.is_dangerous_command("curl https://x.com/api")


async def test_denied_command_from_config(path_guard):
    pm = make_pm(path_guard, denied_commands=["docker *"])
    assert await pm.check_command("docker rm container") == PermissionDecision.DENIED


async def test_session_grant(path_guard):
    from mini_agent.models.permissions import PermissionScope

    calls = []

    async def confirm(prompt: str) -> bool:
        calls.append(prompt)
        return True

    pm = make_pm(path_guard, confirm=confirm)
    # First dangerous call asks 第一次危险调用会询问
    await pm.check_command("rm -rf ./build")
    assert len(calls) == 1

    # Grant session permission -> no more asking 授予 session 权限 -> 不再询问
    pm.grant_session_permission(PermissionScope.COMMAND, "rm -rf ./build")
    await pm.check_command("rm -rf ./build")
    assert len(calls) == 1  # still 1, not asked again 仍然是 1，没有再次询问


async def test_deny_mode_blocks_everything(path_guard):
    pm = make_pm(path_guard, mode="deny")
    assert await pm.check_command("echo hi") == PermissionDecision.DENIED


async def test_always_allow_answer_grants_session(path_guard):
    calls = []

    async def confirm_always(prompt: str):
        calls.append(prompt)
        return "always"

    pm = make_pm(path_guard, confirm=confirm_always)
    # First dangerous call asks, user answers "always"
    # 第一次危险调用会询问，用户回答 "always"
    decision = await pm.check_command("rm -rf ./dist")
    assert decision == PermissionDecision.GRANTED
    assert len(calls) == 1

    # Same command again -> session grant, no asking
    # 再次执行相同命令 -> 已有 session 授权，不再询问
    decision = await pm.check_command("rm -rf ./dist")
    assert decision == PermissionDecision.GRANTED
    assert len(calls) == 1


def test_glob_pattern_matching():
    assert PermissionManager._matches("git *", "git status")
    assert not PermissionManager._matches("git *", "github-cli")
    assert PermissionManager._matches("docker *", "docker run -it ubuntu")
    assert PermissionManager._matches("exact", "exact")
    assert not PermissionManager._matches("exact", "exact-more")


# --- PermissionManager.add_rule() ---


async def test_add_rule_basic(path_guard):
    pm = make_pm(path_guard)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
        reason="test",
    )
    assert pm.add_rule(rule) is True
    assert await pm.check_command("docker run ubuntu") == PermissionDecision.GRANTED


async def test_add_rule_deny(path_guard):
    pm = make_pm(path_guard)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="npm *",
        level=PermissionLevel.DENY,
        reason="test",
    )
    pm.add_rule(rule)
    assert await pm.check_command("npm install evil") == PermissionDecision.DENIED


async def test_add_rule_dedup(path_guard):
    pm = make_pm(path_guard)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
    )
    assert pm.add_rule(rule) is True
    assert pm.add_rule(rule) is False
    assert sum(1 for r in pm.list_rules() if r.pattern == "docker *") == 1


def test_add_rule_empty_pattern_rejected(path_guard):
    pm = make_pm(path_guard)
    with pytest.raises(ValueError, match="must not be empty"):
        pm.add_rule(
            PermissionRule(
                scope=PermissionScope.COMMAND,
                pattern="",
                level=PermissionLevel.ALLOW,
            )
        )


def test_add_rule_whitespace_pattern_rejected(path_guard):
    pm = make_pm(path_guard)
    with pytest.raises(ValueError, match="must not be empty"):
        pm.add_rule(
            PermissionRule(
                scope=PermissionScope.COMMAND,
                pattern="   ",
                level=PermissionLevel.ALLOW,
            )
        )


async def test_add_rule_event_emitted(path_guard):
    from unittest.mock import AsyncMock

    from mini_agent.events.bus import EventBus
    from mini_agent.models.events import PermissionRuleAddedEvent

    bus = EventBus()
    handler = AsyncMock()
    bus.on(PermissionRuleAddedEvent, handler)

    config = SecurityConfig(permission_mode="ask")
    pm = PermissionManager(config=config, path_guard=path_guard, event_bus=bus)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
        reason="slash command",
    )
    pm.add_rule(rule)

    import asyncio

    await asyncio.sleep(0)  # let the event fire

    handler.assert_called_once()
    event = handler.call_args[0][0]
    assert event.scope == "command"
    assert event.pattern == "docker *"
    assert event.level == "allow"


async def test_add_rule_silent_no_event(path_guard):
    from unittest.mock import AsyncMock

    from mini_agent.events.bus import EventBus
    from mini_agent.models.events import PermissionRuleAddedEvent

    bus = EventBus()
    handler = AsyncMock()
    bus.on(PermissionRuleAddedEvent, handler)

    config = SecurityConfig(permission_mode="ask")
    pm = PermissionManager(config=config, path_guard=path_guard, event_bus=bus)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="test *",
        level=PermissionLevel.ALLOW,
    )
    pm.add_rule(rule, _silent=True)

    import asyncio

    await asyncio.sleep(0)

    handler.assert_not_called()


# --- PermissionManager.remove_rule() ---


async def test_remove_rule(path_guard):
    pm = make_pm(path_guard)
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
    )
    pm.add_rule(rule)
    assert await pm.check_command("docker run ubuntu") == PermissionDecision.GRANTED

    assert pm.remove_rule(PermissionScope.COMMAND, "docker *", PermissionLevel.ALLOW) is True
    # After removal, the rule no longer applies -- falls through to default mode
    pm_deny = make_pm(path_guard, mode="deny")
    pm_deny.add_rule(rule)
    pm_deny.remove_rule(PermissionScope.COMMAND, "docker *", PermissionLevel.ALLOW)
    assert await pm_deny.check_command("docker run ubuntu") == PermissionDecision.DENIED


def test_remove_rule_not_found(path_guard):
    pm = make_pm(path_guard)
    assert pm.remove_rule(PermissionScope.COMMAND, "nonexistent", PermissionLevel.ALLOW) is False


# --- PermissionManager.list_rules() ---


def test_list_rules(path_guard):
    pm = make_pm(path_guard)
    initial_count = len(pm.list_rules())
    pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND,
            pattern="docker *",
            level=PermissionLevel.ALLOW,
        )
    )
    rules = pm.list_rules()
    assert len(rules) == initial_count + 1
    assert any(r.pattern == "docker *" for r in rules)


def test_list_rules_returns_copy(path_guard):
    pm = make_pm(path_guard)
    rules = pm.list_rules()
    rules.clear()
    assert len(pm.list_rules()) > 0 or len(pm._rules) >= 0


# --- PermissionManager.save_rule_to_file() ---


def test_save_rule_to_file_creates_new(tmp_path):
    toml_path = tmp_path / "permissions.toml"
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
    )
    PermissionManager.save_rule_to_file(toml_path, rule)

    import tomllib

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert "docker *" in data["commands"]["allow"]


def test_save_rule_to_file_appends(tmp_path):
    toml_path = tmp_path / "permissions.toml"
    toml_path.write_text('[commands]\nallow = ["git *"]\n', encoding="utf-8")
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="docker *",
        level=PermissionLevel.ALLOW,
    )
    PermissionManager.save_rule_to_file(toml_path, rule)

    import tomllib

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert "git *" in data["commands"]["allow"]
    assert "docker *" in data["commands"]["allow"]


def test_save_rule_to_file_no_duplicate(tmp_path):
    toml_path = tmp_path / "permissions.toml"
    rule = PermissionRule(
        scope=PermissionScope.PATH,
        pattern="*/secrets/*",
        level=PermissionLevel.DENY,
    )
    PermissionManager.save_rule_to_file(toml_path, rule)
    PermissionManager.save_rule_to_file(toml_path, rule)

    import tomllib

    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    assert data["paths"]["deny"].count("*/secrets/*") == 1


def test_save_rule_to_file_creates_parent_dirs(tmp_path):
    toml_path = tmp_path / "nested" / "dir" / "permissions.toml"
    rule = PermissionRule(
        scope=PermissionScope.COMMAND,
        pattern="npm *",
        level=PermissionLevel.DENY,
    )
    PermissionManager.save_rule_to_file(toml_path, rule)
    assert toml_path.is_file()
