"""NR4 break fade topk."""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "raw",
    "horizon": "intraday",
    "universe": "basket_topk",
    "exit": "signal_flip",
    "idea_family": "nr4_break_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/nr4_break_fade.md"]


class Nr4BreakFadeTopkStrategy:
    def __init__(self, symbols, top_k=3, lookback_bars=4, max_weight=0.25, **_):
        self.symbols = [s.upper() for s in symbols]
        self.top_k = max(1, int(top_k))
        self.lookback_bars = max(2, int(lookback_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._ranges = {s: deque(maxlen=self.lookback_bars) for s in self.symbols}
        self._highs = {s: deque(maxlen=self.lookback_bars) for s in self.symbols}
        self._lows = {s: deque(maxlen=self.lookback_bars) for s in self.symbols}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        candidates = []
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close"); hi = d.get("high"); lo = d.get("low")
            if cl is None: continue
            cl = float(cl); hi = float(hi) if hi is not None else cl; lo = float(lo) if lo is not None else cl
            ranges = list(self._ranges[s])
            highs = list(self._highs[s])
            lows = list(self._lows[s])
            self._ranges[s].append(hi - lo)
            self._highs[s].append(hi)
            self._lows[s].append(lo)
            if len(ranges) < self.lookback_bars: continue
            cur_range = hi - lo
            min_recent = min(ranges)
            if cur_range > min_recent: continue  # not narrow
            recent_high = max(highs); recent_low = min(lows)
            tgt = None; mag = 0.0
            if cl > recent_high: tgt = "SHORT"; mag = (cl - recent_high) / max(recent_high - recent_low, 1e-9)
            elif cl < recent_low: tgt = "LONG"; mag = (recent_low - cl) / max(recent_high - recent_low, 1e-9)
            if tgt is None: continue
            candidates.append((s, tgt, mag))
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
