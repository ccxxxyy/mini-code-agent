"""Tests for builtin slash commands (project-assessment §2.2).

Covers commands that previously had zero direct test coverage.
Commands with existing test files (undo/fork/todo/cost/record/replay/
help/status) are NOT duplicated here.
内置斜杠命令测试——补上评估 §2.2 指出的零覆盖缺口。
"""

from __future__ import annotations

import pytest

from mini_agent.models.message import Message, Role

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


async def run_cmd(app, line: str) -> str:
    return await app.slash_commands.execute(line, app)


# ── /clear ──────────────────────────────────────────────────────────


async def test_clear_preserves_system_prompt(app):
    app.session.conversation.append(Message(role=Role.USER, content="hi"))
    app.session.conversation.append(Message(role=Role.ASSISTANT, content="hello"))
    sp = app.session.conversation.system_prompt

    result = await run_cmd(app, "/clear")

    assert "Conversation cleared" in result
    assert len(app.session.conversation.messages) == 0
    assert app.session.conversation.system_prompt == sp


# ── /model ──────────────────────────────────────────────────────────


async def test_model_no_args_shows_current(app):
    result = await run_cmd(app, "/model")
    assert app.config.llm.model in result


async def test_model_switch_raw_name(app):
    result = await run_cmd(app, "/model gpt-4o-test")
    assert "gpt-4o-test" in result
    assert app.config.llm.model == "gpt-4o-test"
    assert app.session.metadata.model == "gpt-4o-test"


# ── /compact ────────────────────────────────────────────────────────


async def test_compact_reports_token_change(app):
    for i in range(5):
        app.session.conversation.append(Message(role=Role.USER, content=f"msg {i}"))
        app.session.conversation.append(Message(role=Role.ASSISTANT, content=f"reply {i}"))

    result = await run_cmd(app, "/compact")
    assert "Compressed" in result
    assert "→" in result


# ── /tools ──────────────────────────────────────────────────────────


async def test_tools_lists_registered(app):
    result = await run_cmd(app, "/tools")
    assert "Registered Tools" in result
    assert "read_file" in result
    assert "bash" in result


# ── /plugins ────────────────────────────────────────────────────────


async def test_plugins_empty(app):
    result = await run_cmd(app, "/plugins")
    assert "No plugins loaded" in result


# ── /trace ──────────────────────────────────────────────────────────


async def test_trace_toggle(app):
    result = await run_cmd(app, "/trace on")
    assert "ON" in result
    assert app.trace_renderer.enabled is True

    result = await run_cmd(app, "/trace off")
    assert "OFF" in result
    assert app.trace_renderer.enabled is False


async def test_trace_no_args_shows_status(app):
    result = await run_cmd(app, "/trace")
    assert "Trace mode" in result


# ── /explain ────────────────────────────────────────────────────────


async def test_explain_toggle(app):
    result = await run_cmd(app, "/explain on")
    assert "ON" in result
    assert app.teach_renderer.enabled is True

    result = await run_cmd(app, "/explain off")
    assert "OFF" in result
    assert app.teach_renderer.enabled is False


# ── /audit ──────────────────────────────────────────────────────────


async def test_audit_toggle(app):
    result = await run_cmd(app, "/audit on")
    assert "ON" in result
    assert app.audit_logger.enabled is True

    result = await run_cmd(app, "/audit off")
    assert "OFF" in result
    assert app.audit_logger.enabled is False


# ── /theme ──────────────────────────────────────────────────────────


async def test_theme_list(app):
    result = await run_cmd(app, "/theme")
    assert "Available themes" in result
    assert "default" in result


async def test_theme_switch(app):
    result = await run_cmd(app, "/theme dark")
    assert "dark" in result
    assert "persisted" in result


async def test_theme_unknown(app):
    result = await run_cmd(app, "/theme nonexistent")
    assert "Unknown theme" in result


# ── /plan ───────────────────────────────────────────────────────────


async def test_plan_on_off(app):
    from mini_agent.models.permissions import PermissionMode

    result = await run_cmd(app, "/plan on")
    assert "ON" in result
    assert app.permission_manager.mode is PermissionMode.PLAN
    assert app.agent_loop.plan_mode is True

    result = await run_cmd(app, "/plan off")
    assert "OFF" in result
    assert app.permission_manager.mode is PermissionMode.DEFAULT
    assert app.agent_loop.plan_mode is False


async def test_plan_no_args_shows_status(app):
    result = await run_cmd(app, "/plan")
    assert "Plan mode" in result


async def test_plan_invalid_arg(app):
    result = await run_cmd(app, "/plan maybe")
    assert "Usage" in result


# ── /mode ───────────────────────────────────────────────────────────


async def test_mode_show_current(app):
    result = await run_cmd(app, "/mode")
    assert "Permission mode" in result
    assert "default" in result


