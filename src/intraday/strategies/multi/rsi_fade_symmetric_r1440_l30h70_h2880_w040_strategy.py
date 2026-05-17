"""rsi_fade_symmetric_r1440_l30h70_h2880_w040 — RSI extreme fade (long RSI<30, short RSI>70)."""
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
    "idea_family": "rsi_fade_symmetric_r1440_l30h70_h2880_w040",
}
SOURCE_NOTES: list[str] = ["research/notes/rsi_fade_symmetric.md"]


class RsiFadeSymmetricR1440L30h70H2880W040Strategy:
    def __init__(self, symbols, rsi_bars=1440, rebalance_bars=60,
                 low_threshold=30, high_threshold=70,
                 hold_bars=2880, max_weight=0.04, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.rsi_bars = max(2, int(rsi_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.low = float(low_threshold)
        self.high = float(high_threshold)
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.rsi_bars + 1) for s in self.symbols}
        self._open_at = {}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG","SHORT"} else None

    def _rsi(self, s):
        v = list(self._closes[s])
        if len(v) < self.rsi_bars + 1: return None
        gains = losses = 0.0
        for i in range(1, len(v)):
            d = v[i] - v[i-1]
            if d > 0: gains += d
            else: losses -= d
        if losses == 0: return 100.0
        rs = (gains/self.rsi_bars) / (losses/self.rsi_bars)
        return 100 - 100/(1+rs)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is not None and float(c) > 0:
                self._closes[s].append(float(c))
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
                r = self._rsi(s)
                if r is None: continue
                if r <= self.low: cands_long.append(s)
                elif r >= self.high: cands_short.append(s)
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
