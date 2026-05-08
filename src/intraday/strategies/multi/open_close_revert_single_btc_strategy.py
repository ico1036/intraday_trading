"""Open-close revert single BTC."""
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
    "idea_family": "open_close_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/open_close_revert.md"]


class OpenCloseRevertSingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", lookback=240, threshold_pct=0.020, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.lookback = max(10, int(lookback))
        self.threshold_pct = float(threshold_pct)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = deque(maxlen=self.lookback + 5)

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        d = state.panel.get(self.target)
        if d:
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes.append(float(cl))
        if len(self._closes) < self.lookback + 1: return None
        old = self._closes[-self.lookback - 1]; cur_close = self._closes[-1]
        if old <= 0: return None
        ret = (cur_close - old) / old
        cur = self._current_side(state)
        orders = {s: None for s in self.symbols}
        if ret > self.threshold_pct and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif ret < -self.threshold_pct and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
