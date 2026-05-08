"""Session extreme revert single BTC z_score."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeSingleBtcZscoreStrategy:
    def __init__(self, symbols, target="BTCUSDT", history_size=30, entry_z=0.4, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hi = None; self._lo = None
        self._mag_hist = deque(maxlen=self.history_size)
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
            self._day = day; self._hi = None; self._lo = None
        d = state.panel.get(self.target)
        if not d: return None
        hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
        if hi is None and cl is not None: hi = cl
        if lo is None and cl is not None: lo = cl
        if hi is None or lo is None or cl is None: return None
        self._hi = hi if self._hi is None else max(self._hi, float(hi))
        self._lo = lo if self._lo is None else min(self._lo, float(lo))
        sw = max(self._hi - self._lo, 1e-9)
        mag = 0.0; tgt = None
        if cl >= self._hi: mag = (cl - self._hi) / sw + 0.001; tgt = "SHORT"
        elif cl <= self._lo: mag = (self._lo - cl) / sw + 0.001; tgt = "LONG"
        if tgt is None: return None
        hist = list(self._mag_hist)
        self._mag_hist.append(mag)
        if len(hist) >= 5:
            sd = pstdev(hist) or 1e-9
            z = mag / sd
            if z < self.entry_z: return None
        cur = self._current_side(state)
        orders = {s: None for s in self.symbols}
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
