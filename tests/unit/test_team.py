"""Tests for Agent Teams orchestration. Agent Teams 编排的测试。"""

from collections.abc import AsyncIterator
from typing import Any

from mini_agent.core.planner import Planner
from mini_agent.core.subagent import SubAgentManager
from mini_agent.core.team import AgentTeam, TeamConfig, TeamMember
from mini_agent.events.bus import EventBus
from mini_agent.llm.base import LLMProvider, StreamChunk
from mini_agent.models.config import AgentConfig
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import ReadFileTool


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
