"""Two bar reversal fade topk."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "two_bar_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/two_bar_reversal_fade.md"]


class TwoBarRevertTopkStrategy:
    def __init__(self, symbols, top_k=3, threshold=0.005, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.threshold = float(threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=3) for s in self.symbols}

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
            if len(cs) < 2:
                cs.append(cl); continue
            r1 = (cs[-1] - cs[-2]) / max(cs[-2], 1e-9)
            r2 = (cl - cs[-1]) / max(cs[-1], 1e-9)
            cs.append(cl)
            # both same direction, both above threshold
            if r1 > self.threshold and r2 > self.threshold:
                candidates.append((s, "SHORT", abs(r1 + r2)))
            elif r1 < -self.threshold and r2 < -self.threshold:
                candidates.append((s, "LONG", abs(r1 + r2)))
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
