"""ATR-band fade signal_flip session basket."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrFadeBasketSignalFlipStrategy:
    def __init__(self, symbols, atr_window=1440, k=2.0, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.atr_window = max(60, int(atr_window))
        self.k = float(k)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}

    def _atr(self, s):
        h = list(self._highs[s]); lo = list(self._lows[s]); c = list(self._closes[s])
        if len(c) < self.atr_window + 1: return None
        trs = []
        for i in range(-self.atr_window, 0):
            tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
            trs.append(tr)
        return sum(trs) / len(trs)

    def _current_side(self, state, symbol):
        if not state.positions: return None
        info = state.positions.get(symbol)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high", cl); lo = d.get("low", cl)
            if cl is None or hi is None or lo is None: continue
            self._closes[s].append(float(cl))
            self._highs[s].append(float(hi))
            self._lows[s].append(float(lo))
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            atr = self._atr(s)
            if atr is None or atr <= 0: continue
            c = list(self._closes[s])
            if len(c) < 2: continue
            bar_move = c[-1] - c[-2]
            threshold = self.k * atr
            cur = self._current_side(state, s)
            if bar_move > threshold and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif bar_move < -threshold and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
