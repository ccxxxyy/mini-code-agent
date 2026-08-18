"""Verify DEFAULT_AGENT_TYPE fallback with a real LLM.
用真实 LLM 验证未指定类型的 SubAgent 回退到 DEFAULT_AGENT_TYPE（worker）。

Phases:
  Phase 1: untyped spawn -- prompt is the worker template, config iteration
           budget preserved (not the type's 50), full toolset available;
           the agent actually completes a write task.
  Phase 2: typed spawn (verify) -- type profile still overrides (control).

Usage:
    uv run python experiments/verify_default_agent_type.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mini_agent.config.loader import ConfigLoader
from mini_agent.core.agent_types import DEFAULT_AGENT_TYPE, get_agent_type
from mini_agent.core.subagent import SubAgentManager
from mini_agent.events.bus import EventBus
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.tools.base import ToolRegistry
from mini_agent.tools.builtin import BashTool, ReadFileTool, WriteFileTool


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = ConfigLoader.load()
    print(f"Model: {config.llm.model}")
    print(f"DEFAULT_AGENT_TYPE = {DEFAULT_AGENT_TYPE!r}")
    print(f"config.max_agent_iterations = {config.max_agent_iterations}")
    print("=" * 60)

    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()

    working_dir = Path(tempfile.mkdtemp(prefix="verify_default_type_"))
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(BashTool())

    mgr = SubAgentManager(
        llm=llm,
        tool_registry=registry,
        config=config,
        event_bus=EventBus(),
        working_dir=working_dir,
        model_name=config.llm.model,
    )

    # == Phase 1: untyped spawn falls back to the worker profile ==
    print("\n== Phase 1: untyped spawn -> worker profile, config budget kept ==")
    agent_id = await mgr.spawn("Create a file named hello.txt containing exactly: hi")
    agent = mgr._active[agent_id].agent

    worker = get_agent_type(DEFAULT_AGENT_TYPE)
    head = worker.system_prompt.split("{", 1)[0]
    prompt = agent._conversation.system_prompt
    assert prompt.startswith(head), prompt[:120]
    print(f"  system prompt = worker template (starts with {head[:40]!r}...)")

    budget = config.max_agent_iterations
    assert f"roughly {budget} think-act rounds" in prompt, prompt
    print(f"  iteration budget in prompt = {budget} (config value, not worker's 50)")

    assert agent._loop._tools.get("write_file") is not None
    print("  full toolset available (write_file present)")

    result = await mgr.wait(agent_id, timeout=120)
    print(f"  agent finished: success={result.success}, tools={result.tool_calls_made}")
    assert result.success, result.error
    out_file = working_dir / "hello.txt"
    assert out_file.is_file(), "hello.txt not created"
    print(f"  hello.txt content: {out_file.read_text(encoding='utf-8')!r}")
    print("[PASS] Phase 1: untyped subagent ran on the default worker profile\n")

    # == Phase 2: control -- explicit type still overrides ==
    print("== Phase 2: explicit verify type still overrides budget/tools ==")
    agent_id2 = await mgr.spawn(
        "Verify that the file hello.txt exists in the working directory.",
        agent_type="verify",
    )
    agent2 = mgr._active[agent_id2].agent
    prompt2 = agent2._conversation.system_prompt
    assert "roughly 20 think-act rounds" in prompt2  # verify type budget
    assert agent2._loop._tools.get("write_file") is None  # read-only 只读
    result2 = await mgr.wait(agent_id2, timeout=120)
    print(f"  verify agent: success={result2.success}")
    print(f"  verdict tail: ...{result2.output.strip()[-80:]!r}")
    assert result2.success and "PASS" in result2.output
    print("[PASS] Phase 2: typed spawn unchanged (control)\n")

    print("=" * 60)
    print("ALL PHASES PASSED")


if __name__ == "__main__":
    asyncio.run(main())
