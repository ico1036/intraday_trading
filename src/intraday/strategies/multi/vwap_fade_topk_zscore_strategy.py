"""VWAP fade topk z_score deviation."""
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
    "idea_family": "vwap_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/vwap_fade.md"]


class VwapFadeTopkZscoreStrategy:
    def __init__(self, symbols, top_k=3, history_size=60, entry_z=0.7, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.history_size = max(20, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._notional_sum = {s: 0.0 for s in self.symbols}
        self._volume_sum = {s: 0.0 for s in self.symbols}
        self._dev_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            self._notional_sum[s] = 0.0; self._volume_sum[s] = 0.0

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
            cl = d.get("close"); vol = d.get("volume", 0.0)
            if cl is None: continue
            cl = float(cl); vol = float(vol or 0.0)
            self._notional_sum[s] += cl * vol
            self._volume_sum[s] += vol
            if self._volume_sum[s] <= 0: continue
            vwap = self._notional_sum[s] / self._volume_sum[s]
            dev = (cl - vwap) / max(vwap, 1e-9)
            hist = list(self._dev_hist[s])
            self._dev_hist[s].append(dev)
            if len(hist) < 10: continue
            sd = pstdev(hist) or 1e-9
            z = dev / sd
            mag = abs(z)
            if mag < self.entry_z: continue
            tgt = "SHORT" if z > 0 else "LONG"
            candidates.append((s, tgt, mag))
        if not candidates: return None
        candidates.sort(key=lambda x: -x[2])
        chosen = {s: t for s, t, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        for s, tgt in chosen.items():
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
