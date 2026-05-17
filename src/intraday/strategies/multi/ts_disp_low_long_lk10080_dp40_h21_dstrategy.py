"""is_970_ts_disp_low_long_lk10080_dp40_h21d — low-dispersion long basket."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "z_score", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_disp_low_long_lk10080_dp40_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_disp_low_long_lk10080_dp40_h21d.md"]


class TsDispLowLongLk10080Dp40H21DStrategy:
    def __init__(self, symbols, lookback=10080, disp_pct=0.4,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(2, int(lookback)); self.disp_pct = float(disp_pct)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback+1) for s in self.symbols}
        self._disp_hist: deque[float] = deque(maxlen=43200)
        self._open_at: dict[str, int] = {}
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
        # Track dispersion of basket returns
        rets = []
        for s in self.symbols:
            cl = self._closes[s]
            if len(cl) >= self.lookback+1 and cl[0]>0:
                rets.append(math.log(cl[-1]/cl[0]))
        if len(rets) >= 2:
            mean = sum(rets)/len(rets)
            disp = math.sqrt(sum((r-mean)**2 for r in rets)/len(rets))
            self._disp_hist.append(disp)
        orders, any_change = {}, False
        for s in self.symbols:
            cs = self._side(state, s); opened = self._open_at.get(s)
            if cs == "LONG" and opened is not None and self._bar_count - opened >= self.hold_bars:
                orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                self._open_at.pop(s, None); any_change = True
        if self._bar_count % self.rebalance_bars == 0:
            if len(self._disp_hist) < 43200: return PortfolioOrder(orders=orders) if any_change else None
            cur_disp = self._disp_hist[-1]
            below = sum(1 for x in self._disp_hist if x < cur_disp) / len(self._disp_hist)
            if below < self.disp_pct:
                # Low-dispersion regime: long all symbols not in position
                cands = [s for s in self.symbols if self._side(state, s) is None]
                n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
                for s in cands:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                    self._open_at[s] = self._bar_count; any_change = True
        return PortfolioOrder(orders=orders) if any_change else None
