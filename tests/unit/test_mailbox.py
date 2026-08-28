"""Tests for the cross-agent Mailbox and SendMessageTool (6.2).
跨 Agent Mailbox 与 SendMessageTool 测试。"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from mini_agent.core.mailbox import Mailbox
from mini_agent.events.bus import EventBus
from mini_agent.models.config import AgentConfig
from mini_agent.models.session import Session
from mini_agent.tools.base import ToolContext, ToolRegistry
from mini_agent.tools.builtin.send_message import SendMessageTool
from tests.mocks import MockLLM

pytestmark = pytest.mark.asyncio


# --- Mailbox core ---


def make_mailbox(tmp_path) -> Mailbox:
    return Mailbox(tmp_path / "mailboxes")


async def test_send_and_drain(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")

    assert mb.send(sender="agent_a", recipient="main", content="found the bug")
    messages = mb.drain("main")
    assert len(messages) == 1
    assert messages[0].sender == "agent_a"
    assert messages[0].content == "found the bug"
    assert messages[0].timestamp

    # Drain clears the inbox 清空后再 drain 为空
    assert mb.drain("main") == []


async def test_has_pending_true_when_unread(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    assert not mb.has_pending("main")
    mb.send(sender="agent_a", recipient="main", content="hello")
    assert mb.has_pending("main")


async def test_has_pending_false_after_drain(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.send(sender="agent_a", recipient="main", content="hello")
    mb.drain("main")
    assert not mb.has_pending("main")


async def test_has_pending_unregistered(tmp_path):
    mb = make_mailbox(tmp_path)
    assert not mb.has_pending("ghost")


async def test_send_to_unknown_recipient(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    assert not mb.send(sender="main", recipient="ghost", content="hi")


async def test_drain_unregistered_agent(tmp_path):
    mb = make_mailbox(tmp_path)
    assert mb.drain("nobody") == []


async def test_messages_persist_to_file(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("agent_b")
    mb.send(sender="main", recipient="agent_b", content="第一条")
    mb.send(sender="main", recipient="agent_b", content="第二条")

    inbox = tmp_path / "mailboxes" / "agent_b.json"
    assert inbox.is_file()
    messages = mb.drain("agent_b")
    assert [m.content for m in messages] == ["第一条", "第二条"]


async def test_register_resets_stale_inbox(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.send(sender="main", recipient="main", content="stale")
    # New session re-registers -> old messages are dropped
    # 新会话重新注册 -> 旧消息被丢弃
    mb2 = make_mailbox(tmp_path)
    mb2.register("main")
    assert mb2.drain("main") == []


async def test_peers(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.register("agent_b")
    assert mb.peers(exclude="agent_a") == ["agent_b", "main"]
    mb.unregister("agent_b")
    assert mb.peers() == ["agent_a", "main"]


async def test_unregister_keeps_file_for_audit(tmp_path):
    """Unregister blocks new sends but keeps the inbox file as audit trail.
    注销后不可再投递，但收件箱文件保留作审计。"""
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.send(sender="main", recipient="agent_a", content="history")
    mb.drain("agent_a")
    mb.unregister("agent_a")
    assert (tmp_path / "mailboxes" / "agent_a.json").is_file()  # audit 留痕
    assert not mb.send(sender="main", recipient="agent_a", content="late")


async def test_drain_marks_read_and_keeps_on_disk(tmp_path):
    import json

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.send(sender="main", recipient="agent_a", content="evidence")
    assert len(mb.drain("agent_a")) == 1
    assert mb.drain("agent_a") == []  # already read 已读不再投递
    data = json.loads((tmp_path / "mailboxes" / "agent_a.json").read_text(encoding="utf-8"))
    assert len(data["messages"]) == 1
    assert data["messages"][0]["read"] is True
    assert data["messages"][0]["content"] == "evidence"


async def test_reset_all_wipes_inbox_files(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.register("agent_b")
    mb2 = make_mailbox(tmp_path)
    mb2.reset_all()
    assert list((tmp_path / "mailboxes").glob("*.json")) == []


async def test_broadcast_excludes_sender(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.register("agent_b")
    recipients = mb.broadcast(sender="agent_a", content="heads up")
    assert recipients == ["agent_b", "main"]
    assert mb.drain("agent_b")[0].content == "heads up"
    assert mb.drain("main")[0].content == "heads up"
    assert mb.drain("agent_a") == []  # sender excluded 发送者不收


async def test_name_addressing(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("a1b2c3d4", name="explorer")
    assert mb.resolve("explorer") == "a1b2c3d4"
    assert mb.resolve("a1b2c3d4") == "a1b2c3d4"
    assert mb.resolve("ghost") is None
    assert mb.send(sender="main", recipient="explorer", content="by name")
    assert mb.drain("a1b2c3d4")[0].content == "by name"
    assert mb.name_of("a1b2c3d4") == "explorer"
    assert "explorer (a1b2c3d4)" in mb.describe_peers(exclude="main")
    mb.unregister("a1b2c3d4")
    assert mb.resolve("explorer") is None  # alias dies with the agent 别名随注销失效


async def test_structured_message_fields_roundtrip(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.send(
        sender="main",
        recipient="agent_a",
        content="approve my plan?",
        type="request",
        request_id="r-123",
    )
    mb.send(
        sender="main",
        recipient="agent_a",
        content="looks good",
        type="response",
        request_id="r-123",
        approve=True,
    )
    msgs = mb.drain("agent_a")
    assert msgs[0].type == "request" and msgs[0].request_id == "r-123"
    assert msgs[1].type == "response" and msgs[1].approve is True


# --- SendMessageTool ---


def make_ctx(tmp_path, mailbox: Mailbox | None, agent_id: str = "agent_a") -> ToolContext:
    return ToolContext(
        working_dir=tmp_path,
        session=Session(),
        event_bus=EventBus(),
        config=AgentConfig(),
        mailbox=mailbox,
        agent_id=agent_id,
    )


async def test_send_message_tool_delivers(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="progress: 50%")
    assert not result.is_error
    assert "delivered to 'main'" in result.output
    messages = mb.drain("main")
    assert messages[0].sender == "agent_a"
    assert messages[0].content == "progress: 50%"


async def test_send_message_tool_unknown_recipient(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="ghost", message="hi")
    assert result.is_error
    assert "Unknown recipient" in result.output
    assert "main" in result.output  # lists known agents 列出已知 Agent


async def test_send_message_tool_no_mailbox(tmp_path):
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, None), to="main", message="hi")
    assert result.is_error
    assert "not available" in result.output


async def test_send_message_tool_empty_message(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="   ")
    assert result.is_error


async def test_send_message_tool_broadcast(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.register("agent_b")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="*", message="all hands")
    assert not result.is_error
    assert "broadcast to 2 agent(s)" in result.output
    assert mb.drain("main")[0].content == "all hands"
    assert mb.drain("agent_b")[0].content == "all hands"


async def test_send_message_tool_request_gets_id(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(
        make_ctx(tmp_path, mb), to="main", message="need a verdict", type="request"
    )
    assert not result.is_error
    assert "request_id=" in result.output
    msg = mb.drain("main")[0]
    assert msg.type == "request"
    assert msg.request_id  # auto-assigned 自动分配


async def test_send_message_tool_response_requires_request_id(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="yes", type="response")
    assert result.is_error
    assert "request_id" in result.output


async def test_send_message_tool_invalid_type(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    tool = SendMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), to="main", message="hi", type="shutdown")
    assert result.is_error
    assert "Invalid type" in result.output


async def test_send_message_tool_by_name(tmp_path):
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.register("b2c3d4e5", name="summarizer")
    tool = SendMessageTool()
    result = await tool.execute(
        make_ctx(tmp_path, mb), to="summarizer", message="findings attached"
    )
    assert not result.is_error
    assert mb.drain("b2c3d4e5")[0].content == "findings attached"


# --- WaitMessageTool ---


async def test_wait_message_returns_immediately_when_mail_waiting(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.send(sender="main", recipient="agent_a", content="here you go")
    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), timeout_seconds=5)
    assert not result.is_error
    assert "Received 1 message(s)" in result.output
    assert "[from 'main'" in result.output
    assert "here you go" in result.output


async def test_wait_message_blocks_until_mail_arrives(tmp_path):
    import asyncio

    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    mb.register("agent_b")
    tool = WaitMessageTool()

    async def send_later() -> None:
        await asyncio.sleep(0.7)
        mb.send(sender="agent_b", recipient="agent_a", content="delayed news")

    result, _ = await asyncio.gather(
        tool.execute(make_ctx(tmp_path, mb), timeout_seconds=10),
        send_later(),
    )
    assert not result.is_error
    assert "delayed news" in result.output


async def test_wait_message_timeout(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    mb = make_mailbox(tmp_path)
    mb.register("agent_a")
    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, mb), timeout_seconds=0.1)
    assert not result.is_error  # timeout is information, not an error 超时是信息不是错误
    assert "No message arrived" in result.output


async def test_wait_message_no_mailbox(tmp_path):
    from mini_agent.tools.builtin.wait_message import WaitMessageTool

    tool = WaitMessageTool()
    result = await tool.execute(make_ctx(tmp_path, None), timeout_seconds=1)
    assert result.is_error


# --- AgentLoop inbox delivery ---


async def test_agent_loop_delivers_inbox_messages(tmp_path):
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.models.message import Conversation, Message, Role

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.send(sender="agent_a", recipient="main", content="worker finding")

    bus = EventBus()
    config = AgentConfig()
    config.self_verify = False
    loop = AgentLoop(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        event_bus=bus,
        config=config,
        tool_context=make_ctx(tmp_path, mb, agent_id="main"),
    )
    loop.mailbox = mb
    loop.agent_id = "main"

    conversation = Conversation(system_prompt="test")
    conversation.append(Message(role=Role.USER, content="hello"))
    await loop.run(conversation)

    delivered = [
        m
        for m in conversation.messages
        if m.role == Role.USER and "[Message from agent 'agent_a']" in (m.content or "")
    ]
    assert len(delivered) == 1
    assert "worker finding" in delivered[0].content
    assert mb.drain("main") == []  # inbox drained 收件箱已清空


async def test_subagent_registers_and_gets_mailbox_prompt(tmp_path):
    from mini_agent.core.subagent import SubAgent

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    mb = make_mailbox(tmp_path)
    mb.register("main")

    agent = SubAgent(
        task="test task",
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
        mailbox=mb,
    )
    assert agent.agent_id in mb.peers()
    assert agent.agent_id in agent._conversation.system_prompt
    assert "send_message" in agent._conversation.system_prompt
    assert agent._loop.agent_id == agent.agent_id

    # After run() completes, the inbox is unregistered
    # run() 结束后收件箱注销
    await agent.run()
    assert agent.agent_id not in mb.peers()


async def test_spawn_parallel_siblings_know_each_other(tmp_path):
    from mini_agent.core.subagent import SubAgentManager

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    tasks = ["count unit tests", "count core files", "wait and sum the numbers"]
    ids = await mgr.spawn_parallel(tasks)
    assert len(set(ids)) == 3
    # Each agent's system prompt names its own id, and each peer id WITH its
    # task snippet -- so agents know which peer plays which role
    # 每个 Agent 的 prompt 含自身 id，同伴 id 均带任务摘要——知道谁是什么角色
    for i, agent_id in enumerate(ids):
        prompt = mgr._active[agent_id].agent._conversation.system_prompt
        assert f"agent '{agent_id}'" in prompt
        for j, peer in enumerate(ids):
            if peer != agent_id:
                assert f"'{peer}' (task: {tasks[j]}" in prompt
    await mgr.wait_all(ids)


async def test_spawn_parallel_with_names(tmp_path):
    from mini_agent.core.subagent import SubAgentManager

    registry = ToolRegistry()
    registry.register(SendMessageTool())
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    tasks = ["explore the core dir", "wait and summarize"]
    ids = await mgr.spawn_parallel(tasks, names=["explorer", "summarizer"])
    explorer_prompt = mgr._active[ids[0]].agent._conversation.system_prompt
    # Self label carries the name; peer listed by name with id and task
    # 自身标签带名字；同伴按名字列出并附 id 和任务
    assert f"agent 'explorer' (id '{ids[0]}')" in explorer_prompt
    assert f"'summarizer' (id {ids[1]}, task: wait and summarize" in explorer_prompt
    # Name addressing works through the shared mailbox 名字寻址走共享收件箱
    assert mgr.mailbox.resolve("summarizer") == ids[1]
    await mgr.wait_all(ids)


async def test_agent_loop_delivers_request_with_prefix(tmp_path):
    from mini_agent.core.agent_loop import AgentLoop
    from mini_agent.models.message import Conversation, Message, Role

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    mb.send(
        sender="agent_a",
        recipient="main",
        content="approve the plan?",
        type="request",
        request_id="r-777",
    )

    config = AgentConfig()
    config.self_verify = False
    loop = AgentLoop(
        llm=MockLLM(),
        tool_registry=ToolRegistry(),
        event_bus=EventBus(),
        config=config,
        tool_context=make_ctx(tmp_path, mb, agent_id="main"),
    )
    loop.mailbox = mb
    loop.agent_id = "main"

    conversation = Conversation(system_prompt="test")
    conversation.append(Message(role=Role.USER, content="hello"))
    await loop.run(conversation)

    delivered = [
        m.content
        for m in conversation.messages
        if m.role == Role.USER and "request_id=r-777" in (m.content or "")
    ]
    assert len(delivered) == 1
    assert delivered[0].startswith("[Request from agent 'agent_a' request_id=r-777]")


async def test_spawn_agents_tool_names_validation(tmp_path):
    from mini_agent.core.subagent import SubAgentManager
    from mini_agent.tools.builtin import SpawnAgentsTool

    registry = ToolRegistry()
    mgr = SubAgentManager(
        llm=MockLLM(),
        tool_registry=registry,
        config=AgentConfig(),
        event_bus=EventBus(),
        working_dir=tmp_path,
    )
    ctx = make_ctx(tmp_path, mgr.mailbox, agent_id="main")
    ctx.subagent_manager = mgr
    tool = SpawnAgentsTool()

    result = await tool.execute(ctx, tasks=["a", "b"], names=["only-one"])
    assert result.is_error and "must match" in result.output

    result = await tool.execute(ctx, tasks=["a", "b"], names=["dup", "dup"])
    assert result.is_error and "unique" in result.output

    result = await tool.execute(ctx, tasks=["a"], names=["main"])
    assert result.is_error


# --- Cross-process safety (6.4 prerequisite) 跨进程安全 ---


async def test_concurrent_processes_no_message_loss(tmp_path):
    """N processes x M appends to ONE inbox -- file lock must prevent any
    lost update. N 个进程并发向同一收件箱各写 M 条——文件锁保证零丢失。"""
    import subprocess
    import sys

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("target")

    script = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, r'{src}'); "
        "from mini_agent.core.mailbox import Mailbox; "
        "mb = Mailbox(Path(r'{box}')); "
        "[mb.send(sender=sys.argv[1], recipient='target', content=f'msg-{{i}}') "
        "for i in range(20)]"
    ).format(src=str(Path(__file__).parents[2] / "src"), box=str(tmp_path / "mailboxes"))

    procs = [
        subprocess.Popen(
            [sys.executable, "-c", script, f"writer{n}"],
            stderr=subprocess.PIPE,
            text=True,
        )
        for n in range(4)
    ]
    for p in procs:
        _, stderr = p.communicate(timeout=60)
        assert p.returncode == 0, f"writer crashed (exit {p.returncode}):\n{stderr}"

    messages = mb.drain("target")
    assert len(messages) == 80  # 4 procs x 20 msgs, zero lost
    senders = {m.sender for m in messages}
    assert senders == {"writer0", "writer1", "writer2", "writer3"}


async def test_registry_visible_across_instances(tmp_path):
    """A second Mailbox instance (as another process would create) sees
    agents registered by the first. 第二个 Mailbox 实例（等价另一进程）
    能看到第一个实例注册的 Agent。"""
    mb1 = make_mailbox(tmp_path)
    mb1.register("main")
    mb1.register("a1b2c3d4", name="explorer")

    mb2 = make_mailbox(tmp_path)  # fresh instance, no shared memory
    assert mb2.resolve("explorer") == "a1b2c3d4"
    assert mb2.resolve("a1b2c3d4") == "a1b2c3d4"
    assert "explorer (a1b2c3d4)" in mb2.describe_peers(exclude="main")
    assert mb2.send(sender="main", recipient="explorer", content="cross-process hi")
    assert mb1.drain("a1b2c3d4")[0].content == "cross-process hi"


async def test_stale_lock_taken_over(tmp_path):
    """A lock file left by a crashed process is taken over after
    STALE_LOCK_AGE. 崩溃进程遗留的锁超龄后被接管。"""
    import os as _os

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    inbox = tmp_path / "mailboxes" / "agent_a.json"
    stale = Path(f"{inbox}.lock")
    stale.write_text("", encoding="utf-8")
    old = time.time() - 60
    _os.utime(stale, (old, old))

    assert mb.send(sender="main", recipient="agent_a", content="took over")
    assert mb.drain("agent_a")[0].content == "took over"
    assert not stale.exists()  # lock released 锁已释放


async def test_fresh_lock_times_out(tmp_path, monkeypatch):
    """A recent (non-stale) lock held by someone else -> TimeoutError, the
    caller knows the message was NOT delivered.
    他人持有的新鲜锁 -> 超时抛异常，调用方知道消息没送出去。"""
    import mini_agent.core.mailbox as mbox

    monkeypatch.setattr(mbox, "LOCK_TIMEOUT", 0.3)
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")
    inbox = tmp_path / "mailboxes" / "agent_a.json"
    Path(f"{inbox}.lock").write_text("", encoding="utf-8")  # fresh lock

    with pytest.raises(TimeoutError):
        mb.send(sender="main", recipient="agent_a", content="never lands")


async def test_lock_acquire_retries_permission_error(tmp_path, monkeypatch):
    """Windows delete-pending: os.open(O_EXCL) raises PermissionError while
    an AV process still holds the just-unlinked lock -- must be retried like
    ordinary contention, not crash the sender.
    Windows delete-pending：杀毒进程握着刚被 unlink 的锁时 O_EXCL 抛
    PermissionError——须按普通锁竞争重试，不能炸掉发送方。"""
    import os as _os

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")

    real_open = _os.open
    failed = {"n": 0}

    def flaky_open(path, flags, mode=0o777, **kwargs):
        if str(path).endswith(".lock") and failed["n"] == 0:
            failed["n"] += 1
            raise PermissionError(13, "delete pending", str(path))
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr("mini_agent.core.mailbox.os.open", flaky_open)
    assert mb.send(sender="main", recipient="agent_a", content="survived")
    assert failed["n"] == 1
    assert mb.drain("agent_a")[0].content == "survived"


async def test_atomic_write_retries_permission_error(tmp_path, monkeypatch):
    """os.replace transiently blocked (AV holding tmp/destination) -> retry
    succeeds and the message lands.
    os.replace 被瞬时占用（杀毒持有临时/目标文件）-> 重试成功，消息落盘。"""
    import os as _os

    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")

    real_replace = _os.replace
    failed = {"n": 0}

    def flaky_replace(src, dst):
        if failed["n"] < 2:
            failed["n"] += 1
            raise PermissionError(13, "in use", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr("mini_agent.core.mailbox.os.replace", flaky_replace)
    assert mb.send(sender="main", recipient="agent_a", content="landed")
    assert failed["n"] == 2
    assert mb.drain("agent_a")[0].content == "landed"


async def test_atomic_write_permission_error_exhausted(tmp_path, monkeypatch):
    """os.replace permanently blocked -> PermissionError propagates after
    retries exhaust (caller must know the write failed).
    os.replace 持续被占 -> 重试耗尽后异常上抛（调用方必须知道写失败）。"""
    mb = make_mailbox(tmp_path)
    mb.register("main")
    mb.register("agent_a")

    def always_fail(src, dst):
        raise PermissionError(13, "in use", str(dst))

    monkeypatch.setattr("mini_agent.core.mailbox.os.replace", always_fail)
    with pytest.raises(PermissionError):
        mb.send(sender="main", recipient="agent_a", content="never lands")


async def test_reserved_registry_id_rejected(tmp_path):
    mb = make_mailbox(tmp_path)
    with pytest.raises(ValueError):
        mb.register("_registry")
