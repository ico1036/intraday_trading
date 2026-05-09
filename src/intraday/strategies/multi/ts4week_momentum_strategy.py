"""is_012_ts_4week_momentum — per-symbol monthly TS momentum, biweekly rebalance."""
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
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "ts_4week_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_4week_momentum.md"]


class Ts4weekMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 40320,
        history_window: int = 6,
        rebalance_bars: int = 20160,
        entry_z: float = 0.5,
        exit_z: float = 0.1,
        max_weight: float = 0.14,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.history_window = max(3, int(history_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes: dict[str, deque[float]] = {s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols}
        self._return_history: dict[str, deque[float]] = {s: deque(maxlen=self.history_window) for s in self.symbols}
        self._bar_count = 0

    def _ret(self, s):
        p = self._closes[s]
        if len(p) < self.lookback_bars + 1: return None
        a, b = p[0], p[-1]
        if a <= 0 or b <= 0: return None
        return math.log(b / a)

    def _z(self, s):
        r = self._ret(s)
        if r is None: return None
        h = self._return_history[s]
        if len(h) < self.history_window: return None
        sigma = pstdev(h); mu = mean(h)
        if sigma <= 0 or not math.isfinite(sigma): return None
        return (r - mu) / sigma

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
        for s in self.symbols:
            r = self._ret(s)
            if r is not None and math.isfinite(r):
                self._return_history[s].append(r)
        targets, zs = {}, {}
        for s in self.symbols:
            z = self._z(s)
            if z is None: continue
            zs[s] = z
            if z > self.entry_z: targets[s] = "LONG"
            elif z < -self.entry_z: targets[s] = "SHORT"
        n = len(targets)
        w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); t = targets.get(s); z = zs.get(s)
            if t == "LONG":
                if cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            elif t == "SHORT":
                if cs != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET); any_change = True
                else: orders[s] = None
            elif z is not None and abs(z) < self.exit_z and cs is not None:
                orders[s] = self._close(cs); any_change = True
            else: orders[s] = None
        return PortfolioOrder(orders=orders) if any_change else None
