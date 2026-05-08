"""ORB-fade basket_topk trailing exit."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "trailing",
    "idea_family": "orb_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/orb_fade.md"]


class OrbFadeBasketTopkTrailingStrategy:
    def __init__(self, symbols, or_minutes=60, top_k=2, trail_pct=0.005, max_weight=0.20, rebalance_bars=30, **_):
        self.symbols = [s.upper() for s in symbols]
        self.or_minutes = max(5, int(or_minutes))
        self.top_k = max(1, int(top_k))
        self.trail_pct = float(trail_pct)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self._or_high = {s: None for s in self.symbols}
        self._or_low = {s: None for s in self.symbols}
        self._best_favorable = {s: None for s in self.symbols}
        self._current_day = None
        self._bar_count = 0

    def _reset(self):
        for s in self.symbols:
            self._or_high[s] = None; self._or_low[s] = None

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal(); m = ts.hour * 60 + ts.minute
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._reset()
        if m < self.or_minutes:
            for s in self.symbols:
                d = state.panel.get(s)
                if not d: continue
                hi = d.get("high"); lo = d.get("low"); cl = d.get("close")
                if hi is None and cl is not None: hi = cl
                if lo is None and cl is not None: lo = cl
                if hi is None or lo is None: continue
                ch = self._or_high[s]; cl_ = self._or_low[s]
                self._or_high[s] = hi if ch is None else max(ch, float(hi))
                self._or_low[s] = lo if cl_ is None else min(cl_, float(lo))
            return None

        orders = {s: None for s in self.symbols}
        # Trailing exit logic for each open position
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            cur = self._current_side(state, s)
            if cur == "LONG":
                bf = self._best_favorable.get(s)
                if bf is None or cl > bf:
                    self._best_favorable[s] = cl
                trigger = self._best_favorable[s] * (1.0 - self.trail_pct)
                if cl < trigger:
                    orders[s] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                    self._best_favorable[s] = None
                continue
            if cur == "SHORT":
                bf = self._best_favorable.get(s)
                if bf is None or cl < bf:
                    self._best_favorable[s] = cl
                trigger = self._best_favorable[s] * (1.0 + self.trail_pct)
                if cl > trigger:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    self._best_favorable[s] = None
                continue

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        ranked = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = self._or_high.get(s); lo = self._or_low.get(s)
            if cl is None or hi is None or lo is None: continue
            or_w = max(hi - lo, 1e-9)
            if cl > hi:
                ranked.append((s, (cl - hi) / or_w, "SHORT"))
            elif cl < lo:
                ranked.append((s, (lo - cl) / or_w, "LONG"))
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        target = {sym: side for sym, _, side in ranked[: self.top_k]}

        for s in self.symbols:
            cur = self._current_side(state, s)
            tgt = target.get(s)
            if cur is not None: continue  # let trailing manage exits
            if tgt == "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                d = state.panel.get(s)
                if d and d.get("close") is not None:
                    self._best_favorable[s] = float(d["close"])
            elif tgt == "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                d = state.panel.get(s)
                if d and d.get("close") is not None:
                    self._best_favorable[s] = float(d["close"])

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
