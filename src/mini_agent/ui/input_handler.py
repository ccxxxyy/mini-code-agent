"""Input handling with Prompt Toolkit."""

from __future__ import annotations

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings


def create_prompt_session() -> PromptSession:
    """Create a Prompt Toolkit session with multi-line support."""
    bindings = KeyBindings()

    @bindings.add("escape", "enter")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    session: PromptSession = PromptSession(
        history=InMemoryHistory(),
        multiline=False,
        key_bindings=bindings,
    )
    return session
