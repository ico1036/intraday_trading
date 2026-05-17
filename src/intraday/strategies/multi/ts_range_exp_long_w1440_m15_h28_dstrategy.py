"""is_701_ts_range_exp_long_w1440_m15_h28d — HL range expansion long."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "raw", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_range_exp_long_w1440_m15_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_range_exp_long_w1440_m15_h28d.md"]


class TsRangeExpLongW1440M15H28DStrategy:
    def __init__(self, symbols, window=1440, mult=1.5,
                 rebalance_bars=240, hold_bars=40320, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window)); self.mult = float(mult)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._ranges = {s: deque(maxlen=self.window) for s in self.symbols}
        self._opens = {s: deque(maxlen=self.window) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.window) for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h, l, o, c = d.get("high"), d.get("low"), d.get("open"), d.get("close")
            if h is None or l is None or c is None: continue
            self._ranges[s].append(float(h) - float(l))
            if o is not None:
                self._opens[s].append(float(o))
            self._closes[s].append(float(c))
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                if len(self._ranges[s]) < self.window: continue
                avg_r = sum(self._ranges[s]) / len(self._ranges[s])
                if avg_r <= 0: continue
                cur_r = self._ranges[s][-1]
                if cur_r > avg_r * self.mult and self._opens[s] and self._closes[s][-1] > self._opens[s][-1]:
                    cs = self._side(state, s)
                    if cs is None:
                        cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
