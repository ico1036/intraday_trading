"""ORB-fade multi_day single BTC."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeMultidaySingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", or_minutes=30, lookback_days=3, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols: raise ValueError(self.target)
        self.or_minutes = max(5, int(or_minutes))
        self.lookback_days = max(2, int(lookback_days))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high_today = None
        self._or_low_today = None
        self._past_or = deque(maxlen=self.lookback_days)
        self._day = None

    def _reset(self):
        if self._or_high_today is not None and self._or_low_today is not None:
            self._past_or.append((self._or_high_today, self._or_low_today))
        self._or_high_today = None; self._or_low_today = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._reset(); self._day = day
        d = state.panel.get(self.target)
        if not d: return None
        m = ts.hour * 60 + ts.minute
        if m < self.or_minutes:
            hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
            if hi is None and cl is not None: hi = cl
            if lo is None and cl is not None: lo = cl
            if hi is not None and lo is not None:
                self._or_high_today = hi if self._or_high_today is None else max(self._or_high_today, float(hi))
                self._or_low_today = lo if self._or_low_today is None else min(self._or_low_today, float(lo))
            return None
        cl = d.get("close")
        if cl is None: return None
        past = list(self._past_or)
        if not past or self._or_high_today is None: return None
        all_highs = [h for h, _ in past] + [self._or_high_today]
        all_lows = [l for _, l in past] + [self._or_low_today]
        multi_hi = max(all_highs); multi_lo = min(all_lows)
        tgt = None
        if cl > multi_hi: tgt = "SHORT"
        elif cl < multi_lo: tgt = "LONG"
        if tgt is None: return None
        cur = self._current_side(state)
        orders = {s: None for s in self.symbols}
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
