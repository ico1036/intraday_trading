"""BB-fade pair time_stop composite."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "session",
    "universe": "pair",
    "exit": "time_stop",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadePairTsCompStrategy:
    def __init__(self, symbols, leg_a="BTCUSDT", leg_b="ETHUSDT", window=1440, k=2.0, flat_at_minute=1410, rebalance_bars=60, max_weight=0.30, composite_threshold=0.10, **_):
        self.symbols = [s.upper() for s in symbols]
        self.leg_a = leg_a.upper(); self.leg_b = leg_b.upper()
        if self.leg_a not in self.symbols or self.leg_b not in self.symbols:
            raise ValueError("legs must be in symbols")
        self.active = [self.leg_a, self.leg_b]
        self.window = max(60, int(window)); self.k = float(k)
        self.flat_at_minute = int(flat_at_minute)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.composite_threshold = float(composite_threshold)
        self._closes = {s: deque(maxlen=self.window + 5) for s in self.active}
        self._bar_count = 0

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
        ts = state.timestamp; m = ts.hour * 60 + ts.minute
        for s in self.active:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes[s].append(float(cl))
        orders = {s: None for s in self.symbols}
        if m >= self.flat_at_minute:
            for s in self.active:
                cur = self._current_side(state, s); o = self._close_for_side(cur)
                if o: orders[s] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None
        for s in self.active:
            closes = list(self._closes[s])
            if len(closes) < self.window: continue
            seg = closes[-self.window:]
            mu = mean(seg); sd = pstdev(seg) or 1e-12
            cl = closes[-1]
            band_z = (cl - mu) / sd
            mid_dist = (cl - mu) / mu if mu > 0 else 0.0
            cur = self._current_side(state, s)
            if band_z > self.k:
                composite = band_z + mid_dist * 100
                if composite > self.k + self.composite_threshold and cur != "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif band_z < -self.k:
                composite = -band_z + (-mid_dist * 100)
                if composite > self.k + self.composite_threshold and cur != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
