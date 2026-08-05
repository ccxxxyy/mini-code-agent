"""Tests for Agent Teams orchestration. Agent Teams 编排的测试。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.planner import Planner
from mini_agent.core.subagent import SubAgentManager
from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool

pytestmark = pytest.mark.asyncio


class TeamMockLLM(LLMProvider):
    """First call returns the plan JSON; subsequent calls return worker replies.
    首次调用返回计划 JSON；后续调用返回工作者的回复。"""

    def __init__(self, plan_json: str, worker_reply: str = "subtask done"):
        self._plan_json = plan_json
        self._worker_reply = worker_reply
        self._calls = 0

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        self._calls += 1
        text = self._plan_json if self._calls == 1 else self._worker_reply
        yield StreamChunk(delta=text)
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


def make_team(tmp_path, plan_json: str, members: list[TeamMember]):
    llm = TeamMockLLM(plan_json)
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    manager = SubAgentManager(
        llm=llm,
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    planner = Planner(llm)
    config = TeamConfig(name="test-team", members=members)
    return AgentTeam(config=config, planner=planner, subagent_manager=manager)


async def test_team_full_run(tmp_path):
    plan_json = (
        '[{"description": "Fix backend API", "role": "backend"},'
        ' {"description": "Update frontend UI", "role": "frontend"}]'
    )
    team = make_team(
        tmp_path,
        plan_json,
        [
            TeamMember(name="alice", role="backend"),
            TeamMember(name="bob", role="frontend"),
        ],
    )
    report = await team.start("build the feature")

    assert report.success
    assert len(report.plan.steps) == 2
    assert len(report.results) == 2
    assert all(r.success for r in report.results)
    assert all(s.status == "completed" for s in report.plan.steps)


async def test_team_report_summary(tmp_path):
    plan_json = '[{"description": "Single task", "role": "dev"}]'
    team = make_team(tmp_path, plan_json, [TeamMember(name="x", role="dev")])
    report = await team.start("do it")

    summary = report.summary()
    assert "do it" in summary
    assert "OK" in summary


async def test_member_role_matching(tmp_path):
    plan_json = '[{"description": "Write tests", "role": "test"}]'
    team = make_team(
        tmp_path,
        plan_json,
        [
            TeamMember(name="dev", role="backend"),
            TeamMember(name="qa", role="tester"),
        ],
    )
    member = team._match_member("test")
    assert member is not None
    assert member.name == "qa"


async def test_member_fallback_to_first(tmp_path):
    plan_json = '[{"description": "x", "role": "unknown-role"}]'
    team = make_team(
        tmp_path,
        plan_json,
        [TeamMember(name="default", role="generalist")],
    )
    member = team._match_member("nonexistent")
    assert member is not None
    assert member.name == "default"


async def test_empty_team_no_members(tmp_path):
    plan_json = '[{"description": "x", "role": "dev"}]'
    team = make_team(tmp_path, plan_json, [])
    member = team._match_member("dev")
    assert member is None
    # Team still runs, just without member-specific config 团队仍会运行，只是没有成员专属配置
    report = await team.start("task")
    assert len(report.results) == 1


# --- Read-only enforcement + structure scan 只读强制 + 结构扫描 ---


async def test_writes_files_parsed_and_fallback(tmp_path):
    from mini_agent.core.planner import Planner

    class PlanLLM(LLMProvider):
        def __init__(self, json_text):
            self._t = json_text

        async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(delta=self._t)
            yield StreamChunk(finish_reason="stop")

        def count_tokens(self, text):
            return 0

        @property
        def context_window(self):
            return 128_000

    # Explicit writes_files honored 显式标记被采纳
    p = Planner(
        PlanLLM(
            '[{"description":"a","writes_files":false},{"description":"b","writes_files":true}]'
        )
    )
    plan = await p.decompose("t")
    assert plan.steps[0].writes_files is False
    assert plan.steps[1].writes_files is True

    # No writer marked -> last step becomes writer 无标记时最后一步兜底
    p2 = Planner(PlanLLM('[{"description":"a"},{"description":"b"}]'))
    plan2 = await p2.decompose("t")
    assert plan2.steps[0].writes_files is False
    assert plan2.steps[1].writes_files is True


async def test_non_writer_step_loses_write_tools(tmp_path):
    """Non-writer steps must not receive write_file/edit_file.
    非写文件步骤不得获得写工具。"""
    plan_json = (
        '[{"description": "analyze", "role": "dev", "writes_files": false},'
        ' {"description": "write out", "role": "dev", "depends_on": [0], "writes_files": true}]'
    )
    spawned_tools: list = []

    llm = TeamMockLLM(plan_json)
    registry = ToolRegistry()
    from mini_agent.tools.builtin import WriteFileTool

    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    manager = SubAgentManager(
        llm=llm,
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    original_spawn = manager.spawn

    async def spy_spawn(task, isolation="none", allowed_tools=None):
        spawned_tools.append(allowed_tools)
        return await original_spawn(task, isolation=isolation, allowed_tools=allowed_tools)

    manager.spawn = spy_spawn
    team = AgentTeam(
        config=TeamConfig(name="t", members=[TeamMember(name="w", role="dev")]),
        planner=Planner(llm),
        subagent_manager=manager,
    )
    await team.start("t")

    # Step 0 (non-writer): write tools stripped 第 0 步被剥夺写工具
    assert spawned_tools[0] is not None
    assert "write_file" not in spawned_tools[0]
    assert "read_file" in spawned_tools[0]
    # Step 1 (writer): tools not stripped 第 1 步保留全部工具
    assert spawned_tools[1] is None or "write_file" in spawned_tools[1]


async def test_scan_project_structure(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("x", encoding="utf-8")
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    (tmp_path / ".git").mkdir()

    team = make_team(tmp_path, '[{"description":"x"}]', [])
    scan = team._scan_project_structure()
    assert "src/" in scan
    assert "main.py" in scan
    assert "README.md" in scan
    assert ".git" not in scan


# --- Dependency-aware batching 依赖分批执行 ---


async def test_dependent_steps_run_in_batches(tmp_path):
    plan_json = (
        '[{"description": "produce data", "role": "dev", "depends_on": []},'
        ' {"description": "consume data", "role": "dev", "depends_on": [0]}]'
    )
    team = make_team(tmp_path, plan_json, [TeamMember(name="w", role="dev")])
    report = await team.start("pipeline task")

    assert report.success
    assert len(report.results) == 2
    assert report.plan.steps[1].depends_on == [0]
    # Both completed (batch 2 ran after batch 1) 两步都完成（第二批在第一批后执行）
    assert all(s.status == "completed" for s in report.plan.steps)


async def test_dependency_output_passed_to_dependent(tmp_path):
    plan_json = (
        '[{"description": "step a", "role": "dev", "depends_on": []},'
        ' {"description": "step b", "role": "dev", "depends_on": [0]}]'
    )
    team = make_team(tmp_path, plan_json, [TeamMember(name="w", role="dev")])
    from mini_agent.core.subagent import SubAgentResult

    dep_step = type("S", (), {"depends_on": [0]})()
    ctx = team._build_dep_context(
        dep_step,
        {0: SubAgentResult(agent_id="a", task="t", success=True, output="THE DATA")},
    )
    assert "THE DATA" in ctx
    assert "Step 0" in ctx


async def test_failed_dependency_skips_dependent(tmp_path):
    # Worker replies are normal but we mark step 0 failed via monkeypatching wait_all
    # 通过让第一步熔断失败来验证依赖跳过——用 stopped_early 更直接：
    # 这里直接构造 results_by_index 场景，走 team.start 的跳过分支需要真实失败，
    # 用 planner 输出 depends_on 指向失败步骤简化验证 _sanitize 之外的跳过逻辑。
    from mini_agent.core.planner import Plan, PlanStep

    plan = Plan(
        task="t",
        steps=[
            PlanStep(index=0, description="a"),
            PlanStep(index=1, description="b", depends_on=[0]),
        ],
    )

    class FailFirstPlanner:
        async def decompose(self, task, context=""):
            return plan

    class FailingLLM(LLMProvider):
        async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
            raise ConnectionError("llm down")
            yield  # pragma: no cover

        def count_tokens(self, text: str) -> int:
            return 0

        @property
        def context_window(self) -> int:
            return 128_000

    registry = ToolRegistry()
    manager = SubAgentManager(
        llm=FailingLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    team = AgentTeam(
        config=TeamConfig(name="t", members=[]),
        planner=FailFirstPlanner(),
        subagent_manager=manager,
    )
    report = await team.start("t")
    # Step 0 stopped early -> failed; step 1 skipped due to failed dependency
    # 第 0 步熔断失败；第 1 步因依赖失败被跳过
    assert not report.results[0].success
    assert not report.results[1].success
    assert "Skipped" in (report.results[1].error or "")
