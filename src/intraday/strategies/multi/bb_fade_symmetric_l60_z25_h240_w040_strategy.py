"""bb_fade_symmetric_l60_z25_h240_w040 — BB-band fade symmetric (Z>τ short, Z<-τ long), hold N bars."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "bb_fade_symmetric_l60_z25_h240_w040",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_fade_symmetric.md"]


class BbFadeSymmetricL60Z25H240W040Strategy:
    def __init__(self, symbols, lookback_bars=60, rebalance_bars=60,
                 entry_z=2.5, hold_bars=240, max_weight=0.04, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(20, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._open_at = {}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG","SHORT"} else None

    def _zscore(self, s):
        v = list(self._closes[s])
        if len(v) < self.lookback: return None
        mu = sum(v)/len(v)
        var = sum((x-mu)**2 for x in v) / max(1, len(v)-1)
        sd = math.sqrt(var)
        if sd <= 0 or not math.isfinite(sd): return None
        return (v[-1] - mu) / sd

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is not None and float(c) > 0:
                self._closes[s].append(float(c))
        self._bar += 1

        orders, any_change = {}, False
        # time-stop exit
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs is not None and opened is not None and self._bar - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar % self.rebalance_bars == 0:
            cands_long, cands_short = [], []
            for s in self.symbols:
                cs = self._side(state, s)
                if cs is not None: continue
                z = self._zscore(s)
                if z is None: continue
                if z >= self.entry_z:
                    cands_short.append(s)
                elif z <= -self.entry_z:
                    cands_long.append(s)
            n = len(cands_long) + len(cands_short)
            w = min(self.max_weight, 1.0/n) if n > 0 else 0.0
            for s in cands_long:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; any_change = True
            for s in cands_short:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
