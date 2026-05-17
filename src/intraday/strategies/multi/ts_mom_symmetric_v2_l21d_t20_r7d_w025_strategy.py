"""ts_mom_symmetric_v2_l21d_t20_r7d_w025 — TS-mom symmetric (v2), tuned position sizing."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_mom_symmetric_v2_l21d_t20_r7d_w025",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_mom_symmetric.md"]


class TsMomSymmetricV2L21dT20R7dW025Strategy:
    def __init__(self, symbols, lookback_bars=30240, rebalance_bars=10080,
                 entry_threshold=0.02, exit_threshold=0.006, max_weight=0.025, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback + 1) for s in self.symbols}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def _close_order(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is not None and float(c) > 0: self._closes[s].append(float(c))
        self._bar += 1
        if self._bar % self.rebalance_bars != 0: return None

        rets = {}
        for s in self.symbols:
            if len(self._closes[s]) < self.lookback + 1: continue
            start = self._closes[s][0]; end = self._closes[s][-1]
            if start <= 0 or end <= 0: continue
            r = math.log(end / start)
            if math.isfinite(r): rets[s] = r

        active: dict[str, str] = {}
        for s, r in rets.items():
            if r > self.entry_threshold: active[s] = "LONG"
            elif r < -self.entry_threshold: active[s] = "SHORT"

        n = len(active)
        per_w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            r = rets.get(s)
            tgt = active.get(s)
            if tgt == "LONG":
                if cs != "LONG":
                    if cs == "SHORT":
                        orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET); any_change = True
                    else:
                        orders[s] = Order(side=Side.BUY, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change = True
            elif tgt == "SHORT":
                if cs != "SHORT":
                    if cs == "LONG":
                        orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET); any_change = True
                    else:
                        orders[s] = Order(side=Side.SELL, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change = True
            elif r is not None and abs(r) < self.exit_threshold and cs is not None:
                o = self._close_order(cs)
                if o is not None:
                    orders[s] = o; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
