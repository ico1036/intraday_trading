"""ORB-fade basket_full neutral_zone z_score (cell variant of is_077 raw)."""
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
    "exit": "neutral_zone",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeBasketNzZscoreStrategy:
    def __init__(self, symbols, or_minutes=60, history_size=30, entry_z=0.5, max_weight=0.13, exit_inside_minutes=60, **_):
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.exit_inside_minutes = max(1, int(exit_inside_minutes))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = {s: None for s in self.symbols}
        self._or_low = {s: None for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
        self._inside_minutes = {s: 0 for s in self.symbols}
        self._current_day = None

    def _reset(self):
        for s in self.symbols:
            self._or_high[s] = None; self._or_low[s] = None
            self._inside_minutes[s] = 0

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
            # neutral zone exit logic
            if cur is not None and lo <= cl <= hi:
                self._inside_minutes[s] += 1
                if self._inside_minutes[s] >= self.exit_inside_minutes:
                    o = self._close_for_side(cur)
                    if o: orders[s] = o
                    self._inside_minutes[s] = 0
                continue
            else:
                self._inside_minutes[s] = 0
            or_w = max(hi - lo, 1e-9)
            mag = 0.0; tgt = None
            if cl > hi: mag = (cl - hi) / or_w; tgt = "SHORT"
            elif cl < lo: mag = (lo - cl) / or_w; tgt = "LONG"
            if tgt is None: continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            if len(hist) >= 5:
                sd = pstdev(hist) or 1e-9
                z = mag / sd
                if z < self.entry_z: continue
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
