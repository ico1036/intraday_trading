"""Intraday seasonality topk fade (use hour-of-day average return)."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "intraday_seasonality",
}
SOURCE_NOTES: list[str] = ["research/notes/intraday_seasonality.md"]


class IntradaySeasonalityTopkStrategy:
    def __init__(self, symbols, top_k=3, lookback_days=10, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.lookback_days = max(2, int(lookback_days))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        # hourly returns per symbol per hour: list of recent returns
        self._hourly_returns = defaultdict(lambda: defaultdict(list))
        self._last_close = {s: None for s in self.symbols}
        self._last_hour_close = {s: None for s in self.symbols}
        self._current_hour = None

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        h = ts.hour
        # update on hour change
        if self._current_hour is not None and h != self._current_hour:
            for s in self.symbols:
                last_h_cl = self._last_hour_close[s]
                cur_cl = self._last_close[s]
                if last_h_cl and cur_cl:
                    ret = (cur_cl - last_h_cl) / max(last_h_cl, 1e-9)
                    arr = self._hourly_returns[s][self._current_hour]
                    arr.append(ret)
                    if len(arr) > self.lookback_days:
                        arr.pop(0)
                self._last_hour_close[s] = cur_cl
            self._current_hour = h
        elif self._current_hour is None:
            self._current_hour = h
            for s in self.symbols:
                d = state.panel.get(s)
                if d and d.get("close") is not None:
                    self._last_hour_close[s] = float(d["close"])
        # update last_close
        for s in self.symbols:
            d = state.panel.get(s)
            if d and d.get("close") is not None:
                self._last_close[s] = float(d["close"])
        # generate signal: fade against next hour's average historical return
        candidates = []
        for s in self.symbols:
            arr = self._hourly_returns[s].get(h, [])
            if len(arr) < 3: continue
            avg = sum(arr) / len(arr)
            if abs(avg) < 0.001: continue
            tgt = "SHORT" if avg > 0 else "LONG"
            candidates.append((s, tgt, abs(avg)))
        if not candidates: return None
        candidates.sort(key=lambda x: -x[2])
        chosen = {s: t for s, t, _ in candidates[: self.top_k]}
        orders = {s: None for s in self.symbols}
        for s, tgt in chosen.items():
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
