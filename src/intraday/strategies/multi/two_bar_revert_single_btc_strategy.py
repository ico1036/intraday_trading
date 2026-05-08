"""Two bar reversal fade single BTC."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "two_bar_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/two_bar_reversal_fade.md"]


class TwoBarRevertSingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", threshold=0.003, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols: raise ValueError(self.target)
        self.threshold = float(threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = deque(maxlen=3)

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        d = state.panel.get(self.target)
        if not d: return None
        cl = d.get("close")
        if cl is None: return None
        cl = float(cl)
        cs = self._closes
        if len(cs) < 2:
            cs.append(cl); return None
        r1 = (cs[-1] - cs[-2]) / max(cs[-2], 1e-9)
        r2 = (cl - cs[-1]) / max(cs[-1], 1e-9)
        cs.append(cl)
        tgt = None
        if r1 > self.threshold and r2 > self.threshold: tgt = "SHORT"
        elif r1 < -self.threshold and r2 < -self.threshold: tgt = "LONG"
        if tgt is None: return None
        cur = self._current_side(state)
        orders = {s: None for s in self.symbols}
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
