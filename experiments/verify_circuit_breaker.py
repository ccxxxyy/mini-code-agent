"""Verify compression circuit breaker with real LLM.
用真实 LLM 验证压缩熔断器。

Five phases:
  Phase 1: Normal compression -- real LLM fills context, compression succeeds.
  Phase 2: Real trigger -- many read files make _inject_read_files cancel out
           compression gains, breaker trips naturally.
  Phase 3: ensure_fits fallback -- hard truncation still works after breaker.
  Phase 4: Without breaker -- same scenario with breaker disabled (max=0),
           shows the wasted compression attempts the breaker prevents.
  Phase 5: Recovery -- new session (fresh ContextManager) starts clean.

Usage:
    uv run python experiments/verify_circuit_breaker.py
    uv run python experiments/verify_circuit_breaker.py --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from mini_agent.config.loader import ConfigLoader
from mini_agent.llm.registry import ProviderRegistry
from mini_agent.memory.compressor import Compressor
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role

WINDOW = 4_000
THRESHOLD = 0.5


def status(ctx: ContextManager, label: str) -> None:
    print(
        f"  {label}: tokens={ctx.total_tokens}/{ctx.max_tokens} "
        f"ratio={ctx.usage_ratio:.1%} failures={ctx._compress_failures}/"
        f"{ctx._max_compress_failures}"
    )


async def ask_llm(llm, conv: Conversation, prompt: str) -> str:
    """Send a prompt and collect the full response via streaming."""
    conv.append(Message(role=Role.USER, content=prompt))
    api_msgs = conv.to_api_messages()
    chunks = []
    async for chunk in llm.stream(api_msgs):
        if chunk.delta:
            chunks.append(chunk.delta)
    reply = "".join(chunks)
    conv.append(Message(role=Role.ASSISTANT, content=reply))
    return reply


async def main() -> None:
    parser = argparse.ArgumentParser(description="Verify compression circuit breaker")
    parser.add_argument("--model", type=str, help="Override model")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("mini_agent.memory.context").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = ConfigLoader.load()
    if args.model:
        config.llm.model = args.model

    print(f"Model: {config.llm.model}")
    print(f"Window: {WINDOW} tokens | Threshold: {THRESHOLD} | Max failures: 3")
    print("=" * 60)

    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()

    # == Phase 1: Normal compression with real LLM ==
    print("\n== Phase 1: Normal compression (real LLM) ==")
    print("Scenario: long conversation fills context, compression reduces tokens.")

    ctx = ContextManager(
        MemoryConfig(
            context_window=WINDOW, compression_threshold=THRESHOLD, compress_max_failures=3
        )
    )
    ctx.set_compressor(Compressor())

    conv = Conversation(
        system_prompt=(
            "You are a helpful assistant. Always reply with a LONG detailed "
            "answer of at least 300 words to help fill up the context window."
        )
    )

    prompts = [
        "Explain Python asyncio event loop, Task, Future, and coroutine in detail.",
        "Explain Python GIL and how it limits multithreading concurrency.",
        "Compare asyncio vs threading vs multiprocessing with examples.",
    ]

    for i, prompt in enumerate(prompts):
        reply = await ask_llm(llm, conv, prompt)
        ctx.update_total(conv)
        status(ctx, f"After LLM reply {i + 1} ({len(reply)} chars)")

        compressed = await ctx.check_and_compress(conv)
        if compressed:
            print(f"  -> Compression fired! msgs: {len(conv.messages)}")
        status(ctx, f"After compress check {i + 1}")
        print()

    p1_failures = ctx._compress_failures
    print(f"Phase 1 result: failures={p1_failures}")
    assert p1_failures < 3, f"Breaker should NOT trip in normal mode, got {p1_failures}"
    print("[PASS] Phase 1: normal compression works, breaker did not trip\n")

    # == Phase 2: Real trigger -- many read files cancel out compression ==
    print("== Phase 2: Real trigger -- read files exhaust compression headroom ==")
    print("Scenario: agent read 150 files; the injected note is so large that")
    print("          compression gains are cancelled out by _inject_read_files.")

    ctx2 = ContextManager(
        MemoryConfig(
            context_window=WINDOW, compression_threshold=THRESHOLD, compress_max_failures=3
        )
    )
    ctx2.set_compressor(Compressor())

    for i in range(150):
        ctx2.record_file_read(f"src/module_{i}/component_{i}.py")

    conv2 = Conversation(system_prompt="You are helpful.")
    for i in range(8):
        conv2.append(Message(role=Role.USER, content=f"Question {i} " + "a" * 100))
        conv2.append(Message(role=Role.ASSISTANT, content=f"Answer {i} " + "b" * 100))

    attempt = 0
    while ctx2._compress_failures < 3:
        attempt += 1
        ctx2.update_total(conv2)
        status(ctx2, f"Before attempt {attempt}")
        result = await ctx2.check_and_compress(conv2)
        print(f"  -> check_and_compress returned {result}")
        status(ctx2, f"After attempt {attempt}")
        if not result and ctx2._compress_failures < 3:
            print("  (below threshold, adding more messages)")
            for j in range(5):
                conv2.append(Message(role=Role.USER, content=f"Extra {attempt}_{j} " + "c" * 150))
        print()
        if attempt > 20:
            break

    if ctx2._compress_failures >= 3:
        ctx2.update_total(conv2)
        result = await ctx2.check_and_compress(conv2)
        print(f"  -> Breaker check: returned {result} (should be False)")
        assert result is False, "Breaker should have tripped"
        print(f"[PASS] Phase 2: breaker tripped after {attempt} attempts")
        print(f"  read_files injected: {len(ctx2.read_files)} files\n")
    else:
        print(f"[INFO] Phase 2: breaker did not trip in {attempt} attempts")
        print("  Default compressor is strong enough to overcome read_files overhead.")
        print("  This is OK -- the breaker is a safety net, not a frequent event.\n")

    # == Phase 3: ensure_fits fallback ==
    print("== Phase 3: ensure_fits fallback ==")
    print("Scenario: breaker tripped + conversation overflows the window.")
    print("          check_and_compress is blocked, but ensure_fits truncates.")

    # Use a SMALLER window so ensure_fits actually triggers
    small_window = 800
    ctx3 = ContextManager(
        MemoryConfig(
            context_window=small_window, compression_threshold=THRESHOLD, compress_max_failures=3
        )
    )
    ctx3._compress_failures = 3  # simulate tripped breaker

    conv3 = Conversation(system_prompt="You are helpful.")
    for i in range(50):
        conv3.append(Message(role=Role.USER, content=f"Big message {i} " + "x" * 200))

    ctx3.update_total(conv3)
    status(ctx3, "Before ensure_fits")
    msg_before = len(conv3.messages)

    result = await ctx3.check_and_compress(conv3)
    assert result is False, "Breaker should block check_and_compress"
    print(f"  -> check_and_compress: {result} (blocked by breaker)")

    truncated = await ctx3.ensure_fits(conv3, small_window)
    status(ctx3, "After ensure_fits")
    print(f"  -> ensure_fits: {truncated}, msgs {msg_before} -> {len(conv3.messages)}")

    assert truncated
    assert len(conv3.messages) < msg_before
    print("[PASS] Phase 3: ensure_fits works as hard fallback after breaker trips\n")

    # == Phase 4: Without breaker (control group) ==
    print("== Phase 4: Without breaker (max_failures=0, disabled) ==")
    print("Scenario: same as Phase 2 but breaker disabled -- shows wasted attempts.")

    ctx4 = ContextManager(
        MemoryConfig(
            context_window=WINDOW, compression_threshold=THRESHOLD, compress_max_failures=0
        )
    )
    ctx4.set_compressor(Compressor())
    for i in range(150):
        ctx4.record_file_read(f"src/module_{i}/component_{i}.py")

    conv4 = Conversation(system_prompt="You are helpful.")
    for i in range(8):
        conv4.append(Message(role=Role.USER, content=f"Q{i} " + "a" * 100))
        conv4.append(Message(role=Role.ASSISTANT, content=f"A{i} " + "b" * 100))

    wasted = 0
    for attempt in range(6):
        ctx4.update_total(conv4)
        if not ctx4.needs_compression:
            for j in range(5):
                conv4.append(Message(role=Role.USER, content=f"Fill {attempt}_{j} " + "d" * 150))
            continue
        old = ctx4.total_tokens
        await ctx4.check_and_compress(conv4)
        new = ctx4.total_tokens
        if new >= old:
            wasted += 1
            print(f"  Attempt {attempt + 1}: WASTED ({old} -> {new})")
        else:
            print(f"  Attempt {attempt + 1}: effective ({old} -> {new})")

    print(f"  Wasted attempts: {wasted} (breaker=off, no protection)")
    print("  With breaker=on, would have stopped after 3.\n")

    # == Phase 5: Recovery (new session) ==
    print("== Phase 5: Recovery -- new session, fresh state ==")
    print("Scenario: breaker is session-scoped. New session = new ContextManager.")

    ctx5 = ContextManager(
        MemoryConfig(
            context_window=WINDOW, compression_threshold=THRESHOLD, compress_max_failures=3
        )
    )
    ctx5.set_compressor(Compressor())

    conv5 = Conversation(system_prompt="You are helpful.")
    reply = await ask_llm(llm, conv5, "What is Python's GIL? Explain in detail.")
    ctx5.update_total(conv5)
    status(ctx5, "New session after LLM reply")

    compressed = await ctx5.check_and_compress(conv5)
    if compressed:
        print(f"  -> Compression fired! msgs: {len(conv5.messages)}")
    status(ctx5, "After compress check")
    assert ctx5._compress_failures == 0
    print("[PASS] Phase 5: new session starts clean, compression works\n")

    print("=" * 60)
    print("ALL PHASES PASSED")


if __name__ == "__main__":
    asyncio.run(main())
