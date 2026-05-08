"""LR-residual fade basket signal_flip session."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "lr_residual_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/lr_residual_fade.md"]


class LrResidualFadeBasketStrategy:
    def __init__(self, symbols, window=480, k=2.0, rebalance_bars=60, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.window = max(20, int(window)); self.k = float(k)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.window + 5) for s in self.symbols}
        self._bar_count = 0

    def _lr_residual_z(self, s):
        c = list(self._closes[s])
        if len(c) < self.window: return None
        seg = c[-self.window:]
        n = len(seg)
        # x = 0..n-1
        sx = sum(range(n))
        sy = sum(seg)
        sxx = sum(i*i for i in range(n))
        sxy = sum(i*seg[i] for i in range(n))
        denom = n * sxx - sx * sx
        if denom == 0: return None
        slope = (n * sxy - sx * sy) / denom
        intercept = (sy - slope * sx) / n
        # residuals
        residuals = [seg[i] - (slope * i + intercept) for i in range(n)]
        sd = pstdev(residuals) or 1e-9
        last_residual = residuals[-1]
        return last_residual / sd

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes[s].append(float(cl))
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            z = self._lr_residual_z(s)
            if z is None: continue
            cur = self._current_side(state, s)
            if z > self.k and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif z < -self.k and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
