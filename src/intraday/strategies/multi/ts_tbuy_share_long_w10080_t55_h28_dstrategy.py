"""is_739_ts_tbuy_share_long_w10080_t55_h28d — taker-buy volume fraction long."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "raw", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_tbuy_share_long_w10080_t55_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_tbuy_share_long_w10080_t55_h28d.md"]


class TsTbuyShareLongW10080T55H28DStrategy:
    def __init__(self, symbols, window=10080, imb_threshold=0.55,
                 rebalance_bars=240, hold_bars=40320, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window)); self.imb_threshold = float(imb_threshold)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._buy_sum = {s: deque(maxlen=self.window) for s in self.symbols}
        self._tot_sum = {s: deque(maxlen=self.window) for s in self.symbols}
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
            v = d.get("volume"); imb = d.get("volume_imbalance")
            if v is None or imb is None: continue
            v = float(v); imb = float(imb)
            if v <= 0: continue
            buy = v * (imb + 1) / 2  # imbalance in [-1, +1] → buy share
            self._buy_sum[s].append(buy); self._tot_sum[s].append(v)
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
                if len(self._buy_sum[s]) < self.window: continue
                total = sum(self._tot_sum[s])
                if total <= 0: continue
                share = sum(self._buy_sum[s]) / total
                cs = self._side(state, s)
                if cs is None and share > self.imb_threshold:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
