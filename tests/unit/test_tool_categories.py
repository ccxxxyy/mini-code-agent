"""Tests for the tool category axis (mode × category matrix) and the
sub-agent permission stack propagation (ChildPermissionManager).
工具类别轴（模式 × 类别矩阵）与子 agent 权限栈传播测试。
"""

from pathlib import Path
from typing import Any

import pytest

from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig, SecurityConfig, ToolConfig
from mini_agent.models.message import ToolCall, ToolResult
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionMode,
    PermissionRule,
    PermissionScope,
    ToolCategory,
)
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import ChildPermissionManager, PermissionManager
from mini_agent.tools.base import Tool, ToolContext, ToolRegistry
from mini_agent.tools.builtin import ALL_BUILTIN_TOOLS

pytestmark = pytest.mark.asyncio


EXPECTED_CATEGORIES = {
    "read_file": ToolCategory.READ,
    "glob": ToolCategory.READ,
    "grep": ToolCategory.READ,
    "tool_search": ToolCategory.READ,
    "task_create": ToolCategory.READ,
    "task_get": ToolCategory.READ,
    "task_list": ToolCategory.READ,
    "task_update": ToolCategory.READ,
    "ask_user": ToolCategory.READ,
    "exit_plan_mode": ToolCategory.READ,
    "load_skill": ToolCategory.READ,
    "send_message": ToolCategory.READ,
    "wait_message": ToolCategory.READ,
    "write_file": ToolCategory.WRITE,
    "edit_file": ToolCategory.WRITE,
    "delete_file": ToolCategory.WRITE,
    "install_skill": ToolCategory.WRITE,
    "bash": ToolCategory.EXECUTE,
    "spawn_agents": ToolCategory.EXECUTE,
    "mcp_call": ToolCategory.EXTERNAL,
}


def test_all_builtin_tools_declare_expected_categories():
    """Snapshot: every builtin declares its category explicitly -- a new
    tool that forgets falls to the conservative EXTERNAL default and this
    test flags it for a conscious decision.
    快照：每个内置工具显式声明类别——新工具漏声明会落到保守的 EXTERNAL
    默认值，此测试强制做一次有意识的归类决定。"""
    seen = {}
    for cls in ALL_BUILTIN_TOOLS:
        tool = cls()
        seen[tool.schema.name] = tool.category
    assert seen == EXPECTED_CATEGORIES


def test_tool_abc_default_category_is_external():
    class Mystery(Tool):
        _name = "mystery"
        _description = "undeclared plugin tool"

        async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
            return ToolResult(call_id="", name="mystery", output="ok")

    assert Mystery().category is ToolCategory.EXTERNAL


# --- category gate in _check_permission (mode × category) ---


class _NoopTool(Tool):
    def __init__(self, name: str, category: ToolCategory) -> None:
        self._name = name
        self._description = "noop"
        self.category = category

    @property
    def schema(self):
        from mini_agent.tools.base import ToolSchema

        return ToolSchema(name=self._name, description="noop", parameters=[])

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return ToolResult(call_id="", name=self._name, output="ok")


def make_loop(tmp_path: Path, mode: PermissionMode) -> AgentLoop:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    pg = PathGuard(tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project)
    pm = PermissionManager(config=SecurityConfig(denied_commands=[]), path_guard=pg)
    pm.mode = mode
    registry = ToolRegistry()
    registry.register(_NoopTool("ext_tool", ToolCategory.EXTERNAL))
    registry.register(_NoopTool("writer_tool", ToolCategory.WRITE))
    registry.register(_NoopTool("reader_tool", ToolCategory.READ))

    class _Ctx:
        working_dir = project
        session = None
        event_bus = EventBus()
        config = AgentConfig()
        file_state = None

    loop = AgentLoop(
        llm=None,  # _check_permission never touches the LLM
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=None,
        permission_manager=pm,
    )
    return loop


