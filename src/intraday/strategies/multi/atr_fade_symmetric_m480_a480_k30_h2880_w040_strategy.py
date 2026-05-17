"""atr_fade_symmetric_m480_a480_k30_h2880_w040 — ATR-channel fade symmetric (k=3.0 ATRs from EMA mean)."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "atr_fade_symmetric_m480_a480_k30_h2880_w040",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_fade_symmetric.md"]


class AtrFadeSymmetricM480A480K30H2880W040Strategy:
    def __init__(self, symbols, mean_bars=480, atr_bars=480,
                 k_atr=3.0, rebalance_bars=60,
                 hold_bars=2880, max_weight=0.04, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.mean_bars = max(20, int(mean_bars))
        self.atr_bars = max(2, int(atr_bars))
        self.k_atr = float(k_atr)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.mean_bars) for s in self.symbols}
        self._tr = {s: deque(maxlen=self.atr_bars) for s in self.symbols}
        self._prev_close = {s: None for s in self.symbols}
        self._open_at = {}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG","SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h, l, c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            h, l, c = float(h), float(l), float(c)
            pc = self._prev_close[s]
            tr = max(h-l, abs(h-pc) if pc else 0, abs(l-pc) if pc else 0)
            self._tr[s].append(tr)
            self._closes[s].append(c)
            self._prev_close[s] = c
        self._bar += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs is not None and opened is not None and self._bar - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar % self.rebalance_bars == 0:
            cands_long, cands_short = [], []
            for s in self.symbols:
                cs = self._side(state, s)
                if cs is not None: continue
                if len(self._closes[s]) < self.mean_bars: continue
                if len(self._tr[s]) < self.atr_bars: continue
                close = self._closes[s][-1]
                mean = sum(self._closes[s])/len(self._closes[s])
                atr = sum(self._tr[s])/len(self._tr[s])
                if atr <= 0 or not math.isfinite(atr): continue
                dev = (close - mean) / atr
                if dev >= self.k_atr: cands_short.append(s)
                elif dev <= -self.k_atr: cands_long.append(s)
            n = len(cands_long) + len(cands_short)
            w = min(self.max_weight, 1.0/n) if n > 0 else 0.0
            for s in cands_long:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; any_change = True
            for s in cands_short:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
