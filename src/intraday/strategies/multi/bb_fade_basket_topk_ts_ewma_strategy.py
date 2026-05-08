"""BB-fade basket_topk time_stop ewma_residual."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "time_stop",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeBasketTopkTsEwmaStrategy:
    def __init__(self, symbols, window=1440, k=2.0, top_k=2, ema_window=20, flat_at_minute=1410, rebalance_bars=60, max_weight=0.20, **_):
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window)); self.k = float(k)
        self.top_k = max(1, int(top_k))
        self.ema_window = max(5, int(ema_window))
        self.alpha_ema = 2.0 / (self.ema_window + 1.0)
        self.flat_at_minute = int(flat_at_minute)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.window + 5) for s in self.symbols}
        self._ema_z = {s: 0.0 for s in self.symbols}
        self._bar_count = 0

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
        ts = state.timestamp; m = ts.hour * 60 + ts.minute
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is not None and cl > 0: self._closes[s].append(float(cl))
        orders = {s: None for s in self.symbols}
        if m >= self.flat_at_minute:
            for s in self.symbols:
                cur = self._current_side(state, s); o = self._close_for_side(cur)
                if o: orders[s] = o
            active = {s: o for s, o in orders.items() if o is not None}
            return PortfolioOrder(orders=orders) if active else None
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None
        ranked = []
        for s in self.symbols:
            closes = list(self._closes[s])
            if len(closes) < self.window: continue
            seg = closes[-self.window:]
            mu = mean(seg); sd = pstdev(seg) or 1e-12
            cl = closes[-1]
            z = (cl - mu) / sd; absz = abs(z)
            self._ema_z[s] = self.alpha_ema * absz + (1 - self.alpha_ema) * self._ema_z[s]
            residual = absz - self._ema_z[s]
            if absz < self.k or residual <= 0: continue
            side = "SHORT" if z > 0 else "LONG"
            ranked.append((s, residual, side))
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        target = {sym: side for sym, _, side in ranked[: self.top_k]}
        for s in self.symbols:
            cur = self._current_side(state, s); tgt = target.get(s)
            if tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
