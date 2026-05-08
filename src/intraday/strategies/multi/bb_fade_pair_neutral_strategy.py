"""BB band fade pair neutral_zone."""
from __future__ import annotations

from collections import deque
from statistics import pstdev, mean
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "session",
    "universe": "pair",
    "exit": "neutral_zone",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadePairNeutralStrategy:
    def __init__(self, symbols, pair=("BTCUSDT", "ETHUSDT"), lookback=120, k=1.5, neutral_band=0.3, max_weight=0.4, **_):
        self.symbols = [s.upper() for s in symbols]
        self.pair = tuple(p.upper() for p in pair)
        for p in self.pair:
            if p not in self.symbols: raise ValueError(f"{p}")
        self.lookback = max(20, int(lookback))
        self.k = float(k)
        self.neutral_band = float(neutral_band)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.lookback) for s in self.pair}

    def _current_side(self, state, sym):
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state):
        if state.panel is None: return None
        orders = {s: None for s in self.symbols}
        any_signal = False
        for s in self.pair:
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
            cur = self._current_side(state, s)
            if cur in {"LONG", "SHORT"} and abs(cl - m) <= self.neutral_band * sd:
                orders[s] = Order(side=Side.SELL if cur == "LONG" else Side.BUY,
                                  quantity=0.0, order_type=OrderType.MARKET)
                continue
            tgt = None
            if z >= self.k: tgt = "SHORT"
            elif z <= -self.k: tgt = "LONG"
            if tgt is None: continue
            if cur is None:
                any_signal = True
                if tgt == "SHORT":
                    orders[s] = Order(side=Side.SELL, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
                else:
                    orders[s] = Order(side=Side.BUY, quantity=0.0, weight=self.max_weight, order_type=OrderType.MARKET)
        active = {s: o for s, o in orders.items() if o is not None}
        if not active: return None
        has_entry = any(getattr(o, 'weight', None) for o in orders.values() if o is not None)
        if not has_entry: return None
        return PortfolioOrder(orders=orders)
