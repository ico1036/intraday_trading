"""Cross-sectional vol-adjusted momentum (daily rebalance).

Score per symbol = trailing_return / trailing_rv over a multi-day window.
Rank cross-sectionally; top-k long, bottom-k short. Rebalance once per day.
Signal flip → reverse via the next rebalance.
"""
from __future__ import annotations

from collections import deque
from math import sqrt
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "vol_adjusted_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/vol_adjusted_momentum.md"]


class VolAdjustedMomentumDailyStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 2880,   # 48h on 1m bars
        rv_bars: int = 1440,         # 24h
        rebalance_bars: int = 1440,  # 24h
        top_k: int = 2,
        max_weight: float = 0.18,
        min_score: float = 0.05,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(5, int(lookback_bars))
        self.rv_bars = max(5, int(rv_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.min_score = float(min_score)

        max_hist = max(self.lookback_bars, self.rv_bars) + 5
        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=max_hist) for s in self.symbols
        }
        self._bar_count = 0

    def _score(self, closes: list[float]) -> float | None:
        if len(closes) < self.lookback_bars + 1 or len(closes) < self.rv_bars + 1:
            return None
        ret = (closes[-1] - closes[-self.lookback_bars - 1]) / closes[-self.lookback_bars - 1]
        rv_seg = closes[-self.rv_bars - 1:]
        rets = []
        for prev, cur in zip(rv_seg[:-1], rv_seg[1:]):
            rets.append((cur - prev) / prev if prev > 0 else 0.0)
        if len(rets) < 5:
            return None
        sigma = pstdev(rets) or 1e-9
        # annualize-like scale: per-bar sigma × sqrt(rv_bars)
        return ret / (sigma * sqrt(self.rv_bars))

    def _current_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_for_side(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None
        for s in self.symbols:
            data = state.panel.get(s)
            if not data:
                continue
            close = data.get("close")
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        scores: dict[str, float] = {}
        for s in self.symbols:
            sc = self._score(list(self._closes[s]))
            if sc is not None:
                scores[s] = sc
        if len(scores) < 2:
            return None

        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        # Strongest momentum (top) → LONG; weakest (bottom) → SHORT
        long_pick = [s for s, v in ranked[-self.top_k:] if v > self.min_score]
        short_pick = [s for s, v in ranked[: self.top_k] if v < -self.min_score]

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            if s in long_pick:
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif s in short_pick:
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=self.max_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            else:
                orders[s] = self._close_for_side(cur)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
