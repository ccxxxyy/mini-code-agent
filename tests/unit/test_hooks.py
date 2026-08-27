"""Tests for the hook lifecycle system."""

import pytest

from mini_agent.tools.hooks import (
    HookAction,
    HookContext,
    HookManager,
    HookResult,
    HookStage,
)

pytestmark = pytest.mark.asyncio


async def test_no_hooks_continues():
    mgr = HookManager()
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash"))
    assert result.action == HookAction.CONTINUE


async def test_block_hook():
    mgr = HookManager()

    async def blocker(ctx: HookContext) -> HookResult:
        return HookResult(action=HookAction.BLOCK, reason="not allowed")

    mgr.register(HookStage.PRE_TOOL, blocker)
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash"))
    assert result.action == HookAction.BLOCK
    assert result.reason == "not allowed"


async def test_block_short_circuits():
    calls = []

    async def blocker(ctx):
        calls.append("blocker")
        return HookResult(action=HookAction.BLOCK)

    async def later(ctx):
        calls.append("later")
        return HookResult(action=HookAction.CONTINUE)

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, blocker, priority=10)
    mgr.register(HookStage.PRE_TOOL, later, priority=0)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == ["blocker"]


async def test_modify_hook_updates_args():
    async def modifier(ctx: HookContext) -> HookResult:
        new_args = dict(ctx.tool_args or {})
        new_args["timeout"] = 5
        return HookResult(action=HookAction.MODIFY, modified_args=new_args)

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, modifier)
    ctx = HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "ls"})
    await mgr.run(ctx)
    assert ctx.tool_args == {"command": "ls", "timeout": 5}


async def test_priority_order():
    calls = []

    async def high(ctx):
        calls.append("high")
        return HookResult()

    async def low(ctx):
        calls.append("low")
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, low, priority=1)
    mgr.register(HookStage.PRE_TOOL, high, priority=10)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == ["high", "low"]


async def test_stage_isolation():
    calls = []

    async def pre_hook(ctx):
        calls.append("pre")
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, pre_hook)
    await mgr.run(HookContext(stage=HookStage.POST_TOOL))
    assert calls == []


async def test_unregister():
    calls = []

    async def hook(ctx):
        calls.append(1)
        return HookResult()

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, hook)
    mgr.unregister(HookStage.PRE_TOOL, hook)
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL))
    assert calls == []


# --- Declarative hook rules from [[hooks]] config (7.2) ---


async def test_hook_rule_blocks_matching_tool():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"tool": "bash", "reason": "bash is forbidden"}])
    assert n == 1
    result = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "ls"})
    )
    assert result.action == HookAction.BLOCK
    assert result.reason == "bash is forbidden"
    # Other tools pass 其他工具放行
    result = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="read_file", tool_args={})
    )
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_fnmatch_pattern():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "write_*", "reason": "read-only mode"}])
    for tool in ("write_file", "write_anything"):
        result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name=tool))
        assert result.action == HookAction.BLOCK
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="read_file"))
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_arg_contains():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "tool": "write_file",
                "arg": "file_path",
                "contains": "docs/spec",
                "reason": "spec is locked",
            }
        ],
    )
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "docs/spec.md", "content": "x"},
        )
    )
    assert blocked.action == HookAction.BLOCK
    allowed = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "src/main.py", "content": "docs/spec mention ok"},
        )
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_any_arg_contains():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "bash", "contains": "curl", "reason": "no curl"}])
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "curl http://x"}
        )
    )
    assert blocked.action == HookAction.BLOCK
    allowed = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "ls -la"})
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_default_reason():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "bash"}])
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert result.action == HookAction.BLOCK
    assert "blocked by a project hook rule" in result.reason


async def test_hook_rule_invalid_entries_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(
        mgr,
        [
            "not-a-table",  # 非字典
            {"event": "unknown_event", "tool": "bash"},  # 不支持的 event
            {"tool": "bash", "reject": False},  # 只支持 reject=true
            {"tool": "glob", "reason": "ok"},  # 唯一合法条目
        ],
    )
    assert n == 1
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="glob"))
    assert result.action == HookAction.BLOCK


