"""is_115_ts_zrevert_240m_120m — extreme z-score mean reversion.

For each symbol, compute log(close) − log(close[N-bar ago]) over a sliding
window. Z-score that returns vs trailing window history; when |z| > entry_z
take the opposite side (mean reversion). Time-stop after hold_bars.
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
    "idea_family": "ts_zrevert_240m_120m",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_zrevert_240m_120m.md"]


class TsZrevert240m120mStrategy:
    def __init__(self, symbols, window_bars=240, hold_bars=120,
                 rebalance_bars=60, entry_z=2.0, max_weight=0.07,
                 history_bars=2880, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.window = max(2, int(window_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.history_bars = max(60, int(history_bars))
        self._closes = {s: deque(maxlen=self.window + 1) for s in self.symbols}
        # rolling history of {window-bar log returns} for z-score
        self._ret_hist = {s: deque(maxlen=self.history_bars) for s in self.symbols}
        self._sum = {s: 0.0 for s in self.symbols}
        self._sumsq = {s: 0.0 for s in self.symbols}
        self._open_at = {}
        self._bar_count = 0

    def _push_ret(self, s, r):
        rs = self._ret_hist[s]
        if len(rs) == rs.maxlen:
            old = rs[0]; self._sum[s] -= old; self._sumsq[s] -= old * old
        rs.append(r); self._sum[s] += r; self._sumsq[s] += r * r

    def _z_for(self, s):
        rs = self._ret_hist[s]; n = len(rs)
        if n < self.history_bars: return None
        mean = self._sum[s] / n
        var = self._sumsq[s] / n - mean * mean
        if var <= 0 or not math.isfinite(var): return None
        sd = math.sqrt(var)
        # Current return = log(latest close) - log(close N bars ago)
        cs = self._closes[s]
        if len(cs) < self.window + 1: return None
        r = math.log(cs[-1] / cs[0]) if cs[0] > 0 else None
        if r is None or not math.isfinite(r): return None
        return (r - mean) / sd

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
            cs = self._closes[s]
            if len(cs) >= self.window + 1:
                # Compute new return (log price diff over window)
                if cs[0] > 0:
                    r = math.log(float(c) / cs[0])
                    if math.isfinite(r):
                        self._push_ret(s, r)
            cs.append(float(c))
        self._bar_count += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs_pos = self._side(state, s)
            opened = self._open_at.get(s)
            if cs_pos is not None and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL if cs_pos == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar_count % self.rebalance_bars == 0:
            cands = []
            for s in self.symbols:
                z = self._z_for(s)
                if z is None: continue
                cs_pos = self._side(state, s)
                if cs_pos is not None: continue  # already in position
                # MEAN REVERSION: entry on extreme z, opposite direction.
                if z > self.entry_z:
                    cands.append((s, "SHORT"))
                elif z < -self.entry_z:
                    cands.append((s, "LONG"))
            n = len(cands); w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s, dir_ in cands:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY if dir_ == "LONG" else Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
