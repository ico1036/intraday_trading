"""ORB continuation (NOT fade) session signal_flip — opposite direction of orb_fade."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "opening_range_breakout",
}
SOURCE_NOTES: list[str] = ["research/notes/opening_range_breakout.md"]


class OrbContinuationSessionSignalFlipStrategy:
    def __init__(self, symbols, or_minutes=60, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = {s: None for s in self.symbols}
        self._or_low = {s: None for s in self.symbols}
        self._current_day = None

    def _reset(self):
        for s in self.symbols:
            self._or_high[s] = None; self._or_low[s] = None

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp; day = ts.toordinal(); m = ts.hour * 60 + ts.minute
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._reset()
        if m < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                ch = self._or_high[s]; cl_ = self._or_low[s]
                self._or_high[s] = hi if ch is None else max(ch, float(hi))
                self._or_low[s] = lo if cl_ is None else min(cl_, float(lo))
            return None
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = self._or_high.get(s); lo = self._or_low.get(s)
            if cl is None or hi is None or lo is None: continue
            cur = self._current_side(state, s)
            # CONTINUATION: break above OR-high → LONG (follow break)
            if cl > hi and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif cl < lo and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