async def test_hook_rules_config_toml_roundtrip(tmp_path, monkeypatch):
    """[[hooks]] in project config.toml lands in AgentConfig.hooks.
    项目 config.toml 的 [[hooks]] 能进入 AgentConfig.hooks。"""
    import tomllib

    from mini_agent.config.loader import ConfigLoader
    from mini_agent.models.config import AgentConfig

    toml_text = """
[[hooks]]
tool = "bash"
contains = "rm -rf"
reason = "destructive command blocked by policy"
"""
    data = tomllib.loads(toml_text)
    config = AgentConfig()
    ConfigLoader._merge(config, data)
    assert len(config.hooks) == 1
    assert config.hooks[0]["tool"] == "bash"
    assert config.hooks[0]["contains"] == "rm -rf"


async def test_hook_rule_blocks_tool_in_agent_loop(tool_context):
    """End-to-end: a config rule stops the tool inside the ReAct pipeline --
    the file is not written and the LLM sees the rejection reason.
    端到端：配置规则在 ReAct 流水线内拦截工具——文件未写入，LLM 收到拒绝原因。"""

    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.models.message import Conversation, Role
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import WriteFileTool
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import MockLLM, text_response, tool_call_response

    target = tool_context.working_dir / "locked.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr, [{"tool": "write_file", "contains": "locked", "reason": "locked.txt is read-only"}]
    )

    registry = ToolRegistry()
    registry.register(WriteFileTool())
    loop = AgentLoop(
        llm=MockLLM(
            [
                tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
                text_response("Understood, cannot write."),
            ]
        ),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=tool_context,
        hook_manager=mgr,
    )
    from mini_agent.models.message import Message

    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write the file"))
    await loop.run(conv)

    assert not target.exists()  # tool never executed 工具未执行
    tool_msgs = [m for m in conv.messages if m.role == Role.TOOL]
    assert any(
        "Blocked by hook: locked.txt is read-only" in (m.tool_result.output or "")
        for m in tool_msgs
        if m.tool_result
    )


async def test_hook_rule_regex():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr, [{"tool": "bash", "regex": r"rm\s+-rf", "reason": "destructive rm blocked"}]
    )
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "rm   -rf /tmp/x"}
        )
    )
    assert blocked.action == HookAction.BLOCK
    # Substring would false-positive here; regex does not 子串会误伤引号内文本，正则可控
    allowed = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "echo rm-rf-safe"}
        )
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_regex_and_contains_are_anded():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "bash", "contains": "git push", "regex": r"--force|main", "reason": "no force"}],
    )
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="bash",
            tool_args={"command": "git push --force origin dev"},
        )
    )
    assert blocked.action == HookAction.BLOCK
    # contains hits but regex doesn't -> pass 只中 contains 不中 regex -> 放行
    allowed = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "git push origin dev"}
        )
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_invalid_regex_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"tool": "bash", "regex": "([unclosed", "reason": "bad"}])
    assert n == 0  # invalid regex must not crash startup 非法正则不崩启动
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert result.action == HookAction.CONTINUE


# --- HookAction.CONFIRM: config rules + agent loop resolution ---


async def test_confirm_short_circuits():
    calls = []

    async def confirmer(ctx):
        calls.append("confirmer")
        return HookResult(action=HookAction.CONFIRM, reason="are you sure?")

    async def later(ctx):
        calls.append("later")
        return HookResult(action=HookAction.CONTINUE)

    mgr = HookManager()
    mgr.register(HookStage.PRE_TOOL, confirmer, priority=10)
    mgr.register(HookStage.PRE_TOOL, later, priority=0)
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash"))
    assert result.action == HookAction.CONFIRM
    assert result.reason == "are you sure?"
    assert calls == ["confirmer"]


