"""Intraday seasonality fade — fade close vs session-open during specific UTC hours."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "intraday_seasonality",
}
SOURCE_NOTES: list[str] = ["research/notes/intraday_seasonality.md"]


class IntradaySeasonalityFadeStrategy:
    def __init__(self, symbols, trade_start_hour=12, trade_end_hour=22, threshold_pct=0.005, max_weight=0.13, **_):
        # Trade only during US session (12-22 UTC); fade close-vs-open
        self.symbols = [s.upper() for s in symbols]
        self.trade_start_hour = int(trade_start_hour)
        self.trade_end_hour = int(trade_end_hour)
        self.threshold_pct = float(threshold_pct)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._sess_open = {s: None for s in self.symbols}
        self._current_day = None

    def _reset(self):
        for s in self.symbols:
            self._sess_open[s] = None

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_for_side(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp; day = ts.toordinal(); h = ts.hour
        if self._current_day is None or day != self._current_day:
            self._current_day = day; self._reset()
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and self._sess_open[s] is None:
                self._sess_open[s] = float(cl)

        orders = {s: None for s in self.symbols}
        if h < self.trade_start_hour or h >= self.trade_end_hour:
            # outside trading window — flatten
            for s in self.symbols:
                cur = self._current_side(state, s); o = self._close_for_side(cur)
                if o: orders[s] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None

        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); so = self._sess_open.get(s)
            if cl is None or so is None or so <= 0: continue
            stretch = (cl - so) / so
            cur = self._current_side(state, s)
            if stretch > self.threshold_pct and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif stretch < -self.threshold_pct and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
