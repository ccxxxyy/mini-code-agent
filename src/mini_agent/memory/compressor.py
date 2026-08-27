"""Compression strategies for managing context window overflow.
用于处理上下文窗口溢出的压缩策略。

Three-stage cascade:
  Stage 1: DropToolResults — abbreviate verbose tool outputs
  Stage 2: SummarizeOldest — LLM-summarize the oldest messages
  Stage 3: SlidingWindow  — keep only the most recent N messages

三级级联：
  第 1 级：DropToolResults——缩略冗长的工具输出
  第 2 级：SummarizeOldest——用 LLM 总结最旧的消息
  第 3 级：SlidingWindow——只保留最近的 N 条消息
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

from mini_agent.llm.token_counter import count_tokens
from mini_agent.models.message import Conversation, Message, Role

if TYPE_CHECKING:
    from mini_agent.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class CompressionStrategy(ABC):
    @abstractmethod
    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        """Mutate conversation.messages in-place to reduce token count.
        原地修改 conversation.messages 以减少 token 数。"""
        ...


class DropToolResults(CompressionStrategy):
    """Stage 1: Replace verbose tool outputs with short summaries.
    第 1 级：用简短摘要替换冗长的工具输出。

    Only touches tool results OUTSIDE the keep window. Truncating the tail
    the model is actively working with makes it perceive broken tools and
    spiral into ever-smaller re-reads (real-terminal verified: the model
    measured a "~300 char output cap" == MAX_TOOL_OUTPUT + notice line,
    burned 36 iterations working around its own compressor).
    只处理保留窗口之外的工具结果。截断模型正在使用的尾部结果会让它以为
    工具坏了，陷入越读越小的重读螺旋（真实终端实测：模型量出"输出上限
    约 300 字符"== MAX_TOOL_OUTPUT + 说明行，烧 36 轮迭代绕自家压缩器）。
    """

    MAX_TOOL_OUTPUT = 200

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        split = _compute_keep_split(msgs, target_tokens)
        for msg in msgs[:split]:
            if msg.role == Role.TOOL and msg.tool_result and not msg.compressed:
                output = msg.tool_result.output
                if len(output) > self.MAX_TOOL_OUTPUT:
                    lines = output.count("\n") + 1
                    chars = len(output)
                    short = (
                        output[: self.MAX_TOOL_OUTPUT]
                        + f"\n... ({lines} lines, {chars} chars total, truncated)"
                    )
                    msg.tool_result = msg.tool_result.__class__(
                        call_id=msg.tool_result.call_id,
                        name=msg.tool_result.name,
                        output=short,
                        is_error=msg.tool_result.is_error,
                        metadata=msg.tool_result.metadata,
                    )
                    msg.content = short
                    msg.token_count = None  # force recount
                    msg.compressed = True


class SummarizeOldest(CompressionStrategy):
    """Stage 2: Summarize the oldest portion of messages into one summary message.
    第 2 级：把最旧的一批消息总结成一条摘要消息。

    Uses a simple extractive approach (no LLM call — keeps it fast
    and avoids recursive API calls). A full LLM-based summary can be
    plugged in later.

    使用简单的抽取式方法（不调用 LLM——保持速度快并避免递归 API 调用）。
    以后可以接入完整的基于 LLM 的摘要。
    """

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        if len(msgs) <= MIN_KEEP_MESSAGES:
            return

        split = _align_split_to_tool_pair(msgs, _compute_keep_split(msgs, target_tokens))
        if split <= 0:
            return

        if _prefix_tokens(msgs[:split]) < MIN_SUMMARIZE_PREFIX_TOKENS:
            return

        to_summarize = msgs[:split]
        kept = msgs[split:]

        summary_text = (
            "[Compressed conversation history -- this is the authoritative "
            "record of earlier conversation. Do NOT search session files or "
            "disk to recover history; use this summary.]\n" + _extractive_digest(to_summarize)
        )
        conversation.messages = [_make_summary_message(summary_text)] + kept


def _align_split_to_tool_pair(msgs: list[Message], split: int) -> int:
    """Move the keep-start backward so it never lands on a tool result whose
    tool_use (assistant tool_calls message) would be summarized away --
    an orphan tool result makes the API reject the request with a 400.
    把 keep 起点向前移，避免落在 tool result 上而其对应的 tool_use
    （assistant 的 tool_calls 消息）被摘要掉——孤儿 tool result 会导致 API 400。
    """
    while 0 < split < len(msgs) and msgs[split].role == Role.TOOL:
        split -= 1
    return split


# Token-driven keep window constants
KEEP_RECENT_TOKENS = 10_000  # minimum tokens to keep from the tail 尾部最少保留 token 数
MIN_KEEP_MESSAGES = 5  # always keep at least this many messages 最少保留消息数
KEEP_MAX_TOKENS = 40_000  # hard cap on kept tokens 保留 token 硬顶
MIN_SUMMARIZE_PREFIX_TOKENS = 2_000  # skip if prefix < this 前缀不足时跳过压缩

# Recovery-attachment markers appended to summary messages by
# ContextManager._inject_read_files (shared so both sides stay in sync).
# ContextManager._inject_read_files 追加到摘要消息的恢复附件标记（共享防不同步）。
RECOVERY_MARKERS = ("[User's most recent request", "[Files already read")


def _prefix_tokens(msgs: list[Message]) -> int:
    return sum(m.token_count or count_tokens(m.content) for m in msgs)


def _compute_keep_split(msgs: list[Message], target_tokens: int) -> int:
    """Token-driven split: msgs[split:] are kept, msgs[:split] are summarized.
    从尾部反向扫描累计 token，满足最少消息数后达到 token 阈值即停。

    Stop conditions (from tail, scanning backward):
    - accumulated >= keep floor AND count >= MIN_KEEP_MESSAGES
    - accumulated would exceed the keep cap (hard cap)

    Floor/cap scale down with target_tokens: with a small context window the
    absolute floor (10K) can equal or exceed the target, making summarization
    mathematically unable to reach it -- observed at window=10K: the hard
    threshold fired every iteration and all work fell to SlidingWindow.
    下限/硬顶随 target_tokens 缩放：小窗口下绝对下限（10K）可能不小于压缩目标，
    摘要级数学上永远达不到目标——实测 window=10K 时硬阈值每轮触发，
    压缩全部退化为 SlidingWindow 截断。
    """
    if len(msgs) <= MIN_KEEP_MESSAGES:
        return 0

    keep_recent = min(KEEP_RECENT_TOKENS, target_tokens // 2)
    keep_max = min(KEEP_MAX_TOKENS, target_tokens)

    running_tokens = 0
    keep_count = 0

    for i in range(len(msgs) - 1, -1, -1):
        msg = msgs[i]
        cost = msg.token_count or count_tokens(msg.content or "") + 4
        if running_tokens + cost > keep_max:
            break
        running_tokens += cost
        keep_count += 1
        if keep_count >= MIN_KEEP_MESSAGES and running_tokens >= keep_recent:
            break

    # Never summarize away the entire tail -- the newest message may alone
    # exceed the cap; losing it would erase the task in progress.
    # 绝不把尾部全部摘要掉——最新一条可能单独超硬顶，丢了它就丢了进行中的任务。
    if keep_count == 0:
        keep_count = 1

    split = len(msgs) - keep_count
    return max(split, 0)


def _extractive_digest(messages: list[Message]) -> str:
    """Mechanical digest: role + content snippet per message.
    机械式摘要：每条消息取角色 + 内容片段。"""
    parts: list[str] = []
    for msg in messages:
        role = msg.role.value
        if msg.compressed and msg.role == Role.SYSTEM and msg.content:
            # A previous compression summary is already dense -- truncating it
            # to 300 chars makes each re-compression a "summary of a mangled
            # summary", compounding detail loss (observed in real-terminal
            # verification: final boundary said "the full request is unknown").
            # 旧压缩摘要本身已是浓缩产物——砍到 300 字符会让每次二次压缩变成
            # "残缺摘要的摘要"，细节损失复利叠加（真实终端验证实测：最终边界
            # 自述"完整请求未知"）。整条传递，由 MAX_HISTORY_CHARS 统一封顶。
            text = msg.content
            # BUT strip the recovery attachment first: _inject_read_files bakes
            # up to ~17K chars of file contents onto the summary message, and
            # re-digesting that drowns the actual history -- real-terminal
            # verified: planted conventions (~500 chars) buried under source
            # dumps were dropped by the next summarization. The attachment is
            # re-injected after every compression anyway, so nothing is lost.
            # 但要先剥离恢复附件：_inject_read_files 会把 ~17K 字符的文件内容
            # 烤到摘要消息上，再次进 digest 会淹没真正的历史——真实终端实测：
            # 约 500 字符的埋点约定被源码转储淹没后遭下一次摘要丢弃。附件在
            # 每次压缩后都会重新注入，剥离不损失任何信息。
            cuts = [i for m in RECOVERY_MARKERS if (i := text.find(m)) != -1]
            if cuts:
                text = text[: min(cuts)].rstrip()
            if text:
                parts.append(text)
        elif msg.content:
            text = msg.content[:300]
            parts.append(f"[{role}] {text}")
        elif msg.tool_calls:
            names = ", ".join(tc.name for tc in msg.tool_calls)
            parts.append(f"[{role}] called tools: {names}")
        elif msg.tool_result:
            status = "error" if msg.tool_result.is_error else "ok"
            parts.append(f"[{role}] {msg.tool_result.name} → {status}")
    return "\n".join(parts)


def _make_summary_message(summary_text: str) -> Message:
    msg = Message(role=Role.SYSTEM, content=summary_text, compressed=True)
    msg.token_count = count_tokens(summary_text) + 4
    return msg


_SUMMARY_PROMPT = """Your task is to create a detailed summary of the conversation history below \
between a user and a coding agent, paying close attention to the user's explicit requests and the \
agent's actions. Recent messages are kept verbatim elsewhere; this summary replaces only the older \
history, so it must capture every technical detail needed to continue work without losing context.

