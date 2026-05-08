"""Donchian fade topk time_stop."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "time_stop",
    "idea_family": "donchian_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/donchian_fade.md"]


class DonchianFadeTopkTsStrategy:
    def __init__(self, symbols, top_k=3, lookback=240, max_weight=0.25, hold_bars=180, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.lookback = max(60, int(lookback))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.hold_bars = max(10, int(hold_bars))
        self._highs = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.lookback) for s in self.symbols}
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
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and self._entry_bar[s] is not None:
                if self._bar_count - self._entry_bar[s] >= self.hold_bars:
                    orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                      quantity=0.0, order_type=OrderType.MARKET)
                    self._entry_bar[s] = None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
            self._highs[s].append(hi); self._lows[s].append(lo)
            if len(self._highs[s]) < self.lookback // 2: continue
            ch = max(self._highs[s]); cl_ = min(self._lows[s])
            cw = max(ch - cl_, 1e-9)
            mag = 0.0; tgt = None
            if cl >= ch: mag = (cl - ch) / cw + 0.001; tgt = "SHORT"
            elif cl <= cl_: mag = (cl_ - cl) / cw + 0.001; tgt = "LONG"
            if tgt is None: continue
            candidates.append((s, tgt, mag))
        if candidates:
            candidates.sort(key=lambda x: -x[2])
            for s, tgt, _ in candidates[: self.top_k]:
                if orders.get(s) is not None: continue
                cur = self._current_side(state, s)
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
