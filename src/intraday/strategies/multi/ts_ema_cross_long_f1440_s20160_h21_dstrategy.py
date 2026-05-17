"""is_826_ts_ema_cross_long_f1440_s20160_h21d — EMA cross long."""
from __future__ import annotations
import math
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "ewma_residual", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_ema_cross_long_f1440_s20160_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_ema_cross_long_f1440_s20160_h21d.md"]


class TsEmaCrossLongF1440S20160H21DStrategy:
    def __init__(self, symbols, fast_period=1440, slow_period=20160,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.fast = max(2, int(fast_period)); self.slow = max(self.fast+1, int(slow_period))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._fa = 2.0 / (self.fast+1); self._sa = 2.0 / (self.slow+1)
        self._ef = {s: None for s in self.symbols}
        self._es = {s: None for s in self.symbols}
        self._n = {s: 0 for s in self.symbols}
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
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            x = float(c)
            self._ef[s] = x if self._ef[s] is None else self._fa*x + (1-self._fa)*self._ef[s]
            self._es[s] = x if self._es[s] is None else self._sa*x + (1-self._sa)*self._es[s]
            self._n[s] += 1
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
                if self._ef[s] is None or self._es[s] is None: continue
                if self._n[s] < self.slow: continue
                cs = self._side(state, s)
                if cs is None and self._ef[s] > self._es[s] * 1.005:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
