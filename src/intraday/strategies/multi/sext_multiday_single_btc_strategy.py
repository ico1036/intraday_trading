"""Session extreme revert multi_day single BTC."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SextMultidaySingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", lookback_days=3, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols: raise ValueError(self.target)
        self.lookback_days = max(2, int(lookback_days))
        self.window = self.lookback_days * 1440
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = deque(maxlen=self.window)
        self._lows = deque(maxlen=self.window)

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
        cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
        if cl is None: return None
        cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
        self._highs.append(hi); self._lows.append(lo)
        if len(self._highs) < self.window // 2: return None
        roll_hi = max(self._highs); roll_lo = min(self._lows)
        tgt = None
        if cl >= roll_hi: tgt = "SHORT"
        elif cl <= roll_lo: tgt = "LONG"
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