async def test_plan_denies_write_category_without_path_arg(tmp_path):
    """install_skill-class tools (WRITE, no file_path) are caught by the
    category gate. install_skill 类工具（WRITE 无路径参数）被类别门拦下。"""
    loop = make_loop(tmp_path, PermissionMode.PLAN)
    tc = ToolCall(id="1", name="writer_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.DENIED
    assert loop._permissions.last_decision_reason == "mode:plan"


async def test_plan_denies_external_category(tmp_path):
    """MCP-class tools (EXTERNAL) are denied in plan: external side effects
    cannot be verified read-only. MCP 类工具 plan 下拒绝。"""
    loop = make_loop(tmp_path, PermissionMode.PLAN)
    tc = ToolCall(id="1", name="ext_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.DENIED
    assert loop._permissions.last_decision_reason == "mode:plan"


async def test_plan_denies_unknown_tool_as_external(tmp_path):
    """Unregistered names fall to EXTERNAL (conservative).
    未注册名字保守视为 EXTERNAL。"""
    loop = make_loop(tmp_path, PermissionMode.PLAN)
    tc = ToolCall(id="1", name="ghost_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.DENIED


async def test_bypass_grants_external_with_reason(tmp_path):
    loop = make_loop(tmp_path, PermissionMode.BYPASS)
    tc = ToolCall(id="1", name="ext_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.GRANTED
    assert loop._permissions.last_decision_reason == "mode:bypass"


async def test_default_external_unchanged(tmp_path):
    loop = make_loop(tmp_path, PermissionMode.DEFAULT)
    tc = ToolCall(id="1", name="ext_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.GRANTED
    assert loop._permissions.last_decision_reason == "unrestricted_tool"


async def test_plan_allows_read_category(tmp_path):
    loop = make_loop(tmp_path, PermissionMode.PLAN)
    tc = ToolCall(id="1", name="reader_tool", arguments={})
    assert await loop._check_permission(tc) == PermissionDecision.GRANTED


# --- ChildPermissionManager ---


@pytest.fixture
def parent_pm(tmp_path: Path) -> PermissionManager:
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    pg = PathGuard(tool_config=ToolConfig(), security_config=SecurityConfig(), project_dir=project)

    async def confirm(prompt: str) -> bool:
        raise AssertionError("parent confirm must never fire from a child view")

    pm = PermissionManager(
        config=SecurityConfig(denied_commands=[]), path_guard=pg, confirm_callback=confirm
    )
    pm.working_dir = project
    return pm


async def test_child_never_prompts_dangerous_denied(parent_pm):
    """Dangerous commands in a child are denied fail-safe, not prompted --
    even though the parent HAS a confirm callback.
    子视图的危险命令安全拒绝而非弹窗——即使父级有确认回调。"""
    child = parent_pm.child_view()
    assert isinstance(child, ChildPermissionManager)
    assert await child.check_command("sudo whoami") == PermissionDecision.DENIED
    assert child.last_decision_reason == "no_ui:default_deny"


async def test_child_shares_deny_rules_live(parent_pm):
    """A /deny added on the parent AFTER the child exists blocks the child.
    子视图创建后父级新增的 deny 规则对子视图实时生效。"""
    child = parent_pm.child_view()
    parent_pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND, pattern="git push*", level=PermissionLevel.DENY
        )
    )
    assert await child.check_command("git push origin main") == PermissionDecision.DENIED


async def test_child_mode_follows_parent_live(parent_pm):
    """/mode on the parent immediately affects running children.
    父级 /mode 切换即时影响运行中的子 agent。"""
    child = parent_pm.child_view()
    assert child.mode is PermissionMode.DEFAULT
    parent_pm.mode = PermissionMode.PLAN
    assert child.mode is PermissionMode.PLAN
    # child writes denied under the propagated plan mode
    target = parent_pm.working_dir / "x.py"
    assert await child.check_path(target, "write") == PermissionDecision.DENIED
    assert child.last_decision_reason == "mode:plan"


async def test_child_mode_setter_writes_parent(parent_pm):
    child = parent_pm.child_view()
    child.mode = PermissionMode.BYPASS
    assert parent_pm.mode is PermissionMode.BYPASS


async def test_child_sensitive_path_denied(parent_pm):
    child = parent_pm.child_view()
    ssh = Path("~/.ssh/id_rsa").expanduser()
    assert await child.check_path(ssh, "read") == PermissionDecision.DENIED


async def test_child_reason_isolated_from_parent(parent_pm):
    """Parallel children must not clobber each other's trace context.
    并行子视图不互相覆盖 trace 上下文。"""
    child_a = parent_pm.child_view()
    child_b = parent_pm.child_view()
    await child_a.check_command("sudo x")
    await child_b.check_command("echo hi")
    assert child_a.last_decision_reason == "no_ui:default_deny"
    assert child_b.last_decision_reason != child_a.last_decision_reason


# --- spawn propagation 派生传播 ---


class MockLLM:
    async def stream(self, messages, tools=None, **kwargs):
        from mini_agent.llm.base import StreamChunk

        yield StreamChunk(delta="Done.")
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


async def test_spawn_passes_child_permission_view(tmp_path, parent_pm):
    """In-process spawns inherit the parent stack as a child view.
    in-process 派生以子视图继承父级权限栈。"""
    from mini_agent.core.subagent import SubAgentManager

    registry = ToolRegistry()
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        permission_manager=parent_pm,
    )
    assert mgr.has_permission_gate is True
    agent_id = await mgr.spawn("say done")
    child_pm = mgr._active[agent_id].agent._loop._permissions
    assert isinstance(child_pm, ChildPermissionManager)
    parent_pm.mode = PermissionMode.PLAN
    assert child_pm.mode is PermissionMode.PLAN
    await mgr.wait_all([agent_id])


async def test_spawn_without_pm_has_no_gate(tmp_path):
    from mini_agent.core.subagent import SubAgentManager

    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    assert mgr.has_permission_gate is False


async def test_spawn_agents_allowed_in_plan_when_gated(tmp_path, parent_pm):
    """With a propagated permission stack, plan mode may spawn research
    agents -- their writes are denied at the permission layer.
    有权限栈传播时 plan 可派研究 agent——其写操作在权限层被拒。"""
    import types

    from mini_agent.core.subagent import SubAgentManager
    from mini_agent.models.session import Session
    from mini_agent.tools.builtin import SpawnAgentsTool

    registry = ToolRegistry()
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        permission_manager=parent_pm,
    )
    parent_pm.mode = PermissionMode.PLAN
    ctx = ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        subagent_manager=mgr,
    )
    ctx.agent_loop_ref = types.SimpleNamespace(
        get_plan_mode=lambda: True, set_plan_mode=lambda v: None
    )
    tool = SpawnAgentsTool()
    result = await tool.execute(ctx, tasks=["research the codebase"])
    assert not result.is_error


