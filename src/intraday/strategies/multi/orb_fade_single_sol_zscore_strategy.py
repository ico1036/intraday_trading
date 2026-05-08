"""ORB-fade session single SOL z_score."""
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
    "exit": "time_stop",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeSingleSolZscoreStrategy:
    def __init__(self, symbols, target="SOLUSDT", or_minutes=30, history_size=30, entry_z=0.7, max_weight=0.5, hold_bars=120, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.hold_bars = max(10, int(hold_bars))
        self._or_high = None; self._or_low = None
        self._mag_hist = deque(maxlen=self.history_size)
        self._day = None
        self._entry_bar = None
        self._bar_count = 0

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        self._bar_count += 1
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._or_high = None; self._or_low = None
        d = state.panel.get(self.target)
        m = ts.hour * 60 + ts.minute
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
        if cl is None or self._or_high is None or self._or_low is None: return None
        cur = self._current_side(state)
        # time_stop exit
        if cur in {"LONG", "SHORT"} and self._entry_bar is not None:
            if self._bar_count - self._entry_bar >= self.hold_bars:
                orders[self.target] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                            quantity=0.0, weight=0.0, order_type=OrderType.MARKET)
                self._entry_bar = None
                active = {s: o for s, o in orders.items() if o is not None}
                return PortfolioOrder(orders=orders) if active else None
        or_w = max(self._or_high - self._or_low, 1e-9)
        mag = 0.0; tgt = None
        if cl > self._or_high: mag = (cl - self._or_high) / or_w; tgt = "SHORT"
        elif cl < self._or_low: mag = (self._or_low - cl) / or_w; tgt = "LONG"
        if tgt is None: return None
        hist = list(self._mag_hist)
        self._mag_hist.append(mag)
        if len(hist) >= 5:
            sd = pstdev(hist) or 1e-9
            z = mag / sd
            if z < self.entry_z: return None
        if cur is None:
            if tgt == "SHORT":
                orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                self._entry_bar = self._bar_count
            elif tgt == "LONG":
                orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                self._entry_bar = self._bar_count
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
