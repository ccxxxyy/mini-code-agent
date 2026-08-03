"""Plan mode -- structured task decomposition via LLM. 计划模式——通过 LLM 进行结构化任务分解。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mini_agent.llm.base import LLMProvider

PLANNER_PROMPT = """You are a task planner. Decompose the following task into \
independent, parallelizable subtasks.

Task: {task}

{context_section}

Respond with ONLY a JSON array (no markdown fences, no commentary):
[
  {{"description": "subtask 1 description", "role": "suggested role e.g. backend/frontend/test"}},
  {{"description": "subtask 2 description", "role": "..."}}
]

Rules:
- 2 to {max_steps} subtasks
- Each subtask must be self-contained and independently executable
- Descriptions must be specific enough for another agent to execute without context"""


@dataclass
class PlanStep:
    index: int
    description: str
    role: str = ""
    status: str = "pending"  # pending | in_progress | completed | failed 待处理|进行中|已完成|失败
    result: str = ""


@dataclass
class Plan:
    task: str
    steps: list[PlanStep] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all(s.status in ("completed", "failed") for s in self.steps)


class Planner:
    """Decomposes tasks into structured plans using the LLM. 使用 LLM 将任务分解为结构化计划。"""

    def __init__(self, llm: LLMProvider, max_steps: int = 5) -> None:
        self._llm = llm
        self._max_steps = max_steps

    async def decompose(self, task: str, context: str = "") -> Plan:
        """Ask the LLM to break a task into subtasks. 请求 LLM 将任务拆分为子任务。"""
        context_section = f"Context:\n{context}" if context else ""
        prompt = PLANNER_PROMPT.format(
            task=task, context_section=context_section, max_steps=self._max_steps
        )

        messages = [{"role": "user", "content": prompt}]
        chunks = []
        async for chunk in self._llm.stream(messages):
            chunks.append(chunk)

        text = "".join(c.delta for c in chunks if c.delta)
        steps = self._parse_steps(text)

        return Plan(
            task=task,
            steps=[
                PlanStep(index=i, description=s["description"], role=s.get("role", ""))
                for i, s in enumerate(steps)
            ],
        )

    def _parse_steps(self, text: str) -> list[dict]:
        """Extract the JSON array from LLM output (tolerates markdown fences).
        从 LLM 输出中提取 JSON 数组（容忍 markdown 代码围栏）。
        """
        # Strip markdown code fences if present 若存在 markdown 代码围栏则先剥离
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1)

        # Find the first JSON array in the text 在文本中查找第一个 JSON 数组
        array_match = re.search(r"\[.*\]", text, re.DOTALL)
        if not array_match:
            return [{"description": text.strip() or "Execute the task", "role": ""}]

        try:
            parsed = json.loads(array_match.group())
        except json.JSONDecodeError:
            return [{"description": text.strip()[:200], "role": ""}]

        steps = []
        for item in parsed[: self._max_steps]:
            if isinstance(item, dict) and item.get("description"):
                steps.append(item)
            elif isinstance(item, str):
                steps.append({"description": item, "role": ""})
        return steps or [{"description": "Execute the task", "role": ""}]