# --- dialog tools never eager-execute mid-stream 对话框工具不流式抢跑 ---


def test_dialog_tools_declared():
    """ask_user and exit_plan_mode open dialogs; everything else must not.
    ask_user/exit_plan_mode 开对话框；其余工具不得声明。"""
    dialogs = set()
    for cls in ALL_BUILTIN_TOOLS:
        tool = cls()
        if tool.opens_dialog:
            dialogs.add(tool.schema.name)
    assert dialogs == {"ask_user", "exit_plan_mode"}


def test_tool_abc_default_no_dialog():
    class Plain(Tool):
        _name = "plain"
        _description = "x"

        async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
            return ToolResult(call_id="", name="plain", output="ok")

    assert Plain().opens_dialog is False


# --- headless denial breaker + rule source in reasons 无头熔断 + 规则来源 ---


async def test_no_ui_denial_trips_breaker(tmp_path, parent_pm):
    """A gated child that hits a would-prompt denial must stop hunting
    bypass routes: no_ui:default_deny counts toward the confirm-denial
    breaker (threshold default 1).
    有门子 agent 命中"本该弹窗"的拒绝后必须停止找绕路：no_ui:default_deny
    计入确认拒绝熔断（默认阈值 1）。"""
    child = parent_pm.child_view()
    registry = ToolRegistry()
    for cls in ALL_BUILTIN_TOOLS:
        registry.register(cls())
    loop = AgentLoop(
        llm=None,
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=None,
        permission_manager=child,
    )
    tc = ToolCall(id="1", name="bash", arguments={"command": "sudo whoami"})
    assert await loop._check_permission(tc) == PermissionDecision.DENIED
    assert loop._state.consecutive_confirm_denials == 1
    assert loop._should_continue() is False
    assert loop.stop_reason == "confirm_denied"


