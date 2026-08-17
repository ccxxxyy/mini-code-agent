"""Tests for session cost tracking. 会话成本跟踪测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from mini_agent.core.cost_tracker import CostTracker
from mini_agent.models.config import CostConfig
from mini_agent.models.events import LLMResponseEvent

pytestmark = pytest.mark.asyncio


def make_tracker(pricing: dict | None = None, budget: float = 0.0) -> CostTracker:
    return CostTracker(CostConfig(pricing=pricing or {}, budget=budget))


async def emit(tracker, model: str, prompt: int, completion: int):
    await tracker._on_response(
        LLMResponseEvent(
            tokens_used=prompt + completion,
            prompt_tokens=prompt,
            completion_tokens=completion,
            model=model,
        )
    )


# --- accumulation 累计 ---


async def test_accumulates_per_model():
    t = make_tracker()
    await emit(t, "m1", 1000, 200)
    await emit(t, "m1", 500, 100)
    await emit(t, "m2", 300, 50)

    assert t.usage["m1"] == {
        "prompt": 1500,
        "completion": 300,
        "calls": 2,
        "cache_read": 0,
        "cache_creation": 0,
    }
    assert t.usage["m2"] == {
        "prompt": 300,
        "completion": 50,
        "calls": 1,
        "cache_read": 0,
        "cache_creation": 0,
    }


async def test_empty_model_goes_to_unknown():
    t = make_tracker()
    await emit(t, "", 100, 10)
    assert "(unknown)" in t.usage


async def test_zero_usage_ignored():
    t = make_tracker()
    await t._on_response(LLMResponseEvent(tokens_used=0, model="m1"))
    assert not t.usage


# --- pricing 计价 ---


async def test_cost_formula():
    t = make_tracker(pricing={"m1": {"input": 2.0, "output": 8.0}})
    await emit(t, "m1", 1_000_000, 500_000)

    # 1M input * 2/M + 0.5M output * 8/M = 2 + 4 = 6
    assert t.cost_for("m1") == pytest.approx(6.0)
    assert t.total_cost == pytest.approx(6.0)


async def test_no_pricing_returns_none():
    t = make_tracker()
    await emit(t, "m1", 1000, 100)
    assert t.cost_for("m1") is None
    assert t.total_cost == 0.0
    assert not t.has_pricing


async def test_mixed_priced_and_unpriced():
    t = make_tracker(pricing={"m1": {"input": 1.0, "output": 1.0}})
    await emit(t, "m1", 1_000_000, 0)
    await emit(t, "m2", 9_999_999, 9_999_999)  # unpriced 未定价

    assert t.total_cost == pytest.approx(1.0)  # m2 not counted m2 不计入


# --- budget 预算 ---


async def test_budget_status_levels():
    t = make_tracker(pricing={"m": {"input": 1.0, "output": 0.0}}, budget=1.0)

    ratio, level = t.budget_status()
    assert level == "ok"

    await emit(t, "m", 850_000, 0)  # 0.85 -> warn
    ratio, level = t.budget_status()
    assert level == "warn"
    assert ratio == pytest.approx(0.85)

    await emit(t, "m", 200_000, 0)  # 1.05 -> over
    _, level = t.budget_status()
    assert level == "over"


async def test_no_budget_always_ok():
    t = make_tracker(pricing={"m": {"input": 100.0, "output": 100.0}}, budget=0.0)
    await emit(t, "m", 5_000_000, 5_000_000)
    _, level = t.budget_status()
    assert level == "ok"


# --- summary 摘要 ---


async def test_summary_lines():
    t = make_tracker(pricing={"m1": {"input": 2.0, "output": 8.0}}, budget=5.0)
    await emit(t, "m1", 10_000, 2_000)

    text = "\n".join(t.summary_lines())
    assert "m1" in text
    assert "10,000" in text
    assert "合计" in text
    assert "预算" in text


# --- integration 集成 ---


class UsageLLM:
    """MockLLM emitting usage data. 带 usage 的 MockLLM。"""

    async def stream(self, messages, tools=None, **kwargs: Any) -> AsyncIterator[Any]:
        from mini_agent.llm.base import StreamChunk, TokenUsage

        yield StreamChunk(delta="hi")
        yield StreamChunk(
            finish_reason="stop",
            usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    @property
    def context_window(self) -> int:
        return 128_000


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    return Application(ConfigLoader.load())


async def test_turn_records_model_usage(app):
    from mini_agent.models.message import Conversation, Message, Role

    app.agent_loop._llm = UsageLLM()
    app.agent_loop.model_name = "test-model-x"

    conv = Conversation(system_prompt="t")
    conv.append(Message(role=Role.USER, content="hi"))
    await app.agent_loop.run(conv)

    assert "test-model-x" in app.cost_tracker.usage
    rec = app.cost_tracker.usage["test-model-x"]
    assert rec["prompt"] == 100
    assert rec["completion"] == 20


async def test_cost_command_output(app):
    from mini_agent.models.events import LLMResponseEvent

    await app.cost_tracker._on_response(
        LLMResponseEvent(tokens_used=120, prompt_tokens=100, completion_tokens=20, model="mx")
    )
    result = await app.slash_commands.execute("/cost")
    assert "Cost Dashboard" in result
    assert "mx" in result
    assert "no pricing" in result  # default config has no pricing 默认无价格配置


async def test_status_has_cost_line(app):
    result = await app.slash_commands.execute("/status")
    assert "Cost:" in result


# --- all-time ledger 总账 ---


def make_ledger_tracker(tmp_path, pricing: dict | None = None) -> CostTracker:
    return CostTracker(CostConfig(pricing=pricing or {}), ledger_path=tmp_path / "ledger.json")


async def test_flush_writes_and_reloads(tmp_path):
    t1 = make_ledger_tracker(tmp_path)
    await emit(t1, "m1", 1000, 200)
    t1.flush_to_ledger()

    t2 = make_ledger_tracker(tmp_path)  # new session 新会话
    merged = t2._merged_models()
    assert merged["m1"]["prompt"] == 1000
    assert merged["m1"]["completion"] == 200
    assert merged["m1"]["calls"] == 1
    assert not t2.usage  # session scope is fresh 会话级是全新的


async def test_flush_idempotent(tmp_path):
    t = make_ledger_tracker(tmp_path)
    await emit(t, "m1", 500, 100)
    t.flush_to_ledger()
    t.flush_to_ledger()  # second flush must not double 第二次 flush 不翻倍

    t2 = make_ledger_tracker(tmp_path)
    assert t2._merged_models()["m1"]["prompt"] == 500


async def test_cross_session_accumulation(tmp_path):
    t1 = make_ledger_tracker(tmp_path)
    await emit(t1, "m1", 1000, 0)
    t1.flush_to_ledger()

    t2 = make_ledger_tracker(tmp_path)
    await emit(t2, "m1", 2000, 0)
    t2.flush_to_ledger()

    t3 = make_ledger_tracker(tmp_path)
    assert t3._merged_models()["m1"]["prompt"] == 3000
    assert t3._merged_models()["m1"]["calls"] == 2


async def test_all_time_cost_uses_current_prices(tmp_path):
    t1 = make_ledger_tracker(tmp_path)
    await emit(t1, "m1", 1_000_000, 0)
    t1.flush_to_ledger()

    # New session with pricing configured 新会话配了价格
    t2 = make_ledger_tracker(tmp_path, pricing={"m1": {"input": 2.0, "output": 0.0}})
    assert t2.all_time_cost == pytest.approx(2.0)


async def test_reset_ledger(tmp_path):
    t = make_ledger_tracker(tmp_path)
    await emit(t, "m1", 1000, 0)
    t.flush_to_ledger()
    t.reset_ledger()

    assert not (tmp_path / "ledger.json").exists()
    assert t._merged_models() == {}


async def test_total_budget_status(tmp_path):
    t = CostTracker(
        CostConfig(pricing={"m": {"input": 1.0, "output": 0.0}}, total_budget=1.0),
        ledger_path=tmp_path / "ledger.json",
    )
    _, level = t.total_budget_status()
    assert level == "ok"

    await emit(t, "m", 900_000, 0)  # 0.9 -> warn
    ratio, level = t.total_budget_status()
    assert level == "warn"

    await emit(t, "m", 200_000, 0)  # 1.1 -> over
    _, level = t.total_budget_status()
    assert level == "over"


async def test_total_budget_includes_history(tmp_path):
    t1 = CostTracker(
        CostConfig(pricing={"m": {"input": 1.0, "output": 0.0}}),
        ledger_path=tmp_path / "ledger.json",
    )
    await emit(t1, "m", 700_000, 0)
    t1.flush_to_ledger()

    # New session: history 0.7 + session 0.4 = 1.1 over a 1.0 total budget
    # 新会话：历史 0.7 + 本会话 0.4 = 1.1，超 1.0 总预算
    t2 = CostTracker(
        CostConfig(pricing={"m": {"input": 1.0, "output": 0.0}}, total_budget=1.0),
        ledger_path=tmp_path / "ledger.json",
    )
    await emit(t2, "m", 400_000, 0)
    _, level = t2.total_budget_status()
    assert level == "over"


async def test_summary_has_all_time_block(tmp_path):
    t = make_ledger_tracker(tmp_path)
    await emit(t, "m1", 100, 10)
    t.flush_to_ledger()

    text = "\n".join(t.summary_lines())
    assert "This session" in text
    assert "All-time" in text


# --- per-turn history 逐轮历史 ---


async def test_end_turn_records_delta():
    t = make_tracker(pricing={"m": {"input": 1.0, "output": 2.0}})
    await emit(t, "m", 1000, 500)
    cost, delta = t.end_turn()

    assert delta == {"prompt": 1000, "completion": 500}
    assert cost == pytest.approx((1000 * 1.0 + 500 * 2.0) / 1_000_000)
    assert len(t.turn_history) == 1


async def test_end_turn_delta_not_cumulative():
    t = make_tracker(pricing={"m": {"input": 1.0, "output": 0.0}})
    await emit(t, "m", 1000, 0)
    t.end_turn()
    await emit(t, "m", 3000, 0)
    cost, delta = t.end_turn()

    # second turn only counts its own usage 第二轮只计自己的增量
    assert delta["prompt"] == 3000
    assert t.turn_history[1]["prompt"] == 3000


async def test_end_turn_empty_not_recorded():
    t = make_tracker()
    t.end_turn()  # no usage 无用量
    assert t.turn_history == []


async def test_turn_lines_output():
    t = make_tracker(pricing={"m": {"input": 1.0, "output": 1.0}})
    await emit(t, "m", 500, 100)
    t.end_turn()

    text = "\n".join(t.turn_lines())
    assert "turn   1" in text
    assert "500" in text


async def test_cost_turns_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from mini_agent.app import Application
    from mini_agent.config.loader import ConfigLoader

    app = Application(ConfigLoader.load())
    await emit(app.cost_tracker, "mx", 100, 20)
    app.cost_tracker.end_turn()

    result = await app.slash_commands.execute("/cost turns")
    assert "Per-turn Cost" in result
    assert "turn   1" in result


async def test_toml_cost_section_merges(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    cfg_dir = tmp_path / ".mini-agent"
    cfg_dir.mkdir()
    (cfg_dir / "config.toml").write_text(
        "[cost]\nbudget = 3.5\n[cost.pricing.deepseek-chat]\ninput = 2.0\noutput = 8.0\n",
        encoding="utf-8",
    )

    from mini_agent.config.loader import ConfigLoader

    config = ConfigLoader.load()
    assert config.cost.budget == 3.5
    assert config.cost.pricing["deepseek-chat"]["input"] == 2.0
