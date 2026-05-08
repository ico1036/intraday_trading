"""BB band fade multi_day basket ewma_residual."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeMultidayBasketEwmaStrategy:
    def __init__(self, symbols, lookback=720, k=2.0, alpha=0.1, entry_thr=0.05, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(60, int(lookback))
        self.k = float(k)
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
            m = mean(cs); sd = pstdev(cs) or 1e-9
            z = (cl - m) / sd
            cs.append(cl)
            mag = abs(z)
            if mag < self.k: continue
            tgt = "SHORT" if z > 0 else "LONG"
            ema = self._mag_ewma[s]
            ema_new = mag if ema is None else self.alpha * mag + (1 - self.alpha) * ema
            self._mag_ewma[s] = ema_new
            if ema is not None and (mag - ema) < self.entry_thr: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
