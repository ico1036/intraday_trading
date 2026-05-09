"""is_015_xs_weekly_momentum — cross-sectional weekly momentum (sign-flip of xs_weekly_reversal)."""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "xs_weekly_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_weekly_momentum.md"]


class XsWeeklyMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 10080,
        rebalance_bars: int = 10080,
        entry_z: float = 0.5,
        exit_z: float = 0.1,
        max_weight: float = 0.3,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z); self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols}
        self._bar_count = 0

    def _ret(self, s):
        p = self._closes[s]
        if len(p) < self.lookback_bars + 1: return None
        a, b = p[0], p[-1]
        if a <= 0 or b <= 0: return None
        return math.log(b / a)

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        v = info.get("side")
        return v if v in {"LONG", "SHORT"} else None

    def _close(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is not None and float(c) > 0:
                self._closes[s].append(float(c))
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None

        rets = {}
        for s in self.symbols:
            r = self._ret(s)
            if r is not None and math.isfinite(r): rets[s] = r
        if len(rets) < 2: return None
        vals = list(rets.values())
        mu = mean(vals); sigma = pstdev(vals)
        if sigma <= 0 or not math.isfinite(sigma): return None
        zs = {s: (rets[s] - mu) / sigma for s in rets}  # NOT inverted: momentum direction

        targets = {}
        for s, z in zs.items():
            if z > self.entry_z: targets[s] = "LONG"
            elif z < -self.entry_z: targets[s] = "SHORT"
        n = len(targets)
        w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            if s not in zs: orders[s] = None; continue
            z = zs[s]; t = targets.get(s)
            if t == "LONG":
                if cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            elif t == "SHORT":
                if cs != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            elif abs(z) < self.exit_z and cs is not None:
                orders[s] = self._close(cs); any_change = True
            else: orders[s] = None
        return PortfolioOrder(orders=orders) if any_change else None
