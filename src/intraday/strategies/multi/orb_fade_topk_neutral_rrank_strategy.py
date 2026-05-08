"""ORB-fade topk neutral_zone rolling_rank."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "neutral_zone",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeTopkNeutralRrankStrategy:
    def __init__(self, symbols, top_k=3, or_minutes=30, history_size=30, rank_thr=0.5,
                 neutral_band=0.4, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.or_minutes = max(5, int(or_minutes))
        self.history_size = max(10, int(history_size))
        self.rank_thr = float(rank_thr)
        self.neutral_band = float(neutral_band)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high = {s: None for s in self.symbols}
        self._or_low = {s: None for s in self.symbols}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
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
        snapshots = {}
        if m < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                self._or_high[s] = hi if self._or_high[s] is None else max(self._or_high[s], float(hi))
                self._or_low[s] = lo if self._or_low[s] is None else min(self._or_low[s], float(lo))
            return None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = self._or_high.get(s); lo = self._or_low.get(s)
            if cl is None or hi is None or lo is None: continue
            or_w = max(hi - lo, 1e-9)
            mid = (hi + lo) / 2
            snapshots[s] = (cl, mid, or_w)
            mag = 0.0; tgt = None
            if cl > hi: mag = (cl - hi) / or_w; tgt = "SHORT"
            elif cl < lo: mag = (lo - cl) / or_w; tgt = "LONG"
            if tgt is None: continue
            hist = list(self._mag_hist[s])
            self._mag_hist[s].append(mag)
            score = mag
            if len(hist) >= 5:
                sorted_h = sorted(hist)
                rank = sum(1 for h in sorted_h if h <= mag) / len(sorted_h)
                if rank < self.rank_thr: continue
                score = rank
            candidates.append((s, tgt, score))
        candidates.sort(key=lambda x: -x[2])
        chosen = {s: t for s, t, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        if state.positions:
            for s, info in state.positions.items():
                side = info.get("side")
                if side not in {"LONG", "SHORT"}: continue
                snap = snapshots.get(s)
                if not snap: continue
                cl, mid, or_w = snap
                if abs(cl - mid) <= self.neutral_band * or_w:
                    orders[s] = Order(side=Side.SELL if side == "LONG" else Side.BUY,
                                      quantity=0.0, order_type=OrderType.MARKET)
        for s, tgt in chosen.items():
            if orders.get(s) is not None: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not has_entry: return None
        return PortfolioOrder(orders=orders)
