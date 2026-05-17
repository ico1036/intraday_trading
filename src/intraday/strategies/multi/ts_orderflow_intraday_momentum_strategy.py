"""is_402_ts_orderflow_intraday_momentum — intraday orderflow momentum (not fade).

Per-symbol cumulative signed-volume over a short window (e.g. 4h). Z-score
vs trailing day. When |z| > entry_z take the SAME direction as flow
(follow, not fade). Shorter horizon than the weekly orderflow alpha.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_orderflow_intraday_momentum",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_orderflow_intraday_momentum.md"]


class TsOrderflowIntradayMomentumStrategy:
    def __init__(
        self,
        symbols: list[str],
        flow_window: int = 240,      # 4h
        norm_window: int = 2880,     # 2d
        rebalance_bars: int = 60,
        entry_z: float = 1.5,
        hold_bars: int = 480,        # 8h
        max_weight: float = 0.10,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols")
        if norm_window <= flow_window:
            raise ValueError("norm_window must exceed flow_window")
        self.symbols = [s.upper() for s in symbols]
        self.flow_window = max(2, int(flow_window))
        self.norm_window = max(self.flow_window + 1, int(norm_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        self._sv = {s: deque(maxlen=self.flow_window) for s in self.symbols}
        self._flow_hist = {s: deque(maxlen=self.norm_window) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _push_hist(self, s, val):
        h = self._flow_hist[s]
        if len(h) == h.maxlen:
            old = h[0]
            self._sum[s] -= old
            self._sumsq[s] -= old * old
        h.append(val)
        self._sum[s] += val
        self._sumsq[s] += val * val

    def _z_for(self, s):
        if len(self._sv[s]) < self.flow_window: return None
        flow = sum(self._sv[s])
        h = self._flow_hist[s]
        n = len(h)
        if n < self.norm_window: return None
        m = self._sum[s] / n
        var = self._sumsq[s] / n - m * m
        if var <= 0 or not math.isfinite(var): return None
        sd = math.sqrt(var)
        return (flow - m) / sd

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG","SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            vol = d.get("volume"); imb = d.get("volume_imbalance")
            if vol is None or imb is None: continue
            v = float(vol); i = float(imb)
            if not (math.isfinite(v) and math.isfinite(i)) or v <= 0: continue
            self._sv[s].append(i * v)
            if len(self._sv[s]) == self.flow_window:
                self._push_hist(s, sum(self._sv[s]))
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
                z = self._z_for(s)
                if z is None: continue
                cs = self._side(state, s)
                if cs is not None: continue
                # MOMENTUM: follow direction of flow
                if z > self.entry_z:
                    cands.append((s, "LONG"))
                elif z < -self.entry_z:
                    cands.append((s, "SHORT"))
            n = len(cands); w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s, dir_ in cands:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY if dir_ == "LONG" else Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
