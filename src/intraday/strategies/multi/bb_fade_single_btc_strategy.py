"""BB band fade session single BTC raw."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "single",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeSingleBtcStrategy:
    def __init__(self, symbols, target="BTCUSDT", lookback=120, k=1.5, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.lookback = max(20, int(lookback))
        self.k = float(k)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = deque(maxlen=self.lookback)

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        d = state.panel.get(self.target)
        if not d: return None
        cl = d.get("close")
        if cl is None: return None
        cl = float(cl)
        if len(self._closes) < self.lookback // 2:
            self._closes.append(cl); return None
        m = mean(self._closes); sd = pstdev(self._closes) or 1e-9
        upper = m + self.k * sd; lower = m - self.k * sd
        self._closes.append(cl)
        orders = {s: None for s in self.symbols}
        cur = self._current_side(state)
        tgt = None
        if cl >= upper: tgt = "SHORT"
        elif cl <= lower: tgt = "LONG"
        if tgt is None: return None
        if tgt == "SHORT" and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif tgt == "LONG" and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
