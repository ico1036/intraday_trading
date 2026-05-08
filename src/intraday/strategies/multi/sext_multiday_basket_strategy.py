"""Session extreme revert with multi_day rolling H/L (3-day window)."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SextMultidayBasketStrategy:
    def __init__(self, symbols, lookback_days=3, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback_days = max(2, int(lookback_days))
        # 3 days = ~4320 minute bars; cache only highs/lows per minute
        self.window = self.lookback_days * 1440
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = {s: deque(maxlen=self.window) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.window) for s in self.symbols}

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
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl)
            hi = float(hi) if hi is not None else cl
            lo = float(lo) if lo is not None else cl
            self._highs[s].append(hi); self._lows[s].append(lo)
            if len(self._highs[s]) < self.window // 2: continue
            roll_hi = max(self._highs[s])
            roll_lo = min(self._lows[s])
            tgt = None
            if cl >= roll_hi: tgt = "SHORT"
            elif cl <= roll_lo: tgt = "LONG"
            if tgt is None: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
