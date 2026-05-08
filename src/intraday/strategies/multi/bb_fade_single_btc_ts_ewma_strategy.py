"""BB-fade single BTC time_stop ewma_residual."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "single",
    "exit": "time_stop",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeSingleBtcTsEwmaStrategy:
    def __init__(self, symbols, target="BTCUSDT", window=1440, k=2.0, ema_window=20, flat_at_minute=1410, rebalance_bars=60, max_weight=0.5, **_):
        self.symbols = [s.upper() for s in symbols]
        self.target = target.upper()
        if self.target not in self.symbols:
            raise ValueError(f"target {self.target} not in symbols")
        self.window = max(60, int(window)); self.k = float(k)
        self.ema_window = max(5, int(ema_window))
        self.alpha_ema = 2.0 / (self.ema_window + 1.0)
        self.flat_at_minute = int(flat_at_minute)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = deque(maxlen=self.window + 5)
        self._ema_z = 0.0
        self._bar_count = 0

    def _current_side(self, state):
        if not state.positions: return None
        info = state.positions.get(self.target)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_for_side(self, side):
        if side == "LONG": return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT": return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp; m = ts.hour * 60 + ts.minute
        d = state.panel.get(self.target)
        if d:
            cl = d.get("close")
            if cl is not None and cl > 0:
                self._closes.append(float(cl))
        orders = {s: None for s in self.symbols}
        if m >= self.flat_at_minute:
            cur = self._current_side(state); o = self._close_for_side(cur)
            if o: orders[self.target] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None
        if len(self._closes) < self.window: return None
        seg = list(self._closes)[-self.window:]
        mu = mean(seg); sd = pstdev(seg) or 1e-12
        cl = self._closes[-1]
        z = (cl - mu) / sd
        absz = abs(z)
        self._ema_z = self.alpha_ema * absz + (1 - self.alpha_ema) * self._ema_z
        residual = absz - self._ema_z
        if absz < self.k or residual <= 0: return None
        cur = self._current_side(state)
        if z > 0 and cur != "SHORT":
            orders[self.target] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        elif z < 0 and cur != "LONG":
            orders[self.target] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
