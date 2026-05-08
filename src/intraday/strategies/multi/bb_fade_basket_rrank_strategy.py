"""BB band fade basket rolling_rank."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeBasketRrankStrategy:
    def __init__(self, symbols, lookback=120, k=1.5, history_size=30, rank_thr=0.6, max_weight=0.13, **_):
        self.symbols = [s.upper() for s in symbols]
        self.lookback = max(20, int(lookback))
        self.k = float(k)
        self.history_size = max(10, int(history_size))
        self.rank_thr = float(rank_thr)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.symbols}
        self._zhist = {s: deque(maxlen=self.history_size) for s in self.symbols}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        orders = {s: None for s in self.symbols}
        for s in self.symbols:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            cl = float(cl)
            cs = self._closes[s]
            if len(cs) < self.lookback // 2:
                cs.append(cl); continue
            m = mean(cs); sd = pstdev(cs) or 1e-9
            z = (cl - m) / sd
            cs.append(cl)
            tgt = None; mag = 0.0
            if z >= self.k: tgt = "SHORT"; mag = z
            elif z <= -self.k: tgt = "LONG"; mag = -z
            if tgt is None: continue
            hist = list(self._zhist[s])
            self._zhist[s].append(mag)
            if len(hist) >= 5:
                sorted_h = sorted(hist)
                rank = sum(1 for h in sorted_h if h <= mag) / len(sorted_h)
                if rank < self.rank_thr: continue
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
