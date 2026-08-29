"""Composition-root wiring tests for Application. 组合根装配测试。

Application.__init__ delegates to _setup_*/_wire_* steps; these tests
guard that the assembled object graph stays complete after refactors:
every subsystem exists, ToolContext is fully injected, and agent-loop
callbacks are wired. __init__ 拆分为装配方法后，守护装配产物完整性：
子系统齐全、ToolContext 注入完整、回调接线正确。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "home")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    def _make(mutate=None):
        config = ConfigLoader.load()
        if mutate:
            mutate(config)
        return Application(config)

    return _make


def test_all_subsystems_constructed(make_app):
    app = make_app()
    for attr in (
        "terminal",
        "session",
        "tool_registry",
        "permission_manager",
        "hook_manager",
        "context_manager",
        "session_store",
        "agent_loop",
        "worktree_manager",
        "subagent_manager",
        "mailbox",
        "trace_renderer",
        "teach_renderer",
        "audit_logger",
        "tool_recorder",
        "cost_tracker",
        "mcp_manager",
        "task_store",
        "skill_registry",
        "slash_commands",
        "result_cache",
    ):
        assert getattr(app, attr) is not None, f"missing subsystem: {attr}"


def test_tool_context_fully_injected(make_app):
    app = make_app()
    ctx = app._tool_context
    assert ctx.session is app.session
    assert ctx.event_bus is app.event_bus
    assert ctx.config is app.config
    assert ctx.working_dir == app._working_dir
    assert ctx.subagent_manager is app.subagent_manager
    assert ctx.mailbox is app.mailbox
    assert ctx.mcp_manager is app.mcp_manager
    assert ctx.task_store is app.task_store
    assert ctx.skill_registry is app.skill_registry
    assert ctx.agent_loop_ref is not None
    assert ctx.ask_user_callback is not None


def test_agent_loop_wiring(make_app):
    app = make_app()
    loop = app.agent_loop
    assert loop.confirm_callback is not None
    assert loop.snapshot_store is not None
    assert loop.result_cache is app.result_cache
    assert loop.mailbox is app.mailbox
    assert loop.model_name == app.config.llm.model
    assert loop.on_stream_start is not None
    assert loop.on_stream_delta is not None
    assert loop.on_stream_end is not None
    assert loop.on_thinking_delta is not None
    assert loop.on_tool_start is not None
    assert loop.on_tool_end is not None
    assert loop.on_tool_call_assembling is not None


def test_mailbox_main_registered(make_app):
    app = make_app()
    assert not app.mailbox.has_pending("main")  # registered, empty inbox


def test_system_prompt_has_model_and_working_dir(make_app):
    app = make_app()
    sp = app.session.conversation.system_prompt
    assert app.config.llm.model in sp
    assert str(app._working_dir) in sp
    assert app.session.metadata.project_dir == app._working_dir


def test_plan_mode_ref_roundtrip(make_app):
    """agent_loop_ref exposes plan-mode control routed through the mode
    switch. agent_loop_ref 暴露的计划模式控制经模式切换器往返。"""
    from mini_agent.models.permissions import PermissionMode

    app = make_app()
    ref = app._tool_context.agent_loop_ref
    assert ref.get_plan_mode() is False
    ref.set_plan_mode(True)
    assert app.agent_loop.plan_mode is True
    assert app.permission_manager.mode is PermissionMode.PLAN
    ref.set_plan_mode(False)
    assert app.agent_loop.plan_mode is False
    assert app.permission_manager.mode is PermissionMode.DEFAULT


def test_startup_mode_from_config(make_app):
    from mini_agent.models.permissions import PermissionMode

    def mutate(config):
        config.security.approval_mode = "accept-edits"

    app = make_app(mutate)
    assert app.permission_manager.mode is PermissionMode.ACCEPT_EDITS


def test_invalid_approval_mode_falls_back_to_default(make_app):
    from mini_agent.models.permissions import PermissionMode

    def mutate(config):
        config.security.approval_mode = "no-such-mode"

    app = make_app(mutate)
    assert app.permission_manager.mode is PermissionMode.DEFAULT


def test_enable_plan_mode_backcompat(make_app):
    from mini_agent.models.permissions import PermissionMode

    def mutate(config):
        config.enable_plan_mode = True

    app = make_app(mutate)
    assert app.permission_manager.mode is PermissionMode.PLAN
    assert app.agent_loop.plan_mode is True


def test_only_enabled_tools_registered(make_app):
    app = make_app()
    registered = {t.schema.name for t in app.tool_registry.list_tools()}
    assert registered <= set(app.config.tools.enabled_tools)
    assert "read_file" in registered
    assert "bash" in registered


async def test_memory_injection_honors_recall_threshold(make_app):
    """Non-selective branch injects up to recall_threshold entries
    (regression: a hardcoded [:10] silently truncated when the threshold
    was raised past 10). 非选择性分支按 recall_threshold 注入（回归：
    硬编码 [:10] 曾在阈值调过 10 后静默截断）。"""
    from mini_agent.memory.persistent import MemoryEntry, PersistentMemory
    from mini_agent.models.message import Message, Role
    from mini_agent.tools.hooks import HookContext, HookStage

    def mutate(config):
        config.memory.recall_threshold = 30

    app = make_app(mutate)
    pm = PersistentMemory()
    for i in range(12):
        await pm.add_user_memory(MemoryEntry(content=f"memory-{i}", source="user"))
    app.session.conversation.messages.append(Message(role=Role.USER, content="hi"))

    await app.hook_manager.run(HookContext(stage=HookStage.PRE_LLM))

    sp = app.session.conversation.system_prompt
    assert "--- Relevant memories ---" in sp
    for i in range(12):  # 12 <= threshold(30): ALL injected, not just 10
        assert f"memory-{i}" in sp
