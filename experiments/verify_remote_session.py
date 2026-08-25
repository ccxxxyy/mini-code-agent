"""Real-run verification for remote-mode session persistence.
远程模式会话持久化真实验证：WS 客户端两阶段驱动真实服务器。

Phase 1 (chat):    connect, send a prompt, wait for turn_end, print events.
Phase 2 (verify):  connect, collect history_* replay events, assert the
                   phase-1 exchange survived the server restart.

Usage:
    python experiments/verify_remote_session.py chat <port>
    python experiments/verify_remote_session.py verify <port>
"""

from __future__ import annotations

import asyncio
import json
import sys


async def chat(port: int) -> None:
    import websockets

    uri = f"ws://localhost:{port}/ws"
    async with websockets.connect(uri) as ws:
        prompt = "9.9 和 9.11 哪个大？只回答结果，一句话。"
        await ws.send(json.dumps({"type": "user_input", "text": prompt}))
        async for raw in ws:
            msg = json.loads(raw)
            t = msg.get("type", "")
            if t in ("stream_end",):
                print("ASSISTANT:", msg.get("full_text", "")[:200])
            elif t == "turn_end":
                print("TURN_END tokens=", msg.get("tokens"))
                return
            elif t == "error":
                print("ERROR:", msg.get("message"))
                return


async def verify(port: int) -> None:
    import websockets

    uri = f"ws://localhost:{port}/ws"
    history: list[tuple[str, str]] = []
    async with websockets.connect(uri) as ws:
        try:
            async with asyncio.timeout(10):
                async for raw in ws:
                    msg = json.loads(raw)
                    t = msg.get("type", "")
                    if t.startswith("history_"):
                        history.append((t, msg.get("text", "")[:100]))
                    elif t == "commands":  # sent after replay 重放之后发送
                        break
        except TimeoutError:
            pass

    print(f"HISTORY EVENTS: {len(history)}")
    for t, text in history:
        print(f"  {t}: {text}")
    user_ok = any(t == "history_user" and "9.11" in text for t, text in history)
    asst_ok = any(t == "history_assistant" and text.strip() for t, text in history)
    print("USER_RESTORED:", user_ok)
    print("ASSISTANT_RESTORED:", asst_ok)
    print("VERDICT:", "PASS" if (user_ok and asst_ok) else "FAIL")


if __name__ == "__main__":
    mode, port = sys.argv[1], int(sys.argv[2])
    asyncio.run(chat(port) if mode == "chat" else verify(port))
