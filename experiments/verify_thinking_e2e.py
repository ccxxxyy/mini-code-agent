"""End-to-end verification of request-side extended thinking (tech-notes §110).
发送侧 extended thinking 全管道无污染验证。

Starts a local mock Anthropic SSE server that emits official-shaped events
(thinking_delta / signature_delta / tool_use), then runs the REAL mini-agent
headless pipeline against it (config env vars -> AnthropicProvider ->
agent_loop -> tool execution -> second LLM call), and asserts:

  1. Request 1 body carries `thinking: {type: enabled, budget_tokens}`
  2. stream-json output contains thinking_delta events (思考流进渲染管道)
  3. Request 2 round-trips the SIGNED thinking block before tool_use,
     followed by the tool_result (多轮签名往返)
  4. Exit code 0, final answer delivered

Turn-2 SSE intentionally uses `data:{...}` WITHOUT the space after the colon
to keep covering the gateway-compat parsing fix in the same run.
第二轮 SSE 故意用 `data:` 后无空格的格式，同一趟顺带覆盖网关兼容解析修复。

Run: uv run python experiments/verify_thinking_e2e.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

THINKING_TEXT = "我先想想边界情况"
SIGNATURE = "sig-e2e-test-123"
FINAL_TEXT = "思考管道验证完成"

REQUESTS: list[dict] = []


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def log(msg: str) -> None:
    print(f"[{ts()}] {msg}", flush=True)


def sse(event: dict, space: bool = True) -> bytes:
    sep = "data: " if space else "data:"
    return f"{sep}{json.dumps(event, ensure_ascii=False)}\n\n".encode()


def turn1_payload() -> bytes:
    """Thinking block (deltas + signature) then a tool_use, official shapes.
    官方事件形态：thinking 块（增量+签名）后跟 tool_use。"""
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": THINKING_TEXT[:4]},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "thinking_delta", "thinking": THINKING_TEXT[4:]},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "signature_delta", "signature": SIGNATURE},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tu_1", "name": "glob"},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"pattern": "*.toml"}'},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 7},
        },
    ]
    return b"".join(sse(e) for e in events)


def turn2_payload() -> bytes:
    """Final text answer; `data:` without space (gateway-compat coverage).
    最终文本回答；data: 后无空格（覆盖网关兼容解析）。"""
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": FINAL_TEXT},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 4},
        },
    ]
    return b"".join(sse(e, space=False) for e in events)


async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await reader.read(4096)
            if not chunk:
                return
            header += chunk
        head, _, rest = header.partition(b"\r\n\r\n")
        length = 0
        for line in head.decode("latin1").split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = rest
        while len(body) < length:
            body += await reader.read(4096)
        req = json.loads(body.decode("utf-8"))
        REQUESTS.append(req)

        has_tool_result = any(
            isinstance(m.get("content"), list)
            and any(b.get("type") == "tool_result" for b in m["content"])
            for m in req.get("messages", [])
        )
        turn = 2 if has_tool_result else 1
        log(
            f"mock server: request #{len(REQUESTS)} (turn {turn}), "
            f"thinking={req.get('thinking')}, messages={len(req.get('messages', []))}"
        )
        payload = turn2_payload() if turn == 2 else turn1_payload()
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"content-type: text/event-stream\r\n"
            b"connection: close\r\n"
            b"content-length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload
        )
        await writer.drain()
    finally:
        writer.close()


def run_agent(port: int) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "MINI_AGENT_PROVIDER": "anthropic",
        "MINI_AGENT_BASE_URL": f"http://127.0.0.1:{port}",
        "MINI_AGENT_API_KEY": "test-key-not-real",
        "MINI_AGENT_MODEL": "claude-sonnet-4-5-20250929",
        "MINI_AGENT_THINKING": "true",
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from mini_agent.cli import main; main()",
            "-p",
            "列出项目里的 toml 文件",
            "--output-format",
            "stream-json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


async def main() -> int:
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    log(f"mock Anthropic SSE server on 127.0.0.1:{port}")

    proc = await asyncio.get_running_loop().run_in_executor(None, run_agent, port)
    server.close()
    await server.wait_closed()

    log(f"agent exit code: {proc.returncode}")
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))  # every line must be valid NDJSON
    event_types = [e.get("type") for e in events]
    log(f"stream-json events: {event_types}")

    failures: list[str] = []

    # 1. request 1: thinking param (sonnet-4-5 -> explicit budget max_tokens-1)
    req1 = REQUESTS[0]
    expected = {"type": "enabled", "budget_tokens": req1["max_tokens"] - 1}
    if req1.get("thinking") == expected:
        log(f"PASS 1: request 1 thinking param = {req1['thinking']}")
    else:
        failures.append(f"request 1 thinking param wrong: {req1.get('thinking')} != {expected}")

    # 2. thinking stream reached the render pipeline
    thinking_events = [e for e in events if e.get("type") == "thinking_delta"]
    streamed = "".join(e.get("delta", "") for e in thinking_events)
    if streamed == THINKING_TEXT:
        log(f"PASS 2: thinking_delta events streamed intact: {streamed!r}")
    else:
        failures.append(f"thinking stream mismatch: {streamed!r} != {THINKING_TEXT!r}")

    # 3. request 2: signed thinking block round-trip before tool_use + tool_result present
    if len(REQUESTS) < 2:
        failures.append(f"expected 2 LLM calls, got {len(REQUESTS)}")
    else:
        req2 = REQUESTS[1]
        assistant = next(
            (
                m
                for m in req2["messages"]
                if m["role"] == "assistant" and isinstance(m.get("content"), list)
            ),
            None,
        )
        blocks = (assistant or {}).get("content", [])
        want = {"type": "thinking", "thinking": THINKING_TEXT, "signature": SIGNATURE}
        if blocks and blocks[0] == want and blocks[1].get("type") == "tool_use":
            log("PASS 3: request 2 round-trips signed thinking block before tool_use")
        else:
            got = json.dumps(blocks, ensure_ascii=False)[:300]
            failures.append(f"round-trip blocks wrong: {got}")

    # 4. final answer + exit code
    stream_texts = "".join(e.get("delta", "") for e in events if e.get("type") == "stream_text")
    if proc.returncode == 0 and FINAL_TEXT in stream_texts:
        log(f"PASS 4: exit 0, final answer delivered: {stream_texts!r}")
    else:
        failures.append(
            f"exit={proc.returncode}, stream_text={stream_texts!r}, "
            f"stderr tail: {proc.stderr[-300:]}"
        )

    print()
    if failures:
        for f in failures:
            log(f"FAIL: {f}")
        log(f"VERDICT: FAIL ({4 - len(failures)}/4)")
        return 1
    log("VERDICT: PASS (4/4) — 思考流渲染 / thinking 参数 / 签名往返 / 完整回合全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
