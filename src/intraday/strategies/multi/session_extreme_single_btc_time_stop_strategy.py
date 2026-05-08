"""Session extreme revert single BTC TIME_STOP exit."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "time_stop",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeSingleBtcTimeStopStrategy:
    def __init__(self, symbols, target="BTCUSDT", warmup_minutes=30, flat_at_minute=1410, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.warmup_minutes = max(5, int(warmup_minutes))
        self.flat_at_minute = int(flat_at_minute)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._sess_high = None; self._sess_low = None
        self._current_day = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
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
            self._current_day = day; self._sess_high = None; self._sess_low = None
        d = state.panel.get(self.target)
        if d:
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is not None and lo is not None:
                self._sess_high = hi if self._sess_high is None else max(self._sess_high, float(hi))
                self._sess_low = lo if self._sess_low is None else min(self._sess_low, float(lo))
        if m < self.warmup_minutes: return None
        orders = {s: None for s in self.symbols}
        if m >= self.flat_at_minute:
            cur = self._current_side(state); o = self._close_for_side(cur)
            if o: orders[self.target] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        if not d: return None
        cl = d.get("close")
        if cl is None or self._sess_high is None or self._sess_low is None: return None
        cur = self._current_side(state)
        if cl >= self._sess_high - 1e-9 and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif cl <= self._sess_low + 1e-9 and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