async def test_mode_switch(app):
    from mini_agent.models.permissions import PermissionMode

    result = await run_cmd(app, "/mode accept-edits")
    assert "accept-edits" in result
    assert app.permission_manager.mode is PermissionMode.ACCEPT_EDITS


async def test_mode_alias(app):
    from mini_agent.models.permissions import PermissionMode

    result = await run_cmd(app, "/mode acceptedits")
    assert "accept-edits" in result
    assert app.permission_manager.mode is PermissionMode.ACCEPT_EDITS


async def test_mode_invalid(app):
    result = await run_cmd(app, "/mode turbo")
    assert "Unknown mode" in result


async def test_mode_bypass_shows_warning(app):
    result = await run_cmd(app, "/mode bypass")
    assert "Bypass" in result
    assert "⚠" in result


# ── /allow & /deny ──────────────────────────────────────────────────


async def test_allow_add_and_list(app):
    result = await run_cmd(app, '/allow command "echo *"')
    assert "Added allow rule" in result

    result = await run_cmd(app, "/allow")
    assert "echo" in result


async def test_allow_remove(app):
    await run_cmd(app, '/allow command "ls -la"')
    result = await run_cmd(app, '/allow remove command "ls -la"')
    assert "Removed" in result


async def test_deny_add(app):
    result = await run_cmd(app, '/deny command "rm -rf *"')
    assert "Added deny rule" in result


async def test_allow_no_args_empty(app):
    result = await run_cmd(app, "/allow")
    assert "No allow rules" in result


async def test_allow_invalid_scope(app):
    result = await run_cmd(app, "/allow foobar pattern")
    assert "Unknown scope" in result


async def test_allow_missing_pattern(app):
    result = await run_cmd(app, "/allow command")
    assert "Usage" in result


# ── /quit & /exit ───────────────────────────────────────────────────


async def test_quit_raises_system_exit(app):
    with pytest.raises(SystemExit):
        await run_cmd(app, "/quit")


async def test_exit_raises_system_exit(app):
    with pytest.raises(SystemExit):
        await run_cmd(app, "/exit")


# ── /session ────────────────────────────────────────────────────────


async def test_session_save(app):
    app.session.conversation.append(Message(role=Role.USER, content="test"))
    result = await run_cmd(app, "/session save")
    assert "Session saved" in result


async def test_session_new(app):
    app.session.conversation.append(Message(role=Role.USER, content="old"))
    old_id = app.session.metadata.session_id

    result = await run_cmd(app, "/session new")
    assert "New session started" in result
    assert app.session.metadata.session_id != old_id
    assert len(app.session.conversation.messages) == 0


async def test_session_tag_untag(app):
    result = await run_cmd(app, "/session tag feature-x")
    assert "#feature-x" in result
    assert "feature-x" in app.session.metadata.tags

    result = await run_cmd(app, "/session untag feature-x")
    assert "removed" in result.lower()
    assert "feature-x" not in app.session.metadata.tags


async def test_session_tags(app):
    await run_cmd(app, "/session tag demo")
    result = await run_cmd(app, "/session tags")
    assert "#demo" in result


async def test_session_tags_empty(app):
    result = await run_cmd(app, "/session tags")
    assert "No tags" in result


async def test_session_list_empty(app):
    result = await run_cmd(app, "/session list")
    assert "No saved sessions" in result


async def test_session_list_with_sessions(app):
    app.session.conversation.append(Message(role=Role.USER, content="x"))
    await app.session_store.save(app.session)

    result = await run_cmd(app, "/session list")
    assert "Saved Sessions" in result
    assert app.session.metadata.session_id[:12] in result


async def test_session_delete_not_found(app):
    result = await run_cmd(app, "/session delete nonexistent")
    assert "Not found" in result


async def test_session_usage(app):
    result = await run_cmd(app, "/session")
    assert "Usage" in result


# ── /memory ─────────────────────────────────────────────────────────


async def test_memory_add_and_list(app):
    result = await run_cmd(app, "/memory add remember this test fact")
    assert "Added" in result

    result = await run_cmd(app, "/memory")
    assert "remember this test fact" in result


async def test_memory_delete(app):
    await run_cmd(app, "/memory add deletable memory entry")
    result = await run_cmd(app, "/memory delete deletable")
    assert "Deleted" in result


async def test_memory_empty(app):
    result = await run_cmd(app, "/memory")
    assert "No memories" in result


# ── /skill ──────────────────────────────────────────────────────────


async def test_skill_list_empty(app):
    result = await run_cmd(app, "/skill")
    assert "No skills" in result


# ── /spawn (info subcommands only) ─────────────────────────────────


async def test_spawn_no_args_usage(app):
    result = await run_cmd(app, "/spawn")
    assert "Usage" in result


async def test_spawn_list_empty(app):
    result = await run_cmd(app, "/spawn list")
    assert "No active SubAgents" in result


async def test_spawn_cancel_all_empty(app):
    result = await run_cmd(app, "/spawn cancel")
    assert "cancelled" in result.lower()
