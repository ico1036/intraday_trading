"""Session extreme revert multi_day basket trailing exit."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "trailing",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SextMdBasketTrailingStrategy:
    def __init__(self, symbols, lookback_days=3, max_weight=0.13, trail_pct=0.015, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback_days = max(2, int(lookback_days))
        self.window = self.lookback_days * 1440
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.trail_pct = float(trail_pct)
        self._highs = {s: deque(maxlen=self.window) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.window) for s in self.symbols}
        self._entry_price = {s: None for s in self.symbols}
        self._best = {s: None for s in self.symbols}
        self._side = {s: None for s in self.symbols}

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
            # Trailing exit
            if self._side[s] == "LONG":
                if self._best[s] is None or cl > self._best[s]:
                    self._best[s] = cl
                if cl <= self._best[s] * (1 - self.trail_pct):
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                    self._side[s] = None; self._entry_price[s] = None; self._best[s] = None
                    continue
            elif self._side[s] == "SHORT":
                if self._best[s] is None or cl < self._best[s]:
                    self._best[s] = cl
                if cl >= self._best[s] * (1 + self.trail_pct):
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    self._side[s] = None; self._entry_price[s] = None; self._best[s] = None
                    continue
            if len(self._highs[s]) < self.window // 2: continue
            roll_hi = max(self._highs[s])
            roll_lo = min(self._lows[s])
            tgt = None
            if cl >= roll_hi: tgt = "SHORT"
            elif cl <= roll_lo: tgt = "LONG"
            if tgt is None: continue
            if self._side[s] is None:
                if tgt == "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                else:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                self._side[s] = tgt; self._entry_price[s] = cl; self._best[s] = cl
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
