"""is_021_xs_lowvol_premium — long lowest realized vol, short highest, weekly XS rebalance."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "xs_lowvol_premium",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_lowvol_premium.md"]


class XsLowvolPremiumStrategy:
    def __init__(self, symbols, vol_window_bars=10080, rebalance_bars=10080, max_weight=0.3, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(vol_window_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._returns = {s: deque(maxlen=self.window) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._last_close = {s: None for s in self.symbols}
        self._bar_count = 0

    def _push(self, s, r):
        rs = self._returns[s]
        if len(rs) == rs.maxlen:
            old = rs[0]; self._sum[s] -= old; self._sumsq[s] -= old * old
        rs.append(r); self._sum[s] += r; self._sumsq[s] += r * r

    def _vol(self, s):
        rs = self._returns[s]; n = len(rs)
        if n < self.window: return None
        m = self._sum[s] / n
        v = self._sumsq[s] / n - m * m
        if v <= 0 or not math.isfinite(v): return None
        return math.sqrt(v)

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG", "SHORT"} else None)

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
            if c is None or float(c) <= 0: continue
            if self._last_close[s] is not None and self._last_close[s] > 0:
                self._push(s, math.log(float(c) / self._last_close[s]))
            self._last_close[s] = float(c)
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None

        vols = {}
        for s in self.symbols:
            v = self._vol(s)
            if v is not None and math.isfinite(v): vols[s] = v
        if len(vols) < 4: return None

        ranked = sorted(vols, key=lambda x: vols[x])
        # Long bottom 2 (low vol), short top 2 (high vol)
        long_set = set(ranked[:2])
        short_set = set(ranked[-2:])
        n = len(long_set) + len(short_set)
        w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            if s in long_set:
                if cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            elif s in short_set:
                if cs != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            else:
                if cs is not None:
                    orders[s] = self._close(cs); any_change = True
                else: orders[s] = None
        return PortfolioOrder(orders=orders) if any_change else None
