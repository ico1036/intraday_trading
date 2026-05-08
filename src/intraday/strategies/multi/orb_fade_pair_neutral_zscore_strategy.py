"""ORB-fade pair neutral_zone z_score."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "pair",
    "exit": "neutral_zone",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadePairNeutralZscoreStrategy:
    def __init__(self, symbols, pair=("BTCUSDT", "ETHUSDT"), or_minutes=30, history_size=30, entry_z=0.4,
                 neutral_band=0.4, max_weight=0.4, **_):
        self.symbols = [s.upper() for s in symbols]
        self.pair = tuple(p.upper() for p in pair)
        for p in self.pair:
            if p not in self.symbols: raise ValueError(p)
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.neutral_band = float(neutral_band)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = {s: None for s in self.pair}
        self._or_low = {s: None for s in self.pair}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.pair}
        self._day = None

    def _reset(self):
        for s in self.pair:
            self._or_high[s] = None; self._or_low[s] = None

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._reset()
        m = ts.hour * 60 + ts.minute
        if m < self.or_minutes:
            for s in self.pair:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                self._or_high[s] = hi if self._or_high[s] is None else max(self._or_high[s], float(hi))
                self._or_low[s] = lo if self._or_low[s] is None else min(self._or_low[s], float(lo))
            return None
        orders = {s: None for s in self.symbols}
        for s in self.pair:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = self._or_high.get(s); lo = self._or_low.get(s)
            if cl is None or hi is None or lo is None: continue
            or_w = max(hi - lo, 1e-9)
            mid = (hi + lo) / 2
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and abs(cl - mid) <= self.neutral_band * or_w:
                orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                  quantity=0.0, order_type=OrderType.MARKET)
                continue
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
            if cur is None:
                if tgt == "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                else:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not has_entry: return None
        return PortfolioOrder(orders=orders)
