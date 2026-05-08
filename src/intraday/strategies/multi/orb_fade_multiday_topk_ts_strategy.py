"""ORB-fade multi_day topk time_stop."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "multi_day",
    "universe": "basket_topk",
    "exit": "time_stop",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeMultidayTopkTsStrategy:
    def __init__(self, symbols, top_k=3, or_minutes=30, lookback_days=3, max_weight=0.25, hold_bars=180, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.or_minutes = max(5, int(or_minutes))
        self.lookback_days = max(2, int(lookback_days))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.hold_bars = max(10, int(hold_bars))
        self._or_high_today = {s: None for s in self.symbols}
        self._or_low_today = {s: None for s in self.symbols}
        self._past_or = {s: deque(maxlen=self.lookback_days) for s in self.symbols}
        self._day = None
        self._entry_bar = {s: None for s in self.symbols}
        self._bar_count = 0

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
        self._bar_count += 1
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
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and self._entry_bar[s] is not None:
                if self._bar_count - self._entry_bar[s] >= self.hold_bars:
                    orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                      quantity=0.0, order_type=OrderType.MARKET)
                    self._entry_bar[s] = None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            past = list(self._past_or[s])
            if not past or self._or_high_today[s] is None: continue
            all_highs = [h for h, _ in past] + [self._or_high_today[s]]
            all_lows = [l for _, l in past] + [self._or_low_today[s]]
            multi_hi = max(all_highs); multi_lo = min(all_lows)
            mw = max(multi_hi - multi_lo, 1e-9)
            mag = 0.0; tgt = None
            if cl > multi_hi: mag = (cl - multi_hi) / mw + 0.001; tgt = "SHORT"
            elif cl < multi_lo: mag = (multi_lo - cl) / mw + 0.001; tgt = "LONG"
            if tgt is None: continue
            candidates.append((s, tgt, mag))
        if candidates:
            candidates.sort(key=lambda x: -x[2])
            for s, tgt, _ in candidates[: self.top_k]:
                if orders.get(s) is not None: continue
                cur = self._current_side(state, s)
                if cur is None:
                    if tgt == "SHORT":
                        orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                        self._entry_bar[s] = self._bar_count
                    else:
                        orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                        self._entry_bar[s] = self._bar_count
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
