"""ORB-fade basket signal_flip with pctile=0.70 stricter (different from is_055 PASS)."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "neutral_zone",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class OrbFadeBasketFullSignalPct70Strategy:
    """Session_extreme variant with neutral_zone exit (untried cell)."""
    def __init__(self, symbols, neutral_band=0.4, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.neutral_band = float(neutral_band)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hi = {s: None for s in self.symbols}
        self._lo = {s: None for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            self._hi[s] = None; self._lo[s] = None

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._reset()
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is None or lo is None or cl is None: continue
            self._hi[s] = hi if self._hi[s] is None else max(self._hi[s], float(hi))
            self._lo[s] = lo if self._lo[s] is None else min(self._lo[s], float(lo))
            sw = max(self._hi[s] - self._lo[s], 1e-9)
            mid = (self._hi[s] + self._lo[s]) / 2
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and abs(cl - mid) <= self.neutral_band * sw:
                orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                  quantity=0.0, order_type=OrderType.MARKET)
                continue
            tgt = None
            if cl >= self._hi[s]: tgt = "SHORT"
            elif cl <= self._lo[s]: tgt = "LONG"
            if tgt is None: continue
            if cur is None:
                if tgt == "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                else:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not has_entry: return None
        return PortfolioOrder(orders=orders)
