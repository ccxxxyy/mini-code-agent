"""Tests for core data models."""

from mini_agent.models.message import Conversation, Message, Role, ToolCall, ToolResult


def test_message_defaults():
    msg = Message()
    assert msg.role == Role.USER
    assert msg.content == ""
    assert msg.id


def test_conversation_append():
    conv = Conversation(system_prompt="test")
    msg = Message(role=Role.USER, content="hello", token_count=5)
    conv.append(msg)
    assert len(conv.messages) == 1
    assert conv.total_tokens == 5


def test_conversation_to_api_messages():
    conv = Conversation(system_prompt="You are helpful.")
    conv.append(Message(role=Role.USER, content="hi"))
    conv.append(Message(role=Role.ASSISTANT, content="hello"))

    api = conv.to_api_messages()
    assert len(api) == 3
    assert api[0] == {"role": "system", "content": "You are helpful."}
    assert api[1] == {"role": "user", "content": "hi"}
    assert api[2] == {"role": "assistant", "content": "hello"}


def test_conversation_tool_call_messages():
    conv = Conversation()
    tc = ToolCall(id="tc_1", name="read_file", arguments={"path": "/tmp/a.txt"})
    conv.append(Message(role=Role.ASSISTANT, content="", tool_calls=[tc]))

    tr = ToolResult(call_id="tc_1", name="read_file", output="file contents")
    conv.append(Message(role=Role.TOOL, tool_result=tr))

    api = conv.to_api_messages()
    assert len(api) == 2
    assert api[0]["role"] == "assistant"
    assert len(api[0]["tool_calls"]) == 1
    assert api[0]["tool_calls"][0]["function"]["name"] == "read_file"
    assert api[1]["role"] == "tool"
    assert api[1]["tool_call_id"] == "tc_1"
