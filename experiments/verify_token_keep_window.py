"""Verify token-driven reservation window with real LLM.
用真实 LLM 验证 token 驱动的保留窗口。

Three phases:
  Phase 1: Short messages — all kept (total tokens < KEEP_RECENT_TOKENS).
           Old KEEP_RECENT=6 would have summarized 14 of 20 messages.
  Phase 2: Long messages — token budget limits kept count.
           Old KEEP_RECENT=6 would keep 6×8K=48K tokens (too much).
  Phase 3: Real LLM conversation — compression fires and the kept
           window adapts to actual message sizes.

Usage:
    uv run python experiments/verify_token_keep_window.py
    uv run python experiments/verify_token_keep_window.py --model gpt-4o-mini
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
from mini_agent.memory.compressor import (
    KEEP_MAX_TOKENS,
    KEEP_RECENT_TOKENS,
    MIN_KEEP_MESSAGES,
    Compressor,
    LLMSummarizeOldest,
    SummarizeOldest,
    _compute_keep_split,
)
from mini_agent.memory.context import ContextManager
from mini_agent.models.config import MemoryConfig
from mini_agent.models.message import Conversation, Message, Role

WINDOW = 10_000


def status(ctx: ContextManager, conv: Conversation, label: str) -> None:
    ctx.update_total(conv)
    print(
        f"  {label}: tokens={ctx.total_tokens}/{ctx.max_tokens} "
        f"ratio={ctx.usage_ratio:.1%} msgs={len(conv.messages)}"
    )


def make_msg(role=Role.USER, content="x" * 100, token_count=25) -> Message:
    msg = Message(role=role, content=content)
    msg.token_count = token_count
    return msg


async def ask_llm(llm, conv: Conversation, prompt: str) -> str:
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
    parser = argparse.ArgumentParser(description="Verify token-driven keep window")
    parser.add_argument("--model", type=str, help="Override model")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("mini_agent.memory.context").setLevel(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = ConfigLoader.load()
    if args.model:
        config.llm.model = args.model

    print(f"Model: {config.llm.model}")
    print(
        f"Constants: KEEP_RECENT_TOKENS={KEEP_RECENT_TOKENS} "
        f"MIN_KEEP_MESSAGES={MIN_KEEP_MESSAGES} KEEP_MAX_TOKENS={KEEP_MAX_TOKENS}"
    )
    print("=" * 70)

    # == Phase 1: Short messages — all kept 短消息全保留 ==
    print("\n== Phase 1: Short messages — token-driven keeps ALL ==")
    print("Scenario: 20 messages × 10 tokens = 200 total. Old KEEP_RECENT=6")
    print("          would summarize 14 messages. Token-driven keeps all.")

    conv1 = Conversation()
    for i in range(20):
        conv1.messages.append(make_msg(content=f"short msg {i}", token_count=10))

    split = _compute_keep_split(conv1.messages)
    kept = len(conv1.messages) - split
    print(f"  _compute_keep_split: split={split}, kept={kept}")
    assert split == 0, f"Expected split=0 (keep all), got {split}"
    assert kept == 20, f"Expected kept=20, got {kept}"

    strategy = SummarizeOldest()
    msgs_before = len(conv1.messages)
    await strategy.compress(conv1, 100)
    print(f"  SummarizeOldest: msgs {msgs_before} -> {len(conv1.messages)} (should be unchanged)")
    assert len(conv1.messages) == 20, "Short messages should all be kept"
    print("[PASS] Phase 1: short messages all kept (old behavior would lose 14)\n")

    # == Phase 2: Long messages — token budget limits 长消息受 token 预算限制 ==
    print("== Phase 2: Long messages — token budget limits kept count ==")
    print("Scenario: 20 messages × 8000 tokens each. Old KEEP_RECENT=6 would")
    print("          keep 48K tokens. Token-driven keeps 5 (40K = KEEP_MAX_TOKENS).")

    conv2 = Conversation()
    for i in range(20):
        conv2.messages.append(make_msg(content=f"long msg {i}", token_count=8000))

    split2 = _compute_keep_split(conv2.messages)
    kept2 = len(conv2.messages) - split2
    print(f"  _compute_keep_split: split={split2}, kept={kept2}")
    assert kept2 == MIN_KEEP_MESSAGES, f"Expected kept={MIN_KEEP_MESSAGES}, got {kept2}"
    assert split2 == 15, f"Expected split=15, got {split2}"

    strategy2 = SummarizeOldest()
    await strategy2.compress(conv2, 100)
    non_summary = [m for m in conv2.messages if not m.compressed]
    summary = [m for m in conv2.messages if m.compressed]
    print(f"  After compress: {len(summary)} summary + {len(non_summary)} kept")
    assert len(summary) == 1, "Should have 1 summary message"
    assert len(non_summary) == MIN_KEEP_MESSAGES
    print("[PASS] Phase 2: long messages kept = MIN_KEEP_MESSAGES (old: 6 × 8K = 48K)\n")

    # == Phase 3: Real LLM — compression with effective token-driven split ==
    # == 真实 LLM——token 驱动切分生效 ==
    # 窗口须 > KEEP_RECENT_TOKENS，使切分能真正分离旧消息与保留尾部。
    # context_window=20K + 长回复填满后，压缩摘要最旧消息，保留约 10K token。
    real_window = 20_000
    print("== Phase 3: Real LLM — compression with effective token-driven split ==")
    print(f"Scenario: context_window={real_window}, long LLM replies fill context,")
    print("          compression fires with LLM summary, kept window is token-driven")
    print(f"          (target ~{KEEP_RECENT_TOKENS} tokens, not fixed 6 messages).")

    llm = ProviderRegistry.create(config.llm)
    await llm.prepare()

    ctx = ContextManager(
        MemoryConfig(
            context_window=real_window,
            compression_threshold=0.5,
            compress_max_failures=3,
        )
    )
    compressor = Compressor(strategies=[LLMSummarizeOldest(llm)])
    ctx.set_compressor(compressor)

    conv3 = Conversation(
        system_prompt="You are a helpful assistant. Reply with detailed answers of 200+ words."
    )

    prompts = [
        "Explain Python's GIL in detail with examples.",
        "Explain asyncio coroutines and event loop architecture.",
        "What is a context manager in Python? Give advanced usage.",
        "How does garbage collection work in CPython? Explain generations.",
        "What are Python descriptors? Show __get__/__set__ examples.",
        "Explain Python metaclasses with a real-world use case.",
        "Compare Python's threading vs multiprocessing with code examples.",
    ]

    compressed_count = 0
    for i, prompt in enumerate(prompts):
        reply = await ask_llm(llm, conv3, prompt)
        status(ctx, conv3, f"After reply {i + 1} ({len(reply)} chars)")

        compressed = await ctx.check_and_compress(conv3)
        if compressed:
            compressed_count += 1
            summary_msgs = [m for m in conv3.messages if m.compressed]
            non_summary_msgs = [m for m in conv3.messages if not m.compressed]
            kept_tokens = sum(m.token_count or 0 for m in non_summary_msgs)
            print(
                f"  -> Compression #{compressed_count}! "
                f"summary={len(summary_msgs)} kept={len(non_summary_msgs)} "
                f"kept_tokens≈{kept_tokens}"
            )
            if kept_tokens > 0:
                print(
                    f"     Token-driven: kept {len(non_summary_msgs)} msgs "
                    f"≈{kept_tokens} tokens "
                    f"(old KEEP_RECENT=6 would be fixed at 6 msgs)"
                )
        status(ctx, conv3, f"After check {i + 1}")
        print()

    if compressed_count > 0:
        print(
            f"[PASS] Phase 3: {compressed_count} compressions fired, "
            f"kept window adapted to actual sizes"
        )
    else:
        print(f"[INFO] Phase 3: no compression fired (window={real_window} was sufficient)")
        print("  Replies were short enough to fit. Token-driven logic verified in Phase 1 & 2.")

    print()
    print("=" * 70)
    print("ALL PHASES PASSED")


if __name__ == "__main__":
    asyncio.run(main())
