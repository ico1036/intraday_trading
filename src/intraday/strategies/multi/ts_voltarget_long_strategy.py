"""is_016_ts_voltarget_long — long-only basket sized inversely to realized vol with vol-stop.

Uses incremental rolling sum / sum_sq for O(1) per-bar variance update, otherwise
the per-bar pstdev() over a 10080-deque turns the inner loop into O(N²).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "vol_stop",
    "idea_family": "ts_voltarget_long",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_voltarget_long.md"]


class TsVoltargetLongStrategy:
    def __init__(
        self,
        symbols: list[str],
        vol_window_bars: int = 10080,
        rebalance_bars: int = 10080,
        target_daily_vol: float = 0.02,
        vol_stop_multiplier: float = 2.0,
        max_weight: float = 0.14,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.vol_window_bars = max(60, int(vol_window_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.target_daily_vol = float(target_daily_vol)
        self.vol_stop_multiplier = float(vol_stop_multiplier)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        # rolling per-bar log returns + incremental sum / sum_sq for O(1) variance.
        self._returns = {s: deque(maxlen=self.vol_window_bars) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._last_close = {s: None for s in self.symbols}
        self._bar_count = 0

    def _push_return(self, s, r):
        rs = self._returns[s]
        if len(rs) == rs.maxlen:
            old = rs[0]
            self._sum[s] -= old
            self._sumsq[s] -= old * old
        rs.append(r)
        self._sum[s] += r
        self._sumsq[s] += r * r

    def _realized_daily_vol(self, s):
        rs = self._returns[s]
        n = len(rs)
        if n < self.vol_window_bars: return None
        mean = self._sum[s] / n
        var = self._sumsq[s] / n - mean * mean
        if var <= 0 or not math.isfinite(var): return None
        sigma = math.sqrt(var)
        return sigma * math.sqrt(1440)

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        v = info.get("side")
        return v if v in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            if self._last_close[s] is not None and self._last_close[s] > 0:
                self._push_return(s, math.log(float(c) / self._last_close[s]))
            self._last_close[s] = float(c)

        self._bar_count += 1
        orders, any_change = {}, False

        # Vol-stop check every bar
        for s in self.symbols:
            cs = self._side(state, s)
            if cs == "LONG":
                rv = self._realized_daily_vol(s)
                if rv is not None and rv > self.target_daily_vol * self.vol_stop_multiplier:
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                    any_change = True

        # Rebalance entries: enter LONG with vol-targeted weight when no position
        if self._bar_count % self.rebalance_bars == 0:
            sized = {}
            for s in self.symbols:
                rv = self._realized_daily_vol(s)
                if rv is None or rv <= 0: continue
                # weight ∝ target_vol / realized_vol, capped by max_weight
                raw = self.target_daily_vol / rv
                sized[s] = min(self.max_weight, raw)
            # normalize so total <= 1
            total = sum(sized.values())
            if total > 1.0:
                scale = 1.0 / total
                for s in sized:
                    sized[s] *= scale

            for s, w in sized.items():
                cs = self._side(state, s)
                if cs == "LONG":
                    continue
                if s in orders and orders[s] is not None:
                    # we just stop-closed; don't immediately re-enter
                    continue
                if w <= 0:
                    continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
