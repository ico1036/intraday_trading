"""is_619_xs_revert_rank_l21d_k2_r1d — cross-section past-21d reversal rank, long bottom-2 / short top-2."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "xs_revert_rank_l21d_k2_r1d",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_revert_rank.md"]


class XsRevertRankL21dK2R1dStrategy:
    def __init__(self, symbols, lookback_bars=30240, rebalance_bars=1440,
                 top_k=2, max_weight=0.2, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback + 1) for s in self.symbols}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def _close_order(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is not None and float(c) > 0: self._closes[s].append(float(c))
        self._bar += 1
        if self._bar % self.rebalance_bars != 0: return None

        rets = {}
        for s in self.symbols:
            if len(self._closes[s]) < self.lookback + 1: continue
            start = self._closes[s][0]; end = self._closes[s][-1]
            if start <= 0 or end <= 0: continue
            r = math.log(end / start)
            if math.isfinite(r): rets[s] = r

        if len(rets) < 2 * self.top_k: return None
        ranked = sorted(rets.items(), key=lambda kv: kv[1])
        # REVERSAL: long the bottom (losers), short the top (winners)
        longs = [s for s, _ in ranked[:self.top_k]]
        shorts = [s for s, _ in ranked[-self.top_k:]]
        active = {**{s: "LONG" for s in longs}, **{s: "SHORT" for s in shorts}}

        per_w = min(self.max_weight, 1.0 / (2 * self.top_k))
        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); tgt = active.get(s)
            if tgt == "LONG":
                if cs != "LONG":
                    if cs == "SHORT":
                        orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET); any_change = True
                    else:
                        orders[s] = Order(side=Side.BUY, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change = True
            elif tgt == "SHORT":
                if cs != "SHORT":
                    if cs == "LONG":
                        orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET); any_change = True
                    else:
                        orders[s] = Order(side=Side.SELL, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change = True
            else:
                if cs is not None:
                    o = self._close_order(cs)
                    if o is not None:
                        orders[s] = o; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
