"""is_950_xs_accel_topk_s14_l56_k2_r7d — basket-relative accel long top-K."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "rolling_rank", "horizon": "multi_day",
    "universe": "basket_topk", "exit": "signal_flip",
    "idea_family": "xs_accel_topk_s14_l56_k2_r7d",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_accel_topk_s14_l56_k2_r7d.md"]


class XsAccelTopkS14L56K2R7dStrategy:
    def __init__(self, symbols, short_w=20160, long_w=80640, top_k=2,
                 rebalance_bars=10080, max_weight=0.2, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.short = max(60, int(short_w)); self.long = max(self.short+1, int(long_w))
        self.top_k = int(top_k)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.long+1) for s in self.symbols}
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
        if self._bar_count % self.rebalance_bars != 0: return None
        accels = {}
        for s in self.symbols:
            cl = self._closes[s]
            if len(cl) < self.long+1: continue
            if cl[0]<=0 or cl[-self.short]<=0: continue
            sr = math.log(cl[-1]/cl[-self.short]) / self.short
            lr = math.log(cl[-1]/cl[0]) / self.long
            accels[s] = sr - lr
        if len(accels) < 2*self.top_k: return None
        ranked = sorted(accels.keys(), key=lambda s: accels[s])
        longs = set(ranked[-self.top_k:])
        n = self.top_k
        w = min(self.max_weight, 1.0/n) if n>0 else 0.0
        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s)
            if s in longs:
                if cs != "LONG":
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                    any_change = True
            else:
                if cs is not None:
                    orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
