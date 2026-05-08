"""LR residual fade pair z_score."""
from __future__ import annotations

from collections import deque
from statistics import pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "pair",
    "exit": "signal_flip",
    "idea_family": "lr_residual_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/lr_residual_fade.md"]


class LrResidualPairZscoreStrategy:
    def __init__(self, symbols, pair=("BTCUSDT", "ETHUSDT"), lookback=120, history_size=30, entry_z=0.7,
                 max_weight=0.4, **_):
        self.symbols = [s.upper() for s in symbols]
        self.pair = tuple(p.upper() for p in pair)
        for p in self.pair:
            if p not in self.symbols: raise ValueError(p)
        self.lookback = max(20, int(lookback))
        self.history_size = max(10, int(history_size))
        self.entry_z = float(entry_z)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.pair}
        self._mag_hist = {s: deque(maxlen=self.history_size) for s in self.pair}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        orders = {s: None for s in self.symbols}
        for s in self.pair:
            d = state.panel.get(s)
            if not d: continue
            cl = d.get("close")
            if cl is None: continue
            cl = float(cl)
            cs = self._closes[s]
            if len(cs) < self.lookback // 2:
                cs.append(cl); continue
            n = len(cs); xs = list(range(n))
            mean_x = (n - 1) / 2.0
            mean_y = sum(cs) / n
            num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, cs))
            den = sum((x - mean_x) ** 2 for x in xs) or 1e-9
            slope = num / den
            intercept = mean_y - slope * mean_x
            pred = intercept + slope * n
            resid = cl - pred
            cs.append(cl)
            self._mag_hist[s].append(abs(resid))
            if len(self._mag_hist[s]) < 5: continue
            sd = pstdev(self._mag_hist[s]) or 1e-9
            z = abs(resid) / sd
            if z < self.entry_z: continue
            tgt = "SHORT" if resid > 0 else "LONG"
            cur = self._current_side(state, s)
            if tgt == "SHORT" and cur != "SHORT":
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
            elif tgt == "LONG" and cur != "LONG":
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        return PortfolioOrder(orders=orders)