async def test_policy_denials_stay_neutral(tmp_path, parent_pm):
    """rule:/mode: denials do NOT count -- they skip and continue.
    策略拒绝不计数——跳过继续。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="ping*", level=PermissionLevel.DENY)
    )
    child = parent_pm.child_view()
    registry = ToolRegistry()
    for cls in ALL_BUILTIN_TOOLS:
        registry.register(cls())
    loop = AgentLoop(
        llm=None,
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(),
        tool_context=None,
        permission_manager=child,
    )
    tc = ToolCall(id="1", name="bash", arguments={"command": "ping -n 2 127.0.0.1"})
    assert await loop._check_permission(tc) == PermissionDecision.DENIED
    assert loop._state.consecutive_confirm_denials == 0
    assert loop._should_continue() is True


async def test_rule_reason_carries_source(parent_pm):
    """Denial reasons name the rule's source so the LLM never hunts config
    files for an in-memory session rule.
    拒绝理由带规则来源——LLM 不再为内存中的会话规则翻配置文件。"""
    parent_pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND,
            pattern="ping*",
            level=PermissionLevel.DENY,
            reason="/deny session rule, not persisted",
        )
    )
    assert await parent_pm.check_command("ping -n 2 x") == PermissionDecision.DENIED
    expected = "rule:command:ping* (/deny session rule, not persisted)"
    assert parent_pm.last_decision_reason == expected


async def test_rule_without_reason_keeps_plain_format(parent_pm):
    parent_pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND, pattern="git push*", level=PermissionLevel.DENY
        )
    )
    assert await parent_pm.check_command("git push") == PermissionDecision.DENIED
    assert parent_pm.last_decision_reason == "rule:command:git push*"


# --- write-then-execute: bare invocation 写后执行的裸调用形态 ---


async def test_bare_written_script_invocation_detected(parent_pm, tmp_path):
    """`run_ping.bat` invoked BARE (no ./ or cmd /c) must be flagged --
    real-run: a sub-agent bypassed a deny rule exactly this way.
    裸文件名调用写过的脚本必须被检出——实测子 agent 正是这样绕过 deny 规则。"""
    project = parent_pm.working_dir
    script = project / "run_ping.bat"
    parent_pm.record_written_file(str(script))
    assert parent_pm.is_executing_written_script("run_ping.bat", project) is True
    # with segment separators too 带分隔符也检出
    assert parent_pm.is_executing_written_script("echo hi & run_ping.bat", project) is True
    # call / start launcher forms call/start 启动形态
    assert parent_pm.is_executing_written_script("call run_ping.bat", project) is True
    assert parent_pm.is_executing_written_script("start run_ping.bat", project) is True


async def test_reading_written_script_not_flagged(parent_pm):
    """Reading a file the agent wrote (verify-own-write flow) must NOT
    trigger the write-then-execute confirm.
    读取自己写的文件（写后自检流）不得触发写后执行确认。"""
    project = parent_pm.working_dir
    parent_pm.record_written_file(str(project / "run_ping.bat"))
    assert parent_pm.is_executing_written_script("type run_ping.bat", project) is False


async def test_bare_written_script_via_child_denied(parent_pm):
    """The full bypass chain through a child view: write the script, then
    bare-invoke it -> dangerous confirm -> no UI -> denied.
    子视图完整绕过链：写脚本→裸调用→危险确认→无 UI→拒绝。"""
    child = parent_pm.child_view()
    project = parent_pm.working_dir
    child.record_written_file(str(project / "x.bat"))
    child.working_dir = project
    assert await child.check_command("x.bat") == PermissionDecision.DENIED
    assert child.last_decision_reason == "no_ui:default_deny"


# --- early-stop report carries denial reason + leftovers 早停报告带原因与遗留 ---


async def test_child_breaker_report_carries_reason_and_leftovers(tmp_path, parent_pm):
    """A breaker-stopped child's result must name the denial reason (so the
    parent does not blindly re-spawn) and list files it created (breaker
    stop leaves no cleanup chance). Real-run: a second identical child was
    spawned and two orphan .bat files were left behind.
    熔断停止的子 agent 结果须写明拒绝原因（父级不再盲目重派）并列出本次
    创建的文件（熔断即停无清理机会）。实测：重派了一模一样的子 agent，
    留下两个孤儿 .bat。"""
    import json as _json

    from mini_agent.core.subagent import SubAgent
    from mini_agent.llm.base import StreamChunk, ToolCallDelta
    from mini_agent.tools.builtin.bash import BashTool
    from mini_agent.tools.builtin.write_file import WriteFileTool

    class ScriptedLLM:
        def __init__(self, scripts):
            self._scripts = scripts
            self._i = 0

        async def stream(self, messages, tools=None, **kwargs):
            script = self._scripts[min(self._i, len(self._scripts) - 1)]
            self._i += 1
            for chunk in script:
                yield chunk

        def count_tokens(self, text: str) -> int:
            return len(text) // 4

        @property
        def context_window(self) -> int:
            return 128_000

    def tc_chunks(cid, name, args):
        return [
            StreamChunk(
                tool_call_deltas=[
                    ToolCallDelta(index=0, id=cid, name=name, arguments_delta=_json.dumps(args))
                ]
            ),
            StreamChunk(finish_reason="tool_calls"),
        ]

    project = parent_pm.working_dir
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(BashTool())
    # a deny rule provides the ROOT cause; the breaker trips later on no_ui
    # deny 规则是根因；熔断由之后的 no_ui 触发
    parent_pm.add_rule(
        PermissionRule(
            scope=PermissionScope.COMMAND,
            pattern="ping*",
            level=PermissionLevel.DENY,
            reason="/deny session rule, not persisted",
        )
    )
    # script: ping (rule deny) -> write junk.bat -> bare-invoke (no UI deny -> breaker)
    llm = ScriptedLLM(
        [
            tc_chunks("c0", "bash", {"command": "ping -n 2 127.0.0.1"}),
            tc_chunks(
                "c1", "write_file", {"file_path": str(project / "junk.bat"), "content": "@echo off"}
            ),
            tc_chunks("c2", "bash", {"command": "junk.bat"}),
            [StreamChunk(delta="done"), StreamChunk(finish_reason="stop")],
        ]
    )
    child_pm = parent_pm.child_view()
    child_pm.working_dir = project
    agent = SubAgent(
        task="run junk",
        llm=llm,
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=project,
        permission_manager=child_pm,
    )
    result = await agent.run()
    assert result.success is False
    # ALL distinct denials, root cause first -- not just the tripping one
    # 全部去重拒绝原因、根因在前——不只是最后一击
    assert "rule:command:ping* (/deny session rule, not persisted)" in (result.error or "")
    assert "no_ui:default_deny" in result.error
    assert result.error.index("rule:command:ping*") < result.error.index("no_ui:default_deny")
    assert "Re-spawning" in result.error
    # rule denials carry the VERBATIM removal command + "every agent" fact
    # rule 拒绝附带可照抄的移除命令与"对所有 agent 生效"事实
    assert '/deny remove command "ping*"' in result.error
    assert "every agent" in result.error
    assert "junk.bat" in result.error  # leftover listed 遗留文件被列出


# --- deny rules match wrapped / chained commands 包装与串联命令的 deny 匹配 ---


async def test_deny_rule_matches_cmd_c_wrapper(parent_pm):
    """`cmd /c "ping x"` must hit a `ping*` deny rule -- real-run: it sailed
    past the rule and only the dangerous-command layer caught it.
    `cmd /c "ping x"` 必须命中 `ping*` deny 规则——实测它绕过了规则，
    仅靠危险命令层兜底。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="ping*", level=PermissionLevel.DENY)
    )
    assert await parent_pm.check_command('cmd /c "ping -n 2 127.0.0.1"') == (
        PermissionDecision.DENIED
    )
    assert parent_pm.last_decision_reason.startswith("rule:command:ping*")


