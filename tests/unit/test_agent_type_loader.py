"""Tests for custom agent type loading from .md files (B3).
自定义 Agent 类型 .md 加载测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mini_agent.core.agent_type_loader import load_agent_types, parse_agent_md
from mini_agent.core.agent_types import AGENT_TYPES, AgentTypeDefinition, get_agent_type

pytestmark = pytest.mark.asyncio

VALID_MD = """\
---
name: reviewer
description: Code review specialist
allowed_tools:
  - read_file
  - glob
  - grep
max_iterations: 25
---
You are a code review agent.
Working directory: {working_dir}
Platform: {platform}
Shell: {shell}
Budget: {iteration_budget} rounds.
"""

MINIMAL_MD = """\
---
name: minimal
---
A minimal agent.
"""


@pytest.fixture(autouse=True)
def _restore_agent_types():
    snapshot = dict(AGENT_TYPES)
    yield
    AGENT_TYPES.clear()
    AGENT_TYPES.update(snapshot)


# --- parse_agent_md ---


def test_parse_valid_full_fields(tmp_path):
    f = tmp_path / "reviewer.md"
    f.write_text(VALID_MD, encoding="utf-8")
    defn = parse_agent_md(f)
    assert defn is not None
    assert defn.name == "reviewer"
    assert defn.description == "Code review specialist"
    assert defn.allowed_tools == ("read_file", "glob", "grep")
    assert defn.max_iterations == 25
    assert "{working_dir}" in defn.system_prompt


def test_parse_minimal_defaults(tmp_path):
    f = tmp_path / "minimal.md"
    f.write_text(MINIMAL_MD, encoding="utf-8")
    defn = parse_agent_md(f)
    assert defn is not None
    assert defn.name == "minimal"
    assert defn.description == ""
    assert defn.allowed_tools is None
    assert defn.max_iterations == 30


def test_parse_missing_name_returns_none(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("---\ndescription: no name\n---\nsome body\n", encoding="utf-8")
    assert parse_agent_md(f) is None


def test_parse_invalid_name_returns_none(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("---\nname: Has Spaces\n---\nsome body\n", encoding="utf-8")
    assert parse_agent_md(f) is None


def test_parse_no_frontmatter_returns_none(tmp_path):
    f = tmp_path / "plain.md"
    f.write_text("just some text\n", encoding="utf-8")
    assert parse_agent_md(f) is None


def test_parse_empty_body_returns_none(tmp_path):
    f = tmp_path / "empty.md"
    f.write_text("---\nname: empty\n---\n", encoding="utf-8")
    assert parse_agent_md(f) is None


def test_parse_unknown_placeholder_returns_none(tmp_path):
    f = tmp_path / "bad.md"
    f.write_text("---\nname: bad\n---\nHello {unknown_var}\n", encoding="utf-8")
    assert parse_agent_md(f) is None


# --- load_agent_types ---


def test_load_registers_types(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "reviewer.md").write_text(VALID_MD, encoding="utf-8")
    (d / "minimal.md").write_text(MINIMAL_MD, encoding="utf-8")
    count = load_agent_types([str(d)])
    assert count == 2
    assert get_agent_type("reviewer").name == "reviewer"
    assert get_agent_type("minimal").name == "minimal"


def test_project_overrides_user(tmp_path):
    user_dir = tmp_path / "user"
    proj_dir = tmp_path / "project"
    user_dir.mkdir()
    proj_dir.mkdir()
    (user_dir / "custom.md").write_text(
        "---\nname: custom\n---\nuser version\n", encoding="utf-8"
    )
    (proj_dir / "custom.md").write_text(
        "---\nname: custom\n---\nproject version\n", encoding="utf-8"
    )
    load_agent_types([str(user_dir), str(proj_dir)])
    assert "project version" in get_agent_type("custom").system_prompt


def test_custom_overrides_builtin(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "explore.md").write_text(
        "---\nname: explore\ndescription: custom explore\n---\nmy custom explore\n",
        encoding="utf-8",
    )
    load_agent_types([str(d)])
    defn = get_agent_type("explore")
    assert defn.description == "custom explore"
    assert "my custom explore" in defn.system_prompt


def test_load_skips_invalid_files(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    (d / "good.md").write_text(MINIMAL_MD, encoding="utf-8")
    (d / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    count = load_agent_types([str(d)])
    assert count == 1


def test_nonexistent_dir_is_harmless(tmp_path):
    count = load_agent_types([str(tmp_path / "does-not-exist")])
    assert count == 0