async def test_hook_rule_confirm_action():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(
        mgr,
        [{"tool": "bash", "action": "confirm", "contains": "git push", "reason": "pushes remote"}],
    )
    assert n == 1
    result = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "git push origin"}
        )
    )
    assert result.action == HookAction.CONFIRM
    assert result.reason == "pushes remote"
    # Non-matching command passes 不匹配的命令放行
    result = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "ls"})
    )
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_confirm_default_reason():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "delete_file", "action": "confirm"}])
    result = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="delete_file", tool_args={})
    )
    assert result.action == HookAction.CONFIRM
    assert "requires confirmation" in result.reason


async def test_hook_rule_invalid_action_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"tool": "bash", "action": "modify"}])
    assert n == 0
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert result.action == HookAction.CONTINUE


async def test_would_confirm_peek():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {"tool": "bash", "action": "confirm", "contains": "git push"},
            {"tool": "write_file", "reason": "blocked"},  # block rule: not a confirm 阻止规则不算
        ],
    )
    assert mgr.would_confirm("bash", {"command": "git push origin"})
    assert not mgr.would_confirm("bash", {"command": "ls"})
    assert not mgr.would_confirm("write_file", {"file_path": "x"})


def _make_confirm_loop(tool_context, mgr, responses):
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.events.bus import EventBus
    from mini_agent.models.config import AgentConfig
    from mini_agent.tools.base import ToolRegistry
    from mini_agent.tools.builtin import WriteFileTool
    from tests.unit.test_agent_loop import MockLLM

    registry = ToolRegistry()
    registry.register(WriteFileTool())
    return AgentLoop(
        llm=MockLLM(responses),
        tool_registry=registry,
        event_bus=EventBus(),
        config=AgentConfig(self_verify=False),
        tool_context=tool_context,
        hook_manager=mgr,
    )


async def test_confirm_rule_approved_executes_tool(tool_context):
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "confirmed.txt"
    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "write_file", "action": "confirm", "reason": "writes file"}])
    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("done"),
        ],
    )
    prompts = []

    async def approve(prompt: str) -> bool:
        prompts.append(prompt)
        return True

    loop.confirm_callback = approve
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write it"))
    await loop.run(conv)

    assert target.exists()
    assert len(prompts) == 1
    assert "writes file" in prompts[0]


async def test_confirm_rule_denied_blocks_tool(tool_context):
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "denied.txt"
    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "write_file", "action": "confirm", "reason": "writes file"}])
    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("ok, not writing"),
        ],
    )

    async def deny(prompt: str) -> bool:
        return False

    loop.confirm_callback = deny
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write it"))
    await loop.run(conv)

    assert not target.exists()
    tool_msgs = [m for m in conv.messages if m.role == Role.TOOL]
    assert any(
        "Denied by user: writes file" in (m.tool_result.output or "")
        for m in tool_msgs
        if m.tool_result
    )


async def test_confirm_without_callback_denies(tool_context):
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "no_ui.txt"
    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "write_file", "action": "confirm"}])
    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("ok"),
        ],
    )
    # confirm_callback stays None -> safe deny 无回调 -> 安全拒绝
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write it"))
    await loop.run(conv)
    assert not target.exists()


async def test_confirm_always_grants_session(tool_context):
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    t1 = tool_context.working_dir / "always1.txt"
    t2 = tool_context.working_dir / "always2.txt"
    mgr = HookManager()
    register_hook_rules(mgr, [{"tool": "write_file", "action": "confirm", "reason": "writes file"}])
    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(t1), "content": "1"}),
            tool_call_response("write_file", {"file_path": str(t2), "content": "2"}),
            text_response("done"),
        ],
    )
    prompts = []

    async def always(prompt: str) -> str:
        prompts.append(prompt)
        return "always"

    loop.confirm_callback = always
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write both"))
    await loop.run(conv)

    assert t1.exists() and t2.exists()
    assert len(prompts) == 1  # second call auto-granted 第二次自动放行


# --- Confirm + condition (tech-notes §109, confirm 场景组) ---


