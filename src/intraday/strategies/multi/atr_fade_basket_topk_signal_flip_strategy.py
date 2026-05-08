"""ATR-band fade basket_topk signal_flip session."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "atr_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/atr_band_fade.md"]


class AtrFadeBasketTopkSignalFlipStrategy:
    def __init__(self, symbols, atr_window=1440, k=2.0, top_k=2, rebalance_bars=1, max_weight=0.20, **_):
        self.symbols = [s.upper() for s in symbols]
        self.atr_window = max(60, int(atr_window))
        self.k = float(k)
        self.top_k = max(1, int(top_k))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._highs = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}
        self._closes = {s: deque(maxlen=self.atr_window + 5) for s in self.symbols}
        self._bar_count = 0

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
            if cl is not None and hi is not None and lo is not None:
                self._closes[s].append(float(cl))
                self._highs[s].append(float(hi))
                self._lows[s].append(float(lo))
        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0: return None
        ranked = []
        for s in self.symbols:
            atr = self._atr(s)
            if atr is None or atr <= 0: continue
            c = list(self._closes[s])
            if len(c) < 2: continue
            bar_move = c[-1] - c[-2]
            threshold = self.k * atr
            if bar_move > threshold:
                ranked.append((s, bar_move / atr, "SHORT"))
            elif bar_move < -threshold:
                ranked.append((s, -bar_move / atr, "LONG"))
        ranked.sort(key=lambda kv: kv[1], reverse=True)
        target = {sym: side for sym, _, side in ranked[: self.top_k]}
        orders = {}
        for s in self.symbols:
            cur = self._current_side(state, s); tgt = target.get(s)
            if tgt == "LONG":
                orders[s] = (None if cur == "LONG" else
                    Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET))
            elif tgt == "SHORT":
                orders[s] = (None if cur == "SHORT" else
                    Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET))
            else:
                orders[s] = None
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
