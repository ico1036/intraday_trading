"""Session extreme revert multi_day basket time_stop."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SextMultidayBasketTsStrategy:
    def __init__(self, symbols, lookback_days=3, max_weight=0.13, hold_bars=180, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback_days = max(2, int(lookback_days))
        self.window = self.lookback_days * 1440
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.hold_bars = max(10, int(hold_bars))
        self._highs = {s: deque(maxlen=self.window) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.window) for s in self.symbols}
        self._entry_bar = {s: None for s in self.symbols}
        self._bar_count = 0

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        self._bar_count += 1
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
            self._highs[s].append(hi); self._lows[s].append(lo)
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and self._entry_bar[s] is not None:
                if self._bar_count - self._entry_bar[s] >= self.hold_bars:
                    orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                      quantity=0.0, order_type=OrderType.MARKET)
                    self._entry_bar[s] = None
                    continue
            if len(self._highs[s]) < self.window // 2: continue
            roll_hi = max(self._highs[s])
            roll_lo = min(self._lows[s])
            tgt = None
            if cl >= roll_hi: tgt = "SHORT"
            elif cl <= roll_lo: tgt = "LONG"
            if tgt is None: continue
            if cur is None:
                if tgt == "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                    self._entry_bar[s] = self._bar_count
                else:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                    self._entry_bar[s] = self._bar_count
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