async def test_confirm_condition_match_fires(tool_context):
    """Condition matches → confirm dialog fires."""
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "confirm_cond.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "condition": "tool == 'write_file' and args.file_path =~ 'confirm_cond'",
                "action": "confirm",
                "reason": "condition confirm test",
            }
        ],
    )
    prompts = []

    async def approve(prompt: str):
        prompts.append(prompt)
        return True

    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("done"),
        ],
    )
    loop.confirm_callback = approve
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write"))
    await loop.run(conv)

    assert target.exists()
    assert len(prompts) == 1
    assert "condition confirm test" in prompts[0]


async def test_confirm_condition_no_match_passes(tool_context):
    """Condition does not match → no confirm, tool executes directly."""
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "no_match.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "condition": "tool == 'write_file' and args.file_path =~ 'WONT_MATCH'",
                "action": "confirm",
                "reason": "should not fire",
            }
        ],
    )
    prompts = []

    async def approve(prompt: str):
        prompts.append(prompt)
        return True

    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("done"),
        ],
    )
    loop.confirm_callback = approve
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write"))
    await loop.run(conv)

    assert target.exists()
    assert len(prompts) == 0  # no confirm dialog


async def test_confirm_condition_denied_blocks(tool_context):
    """Condition matches + user denies → tool blocked."""
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "denied_cond.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "condition": "tool == 'write_file'",
                "action": "confirm",
                "reason": "deny test",
            }
        ],
    )

    async def deny(prompt: str):
        return False

    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("ok"),
        ],
    )
    loop.confirm_callback = deny
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write"))
    await loop.run(conv)

    assert not target.exists()
    tool_msgs = [m for m in conv.messages if m.role == Role.TOOL]
    assert any("Denied by user" in (m.tool_result.output or "") for m in tool_msgs if m.tool_result)


async def test_confirm_condition_always_grants(tool_context):
    """Condition matches + user says 'always' → second call auto-granted."""
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    t1 = tool_context.working_dir / "always1.txt"
    t2 = tool_context.working_dir / "always2.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "condition": "tool == 'write_file'",
                "action": "confirm",
                "reason": "always test",
            }
        ],
    )
    prompts = []

    async def always(prompt: str):
        prompts.append(prompt)
        return "always"

    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(t1), "content": "1"}),
            tool_call_response("write_file", {"file_path": str(t2), "content": "2"}),
            text_response("done"),
        ],
    )
    loop.confirm_callback = always
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write both"))
    await loop.run(conv)

    assert t1.exists() and t2.exists()
    assert len(prompts) == 1  # second auto-granted


async def test_confirm_condition_without_callback_denies(tool_context):
    """Condition matches but no callback (headless) → safe deny."""
    from mini_agent.models.message import Conversation, Message, Role
    from mini_agent.tools.hooks import register_hook_rules
    from tests.unit.test_agent_loop import text_response, tool_call_response

    target = tool_context.working_dir / "headless.txt"
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "condition": "tool == 'write_file'",
                "action": "confirm",
            }
        ],
    )
    loop = _make_confirm_loop(
        tool_context,
        mgr,
        [
            tool_call_response("write_file", {"file_path": str(target), "content": "hi"}),
            text_response("ok"),
        ],
    )
    # confirm_callback stays None → safe deny
    conv = Conversation()
    conv.append(Message(role=Role.USER, content="write"))
    await loop.run(conv)
    assert not target.exists()


# --- Condition expression matching (tech-notes §109) ---


async def test_hook_rule_condition_matches():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(
        mgr,
        [{"condition": "tool == 'bash' and args.command =~ 'git push'", "reason": "no push"}],
    )
    assert n == 1
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "git push origin"}
        )
    )
    assert blocked.action == HookAction.BLOCK
    allowed = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "git pull"})
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_condition_overrides_fixed_fields():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "tool": "read_file",
                "contains": "should-be-ignored",
                "condition": "tool == 'bash'",
                "reason": "condition wins",
            }
        ],
    )
    blocked = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert blocked.action == HookAction.BLOCK
    allowed = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="read_file", tool_args={})
    )
    assert allowed.action == HookAction.CONTINUE


