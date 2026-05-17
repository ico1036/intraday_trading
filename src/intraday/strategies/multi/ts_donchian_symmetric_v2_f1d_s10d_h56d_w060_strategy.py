"""ts_donchian_symmetric_v2_f1d_s10d_h56d_w060 — symmetric Donchian persist (long upper + short lower), tuned position sizing."""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "time_stop",
    "idea_family": "ts_donchian_symmetric_v2_f1d_s10d_h56d_w060",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_donchian_symmetric.md"]


class TsDonchianSymmetricV2F1dS10dH56dW060Strategy:
    def __init__(self, symbols, fast_channel_bars=1440, slow_channel_bars=14400,
                 rebalance_bars=240, hold_bars=80640, max_weight=0.06, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.fast = max(2, int(fast_channel_bars))
        self.slow = max(self.fast + 1, int(slow_channel_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._fh = {s: deque(maxlen=self.fast) for s in self.symbols}
        self._fl = {s: deque(maxlen=self.fast) for s in self.symbols}
        self._sh = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._sl = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.slow) for s in self.symbols}
        self._regime = {s: 0 for s in self.symbols}
        self._has_traded = {s: False for s in self.symbols}
        self._open_at = {}
        self._bar = 0

    def _side(self, state, s):
        if not state.positions: return None
        info = state.positions.get(s)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            h, l, c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            self._fh[s].append(float(h)); self._fl[s].append(float(l))
            self._sh[s].append(float(h)); self._sl[s].append(float(l))
            self._closes[s].append(float(c))
        self._bar += 1

        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs is not None and opened is not None and self._bar - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL if cs == "LONG" else Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True

        if self._bar % self.rebalance_bars == 0:
            cands_long, cands_short = [], []
            for s in self.symbols:
                if len(self._fh[s]) < self.fast or len(self._sh[s]) < self.slow: continue
                if not self._closes[s]: continue
                fhi = max(self._fh[s]); flo = min(self._fl[s])
                shi = max(self._sh[s]); slo = min(self._sl[s])
                close = self._closes[s][-1]
                if not all(map(math.isfinite, [fhi, flo, shi, slo, close])): continue
                prev_reg = self._regime[s]
                if close >= shi: self._regime[s] = +1
                elif close <= slo: self._regime[s] = -1
                if self._regime[s] != prev_reg: self._has_traded[s] = False
                cs = self._side(state, s); reg = self._regime[s]
                if cs is None and reg > 0 and ((close >= fhi) or self._has_traded[s]):
                    cands_long.append(s)
                elif cs is None and reg < 0 and ((close <= flo) or self._has_traded[s]):
                    cands_short.append(s)
            n = len(cands_long) + len(cands_short)
            w = min(self.max_weight, 1.0 / n) if n > 0 else 0.0
            for s in cands_long:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; self._has_traded[s] = True; any_change = True
            for s in cands_short:
                if s in orders and orders[s] is not None: continue
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar; self._has_traded[s] = True; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
