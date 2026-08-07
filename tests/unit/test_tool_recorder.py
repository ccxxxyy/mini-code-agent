"""Tests for toolchain recording and replay. 工具链录制与回放测试。"""

from __future__ import annotations

import pytest

from mini_agent.core.tool_recorder import ToolRecorder
from mini_agent.models.events import ToolCallEndEvent, ToolCallStartEvent

pytestmark = pytest.mark.asyncio


@pytest.fixture
def recorder(tmp_path):
    return ToolRecorder(tmp_path / "recordings")


async def emit_call(rec, call_id: str, tool: str, args: dict, is_error: bool = False):
    await rec._on_start(ToolCallStartEvent(tool_name=tool, arguments=args, call_id=call_id))
    await rec._on_end(
        ToolCallEndEvent(tool_name=tool, call_id=call_id, is_error=is_error, duration_ms=1.0)
    )


# --- ToolRecorder unit tests ---


async def test_start_stop_saves(recorder, tmp_path):
    recorder.start("demo")
    await emit_call(recorder, "c1", "bash", {"command": "echo hi"})
    count, path = recorder.stop()

    assert count == 1
    assert path.is_file()
    data = recorder.load("demo")
    assert data["steps"][0]["tool"] == "bash"
    assert data["steps"][0]["args"]["command"] == "echo hi"


async def test_only_successful_calls_recorded(recorder):
    recorder.start("demo")
    await emit_call(recorder, "c1", "bash", {"command": "ok"})
    await emit_call(recorder, "c2", "bash", {"command": "boom"}, is_error=True)
    count, _ = recorder.stop()

    assert count == 1
    assert recorder.load("demo")["steps"][0]["args"]["command"] == "ok"


async def test_cancel_discards(recorder):
    recorder.start("demo")
    await emit_call(recorder, "c1", "bash", {"command": "x"})
    recorder.cancel()

    assert recorder.load("demo") is None
    assert not recorder.is_recording


async def test_suspended_not_recorded(recorder):
    recorder.start("demo")
    recorder.suspended = True
    await emit_call(recorder, "c1", "bash", {"command": "x"})
    recorder.suspended = False
    count, _ = recorder.stop()

    assert count == 0


async def test_not_recording_ignores_events(recorder):
    await emit_call(recorder, "c1", "bash", {"command": "x"})
    assert not recorder._steps


async def test_list_load_delete_roundtrip(recorder):
    recorder.start("one")
    await emit_call(recorder, "c1", "bash", {"command": "a"})
    recorder.stop()
    recorder.start("two")
    await emit_call(recorder, "c2", "bash", {"command": "b"})
    recorder.stop()

    names = [it["name"] for it in recorder.list_recordings()]
    assert names == ["one", "two"]
    assert recorder.delete("one") is True
    assert recorder.delete("one") is False
    assert [it["name"] for it in recorder.list_recordings()] == ["two"]


# --- command integration 命令集成 ---


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


async def test_record_command_full_cycle(app, tmp_path):
    from mini_agent.models.message import ToolCall

    result = await app.slash_commands.execute("/record start mytask")
    assert "Recording 'mytask'" in result

    # A real tool call flows through the event bus 真实工具调用经过事件总线
    target = tmp_path / "rec.txt"
    await app.agent_loop._act(
        [ToolCall(id="c1", name="write_file", arguments={"file_path": str(target), "content": "v"})]
    )

    result = await app.slash_commands.execute("/record stop")
    assert "1 step(s)" in result

    result = await app.slash_commands.execute("/record")
    assert "mytask" in result


async def test_replay_executes_tools(app, tmp_path):
    from mini_agent.models.message import ToolCall

    target = tmp_path / "replayed.txt"
    await app.slash_commands.execute("/record start flow")
    await app.agent_loop._act(
        [
            ToolCall(
                id="c1", name="write_file", arguments={"file_path": str(target), "content": "data"}
            )
        ]
    )
    await app.slash_commands.execute("/record stop")

    target.unlink()  # remove so replay must recreate it 删掉让回放重建
    result = await app.slash_commands.execute("/replay flow")

    assert "ok" in result
    assert target.read_text(encoding="utf-8") == "data"


async def test_replay_stops_on_failure(app, tmp_path):
    import json

    # Hand-craft a recording: step1 fails (edit missing file), step2 would create a file
    # 手工构造录制：第一步必败，第二步不该执行
    rec_dir = app.tool_recorder._dir
    rec_dir.mkdir(parents=True, exist_ok=True)
    marker = tmp_path / "should_not_exist.txt"
    (rec_dir / "bad.json").write_text(
        json.dumps(
            {
                "name": "bad",
                "steps": [
                    {
                        "tool": "edit_file",
                        "args": {
                            "file_path": str(tmp_path / "nope.txt"),
                            "old_text": "a",
                            "new_text": "b",
                        },
                    },
                    {"tool": "write_file", "args": {"file_path": str(marker), "content": "x"}},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = await app.slash_commands.execute("/replay bad")
    assert "FAILED" in result
    assert "Stopped" in result
    assert not marker.exists()  # step 2 never ran 第二步未执行


async def test_replay_missing_recording(app):
    result = await app.slash_commands.execute("/replay nonexistent")
    assert "not found" in result


# --- template variables 模板变量 ---


async def test_render_template_substitutes():
    from mini_agent.core.tool_recorder import render_template

    args = {"file_path": "report_{{date}}.txt", "content": "by {{author}}", "n": 3}
    out = render_template(args, {"date": "2026-08-07", "author": "me"})
    assert out["file_path"] == "report_2026-08-07.txt"
    assert out["content"] == "by me"
    assert out["n"] == 3


async def test_render_template_nested():
    from mini_agent.core.tool_recorder import render_template

    args = {"outer": {"inner": ["{{x}}", "static"]}}
    out = render_template(args, {"x": "VAL"})
    assert out["outer"]["inner"] == ["VAL", "static"]


async def test_builtin_variables_present():
    from mini_agent.core.tool_recorder import builtin_variables

    v = builtin_variables()
    assert set(v) == {"date", "time", "datetime"}
    assert len(v["date"]) == 10  # YYYY-MM-DD


async def test_find_placeholders():
    from mini_agent.core.tool_recorder import find_placeholders

    steps = [
        {"tool": "write_file", "args": {"file_path": "r_{{date}}.txt", "content": "{{msg}}"}},
        {"tool": "bash", "args": {"command": "echo {{msg}}"}},
    ]
    assert find_placeholders(steps) == {"date", "msg"}


async def test_replay_with_template_variable(app, tmp_path):
    import json

    rec_dir = app.tool_recorder._dir
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "tpl.json").write_text(
        json.dumps(
            {
                "name": "tpl",
                "steps": [
                    {
                        "tool": "write_file",
                        "args": {
                            "file_path": str(tmp_path / "out_{{tag}}.txt"),
                            "content": "on {{date}}",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = await app.slash_commands.execute("/replay tpl tag=v1")
    assert "ok" in result
    out = tmp_path / "out_v1.txt"
    assert out.exists()
    assert "on 20" in out.read_text(encoding="utf-8")  # {{date}} auto-filled 自动填充


async def test_replay_missing_variable_reports(app):
    import json

    rec_dir = app.tool_recorder._dir
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / "needs.json").write_text(
        json.dumps(
            {
                "name": "needs",
                "steps": [{"tool": "bash", "args": {"command": "echo {{target}}"}}],
            }
        ),
        encoding="utf-8",
    )

    result = await app.slash_commands.execute("/replay needs")
    assert "Missing template variable" in result
    assert "target" in result
