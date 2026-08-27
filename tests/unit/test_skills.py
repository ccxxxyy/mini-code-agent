"""Tests for skill system."""

from pathlib import Path

import pytest

from mini_agent.extensions.skills import Skill, SkillRegistry
from mini_agent.models.message import Conversation

pytestmark = pytest.mark.asyncio


def make_skill_dir(tmp_path: Path, name: str, front_matter: str, body: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text(
        f"---\n{front_matter}\n---\n{body}",
        encoding="utf-8",
    )
    return d


def test_parse_skill_file(tmp_path):
    fm = (
        "name: code-review\n"
        "description: Review code\n"
        "triggers:\n"
        '  - "review"\n'
        '  - "code review"\n'
        "tools:\n"
        "  - read_file\n"
        "  - grep"
    )
    make_skill_dir(tmp_path, "review", fm, "You are a reviewer.\n1. Read the diff\n2. Comment")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()

    skill = reg.get("code-review")
    assert skill is not None
    assert skill.name == "code-review"
    assert skill.description == "Review code"
    assert "review" in skill.trigger_patterns
    assert "code review" in skill.trigger_patterns
    assert "read_file" in skill.tools
    assert "grep" in skill.tools
    assert "You are a reviewer" in skill.prompt


def test_load_all_multiple(tmp_path):
    make_skill_dir(tmp_path, "a", "name: skill-a\ndescription: A", "Prompt A")
    make_skill_dir(tmp_path, "b", "name: skill-b\ndescription: B", "Prompt B")

    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert len(reg.list_skills()) == 2


def test_activate_and_deactivate(tmp_path):
    make_skill_dir(tmp_path, "x", "name: x\ndescription: X", "Extra prompt")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()

    conv = Conversation(system_prompt="Base prompt")
    assert reg.activate("x", conv)
    assert reg.is_active("x")
    assert "Extra prompt" in conv.system_prompt

    assert reg.deactivate("x", conv)
    assert not reg.is_active("x")
    assert "Extra prompt" not in conv.system_prompt


def test_activate_nonexistent(tmp_path):
    reg = SkillRegistry(skill_dirs=[tmp_path])
    conv = Conversation()
    assert not reg.activate("nonexistent", conv)


def test_match_triggers(tmp_path):
    make_skill_dir(
        tmp_path,
        "rev",
        'name: review\ndescription: R\ntriggers:\n  - "review"\n  - "code review"',
        "Review prompt",
    )
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()

    matched = reg.match_triggers("please review this code")
    assert len(matched) == 1
    assert matched[0].name == "review"

    matched = reg.match_triggers("just a normal question")
    assert len(matched) == 0


def test_no_match_when_active(tmp_path):
    make_skill_dir(tmp_path, "s", 'name: s\ndescription: S\ntriggers:\n  - "trigger"', "P")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()

    conv = Conversation()
    reg.activate("s", conv)
    matched = reg.match_triggers("trigger this")
    assert len(matched) == 0


def test_invalid_skill_file(tmp_path):
    d = tmp_path / "bad"
    d.mkdir()
    (d / "SKILL.md").write_text("no front matter here", encoding="utf-8")

    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert len(reg.list_skills()) == 0


def test_missing_name_skipped(tmp_path):
    d = tmp_path / "noname"
    d.mkdir()
    (d / "SKILL.md").write_text("---\ndescription: no name field\n---\nbody", encoding="utf-8")

    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert len(reg.list_skills()) == 0


# --- Install / Uninstall ---


def _reg_for(target: Path) -> SkillRegistry:
    return SkillRegistry(skill_dirs=[target])


async def test_install_from_local_path(tmp_path):
    (tmp_path / "source").mkdir()
    src = make_skill_dir(tmp_path / "source", "my-skill", "name: my-skill\ndescription: M", "P")
    target = tmp_path / "installed"
    reg = _reg_for(target)
    name = await reg.install(str(src), target)
    assert name == "my-skill"
    assert (target / "my-skill" / "SKILL.md").is_file()
    assert reg.get("my-skill") is not None


async def test_install_invalid_no_skill_md(tmp_path):
    src = tmp_path / "no-skill"
    src.mkdir()
    (src / "README.md").write_text("not a skill", encoding="utf-8")
    target = tmp_path / "installed"
    with pytest.raises(ValueError, match="no SKILL.md"):
        await _reg_for(target).install(str(src), target)
    assert not (target / "no-skill").exists()


async def test_install_invalid_no_name(tmp_path):
    src = tmp_path / "bad-skill"
    src.mkdir()
    (src / "SKILL.md").write_text("---\ndescription: no name\n---\nbody", encoding="utf-8")
    target = tmp_path / "installed"
    with pytest.raises(ValueError, match="missing 'name'"):
        await _reg_for(target).install(str(src), target)
    assert not (target / "bad-skill").exists()


def test_uninstall_removes_dir(tmp_path):
    d = make_skill_dir(tmp_path, "removeme", "name: removeme\ndescription: R", "P")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert reg.get("removeme") is not None
    assert reg.uninstall("removeme", tmp_path)
    assert not d.exists()
    assert reg.get("removeme") is None


def test_uninstall_not_found(tmp_path):
    reg = SkillRegistry(skill_dirs=[tmp_path])
    assert not reg.uninstall("nonexistent", tmp_path)


# --- Reload ---


def test_reload_picks_up_new_skill(tmp_path):
    make_skill_dir(tmp_path, "old", "name: old\ndescription: O", "Old prompt")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert reg.get("old") is not None
    assert reg.get("new") is None

    make_skill_dir(tmp_path, "new", "name: new\ndescription: N", "New prompt")
    conv = Conversation()
    loaded, lost = reg.reload(conv)
    assert loaded == 2
    assert reg.get("new") is not None
    assert lost == []


def test_reload_removes_deleted_skill(tmp_path):
    d = make_skill_dir(tmp_path, "gone", "name: gone\ndescription: G", "Prompt")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert reg.get("gone") is not None

    import shutil

    shutil.rmtree(str(d))
    conv = Conversation()
    loaded, lost = reg.reload(conv)
    assert reg.get("gone") is None


def test_reload_updates_active_prompt(tmp_path):
    d = make_skill_dir(tmp_path, "edit", "name: edit\ndescription: E", "Old version")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    conv = Conversation(system_prompt="Base")
    reg.activate("edit", conv)
    assert "Old version" in conv.system_prompt

    (d / "SKILL.md").write_text(
        "---\nname: edit\ndescription: E\n---\nNew version", encoding="utf-8"
    )
    loaded, lost = reg.reload(conv)
    assert "New version" in conv.system_prompt
    assert "Old version" not in conv.system_prompt


def test_reload_reports_lost_skills(tmp_path):
    d = make_skill_dir(tmp_path, "temp", "name: temp\ndescription: T", "Temp")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    conv = Conversation(system_prompt="Base")
    reg.activate("temp", conv)

    import shutil

    shutil.rmtree(str(d))
    loaded, lost = reg.reload(conv)
    assert "temp" in lost
    assert not reg.is_active("temp")


def test_load_all_clears_stale(tmp_path):
    d = make_skill_dir(tmp_path, "stale", "name: stale\ndescription: S", "P")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    assert reg.get("stale") is not None

    import shutil

    shutil.rmtree(str(d))
    reg.load_all()
    assert reg.get("stale") is None


def test_programmatic_register_survives_load_all(tmp_path):
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.register(Skill(name="plugin-skill", description="registered from code", prompt="stay"))
    assert reg.get("plugin-skill") is not None

    reg.load_all()
    assert reg.get("plugin-skill") is not None


# --- skill invocation record (recovery attachment) 技能调用记录（恢复附件） ---


def test_activate_records_invocation(tmp_path):
    """activate() appends to the ordered, deduplicated invocation history."""
    make_skill_dir(tmp_path, "a", "name: skill-a\ndescription: A", "Prompt A")
    make_skill_dir(tmp_path, "b", "name: skill-b\ndescription: B", "Prompt B")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    conv = Conversation()

    reg.activate("skill-a", conv)
    reg.activate("skill-b", conv)
    reg.activate("skill-a", conv)  # duplicate -- must not repeat 重复激活不重复记录

    assert reg.invoked_names == ["skill-a", "skill-b"]
    assert reg.active_names == ["skill-a", "skill-b"]


def test_deactivate_keeps_invocation_history(tmp_path):
    """Invocation history is a RECORD -- deactivate must not erase it.
    调用历史是记录——停用不抹除。"""
    make_skill_dir(tmp_path, "a", "name: skill-a\ndescription: A", "Prompt A")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    conv = Conversation()

    reg.activate("skill-a", conv)
    reg.deactivate("skill-a", conv)

    assert reg.invoked_names == ["skill-a"]
    assert reg.active_names == []


def test_restore_state_does_not_touch_prompt(tmp_path):
    """restore_state() restores sets WITHOUT re-injecting prompts -- a
    restored system_prompt already contains the skill prompt markers.
    restore_state 只恢复集合不重注入 prompt——恢复的 system_prompt 已含标记。"""
    make_skill_dir(tmp_path, "a", "name: skill-a\ndescription: A", "Prompt A")
    reg = SkillRegistry(skill_dirs=[tmp_path])
    reg.load_all()
    conv = Conversation()
    conv.system_prompt = "base\n\n--- Skill: skill-a ---\nPrompt A"  # as restored 恢复态

    reg.restore_state(["skill-a"], ["skill-a"])

    assert reg.is_active("skill-a")
    assert reg.invoked_names == ["skill-a"]
    # prompt NOT duplicated -- restore never touches conversation
    assert conv.system_prompt.count("--- Skill: skill-a ---") == 1
