"""Session extreme revert: BTC + ETH pair."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "pair",
    "exit": "signal_flip",
    "idea_family": "session_extreme_revert",
}
SOURCE_NOTES: list[str] = ["research/notes/session_extreme_revert.md"]


class SessionExtremePairStrategy:
    def __init__(self, symbols, pair=("BTCUSDT", "ETHUSDT"), max_weight=0.4, **_):
        self.symbols = [s.upper() for s in symbols]
        self.pair = tuple(p.upper() for p in pair)
        for p in self.pair:
            if p not in self.symbols:
                raise ValueError(f"{p} not in symbols")
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
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is None or lo is None or cl is None: continue
            ch = self._hi[s]; cl_ = self._lo[s]
            self._hi[s] = hi if ch is None else max(ch, float(hi))
            self._lo[s] = lo if cl_ is None else min(cl_, float(lo))
            sh = self._hi[s]; sl = self._lo[s]
            tgt = None
            if cl >= sh: tgt = "SHORT"
            elif cl <= sl: tgt = "LONG"
            if tgt is None: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
