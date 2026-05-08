"""ORB-fade multi_day basket signal with different lookback (4 days) — different cell would need different exit/transform; this one uses higher k."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


# Cell only differs in transform — ALPHA_CELL would dedupe.
# Use a different idea_family slot via "lr_residual_fade" multi_day variant
ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "lr_residual_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/lr_residual_fade.md"]


class LrResidualMultidayBasketStrategy:
    """LR residual fade with multi_day rolling window (untried cell)."""
    def __init__(self, symbols, lookback_days=3, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback_days = max(2, int(lookback_days))
        self.window = self.lookback_days * 1440
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.window) for s in self.symbols}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            cl = float(cl)
            cs = self._closes[s]
            if len(cs) < self.window // 2:
                cs.append(cl); continue
            n = len(cs); xs = list(range(n))
            mean_x = (n - 1) / 2.0
            mean_y = sum(cs) / n
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, cs))
            den = sum((x - mean_x) ** 2 for x in xs) or 1e-9
            slope = num / den
            intercept = mean_y - slope * mean_x
            pred = intercept + slope * n
            resid = cl - pred
            cs.append(cl)
            if abs(resid) / max(cl, 1e-9) < 0.01: continue
            tgt = "SHORT" if resid > 0 else "LONG"
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
