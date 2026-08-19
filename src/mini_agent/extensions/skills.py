"""Skill system -- loadable skill packs (prompt + tools + resources).
技能系统——可加载的技能包（prompt + 工具 + 资源）。"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from mini_agent.models.message import Conversation


@dataclass
class Skill:
    """A loadable skill pack: prompt + tools + resources.
    一个可加载的技能包：prompt + 工具 + 资源。"""

    name: str
    description: str = ""
    prompt: str = ""
    trigger_patterns: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    source_path: Path | None = None


class SkillRegistry:
    """Discovers, loads, and manages skill packs from SKILL.md files.
    从 SKILL.md 文件中发现、加载并管理技能包。"""

    def __init__(self, skill_dirs: list[Path] | None = None) -> None:
        self._skills: dict[str, Skill] = {}
        self._active: set[str] = set()
        self._skill_dirs = skill_dirs or []
        # Programmatically registered skills (plugin API) -- survive load_all()
        # 编程式注册的技能（插件 API）——load_all() 后仍保留
        self._external: dict[str, Skill] = {}

    def load_all(self) -> None:
        """Scan skill directories and load all valid skill packs.
        扫描技能目录并加载所有有效的技能包。"""
        self._skills.clear()
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
        self._skills.update(self._external)

    def register(self, skill: Skill) -> None:
        """Programmatically register a skill (plugin API).
        Survives load_all()/reload() -- unlike SKILL.md packs it has no disk
        presence, so it is kept in a separate dict merged after each rescan.
        编程式注册技能（插件 API，P83）。load_all()/reload() 后仍保留——
        与 SKILL.md 技能包不同它没有磁盘存在，因此单独存放并在每次重扫后合并。"""
        self._external[skill.name] = skill
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[Skill]:
        return list(self._skills.values())

    def activate(self, name: str, conversation: Conversation) -> bool:
        """Activate a skill -- inject its prompt into conversation.
        激活一个技能——将其 prompt 注入对话。"""
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
        """Deactivate a skill -- remove its prompt from conversation.
        停用一个技能——从对话中移除其 prompt。"""
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
        """Find skills whose trigger patterns match the user message.
        查找触发模式与用户消息匹配的技能。"""
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

    def reload(self, conversation: Conversation) -> tuple[int, list[str]]:
        """Hot-reload: rescan disk, update active skill prompts (P56).
        热重载：重新扫描磁盘，更新活跃 skill 的 prompt。
        Returns (loaded_count, lost_skills).
        返回 (加载数量, 丢失的 skill 列表)。"""
        previously_active = set(self._active)
        for name in list(self._active):
            self.deactivate(name, conversation)
        self.load_all()
        lost: list[str] = []
        for name in previously_active:
            if not self.activate(name, conversation):
                lost.append(name)
        return len(self._skills), lost

    async def install(self, source: str, target_dir: Path) -> str:
        """Install a skill from a local path or git URL into target_dir (P55).
        从本地路径或 git URL 安装技能到 target_dir。"""
        target_dir.mkdir(parents=True, exist_ok=True)
        src_path = Path(source).expanduser()

        if src_path.is_dir():
            dir_name = src_path.name
            dest = target_dir / dir_name
            if dest.exists():
                raise ValueError(f"Destination already exists: {dest}")
            shutil.copytree(str(src_path), str(dest))
        elif source.startswith("https://") or source.endswith(".git"):
            dir_name = source.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            dest = target_dir / dir_name
            if dest.exists():
                raise ValueError(f"Destination already exists: {dest}")
            proc = await asyncio.create_subprocess_exec(
                "git",
                "clone",
                "--depth",
                "1",
                source,
                str(dest),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                shutil.rmtree(str(dest), ignore_errors=True)
                raise ValueError(f"git clone failed: {stderr.decode(errors='replace').strip()}")
        else:
            raise ValueError(f"Invalid source: {source} (expected a directory path or git URL)")

        skill_file = dest / "SKILL.md"
        if not skill_file.is_file():
            shutil.rmtree(str(dest), ignore_errors=True)
            raise ValueError(f"Invalid skill: no SKILL.md found in {dest.name}")
        skill = self._parse_skill_file(skill_file)
        if skill is None:
            shutil.rmtree(str(dest), ignore_errors=True)
            raise ValueError(f"Invalid SKILL.md in {dest.name}: missing 'name' field")

        self.load_all()
        return skill.name

    def uninstall(self, name: str, target_dir: Path) -> bool:
        """Uninstall a skill by removing its directory from target_dir (P55).
        通过删除 target_dir 中的目录来卸载技能。"""
        if not target_dir.is_dir():
            return False
        for child in target_dir.iterdir():
            if not child.is_dir():
                continue
            skill_file = child / "SKILL.md"
            if not skill_file.is_file():
                continue
            skill = self._parse_skill_file(skill_file)
            if skill and skill.name == name:
                shutil.rmtree(str(child), ignore_errors=True)
                self._skills.pop(name, None)
                self._active.discard(name)
                return True
        return False

    @staticmethod
    def _parse_skill_file(path: Path) -> Skill | None:
        """Parse a SKILL.md file (YAML front-matter + markdown body).
        解析一个 SKILL.md 文件（YAML front-matter + Markdown 正文）。"""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None

        # Split front-matter (between ---) and body 拆分 front-matter（位于 --- 之间）和正文
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
        if not fm_match:
            return None

        front_matter = fm_match.group(1)
        body = fm_match.group(2).strip()

        # Simple YAML-like parsing (no PyYAML dependency) 简单的类 YAML 解析（不依赖 PyYAML）
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
