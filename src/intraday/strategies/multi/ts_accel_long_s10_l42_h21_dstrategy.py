"""is_632_ts_accel_long_s10_l42_h21d — return acceleration long."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "raw", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_accel_long_s10_l42_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_accel_long_s10_l42_h21d.md"]


class TsAccelLongS10L42H21DStrategy:
    def __init__(self, symbols, short_window=14400, long_window=60480,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.short = max(60, int(short_window))
        self.long = max(self.short+1, int(long_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.long+1) for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            self._closes[s].append(float(c))
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
                cl = self._closes[s]
                if len(cl) < self.long+1: continue
                if cl[0] <= 0 or cl[-self.short] <= 0: continue
                short_ret = math.log(cl[-1]/cl[-self.short])
                long_ret = math.log(cl[-1]/cl[0])
                # acceleration: short_ret per-bar > long_ret per-bar (recent slope > average)
                accel = short_ret/self.short - long_ret/self.long
                cs = self._side(state, s)
                if cs is not None: continue
                if accel > 0:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
