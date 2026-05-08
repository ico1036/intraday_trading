"""BB-fade basket_topk time_stop rolling_rank."""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "session",
    "universe": "basket_topk",
    "exit": "time_stop",
    "idea_family": "bb_band_fade",
}
SOURCE_NOTES: list[str] = ["research/notes/bb_band_fade.md"]


class BbFadeBasketTopkTsRrankStrategy:
    def __init__(self, symbols, window=1440, top_k=2, history_size=30, rank_threshold=0.30, flat_at_minute=1410, rebalance_bars=60, max_weight=0.20, **_):
        self.symbols = [s.upper() for s in symbols]
        self.window = max(60, int(window))
        self.top_k = max(1, int(top_k))
        self.history_size = max(10, int(history_size))
        self.rank_threshold = max(0.0, min(1.0, float(rank_threshold)))
        self.flat_at_minute = int(flat_at_minute)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self._closes = {s: deque(maxlen=self.window + 5) for s in self.symbols}
        self._z_hist = {s: deque(maxlen=self.history_size) for s in self.symbols}
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
            cl = closes[-1]; z = (cl - mu) / sd; absz = abs(z)
            hist = list(self._z_hist[s])
            self._z_hist[s].append(absz)
            if len(hist) >= 5:
                rank = sum(1 for x in hist if x <= absz) / len(hist)
                if rank < (1.0 - self.rank_threshold): continue
            else:
                if absz < 1.5: continue
            side = "SHORT" if z > 0 else "LONG"
            ranked.append((s, absz, side))
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
