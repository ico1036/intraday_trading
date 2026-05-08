"""Session extreme revert topk composite."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremeTopkCompositeStrategy:
    def __init__(self, symbols, top_k=2, history_size=30, entry_thr=0.4, max_weight=0.3, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.history_size = max(10, int(history_size))
        self.entry_thr = float(entry_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hi = {s: None for s in self.symbols}
        self._lo = {s: None for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            self._hi[s] = None; self._lo[s] = None

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
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is None or lo is None or cl is None: continue
            self._hi[s] = hi if self._hi[s] is None else max(self._hi[s], float(hi))
            self._lo[s] = lo if self._lo[s] is None else min(self._lo[s], float(lo))
            sw = max(self._hi[s] - self._lo[s], 1e-9)
            mag = 0.0; tgt = None
            if cl >= self._hi[s]: mag = (cl - self._hi[s]) / sw + 0.001; tgt = "SHORT"
            elif cl <= self._lo[s]: mag = (self._lo[s] - cl) / sw + 0.001; tgt = "LONG"
            if tgt is None: continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            score = mag
            if len(hist) >= 5:
                sd = pstdev(hist) or 1e-9
                z = mag / sd
                rank = sum(1 for h in hist if h <= mag) / len(hist)
                score = 0.5 * z + 0.5 * (rank * 2.0)
                if score < self.entry_thr: continue
            candidates.append((s, tgt, score))
        # Avoid empty-only-close orders
        if not candidates:
            return None
        candidates.sort(key=lambda x: -x[2])
        chosen_set = {s for s, _, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        for s, tgt, _ in candidates[: self.top_k]:
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
