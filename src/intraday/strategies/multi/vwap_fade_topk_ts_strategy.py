"""VWAP fade topk time_stop."""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "time_stop",
    "idea_family": "vwap_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/vwap_fade.md"]


class VwapFadeTopkTsStrategy:
    def __init__(self, symbols, top_k=3, deviation_threshold=0.004, max_weight=0.25, hold_bars=180, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.deviation_threshold = float(deviation_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.hold_bars = max(10, int(hold_bars))
        self._notional_sum = {s: 0.0 for s in self.symbols}
        self._volume_sum = {s: 0.0 for s in self.symbols}
        self._day = None
        self._entry_bar = {s: None for s in self.symbols}
        self._bar_count = 0

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
        self._bar_count += 1
        ts = state.timestamp
        day = ts.toordinal()
        if self._day != day:
            self._day = day; self._reset()
        orders = {s: None for s in self.symbols}
        # close stale
        for s in self.symbols:
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and self._entry_bar[s] is not None:
                if self._bar_count - self._entry_bar[s] >= self.hold_bars:
                    orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                      quantity=0.0, order_type=OrderType.MARKET)
                    self._entry_bar[s] = None
        candidates = []
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
            mag = abs(dev)
            if mag < self.deviation_threshold: continue
            tgt = "SHORT" if dev > 0 else "LONG"
            candidates.append((s, tgt, mag))
        if candidates:
            candidates.sort(key=lambda x: -x[2])
            for s, tgt, _ in candidates[: self.top_k]:
                if orders.get(s) is not None: continue
                cur = self._current_side(state, s)
                if cur is None:
                    if tgt == "SHORT":
                        orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                        self._entry_bar[s] = self._bar_count
                    else:
                        orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                        self._entry_bar[s] = self._bar_count
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
