"""Session extreme revert: top-k by z-score magnitude."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeTopkZscoreStrategy:
    def __init__(self, symbols, top_k=3, history_size=30, entry_z=0.0, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._sess_high = {s: None for s in self.symbols}
        self._sess_low = {s: None for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
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

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._reset()
        # update session H/L
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
        # build (sym, dir, z) signals
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = self._sess_high.get(s); lo = self._sess_low.get(s)
            if cl is None or hi is None or lo is None: continue
            sw = max(hi - lo, 1e-9)
            mag = 0.0; tgt = None
            if cl >= hi: mag = (cl - hi) / sw + 0.001; tgt = "SHORT"
            elif cl <= lo: mag = (lo - cl) / sw + 0.001; tgt = "LONG"
            if tgt is None: continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            if len(hist) >= 5:
                sd = pstdev(hist) or 1e-9
                z = mag / sd
                if z < self.entry_z: continue
            else:
                z = 0
            candidates.append((s, tgt, mag, z))
        if not candidates: return None
        candidates.sort(key=lambda x: -x[2])
        chosen = {s for s, _, _, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        for s, tgt, _, _ in candidates[: self.top_k]:
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        # close non-chosen open positions (close orders use no weight)
        if state.positions:
            for s, info in state.positions.items():
                if s in chosen: continue
                if orders.get(s) is not None: continue
                side = info.get("side")
                if side == "LONG":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                elif side == "SHORT":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not active or not has_entry:
            return None
        return PortfolioOrder(orders=orders)
