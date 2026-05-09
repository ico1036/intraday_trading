"""is_039_ts_donchian_weekly_3day_hold — Donchian breakout variant."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_donchian_weekly_3day_hold",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_donchian_weekly_3day_hold.md"]


class TsDonchianWeekly3dayHoldStrategy:
    def __init__(self, symbols, channel_bars=10080, rebalance_bars=240, hold_bars=4320, max_weight=0.14, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.channel_bars = max(2, int(channel_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = {s: deque(maxlen=self.channel_bars) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.channel_bars) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.channel_bars) for s in self.symbols}
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
            self._highs[s].append(float(h)); self._lows[s].append(float(l)); self._closes[s].append(float(c))
        self._bar_count += 1
        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            opened = self._open_at.get(s)
            if cs is not None and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True
        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                if len(self._highs[s]) < self.channel_bars or not self._closes[s]: continue
                hi, lo, close = max(self._highs[s]), min(self._lows[s]), self._closes[s][-1]
                if not (math.isfinite(hi) and math.isfinite(lo) and math.isfinite(close)): continue
                cs = self._side(state, s)
                if close >= hi and cs != "LONG": cands.append((s, "LONG"))
                elif close <= lo and cs != "SHORT": cands.append((s, "SHORT"))
            n = len(cands); w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s, dir_ in cands:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY if dir_ == "LONG" else Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
