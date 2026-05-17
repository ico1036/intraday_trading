"""xs_range_fade_l14d_k2_r1d_w060 — cross-section: rank by close position in N-day range, fade extremes."""
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
    "idea_family": "xs_range_fade_l14d_k2_r1d_w060",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_range_position_fade.md"]


class XsRangeFadeL14dK2R1dW060Strategy:
    def __init__(self, symbols, lookback_bars=20160, rebalance_bars=1440,
                 top_k=2, max_weight=0.06, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG","SHORT"} else None

    def _close_order(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h,l,c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            self._highs[s].append(float(h)); self._lows[s].append(float(l)); self._closes[s].append(float(c))
        self._bar += 1
        if self._bar % self.rebalance_bars != 0: return None

        scores = {}
        for s in self.symbols:
            if len(self._highs[s]) < self.lookback: continue
            hi = max(self._highs[s]); lo = min(self._lows[s])
            if not self._closes[s]: continue
            close = self._closes[s][-1]
            rng = hi - lo
            if rng <= 0 or not math.isfinite(rng): continue
            # signal = close position; we will FADE — high pos goes short
            scores[s] = (close - (hi+lo)/2) / (rng/2)
        if len(scores) < 2*self.top_k: return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        # FADE: long bottom (oversold), short top (overbought)
        longs = [s for s,_ in ranked[:self.top_k]]
        shorts = [s for s,_ in ranked[-self.top_k:]]
        active = {**{s:"LONG" for s in longs}, **{s:"SHORT" for s in shorts}}
        per_w = min(self.max_weight, 1.0/(2*self.top_k))

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); tgt = active.get(s)
            if tgt == "LONG":
                if cs != "LONG":
                    if cs == "SHORT":
                        orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET); any_change=True
                    else:
                        orders[s] = Order(side=Side.BUY, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change=True
            elif tgt == "SHORT":
                if cs != "SHORT":
                    if cs == "LONG":
                        orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET); any_change=True
                    else:
                        orders[s] = Order(side=Side.SELL, quantity=0.0, weight=per_w, order_type=OrderType.MARKET); any_change=True
            else:
                if cs is not None:
                    o = self._close_order(cs)
                    if o is not None:
                        orders[s] = o; any_change=True
        return PortfolioOrder(orders=orders) if any_change else None
