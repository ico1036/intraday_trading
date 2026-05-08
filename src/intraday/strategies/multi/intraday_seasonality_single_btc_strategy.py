"""Intraday seasonality single BTC fade."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "intraday_seasonality",
}
SOURCE_NOTES: list[str] = ["research/notes/intraday_seasonality.md"]


class IntradaySeasonalitySingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", lookback_days=10, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols: raise ValueError(f"{self.target}")
        self.lookback_days = max(2, int(lookback_days))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._hourly_returns = defaultdict(list)
        self._last_close = None
        self._last_hour_close = None
        self._current_hour = None

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        d = state.panel.get(self.target)
        if not d or d.get("close") is None: return None
        cl = float(d["close"])
        ts = state.timestamp
        h = ts.hour
        if self._current_hour is not None and h != self._current_hour:
            if self._last_hour_close and self._last_close:
                ret = (self._last_close - self._last_hour_close) / max(self._last_hour_close, 1e-9)
                arr = self._hourly_returns[self._current_hour]
                arr.append(ret)
                if len(arr) > self.lookback_days: arr.pop(0)
            self._last_hour_close = self._last_close or cl
            self._current_hour = h
        elif self._current_hour is None:
            self._current_hour = h
            self._last_hour_close = cl
        self._last_close = cl
        arr = self._hourly_returns.get(h, [])
        if len(arr) < 3: return None
        avg = sum(arr) / len(arr)
        if abs(avg) < 0.001: return None
        tgt = "SHORT" if avg > 0 else "LONG"
        cur = self._current_side(state)
        orders = {s: None for s in self.symbols}
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
