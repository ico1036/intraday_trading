"""ATR-band fade single BTC signal_flip session."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrFadeSingleBtcSignalFlipStrategy:
    def __init__(self, symbols, target="BTCUSDT", atr_window=1440, k=2.0, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.atr_window = max(60, int(atr_window))
        self.k = float(k)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = deque(maxlen=self.atr_window + 5)
        self._lows = deque(maxlen=self.atr_window + 5)
        self._closes = deque(maxlen=self.atr_window + 5)

    def _atr(self):
        h = list(self._highs); lo = list(self._lows); c = list(self._closes)
        if len(c) < self.atr_window + 1: return None
        trs = []
        for i in range(-self.atr_window, 0):
            tr = max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
            trs.append(tr)
        return sum(trs) / len(trs)

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        d = state.panel.get(self.target)
        if d:
            cl = d.get("close"); hi = d.get("high", cl); lo = d.get("low", cl)
            if cl is not None and hi is not None and lo is not None:
                self._closes.append(float(cl))
                self._highs.append(float(hi))
                self._lows.append(float(lo))
        orders = {s: None for s in self.symbols}
        atr = self._atr()
        if atr is None or atr <= 0: return None
        c = list(self._closes)
        if len(c) < 2: return None
        bar_move = c[-1] - c[-2]
        threshold = self.k * atr
        cur = self._current_side(state)
        if bar_move > threshold and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif bar_move < -threshold and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
