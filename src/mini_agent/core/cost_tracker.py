"""Session cost tracking from LLM token usage.
会话成本跟踪——从 LLM token 用量按模型计价。

An EventBus subscriber: accumulates prompt/completion tokens per model from
LLMResponseEvents (main loop and SubAgents alike), prices them via the
[cost] config section, and reports budget status.
EventBus 订阅者：从 LLMResponseEvent 按模型累计输入/输出 token
（主循环和 SubAgent 都覆盖），按 [cost] 配置计价并报告预算状态。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date
from pathlib import Path

from mini_agent.models.config import CostConfig
from mini_agent.models.events import LLMResponseEvent

logger = logging.getLogger(__name__)

UNKNOWN = "(unknown)"


class CostTracker:
    """Accumulates per-model token usage and computes cost.
    按模型累计 token 用量并计算成本。

    Two time scopes: session (in-memory, resets on restart) and all-time
    (persisted to a ledger file, survives restarts; see /cost reset).
    两个时间范围：会话级（内存，重启清零）和从始至终
    （持久化到总账文件，跨重启累计；/cost reset 可清零）。
    """

    def __init__(self, config: CostConfig, ledger_path: Path | None = None) -> None:
        self._pricing: dict = config.pricing or {}
        self.budget: float = config.budget
        self.total_budget: float = config.total_budget
        self.currency: str = config.currency
        # model -> {"prompt": int, "completion": int, "calls": int}
        self.usage: dict[str, dict[str, int]] = {}
        self._ledger_path = ledger_path
        # Historical totals loaded at startup 启动时加载的历史总量
        self._baseline: dict = self._load_ledger()
        # Per-turn history (session-scoped) 逐轮历史（会话级）
        # each: {"turn": int, "prompt": int, "completion": int, "cost": float|None}
        self.turn_history: list[dict] = []
        self._turn_mark: dict[str, dict[str, int]] = {}  # usage snapshot at turn start
        self._lock = asyncio.Lock()  # guards self.usage against concurrent SubAgent events

    def attach(self, bus) -> None:
        bus.on(LLMResponseEvent, self._on_response)

    def detach(self, bus) -> None:
        bus.off(LLMResponseEvent, self._on_response)

    async def _on_response(self, event: LLMResponseEvent) -> None:
        if event.tokens_used <= 0:
            return
        model = event.model or UNKNOWN
        async with self._lock:
            rec = self.usage.setdefault(
                model,
                {
                    "prompt": 0,
                    "completion": 0,
                    "calls": 0,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
            )
            rec["prompt"] += event.prompt_tokens
            rec["completion"] += event.completion_tokens
            rec["cache_read"] += event.cache_read_input_tokens
            rec["cache_creation"] += event.cache_creation_input_tokens
            rec["calls"] += 1

    # --- pricing 计价 ---

    def cost_for(self, model: str) -> float | None:
        """Cost for one model; None if no pricing configured.
        单个模型的成本；未配置价格返回 None。"""
        price = self._pricing.get(model)
        rec = self.usage.get(model)
        if price is None or rec is None:
            return None
        return self._compute_cost(price, rec)

    @staticmethod
    def _compute_cost(price: dict, rec: dict) -> float:
        """Compute cost accounting for cache token pricing.
        计算成本，考虑缓存 token 的差异化定价（未配置缓存价则退回 input 价）。"""
        per_m_in = float(price.get("input", 0.0))
        per_m_out = float(price.get("output", 0.0))
        per_m_cache_read = float(price.get("cache_read", per_m_in))
        per_m_cache_create = float(price.get("cache_creation", per_m_in))
        cache_read = rec.get("cache_read", 0)
        cache_creation = rec.get("cache_creation", 0)
        non_cached = max(0, rec["prompt"] - cache_read - cache_creation)
        return (
            non_cached * per_m_in
            + cache_read * per_m_cache_read
            + cache_creation * per_m_cache_create
            + rec["completion"] * per_m_out
        ) / 1_000_000

    @property
    def total_cost(self) -> float:
        """Sum over models that have pricing. 只累计有价格的模型。"""
        total = 0.0
        for model in self.usage:
            c = self.cost_for(model)
            if c is not None:
                total += c
        return total

    @property
    def has_pricing(self) -> bool:
        return bool(self._pricing)

    @staticmethod
    def _level_for(ratio: float) -> str:
        if ratio >= 1.0:
            return "over"
        if ratio >= 0.8:
            return "warn"
        return "ok"

    def budget_status(self) -> tuple[float, str]:
        """Session budget status: (ratio, ok|warn|over).
        会话预算状态。"""
        if self.budget <= 0:
            return 0.0, "ok"
        ratio = self.total_cost / self.budget
        return ratio, self._level_for(ratio)

    def total_budget_status(self) -> tuple[float, str]:
        """All-time ledger budget status: (ratio, ok|warn|over).
        累计总账预算状态。"""
        if self.total_budget <= 0:
            return 0.0, "ok"
        ratio = self.all_time_cost / self.total_budget
        return ratio, self._level_for(ratio)

    # --- per-turn history 逐轮历史 ---

    def _usage_snapshot(self) -> dict[str, dict[str, int]]:
        return {m: dict(rec) for m, rec in self.usage.items()}

    def end_turn(self) -> tuple[float | None, dict[str, int]]:
        """Close the current turn: record the delta since the last mark.
        结束当前轮：记录自上次标记以来的增量。

        Returns (turn_cost_or_None, {"prompt": int, "completion": int}).
        """
        delta_prompt = 0
        delta_completion = 0
        cost: float | None = 0.0
        for model, rec in self.usage.items():
            prev = self._turn_mark.get(
                model,
                {
                    "prompt": 0,
                    "completion": 0,
                    "cache_read": 0,
                    "cache_creation": 0,
                },
            )
            dp = rec["prompt"] - prev["prompt"]
            dc = rec["completion"] - prev["completion"]
            d_cr = rec.get("cache_read", 0) - prev.get("cache_read", 0)
            d_cc = rec.get("cache_creation", 0) - prev.get("cache_creation", 0)
            delta_prompt += dp
            delta_completion += dc
            price = self._pricing.get(model)
            if price is not None and cost is not None:
                delta_rec = {
                    "prompt": dp,
                    "completion": dc,
                    "cache_read": d_cr,
                    "cache_creation": d_cc,
                }
                cost += self._compute_cost(price, delta_rec)
            elif dp or dc:
                cost = None  # some usage unpriced this turn 本轮有未定价用量
        self._turn_mark = self._usage_snapshot()
        if delta_prompt or delta_completion:
            self.turn_history.append(
                {
                    "turn": len(self.turn_history) + 1,
                    "prompt": delta_prompt,
                    "completion": delta_completion,
                    "cost": cost,
                }
            )
        return cost, {"prompt": delta_prompt, "completion": delta_completion}

    def turn_lines(self) -> list[str]:
        """Per-turn history lines for /cost turns. 逐轮历史文本行。"""
        if not self.turn_history:
            return ["  No turns yet this session. 本会话尚无对话轮次。"]
        lines = []
        for rec in self.turn_history:
            cost_str = (
                f"{self.currency}{rec['cost']:.4f}" if rec["cost"] is not None else "(no pricing)"
            )
            lines.append(
                f"  turn {rec['turn']:>3}   in {rec['prompt']:>8,} tok   "
                f"out {rec['completion']:>7,} tok   {cost_str}"
            )
        return lines

    # --- all-time ledger 从始至终总账 ---

    def _load_ledger(self) -> dict:
        empty = {"since": date.today().isoformat(), "models": {}}
        if self._ledger_path is None or not self._ledger_path.is_file():
            return empty
        try:
            data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            if isinstance(data.get("models"), dict):
                return data
        except (OSError, ValueError):
            logger.debug("ledger load failed", exc_info=True)
            pass
        return empty

    def _merged_models(self) -> dict[str, dict[str, int]]:
        """baseline + session usage, per model. 历史 + 本会话按模型合并。"""
        merged: dict[str, dict[str, int]] = {}
        for model, rec in self._baseline.get("models", {}).items():
            merged[model] = dict(rec)
        for model, rec in self.usage.items():
            m = merged.setdefault(
                model,
                {"prompt": 0, "completion": 0, "calls": 0, "cache_read": 0, "cache_creation": 0},
            )
            m["prompt"] += rec["prompt"]
            m["completion"] += rec["completion"]
            m["calls"] += rec["calls"]
            m["cache_read"] = m.get("cache_read", 0) + rec.get("cache_read", 0)
            m["cache_creation"] = m.get("cache_creation", 0) + rec.get("cache_creation", 0)
        return merged

    def flush_to_ledger(self) -> None:
        """Persist baseline + session to the ledger file (idempotent).
        把历史 + 本会话合并写入总账文件（幂等）。"""
        if self._ledger_path is None:
            return
        data = {"since": self._baseline.get("since", date.today().isoformat())}
        data["models"] = self._merged_models()
        try:
            self._ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        except OSError:
            logger.debug("ledger persist failed", exc_info=True)
            pass  # ledger failure must not break the turn 总账失败不阻断对话

    def _cost_of(self, models: dict[str, dict[str, int]]) -> float:
        total = 0.0
        for model, rec in models.items():
            price = self._pricing.get(model)
            if price is None:
                continue
            total += self._compute_cost(price, rec)
        return total

    @property
    def all_time_cost(self) -> float:
        """Ledger + session cost at current prices. 按当前价格计的总账金额。"""
        return self._cost_of(self._merged_models())

    def reset_ledger(self) -> None:
        """Wipe the all-time ledger and current session's contribution to it.
        清空总账（含本会话已计入部分）。"""
        self._baseline = {"since": date.today().isoformat(), "models": {}}
        self.usage.clear()
        if self._ledger_path is not None and self._ledger_path.is_file():
            try:
                self._ledger_path.unlink()
            except OSError:
                logger.debug("ledger delete failed", exc_info=True)
                pass

    # --- display 展示 ---

    @staticmethod
    def _wpad(text: str, width: int, align: str = ">") -> str:
        """Width-aware pad: CJK chars occupy 2 cells, so plain format specs
        misalign mixed Chinese/ASCII columns. Pad by display cells instead.
        宽度感知填充：中文占 2 格，普通格式化会让中英混排错位——按显示宽度补空格。"""
        cells = sum(2 if ord(ch) > 0x2E7F else 1 for ch in text)
        pad = max(0, width - cells)
        return (" " * pad + text) if align == ">" else (text + " " * pad)

    _RULE = "  " + "─" * 74

    def _header(self) -> str:
        return (
            "  "
            + self._wpad("模型 model", 26, "<")
            + self._wpad("请求数", 8)
            + self._wpad("输入 input", 14)
            + self._wpad("输出 output", 14)
            + self._wpad("金额 cost", 12)
        )

    def _model_lines(self, models: dict[str, dict[str, int]]) -> list[str]:
        lines = [self._header(), self._RULE]
        for model, rec in sorted(models.items()):
            price = self._pricing.get(model)
            if price is not None:
                cost = self._compute_cost(price, rec)
                cost_str = f"{self.currency}{cost:.4f}"
            else:
                cost_str = "无价格"
            lines.append(
                "  "
                + self._wpad(model, 26, "<")
                + self._wpad(str(rec["calls"]), 8)
                + self._wpad(f"{rec['prompt']:,}", 14)
                + self._wpad(f"{rec['completion']:,}", 14)
                + self._wpad(cost_str, 12)
            )
        return lines

    def summary_lines(self) -> list[str]:
        """Two-scope dashboard: session + all-time. 两区块仪表盘：会话 + 总账。"""
        lines = ["■ 本次会话 This session"]
        if not self.usage:
            lines.append("  No LLM calls yet this session. 本会话尚无 LLM 调用。")
        else:
            lines.extend(self._model_lines(self.usage))
            lines.append(self._RULE)
            total_line = f"  合计 {self.currency}{self.total_cost:.4f}"
            if self.budget > 0:
                ratio, _ = self.budget_status()
                total_line += (
                    f"    预算 {self.currency}{self.budget:.2f}（已用 {ratio * 100:.1f}%）"
                )
            lines.append(total_line)
            lines.append("  （请求数 = LLM API 调用次数——一轮对话含多次思考/工具迭代）")

        merged = self._merged_models()
        if merged and self._ledger_path is not None:
            since = self._baseline.get("since", "?")
            lines.append("")
            lines.append(f"■ 累计总账 All-time（自 {since} 起，/cost reset 清零）")
            lines.extend(self._model_lines(merged))
            lines.append(self._RULE)
            total_line = f"  合计 {self.currency}{self.all_time_cost:.4f}"
            if self.total_budget > 0:
                ratio, _ = self.total_budget_status()
                total_line += (
                    f"    总预算 {self.currency}{self.total_budget:.2f}（已用 {ratio * 100:.1f}%）"
                )
            lines.append(total_line)
        return lines
