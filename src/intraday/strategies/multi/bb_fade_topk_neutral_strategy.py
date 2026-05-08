"""BB band fade topk neutral_zone exit."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "neutral_zone",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeTopkNeutralStrategy:
    def __init__(self, symbols, lookback=120, k=1.5, neutral_band=0.3, top_k=2, max_weight=0.3, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(20, int(lookback))
        self.k = float(k)
        self.neutral_band = float(neutral_band)
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        candidates = []
        snapshots = {}
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
            snapshots[s] = (cl, m, sd, z)
            cs.append(cl)
            tgt = None
            if z >= self.k: tgt = "SHORT"
            elif z <= -self.k: tgt = "LONG"
            if tgt is None: continue
            candidates.append((s, tgt, abs(z)))
        candidates.sort(key=lambda x: -x[2])
        chosen = {s: t for s, t, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        # close existing positions hitting neutral band
        if state.positions:
            for s, info in state.positions.items():
                side = info.get("side")
                if side not in {"LONG", "SHORT"}: continue
                snap = snapshots.get(s)
                if not snap: continue
                cl, m, sd, _ = snap
                if abs(cl - m) <= self.neutral_band * sd:
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
