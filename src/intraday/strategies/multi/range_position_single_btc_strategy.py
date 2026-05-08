"""Range position fade single BTC."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "range_position_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/range_position.md"]


class RangePositionSingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", edge_thr=0.85, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols: raise ValueError(self.target)
        self.edge_thr = float(edge_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hi = None; self._lo = None
        self._day = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._hi = None; self._lo = None
        d = state.panel.get(self.target)
        if not d: return None
        cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
        if cl is None: return None
        cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
        self._hi = hi if self._hi is None else max(self._hi, hi)
        self._lo = lo if self._lo is None else min(self._lo, lo)
        sw = max(self._hi - self._lo, 1e-9)
        pos = (cl - self._lo) / sw
        tgt = None
        if pos >= self.edge_thr: tgt = "SHORT"
        elif pos <= 1 - self.edge_thr: tgt = "LONG"
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
