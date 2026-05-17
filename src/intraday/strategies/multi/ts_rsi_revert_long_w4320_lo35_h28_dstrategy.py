"""is_511_ts_rsi_revert_long_w4320_lo35_h28d — RSI oversold long, hold 28d."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "rolling_rank", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_rsi_revert_long_w4320_lo35_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_rsi_revert_long_w4320_lo35_h28d.md"]


class TsRsiRevertLongW4320Lo35H28DStrategy:
    def __init__(self, symbols, rsi_window=4320, rsi_lower=35,
                 rebalance_bars=240, hold_bars=40320, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.rsi_window = max(2, int(rsi_window))
        self.rsi_lower = float(rsi_lower)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._gains = {s: deque(maxlen=self.rsi_window) for s in self.symbols}
        self._losses = {s: deque(maxlen=self.rsi_window) for s in self.symbols}
        self._prev_close = {s: None for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def _rsi(self, s):
        if len(self._gains[s]) < self.rsi_window: return None
        avg_g = sum(self._gains[s]) / len(self._gains[s])
        avg_l = sum(self._losses[s]) / len(self._losses[s])
        if avg_l <= 0: return 100.0
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            c = float(c)
            if self._prev_close[s] is not None:
                ch = c - self._prev_close[s]
                self._gains[s].append(max(0.0, ch))
                self._losses[s].append(max(0.0, -ch))
            self._prev_close[s] = c
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                r = self._rsi(s)
                if r is None: continue
                cs = self._side(state, s)
                if cs is not None: continue
                if r < self.rsi_lower:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
