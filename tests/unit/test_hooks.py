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
            {"event": "post_tool", "tool": "bash"},  # 不支持的 event
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
