"""Cross-sectional vol dispersion with neutral-zone exit.

Same family as is_019 (vol_dispersion_xs intraday) but exit when the rv
spread closes (the highest-rv coin is no longer materially above median).
Cell exit value differs.
"""
from __future__ import annotations

from collections import deque
from statistics import median, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "neutral_zone",
    "idea_family": "vol_dispersion_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/vol_dispersion.md"]


class VolDispersionNeutralZoneStrategy:
    def __init__(
        self,
        symbols: list[str],
        rv_bars: int = 480,
        rebalance_bars: int = 240,
        top_k: int = 1,
        max_weight: float = 0.16,
        spread_entry: float = 0.30,  # min ratio (max-rv / median-rv) to enter
        spread_exit: float = 0.10,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rv_bars = max(10, int(rv_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.spread_entry = float(spread_entry)
        self.spread_exit = float(spread_exit)

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.rv_bars + 5) for s in self.symbols
        }
        self._bar_count = 0

    def _rv(self, s: str) -> float | None:
        c = list(self._closes[s])
        if len(c) < self.rv_bars + 1:
            return None
        rets = []
        for prev, cur in zip(c[-self.rv_bars - 1:-1], c[-self.rv_bars:]):
            rets.append((cur - prev) / prev if prev > 0 else 0.0)
        return pstdev(rets) if len(rets) >= 5 else None

    def _current_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d:
                continue
            close = d.get("close")
            if close is not None and close > 0:
                self._closes[s].append(float(close))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        rvs: dict[str, float] = {}
        for s in self.symbols:
            v = self._rv(s)
            if v is not None:
                rvs[s] = v
        if len(rvs) < 3:
            return None

        med = median(rvs.values()) or 1e-12
        ranked = sorted(rvs.items(), key=lambda kv: kv[1])
        # only enter if dispersion is meaningful
        max_rv = ranked[-1][1]
        min_rv = ranked[0][1]
        spread_ratio = (max_rv - min_rv) / med if med > 0 else 0.0
        if spread_ratio < self.spread_entry:
            # neutral zone: close all
            orders = {}
            for s in self.symbols:
                cur = self._current_side(state, s)
                if cur == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                elif cur == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                else:
                    orders[s] = None
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        long_pick = [s for s, _ in ranked[: self.top_k]]
        short_pick = [s for s, _ in ranked[-self.top_k:]]
        target = {s: None for s in self.symbols}
        for s in long_pick:
            target[s] = "LONG"
        for s in short_pick:
            target[s] = "SHORT"

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            cur = self._current_side(state, s)
            tgt = target[s]
            if tgt == "LONG":
                orders[s] = (
                    None
                    if cur == "LONG"
                    else Order(
                        side=Side.BUY, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            elif tgt == "SHORT":
                orders[s] = (
                    None
                    if cur == "SHORT"
                    else Order(
                        side=Side.SELL, quantity=0.0,
                        weight=self.max_weight, order_type=OrderType.MARKET,
                    )
                )
            else:
                if cur == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                elif cur == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                else:
                    orders[s] = None

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
