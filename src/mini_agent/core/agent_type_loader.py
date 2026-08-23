"""Load custom AgentTypeDefinitions from .md files.
从 .md 文件加载自定义 Agent 类型定义。

Directory scan order: user-level first, project-level second. Later entries
overwrite earlier ones, so priority is: project > user > builtin.
目录扫描顺序：用户级先、项目级后。后者覆盖前者，优先级：项目 > 用户 > 内置。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from mini_agent.core.agent_types import AgentTypeDefinition, register_agent_type

logger = logging.getLogger(__name__)

DEFAULT_MAX_ITERATIONS = 30
_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_VALID_PLACEHOLDERS = {"working_dir", "platform", "shell", "iteration_budget"}


def parse_agent_md(path: Path) -> AgentTypeDefinition | None:
    """Parse a single agent .md file (YAML frontmatter + body).
    解析单个 agent .md 文件。返回 None 表示解析失败（仅 warning 不抛异常）。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("cannot read agent type file %s: %s", path, e)
        return None

    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not fm_match:
        logger.warning("agent type file %s: missing frontmatter delimiters (---)", path)
        return None

    front_matter = fm_match.group(1)
    body = fm_match.group(2).strip()
    if not body:
        logger.warning("agent type file %s: empty body (system prompt required)", path)
        return None

    meta: dict[str, str | list[str]] = {}
    current_key = ""
    current_list: list[str] = []

    for line in front_matter.splitlines():
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        list_match = re.match(r"^\s+-\s+(.+)", line)
        if list_match and current_key:
            current_list.append(list_match.group(1).strip("\"'"))
            meta[current_key] = current_list
            continue
        kv_match = re.match(r"^(\w+)\s*:\s*(.*)", line)
        if kv_match:
            current_key = kv_match.group(1)
            value = kv_match.group(2).strip().strip("\"'")
            if value:
                meta[current_key] = value
                current_list = []
            else:
                current_list = []

    name = meta.get("name", "")
    if not name or not isinstance(name, str) or not _NAME_RE.match(name):
        logger.warning("agent type file %s: invalid or missing 'name' field", path)
        return None

    description = str(meta.get("description", ""))

    raw_tools = meta.get("allowed_tools")
    allowed_tools: tuple[str, ...] | None = None
    if isinstance(raw_tools, list):
        allowed_tools = tuple(raw_tools)
    elif isinstance(raw_tools, str):
        allowed_tools = (raw_tools,)

    try:
        max_iterations = int(meta.get("max_iterations", DEFAULT_MAX_ITERATIONS))
    except (ValueError, TypeError):
        max_iterations = DEFAULT_MAX_ITERATIONS

    try:
        body.format(**{k: "" for k in _VALID_PLACEHOLDERS})
    except KeyError as e:
        logger.warning("agent type file %s: unknown placeholder %s in body", path, e)
        return None

    return AgentTypeDefinition(
        name=name,
        system_prompt=body,
        allowed_tools=allowed_tools,
        max_iterations=max_iterations,
        description=description,
    )


def load_agent_types(agent_dirs: list[str | Path]) -> int:
    """Scan directories for *.md agent definitions and register them.
    扫描目录中的 *.md 定义并注册。返回注册数量。"""
    count = 0
    for raw_dir in agent_dirs:
        dir_path = Path(raw_dir).expanduser()
        if not dir_path.is_dir():
            continue
        for md_file in sorted(dir_path.glob("*.md")):
            defn = parse_agent_md(md_file)
            if defn is not None:
                register_agent_type(defn)
                count += 1
                logger.debug("loaded custom agent type '%s' from %s", defn.name, md_file)
    return count