async def test_deny_rule_matches_chained_segment(parent_pm):
    """A denied command hidden behind `&` must still match.
    藏在 `&` 后面的被拒命令也必须命中。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="ping*", level=PermissionLevel.DENY)
    )
    assert await parent_pm.check_command("echo hi & ping 127.0.0.1") == PermissionDecision.DENIED


async def test_deny_rule_ignores_quoted_data(parent_pm):
    """`echo "a & ping x"` is data, not a ping invocation -- no false deny.
    引号内是数据不是 ping 调用——不能误拒。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="ping*", level=PermissionLevel.DENY)
    )
    assert await parent_pm.check_command('echo "a & ping x"') == PermissionDecision.GRANTED


async def test_allow_rule_does_not_unwrap(parent_pm):
    """ALLOW rules stay on the plain command: `cmd /c git status` must not be
    auto-granted by a `git *` allow rule (unwrapping widens deny = fail
    closed; widening allow = fail open).
    allow 规则只看命令本体：`git *` allow 规则不能自动放行
    `cmd /c git status`（扩大 deny 是收紧，扩大 allow 是放松）。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="git *", level=PermissionLevel.ALLOW)
    )
    from mini_agent.models.permissions import PermissionRequest

    decision = await parent_pm._check_rules_only(
        PermissionRequest(scope=PermissionScope.COMMAND, resource="cmd /c git status")
    )
    assert decision is None  # no rule matched; falls through to dangerous-confirm


async def test_nested_wrapper_unwrapped(parent_pm):
    """powershell -Command wrapping is unwrapped too. powershell 包装同样解包。"""
    parent_pm.add_rule(
        PermissionRule(scope=PermissionScope.COMMAND, pattern="ping*", level=PermissionLevel.DENY)
    )
    assert (
        await parent_pm.check_command('powershell -NoProfile -Command "ping 127.0.0.1"')
        == PermissionDecision.DENIED
    )
