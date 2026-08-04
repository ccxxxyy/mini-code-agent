"""Verification test for multi_step_edit benchmark."""

from routes import handle_profile


def test_handle_profile_with_age():
    result = handle_profile("Alice", "alice@example.com", 25)
    assert result == "Alice <alice@example.com> (age: 25)", f"Got: {result}"
