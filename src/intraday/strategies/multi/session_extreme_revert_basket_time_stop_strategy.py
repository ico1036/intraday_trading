"""Session extreme revert basket TIME_STOP exit (cell variant)."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeRevertBasketTimeStopStrategy:
    def __init__(self, symbols, warmup_minutes=30, flat_at_minute=1410, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.flat_at_minute = int(flat_at_minute)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._sess_high = {s: None for s in self.symbols}
        self._sess_low = {s: None for s in self.symbols}
        self._current_day = None

    def _reset(self):
        for s in self.symbols:
            self._sess_high[s] = None; self._sess_low[s] = None

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
        ts = state.timestamp; day = ts.toordinal(); m = ts.hour * 60 + ts.minute
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._reset()
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is None or lo is None: continue
            ch = self._sess_high[s]; cl_ = self._sess_low[s]
            self._sess_high[s] = hi if ch is None else max(ch, float(hi))
            self._sess_low[s] = lo if cl_ is None else min(cl_, float(lo))
        if m < self.warmup_minutes: return None
        orders = {s: None for s in self.symbols}
        if m >= self.flat_at_minute:
            for s in self.symbols:
                cur = self._current_side(state, s); o = self._close_for_side(cur)
                if o: orders[s] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); sh = self._sess_high.get(s); sl = self._sess_low.get(s)
            if cl is None or sh is None or sl is None: continue
            cur = self._current_side(state, s)
            if cl >= sh - 1e-9 and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif cl <= sl + 1e-9 and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
