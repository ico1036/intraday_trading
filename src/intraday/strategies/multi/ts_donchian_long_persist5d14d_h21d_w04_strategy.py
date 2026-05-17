"""is_162_ts_donchian_long_persist_5d14d_h21d_w04 — long-only persist Donchian, very long hold."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_donchian_long_persist_5d14d_h21d_w04",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_donchian_long_persist_5d14d_h21d_w04.md"]


class TsDonchianLongPersist5d14dH21dW04Strategy:
    def __init__(self, symbols, fast_channel_bars=7200, slow_channel_bars=20160,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.04, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.fast = max(2, int(fast_channel_bars))
        self.slow = max(self.fast + 1, int(slow_channel_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._fast_h = {s: deque(maxlen=self.fast) for s in self.symbols}
        self._slow_h = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._slow_l = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._regime = {s: 0 for s in self.symbols}
        self._has_traded = {s: False for s in self.symbols}
        self._open_at = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG", "SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h, l, c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            self._fast_h[s].append(float(h))
            self._slow_h[s].append(float(h)); self._slow_l[s].append(float(l))
            self._closes[s].append(float(c))
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                if len(self._fast_h[s]) < self.fast: continue
                if len(self._slow_h[s]) < self.slow: continue
                if not self._closes[s]: continue
                fhi = max(self._fast_h[s])
                shi = max(self._slow_h[s]); slo = min(self._slow_l[s])
                close = self._closes[s][-1]
                if not all(map(math.isfinite, [fhi, shi, slo, close])): continue
                prev_reg = self._regime[s]
                if close >= shi: self._regime[s] = +1
                elif close <= slo: self._regime[s] = -1
                if self._regime[s] != prev_reg:
                    self._has_traded[s] = False
                cs = self._side(state, s); reg = self._regime[s]
                if cs is None and reg > 0:
                    if (close >= fhi) or self._has_traded[s]:
                        cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s in cands:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                self._has_traded[s] = True
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
