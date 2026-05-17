"""is_545_ts_vol_regime_long_vw7200_e50_h28d — low-vol regime long, hold 28d."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "rolling_rank", "horizon": "multi_day",
    "universe": "basket_full", "exit": "vol_stop",
    "idea_family": "ts_vol_regime_long_vw7200_e50_h28d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_vol_regime_long_vw7200_e50_h28d.md"]


class TsVolRegimeLongVw7200E50H28DStrategy:
    def __init__(self, symbols, vol_window=7200, norm_window=43200,
                 vol_pct_entry=0.5, vol_pct_exit=0.9,
                 rebalance_bars=240, hold_bars=40320, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.vol_window = max(60, int(vol_window))
        self.norm_window = max(self.vol_window+1, int(norm_window))
        self.vol_pct_entry = float(vol_pct_entry)
        self.vol_pct_exit = float(vol_pct_exit)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._rets = {s: deque(maxlen=self.vol_window) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._last = {s: None for s in self.symbols}
        self._vol_hist = {s: deque(maxlen=self.norm_window) for s in self.symbols}
        self._open_at: dict[str, int] = {}
        self._bar_count = 0

    def _push_r(self, s, r):
        rs = self._rets[s]
        if len(rs) == rs.maxlen:
            old = rs[0]; self._sum[s] -= old; self._sumsq[s] -= old*old
        rs.append(r); self._sum[s] += r; self._sumsq[s] += r*r

    def _vol(self, s):
        n = len(self._rets[s])
        if n < self.vol_window: return None
        m = self._sum[s]/n; var = self._sumsq[s]/n - m*m
        if var <= 0 or not math.isfinite(var): return None
        return math.sqrt(var)

    def _pct(self, s, v):
        h = self._vol_hist[s]
        if len(h) < self.norm_window: return None
        below = sum(1 for x in h if x < v)
        return below / len(h)

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
            cv = float(c)
            if self._last[s] is not None and self._last[s] > 0:
                r = math.log(cv/self._last[s])
                if math.isfinite(r): self._push_r(s, r)
            self._last[s] = cv
            v = self._vol(s)
            if v is not None:
                vh = self._vol_hist[s]
                if len(vh) == vh.maxlen: vh.popleft()
                vh.append(v)
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs != "LONG" or opened is None: continue
            # Time-stop OR vol exceeded exit threshold
            v = self._vol(s); pct = self._pct(s, v) if v else None
            time_done = self._bar_count - opened >= self.hold_bars
            vol_done = pct is not None and pct > self.vol_pct_exit
            if time_done or vol_done:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                v = self._vol(s)
                if v is None: continue
                pct = self._pct(s, v)
                if pct is None: continue
                cs = self._side(state, s)
                if cs is not None: continue
                if pct < self.vol_pct_entry:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
