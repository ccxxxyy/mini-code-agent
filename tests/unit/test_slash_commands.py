"""Tests for slash command framework."""

from mini_agent.extensions.slash_commands import SlashCommand, SlashCommandRegistry


async def test_register_and_execute():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return f"echo: {args}"

    reg.register(SlashCommand(name="test", description="test cmd", handler=handler))
    result = await reg.execute("/test hello world")
    assert result == "echo: hello world"


async def test_unknown_command():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return "ok"

    reg.register(SlashCommand(name="known", description="x", handler=handler))
    result = await reg.execute("/unknown")
    assert "Unknown command" in result
    assert "/known" in result


async def test_is_slash_command():
    reg = SlashCommandRegistry()
    assert reg.is_slash_command("/help")
    assert reg.is_slash_command("  /status")
    assert not reg.is_slash_command("hello")
    assert not reg.is_slash_command("")


async def test_list_hides_hidden():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return ""

    reg.register(SlashCommand(name="visible", description="x", handler=handler))
    reg.register(SlashCommand(name="secret", description="x", handler=handler, hidden=True))
    commands = reg.list_commands()
    names = [c.name for c in commands]
    assert "visible" in names
    assert "secret" not in names


async def test_no_args():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return f"args='{args}'"

    reg.register(SlashCommand(name="noarg", description="x", handler=handler))
    result = await reg.execute("/noarg")
    assert result == "args=''"


async def test_not_slash_returns_none():
    reg = SlashCommandRegistry()
    result = await reg.execute("just text")
    assert result is None


async def test_unregister():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return "ok"

    reg.register(SlashCommand(name="temp", description="x", handler=handler))
    assert reg.get("temp") is not None
    reg.unregister("temp")
    assert reg.get("temp") is None
