"""Open-close revert basket — fade N-bar return extremes."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "open_close_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/open_close_revert.md"]


class OpenCloseRevertBasketStrategy:
    def __init__(self, symbols, lookback=240, threshold_pct=0.015, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(10, int(lookback))
        self.threshold_pct = float(threshold_pct)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback + 5) for s in self.symbols}

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes[s].append(float(cl))
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            c = list(self._closes[s])
            if len(c) < self.lookback + 1: continue
            old = c[-self.lookback - 1]
            cur_close = c[-1]
            if old <= 0: continue
            ret = (cur_close - old) / old
            cur = self._current_side(state, s)
            if ret > self.threshold_pct and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif ret < -self.threshold_pct and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
