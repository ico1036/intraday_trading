"""Single-bar burst then fade across basket."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "burst_then_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/burst_then_fade.md"]


class BurstThenFadeBasketStrategy:
    def __init__(self, symbols, sigma_window=240, k=3.0, hold_bars=60, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.sigma_window = max(20, int(sigma_window)); self.k = float(k)
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.sigma_window + 5) for s in self.symbols}
        self._held = {s: 0 for s in self.symbols}

    def _z(self, s):
        c = list(self._closes[s])
        if len(c) < self.sigma_window + 1: return None
        rets = [(c[i+1]-c[i])/c[i] for i in range(len(c)-1) if c[i] > 0]
        if len(rets) < 5: return None
        sigma = pstdev(rets) or 1e-9
        last = (c[-1] - c[-2]) / c[-2] if c[-2] > 0 else 0.0
        return last / sigma

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_for_side(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes[s].append(float(cl))
        for s in self.symbols:
            if self._current_side(state, s) is not None:
                self._held[s] += 1
            else:
                self._held[s] = 0
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            cur = self._current_side(state, s)
            if cur is not None and self._held[s] >= self.hold_bars:
                orders[s] = self._close_for_side(cur)
                self._held[s] = 0
                continue
            if cur is not None: continue
            z = self._z(s)
            if z is None: continue
            if z > self.k:
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                self._held[s] = 1
            elif z < -self.k:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                self._held[s] = 1
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
