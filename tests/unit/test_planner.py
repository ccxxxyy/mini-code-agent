"""Tests for the Planner (task decomposition). Planner（任务分解）的测试。"""

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.planner import Planner
from mini_agent.llm.base import LLMProvider, StreamChunk

pytestmark = pytest.mark.asyncio


class ScriptedLLM(LLMProvider):
    def __init__(self, response_text: str):
        self._text = response_text

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta=self._text)
        yield StreamChunk(finish_reason="stop")

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


async def test_decompose_json_array():
    llm = ScriptedLLM(
        '[{"description": "Fix the auth bug", "role": "backend"},'
        ' {"description": "Update the tests", "role": "test"}]'
    )
    planner = Planner(llm)
    plan = await planner.decompose("fix auth and tests")

    assert len(plan.steps) == 2
    assert plan.steps[0].description == "Fix the auth bug"
    assert plan.steps[0].role == "backend"
    assert plan.steps[1].role == "test"
    assert plan.steps[0].index == 0


async def test_decompose_with_markdown_fences():
    llm = ScriptedLLM('```json\n[{"description": "Step one", "role": "dev"}]\n```')
    planner = Planner(llm)
    plan = await planner.decompose("task")

    assert len(plan.steps) == 1
    assert plan.steps[0].description == "Step one"


async def test_decompose_invalid_json_fallback():
    llm = ScriptedLLM("I cannot decompose this task properly")
    planner = Planner(llm)
    plan = await planner.decompose("task")

    # Falls back to a single step 回退为单个步骤
    assert len(plan.steps) == 1


async def test_decompose_respects_max_steps():
    steps = ",".join(f'{{"description": "step {i}", "role": ""}}' for i in range(10))
    llm = ScriptedLLM(f"[{steps}]")
    planner = Planner(llm, max_steps=3)
    plan = await planner.decompose("big task")

    assert len(plan.steps) == 3


async def test_decompose_string_items():
    llm = ScriptedLLM('["do thing A", "do thing B"]')
    planner = Planner(llm)
    plan = await planner.decompose("task")

    assert len(plan.steps) == 2
    assert plan.steps[0].description == "do thing A"


async def test_plan_is_complete():
    llm = ScriptedLLM('[{"description": "x", "role": ""}]')
    planner = Planner(llm)
    plan = await planner.decompose("task")

    assert not plan.is_complete
    plan.steps[0].status = "completed"
    assert plan.is_complete
