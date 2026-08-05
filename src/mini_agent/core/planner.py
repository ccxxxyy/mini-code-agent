"""Plan mode -- structured task decomposition via LLM. 计划模式——通过 LLM 进行结构化任务分解。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from mini_agent.llm.base import LLMProvider

PLANNER_PROMPT = """You are a task planner. Decompose the following task into \
subtasks for parallel execution by independent agents.

Task: {task}

{context_section}

Respond with ONLY a JSON array (no markdown fences, no commentary):
[
  {{"description": "subtask 1", "role": "analyst", "depends_on": [], "writes_files": false}},
  {{"description": "subtask 2", "role": "writer", "depends_on": [0], "writes_files": true}}
]

Rules:
- 2 to {max_steps} subtasks
- PREFER independent subtasks (empty depends_on) -- they run in parallel
- Use depends_on ONLY when a subtask genuinely needs another's output \
(list the 0-based indexes it depends on); dependent subtasks run after \
their dependencies complete
- Each description must be specific enough for another agent to execute \
without extra context
- writes_files: set true ONLY for the subtask(s) that produce the file(s) \
the user explicitly asked for. Analysis/research subtasks get false -- \
their findings go in their final report text, which is automatically \
passed to dependent subtasks. Subtasks with writes_files=false are given \
NO file-writing tools, so never plan for them to save anything
- Base the decomposition on the ACTUAL project structure shown in the \
context above -- do not assume a generic web-app layout
- SIZE LIMIT: each subtask must be completable within ~15 tool calls and \
read AT MOST 5 files. NEVER create subtasks like "read all source files" \
or "analyze the whole codebase" -- scope them to specific named files or \
one directory (e.g. "read the 3 files under src/core/ and summarize their \
roles"). Sampling a few representative files is preferred."""


def _sanitize_deps(raw: object, own_index: int, total: int) -> list[int]:
    """Keep only valid dependency indexes: prior steps, no self/forward refs.
    只保留合法依赖索引：必须指向更早的步骤，禁止自引用和前向引用。"""
    if not isinstance(raw, list):
        return []
    deps = []
    for d in raw:
        if isinstance(d, int) and 0 <= d < total and d != own_index and d < own_index:
            deps.append(d)
    return deps


@dataclass
class PlanStep:
    index: int
    description: str
    role: str = ""
    status: str = "pending"  # pending | in_progress | completed | failed 待处理|进行中|已完成|失败
    result: str = ""
    depends_on: list[int] = field(default_factory=list)
    writes_files: bool = False


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

        plan_steps = [
            PlanStep(
                index=i,
                description=s["description"],
                role=s.get("role", ""),
                depends_on=_sanitize_deps(s.get("depends_on"), i, len(steps)),
                writes_files=bool(s.get("writes_files", False)),
            )
            for i, s in enumerate(steps)
        ]
        # Fallback: if the LLM marked no step as writer, the last step can write
        # (otherwise a deliverable-producing task would end with nothing written)
        # 兜底：LLM 未标记任何写文件步骤时，允许最后一步写文件
        if plan_steps and not any(s.writes_files for s in plan_steps):
            plan_steps[-1].writes_files = True

        return Plan(task=task, steps=plan_steps)

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
