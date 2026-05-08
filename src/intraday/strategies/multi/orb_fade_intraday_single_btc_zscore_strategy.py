"""ORB-fade intraday (4h block) single BTC z_score (cell variant of is_049)."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeIntradaySingleBtcZscoreStrategy:
    def __init__(self, symbols, target="BTCUSDT", block_hours=4, or_minutes=30, history_size=30, entry_z=0.7, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.block_hours = max(1, int(block_hours))
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = None; self._or_low = None
        self._mag_hist = deque(maxlen=self.history_size)
        self._current_block = None

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
        block_idx = ts.hour // self.block_hours
        block_start_minute = block_idx * self.block_hours * 60
        m_in_block = (ts.hour * 60 + ts.minute) - block_start_minute
        if self._current_block is None or (day, block_idx) != self._current_block:
            self._current_block = (day, block_idx); self._or_high = None; self._or_low = None
        d = state.panel.get(self.target)
        if m_in_block < self.or_minutes:
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
        cur = self._current_side(state)
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
