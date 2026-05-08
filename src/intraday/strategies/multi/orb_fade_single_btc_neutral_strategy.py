"""ORB-fade single BTC neutral_zone."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "neutral_zone",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleBtcNeutralStrategy:
    def __init__(self, symbols, target="BTCUSDT", or_minutes=30, neutral_band=0.3, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"{self.target} not in symbols")
        self.or_minutes = max(5, int(or_minutes))
        self.neutral_band = float(neutral_band)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = None; self._or_low = None
        self._day = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._or_high = None; self._or_low = None
        d = state.panel.get(self.target)
        if not d: return None
        m = ts.hour * 60 + ts.minute
        if m < self.or_minutes:
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is not None and lo is not None:
                self._or_high = hi if self._or_high is None else max(self._or_high, float(hi))
                self._or_low = lo if self._or_low is None else min(self._or_low, float(lo))
            return None
        cl = d.get("close")
        if cl is None or self._or_high is None or self._or_low is None: return None
        or_w = max(self._or_high - self._or_low, 1e-9)
        mid = (self._or_high + self._or_low) / 2
        orders = {s: None for s in self.symbols}
        cur = self._current_side(state)
        if cur in {"LONG", "SHORT"} and abs(cl - mid) <= self.neutral_band * or_w:
            orders[self.target] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                        quantity=0.0, order_type=OrderType.MARKET)
            return PortfolioOrder(orders=orders)
        tgt = None
        if cl > self._or_high: tgt = "SHORT"
        elif cl < self._or_low: tgt = "LONG"
        if tgt is None: return None
        if cur is None:
            if tgt == "SHORT":
                orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            else:
                orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not has_entry: return None
        return PortfolioOrder(orders=orders)
