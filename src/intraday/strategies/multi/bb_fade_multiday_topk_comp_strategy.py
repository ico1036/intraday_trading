"""BB band fade multi_day topk composite."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeMultidayTopkCompStrategy:
    def __init__(self, symbols, top_k=3, lookback=720, k=2.0, history_size=30, entry_thr=0.4, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.lookback = max(60, int(lookback))
        self.k = float(k)
        self.history_size = max(10, int(history_size))
        self.entry_thr = float(entry_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}

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
            cl = d.get("close")
            if cl is None: continue
            cl = float(cl)
            cs = self._closes[s]
            if len(cs) < self.lookback // 2:
                cs.append(cl); continue
            m = mean(cs); sd = pstdev(cs) or 1e-9
            z = (cl - m) / sd
            cs.append(cl)
            mag = abs(z)
            if mag < self.k: continue
            tgt = "SHORT" if z > 0 else "LONG"
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            score = mag
            if len(hist) >= 5:
                hsd = pstdev(hist) or 1e-9
                hz = mag / hsd
                rank = sum(1 for h in hist if h <= mag) / len(hist)
                score = 0.5 * hz + 0.5 * (rank * 2.0)
                if score < self.entry_thr: continue
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