The history may itself contain earlier compression summaries (blocks starting with "[Compressed \
conversation history"). Their contents are authoritative history, NOT noise: every convention, \
decision, constraint, and user instruction recorded inside them MUST be carried forward into \
your summary -- dropping them loses information permanently.

Before providing your final summary, wrap your analysis in <analysis> tags to organize your \
thoughts and ensure you've covered all necessary points. Keep the analysis BRIEF -- a compact \
bullet list, not prose; spend your output budget on the <summary> block. In your analysis:
1. Chronologically go through each message and identify:
   - The user's explicit requests and intents
   - The agent's approach to addressing them
   - Key decisions, technical concepts and code patterns
   - Specific details: file names, code snippets, function signatures, file edits
   - Errors encountered and how they were fixed, especially user feedback asking to do \
something differently
2. Double-check for technical accuracy and completeness.

After your analysis, output your final summary wrapped in <summary> tags, with these sections:

1. Primary Request and Intent: all of the user's explicit requests and intents, in detail
2. Key Technical Concepts: important technical concepts, technologies, and frameworks discussed
3. Files and Code Sections: specific files and code sections examined, modified, or created; \
why each matters, with code snippets where available
4. Errors and Fixes: errors encountered and how they were fixed, including any user feedback
5. Problem Solving: problems solved and ongoing troubleshooting efforts
6. All User Messages: ALL user messages that are not tool results -- critical for tracking \
feedback and changing intent
7. Pending Tasks: tasks explicitly requested but not yet done
8. Current Work: precisely what was being worked on in the most recent messages of this history
9. Optional Next Step: the next step DIRECTLY in line with the user's most recent explicit \
request, if any; quote the relevant messages verbatim to avoid drift

