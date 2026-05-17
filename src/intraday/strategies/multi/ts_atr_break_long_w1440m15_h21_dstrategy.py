"""is_504_ts_atr_break_long_w1440_m15_h21d — ATR-band breakout long, hold 21d."""
from __future__ import annotations
import math
from collections import deque
from typing import Any
from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME", "transform": "z_score", "horizon": "multi_day",
    "universe": "basket_full", "exit": "time_stop",
    "idea_family": "ts_atr_break_long_w1440_m15_h21d",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_atr_break_long_w1440_m15_h21d.md"]


class TsAtrBreakLongW1440m15H21DStrategy:
    def __init__(self, symbols, atr_window=1440, atr_mult=1.5, ma_window=7200,
                 rebalance_bars=240, hold_bars=30240, max_weight=0.035, **_):
        if not symbols: raise ValueError("symbols")
        self.symbols = [s.upper() for s in symbols]
        self.atr_window = max(2, int(atr_window))
        self.atr_mult = float(atr_mult)
        self.ma_window = max(2, int(ma_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._high = {s: deque(maxlen=self.ma_window) for s in self.symbols}
        self._low = {s: deque(maxlen=self.ma_window) for s in self.symbols}
        self._close = {s: deque(maxlen=self.ma_window) for s in self.symbols}
        self._tr = {s: deque(maxlen=self.atr_window) for s in self.symbols}
        self._prev_close = {s: None for s in self.symbols}
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
            h, l, c = d.get("high"), d.get("low"), d.get("close")
            if h is None or l is None or c is None: continue
            h, l, c = float(h), float(l), float(c)
            self._high[s].append(h); self._low[s].append(l); self._close[s].append(c)
            if self._prev_close[s] is not None:
                tr = max(h - l, abs(h - self._prev_close[s]), abs(l - self._prev_close[s]))
                self._tr[s].append(tr)
            self._prev_close[s] = c
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
                if len(self._close[s]) < self.ma_window or len(self._tr[s]) < self.atr_window: continue
                close = self._close[s][-1]
                ma = sum(self._close[s]) / len(self._close[s])
                atr = sum(self._tr[s]) / len(self._tr[s])
                if not all(map(math.isfinite, [close, ma, atr])) or atr <= 0: continue
                cs = self._side(state, s)
                if cs is not None: continue
                # Entry: close > ma + atr_mult * atr (vol-normalized breakout)
                if close > ma + self.atr_mult * atr:
                    cands.append(s)
            n = len(cands); w = min(self.max_weight, 1.0/n) if n>0 else 0.0
            for s in cands:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                self._open_at[s] = self._bar_count
                any_change = True

        return PortfolioOrder(orders=orders) if any_change else None
