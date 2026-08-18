"""Verify tool-level permission gate + universal check entry with a real LLM.
用真实 LLM 验证工具级权限门（PermissionScope.TOOL）与通用检查入口 check()。

Phases:
  Phase 1: TOOL deny rule -- real LLM tries bash, gate blocks it outright
           (PermissionCheckEvent scope=tool, decision=denied).
  Phase 2a: Control -- dangerous command with NO tool rule pops a confirm.
  Phase 2b: TOOL allow rule -- same dangerous command runs with zero prompts
           (wholesale trust skips resource checks).
  Phase 3: check() universal entry -- one call evaluates COMMAND / PATH /
           TOOL requests through the correct scope pipeline (no LLM).
  Phase 4: permissions.toml [tools] section roundtrip (no LLM).

Usage:
    uv run python experiments/verify_tool_permission.py
    uv run python experiments/verify_tool_permission.py --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.agent_loop import AgentLoop
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.models.config import AgentConfig, SecurityConfig, ToolConfig
from mini_agent.models.events import PermissionCheckEvent
from mini_agent.models.message import Conversation, Message, Role
from mini_agent.models.permissions import (
    PermissionDecision,
    PermissionLevel,
    PermissionRequest,
    PermissionRule,
    PermissionScope,
)
from mini_agent.models.session import Session
from mini_agent.security.path_guard import PathGuard
from mini_agent.security.permission import PermissionManager
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin import BashTool, ReadFileTool


def build_loop(llm, working_dir: Path, confirm=None):
    registry = ToolRegistry()
    registry.register(BashTool())
    registry.register(ReadFileTool())

    bus = EventBus()
    path_guard = PathGuard(
        tool_config=ToolConfig(),
        security_config=SecurityConfig(),
        project_dir=working_dir,
    )
    pm = PermissionManager(
        config=SecurityConfig(),
        path_guard=path_guard,
        confirm_callback=confirm,
    )
    ctx = ToolContext(
        working_dir=working_dir,
        session=Session(),
        event_bus=bus,
        config=AgentConfig(),
    )
    loop = AgentLoop(
        llm=llm,
        tool_registry=registry,
        event_bus=bus,
        config=AgentConfig(),
        tool_context=ctx,
        permission_manager=pm,
    )
    return loop, pm, bus


def collect_events(bus: EventBus) -> list[PermissionCheckEvent]:
    events: list[PermissionCheckEvent] = []

    async def on_check(e: PermissionCheckEvent) -> None:
        events.append(e)
        print(
            f"  [event] tool={e.tool_name} scope={e.scope} resource={e.resource!r} "
            f"decision={e.decision} reason={e.reason} rule={e.matched_rule}"
        )

    bus.on(PermissionCheckEvent, on_check)
    return events


async def run_turn(loop: AgentLoop, prompt: str) -> Conversation:
    conv = Conversation(
        system_prompt=(
            "You are a coding agent. Use the available tools exactly as asked. "
            "If a tool call is denied or fails, report the error text and stop; "
            "do not retry more than once."
        )
    )
    conv.append(Message(role=Role.USER, content=prompt))
    await loop.run(conv)
    return conv


def tool_outputs(conv: Conversation) -> list[str]:
    return [m.tool_result.output for m in conv.messages if m.role == Role.TOOL and m.tool_result]


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify tool-level permission gate")
    parser.add_argument("--model", type=str, help="Override model")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = ConfigLoader.load()
    if args.model:
        config.llm.model = args.model
    print(f"Model: {config.llm.model}")
    print("=" * 60)

    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()

    working_dir = Path(tempfile.mkdtemp(prefix="verify_tool_perm_"))

    # == Phase 1: TOOL deny rule blocks bash outright ==
    print("\n== Phase 1: /deny tool bash -- gate blocks a harmless command ==")
    loop, pm, bus = build_loop(llm, working_dir)
    pm.add_rule(
        PermissionRule(scope=PermissionScope.TOOL, pattern="bash", level=PermissionLevel.DENY),
        _silent=True,
    )
    events = collect_events(bus)
    conv = await run_turn(loop, "Use the bash tool to run this command: echo hello")

    denied = [e for e in events if e.scope == "tool" and e.decision == "denied"]
    assert denied, "expected a tool-scope denied PermissionCheckEvent"
    assert denied[0].matched_rule == "deny:bash", denied[0].matched_rule
    outs = tool_outputs(conv)
    assert any("Permission denied" in o for o in outs), outs
    print("[PASS] Phase 1: tool deny rule blocked bash; event scope=tool, rule=deny:bash\n")

    # == Phase 2a: control -- dangerous command with no tool rule asks ==
    print("== Phase 2a: control -- dangerous command pops a confirm (denied) ==")
    asked: list[str] = []

    async def deny_confirm(prompt: str) -> bool:
        asked.append(prompt)
        print(f"  [confirm] {prompt.splitlines()[0]} -> deny")
        return False

    loop2a, _, bus2a = build_loop(llm, working_dir, confirm=deny_confirm)
    collect_events(bus2a)
    conv2a = await run_turn(
        loop2a, 'Run exactly this command with the bash tool: git commit -m "test"'
    )
    assert asked, "dangerous command should have prompted for confirmation"
    assert any("Permission denied" in o for o in tool_outputs(conv2a))
    print(f"[PASS] Phase 2a: confirm prompted {len(asked)}x, denied as scripted\n")

    # == Phase 2b: TOOL allow rule skips resource checks ==
    print("== Phase 2b: /allow tool bash -- same dangerous command, zero prompts ==")
    asked2: list[str] = []

    async def record_confirm(prompt: str) -> bool:
        asked2.append(prompt)
        return False

    loop2b, pm2b, bus2b = build_loop(llm, working_dir, confirm=record_confirm)
    pm2b.add_rule(
        PermissionRule(scope=PermissionScope.TOOL, pattern="bash", level=PermissionLevel.ALLOW),
        _silent=True,
    )
    events2b = collect_events(bus2b)
    conv2b = await run_turn(
        loop2b, 'Run exactly this command with the bash tool: git commit -m "test"'
    )
    granted = [e for e in events2b if e.scope == "tool" and e.decision == "granted"]
    assert granted, "expected a tool-scope granted event"
    assert asked2 == [], f"tool allow rule must not prompt, got {asked2}"
    assert not any("Permission denied" in o for o in tool_outputs(conv2b))
    print("[PASS] Phase 2b: tool allow rule ran a dangerous command without prompting\n")

    # == Phase 3: check() universal entry (no LLM) ==
    print("== Phase 3: check() universal entry dispatches by scope ==")
    loop3, pm3, _ = build_loop(llm, working_dir)

    d1 = await pm3.check(PermissionRequest(scope=PermissionScope.COMMAND, resource="rm -rf ./x"))
    print(f"  COMMAND 'rm -rf ./x' (no UI) -> {d1.value} ({pm3.last_decision_reason})")
    assert d1 == PermissionDecision.DENIED  # dangerous, no UI -> safe deny

    project_file = working_dir / "hello.txt"
    project_file.write_text("hi", encoding="utf-8")
    d2 = await pm3.check(PermissionRequest(scope=PermissionScope.PATH, resource=str(project_file)))
    print(f"  PATH project file -> {d2.value} ({pm3.last_decision_reason})")
    assert d2 == PermissionDecision.GRANTED
    assert pm3.last_decision_reason == "path_guard:project_dir"

    pm3.add_rule(
        PermissionRule(
            scope=PermissionScope.TOOL, pattern="delete_file", level=PermissionLevel.DENY
        ),
        _silent=True,
    )
    d3 = await pm3.check(PermissionRequest(scope=PermissionScope.TOOL, resource="delete_file"))
    print(f"  TOOL 'delete_file' (deny rule) -> {d3.value} ({pm3.last_decision_reason})")
    assert d3 == PermissionDecision.DENIED
    print("[PASS] Phase 3: one entry, three scopes, correct pipelines\n")

    # == Phase 4: permissions.toml [tools] roundtrip ==
    print("== Phase 4: [tools] section save/load roundtrip ==")
    toml_path = working_dir / "permissions.toml"
    PermissionManager.save_rule_to_file(
        toml_path,
        PermissionRule(
            scope=PermissionScope.TOOL, pattern="delete_file", level=PermissionLevel.DENY
        ),
    )
    print(f"  saved: {toml_path.read_text(encoding='utf-8').strip()!r}")
    _, pm4, _ = build_loop(llm, working_dir)
    n = pm4.load_rule_files(user_file=toml_path)
    d4 = await pm4.check_tool("delete_file")
    print(f"  loaded {n} rule(s); check_tool('delete_file') -> {d4}")
    assert n == 1 and d4 == PermissionDecision.DENIED
    print("[PASS] Phase 4: [tools] rules persist and reload\n")

    print("=" * 60)
    print("ALL PHASES PASSED")


if __name__ == "__main__":
    asyncio.run(main())