async def test_hook_rule_invalid_condition_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"condition": "this is invalid", "reason": "bad"}])
    assert n == 0


async def test_hook_rule_condition_or():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"condition": "tool == 'bash' or tool == 'delete_file'", "action": "confirm"}],
    )
    for tool in ("bash", "delete_file"):
        r = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name=tool, tool_args={}))
        assert r.action == HookAction.CONFIRM
    r = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="read_file", tool_args={}))
    assert r.action == HookAction.CONTINUE


async def test_hook_rule_condition_with_args_dot_access():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"condition": "args.file_path =~ '\\.py$'", "tool": "write_file", "reason": "py only"}],
    )
    blocked = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "src/main.py"},
        )
    )
    assert blocked.action == HookAction.BLOCK
    allowed = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "README.md"},
        )
    )
    assert allowed.action == HookAction.CONTINUE


# --- Notify action (tech-notes §109) ---


async def test_hook_rule_notify_fires_callback():
    from mini_agent.tools.hooks import register_hook_rules

    messages: list[str] = []
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "write_file", "action": "notify", "message": "wrote $TOOL_NAME"}],
        notify_callback=messages.append,
    )
    result = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="write_file", tool_args={"file_path": "x.py"}
        )
    )
    assert result.action == HookAction.CONTINUE
    assert len(messages) == 1
    assert "wrote write_file" in messages[0]


async def test_hook_rule_notify_template_expansion():
    from mini_agent.tools.hooks import register_hook_rules

    messages: list[str] = []
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "tool": "write_file",
                "action": "notify",
                "message": "File: $TOOL_ARGS.file_path",
            }
        ],
        notify_callback=messages.append,
    )
    await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "/tmp/test.py"},
        )
    )
    assert messages[0] == "File: /tmp/test.py"


async def test_hook_rule_notify_no_callback_logs(caplog):
    import logging

    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "bash", "action": "notify", "message": "running bash"}],
    )
    with caplog.at_level(logging.INFO, logger="mini_agent.tools.hooks"):
        await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert any("running bash" in r.message for r in caplog.records)


async def test_hook_rule_notify_missing_message_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"tool": "bash", "action": "notify"}])
    assert n == 0


# --- Command action (tech-notes §109) ---


async def test_hook_rule_command_pre_tool_success():
    from mini_agent.tools.hooks import register_hook_rules

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        return (0, "formatted ok")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "write_file", "action": "command", "command": "echo ok"}],
        command_runner=runner,
    )
    result = await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL, tool_name="write_file", tool_args={"file_path": "x.py"}
        )
    )
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_command_pre_tool_reject():
    from mini_agent.tools.hooks import register_hook_rules

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        return (1, "validation failed")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "bash", "action": "command", "command": "validate $TOOL_ARGS.command"}],
        command_runner=runner,
    )
    result = await mgr.run(
        HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={"command": "rm -rf /"})
    )
    assert result.action == HookAction.BLOCK
    assert "validation failed" in result.reason


async def test_hook_rule_command_post_tool_always_continues():
    from mini_agent.tools.hooks import register_hook_rules

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        return (1, "error")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "event": "post_tool",
                "tool": "write_file",
                "action": "command",
                "command": "ruff format $TOOL_ARGS.file_path",
            }
        ],
        command_runner=runner,
    )
    result = await mgr.run(
        HookContext(
            stage=HookStage.POST_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "x.py"},
        )
    )
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_command_template_expansion():
    from mini_agent.tools.hooks import register_hook_rules

    captured: list[str] = []

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        captured.append(cmd)
        return (0, "")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "tool": "write_file",
                "action": "command",
                "command": "ruff format $TOOL_ARGS.file_path",
            }
        ],
        command_runner=runner,
    )
    await mgr.run(
        HookContext(
            stage=HookStage.PRE_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "/src/main.py"},
        )
    )
    assert captured[0] == "ruff format /src/main.py"


