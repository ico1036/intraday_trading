"""VWAP fade basket ewma_residual."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "ewma_residual",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "vwap_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/vwap_fade.md"]


class VwapFadeBasketEwmaStrategy:
    def __init__(self, symbols, alpha=0.05, entry_thr=0.003, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.alpha = float(alpha)
        self.entry_thr = float(entry_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._notional_sum = {s: 0.0 for s in self.symbols}
        self._volume_sum = {s: 0.0 for s in self.symbols}
        self._dev_ewma = {s: None for s in self.symbols}
        self._day = None

    def _reset(self):
        for s in self.symbols:
            self._notional_sum[s] = 0.0; self._volume_sum[s] = 0.0

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._reset()
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); vol = d.get("volume", 0.0)
            if cl is None: continue
            cl = float(cl); vol = float(vol or 0.0)
            self._notional_sum[s] += cl * vol
            self._volume_sum[s] += vol
            if self._volume_sum[s] <= 0: continue
            vwap = self._notional_sum[s] / self._volume_sum[s]
            dev = (cl - vwap) / max(vwap, 1e-9)
            ema = self._dev_ewma[s]
            ema_new = dev if ema is None else self.alpha * dev + (1 - self.alpha) * ema
            self._dev_ewma[s] = ema_new
            if ema is None: continue
            resid = dev - ema
            if abs(resid) < self.entry_thr: continue
            tgt = "SHORT" if resid > 0 else "LONG"
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
