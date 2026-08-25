"""Tests for slash command framework. 斜杠命令框架的测试。"""

import pytest

from mini_agent.extensions.slash_commands import SlashCommand, SlashCommandRegistry

pytestmark = pytest.mark.asyncio


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


def test_names_includes_hidden():
    reg = SlashCommandRegistry()

    async def handler(args, ctx):
        return "ok"

    reg.register(SlashCommand(name="visible", description="x", handler=handler))
    reg.register(SlashCommand(name="secret", description="x", handler=handler, hidden=True))
    assert reg.names() == {"visible", "secret"}


# --- no-arg = show status, don't change state 无参数只显示状态 ---


class _Obj:
    """Minimal attribute bag for mocking app sub-objects."""

    def __init__(self, **kw: object) -> None:
        for k, v in kw.items():
            setattr(self, k, v)


async def test_trace_no_arg_shows_status():
    from mini_agent.extensions.builtin_commands import _make_trace

    app = _Obj(trace_renderer=_Obj(enabled=False))
    handler = _make_trace(app)
    result = await handler("", None)
    assert "OFF" in result
    assert not app.trace_renderer.enabled

    app.trace_renderer.enabled = True
    result = await handler("", None)
    assert "ON" in result
    assert app.trace_renderer.enabled


async def test_explain_no_arg_shows_status():
    from mini_agent.extensions.builtin_commands import _make_explain

    app = _Obj(teach_renderer=_Obj(enabled=True))
    handler = _make_explain(app)
    result = await handler("", None)
    assert "ON" in result
    assert app.teach_renderer.enabled

    app.teach_renderer.enabled = False
    result = await handler("", None)
    assert "OFF" in result
    assert not app.teach_renderer.enabled


async def test_audit_no_arg_shows_status():
    from mini_agent.extensions.builtin_commands import _make_audit

    app = _Obj(
        audit_logger=_Obj(
            enabled=False,
            set_enabled=lambda v: None,
            log_path="/tmp/audit.jsonl",
            entry_count=42,
        )
    )
    handler = _make_audit(app)
    result = await handler("", None)
    assert "OFF" in result
    assert not app.audit_logger.enabled


async def test_plan_no_arg_shows_status():
    from mini_agent.extensions.builtin_commands import _make_plan
    from mini_agent.models.permissions import PermissionMode

    app = _Obj(permission_manager=_Obj(mode=PermissionMode.DEFAULT))
    handler = _make_plan(app)
    result = await handler("", None)
    assert "OFF" in result

    app.permission_manager.mode = PermissionMode.PLAN
    result = await handler("", None)
    assert "ON" in result


# --- /session list pagination 会话列表分页 ---


async def _session_list_app(tmp_path, count: int, tag: str = ""):
    """Create an app bag with a real store holding *count* sessions.
    构造带真实 store 与 count 个会话的 app 替身。"""
    from mini_agent.memory.session_store import SessionStore
    from mini_agent.models.session import Session

    store = SessionStore(session_dir=str(tmp_path))
    for _ in range(count):
        s = Session()
        s.metadata.closed_cleanly = True
        if tag:
            s.metadata.tags.append(tag)
        await store.save(s)
    return _Obj(session_store=store, session=Session())


async def test_session_list_truncates_at_limit(tmp_path):
    from mini_agent.extensions.builtin_commands import _SESSION_LIST_LIMIT, _make_session

    app = await _session_list_app(tmp_path, count=25)
    result = await _make_session(app)("list", None)

    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == _SESSION_LIST_LIMIT
    assert "25" in result  # footer shows total 尾行显示总数
    assert "--all" in result


async def test_session_list_all_shows_everything(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = await _session_list_app(tmp_path, count=25)
    result = await _make_session(app)("list --all", None)

    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == 25
    assert "--all` 查看全部" not in result  # no footer 无尾行提示


async def test_session_list_no_footer_under_limit(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = await _session_list_app(tmp_path, count=3)
    result = await _make_session(app)("list", None)

    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == 3
    assert "--all" not in result


async def test_session_list_tag_filter_combines_with_truncation(tmp_path):
    from mini_agent.extensions.builtin_commands import _SESSION_LIST_LIMIT, _make_session

    app = await _session_list_app(tmp_path, count=25, tag="work")
    handler = _make_session(app)

    result = await handler("list --tag work", None)
    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == _SESSION_LIST_LIMIT  # filtered then truncated 过滤后仍截断

    result_all = await handler("list --tag work --all", None)
    rows_all = [ln for ln in result_all.split("\n") if "model=" in ln]
    assert len(rows_all) == 25  # --all combines with --tag 组合生效

    result_none = await handler("list --tag nosuch", None)
    assert "No sessions with tag" in result_none


async def test_session_list_page_2(tmp_path):
    from mini_agent.extensions.builtin_commands import _SESSION_LIST_LIMIT, _make_session

    app = await _session_list_app(tmp_path, count=25)
    result = await _make_session(app)("list --page 2", None)

    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == 25 - _SESSION_LIST_LIMIT  # remaining 5 剩余 5 条
    assert "2/2" in result  # page indicator 页码指示
    assert "--page 3" not in result  # last page: no next hint 末页无下一页提示


async def test_session_list_page_out_of_range(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = await _session_list_app(tmp_path, count=25)
    result = await _make_session(app)("list --page 99", None)
    assert "out of range" in result
    assert "2" in result  # total pages shown 显示总页数


async def test_session_list_all_wins_over_page(tmp_path):
    from mini_agent.extensions.builtin_commands import _make_session

    app = await _session_list_app(tmp_path, count=25)
    result = await _make_session(app)("list --page 2 --all", None)
    rows = [ln for ln in result.split("\n") if "model=" in ln]
    assert len(rows) == 25  # --all takes precedence --all 优先