async def test_hook_rule_command_stdout_displayed():
    from mini_agent.tools.hooks import register_hook_rules

    displayed: list[str] = []

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        return (0, "syntax OK")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"event": "post_tool", "tool": "write_file", "action": "command", "command": "check"}],
        command_runner=runner,
        notify_callback=displayed.append,
    )
    await mgr.run(
        HookContext(
            stage=HookStage.POST_TOOL,
            tool_name="write_file",
            tool_args={"file_path": "x.py"},
        )
    )
    assert displayed == ["syntax OK"]


async def test_hook_rule_command_empty_stdout_not_displayed():
    from mini_agent.tools.hooks import register_hook_rules

    displayed: list[str] = []

    async def runner(cmd: str, timeout: float) -> tuple[int, str]:
        return (0, "")

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "bash", "action": "command", "command": "silent"}],
        command_runner=runner,
        notify_callback=displayed.append,
    )
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert displayed == []


async def test_hook_rule_command_no_runner_skipped(caplog):
    import logging

    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"tool": "bash", "action": "command", "command": "echo hi"}],
    )
    with caplog.at_level(logging.WARNING, logger="mini_agent.tools.hooks"):
        result = await mgr.run(
            HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={})
        )
    assert result.action == HookAction.CONTINUE
    assert any("no runner" in r.message for r in caplog.records)


async def test_hook_rule_command_timeout():
    from mini_agent.tools.hooks import register_hook_rules

    async def slow_runner(cmd: str, timeout: float) -> tuple[int, str]:
        raise TimeoutError()

    mgr = HookManager()
    register_hook_rules(
        mgr,
        [
            {
                "tool": "bash",
                "action": "command",
                "command": "sleep 999",
                "command_timeout": 1,
            }
        ],
        command_runner=slow_runner,
    )
    result = await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="bash", tool_args={}))
    assert result.action == HookAction.CONTINUE


async def test_hook_rule_command_missing_skipped():
    from mini_agent.tools.hooks import register_hook_rules

    mgr = HookManager()
    n = register_hook_rules(mgr, [{"tool": "bash", "action": "command"}])
    assert n == 0


async def test_hook_rule_post_tool_event_registers_on_post_tool():
    from mini_agent.tools.hooks import register_hook_rules

    messages: list[str] = []
    mgr = HookManager()
    register_hook_rules(
        mgr,
        [{"event": "post_tool", "tool": "write_file", "action": "notify", "message": "done"}],
        notify_callback=messages.append,
    )
    await mgr.run(HookContext(stage=HookStage.PRE_TOOL, tool_name="write_file", tool_args={}))
    assert len(messages) == 0
    await mgr.run(HookContext(stage=HookStage.POST_TOOL, tool_name="write_file", tool_args={}))
    assert len(messages) == 1


# --- expand_template ---


def test_expand_template():
    from mini_agent.tools.hooks import expand_template

    result = expand_template(
        "$TOOL_NAME: $TOOL_ARGS.file_path ($EVENT)",
        tool_name="write_file",
        tool_args={"file_path": "/tmp/x.py", "content": "hi"},
        stage="pre_tool",
    )
    assert result == "write_file: /tmp/x.py (pre_tool)"


def test_expand_template_tool_args_json():
    from mini_agent.tools.hooks import expand_template

    result = expand_template(
        "args=$TOOL_ARGS",
        tool_name="bash",
        tool_args={"command": "ls"},
    )
    assert '"command": "ls"' in result


def test_expand_template_missing_var():
    from mini_agent.tools.hooks import expand_template

    result = expand_template("$UNKNOWN stays", tool_name="bash", tool_args={})
    assert result == "$UNKNOWN stays"


def test_expand_template_result():
    from mini_agent.models.message import ToolResult
    from mini_agent.tools.hooks import expand_template

    tr = ToolResult(call_id="c1", name="t", output="hello world", is_error=False)
    result = expand_template("out=$RESULT err=$RESULT_ERROR", "t", {}, tool_result=tr)
    assert result == "out=hello world err=false"
