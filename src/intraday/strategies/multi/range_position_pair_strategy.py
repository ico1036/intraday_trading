"""Range position fade pair."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "pair",
    "exit": "signal_flip",
    "idea_family": "range_position_xs",
}
SOURCE_NOTES: list[str] = ["research/notes/range_position.md"]


class RangePositionPairStrategy:
    def __init__(self, symbols, pair=("BTCUSDT", "ETHUSDT"), edge_thr=0.8, max_weight=0.4, **_):
        self.symbols = [s.upper() for s in symbols]
        self.pair = tuple(p.upper() for p in pair)
        for p in self.pair:
            if p not in self.symbols: raise ValueError(p)
        self.edge_thr = float(edge_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hi = {s: None for s in self.pair}
        self._lo = {s: None for s in self.pair}
        self._day = None

    def _reset(self):
        for s in self.pair:
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
        for s in self.pair:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
            self._hi[s] = hi if self._hi[s] is None else max(self._hi[s], hi)
            self._lo[s] = lo if self._lo[s] is None else min(self._lo[s], lo)
            sw = max(self._hi[s] - self._lo[s], 1e-9)
            pos = (cl - self._lo[s]) / sw
            tgt = None
            if pos >= self.edge_thr: tgt = "SHORT"
            elif pos <= 1 - self.edge_thr: tgt = "LONG"
            if tgt is None: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
