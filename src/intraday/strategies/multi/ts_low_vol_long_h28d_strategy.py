"""is_403_ts_low_vol_long_h28d — long-only entry when realized vol is below median, 28d hold.

Different signal source from Donchian breakout: enter when 5-day realized vol
drops below trailing 30-day median (calm regime). Same long-only + 28d hold +
small weight (DD<12%) structure that produced ensemble winners.
"""
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
    "idea_family": "ts_low_vol_long_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_low_vol_long_h28d.md"]


class TsLowVolLongH28dStrategy:
    def __init__(
        self,
        symbols: list[str],
        vol_window_bars: int = 7200,        # 5d
        norm_window_bars: int = 43200,      # 30d
        rebalance_bars: int = 240,
        hold_bars: int = 40320,             # 28d
        max_weight: float = 0.035,
        vol_pct_threshold: float = 0.50,    # only enter when current vol < median (0.5 percentile)
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols")
        if norm_window_bars <= vol_window_bars:
            raise ValueError("norm_window must exceed vol_window")
        self.symbols = [s.upper() for s in symbols]
        self.vol_window = max(60, int(vol_window_bars))
        self.norm_window = max(self.vol_window + 1, int(norm_window_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.vol_pct_threshold = float(vol_pct_threshold)

        self._rets = {s: deque(maxlen=self.vol_window) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._last_close = {s: None for s in self.symbols}
        self._vol_hist = {s: deque(maxlen=self.norm_window) for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _push_ret(self, s, r):
        rs = self._rets[s]
        if len(rs) == rs.maxlen:
            old = rs[0]
            self._sum[s] -= old
            self._sumsq[s] -= old * old
        rs.append(r)
        self._sum[s] += r
        self._sumsq[s] += r * r

    def _realized_vol(self, s):
        n = len(self._rets[s])
        if n < self.vol_window: return None
        mean = self._sum[s] / n
        var = self._sumsq[s] / n - mean * mean
        if var <= 0 or not math.isfinite(var): return None
        return math.sqrt(var)

    def _vol_percentile(self, s, cur_vol):
        h = self._vol_hist[s]
        if len(h) < self.norm_window: return None
        below = sum(1 for v in h if v < cur_vol)
        return below / len(h)

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s); return None if not info else (info.get("side") if info.get("side") in {"LONG", "SHORT"} else None)

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            c = d.get("close")
            if c is None or float(c) <= 0: continue
            cv = float(c)
            if self._last_close[s] is not None and self._last_close[s] > 0:
                r = math.log(cv / self._last_close[s])
                if math.isfinite(r): self._push_ret(s, r)
            self._last_close[s] = cv
            # Update vol history when we have full vol_window
            v = self._realized_vol(s)
            if v is not None:
                vh = self._vol_hist[s]
                if len(vh) == vh.maxlen: vh.popleft()
                vh.append(v)
        self._bar_count += 1

        orders, any_change = {}, False
        # Time-stop
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        # Entry: low vol regime
        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                v = self._realized_vol(s)
                if v is None: continue
                pct = self._vol_percentile(s, v)
                if pct is None: continue
                cs = self._side(state, s)
                if cs is not None: continue
                if pct < self.vol_pct_threshold:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s in cands:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
