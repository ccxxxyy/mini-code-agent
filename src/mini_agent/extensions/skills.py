"""Skill system -- loadable skill packs (prompt + tools + resources)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mini_agent.models.message import Conversation


@dataclass
class Skill:
    """A loadable skill pack: prompt + tools + resources."""

    name: str
    description: str = ""
    prompt: str = ""
    trigger_patterns: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    source_path: Path | None = None


class SkillRegistry:
    """Discovers, loads, and manages skill packs from SKILL.md files."""

    def __init__(self, skill_dirs: list[Path] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._active: set[str] = set()
        self._skill_dirs = skill_dirs or []

    def load_all(self) -> None:
        """Scan skill directories and load all valid skill packs."""
        for skill_dir in self._skill_dirs:
            skill_dir = Path(skill_dir).expanduser()
            if not skill_dir.is_dir():
                continue
            for child in skill_dir.iterdir():
                if child.is_dir():
                    skill_file = child / "SKILL.md"
                    if skill_file.is_file():
                        skill = self._parse_skill_file(skill_file)
                        if skill:
                            self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def activate(self, name: str, conversation: Conversation) -> bool:
        """Activate a skill -- inject its prompt into conversation."""
        skill = self._skills.get(name)
        if not skill:
            return False
        if name in self._active:
            return True
        self._active.add(name)
        if skill.prompt:
            conversation.system_prompt += f"\n\n--- Skill: {skill.name} ---\n{skill.prompt}"
        return True

    def deactivate(self, name: str, conversation: Conversation) -> bool:
        """Deactivate a skill -- remove its prompt from conversation."""
        skill = self._skills.get(name)
        if not skill or name not in self._active:
            return False
        self._active.discard(name)
        marker = f"\n\n--- Skill: {skill.name} ---\n{skill.prompt}"
        conversation.system_prompt = conversation.system_prompt.replace(marker, "")
        return True

    def is_active(self, name: str) -> bool:
        return name in self._active

    def match_triggers(self, user_message: str) -> list[Skill]:
        """Find skills whose trigger patterns match the user message."""
        matched: list[Skill] = []
        msg_lower = user_message.lower()
        for skill in self._skills.values():
            if skill.name in self._active:
                continue
            for pattern in skill.trigger_patterns:
                if pattern.lower() in msg_lower:
                    matched.append(skill)
                    break
        return matched

    @staticmethod
    def _parse_skill_file(path: Path) -> Skill | None:
        """Parse a SKILL.md file (YAML front-matter + markdown body)."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        # Split front-matter (between ---) and body
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not fm_match:
            return None

        front_matter = fm_match.group(1)
        body = fm_match.group(2).strip()

        # Simple YAML-like parsing (no PyYAML dependency)
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
        if not name or not isinstance(name, str):
            return None

        triggers = meta.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]

        tools = meta.get("tools", [])
        if isinstance(tools, str):
            tools = [tools]

        return Skill(
            name=name,
            description=str(meta.get("description", "")),
            prompt=body,
            trigger_patterns=triggers,
            tools=tools,
            source_path=path.parent,
        )
