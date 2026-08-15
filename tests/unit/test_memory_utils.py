"""Tests for memory._utils -- strip_json_fence."""

from mini_agent.memory._utils import strip_json_fence


def test_plain_json():
    assert strip_json_fence("[1, 2, 3]") == "[1, 2, 3]"


def test_fenced_json():
    text = "```json\n[1, 2, 3]\n```"
    assert strip_json_fence(text) == "[1, 2, 3]"


def test_fenced_no_lang():
    text = '```\n{"a": 1}\n```'
    assert strip_json_fence(text) == '{"a": 1}'


def test_fenced_with_whitespace():
    text = "  ```json\n  [1, 2]\n  ```  "
    assert strip_json_fence(text) == "[1, 2]"


def test_no_newline_after_backticks():
    text = "```[1]```"
    assert strip_json_fence(text) == "[1]"


def test_opening_fence_only():
    text = "```json\n[1, 2, 3]"
    assert strip_json_fence(text) == "[1, 2, 3]"


def test_empty_string():
    assert strip_json_fence("") == ""


def test_no_fence():
    text = '  {"key": "value"}  '
    assert strip_json_fence(text) == '{"key": "value"}'
