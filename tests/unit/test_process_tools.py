"""Tests for B1 process tools: ask_user, exit_plan_mode, task CRUD.
B1 流程工具测试：ask_user、exit_plan_mode、task CRUD。"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest

from mini_agent.core.task_store import TaskStore
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext
from mini_agent.tools.builtin.ask_user import AskUserTool
from mini_agent.tools.builtin.exit_plan_mode import ExitPlanModeTool
from mini_agent.tools.builtin.task_create import TaskCreateTool
from mini_agent.tools.builtin.task_get import TaskGetTool
from mini_agent.tools.builtin.task_list import TaskListTool
from mini_agent.tools.builtin.task_update import TaskUpdateTool

pytestmark = pytest.mark.asyncio


def _ctx(tmp_path: Path, **overrides: Any) -> ToolContext:
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
    )
    ctx.task_store = overrides.get("task_store", TaskStore(tmp_path))
    ctx.agent_loop_ref = overrides.get("agent_loop_ref")
    ctx.ask_user_callback = overrides.get("ask_user_callback")
    return ctx


# --- ask_user ---


async def test_ask_user_with_callback(tmp_path):
    async def mock_ask(q, choices):
        return "option B"

    ctx = _ctx(tmp_path, ask_user_callback=mock_ask)
    tool = AskUserTool()
    result = await tool.execute(ctx, question="Pick one", choices=["A", "B"])
    assert result.output == "option B"
    assert not result.is_error


async def test_ask_user_no_callback_returns_error(tmp_path):
    ctx = _ctx(tmp_path, ask_user_callback=None)
    tool = AskUserTool()
    result = await tool.execute(ctx, question="hello?")
    assert result.is_error
    assert "only available in the main agent" in result.output


async def test_ask_user_free_text(tmp_path):
    async def mock_ask(q, choices):
        assert choices is None
        return "free answer"

    ctx = _ctx(tmp_path, ask_user_callback=mock_ask)
    tool = AskUserTool()
    result = await tool.execute(ctx, question="What do you think?", choices=[])
    assert result.output == "free answer"


# --- exit_plan_mode ---


async def test_exit_plan_mode_success(tmp_path):
    state = {"plan_mode": True}
    ref = types.SimpleNamespace(
        get_plan_mode=lambda: state["plan_mode"],
        set_plan_mode=lambda v: state.__setitem__("plan_mode", v),
    )
    ctx = _ctx(tmp_path, agent_loop_ref=ref)
    tool = ExitPlanModeTool()
    result = await tool.execute(ctx)
    assert not result.is_error
    assert "Plan mode exited" in result.output
    assert state["plan_mode"] is False


async def test_exit_plan_mode_not_in_plan(tmp_path):
    ref = types.SimpleNamespace(
        get_plan_mode=lambda: False,
        set_plan_mode=lambda v: None,
    )
    ctx = _ctx(tmp_path, agent_loop_ref=ref)
    tool = ExitPlanModeTool()
    result = await tool.execute(ctx)
    assert result.is_error
    assert "Not in plan mode" in result.output


async def test_exit_plan_mode_no_ref(tmp_path):
    ctx = _ctx(tmp_path, agent_loop_ref=None)
    tool = ExitPlanModeTool()
    result = await tool.execute(ctx)
    assert result.is_error


# --- task_create ---


async def test_task_create(tmp_path):
    ctx = _ctx(tmp_path)
    tool = TaskCreateTool()
    result = await tool.execute(ctx, description="Build feature X")
    assert not result.is_error
    assert "Created task" in result.output
    tasks = ctx.task_store.load()
    assert len(tasks) == 1
    assert tasks[0].description == "Build feature X"


# --- task_get ---


async def test_task_get(tmp_path):
    ctx = _ctx(tmp_path)
    TaskCreateTool()
    from mini_agent.core.task_store import TaskRecord

    t = TaskRecord(description="Test task")
    ctx.task_store.add(t)

    tool = TaskGetTool()
    result = await tool.execute(ctx, task_id=t.id)
    assert not result.is_error
    assert "Test task" in result.output
    assert t.id in result.output


async def test_task_get_not_found(tmp_path):
    ctx = _ctx(tmp_path)
    tool = TaskGetTool()
    result = await tool.execute(ctx, task_id="nonexistent")
    assert result.is_error


# --- task_list ---


async def test_task_list_empty(tmp_path):
    ctx = _ctx(tmp_path)
    tool = TaskListTool()
    result = await tool.execute(ctx)
    assert "No tasks" in result.output


async def test_task_list_with_tasks(tmp_path):
    ctx = _ctx(tmp_path)
    from mini_agent.core.task_store import TaskRecord

    ctx.task_store.add(TaskRecord(description="Task A"))
    ctx.task_store.add(TaskRecord(description="Task B"))
    tool = TaskListTool()
    result = await tool.execute(ctx)
    assert "Task A" in result.output
    assert "Task B" in result.output


# --- task_update ---


async def test_task_update_status(tmp_path):
    ctx = _ctx(tmp_path)
    from mini_agent.core.task_store import TaskRecord

    t = TaskRecord(description="Do stuff")
    ctx.task_store.add(t)

    tool = TaskUpdateTool()
    result = await tool.execute(ctx, task_id=t.id, status="in_progress")
    assert not result.is_error
    assert "in_progress" in result.output

    updated = ctx.task_store.get(t.id)
    assert updated.status == "in_progress"


async def test_task_update_invalid_status(tmp_path):
    ctx = _ctx(tmp_path)
    from mini_agent.core.task_store import TaskRecord

    t = TaskRecord(description="X")
    ctx.task_store.add(t)

    tool = TaskUpdateTool()
    result = await tool.execute(ctx, task_id=t.id, status="invalid")
    assert result.is_error
    assert "Invalid status" in result.output


async def test_task_update_not_found(tmp_path):
    ctx = _ctx(tmp_path)
    tool = TaskUpdateTool()
    result = await tool.execute(ctx, task_id="nope", status="completed")
    assert result.is_error


# --- load_skill ---


async def test_load_skill_success(tmp_path):
    from mini_agent.extensions.skills import Skill, SkillRegistry

    sr = SkillRegistry()
    sr.register(Skill(name="test-sk", description="A test skill", prompt="Be helpful."))
    ctx = _ctx(tmp_path)
    ctx.skill_registry = sr

    from mini_agent.tools.builtin.load_skill import LoadSkillTool

    tool = LoadSkillTool()
    result = await tool.execute(ctx, name="test-sk")
    assert not result.is_error
    assert "activated" in result.output
    assert sr.is_active("test-sk")


async def test_load_skill_not_found(tmp_path):
    from mini_agent.extensions.skills import SkillRegistry
    from mini_agent.tools.builtin.load_skill import LoadSkillTool

    sr = SkillRegistry()
    ctx = _ctx(tmp_path)
    ctx.skill_registry = sr

    tool = LoadSkillTool()
    result = await tool.execute(ctx, name="nonexistent")
    assert result.is_error
    assert "not found" in result.output.lower()


async def test_load_skill_already_active(tmp_path):
    from mini_agent.extensions.skills import Skill, SkillRegistry
    from mini_agent.tools.builtin.load_skill import LoadSkillTool

    sr = SkillRegistry()
    sr.register(Skill(name="active-sk", description="", prompt="x"))
    sr.activate("active-sk", _ctx(tmp_path).session.conversation)
    ctx = _ctx(tmp_path)
    ctx.skill_registry = sr

    tool = LoadSkillTool()
    result = await tool.execute(ctx, name="active-sk")
    assert not result.is_error
    assert "already active" in result.output


async def test_load_skill_no_registry(tmp_path):
    from mini_agent.tools.builtin.load_skill import LoadSkillTool

    ctx = _ctx(tmp_path)
    ctx.skill_registry = None

    tool = LoadSkillTool()
    result = await tool.execute(ctx, name="x")
    assert result.is_error


# --- install_skill ---


async def test_install_skill_from_dir(tmp_path):
    from mini_agent.extensions.skills import SkillRegistry
    from mini_agent.tools.builtin.install_skill import InstallSkillTool

    skill_src = tmp_path / "my_skill"
    skill_src.mkdir()
    (skill_src / "SKILL.md").write_text(
        "---\nname: installed-sk\ndescription: test\n---\nBe great.", encoding="utf-8"
    )

    sr = SkillRegistry(skill_dirs=[tmp_path / "target"])
    ctx = _ctx(tmp_path)
    ctx.skill_registry = sr

    tool = InstallSkillTool()
    result = await tool.execute(ctx, source=str(skill_src))
    assert not result.is_error
    assert "installed-sk" in result.output


async def test_install_skill_invalid_source(tmp_path):
    from mini_agent.extensions.skills import SkillRegistry
    from mini_agent.tools.builtin.install_skill import InstallSkillTool

    sr = SkillRegistry()
    ctx = _ctx(tmp_path)
    ctx.skill_registry = sr

    tool = InstallSkillTool()
    result = await tool.execute(ctx, source="nonexistent_path_xyz")
    assert result.is_error
