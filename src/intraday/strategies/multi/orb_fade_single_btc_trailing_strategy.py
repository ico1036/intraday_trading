"""ORB-fade single BTC trailing exit."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "trailing",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleBtcTrailingStrategy:
    def __init__(self, symbols, target="BTCUSDT", or_minutes=60, trail_pct=0.005, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.or_minutes = max(5, int(or_minutes))
        self.trail_pct = float(trail_pct)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = None; self._or_low = None
        self._best_favorable = None
        self._current_day = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal(); m = ts.hour * 60 + ts.minute
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._or_high = None; self._or_low = None
        d = state.panel.get(self.target)
        if m < self.or_minutes:
            if d:
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is not None and lo is not None:
                    self._or_high = hi if self._or_high is None else max(self._or_high, float(hi))
                    self._or_low = lo if self._or_low is None else min(self._or_low, float(lo))
            return None

        orders = {s: None for s in self.symbols}
        if not d: return None
        cl = d.get("close")
        if cl is None: return None

        cur = self._current_side(state)
        if cur == "LONG":
            if self._best_favorable is None or cl > self._best_favorable:
                self._best_favorable = cl
            if cl < self._best_favorable * (1.0 - self.trail_pct):
                orders[self.target] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._best_favorable = None
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        if cur == "SHORT":
            if self._best_favorable is None or cl < self._best_favorable:
                self._best_favorable = cl
            if cl > self._best_favorable * (1.0 + self.trail_pct):
                orders[self.target] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._best_favorable = None
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        if self._or_high is None or self._or_low is None: return None
        if cl > self._or_high:
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            self._best_favorable = cl
        elif cl < self._or_low:
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            self._best_favorable = cl
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
