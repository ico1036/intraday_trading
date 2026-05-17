"""is_530_ts_vol_spike_long_w1440_zs30_h21d — volume-spike long, hold 21d."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "z_score", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_vol_spike_long_w1440_zs30_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_vol_spike_long_w1440_zs30_h21d.md"]


class TsVolSpikeLongW1440Zs30H21DStrategy:
    def __init__(self, symbols, vol_window=1440, vol_zscore=3.0,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.vol_window = max(60, int(vol_window))
        self.vol_zscore = float(vol_zscore)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._vols = {s: deque(maxlen=self.vol_window) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.vol_window) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _push(self, s, v):
        vs = self._vols[s]
        if len(vs) == vs.maxlen:
            old = vs[0]; self._sum[s] -= old; self._sumsq[s] -= old*old
        vs.append(v); self._sum[s] += v; self._sumsq[s] += v*v

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            v = d.get("volume"); c = d.get("close")
            if v is None or c is None: continue
            v = float(v); c = float(c)
            if v > 0:
                self._push(s, math.log(v))
            self._closes[s].append(c)
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
                n = len(self._vols[s])
                if n < self.vol_window: continue
                m = self._sum[s]/n; var = self._sumsq[s]/n - m*m
                if var <= 0: continue
                sd = math.sqrt(var)
                latest = self._vols[s][-1]
                z = (latest - m) / sd
                cs = self._side(state, s)
                if cs is not None: continue
                if z > self.vol_zscore:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