Be factual and dense. Output only the <analysis> block followed by the <summary> block.

Conversation history:
{history}"""


def _extract_summary(llm_output: str) -> str:
    """Extract the <summary> block content; fall back to the full output if
    the tags are missing (model ignored the format -- still usable text).
    提取 <summary> 块内容；缺少标签时回退到完整输出（模型没按格式输出，文本仍可用）。
    """
    start = llm_output.find("<summary>")
    end = llm_output.find("</summary>")
    if start != -1:
        if end != -1:
            return llm_output[start + len("<summary>") : end].strip()
        # Opened but never closed (output truncated mid-summary): salvage the
        # partial summary -- it still beats the extractive digest.
        # 开了标签没闭合（输出在 summary 中途截断）：抢救部分摘要——仍远好于抽取式。
        return llm_output[start + len("<summary>") :].strip()
    # No <summary> tag at all (e.g. truncated mid-analysis): strip the
    # <analysis> scratchpad so it never leaks; empty result triggers the
    # extractive fallback upstream.
    # 完全没有 <summary> 标签（如截断在 analysis 中途）：剥离 <analysis> 草稿
    # 防止泄漏；结果为空会触发上游的抽取式回退。
    a_start = llm_output.find("<analysis>")
    if a_start != -1:
        a_end = llm_output.find("</analysis>")
        tail = llm_output[a_end + len("</analysis>") :] if a_end != -1 else ""
        llm_output = llm_output[:a_start] + tail
    return llm_output.strip()


# Error-message markers that indicate the request itself was too large.
# Keyword fallback for providers that wrap errors in plain exceptions.
# 指示请求本身过大的错误消息关键词——用于兜底识别包装过的异常。
_TOO_LONG_MARKERS = (
    "context length",
    "context_length",
    "too long",
    "too many tokens",
    "maximum context",
    "input length",
    "prompt tokens",
)


def _is_prompt_too_long(exc: BaseException) -> bool:
    """Whether the summarize call failed because the prompt was too large.
    判断摘要调用是否因 prompt 过大失败。

    Any 400/413 counts: in streaming mode the error body is often unreadable
    (httpx ResponseNotRead), and a summarize request is fixed-format -- a 400
    is almost always length. Misjudging costs at most a few bounded retries
    before the extractive fallback, never a crash.
    400/413 一律算：流式模式下错误响应体常不可读（httpx ResponseNotRead），
    而摘要请求格式固定——400 几乎必是长度问题。误判最多多花几次有界重试
    后落抽取式回退，不会崩溃。
    """
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (400, 413):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _TOO_LONG_MARKERS)


class LLMSummarizeOldest(CompressionStrategy):
    """Stage 2 (LLM variant): semantically summarize the oldest messages via LLM.
    第 2 级（LLM 变体）：用 LLM 对最旧的消息做语义摘要。

    Falls back to the extractive digest if the LLM call fails -- the
    compression chain must never break on a network error.
    LLM 调用失败时回退到抽取式摘要——压缩链绝不能因网络错误中断。
    """

    MAX_HISTORY_CHARS = 24_000  # cap the summarization request size 限制摘要请求的大小
    # Output budget for the summarize call: hybrid reasoning models (e.g.
    # DeepSeek) burn thousands of tokens in reasoning_content before the
    # visible answer -- the default 4096 gets truncated mid-summary.
    # 摘要调用的输出预算：混合推理模型（如 DeepSeek）先在 reasoning_content
    # 烧几千 token 才输出正文——默认 4096 会截断在 summary 中途。
    SUMMARY_MAX_TOKENS = 8192
    SUMMARY_RETRIES = 2  # attempts before extractive fallback 回退前的尝试次数
    # Prompt-too-long recovery (separate budget from transient retries):
    # drop the oldest 20% of summarizable messages AND shrink the char cap
    # 20% per round. The message drop follows mewcode semantics (oldest is
    # least valuable); the cap shrink guarantees the request actually gets
    # smaller even while the digest still exceeds the cap.
    # prompt 超长恢复（与偶发失败重试预算独立）：每轮丢弃最旧 20% 的可摘要
    # 消息并把字符 cap 缩 20%。丢消息沿用 mewcode 语义（最旧价值最低）；
    # 缩 cap 保证 digest 仍超 cap 时请求也确实变小。
    MAX_SHRINKS = 3  # shrink-and-retry rounds before giving up 收缩重试轮数上限
    SHRINK_KEEP_RATIO = 0.8  # keep 80%, drop oldest 20% 保留 80%，丢最旧 20%

    def __init__(self, llm: LLMProvider) -> None:
        self._llm = llm

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        msgs = conversation.messages
        if len(msgs) <= MIN_KEEP_MESSAGES:
            return

        split = _align_split_to_tool_pair(msgs, _compute_keep_split(msgs, target_tokens))
        if split <= 0:
            return

        if _prefix_tokens(msgs[:split]) < MIN_SUMMARIZE_PREFIX_TOKENS:
            return

        to_summarize = msgs[:split]
        kept = msgs[split:]

        digest = _extractive_digest(to_summarize)
        summary_text = None
        # Retry before falling back: transient empty summaries occurred once
        # per real-terminal session -- a single retry usually recovers, and
        # the extractive fallback loses the 9-section structure.
        # 回退前先重试：真实终端会话几乎每场出现一次偶发空摘要——重试一次
        # 通常就能恢复，而抽取式回退会丢掉 9 节结构。
        cap = self.MAX_HISTORY_CHARS
        attempt = 0
        shrinks = 0
        while attempt < self.SUMMARY_RETRIES:
            try:
                summary = await self._summarize(digest[:cap])
                summary_text = (
                    "[Compressed conversation history (LLM summary) -- this is the "
                    "authoritative record of earlier conversation. Do NOT search "
                    "session files or disk to recover history; use this summary.]\n" + summary
                )
                break
            except Exception as e:
                if _is_prompt_too_long(e):
                    if shrinks >= self.MAX_SHRINKS:
                        # Retrying the identical oversized request fails
                        # identically -- real-run verified (Aliyun MaaS: two
                        # extra 400s on the same 6.1M-char prompt). Fall back.
                        # 相同的超长请求重试必然相同失败——真实运行实测
                        # （阿里云 MaaS：同一 6.1M 字符 prompt 白吃两次 400）。
                        # 直接回退。
                        logger.warning(
                            "summary prompt still too long after %d shrinks, "
                            "falling back to extractive digest",
                            shrinks,
                        )
                        break
                    shrinks += 1
                    to_summarize, dropped = self._shrink_oldest(to_summarize)
                    cap = int(cap * self.SHRINK_KEEP_RATIO)
                    digest = _extractive_digest(to_summarize)
                    logger.warning(
                        "summary prompt too long (%s: %s), dropped oldest %d message(s), "
                        "cap -> %d chars, shrink retry %d/%d",
                        type(e).__name__,
                        e,
                        dropped,
                        cap,
                        shrinks,
                        self.MAX_SHRINKS,
                    )
                    continue
                attempt += 1
                logger.warning(
                    "LLM summarization attempt %d/%d failed (%s: %s)",
                    attempt,
                    self.SUMMARY_RETRIES,
                    type(e).__name__,
                    e,
                )
        if summary_text is None:
            logger.warning("LLM summarization exhausted retries, using extractive digest")
            summary_text = (
                "[Compressed conversation history -- this is the authoritative "
                "record of earlier conversation. Do NOT search session files or "
                "disk to recover history; use this summary.]\n" + digest
            )

        conversation.messages = [_make_summary_message(summary_text)] + kept

    def _shrink_oldest(self, msgs: list[Message]) -> tuple[list[Message], int]:
        """Drop the oldest ~20% of summarizable messages -- but never a prior
        compression summary at the head: it is the sole record of ALL earlier
        history, and losing it repeats the 300-char-truncation failure where
        the boundary ended up saying "the full request is unknown".
        丢弃最旧约 20% 的可摘要消息——但绝不丢头部的旧压缩摘要：它是更早
        全部历史的唯一记录，丢了就重演 300 字符截断的失败（最终边界自述
        "完整请求未知"）。

        Dropped messages are replaced by the summary along with everything
        else -- they just go unrepresented in the summary text (mewcode
        accepts the same loss; we are out of space).
        被丢弃的消息和其余消息一样被摘要替换——只是不再体现在摘要文本里
        （mewcode 接受同样的损失；空间已经不够了）。
        """
        start = 1 if (msgs and msgs[0].compressed and msgs[0].role == Role.SYSTEM) else 0
        droppable = len(msgs) - start
        if droppable <= 1:
            return msgs, 0  # cap shrink alone still makes progress 仅靠缩 cap 也能推进
        drop = max(1, droppable - int(droppable * self.SHRINK_KEEP_RATIO))
        return msgs[:start] + msgs[start + drop :], drop

    async def _summarize(self, history: str) -> str:
        # One-shot direct LLM call, bypasses AgentLoop -- no recursion risk.
        # 一次性直连 LLM 调用，不经过 AgentLoop——无递归风险。
        from mini_agent.llm.base import complete

        messages = [{"role": "user", "content": _SUMMARY_PROMPT.format(history=history)}]
        response = await complete(self._llm, messages, max_tokens=self.SUMMARY_MAX_TOKENS)
        summary = _extract_summary(response.content)
        if not summary:
            raise ValueError("empty summary from LLM")
        return summary


class SlidingWindow(CompressionStrategy):
    """Stage 3: Keep only messages that fit within target_tokens (last resort).
    第 3 级：只保留能放进 target_tokens 预算内的消息（最后手段）。"""

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        system_cost = count_tokens(conversation.system_prompt) if conversation.system_prompt else 0
        budget = target_tokens - system_cost

        kept: list[Message] = []
        running = 0
        for msg in reversed(conversation.messages):
            cost = msg.token_count or count_tokens(msg.content or "") + 4
            if running + cost > budget:
                break
            kept.append(msg)
            running += cost
        kept.reverse()

        # Orphan guard: the token cut may land mid tool-pair, leaving tool
        # results whose tool_use was dropped. Extending backward would blow
        # the budget, so drop the orphans instead.
        # 孤儿防护：按 token 切分可能切在工具对中间，留下 tool_use 已被丢弃的
        # tool result。向前扩会超预算，所以直接丢弃孤儿。
        while kept and kept[0].role == Role.TOOL:
            kept.pop(0)

        # Task anchor: NEVER drop the latest user message. A long turn (one
        # question + dozens of tool results) can push the question itself out
        # of the window -- the LLM then finishes reading and asks "what did
        # you want?" because the task is gone.
        # 任务锚点：绝不丢弃最近一条用户消息。长轮次（一个提问 + 几十条工具
        # 结果）会把提问本身挤出窗口——LLM 读完文件后反问"你要我做什么"，
        # 因为任务没了。
        if not any(m.role == Role.USER for m in kept):
            for msg in reversed(conversation.messages):
                if msg.role == Role.USER:
                    kept.insert(0, msg)
                    break

        # Summary anchor: the compression summary sits at the HEAD, so
        # tail-based truncation drops it first -- destroying the entire
        # compressed history the previous stage just paid an LLM call to
        # preserve (full-pipeline verified: the summary held all planted
        # conventions and SlidingWindow deleted exactly that message).
        # 摘要锚点：压缩摘要位于头部，按尾部保留的截断会最先丢掉它——
        # 上一级刚花一次 LLM 调用保住的全部历史被销毁（全管道实测：
        # 摘要完整保住了埋点约定，而 SlidingWindow 恰好删掉这一条）。
        if not any(m.role == Role.SYSTEM and m.compressed for m in kept):
            for msg in conversation.messages:
                if msg.role == Role.SYSTEM and msg.compressed and msg.content:
                    kept.insert(0, msg)
                    break

        conversation.messages = kept


class Compressor:
    """Runs compression strategies in cascade until target is met.
    级联运行各压缩策略，直到达到目标。"""

    def __init__(
        self,
        strategies: list[CompressionStrategy] | None = None,
    ) -> None:
        self._strategies = strategies or [
            DropToolResults(),
            SummarizeOldest(),
            SlidingWindow(),
        ]

    async def compress(self, conversation: Conversation, target_tokens: int) -> None:
        for strategy in self._strategies:
            # Recount after each stage
            total = sum(
                m.token_count or count_tokens(m.content or "") + 4 for m in conversation.messages
            )
            if total <= target_tokens:
                break
            await strategy.compress(conversation, target_tokens)
            # Record boundary after each stage (SlidingWindow may drop
            # the summary created by SummarizeOldest, so capture early)
            # 每个阶段后记录边界（SlidingWindow 可能丢弃 SummarizeOldest 创建的摘要）
            for msg in conversation.messages:
                if msg.compressed and msg.role == Role.SYSTEM and msg.content:
                    conversation.compact_boundary = {
                        "summary": msg.content,
                        "timestamp": datetime.now().isoformat(),
                    }
                    break


async def summarize_conversation(llm: LLMProvider, messages: list[Message]) -> str:
    """One-shot summary of a conversation for context inheritance.
    Used by fork-style sub-agent spawning: the summary is injected into the
    sub-agent's system prompt as a frozen snapshot of the parent discussion.
    Falls back to the extractive digest if the LLM call fails -- a fork must
    never fail because summarization failed.
    对话的一次性摘要，供摘要式 fork 使用（注入子 Agent system prompt 的冻结
    快照）。LLM 失败时回退提取式 digest——fork 绝不因摘要失败而失败。
    """
    digest = _extractive_digest(messages)
    # Keep the most recent discussion when clipping 截断时保留最近的讨论
    clipped = digest[-LLMSummarizeOldest.MAX_HISTORY_CHARS :]
    try:
        return await LLMSummarizeOldest(llm)._summarize(clipped)
    except Exception:
        return clipped
