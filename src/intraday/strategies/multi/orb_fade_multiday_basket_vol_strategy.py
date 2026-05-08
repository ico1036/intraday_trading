"""ORB-fade multi_day: use prior 3 sessions' OR for fade reference."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "VOLUME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeMultidayBasketVolStrategy:
    def __init__(self, symbols, or_minutes=30, lookback_days=3, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.lookback_days = max(2, int(lookback_days))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._or_high_today = {s: None for s in self.symbols}
        self._or_low_today = {s: None for s in self.symbols}
        self._past_or = {s: deque(maxlen=self.lookback_days) for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            if self._or_high_today[s] is not None and self._or_low_today[s] is not None:
                self._past_or[s].append((self._or_high_today[s], self._or_low_today[s]))
            self._or_high_today[s] = None; self._or_low_today[s] = None

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._reset(); self._day = day
        m = ts.hour * 60 + ts.minute
        if m < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                self._or_high_today[s] = hi if self._or_high_today[s] is None else max(self._or_high_today[s], float(hi))
                self._or_low_today[s] = lo if self._or_low_today[s] is None else min(self._or_low_today[s], float(lo))
            return None
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            past = list(self._past_or[s])
            if not past or self._or_high_today[s] is None: continue
            # use multi-day cumulative max/min from past ORs + today
            all_highs = [h for h, _ in past] + [self._or_high_today[s]]
            all_lows = [l for _, l in past] + [self._or_low_today[s]]
            multi_hi = max(all_highs); multi_lo = min(all_lows)
            tgt = None
            if cl > multi_hi: tgt = "SHORT"
            elif cl < multi_lo: tgt = "LONG"
            if tgt is None: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
