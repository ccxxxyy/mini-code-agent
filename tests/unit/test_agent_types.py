"""Tests for the agent type definition system (P48).
Agent 类型定义系统的测试。"""

import pytest

from mini_agent.core.agent_types import (
    AGENT_TYPES,
    AgentTypeDefinition,
    get_agent_type,
)
from mini_agent.core.subagent import _intersect_tools


def test_get_agent_type_known():
    t = get_agent_type("explore")
    assert t.name == "explore"
    assert t.allowed_tools is not None
    assert "read_file" in t.allowed_tools


def test_get_agent_type_unknown():
    with pytest.raises(ValueError, match="Unknown agent type 'nonexistent'"):
        get_agent_type("nonexistent")


def test_all_builtin_types_exist():
    for name in ("explore", "plan", "worker", "verify"):
        t = get_agent_type(name)
        assert t.name == name
        assert t.max_iterations > 0
        assert "{working_dir}" in t.system_prompt


def test_definitions_are_frozen():
    t = get_agent_type("explore")
    with pytest.raises(AttributeError):
        setattr(t, "name", "hacked")


def test_worker_has_all_tools():
    t = get_agent_type("worker")
    assert t.allowed_tools is None


def test_verify_has_low_iterations():
    t = get_agent_type("verify")
    assert t.max_iterations < get_agent_type("worker").max_iterations


def test_agent_types_dict_complete():
    assert set(AGENT_TYPES.keys()) == {"explore", "plan", "worker", "verify"}
    for name, defn in AGENT_TYPES.items():
        assert isinstance(defn, AgentTypeDefinition)
        assert defn.name == name


def test_intersect_tools_both_none():
    assert _intersect_tools(None, None) is None


def test_intersect_tools_type_none():
    assert _intersect_tools(None, ["read_file", "glob"]) == ["read_file", "glob"]


def test_intersect_tools_caller_none():
    result = _intersect_tools(("read_file", "glob", "grep"), None)
    assert result == ["read_file", "glob", "grep"]


def test_intersect_tools_both_set():
    result = _intersect_tools(("read_file", "glob", "grep", "bash"), ["read_file", "glob"])
    assert set(result) == {"read_file", "glob"}
