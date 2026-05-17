"""is_857_ts_skew_long_w10080_st05_h28d — negative skew capitulation long."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "raw", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_skew_long_w10080_st05_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_skew_long_w10080_st05_h28d.md"]


class TsSkewLongW10080St05H28DStrategy:
    def __init__(self, symbols, window=10080, skew_threshold=-0.5,
                 rebalance_bars=240, hold_bars=40320, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window)); self.skew_threshold = float(skew_threshold)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._rets = {s: deque(maxlen=self.window) for s in self.symbols}
        self._last = {s: None for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def _skew(self, s):
        rs = self._rets[s]; n = len(rs)
        if n < self.window: return None
        m = sum(rs)/n
        var = sum((r-m)**2 for r in rs)/n
        if var <= 0: return None
        sd = math.sqrt(var)
        sk = sum((r-m)**3 for r in rs) / (n * sd**3)
        return sk

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            cv = float(c)
            if self._last[s] is not None and self._last[s] > 0:
                r = math.log(cv/self._last[s])
                if math.isfinite(r): self._rets[s].append(r)
            self._last[s] = cv
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
                sk = self._skew(s)
                if sk is None: continue
                cs = self._side(state, s)
                if cs is None and sk < self.skew_threshold:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
