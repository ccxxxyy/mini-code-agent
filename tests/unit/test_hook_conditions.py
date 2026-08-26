"""Tests for the condition expression engine (hook_conditions.py)."""

from mini_agent.tools.hook_conditions import (
    Condition,
    ConditionGroup,
    evaluate_condition,
    parse_condition,
    resolve_field,
)

# --- parse_condition ---


def test_parse_simple_equality():
    group = parse_condition("tool == 'bash'")
    assert group is not None
    assert len(group.conditions) == 1
    c = group.conditions[0]
    assert c.field == "tool"
    assert c.operator == "=="
    assert c.value == "bash"
    assert group.logic == "and"


def test_parse_not_equal():
    group = parse_condition("tool != 'bash'")
    assert group is not None
    assert group.conditions[0].operator == "!="
    assert group.conditions[0].value == "bash"


def test_parse_regex_operator():
    group = parse_condition("args.command =~ 'git push'")
    assert group is not None
    c = group.conditions[0]
    assert c.field == "args.command"
    assert c.operator == "=~"
    assert c.value == "git push"


def test_parse_glob_operator():
    group = parse_condition("tool ~= 'write_*'")
    assert group is not None
    c = group.conditions[0]
    assert c.operator == "~="
    assert c.value == "write_*"


def test_parse_and_combinator():
    group = parse_condition("tool == 'bash' and args.command =~ 'rm'")
    assert group is not None
    assert len(group.conditions) == 2
    assert group.logic == "and"
    assert group.conditions[0].field == "tool"
    assert group.conditions[1].field == "args.command"


def test_parse_or_combinator():
    group = parse_condition("tool == 'bash' or tool == 'delete_file'")
    assert group is not None
    assert len(group.conditions) == 2
    assert group.logic == "or"


def test_parse_mixed_combinators_rejected():
    result = parse_condition("a == 'x' and b == 'y' or c == 'z'")
    assert result is None


def test_parse_invalid_operator():
    result = parse_condition("tool >< 'bash'")
    assert result is None


def test_parse_invalid_expression():
    result = parse_condition("just nonsense")
    assert result is None


def test_parse_empty_string():
    assert parse_condition("") is None
    assert parse_condition("   ") is None


def test_parse_double_quotes():
    group = parse_condition('tool == "bash"')
    assert group is not None
    assert group.conditions[0].value == "bash"


def test_parse_bare_word_value():
    group = parse_condition("tool == bash")
    assert group is not None
    assert group.conditions[0].value == "bash"


def test_parse_dotted_field():
    group = parse_condition("args.file_path == '/tmp/x'")
    assert group is not None
    assert group.conditions[0].field == "args.file_path"
    assert group.conditions[0].value == "/tmp/x"


def test_parse_invalid_regex_value():
    result = parse_condition("args.command =~ '([unclosed'")
    assert result is None


def test_parse_multiple_and():
    group = parse_condition("tool == 'bash' and args.command =~ 'git' and args.command =~ 'push'")
    assert group is not None
    assert len(group.conditions) == 3
    assert group.logic == "and"


# --- evaluate_condition ---


def test_evaluate_equality_match():
    group = ConditionGroup([Condition("tool", "==", "bash")], "and")
    assert evaluate_condition(group, {"tool": "bash", "args": {}})


def test_evaluate_equality_no_match():
    group = ConditionGroup([Condition("tool", "==", "bash")], "and")
    assert not evaluate_condition(group, {"tool": "read_file", "args": {}})


def test_evaluate_not_equal():
    group = ConditionGroup([Condition("tool", "!=", "bash")], "and")
    assert evaluate_condition(group, {"tool": "read_file", "args": {}})
    assert not evaluate_condition(group, {"tool": "bash", "args": {}})


def test_evaluate_regex_match():
    group = ConditionGroup([Condition("args.command", "=~", r"git\s+push")], "and")
    assert evaluate_condition(group, {"tool": "bash", "args": {"command": "git  push origin"}})
    assert not evaluate_condition(group, {"tool": "bash", "args": {"command": "git pull"}})


def test_evaluate_glob_match():
    group = ConditionGroup([Condition("tool", "~=", "write_*")], "and")
    assert evaluate_condition(group, {"tool": "write_file", "args": {}})
    assert not evaluate_condition(group, {"tool": "read_file", "args": {}})


def test_evaluate_and_all_true():
    group = ConditionGroup(
        [Condition("tool", "==", "bash"), Condition("args.command", "=~", "rm")],
        "and",
    )
    assert evaluate_condition(group, {"tool": "bash", "args": {"command": "rm -rf /tmp"}})


def test_evaluate_and_one_false():
    group = ConditionGroup(
        [Condition("tool", "==", "bash"), Condition("args.command", "=~", "rm")],
        "and",
    )
    assert not evaluate_condition(group, {"tool": "bash", "args": {"command": "ls"}})


def test_evaluate_or_one_true():
    group = ConditionGroup(
        [Condition("tool", "==", "bash"), Condition("tool", "==", "delete_file")],
        "or",
    )
    assert evaluate_condition(group, {"tool": "delete_file", "args": {}})


def test_evaluate_or_none_true():
    group = ConditionGroup(
        [Condition("tool", "==", "bash"), Condition("tool", "==", "delete_file")],
        "or",
    )
    assert not evaluate_condition(group, {"tool": "read_file", "args": {}})


# --- resolve_field ---


def test_resolve_field_top_level():
    assert resolve_field("tool", {"tool": "bash", "args": {}}) == "bash"


def test_resolve_field_dotted():
    ctx = {"tool": "bash", "args": {"command": "ls -la"}}
    assert resolve_field("args.command", ctx) == "ls -la"


def test_resolve_field_missing():
    assert resolve_field("nonexistent", {"tool": "bash"}) == ""


def test_resolve_field_deep_missing():
    assert resolve_field("args.nonexistent.deep", {"tool": "bash", "args": {}}) == ""


def test_resolve_field_none_value():
    assert resolve_field("args.key", {"args": {"key": None}}) == ""


# --- Integration: parse + evaluate ---


def test_full_parse_and_evaluate():
    group = parse_condition("tool == 'bash' and args.command =~ 'git push'")
    assert group is not None
    assert evaluate_condition(group, {"tool": "bash", "args": {"command": "git push origin main"}})
    assert not evaluate_condition(group, {"tool": "bash", "args": {"command": "git pull"}})
    assert not evaluate_condition(
        group, {"tool": "read_file", "args": {"command": "git push origin"}}
    )
