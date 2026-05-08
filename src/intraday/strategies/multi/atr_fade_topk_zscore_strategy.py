"""ATR band fade topk z_score (untried for atr family)."""
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
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrFadeTopkZscoreStrategy:
    def __init__(self, symbols, top_k=3, atr_window=60, k=1.0, history_size=30, entry_z=0.5, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.atr_window = max(20, int(atr_window))
        self.k = float(k)
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._tr_hist = {s: deque(maxlen=self.atr_window) for s in self.symbols}
        self._closes = {s: deque(maxlen=2) for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
        self._sma = {s: deque(maxlen=self.atr_window) for s in self.symbols}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl)
            hi = float(hi) if hi is not None else cl
            lo = float(lo) if lo is not None else cl
            prev_cl = self._closes[s][-1] if self._closes[s] else cl
            tr = max(hi - lo, abs(hi - prev_cl), abs(lo - prev_cl))
            self._tr_hist[s].append(tr)
            self._closes[s].append(cl)
            self._sma[s].append(cl)
            if len(self._tr_hist[s]) < 20: continue
            atr = sum(self._tr_hist[s]) / len(self._tr_hist[s])
            sma = sum(self._sma[s]) / len(self._sma[s])
            band = self.k * atr
            mag = 0.0; tgt = None
            if cl >= sma + band: mag = (cl - sma - band) / max(atr, 1e-9); tgt = "SHORT"
            elif cl <= sma - band: mag = (sma - band - cl) / max(atr, 1e-9); tgt = "LONG"
            if tgt is None: continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            score = mag
            if len(hist) >= 5:
                sd = pstdev(hist) or 1e-9
                z = mag / sd
                if z < self.entry_z: continue
                score = z
            candidates.append((s, tgt, score))
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
