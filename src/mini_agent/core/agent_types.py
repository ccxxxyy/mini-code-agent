"""Agent type definitions -- differentiated SubAgent configurations.
Agent 类型定义——差异化的 SubAgent 配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentTypeDefinition:
    """Immutable definition of a SubAgent type.
    SubAgent 类型的不可变定义。"""

    name: str
    system_prompt: str
    allowed_tools: tuple[str, ...] | None
    max_iterations: int
    description: str = ""


_READ_ONLY_TOOLS = (
    "read_file",
    "glob",
    "grep",
    "bash",
    "send_message",
    "wait_message",
    "synthetic_output",
)

_EXPLORE_PROMPT = """\
You are a read-only research agent. Your job is to explore the codebase, \
find patterns, locate definitions, and report findings.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

Do NOT create, modify, or delete any files. Only use read-only tools.
Complete the research task, then give a concise report of your findings.
Do not ask questions -- make reasonable decisions autonomously.
Respond in the same language the task is written in.

BUDGET: you have roughly {iteration_budget} think-act rounds before you are \
force-stopped. Prioritize the most important searches first."""

_PLAN_PROMPT = """\
You are a read-only planning agent. Analyze the codebase and produce a \
structured implementation plan. Do NOT modify any files.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

Read relevant code, understand the architecture, then output a clear, \
step-by-step plan with file paths and specific changes needed.
Do not ask questions -- make reasonable decisions autonomously.
Respond in the same language the task is written in.

BUDGET: you have roughly {iteration_budget} think-act rounds before you are \
force-stopped. Prioritize reading the most critical files first."""

_WORKER_PROMPT = """\
You are a focused sub-agent working on a single delegated task.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

Complete the task using the available tools, then give a concise final report.
Do not ask questions -- make reasonable decisions autonomously.
Your final message is your report back to the orchestrator.
Respond in the same language the task is written in.

BUDGET: you have roughly {iteration_budget} think-act rounds before you are \
force-stopped. Plan your tool usage: prioritize the most important \
files/actions first, sample instead of reading everything, and when the \
budget is running low, STOP exploring and write out your findings/deliverables \
immediately. A partial deliverable is far better than being cut off with \
nothing written.

Rules:
- Write ALL output files inside the working directory shown above, using \
relative paths (e.g. "report.md"). NEVER write to /tmp or other absolute \
paths outside the working directory.
- Use platform-appropriate shell commands. On Windows use dir/type/findstr, \
NOT ls/cat/grep.
- If a file or resource the task mentions does not exist, report that fact \
and stop -- do NOT retry in a loop."""

_VERIFY_PROMPT = """\
You are a verification agent. Check whether the described condition holds \
by reading relevant code and running read-only commands.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}

Do NOT create, modify, or delete any files. Only use read-only tools.
After your investigation, you MUST call the synthetic_output tool to return \
your structured verdict before writing any text conclusion. Example:
  synthetic_output(pass=true)  or  synthetic_output(pass=false, failures=[...])
This is mandatory — never skip it. Then end your final message with exactly \
one of:
  PASS — the condition holds
  FAIL — the condition does not hold
Include a brief explanation before the verdict.
Respond in the same language the task is written in.

BUDGET: you have roughly {iteration_budget} think-act rounds before you are \
force-stopped. Be focused and efficient."""

AGENT_TYPES: dict[str, AgentTypeDefinition] = {
    "explore": AgentTypeDefinition(
        name="explore",
        system_prompt=_EXPLORE_PROMPT,
        allowed_tools=_READ_ONLY_TOOLS,
        max_iterations=30,
        description="Read-only research agent",
    ),
    "plan": AgentTypeDefinition(
        name="plan",
        system_prompt=_PLAN_PROMPT,
        allowed_tools=_READ_ONLY_TOOLS,
        max_iterations=30,
        description="Read-only planning agent",
    ),
    "worker": AgentTypeDefinition(
        name="worker",
        system_prompt=_WORKER_PROMPT,
        allowed_tools=None,
        max_iterations=50,
        description="Full-capability worker agent (default)",
    ),
    "verify": AgentTypeDefinition(
        name="verify",
        system_prompt=_VERIFY_PROMPT,
        allowed_tools=_READ_ONLY_TOOLS,
        max_iterations=20,
        description="Read-only verifier (structured verdict via synthetic_output + PASS/FAIL)",
    ),
}

DEFAULT_AGENT_TYPE = "worker"


def get_agent_type(name: str) -> AgentTypeDefinition:
    """Look up an agent type by name. Raises ValueError for unknown types.
    按名称查找 Agent 类型。未知类型抛出 ValueError。"""
    if name not in AGENT_TYPES:
        valid = ", ".join(sorted(AGENT_TYPES))
        raise ValueError(f"Unknown agent type '{name}'. Valid types: {valid}")
    return AGENT_TYPES[name]


def register_agent_type(definition: AgentTypeDefinition) -> None:
    """Register a custom agent type. Overwrites any existing type with the same name.
    注册自定义 Agent 类型。同名时覆盖已有类型。"""
    AGENT_TYPES[definition.name] = definition
