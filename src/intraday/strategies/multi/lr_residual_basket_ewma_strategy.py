"""LR residual fade basket ewma_residual."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "lr_residual_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/lr_residual_fade.md"]


class LrResidualBasketEwmaStrategy:
    def __init__(self, symbols, lookback=120, alpha=0.1, entry_thr=0.05, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(20, int(lookback))
        self.alpha = float(alpha)
        self.entry_thr = float(entry_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._mag_ewma = {s: None for s in self.symbols}

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
            if len(cs) < self.lookback // 2:
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
            mag = abs(resid)
            ema = self._mag_ewma[s]
            ema_new = mag if ema is None else self.alpha * mag + (1 - self.alpha) * ema
            self._mag_ewma[s] = ema_new
            if ema is None: continue
            diff = mag - ema
            if diff < self.entry_thr * cl: continue
            tgt = "SHORT" if resid > 0 else "LONG"
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
